"""OpenAQ v3 polling for station locations and latest sensor observations."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from statistics import median

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import Reading, Station
from core.aqi.breakpoints import STANDARD_UNITS
from core.geo.distance import Point, haversine
from core.quality.checks import check_range, check_spike, check_stuck, convert_units

BASE = "https://api.openaq.org/v3"
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
    headers = {"X-API-Key": key}
    with httpx.Client(headers=headers, timeout=25) as client:
        data = _get(client, "locations", {"bbox": "72,27,80,33", "limit": 100, "page": 1})
        locations = data.get("results", [])
        for location in locations[:30]:
            coordinates = location.get("coordinates") or {}
            lat, lon = coordinates.get("latitude"), coordinates.get("longitude")
            location_id = location.get("id")
            if location_id is None or lat is None or lon is None:
                continue
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
            for item in latest:
                parameter = item.get("parameter") or {}
                pollutant = POLLUTANTS.get(str(parameter.get("name", "")).strip().lower())
                ts = iso_date(item)
                value = item.get("value")
                unit = parameter.get("units") or item.get("unit") or ""
                if pollutant is None or ts is None or value is None:
                    continue
                value_std = convert_units(float(value), str(unit), pollutant)
                if value_std is None:
                    continue
                qc_flag = check_range(value_std, pollutant) or _quality_flag(db, station, pollutant, ts, value_std)
                existing = db.scalar(select(Reading).where(Reading.station_id == str(location_id),
                                                           Reading.pollutant == pollutant, Reading.ts_utc == ts))
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
