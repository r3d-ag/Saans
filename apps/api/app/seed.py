"""Seed keyless demo data so a fresh deploy has a useful first screen."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.aqi.breakpoints import STANDARD_UNITS

from .models import Reading, Station

DEMO_STATIONS = [
    ("demo-ambala", "Ambala City", "Ambala", "Haryana", 30.378, 76.776),
    ("demo-panchkula", "Sector 6, Panchkula", "Panchkula", "Haryana", 30.694, 76.860),
    ("demo-chandigarh", "Sector 22, Chandigarh", "Chandigarh", "Chandigarh", 30.733, 76.779),
]
POLLUTANTS = ("PM2.5", "PM10", "NO2", "SO2", "CO", "O3")


def seed_demo(db: Session) -> None:
    if db.scalar(select(func.count()).select_from(Station)):
        return
    stations = [Station(station_id=s[0], name=s[1], city=s[2], state=s[3], lat=s[4], lon=s[5], source="demo") for s in DEMO_STATIONS]
    db.add_all(stations)
    db.flush()
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    rows: list[Reading] = []
    for station_index, station in enumerate(stations):
        for hour_back in range(24 * 8):
            ts = now - timedelta(hours=hour_back)
            h = ts.hour
            daily = math.sin((h - 7) * math.pi / 12)
            evening = 1.0 if 18 <= h <= 23 else 0.0
            for pollutant in POLLUTANTS:
                if pollutant == "PM2.5":
                    value = 72 + station_index * 12 + 13 * daily + 20 * evening
                elif pollutant == "PM10":
                    value = 132 + station_index * 9 + 18 * daily + 18 * evening
                elif pollutant == "NO2":
                    value = 42 + station_index * 5 + 13 * max(daily, 0)
                elif pollutant == "SO2":
                    value = 24 + station_index * 3 + 4 * daily
                elif pollutant == "CO":
                    value = 0.7 + station_index * 0.08 + 0.15 * max(daily, 0)
                else:
                    value = 34 + station_index * 4 + 17 * max(daily, 0)
                rows.append(Reading(station_id=station.station_id, pollutant=pollutant, ts_utc=ts,
                                    value_std=round(max(0.01, value), 2), unit=STANDARD_UNITS[pollutant],
                                    source="demo", qc_flag=None, imputed=False))
    db.add_all(rows)
    db.commit()
