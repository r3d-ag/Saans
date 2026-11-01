"""Download recent NASA FIRMS VIIRS NOAA-20/NOAA-21 active-fire detections."""

from __future__ import annotations

import csv
import io
import os
from datetime import datetime, timezone

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from apps.api.app.models import FireEvent


def ingest_firms(db: Session) -> dict:
    key = os.getenv("FIRMS_MAP_KEY")
    if not key:
        return {"source": "NASA FIRMS", "skipped": True, "reason": "FIRMS_MAP_KEY is not configured"}
    products = ("VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT")
    frames: list[tuple[str, str]] = []
    with httpx.Client(timeout=30) as client:
        for product in products:
            url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{product}/72,27,80,33/3"
            response = client.get(url)
            response.raise_for_status()
            frames.append((product, response.text))
    rows: list[dict] = []
    for product, payload in frames:
        for item in csv.DictReader(io.StringIO(payload)):
            try:
                day = str(item["acq_date"])
                hour = str(item["acq_time"]).zfill(4)
                ts = datetime.strptime(day + hour, "%Y-%m-%d%H%M").replace(tzinfo=timezone.utc)
                lat, lon = float(item["latitude"]), float(item["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            rows.append({"lat": lat, "lon": lon, "acq_ts_utc": ts,
                         "frp": float(item["frp"]) if item.get("frp") else None,
                         "confidence": item.get("confidence"), "satellite": product})

    # FIRMS may return thousands of detections. Batch the idempotent inserts
    # instead of issuing one round-trip query per row (which can exceed the
    # hourly Actions window on a hosted Postgres database).
    inserted = 0
    for start in range(0, len(rows), 500):
        statement = pg_insert(FireEvent).values(rows[start:start + 500])
        result = db.execute(statement.on_conflict_do_nothing(constraint="uq_fire_event"))
        inserted += max(result.rowcount or 0, 0)
    db.commit()
    return {"source": "NASA FIRMS", "products": list(products), "new_detections": inserted}
