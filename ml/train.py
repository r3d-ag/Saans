"""Train CPCB AQI forecasts from hourly snapshots with chronological holdout.

Run: python -m ml.train
Requires at least 500 valid feature/target pairs per horizon. The model is
saved to models/forecast_bundle.pkl; no model is committed by default.
"""

from __future__ import annotations

import json
import pickle
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from lightgbm import LGBMClassifier, LGBMRegressor
from sklearn.metrics import accuracy_score, mean_absolute_error, mean_squared_error

from apps.api.app.database import SessionLocal

from .features import FEATURES, build_training_frame


def train() -> dict:
    version = f"lightgbm-quantile-v1-{datetime.now(timezone.utc):%Y%m%dT%H%MZ}"
    bundle: dict = {"version": version, "models": {}, "station_codes": {}}
    report: dict = {"model_version": bundle["version"], "features": FEATURES, "horizons": {}}
    with SessionLocal() as db:
        for horizon in (24, 48):
            frame, station_codes = build_training_frame(db, horizon)
            bundle["station_codes"].update(station_codes)
            if len(frame) < 500:
                report["horizons"][str(horizon)] = {"status": "insufficient_data", "rows": len(frame), "minimum": 500}
                continue
            frame = frame.sort_values("issue_ts")
            issue_times = sorted(frame["issue_ts"].unique())
            train_cut = issue_times[int(len(issue_times) * 0.70)]
            test_cut = issue_times[int(len(issue_times) * 0.85)]
            early_train = frame[frame["issue_ts"] < train_cut]
            pre_test = frame[frame["issue_ts"] < test_cut]
            test = frame[frame["issue_ts"] >= test_cut]
            if len(early_train) < 100 or early_train["category"].nunique() < 2:
                report["horizons"][str(horizon)] = {"status": "insufficient_category_diversity", "rows": len(frame)}
                continue
            x_train = pre_test[FEATURES]
            x_test = test[FEATURES]
            y_train = pre_test["target"].to_numpy()
            y_test = test["target"].to_numpy()
            category_train = pre_test["category"]
            category_test = test["category"]
            walk_forward = []
            for fraction in (0.50, 0.62, 0.74):
                fold_train_cut = issue_times[int(len(issue_times) * fraction)]
                fold_valid_cut = issue_times[min(len(issue_times) - 1, int(len(issue_times) * (fraction + 0.10)))]
                fold_train = frame[frame["issue_ts"] < fold_train_cut]
                fold_valid = frame[(frame["issue_ts"] >= fold_train_cut) & (frame["issue_ts"] < fold_valid_cut)]
                if len(fold_train) < 100 or fold_valid.empty:
                    continue
                fold_model = LGBMRegressor(objective="quantile", alpha=0.5, n_estimators=250,
                                           learning_rate=0.035, num_leaves=15, min_child_samples=20,
                                           verbosity=-1, random_state=44)
                fold_model.fit(fold_train[FEATURES], fold_train["target"])
                fold_x = fold_valid[FEATURES]
                fold_y = fold_valid["target"].to_numpy()
                fold_pred = np.clip(fold_model.predict(fold_x), 0, 500)
                fold_mae = float(mean_absolute_error(fold_y, fold_pred))
                fold_base = float(mean_absolute_error(fold_y, fold_x["aqi_t0"].to_numpy()))
                walk_forward.append({"train_rows": len(fold_train), "validation_rows": len(fold_y),
                                     "model_mae": fold_mae, "persistence_mae": fold_base,
                                     "beats_persistence": fold_mae < fold_base})
            quantile_metrics = {}
            predictions = {}
            for alpha in (0.1, 0.5, 0.9):
                model = LGBMRegressor(objective="quantile", alpha=alpha, n_estimators=250,
                                      learning_rate=0.035, num_leaves=15, max_depth=-1,
                                      min_child_samples=20, verbosity=-1, random_state=44)
                model.fit(x_train, y_train)
                pred = np.clip(model.predict(x_test), 0, 500)
                predictions[alpha] = pred
                quantile_metrics[str(alpha)] = {"pinball_loss": float(np.mean(np.maximum(
                    alpha * (y_test - pred), (alpha - 1) * (y_test - pred))))}
            classifier = None
            if category_train.nunique() >= 2:
                classifier = LGBMClassifier(objective="multiclass", n_estimators=250,
                                             learning_rate=0.035, num_leaves=15,
                                             min_child_samples=20, verbosity=-1, random_state=44)
                classifier.fit(x_train, category_train)
                class_mask = category_test.isin(classifier.classes_)
                accuracy = accuracy_score(category_test[class_mask],
                                          classifier.predict(x_test.loc[class_mask])) if class_mask.any() else None
            else:
                accuracy = None
            persistence = x_test["aqi_t0"].to_numpy()
            p10, p50, p90 = (predictions[a] for a in (0.1, 0.5, 0.9))
            beats_persistence = mean_absolute_error(y_test, p50) < mean_absolute_error(y_test, persistence)
            walk_forward_beats = bool(walk_forward) and (
                sum(item["model_mae"] for item in walk_forward) / len(walk_forward)
                < sum(item["persistence_mae"] for item in walk_forward) / len(walk_forward))
            report["horizons"][str(horizon)] = {
                "status": "evaluated", "rows": len(frame), "train_rows": len(pre_test),
                "test_rows": len(x_test), "train_period_end": str(pre_test["issue_ts"].max()),
                "test_period_start": str(test["issue_ts"].min()),
                "mae_p50": float(mean_absolute_error(y_test, p50)),
                "rmse_p50": float(mean_squared_error(y_test, p50) ** 0.5),
                "persistence_mae": float(mean_absolute_error(y_test, persistence)),
                "category_accuracy": float(accuracy) if accuracy is not None else None,
                "interval_80_coverage": float(np.mean((y_test >= p10) & (y_test <= p90))),
                "pinball_loss": quantile_metrics,
                "walk_forward_folds": walk_forward, "walk_forward_beats_persistence": walk_forward_beats,
                "beats_persistence": bool(beats_persistence)}
            if not beats_persistence or not walk_forward_beats:
                continue
            # Refit the selected model family on all available rows after the holdout report is computed.
            final_quantiles = {}
            for alpha in (0.1, 0.5, 0.9):
                model = LGBMRegressor(objective="quantile", alpha=alpha, n_estimators=250,
                                      learning_rate=0.035, num_leaves=15, min_child_samples=20,
                                      verbosity=-1, random_state=44)
                model.fit(frame[FEATURES], frame["target"].to_numpy())
                final_quantiles[alpha] = model
            final_classifier = None
            if frame["category"].nunique() >= 2:
                final_classifier = LGBMClassifier(objective="multiclass", n_estimators=250,
                                                    learning_rate=0.035, num_leaves=15,
                                                    min_child_samples=20, verbosity=-1, random_state=44)
                final_classifier.fit(frame[FEATURES], frame["category"])
            bundle["models"][horizon] = {"quantiles": final_quantiles, "classifier": final_classifier}
    if not bundle["models"]:
        report["saved"] = False
        return report
    path = Path("models")
    path.mkdir(exist_ok=True)
    with (path / "forecast_bundle.pkl").open("wb") as handle:
        pickle.dump(bundle, handle, protocol=pickle.HIGHEST_PROTOCOL)
    report["saved"] = True
    (path / "evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(train(), indent=2))
