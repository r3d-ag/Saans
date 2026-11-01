"""Load optional trained models; return None to use the safe baseline."""

from __future__ import annotations

import os
import pickle
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.app.models import AQISnapshot, ModelArtifact, Station

from .features import FEATURES, make_features


def predict_trained(db: Session, station: Station, issue: datetime, horizon: int) -> dict | None:
    model_dir = Path(os.getenv("MODEL_DIR", "models"))
    path = model_dir / "forecast_bundle.pkl"
    try:
        if path.exists():
            with path.open("rb") as handle:
                bundle = pickle.load(handle)
        else:
            artifact = db.scalar(select(ModelArtifact).order_by(ModelArtifact.trained_at.desc()).limit(1))
            if artifact is None:
                return None
            bundle = pickle.loads(artifact.payload)
        snapshot_rows = db.scalars(select(AQISnapshot).where(AQISnapshot.station_id == station.station_id,
                                                            AQISnapshot.aqi.is_not(None))
                                   .order_by(AQISnapshot.ts_utc.desc()).limit(200)).all()
        history = {row.ts_utc.replace(tzinfo=timezone.utc) if row.ts_utc.tzinfo is None
                   else row.ts_utc.astimezone(timezone.utc): float(row.aqi)
                   for row in snapshot_rows if row.aqi is not None}
        code = bundle["station_codes"].get(station.station_id)
        if code is None or horizon not in bundle["models"]:
            return None
        features = make_features(history, issue, code)
        if features is None:
            return None
        frame = [[features[key] for key in FEATURES]]
        model_set = bundle["models"][horizon]
        quantiles = {q: float(model.predict(frame)[0]) for q, model in model_set["quantiles"].items()}
        p10, p50, p90 = sorted(max(0.0, min(500.0, value)) for value in quantiles.values())
        classifier = model_set.get("classifier")
        if classifier is None:
            return None
        raw = classifier.predict_proba(frame)[0]
        probs = {str(category): float(prob) for category, prob in zip(classifier.classes_, raw, strict=False)}
        return {"aqi_p10": round(p10), "aqi_p50": round(p50), "aqi_p90": round(p90),
                "category_probs": probs, "model_version": bundle["version"],
                "reasons": ["Lagged AQI and calendar features", "Trained with time-ordered validation",
                            "Weather and fire features excluded until archived issue-time values are available"]}
    except (OSError, ValueError, KeyError, pickle.PickleError, ImportError):
        return None
