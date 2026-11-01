"""Saans API and same-origin web application."""

from __future__ import annotations

import base64
import csv
import io
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from core.aqi.breakpoints import (
    CATEGORIES,
    CATEGORY_COLOURS,
    METHOD_DATA,
    METHOD_VERSION,
)
from core.geo.distance import Point, StationValue, haversine, idw_estimate

from .database import Base, SessionLocal, engine, get_db
from .models import (
    AlertLog,
    AlertSubscription,
    AQISnapshot,
    FireEvent,
    Forecast,
    ModelArtifact,
    Reading,
    Station,
)
from .seed import seed_demo
from .services import IST, causes_for, current_aqi, forecast_for, iso, station_dict, utc_aware

APP_VERSION = "1.0.0"
WEB_DIR = Path(__file__).resolve().parents[2] / "web"
LAST_INGEST: str | None = None

app = FastAPI(title="Saans AQI Monitor", version=APP_VERSION,
              description="CPCB-method air quality monitoring with source evidence and forecast baselines.")
origins = [x.strip() for x in os.getenv("ALLOWED_ORIGIN", "http://localhost:3000,http://127.0.0.1:8000").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                   allow_methods=["GET", "POST", "DELETE"], allow_headers=["Authorization", "Content-Type"])


class AlertRequest(BaseModel):
    channel: str = Field(pattern="^(telegram|webpush)$")
    destination: str = Field(min_length=4, max_length=2048)
    station_id: str
    threshold: int = Field(ge=51, le=500)


class PushRequest(BaseModel):
    endpoint: str = Field(min_length=10, max_length=2048)
    keys: dict[str, str]
    station_id: str
    threshold: int = Field(default=201, ge=51, le=500)


class ModelUpload(BaseModel):
    version: str = Field(min_length=3, max_length=80)
    bundle_base64: str = Field(min_length=100)
    evaluation: dict = Field(default_factory=dict)


