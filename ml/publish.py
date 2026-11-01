"""Publish a trained model bundle to a protected Saans API endpoint."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import httpx


def main() -> None:
    bundle_path = Path("models/forecast_bundle.pkl")
    evaluation_path = Path("models/evaluation.json")
    if not bundle_path.exists():
        print("No model was published: no horizon passed the persistence gates.")
        return
    api_url = os.getenv("SAANS_API_URL", "").rstrip("/")
    token = os.getenv("INGEST_TOKEN", "")
    if not api_url or not token:
        raise SystemExit("SAANS_API_URL and INGEST_TOKEN are required to publish a model.")
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8")) if evaluation_path.exists() else {}
    version = evaluation.get("model_version")
    if not version:
        raise SystemExit("The training evaluation report has no model version.")
    payload = {"version": version,
               "bundle_base64": base64.b64encode(bundle_path.read_bytes()).decode("ascii"),
               "evaluation": evaluation}
    response = httpx.post(f"{api_url}/internal/models", json=payload,
                          headers={"Authorization": f"Bearer {token}"}, timeout=180)
    response.raise_for_status()
    print(response.text)


if __name__ == "__main__":
    main()
