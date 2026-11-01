"""Orchestrate idempotent source ingestion. Can run inside Actions or locally."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from sqlalchemy import select

from apps.api.app.database import Base, SessionLocal, engine
from apps.api.app.models import AQISnapshot, Forecast, Station
from apps.api.app.seed import seed_demo
from apps.api.app.services import METHOD_VERSION, current_aqi, forecast_for, iso

from .firms import ingest_firms
from .openaq import ingest_openaq
from .openmeteo import ingest_weather


def ingest_all() -> dict:
    Base.metadata.create_all(bind=engine)
    results = []
    with SessionLocal() as db:
        if not os.getenv("OPENAQ_API_KEY"):
            seed_demo(db)
        for runner in (ingest_openaq, ingest_weather, ingest_firms):
            try:
                results.append(runner(db))
            except Exception as exc:  # keep one upstream outage from blocking other sources
                results.append({"source": runner.__name__, "error": f"{type(exc).__name__}: {exc}"})
        issued = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        snapshots = 0
        forecast_rows = 0
        for station in db.scalars(select(Station).where(Station.active.is_(True))).all():
            current = current_aqi(db, station)
            if not current["valid"]:
                continue
            existing = db.scalar(select(AQISnapshot).where(AQISnapshot.station_id == station.station_id,
                                                           AQISnapshot.ts_utc == issued))
            if existing is None:
                db.add(AQISnapshot(station_id=station.station_id, ts_utc=issued, aqi=current["aqi"],
                                   category=current["category"], dominant=current["dominant_pollutant"],
                                   subindices=json.dumps(current["subindices"]), n_pollutants=current["n_pollutants"],
                                   trust=current["trust"]["score"], trust_level=current["trust"]["level"],
                                   source=current["source"], aqi_method_version=METHOD_VERSION))
                snapshots += 1
            for horizon in (24, 48):
                forecast = forecast_for(db, station, current, horizon)
                if not forecast.get("available"):
                    continue
                old = db.scalar(select(Forecast).where(Forecast.station_id == station.station_id,
                                                       Forecast.issued_at == issued,
                                                       Forecast.horizon_h == horizon))
                if old is None:
                    db.add(Forecast(station_id=station.station_id, issued_at=issued,
                                    target_ts=datetime.fromisoformat(forecast["target_ts"].replace("Z", "+00:00")),
                                    horizon_h=horizon, aqi_p10=forecast["aqi_p10"], aqi_p50=forecast["aqi_p50"],
                                    aqi_p90=forecast["aqi_p90"], category_probs=json.dumps(forecast["category_probs"]),
                                    model_version=forecast["model_version"]))
                    forecast_rows += 1
        db.commit()
        results.append({"source": "Saans processing", "aqi_snapshots": snapshots, "forecasts": forecast_rows,
                        "issued_at": iso(issued)})
    return {"sources": results}


if __name__ == "__main__":
    import json
    print(json.dumps(ingest_all(), indent=2))