@app.on_event("startup")
def startup() -> None:
    if engine.dialect.name == "postgresql":
        # Vercel can cold-start several function instances at once. Serialize DDL and
        # demo seeding so concurrent create_all() calls cannot race on PostgreSQL types.
        with engine.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(735414092)"))
            Base.metadata.create_all(bind=connection)
            if not os.getenv("OPENAQ_API_KEY"):
                with Session(bind=connection) as db:
                    seed_demo(db)
    else:
        Base.metadata.create_all(bind=engine)
        if not os.getenv("OPENAQ_API_KEY"):
            with SessionLocal() as db:
                seed_demo(db)


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    try:
        count = len(db.scalars(select(Station)).all())
        return {"status": "ok", "version": APP_VERSION, "database": "ok", "stations": count,
                "last_ingest": LAST_INGEST, "mode": "live" if os.getenv("OPENAQ_API_KEY") else "demo"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/service-worker.js", include_in_schema=False)
def service_worker() -> Response:
    return Response((WEB_DIR / "service-worker.js").read_text(encoding="utf-8"), media_type="application/javascript",
                    headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets", check_dir=False), name="assets")


@app.get("/v1/stations")
def list_stations(lat: float | None = None, lon: float | None = None,
                  radius_km: float = Query(default=100, gt=0, le=100), db: Session = Depends(get_db)) -> dict:
    stations = db.scalars(select(Station).where(Station.active.is_(True))).all()
    if (lat is None) != (lon is None):
        raise HTTPException(status_code=422, detail="lat and lon must be provided together")
    if lat is not None and (not -90 <= lat <= 90 or lon is None or not -180 <= lon <= 180):
        raise HTTPException(status_code=422, detail="Invalid coordinates")
    values = []
    for station in stations:
        distance = haversine(Point(lat, lon), Point(station.lat, station.lon)) if lat is not None and lon is not None else None
        if distance is not None and distance > radius_km:
            continue
        latest = current_aqi(db, station)
        values.append({**station_dict(station), "distance_km": round(distance, 1) if distance is not None else None,
                       "aqi": latest["aqi"], "category": latest["category"], "trust": latest["trust"],
                       "as_of": latest["as_of"], "valid": latest["valid"]})
    values.sort(key=lambda s: (s["distance_km"] is None, s["distance_km"] or 0, s["name"]))
    return {"stations": values, "count": len(values), "as_of": iso(datetime.now(timezone.utc)), "source": "Saans"}


def require_station(db: Session, station_id: str) -> Station:
    station = db.get(Station, station_id)
    if station is None or not station.active:
        raise HTTPException(status_code=404, detail="Station not found")
    return station


def add_snapshot(db: Session, station: Station, at: datetime, result: dict) -> None:
    existing = db.scalar(select(AQISnapshot).where(AQISnapshot.station_id == station.station_id,
                                                   AQISnapshot.ts_utc == at))
    if existing:
        return
    row = AQISnapshot(station_id=station.station_id, ts_utc=at, aqi=result["aqi"], category=result["category"],
                      dominant=result["dominant_pollutant"], subindices=json.dumps(result["subindices"]),
                      n_pollutants=result["n_pollutants"], trust=result["trust"]["score"],
                      trust_level=result["trust"]["level"], source=result["source"],
                      aqi_method_version=METHOD_VERSION)
    db.add(row)


@app.get("/v1/stations/{station_id}/now")
def get_now(station_id: str, db: Session = Depends(get_db)) -> dict:
    station = require_station(db, station_id)
    result = current_aqi(db, station)
    result["causes"] = causes_for(db, station, result) if result["valid"] else []
    if result["valid"]:
        add_snapshot(db, station, datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0), result)
        db.commit()
    forecasts = [forecast_for(db, station, result, horizon) for horizon in (24, 48)]
    result["forecasts"] = forecasts
    for forecast in forecasts:
        store_forecast(db, forecast)
    db.commit()
    return result


@app.get("/v1/stations/{station_id}/history")
def get_history(station_id: str, start: datetime | None = Query(default=None, alias="from"),
                end: datetime | None = Query(default=None, alias="to"), step: str = "hour",
                db: Session = Depends(get_db)) -> dict:
    station = require_station(db, station_id)
    end = utc_aware(end or datetime.now(timezone.utc))
    start = utc_aware(start or (end - timedelta(hours=48)))
    if end < start or (end - start) > timedelta(days=31):
        raise HTTPException(status_code=422, detail="Choose a valid range of at most 31 days")
    if step not in {"hour", "day"}:
        raise HTTPException(status_code=422, detail="step must be hour or day")
    existing = db.scalars(select(AQISnapshot).where(AQISnapshot.station_id == station_id,
                                                    AQISnapshot.ts_utc >= start, AQISnapshot.ts_utc <= end)
                          .order_by(AQISnapshot.ts_utc)).all()
    points = [{"ts": iso(row.ts_utc), "aqi": row.aqi, "category": row.category,
               "dominant_pollutant": row.dominant, "trust": row.trust, "trust_level": row.trust_level,
               "source": row.source} for row in existing]
    if len(points) < 2:
        # Backfill hourly values from readings to make demo history immediately useful.
        readings = db.scalars(select(Reading).where(Reading.station_id == station_id,
                                                   Reading.ts_utc >= start - timedelta(hours=24), Reading.ts_utc <= end)
                              .order_by(Reading.ts_utc)).all()
        timestamps = sorted({utc_aware(r.ts_utc).replace(minute=0, second=0, microsecond=0) for r in readings})
        seen = {point["ts"] for point in points}
        for stamp in timestamps:
            item = current_aqi(db, station, stamp + timedelta(hours=1))
            if item["valid"] and start <= stamp <= end and iso(stamp) not in seen:
                points.append({"ts": iso(stamp), "aqi": item["aqi"], "category": item["category"],
                               "dominant_pollutant": item["dominant_pollutant"], "trust": item["trust"]["score"],
                               "trust_level": item["trust"]["level"], "source": item["source"]})
                add_snapshot(db, station, stamp, item)
        db.commit()
    if step == "day":
        daily: dict[str, list[dict]] = {}
        for point in points:
            key = utc_aware(datetime.fromisoformat(point["ts"].replace("Z", "+00:00"))).astimezone(IST).date().isoformat()
            daily.setdefault(key, []).append(point)
        points = [{"ts": key, "aqi": round(sum(p["aqi"] for p in group if p["aqi"] is not None) /
                                             max(1, sum(p["aqi"] is not None for p in group))),
                   "category": group[-1]["category"], "trust_level": group[-1]["trust_level"]}
                  for key, group in daily.items()]
    return {"station": station_dict(station), "points": points, "count": len(points),
            "from": iso(start), "to": iso(end), "step": step, "timezone": "UTC (displayed in Asia/Kolkata)"}


@app.get("/v1/stations/{station_id}/forecast")
def get_forecast(station_id: str, db: Session = Depends(get_db)) -> dict:
    station = require_station(db, station_id)
    current = current_aqi(db, station)
    return {"station": station_dict(station), "forecasts": [forecast_for(db, station, current, h) for h in (24, 48)],
            "baseline": "persistence", "note": "Forecast bands are indicative until calibrated against held-out data."}


def store_forecast(db: Session, value: dict) -> None:
    if not value.get("available"):
        return
    issued_at = datetime.fromisoformat(value["issued_at"].replace("Z", "+00:00"))
    existing = db.scalar(select(Forecast).where(Forecast.station_id == value["station_id"],
                                                Forecast.issued_at == issued_at,
                                                Forecast.horizon_h == value["horizon_h"]))
    fields = {"target_ts": datetime.fromisoformat(value["target_ts"].replace("Z", "+00:00")),
              "aqi_p10": value["aqi_p10"], "aqi_p50": value["aqi_p50"], "aqi_p90": value["aqi_p90"],
              "category_probs": json.dumps(value["category_probs"]), "model_version": value["model_version"]}
    if existing:
        for key, item in fields.items():
            setattr(existing, key, item)
    else:
        db.add(Forecast(station_id=value["station_id"], issued_at=issued_at,
                        horizon_h=value["horizon_h"], **fields))


@app.get("/v1/report-card")
def report_card(station: str, days: int = Query(default=7, ge=1, le=31), db: Session = Depends(get_db)) -> dict:
    require_station(db, station)
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(Forecast).where(Forecast.station_id == station,
                                              Forecast.target_ts <= now,
                                              Forecast.issued_at >= now - timedelta(days=days + 3))
                      .order_by(Forecast.target_ts.desc()).limit(500)).all()
    actuals = db.scalars(select(AQISnapshot).where(AQISnapshot.station_id == station,
                                                   AQISnapshot.ts_utc >= now - timedelta(days=days + 1),
                                                   AQISnapshot.aqi.is_not(None))).all()
    actual_by_hour = {utc_aware(row.ts_utc).replace(minute=0, second=0, microsecond=0): row for row in actuals}
    comparisons = []
    for row in rows:
        target = utc_aware(row.target_ts).replace(minute=0, second=0, microsecond=0)
        actual = actual_by_hour.get(target)
        if actual and actual.aqi is not None:
            comparisons.append({"issued_at": iso(row.issued_at), "target_ts": iso(row.target_ts),
                                "horizon_h": row.horizon_h, "forecast_aqi": row.aqi_p50,
                                "actual_aqi": actual.aqi, "absolute_error": abs(row.aqi_p50 - actual.aqi),
                                "model_version": row.model_version})
    mae = sum(item["absolute_error"] for item in comparisons) / len(comparisons) if comparisons else None
    return {"station_id": station, "days": days, "comparisons": comparisons,
            "mae": round(mae, 2) if mae is not None else None,
            "note": "Only forecasts with a matching persisted AQI snapshot are compared."}


