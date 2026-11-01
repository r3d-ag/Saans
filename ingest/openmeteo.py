"""Fetch weather forecasts for the configured monitoring stations."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import Station, Weather


def ingest_weather(db: Session) -> dict:
    stations = db.scalars(select(Station).where(Station.active.is_(True)).limit(40)).all()
    saved = 0
    with httpx.Client(timeout=30) as client:
        for station in stations:
            response = client.get("https://api.open-meteo.com/v1/forecast", params={
                "latitude": station.lat, "longitude": station.lon,
                "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,surface_pressure,precipitation",
                "forecast_days": 3, "timezone": "UTC"})
            response.raise_for_status()
            hourly = response.json().get("hourly", {})
            times = hourly.get("time", [])
            series = [hourly.get(key, []) for key in ("temperature_2m", "relative_humidity_2m", "wind_speed_10m",
                                                       "wind_direction_10m", "surface_pressure", "precipitation")]
            for i, stamp in enumerate(times):
                ts = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
                vals = [values[i] if i < len(values) else None for values in series]
                existing = db.scalar(select(Weather).where(Weather.station_id == station.station_id,
                                                            Weather.ts_utc == ts))
                if existing:
                    existing.temp, existing.humidity, existing.wind_speed, existing.wind_dir, existing.pressure, existing.rain = vals
                else:
                    db.add(Weather(station_id=station.station_id, ts_utc=ts, temp=vals[0], humidity=vals[1],
                                   wind_speed=vals[2], wind_dir=vals[3], pressure=vals[4], rain=vals[5]))
                saved += 1
            db.flush()
    db.commit()
    return {"source": "Open-Meteo", "station_hours_upserted": saved}
