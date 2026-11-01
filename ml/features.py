"""Leakage-safe lag/calendar feature construction from persisted AQI snapshots.

Weather, fire and future neighbour features are deliberately excluded until
archived, issue-time values are available. Observations after the forecast
issue time are never inputs.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import AQISnapshot, Station

IST = ZoneInfo("Asia/Kolkata")
LAGS = (1, 3, 6, 12, 24, 48)
FEATURES = ["aqi_t0", *(f"aqi_lag_{h}" for h in LAGS), "aqi_mean_6", "aqi_max_6",
            "aqi_mean_24", "aqi_max_24", "hour_sin", "hour_cos", "weekday_sin",
            "weekday_cos", "month_sin", "month_cos", "stubble_season", "station_code"]


def make_features(history: dict[datetime, float], issue: datetime, station_code: int) -> dict[str, float] | None:
    issue = issue.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    current = history.get(issue)
    if current is None:
        return None
    lags: dict[int, float] = {}
    for lag in LAGS:
        value = history.get(issue - timedelta(hours=lag))
        if value is None:
            return None
        lags[lag] = value
    recent_6 = [history.get(issue - timedelta(hours=offset)) for offset in range(6)]
    recent_24 = [history.get(issue - timedelta(hours=offset)) for offset in range(24)]
    if any(value is None for value in recent_6 + recent_24):
        return None
    local = issue.astimezone(IST)
    hour_angle = 2 * math.pi * local.hour / 24
    weekday_angle = 2 * math.pi * local.weekday() / 7
    month_angle = 2 * math.pi * (local.month - 1) / 12
    return {"aqi_t0": current, **{f"aqi_lag_{h}": lags[h] for h in LAGS},
            "aqi_mean_6": sum(recent_6) / 6, "aqi_max_6": max(recent_6),
            "aqi_mean_24": sum(recent_24) / 24, "aqi_max_24": max(recent_24),
            "hour_sin": math.sin(hour_angle), "hour_cos": math.cos(hour_angle),
            "weekday_sin": math.sin(weekday_angle), "weekday_cos": math.cos(weekday_angle),
            "month_sin": math.sin(month_angle), "month_cos": math.cos(month_angle),
            "stubble_season": float((local.month == 9 and local.day >= 15) or local.month in (10, 11)),
            "station_code": float(station_code)}


def build_training_frame(db: Session, horizon: int) -> tuple[pd.DataFrame, dict[str, int]]:
    stations = db.scalars(select(Station).where(Station.active.is_(True)).order_by(Station.station_id)).all()
    station_codes = {station.station_id: index for index, station in enumerate(stations)}
    result: list[dict] = []
    for station in stations:
        snapshots = db.scalars(select(AQISnapshot).where(AQISnapshot.station_id == station.station_id,
                                                         AQISnapshot.aqi.is_not(None))
                               .order_by(AQISnapshot.ts_utc)).all()
        history = {snapshot.ts_utc.replace(tzinfo=timezone.utc) if snapshot.ts_utc.tzinfo is None
                   else snapshot.ts_utc.astimezone(timezone.utc): float(snapshot.aqi)
                   for snapshot in snapshots if snapshot.aqi is not None}
        for issue, current in history.items():
            features = make_features(history, issue, station_codes[station.station_id])
            target = history.get(issue + timedelta(hours=horizon))
            if features is None or target is None:
                continue
            result.append({**features, "target": target, "category": next(
                (name for low, high, name in ((0,50,"Good"),(51,100,"Satisfactory"),
                 (101,200,"Moderately Polluted"),(201,300,"Poor"),(301,400,"Very Poor"),(401,500,"Severe"))
                 if low <= target <= high), "Severe"), "issue_ts": issue, "station_id": station.station_id})
    return pd.DataFrame(result), station_codes