@app.get("/v1/estimate")
def estimate(lat: float = Query(ge=-90, le=90), lon: float = Query(ge=-180, le=180),
             db: Session = Depends(get_db)) -> dict:
    stations = db.scalars(select(Station).where(Station.active.is_(True))).all()
    points: list[StationValue] = []
    for station in stations:
        item = current_aqi(db, station)
        if item["valid"]:
            points.append(StationValue(Point(station.lat, station.lon), float(item["aqi"]), station.station_id))
    value, used = idw_estimate(Point(lat, lon), points, max_distance_km=100)
    return {"aqi_estimate": value, "label": "Estimated from nearby stations", "stations": [
        {"station_id": sid, "distance_km": round(distance, 2)} for sid, distance in used],
        "warning": "Spatial estimate is not a station measurement."}


@app.get("/v1/fires")
def get_fires(hours: int = Query(default=72, ge=1, le=168), west: float = 72, south: float = 27,
              east: float = 80, north: float = 33, db: Session = Depends(get_db)) -> dict:
    if (west >= east or south >= north or east - west > 20 or north - south > 15
            or not -180 <= west <= 180 or not -180 <= east <= 180
            or not -90 <= south <= 90 or not -90 <= north <= 90):
        raise HTTPException(status_code=422, detail="Invalid bounding box")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = db.scalars(select(FireEvent).where(FireEvent.acq_ts_utc >= cutoff,
                                              FireEvent.lon >= west, FireEvent.lon <= east,
                                              FireEvent.lat >= south, FireEvent.lat <= north)
                      .order_by(FireEvent.acq_ts_utc.desc()).limit(5000)).all()
    return {"fires": [{"lat": x.lat, "lon": x.lon, "time": iso(x.acq_ts_utc), "frp": x.frp,
                        "confidence": x.confidence, "satellite": x.satellite} for x in rows],
            "count": len(rows), "hours": hours, "source": "NASA FIRMS" if rows else "No FIRMS data loaded"}


