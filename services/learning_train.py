"""Train-on-demand direction classifier (willab Phase 4 / Prompt 1, B2).

Fits an interpretable logistic regression on the 11 acoustic features → the
coach's direction label, evaluates on a holdout, serializes the fitted
pipeline (joblib), stores it via the existing coach object transport, and
registers a model_versions row. SHADOW only — the artifact predicts into a log
later (B3); it influences NOTHING here.

`train_direction_classifier` is the testable ML core (pure of DB/storage). The
small-corpus path never emits junk: it trains anyway but returns loud warnings
(below the floor / in-sample metrics / single-class), so the caller can show
"provisional" rather than silently shipping a bad model.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from typing import Optional

from services.learning_export import FEATURES_11

logger = logging.getLogger(__name__)

# Corpus floor — below this we still train but flag it provisional.
_MIN_CORPUS = 50
_SCHEMA_VERSION = "direction-v1"
_ARTIFACT_BUCKET = "coach_feedback_videos"  # reuse the coach R2 transport
_ARTIFACT_PREFIX = "learning_models"


def train_direction_classifier(
    rows: list[dict],
) -> tuple[Optional[bytes], dict, list[str]]:
    """rows = export rows [{features:{11}, label}]. Returns
    (artifact_bytes|None, metrics, warnings). artifact is None when the corpus
    can't yield a model (empty / single class). Requires scikit-learn."""
    warnings: list[str] = []
    n = len(rows or [])
    if n == 0:
        return None, {"corpus_size": 0}, ["empty corpus — nothing to train"]
    if n < _MIN_CORPUS:
        warnings.append(
            f"{n} labels — provisional; recommend >= {_MIN_CORPUS}"
        )

    import numpy as np
    X = np.array(
        [[float(r["features"][k]) for k in FEATURES_11] for r in rows],
        dtype=float,
    )
    y = [r["label"] for r in rows]
    classes = sorted(set(y))
    if len(classes) < 2:
        return None, {"corpus_size": n, "classes": classes}, \
            warnings + ["only one label class present — cannot train"]

    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    from sklearn.metrics import accuracy_score, f1_score

    min_class = min(y.count(c) for c in classes)
    if n >= 8 and min_class >= 2:
        X_tr, X_te, y_tr, y_te = train_test_split(
            X, y, test_size=0.25, stratify=y, random_state=0,
        )
    else:
        X_tr, y_tr, X_te, y_te = X, y, X, y
        warnings.append("corpus too small for a holdout — metrics are in-sample")

    pipe = Pipeline([
        ("scale", StandardScaler()),
        ("clf", LogisticRegression(max_iter=1000)),
    ])
    pipe.fit(X_tr, y_tr)
    pred = pipe.predict(X_te)
    metrics = {
        "model": "logistic_regression",
        "corpus_size": n,
        "classes": classes,
        "by_class_support": {c: y.count(c) for c in classes},
        "accuracy": round(float(accuracy_score(y_te, pred)), 4),
        "f1_macro": round(float(f1_score(y_te, pred, average="macro")), 4),
        "features": list(FEATURES_11),
    }

    import joblib
    buf = io.BytesIO()
    joblib.dump(
        {"pipeline": pipe, "features": list(FEATURES_11), "classes": classes},
        buf,
    )
    return buf.getvalue(), metrics, warnings


def _store_artifact(version: str, artifact: bytes) -> Optional[str]:
    try:
        from services.coach_video_storage import put_coach_object_bytes
        key = f"{_ARTIFACT_PREFIX}/{version}.joblib"
        put_coach_object_bytes(
            _ARTIFACT_BUCKET, key, artifact, "application/octet-stream",
        )
        return key
    except Exception as e:
        logger.warning("learning_train: artifact store failed v=%s: %s", version, e)
        return None


def train_and_register() -> dict:
    """Full on-demand train: export → fit → store artifact → model_versions
    row. SHADOW status. Returns {version, metrics, corpus_size, warnings}.
    Never raises into the route — a failed train returns warnings."""
    from services.learning_export import export_snippet_labels_dataset
    from services.db import db

    rows, summary = export_snippet_labels_dataset()
    # Readiness rig #3: NEVER train on the frozen holdout — it is reserved for an
    # uncontaminated machine-vs-coach agreement read (scripts/eval_direction_
    # holdout.py). The model is shadow (influences nothing), so reserving ~20%
    # costs no product behavior and makes the readiness metric honest.
    train_rows = [r for r in rows if not r.get("is_holdout")]
    artifact, metrics, warnings = train_direction_classifier(train_rows)
    metrics["export_summary"] = summary
    metrics["trained_on"] = len(train_rows)
    metrics["holdout_reserved"] = summary.get("holdout", 0)

    version = (
        f"{_SCHEMA_VERSION}-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    artifact_ref = _store_artifact(version, artifact) if artifact else None
    if artifact and not artifact_ref:
        warnings.append("artifact storage failed — model not persisted")

    try:
        db.insert_model_version(
            version=version,
            status="shadow",
            schema_version=_SCHEMA_VERSION,
            corpus_size=len(rows),
            metrics=metrics,
            artifact_ref=artifact_ref,
        )
    except Exception as e:
        logger.warning("learning_train: model_versions insert failed: %s", e)
        warnings.append("model registry write failed")

    return {
        "version": version,
        "metrics": metrics,
        "corpus_size": len(rows),
        "warnings": warnings,
    }
