"""Download recent NASA FIRMS VIIRS NOAA-20/NOAA-21 active-fire detections."""

from __future__ import annotations

import csv
import io
import os
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
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
    inserted = 0
    for product, payload in frames:
        for item in csv.DictReader(io.StringIO(payload)):
            try:
                day = str(item["acq_date"])
                hour = str(item["acq_time"]).zfill(4)
                ts = datetime.strptime(day + hour, "%Y-%m-%d%H%M").replace(tzinfo=timezone.utc)
                lat, lon = float(item["latitude"]), float(item["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            satellite = product
            existing = db.scalar(select(FireEvent).where(FireEvent.lat == lat, FireEvent.lon == lon,
                                                          FireEvent.acq_ts_utc == ts,
                                                          FireEvent.satellite == satellite))
            if existing:
                continue
            db.add(FireEvent(lat=lat, lon=lon, acq_ts_utc=ts,
                             frp=float(item["frp"]) if item.get("frp") else None,
                             confidence=item.get("confidence"), satellite=satellite))
            inserted += 1
    db.commit()
    return {"source": "NASA FIRMS", "products": list(products), "new_detections": inserted}