@app.get("/v1/export.csv")
def export_csv(station: str, start: datetime = Query(alias="from"), end: datetime = Query(alias="to"),
               db: Session = Depends(get_db)) -> Response:
    require_station(db, station)
    start, end = utc_aware(start), utc_aware(end)
    if end < start or end - start > timedelta(days=31):
        raise HTTPException(status_code=422, detail="Choose a valid range of at most 31 days")
    rows = db.scalars(select(Reading).where(Reading.station_id == station, Reading.ts_utc >= start,
                                             Reading.ts_utc <= end).order_by(Reading.ts_utc)
                      .limit(50000)).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["station_id", "timestamp_utc", "pollutant", "value", "unit", "source", "quality_flag"])
    for row in rows:
        writer.writerow([row.station_id, iso(row.ts_utc), row.pollutant, row.value_std, row.unit, row.source, row.qc_flag or ""])
    return Response(output.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="saans-{station}.csv"'})


@app.get("/v1/method")
def method() -> dict:
    return {"method_version": METHOD_VERSION, "standard": "CPCB National AQI (2014)",
            "formula": "Ip = Ilo + (Cp - BPlo) * (Ihi - Ilo) / (BPhi - BPlo)",
            "validity": {"minimum_pollutants": 3, "requires_one_of": ["PM2.5", "PM10"],
                         "minimum_hours_24h": 16, "minimum_hours_8h": 6,
                         "note": "6 of 8 hourly values for 8-hour pollutants is a documented project choice."},
            "breakpoints": METHOD_DATA["pollutants"],
            "categories": [{"min": lo, "max": hi, "name": name, "colour": CATEGORY_COLOURS[name]}
                           for lo, hi, name in CATEGORIES],
            "sources": [{"name": "OpenAQ", "url": "https://openaq.org", "note": "Attribution and source-specific reuse terms apply."},
                        {"name": "Open-Meteo", "url": "https://open-meteo.com", "note": "CC BY 4.0 attribution; free API is non-commercial."},
                        {"name": "NASA FIRMS", "url": "https://firms.modaps.eosdis.nasa.gov", "note": "Fire detections are incomplete snapshots, not proof of source."}],
            "disclaimer": "Saans is an educational information project, not medical advice."}


@app.get("/v1/config")
def public_config() -> dict:
    return {"vapid_public_key": os.getenv("VAPID_PUBLIC_KEY"), "webpush_available": bool(os.getenv("VAPID_PUBLIC_KEY")),
            "mode": "live" if os.getenv("OPENAQ_API_KEY") else "demo"}


@app.post("/v1/subscriptions", status_code=201)
def create_subscription(body: AlertRequest, db: Session = Depends(get_db)) -> dict:
    station = require_station(db, body.station_id)
    if body.channel == "webpush":
        raise HTTPException(status_code=422, detail="Use /v1/push-subscriptions for browser push subscriptions")
    item = AlertSubscription(channel=body.channel, destination=body.destination,
                             station_id=station.station_id, threshold=body.threshold,
                             created_at=datetime.now(timezone.utc))
    db.add(item)
    db.commit()
    return {"id": item.id, "channel": item.channel, "station_id": item.station_id,
            "threshold": item.threshold, "active": item.active,
            "message": "Telegram alerts will be sent after the user starts the Saans bot."}


@app.post("/v1/push-subscriptions", status_code=201)
def save_push(body: PushRequest, db: Session = Depends(get_db)) -> dict:
    require_station(db, body.station_id)
    if not body.keys.get("p256dh") or not body.keys.get("auth"):
        raise HTTPException(status_code=422, detail="Push subscription is missing encryption keys")
    from .models import PushSubscription
    item = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if item is None:
        item = PushSubscription(endpoint=body.endpoint, p256dh=body.keys["p256dh"], auth=body.keys["auth"],
                                station_id=body.station_id, threshold=body.threshold,
                                created_at=datetime.now(timezone.utc))
        db.add(item)
    else:
        item.p256dh, item.auth, item.station_id, item.threshold = body.keys["p256dh"], body.keys["auth"], body.station_id, body.threshold
    db.commit()
    alert = db.scalar(select(AlertSubscription).where(AlertSubscription.channel == "webpush",
                                                       AlertSubscription.destination == body.endpoint))
    if alert is None:
        db.add(AlertSubscription(channel="webpush", destination=body.endpoint, station_id=body.station_id,
                                 threshold=body.threshold, created_at=datetime.now(timezone.utc)))
    else:
        alert.station_id, alert.threshold, alert.active = body.station_id, body.threshold, True
    db.commit()
    return {"id": item.id, "active": True}


@app.delete("/v1/push-subscriptions")
def delete_push(endpoint: str, db: Session = Depends(get_db)) -> dict:
    from .models import PushSubscription
    item = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if item:
        db.delete(item)
        alert = db.scalar(select(AlertSubscription).where(AlertSubscription.channel == "webpush",
                                                           AlertSubscription.destination == endpoint))
        if alert:
            db.delete(alert)
        db.commit()
    return {"deleted": True}


def check_internal(token: str | None) -> None:
    expected = os.getenv("INGEST_TOKEN")
    if not expected or not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing service token")


@app.post("/internal/ingest")
def run_ingest(authorization: Annotated[str | None, Header()] = None) -> dict:
    global LAST_INGEST
    check_internal(authorization.removeprefix("Bearer ") if authorization else None)
    from ingest.run import ingest_all
    summary = ingest_all()
    LAST_INGEST = iso(datetime.now(timezone.utc))
    return {"status": "ok", "completed_at": LAST_INGEST, **summary}


@app.post("/internal/models", status_code=201)
def upload_model(body: ModelUpload, authorization: Annotated[str | None, Header()] = None,
                 db: Session = Depends(get_db)) -> dict:
    check_internal(authorization.removeprefix("Bearer ") if authorization else None)
    try:
        payload = base64.b64decode(body.bundle_base64, validate=True)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Model bundle is not valid base64") from exc
    if len(payload) > 25_000_000:
        raise HTTPException(status_code=413, detail="Model bundle must be smaller than 25 MB")
    artifact = db.scalar(select(ModelArtifact).where(ModelArtifact.version == body.version))
    if artifact:
        artifact.payload, artifact.evaluation = payload, json.dumps(body.evaluation)
        artifact.trained_at = datetime.now(timezone.utc)
    else:
        db.add(ModelArtifact(version=body.version, payload=payload, evaluation=json.dumps(body.evaluation),
                             trained_at=datetime.now(timezone.utc)))
    db.commit()
    return {"saved": True, "version": body.version, "bytes": len(payload)}


@app.post("/internal/alerts/run")
def run_alerts(authorization: Annotated[str | None, Header()] = None,
               db: Session = Depends(get_db)) -> dict:
    check_internal(authorization.removeprefix("Bearer ") if authorization else None)
    sent = 0
    now_utc = datetime.now(timezone.utc)
    now_local = now_utc.astimezone(IST)
    if 22 <= now_local.hour or now_local.hour < 7:
        return {"sent": 0, "reason": "quiet hours"}
    subscriptions = db.scalars(select(AlertSubscription).where(AlertSubscription.active.is_(True))).all()
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    for subscription in subscriptions:
        station = require_station(db, subscription.station_id)
        recent = db.scalar(select(AlertLog).where(AlertLog.subscription_id == subscription.id,
                                                   AlertLog.sent_at >= now_utc - timedelta(hours=6)))
        if recent:
            continue
        latest = current_aqi(db, station)
        forecast = forecast_for(db, station, latest, 12)
        if not latest["valid"] or (latest["aqi"] < subscription.threshold and
                                    probability_at_or_above(forecast.get("category_probs", {}), subscription.threshold) < 0.6):
            continue
        if subscription.channel == "telegram" and token:
            import httpx
            message = (f"Saans alert · {station.name}: AQI {latest['aqi']} ({latest['category']}). "
                       f"Threshold {subscription.threshold}. Updated {now_local:%H:%M} IST. Likely source labels are indicative.")
            response = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                  json={"chat_id": subscription.destination, "text": message}, timeout=15)
            response.raise_for_status()
            db.add(AlertLog(subscription_id=subscription.id, sent_at=now_utc, reason=message))
            sent += 1
        elif subscription.channel == "webpush":
            from .models import PushSubscription
            push = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == subscription.destination))
            if not push or not os.getenv("VAPID_PRIVATE_KEY"):
                continue
            try:
                from pywebpush import webpush
                payload = json.dumps({"title": f"Saans · {station.city}",
                                      "body": f"AQI {latest['aqi']} · {latest['category']}. Threshold {subscription.threshold}+.",
                                      "url": "/"})
                webpush(subscription_info={"endpoint": push.endpoint,
                                           "keys": {"p256dh": push.p256dh, "auth": push.auth}},
                        data=payload, vapid_private_key=os.getenv("VAPID_PRIVATE_KEY"),
                        vapid_claims={"sub": os.getenv("VAPID_SUBJECT", "mailto:admin@example.com")})
                db.add(AlertLog(subscription_id=subscription.id, sent_at=now_utc, reason=payload))
                sent += 1
            except Exception as exc:
                if "410" in str(exc) or "404" in str(exc):
                    db.delete(push)
    db.commit()
    return {"sent": sent}


def category_for_threshold(threshold: int) -> str:
    for low, high, name in CATEGORIES:
        if low <= threshold <= high:
            return name
    return "Severe"


def probability_at_or_above(probabilities: dict[str, float], threshold: int) -> float:
    lower_bounds = {"Good": 0, "Satisfactory": 51, "Moderately Polluted": 101,
                    "Poor": 201, "Very Poor": 301, "Severe": 401}
    return sum(prob for category, prob in probabilities.items() if lower_bounds.get(category, 0) >= threshold)
