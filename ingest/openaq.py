"""OpenAQ v3 polling for station locations and latest sensor observations."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from statistics import median

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.app.models import Reading, Station
from core.aqi.breakpoints import STANDARD_UNITS
from core.geo.distance import Point, haversine
from core.quality.checks import check_range, check_spike, check_stuck, convert_units

BASE = "https://api.openaq.org/v3"
AMBALA = Point(30.3783, 76.7767)
POLLUTANTS = {"pm25": "PM2.5", "pm2.5": "PM2.5", "pm10": "PM10", "no2": "NO2", "so2": "SO2",
              "co": "CO", "o3": "O3", "nh3": "NH3", "pb": "Pb", "lead": "Pb"}


def iso_date(payload: dict) -> datetime | None:
    period = payload.get("period") or {}
    start = period.get("datetimeFrom") or payload.get("datetime") or {}
    raw = start.get("utc") if isinstance(start, dict) else start
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _get(client: httpx.Client, path: str, params: dict | None = None) -> dict:
    response = client.get(f"{BASE}/{path}", params=params)
    if response.status_code == 429:
        wait = int(response.headers.get("x-ratelimit-reset", "60"))
        time.sleep(min(max(wait, 1), 90))
        response = client.get(f"{BASE}/{path}", params=params)
    response.raise_for_status()
    return response.json()


def _quality_flag(db: Session, station: Station, pollutant: str, ts: datetime, value: float) -> str | None:
    recent = db.scalars(select(Reading).where(Reading.station_id == station.station_id,
                                              Reading.pollutant == pollutant,
                                              Reading.ts_utc < ts,
                                              Reading.ts_utc >= ts - timedelta(hours=24))
                         .order_by(Reading.ts_utc.desc()).limit(24)).all()
    values = [item.value_std for item in recent]
    if values and check_spike(value, median(values)):
        stations = db.scalars(select(Station).where(Station.active.is_(True),
                                         Station.station_id != station.station_id)).all()
        nearby = [item for item in stations if item.source != "demo" and
                  haversine(Point(station.lat, station.lon), Point(item.lat, item.lon)) <= 50]
        confirmed = False
        for neighbour in nearby:
            comparison = db.scalars(select(Reading).where(Reading.station_id == neighbour.station_id,
                                                          Reading.pollutant == pollutant,
                                                          Reading.ts_utc <= ts + timedelta(hours=1),
                                                          Reading.ts_utc >= ts - timedelta(hours=24))
                                    .order_by(Reading.ts_utc.desc()).limit(24)).all()
            if len(comparison) < 2:
                continue
            if abs((ts - comparison[0].ts_utc).total_seconds()) > 3 * 3600:
                continue
            baseline = median([item.value_std for item in comparison[1:]])
            if check_spike(comparison[0].value_std, baseline, threshold_factor=1.5):
                confirmed = True
                break
        if not confirmed:
            return "spike_unconfirmed"
        return "confirmed_spike"
    if len(recent) >= 5:
        consecutive = all(abs((recent[index].ts_utc - recent[index + 1].ts_utc).total_seconds() - 3600) < 60
                          for index in range(4))
        if consecutive and check_stuck([*reversed(values[:5]), value], min_consecutive=6):
            return "stuck"
    return None


def ingest_openaq(db: Session) -> dict:
    key = os.getenv("OPENAQ_API_KEY")
    if not key:
        return {"source": "OpenAQ", "skipped": True, "reason": "OPENAQ_API_KEY is not configured"}
    inserted = 0
    station_count = 0
    window_end = datetime.now(timezone.utc)
    window_start = window_end - timedelta(hours=25)
    headers = {"X-API-Key": key}
    with httpx.Client(headers=headers, timeout=25) as client:
        data = _get(client, "locations", {"bbox": "72,27,80,33", "limit": 100, "page": 1})
        candidates = []
        for location in data.get("results", []):
            coordinates = location.get("coordinates") or {}
            lat, lon = coordinates.get("latitude"), coordinates.get("longitude")
            location_id = location.get("id")
            if location_id is None or lat is None or lon is None:
                continue
            distance = haversine(AMBALA, Point(float(lat), float(lon)))
            if distance <= 100:
                candidates.append((distance, location))

        locations = [location for _, location in sorted(candidates, key=lambda item: item[0])[:30]]
        selected_ids = {str(location["id"]) for location in locations}
        # Keep the live station list focused on the Ambala area when old imports
        # or wider OpenAQ results included distant cities.
        for old_station in db.scalars(select(Station).where(Station.source == "OpenAQ")).all():
            if old_station.station_id not in selected_ids:
                old_station.active = False

        for location in locations:
            coordinates = location.get("coordinates") or {}
            lat, lon = coordinates.get("latitude"), coordinates.get("longitude")
            location_id = location.get("id")
            name = location.get("name") or f"OpenAQ station {location_id}"
            city = location.get("locality") or "Unknown"
            station = db.get(Station, str(location_id))
            if station is None:
                station = Station(station_id=str(location_id), name=name[:250], city=city[:100], state="India",
                                  lat=float(lat), lon=float(lon), source="OpenAQ")
                db.add(station)
            else:
                station.name, station.city, station.lat, station.lon = name[:250], city[:100], float(lat), float(lon)
                station.active, station.source = True, "OpenAQ"
            station_count += 1
            try:
                latest = _get(client, f"locations/{location_id}/latest", {"limit": 100}).get("results", [])
            except httpx.HTTPStatusError:
                continue

            # OpenAQ v3 /locations/{id}/latest returns sensorsId and a value;
            # the parameter and units live on the location's embedded sensors.
            sensors = {str(sensor.get("id")): sensor.get("parameter") or {}
                       for sensor in (location.get("sensors") or []) if sensor.get("id") is not None}
            freshest_by_pollutant: dict[str, tuple[datetime, str, dict]] = {}
            for item in latest:
                ts = iso_date(item)
                sensor_id = item.get("sensorsId") or item.get("sensorId")
                parameter = sensors.get(str(sensor_id)) or item.get("parameter") or {}
                pollutant = POLLUTANTS.get(str(parameter.get("name", "")).strip().lower())
                if pollutant is None or ts is None or ts < window_start:
                    continue
                previous = freshest_by_pollutant.get(pollutant)
                if previous is None or ts > previous[0]:
                    freshest_by_pollutant[pollutant] = (ts, str(sensor_id), parameter)

            for pollutant, (_, sensor_id, parameter) in freshest_by_pollutant.items():
                # Bootstrap a complete 24-hour window once, then fetch only the
                # overlap since the last stored observation on hourly runs.
                last_stored = db.scalar(select(func.max(Reading.ts_utc)).where(
                    Reading.station_id == str(location_id), Reading.pollutant == pollutant))
                start = window_start
                if last_stored is not None and last_stored.replace(tzinfo=timezone.utc) >= window_start:
                    start = max(window_start, last_stored.replace(tzinfo=timezone.utc) - timedelta(hours=2))
                params = {"datetime_from": start.isoformat().replace("+00:00", "Z"),
                          "datetime_to": window_end.isoformat().replace("+00:00", "Z"), "limit": 100}
                try:
                    measurements = _get(client, f"sensors/{sensor_id}/measurements", params).get("results", [])
                except httpx.HTTPStatusError:
                    continue
                for item in measurements:
                    ts = iso_date(item)
                    value = item.get("value")
                    if ts is None or value is None or ts < window_start or ts > window_end:
                        continue
                    measurement_parameter = item.get("parameter") or parameter
                    unit = measurement_parameter.get("units") or parameter.get("units") or ""
                    value_std = convert_units(float(value), str(unit), pollutant)
                    if value_std is None:
                        continue
                    qc_flag = check_range(value_std, pollutant) or _quality_flag(
                        db, station, pollutant, ts, value_std)
                    existing = db.scalar(select(Reading).where(Reading.station_id == str(location_id),
                                                               Reading.pollutant == pollutant,
                                                               Reading.ts_utc == ts))
                    if existing:
                        existing.value_std, existing.unit = value_std, STANDARD_UNITS[pollutant]
                        existing.source, existing.qc_flag = "OpenAQ", qc_flag
                    else:
                        db.add(Reading(station_id=str(location_id), pollutant=pollutant, ts_utc=ts,
                                       value_std=value_std, unit=STANDARD_UNITS[pollutant],
                                       source="OpenAQ", qc_flag=qc_flag, imputed=False))
                    inserted += int(existing is None)
            db.flush()
    db.commit()
    return {"source": "OpenAQ", "stations_seen": station_count, "new_readings": inserted}
