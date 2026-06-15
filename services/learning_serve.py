"""Shadow serving + the auto-retrain trigger (willab Phase 4 / Prompt 1, B3).

Loads the latest trained model (cached), predicts a snippet's direction, and
runs the SHADOW loop: predict per reviewed snippet → log to shadow_predictions
→ backfill the coach's actual label when they submit. The prediction is
TRANSIENT — never returned to a user or the coach packet, never alters the ≤10
selection. Auto-retrain fires off the label submit when enough NEW labels have
accrued (founder cadence: ≥25 new, ≥50 floor, no cron). All best-effort.
"""
from __future__ import annotations

import io
import logging
import threading
from typing import Any, Optional

from services.learning_export import FEATURES_11

logger = logging.getLogger(__name__)

_ARTIFACT_BUCKET = "coach_feedback_videos"
_RETRAIN_MIN_TOTAL = 50    # floor — don't train below this
_RETRAIN_NEW_DELTA = 25    # retrain once this many new labels since last model

_cache: dict = {"version": None, "bundle": None}
_retrain_lock = threading.Lock()


def _latest_bundle():
    """(version, bundle) of the newest model, cached by version. (None, None)
    when there's no model / load fails."""
    from services.db import db
    latest = db.get_latest_model_version()
    if not latest or not latest.get("artifact_ref"):
        return None, None
    version = latest.get("version")
    if _cache["version"] == version and _cache["bundle"] is not None:
        return version, _cache["bundle"]
    try:
        from services.coach_video_storage import get_coach_object_bytes
        import joblib
        raw = get_coach_object_bytes(_ARTIFACT_BUCKET, latest["artifact_ref"])
        bundle = joblib.load(io.BytesIO(raw))
        _cache["version"], _cache["bundle"] = version, bundle
        return version, bundle
    except Exception as e:
        logger.warning("learning_serve: artifact load failed v=%s: %s", version, e)
        return None, None


def predict_direction(features: Any) -> Optional[dict]:
    """{label, confidence, model_version} or None (no model / incomplete
    features / failure). SHADOW only — callers must never surface this."""
    if not isinstance(features, dict):
        return None
    version, bundle = _latest_bundle()
    if not bundle:
        return None
    try:
        keys = bundle.get("features") or list(FEATURES_11)
        vals = []
        for k in keys:
            v = features.get(k)
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                return None  # incomplete vector → no prediction
            vals.append(float(v))
        pipe = bundle["pipeline"]
        proba = pipe.predict_proba([vals])[0]
        idx = int(proba.argmax())
        return {
            "label": str(pipe.classes_[idx]),
            "confidence": round(float(proba[idx]), 4),
            "model_version": version,
        }
    except Exception as e:
        logger.warning("learning_serve: predict failed: %s", e)
        return None


def dispatch_shadow_predictions(session_id: str, snippets: list[dict]) -> None:
    """Fire-and-forget: predict each snippet's direction in SHADOW + log it.
    No-op without a model. NEVER returned to any payload."""
    if not snippets:
        return
    try:
        threading.Thread(
            target=_predict_all, args=(session_id, snippets), daemon=True,
        ).start()
    except Exception as e:
        logger.warning("learning_serve: shadow dispatch failed sid=%s: %s", session_id, e)


def _predict_all(session_id, snippets) -> None:
    from services.db import db
    n = 0
    for snip in (snippets or []):
        try:
            sid = snip.get("id")
            feats = snip.get("features")
            if not sid or not isinstance(feats, dict):
                continue
            pred = predict_direction(feats)
            if pred and db.upsert_shadow_prediction(
                session_id=session_id, snippet_id=str(sid),
                model_version=pred["model_version"],
                predicted_label=pred["label"], confidence=pred["confidence"],
            ):
                n += 1
        except Exception as e:
            logger.warning("learning_serve: shadow predict failed snip=%s: %s",
                           snip.get("id"), e)
    if n:
        logger.info("learning_serve: %d shadow predictions for %s", n, session_id)


def maybe_auto_retrain() -> None:
    """If enough NEW labels have accrued since the last model, retrain in the
    background (shadow). ≥50 total + ≥25 new. Single-flight; never auto-promotes
    (the new model stays status=shadow). Fire-and-forget, best-effort."""
    try:
        from services.db import db
        total = db.count_training_labels()
        if total < _RETRAIN_MIN_TOTAL:
            return
        last = db.get_latest_model_version()
        last_n = (last or {}).get("corpus_size") or 0
        if total - last_n < _RETRAIN_NEW_DELTA:
            return
        if not _retrain_lock.acquire(blocking=False):
            return  # a retrain is already running

        def _run():
            try:
                from services.learning_train import train_and_register
                res = train_and_register()
                logger.info(
                    "learning_serve: auto-retrain done v=%s corpus=%s",
                    res.get("version"), res.get("corpus_size"),
                )
            except Exception as e:
                logger.warning("learning_serve: auto-retrain failed: %s", e)
            finally:
                _retrain_lock.release()

        threading.Thread(target=_run, daemon=True).start()
    except Exception as e:
        logger.warning("learning_serve: maybe_auto_retrain failed: %s", e)
