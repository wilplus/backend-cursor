"""
In-process background job for recording-2 processing (transcribe, score, complete session).
POST recording-2 returns fast; this job runs the heavy work.
Uses the same compute_recording_performance_score formula as recording_1_job.
On failure sets recording_2_processing_status='failed' with a stable error_code.
"""
import logging
import queue
import threading
from io import BytesIO

import sentry_sdk

from config import Config
from services.db import db
from services.openai_service import openai_service
from utils.metrics import count_fillers, compute_wpm
from services.metrics_v2 import compute_recording_performance_score

logger = logging.getLogger(__name__)

ERROR_SESSION_MISSING = "session_missing"
ERROR_STORAGE = "storage_error"
ERROR_TRANSCRIPTION = "transcription_failed"
ERROR_DB = "db_error"
ERROR_UNKNOWN = "unknown"

_recording_2_queue = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()

_pending_recording_ids: set = set()
_pending_lock = threading.Lock()


def enqueue_recording_2_job(
    session_id: str,
    recording_id: str,
    storage_path: str,
    user_id: str,
    duration_seconds=None,
    center_hold_ratio=None,
):
    """Enqueue a recording-2 processing job. Deduplicates by recording_id."""
    with _pending_lock:
        if recording_id in _pending_recording_ids:
            logger.info("recording_2_job: skip duplicate enqueue recording_id=%s", recording_id)
            return
        _pending_recording_ids.add(recording_id)
    _recording_2_queue.put({
        "session_id": session_id,
        "recording_id": recording_id,
        "storage_path": storage_path,
        "user_id": user_id,
        "duration_seconds": duration_seconds,
        "center_hold_ratio": center_hold_ratio,
    })
    _ensure_worker_started()


def _ensure_worker_started():
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True
        t = threading.Thread(target=_worker_loop, daemon=True)
        t.start()
        logger.info("recording_2_job: worker thread started")


def _worker_loop():
    while True:
        try:
            payload = _recording_2_queue.get()
            if payload is None:
                break
            _process_one(payload)
            with _pending_lock:
                _pending_recording_ids.discard(payload.get("recording_id"))
        except Exception as e:
            logger.exception("recording_2_job: worker loop error: %s", e)
            sentry_sdk.capture_exception(e)


def _mark_failed(session_id: str, user_id: str, error_code: str, exc: Exception):
    logger.exception(
        "recording_2_job: failed session_id=%s error_code=%s error=%s",
        session_id, error_code, exc,
        exc_info=True,
    )
    sentry_sdk.capture_exception(exc)
    updates = {"recording_2_processing_status": "failed", "recording_2_processing_error_code": error_code}
    try:
        db.v2_update_session(session_id, user_id, updates)
    except Exception as update_err:
        try:
            db.v2_update_session(session_id, user_id, {"recording_2_processing_status": "failed"})
        except Exception as retry_err:
            logger.warning(
                "recording_2_job: could not set failed status: %s (retry: %s)", update_err, retry_err
            )


def _process_one(payload: dict):
    session_id = payload["session_id"]
    recording_id = payload["recording_id"]
    storage_path = payload["storage_path"]
    user_id = payload["user_id"]
    duration_seconds_from_client = payload.get("duration_seconds")
    center_hold_ratio_from_client = payload.get("center_hold_ratio")

    config = Config()
    session = db.v2_get_session(session_id, user_id)
    if not session:
        logger.warning(
            "recording_2_job: session no longer exists session_id=%s recording_id=%s",
            session_id, recording_id,
        )
        return

    try:
        audio_bytes = db.download_audio(config.AUDIO_BUCKET_NAME, storage_path)
        if not audio_bytes:
            raise ValueError(f"Downloaded audio is empty: path={storage_path}")
        logger.info("recording_2_job: downloaded audio size=%d bytes session_id=%s", len(audio_bytes), session_id)
    except Exception as e:
        _mark_failed(session_id, user_id, ERROR_STORAGE, e)
        return

    recording_row = db.get_recording(recording_id, user_id)
    client_transcript = (recording_row.get("transcription_text") or "").strip() if recording_row else ""

    try:
        transcript_result = openai_service.transcribe_audio(BytesIO(audio_bytes), "audio.webm")
    except Exception as e:
        if client_transcript:
            logger.warning(
                "recording_2_job: Whisper failed, using client transcript session_id=%s error=%s",
                session_id, e,
            )
            transcript_result = {"text": client_transcript, "duration": duration_seconds_from_client}
        else:
            _mark_failed(session_id, user_id, ERROR_TRANSCRIPTION, e)
            return

    try:
        duration_seconds = transcript_result.get("duration") or duration_seconds_from_client
        if duration_seconds is None:
            duration_seconds = 60.0
        else:
            duration_seconds = float(duration_seconds)
        transcript_text = (transcript_result.get("text") or "").strip()

        audio_url = db.create_signed_url(config.AUDIO_BUCKET_NAME, storage_path, config.SIGNED_URL_EXPIRY_SECONDS)
        if not audio_url:
            supabase_url = config.SUPABASE_URL.rstrip("/")
            audio_url = f"{supabase_url}/storage/v1/object/public/{config.AUDIO_BUCKET_NAME}/{storage_path}"

        wpm = compute_wpm(transcript_text, duration_seconds)
        filler_data = count_fillers(transcript_text)
        filler_count = filler_data["total"]

        center_hold_ratio = None
        try:
            if center_hold_ratio_from_client is not None:
                center_hold_ratio = max(0.0, min(1.0, float(center_hold_ratio_from_client)))
        except (TypeError, ValueError):
            center_hold_ratio = None

        score_result = compute_recording_performance_score(center_hold_ratio, filler_count, wpm)
        score = score_result["score_01"]
        logger.info(
            "recording_2_job: score source=%s base_score_100=%s filler_count=%s penalty_points=%s final_score_01=%.4f session_id=%s recording_id=%s",
            score_result["score_source"],
            score_result["base_score_100"],
            filler_count,
            score_result["penalty_points"],
            score,
            session_id,
            recording_id,
        )

        duration_int = int(round(duration_seconds))
        existing_metrics = recording_row.get("performance_metrics_v2") if isinstance(recording_row, dict) else {}
        if not isinstance(existing_metrics, dict):
            existing_metrics = {}
        merged_metrics = dict(existing_metrics)
        merged_metrics["scoring_debug"] = score_result

        db.update_recording(recording_id, {
            "transcription_text": transcript_text,
            "words_per_minute": wpm,
            "filler_words_count": {"breakdown": filler_data.get("breakdown", {}), "total": filler_count},
            "audio_url": audio_url,
            "duration": duration_int,
            "duration_seconds": duration_seconds,
            "performance_metrics_v2": merged_metrics,
        })
        db.v2_update_session(session_id, user_id, {
            "score": score,
            "recording_2_processing_status": "completed",
        })

        # Trigger session completion if already in the completing state.
        from services.homework_completion import complete_session_recording_2_only
        latest = db.v2_get_session(session_id, user_id)
        if latest and latest.get("status") == "completing_from_recording_2":
            try:
                complete_session_recording_2_only(
                    session_id,
                    user_id,
                    preferred_student_email=db.get_user_email_from_auth(user_id),
                )
                logger.info("recording_2_job: completion triggered session_id=%s", session_id)
            except Exception as complete_err:
                logger.warning("recording_2_job: completion failed session_id=%s: %s", session_id, complete_err)
    except Exception as e:
        _mark_failed(session_id, user_id, ERROR_UNKNOWN, e)
        return

    logger.info("recording_2_job: processing done session_id=%s recording_id=%s", session_id, recording_id)
