"""Shared calculation and response helpers for the API."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from statistics import NormalDist, pstdev
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.aqi.breakpoints import (
    AVERAGING_HOURS,
    METHOD_VERSION,
    MIN_HOURS_8H,
    MIN_HOURS_24H,
    STANDARD_UNITS,
)
from core.aqi.engine import compute_aqi
from core.attribution.rules import PollutionContext, attribute_causes
from core.geo.distance import Point, bearing, haversine
from core.quality.trust import agreement_score, compute_trust, freshness_score

from .models import AQISnapshot, FireEvent, Reading, Station, Weather

IST = ZoneInfo("Asia/Kolkata")
CATEGORIES = [(0, 50, "Good"), (51, 100, "Satisfactory"), (101, 200, "Moderately Polluted"),
              (201, 300, "Poor"), (301, 400, "Very Poor"), (401, 500, "Severe")]


def utc_aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def iso(value: datetime | None) -> str | None:
    return utc_aware(value).isoformat().replace("+00:00", "Z") if value else None


def station_dict(station: Station) -> dict:
    return {"id": station.station_id, "name": station.name, "city": station.city,
            "state": station.state, "lat": station.lat, "lon": station.lon, "source": station.source}


def current_aqi(db: Session, station: Station, now: datetime | None = None,
                _include_neighbours: bool = True) -> dict:
    now = now or datetime.now(timezone.utc)
    now = utc_aware(now)
    all_rows = db.scalars(select(Reading).where(Reading.station_id == station.station_id)
                          .order_by(Reading.ts_utc.desc()).limit(5000)).all()
    grouped: dict[str, list[Reading]] = {}
    rejected_flags = {"negative", "extreme_high", "invalid_number", "spike_unconfirmed", "stuck"}
    flags = 0
    total = 0
    for row in all_rows:
        ts = utc_aware(row.ts_utc)
        window = AVERAGING_HOURS.get(row.pollutant, 24)
        if now - timedelta(hours=window) < ts <= now + timedelta(minutes=5):
            total += 1
            if row.qc_flag:
                flags += 1
            if row.qc_flag in rejected_flags:
                continue
            grouped.setdefault(row.pollutant, []).append(row)
    concentrations: dict[str, float] = {}
    counts: dict[str, int] = {}
    latest: datetime | None = None
    for pollutant, records in grouped.items():
        hours = AVERAGING_HOURS[pollutant]
        minimum = MIN_HOURS_8H if hours == 8 else MIN_HOURS_24H
        unique_hours = {utc_aware(r.ts_utc).replace(minute=0, second=0, microsecond=0) for r in records}
        if len(unique_hours) < minimum:
            continue
        concentrations[pollutant] = sum(r.value_std for r in records) / len(records)
        counts[pollutant] = len(unique_hours)
        last = max(utc_aware(r.ts_utc) for r in records)
        latest = max(latest, last) if latest else last

    result = compute_aqi(concentrations)
    freshness = freshness_score(latest or now - timedelta(hours=24), now)
    completeness = (sum(min(1.0, counts.get(p, 0) / AVERAGING_HOURS[p]) for p in concentrations) /
                    len(concentrations)) if concentrations else 0.0
    quality = max(0.0, 1.0 - flags / max(1, total))
    neighbour_values: list[float] = []
    if _include_neighbours:
        neighbours = db.scalars(select(Station).where(Station.active.is_(True),
                                         Station.station_id != station.station_id)).all()
        nearest = sorted(neighbours, key=lambda item: haversine(Point(station.lat, station.lon),
                                                                 Point(item.lat, item.lon)))[:3]
        for neighbour in nearest:
            other = current_aqi(db, neighbour, now, _include_neighbours=False)
            if other["valid"]:
                neighbour_values.append(float(other["aqi"]))
    agreement = agreement_score(float(result.aqi or 0), neighbour_values) if result.valid else 0.5
    trust = compute_trust(freshness, completeness, quality, agreement)
    subindices = {name: {"value": round(item.concentration, 2), "unit": STANDARD_UNITS[name],
                         "sub_index": item.sub_index, "category": item.category, "hours": counts.get(name, 0)}
                  for name, item in result.sub_indices.items()}
    return {"station": station_dict(station), "aqi": result.aqi, "category": result.category,
            "dominant_pollutant": result.dominant_pollutant, "valid": result.valid,
            "reason": result.reason, "subindices": subindices, "n_pollutants": result.n_pollutants,
            "as_of": iso(latest), "as_of_ist": latest.astimezone(IST).isoformat() if latest else None,
            "trust": {"score": trust.score, "level": trust.level,
                      "components": {"freshness": trust.freshness, "completeness": trust.completeness,
                                     "quality": trust.quality, "agreement": trust.agreement}},
            "source": station.source, "aqi_method_version": METHOD_VERSION,
            "limitations": ["Demo data" if station.source == "demo" else "Station readings may be incomplete",
                            "AQI is a public information estimate, not medical advice"]}


def causes_for(db: Session, station: Station, current: dict) -> list[dict]:
    values = {k: v["value"] for k, v in current["subindices"].items()}
    now = datetime.now(timezone.utc)
    weather = db.scalar(select(Weather).where(Weather.station_id == station.station_id,
                                              Weather.ts_utc >= now - timedelta(hours=1),
                                              Weather.ts_utc <= now + timedelta(hours=1))
                        .order_by(Weather.ts_utc.asc()).limit(1))
    fires = db.scalars(select(FireEvent).order_by(FireEvent.acq_ts_utc.desc()).limit(1000)).all()
    fire_count = 0
    for fire in fires:
        if now - timedelta(hours=72) <= utc_aware(fire.acq_ts_utc) <= now:
            dlat = (fire.lat - station.lat) * 111.0
            dlon = (fire.lon - station.lon) * 85.0
            distance = math.hypot(dlat, dlon)
            direction = weather.wind_dir if weather else None
            source_bearing = bearing(Point(station.lat, station.lon), Point(fire.lat, fire.lon))
            angular_diff = abs((source_bearing - direction + 180) % 360 - 180) if direction is not None else 180
            if distance <= 200 and angular_diff <= 60:
                fire_count += 1
    pm25, pm10 = values.get("PM2.5", 0), values.get("PM10", 0)
    ctx = PollutionContext(pm25=pm25, pm10=pm10, no2=values.get("NO2"), co=values.get("CO"),
                           o3=values.get("O3"), dominant_pollutant=current.get("dominant_pollutant"),
                           hour_of_day=datetime.now(IST).hour,
                           wind_speed_kmh=weather.wind_speed if weather else None,
                           humidity_pct=weather.humidity if weather else None,
                           is_stubble_season=((datetime.now(IST).month == 9 and datetime.now(IST).day >= 15)
                                              or datetime.now(IST).month in (10, 11)),
                           fire_count_72h=fire_count)
    return [{"label": a.label, "confidence": a.confidence, "evidence": a.evidence,
             "note": "Heuristic attribution; signals are not proof of source."}
            for a in attribute_causes(ctx)]


def forecast_for(db: Session, station: Station, current: dict, horizon: int) -> dict:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    if not current["valid"]:
        return {"station_id": station.station_id, "issued_at": iso(now), "target_ts": iso(now + timedelta(hours=horizon)),
                "horizon_h": horizon, "available": False, "reason": current["reason"], "model_version": "baseline-persistence-v1"}
    from ml.predict import predict_trained
    trained = predict_trained(db, station, now, horizon)
    if trained:
        return {"station_id": station.station_id, "issued_at": iso(now),
                "target_ts": iso(now + timedelta(hours=horizon)), "horizon_h": horizon,
                "available": True, **trained, "source": current["source"]}
    history = db.scalars(select(AQISnapshot).where(AQISnapshot.station_id == station.station_id,
                                                  AQISnapshot.aqi.is_not(None))
                         .order_by(AQISnapshot.ts_utc.desc()).limit(168)).all()
    values = [float(x.aqi) for x in history if x.aqi is not None]
    center = float(current["aqi"])
    spread = max(18.0, pstdev(values) if len(values) > 1 else 25.0)
    # Until sufficient local history exists, explicitly use persistence as the forecast baseline.
    p50 = round(center)
    p10 = round(max(0.0, center - 1.2816 * spread))
    p90 = round(min(500.0, center + 1.2816 * spread))
    distribution = NormalDist(mu=center, sigma=spread)
    probs = {}
    for low, high, name in CATEGORIES:
        lower = 0.0 if low == 0 else low - 0.5
        upper = 500.5 if high == 500 else high + 0.5
        probs[name] = round(max(0.0, distribution.cdf(upper) - distribution.cdf(lower)), 4)
    total = sum(probs.values())
    probs = {key: round(value / total, 4) for key, value in probs.items()}
    return {"station_id": station.station_id, "issued_at": iso(now), "target_ts": iso(now + timedelta(hours=horizon)),
            "horizon_h": horizon, "available": True, "aqi_p10": p10, "aqi_p50": p50, "aqi_p90": p90,
            "category_probs": probs, "model_version": "baseline-persistence-v1",
            "reasons": ["Persistence baseline: latest CPCB-method AQI is carried forward",
                        "Band width reflects recent AQI variation; this is not a calibrated probability model"],
            "source": current["source"]}
