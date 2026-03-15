"""
In-process background job for recording-1 processing (transcribe, score, context, focus task).
POST recording-1 returns fast with task_block; this job runs the heavy work.
On failure we set recording_1_processing_status='failed' and recording_1_processing_error_code
so logs and GET session/status show the exact reason.
"""
import logging
import queue
import threading
from io import BytesIO

import sentry_sdk

from config import Config
from services.db import db
from services.openai_service import openai_service
from services.v2_flow_service import select_focus_task_for_performance_score_1
from utils.metrics import count_fillers, compute_wpm
from services.metrics_v2 import compute_performance_score_1, build_recording_1_performance_profile
from services.homework_completion import minimal_complete_and_notify

logger = logging.getLogger(__name__)

# Stable error codes when recording_1_processing_status = 'failed' (for logs and optional frontend).
ERROR_SESSION_MISSING = "session_missing"
ERROR_STORAGE = "storage_error"
ERROR_TRANSCRIPTION = "transcription_failed"
ERROR_CONTEXT = "context_generation_failed"
ERROR_DB = "db_error"
ERROR_UNKNOWN = "unknown"

# In-memory queue and worker (Option A). Jobs lost on process restart.
_recording_1_queue = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()

# Dedup: recording_ids we've already enqueued (so we don't double-enqueue on retries)
_pending_recording_ids = set()
_pending_lock = threading.Lock()


def enqueue_recording_1_job(session_id: str, recording_id: str, storage_path: str, user_id: str, duration_seconds=None):
    """Enqueue a recording-1 processing job. Deduplicates by recording_id."""
    with _pending_lock:
        if recording_id in _pending_recording_ids:
            logger.info("recording_1_job: skip duplicate enqueue recording_id=%s", recording_id)
            return
        _pending_recording_ids.add(recording_id)
    _recording_1_queue.put({
        "session_id": session_id,
        "recording_id": recording_id,
        "storage_path": storage_path,
        "user_id": user_id,
        "duration_seconds": duration_seconds,
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
        logger.info("recording_1_job: worker thread started")


def _worker_loop():
    while True:
        try:
            payload = _recording_1_queue.get()
            if payload is None:
                break
            _process_one(payload)
            with _pending_lock:
                _pending_recording_ids.discard(payload.get("recording_id"))
        except Exception as e:
            logger.exception("recording_1_job: worker loop error: %s", e)
            sentry_sdk.capture_exception(e)


def _mark_failed(session_id: str, user_id: str, error_code: str, exc: Exception):
    """Log full stack trace and set session to failed with stable error_code (for Railway logs and GET status)."""
    logger.exception(
        "recording_1_job: failed session_id=%s error_code=%s error=%s",
        session_id, error_code, exc,
        exc_info=True,
    )
    sentry_sdk.capture_exception(exc)
    updates = {"recording_1_processing_status": "failed", "recording_1_processing_error_code": error_code}
    try:
        db.v2_update_session(session_id, user_id, updates)
    except Exception as update_err:
        try:
            db.v2_update_session(session_id, user_id, {"recording_1_processing_status": "failed"})
        except Exception as retry_err:
            logger.warning("recording_1_job: could not set failed status: %s (retry without error_code: %s)", update_err, retry_err)


def _process_one(payload: dict):
    session_id = payload["session_id"]
    recording_id = payload["recording_id"]
    storage_path = payload["storage_path"]
    user_id = payload["user_id"]
    duration_seconds_from_client = payload.get("duration_seconds")

    config = Config()
    session = db.v2_get_session(session_id, user_id)
    if not session:
        logger.warning(
            "recording_1_job: session no longer exists (e.g. abandoned), session_id=%s recording_id=%s",
            session_id, recording_id,
        )
        return

    try:
        # Step 1: download audio from storage
        audio_bytes = db.download_audio(config.AUDIO_BUCKET_NAME, storage_path)
        if not audio_bytes:
            raise ValueError(f"Downloaded audio is empty (0 bytes): path={storage_path}")
        logger.info("recording_1_job: downloaded audio size=%d bytes session_id=%s", len(audio_bytes), session_id)
    except Exception as e:
        _mark_failed(session_id, user_id, ERROR_STORAGE, e)
        try:
            if minimal_complete_and_notify(session_id, user_id):
                logger.info("recording_1_job: minimal completion and coach notification sent after storage_error")
        except Exception as fallback_err:
            logger.warning("recording_1_job: minimal_complete_and_notify failed: %s", fallback_err)
        return

    try:
        transcript_result = openai_service.transcribe_audio(BytesIO(audio_bytes), "audio.webm")
    except Exception as e:
        _mark_failed(session_id, user_id, ERROR_TRANSCRIPTION, e)
        try:
            if minimal_complete_and_notify(session_id, user_id):
                logger.info("recording_1_job: minimal completion and coach notification sent after transcription_failed")
        except Exception as fallback_err:
            logger.warning("recording_1_job: minimal_complete_and_notify failed: %s", fallback_err)
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
        performance_score_1 = compute_performance_score_1(wpm=wpm, strength_raw=None, filler_count=filler_count)
        performance_profile = build_recording_1_performance_profile(wpm, filler_count)

        try:
            context_short = openai_service.generate_context_short(transcript_text)
        except Exception as e:
            _mark_failed(session_id, user_id, ERROR_CONTEXT, e)
            try:
                if minimal_complete_and_notify(session_id, user_id):
                    logger.info("recording_1_job: minimal completion and coach notification sent after context_generation_failed")
            except Exception as fallback_err:
                logger.warning("recording_1_job: minimal_complete_and_notify failed: %s", fallback_err)
            return

        focus_task = db.v2_select_student_focus_task_for_score(user_id, performance_score_1)
        if not focus_task:
            overrides = db.v2_get_student_overrides(user_id)
            assigned_task_ids = (overrides.get("assigned_next_task_ids") or []) if overrides else None
            all_tasks = db.v2_get_active_tasks()
            focus_task = select_focus_task_for_performance_score_1(
                all_tasks, performance_score_1, assigned_task_ids
            )
        if not focus_task:
            focus_task = {"id": None, "title": db.DEFAULT_FOCUS_TASK_TEXT, "prompt_text": db.DEFAULT_FOCUS_TASK_TEXT}

        duration_int = int(round(duration_seconds))
        db.update_recording(recording_id, {
            "transcription_text": transcript_text,
            "words_per_minute": wpm,
            "filler_words_count": {"breakdown": filler_data.get("breakdown", {}), "total": filler_count},
            "audio_url": audio_url,
            "duration": duration_int,
            "duration_seconds": duration_seconds,
            "task_id": focus_task["id"] if focus_task else None,
        })
        db.v2_update_session(session_id, user_id, {
            "performance_score_1": performance_score_1,
            "context_short": context_short,
            "selected_task_id": focus_task["id"] if focus_task else None,
            "recording_1_processing_status": "completed",
            "recording_1_performance_profile": performance_profile,
        })
    except Exception as e:
        _mark_failed(session_id, user_id, ERROR_UNKNOWN, e)
        try:
            if minimal_complete_and_notify(session_id, user_id):
                logger.info("recording_1_job: minimal completion and coach notification sent after %s", ERROR_UNKNOWN)
        except Exception as fallback_err:
            logger.warning("recording_1_job: minimal_complete_and_notify failed: %s", fallback_err)
        return

    logger.info(
        "recording_1_job: processing done, waiting for self-rating to complete session_id=%s recording_id=%s",
        session_id, recording_id,
    )
