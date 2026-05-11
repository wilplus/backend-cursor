"""
In-process background job for recording-1 processing (transcribe, score, context, focus task).
POST recording-1 returns fast with task_block; this job runs the heavy work.
On failure we set recording_1_processing_status='failed' and recording_1_processing_error_code
so logs and GET session/status show the exact reason.
"""
import logging
import queue
import threading
import time
from io import BytesIO
from typing import Optional

import sentry_sdk

from config import Config
from services.db import db
from services.openai_service import openai_service
from utils.metrics import count_fillers, compute_wpm
from services.metrics_v2 import (
    build_recording_1_performance_profile,
    compute_recording_performance_score,
)
from services.homework_completion import complete_session_recording_1_only
from services.stress_snippet_service import (
    STRESS_SNIPPET_CLIP_SEC_DEFAULT,
    generate_stress_snippets_for_recording,
)
from services.charisma_snippet_service import (
    CHARISMA_SNIPPET_CLIP_SEC_DEFAULT,
    generate_charisma_snippets_for_recording,
)

logger = logging.getLogger(__name__)

# Stable error codes when recording_1_processing_status = 'failed' (for logs and optional frontend).
ERROR_SESSION_MISSING = "session_missing"
ERROR_STORAGE = "storage_error"
ERROR_TRANSCRIPTION = "transcription_failed"
ERROR_CONTEXT = "context_generation_failed"
ERROR_AUDIO_METRICS = "audio_metrics_failed"
ERROR_DB = "db_error"
ERROR_UNKNOWN = "unknown"

# In-memory queue and worker (Option A). Jobs lost on process restart.
_recording_1_queue = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()

# Dedup: recording_ids we've already enqueued (so we don't double-enqueue on retries)
_pending_recording_ids = set()
_pending_lock = threading.Lock()


def _runtime_bool(key: str, default: bool) -> bool:
    raw = (db.get_runtime_config(key) or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def enqueue_recording_1_job(
    session_id: str,
    recording_id: str,
    storage_path: str,
    user_id: str,
    duration_seconds=None,
    center_hold_ratio=None,
):
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


def _session_homework_task_id(session: Optional[dict]) -> Optional[str]:
    """UUID string of the homework task row (public.tasks) from session snapshot, if any."""
    if not session:
        return None
    tid = session.get("session_task_id")
    if tid is None:
        return None
    s = str(tid).strip()
    return s or None


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
    center_hold_ratio_from_client = payload.get("center_hold_ratio")

    config = Config()
    session = db.v2_get_session(session_id, user_id)
    if not session:
        logger.warning(
            "recording_1_job: session no longer exists (e.g. abandoned), session_id=%s recording_id=%s",
            session_id, recording_id,
        )
        return
    job_started = time.monotonic()

    try:
        # Step 1: download audio from storage.
        #
        # We pull through services.coach_video_storage.get_coach_object_bytes
        # so this stays in sync with the upload helper used by /v2/public/
        # interview/upload-answer (put_coach_object_bytes). That helper writes
        # to R2 when R2_* env vars are set (production) and falls back to
        # Supabase Storage otherwise. The previous direct
        # db.download_audio(AUDIO_BUCKET_NAME, ...) call always looked in
        # Supabase Storage, which broke this worker the moment uploads moved
        # to R2 — every new session crashed with:
        #   StorageException {'statusCode': 400, 'error': 'not_found'}
        # on guest_funnel/<sid>/turn_N.webm.
        from services.coach_video_storage import get_coach_object_bytes
        audio_bytes = get_coach_object_bytes(
            config.AUDIO_BUCKET_NAME, storage_path
        )
        if not audio_bytes:
            raise ValueError(f"Downloaded audio is empty (0 bytes): path={storage_path}")
        logger.info("recording_1_job: downloaded audio size=%d bytes session_id=%s", len(audio_bytes), session_id)
    except Exception as e:
        _mark_failed(session_id, user_id, ERROR_STORAGE, e)
        return

    # Client-side Web Speech transcript saved on the recording row as fallback
    recording_row = db.get_recording(recording_id, user_id)
    client_transcript = (recording_row.get("transcription_text") or "").strip() if recording_row else ""

    try:
        transcript_result = openai_service.transcribe_audio(BytesIO(audio_bytes), "audio.webm")
    except Exception as e:
        if client_transcript:
            logger.warning(
                "recording_1_job: Whisper failed, using client transcript as fallback session_id=%s error=%s",
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
        if not transcript_text:
            _mark_failed(session_id, user_id, ERROR_TRANSCRIPTION, ValueError("empty transcript"))
            return
        logger.info(
            "recording_1_job: stage=transcript_ready session_id=%s elapsed_ms=%d",
            session_id,
            int((time.monotonic() - job_started) * 1000),
        )

        # Build a playable URL for the recording row. With per-turn audio
        # now living in R2 (see services.coach_video_storage), the prior
        # db.create_signed_url(AUDIO_BUCKET_NAME, ...) call hits Supabase
        # Storage for an object that isn't there and raises
        # "{'statusCode': 400, 'error': 'not_found'}". Prefer the R2 public
        # URL (via R2_PUBLIC_BASE_URL, configured in production) and fall
        # back to the Supabase signed-URL path so this still works in dev
        # environments where R2 isn't configured.
        audio_url = ""
        try:
            from services.coach_video_storage import coach_media_public_url
            audio_url = coach_media_public_url(storage_path) or ""
        except Exception as e:
            logger.warning(
                "recording_1_job: R2 URL build failed for %s: %s",
                storage_path, e,
            )
        if not audio_url:
            try:
                audio_url = db.create_signed_url(
                    config.AUDIO_BUCKET_NAME, storage_path, config.SIGNED_URL_EXPIRY_SECONDS
                ) or ""
            except Exception as e:
                logger.warning(
                    "recording_1_job: signed URL fallback failed for %s: %s",
                    storage_path, e,
                )
                audio_url = ""
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
        score_source = score_result["score_source"]
        base_score_100 = score_result["base_score_100"]
        penalty_points = score_result["penalty_points"]
        final_score_100 = score_result["final_score_01"] * 100.0
        score = score_result["score_01"]
        logger.info(
            "recording_1_job: score source=%s base_score_100=%s filler_count=%s penalty_points=%s final_score_01=%.4f session_id=%s recording_id=%s",
            score_source,
            base_score_100,
            filler_count,
            penalty_points,
            score,
            session_id,
            recording_id,
        )
        performance_profile = build_recording_1_performance_profile(wpm, filler_count)

        try:
            context_short = openai_service.generate_context_short(transcript_text)
        except Exception as e:
            _mark_failed(session_id, user_id, ERROR_CONTEXT, e)
            return
        if not (context_short or "").strip():
            _mark_failed(session_id, user_id, ERROR_CONTEXT, ValueError("empty context_short"))
            return
        logger.info(
            "recording_1_job: stage=context_ready session_id=%s elapsed_ms=%d",
            session_id,
            int((time.monotonic() - job_started) * 1000),
        )

        # ── Sniper audio metrics (graceful fallback when ffmpeg is unavailable) ──
        try:
            from services.audio_metrics import analyze_audio
            audio_analysis = analyze_audio(
                audio_bytes,
                transcript=transcript_text,
                duration_sec=duration_seconds,
                fallback_wpm=wpm,
            )
        except Exception as metrics_err:
            logger.warning("recording_1_job: analyze_audio crashed, using fallback metrics session_id=%s: %s", session_id, metrics_err)
            audio_analysis = None

        # Railway environments without ffmpeg can still finish homework by persisting
        # minimal metrics (including stage_score) from deterministic backend scoring.
        if not audio_analysis:
            audio_analysis = {
                "wpm": wpm,
                "pause_ms": None,
                "dynamic_db": None,
                "emphasis_per_min": None,
                "energy_ratio": None,
                "pitch_center_st": None,
                "pitch_frame_count": None,
                "voiced_duration_sec": round(float(duration_seconds or 0.0), 1) if duration_seconds is not None else None,
            }
            logger.warning(
                "recording_1_job: ffmpeg metrics unavailable; using fallback sniper metrics session_id=%s recording_id=%s",
                session_id,
                recording_id,
            )

        try:
            db.save_session_sniper_metrics(
                session_id=session_id,
                user_id=user_id,
                wpm=audio_analysis.get("wpm"),
                pause_ms=audio_analysis.get("pause_ms"),
                dynamic_db=audio_analysis.get("dynamic_db"),
                emphasis_per_min=audio_analysis.get("emphasis_per_min"),
                energy_ratio=audio_analysis.get("energy_ratio"),
                stage_score=round(float(score), 4),
                voiced_duration_sec=audio_analysis.get("voiced_duration_sec"),
                recording_id=recording_id,
                duration_seconds=duration_seconds,
                pitch_center_st=audio_analysis.get("pitch_center_st"),
                pitch_frame_count=audio_analysis.get("pitch_frame_count"),
            )
            logger.info(
                "recording_1_job: sniper metrics saved wpm=%.0f pause=%s dyn=%s emph=%s energy=%s pitch=%s stage=%.4f session_id=%s",
                audio_analysis.get("wpm") or 0,
                audio_analysis.get("pause_ms"),
                audio_analysis.get("dynamic_db"),
                audio_analysis.get("emphasis_per_min"),
                audio_analysis.get("energy_ratio"),
                audio_analysis.get("pitch_center_st"),
                float(score),
                session_id,
            )
            logger.info(
                "recording_1_job: stage=metrics_ready session_id=%s elapsed_ms=%d",
                session_id,
                int((time.monotonic() - job_started) * 1000),
            )
        except Exception as metrics_save_err:
            _mark_failed(session_id, user_id, ERROR_AUDIO_METRICS, metrics_save_err)
            return

        duration_int = int(round(duration_seconds))
        existing_metrics = recording_row.get("performance_metrics_v2") if isinstance(recording_row, dict) else {}
        if not isinstance(existing_metrics, dict):
            existing_metrics = {}
        scoring_debug = score_result
        merged_metrics = dict(existing_metrics)
        merged_metrics["scoring_debug"] = scoring_debug
        recording_update = {
            "transcription_text": transcript_text,
            "words_per_minute": wpm,
            "filler_words_count": {"breakdown": filler_data.get("breakdown", {}), "total": filler_count},
            "audio_url": audio_url,
            "duration": duration_int,
            "duration_seconds": duration_seconds,
            "performance_metrics_v2": merged_metrics,
        }
        hw_task_id = _session_homework_task_id(session)
        if hw_task_id:
            recording_update["task_id"] = hw_task_id
        db.update_recording(recording_id, recording_update)
        db.v2_update_session(session_id, user_id, {
            "score": score,
            "context_short": context_short,
            "recording_1_processing_status": "completed",
            "recording_1_performance_profile": performance_profile,
        })
        # Generate candidate stress snippets (best-effort, non-blocking for completion).
        if _runtime_bool("stress_snippets_auto_extract_enabled", True):
            try:
                generate_stress_snippets_for_recording(
                    str(recording_id),
                    source_type="student",
                    max_snippets=8,
                    clip_seconds=STRESS_SNIPPET_CLIP_SEC_DEFAULT,
                    clear_existing=True,
                )
            except Exception as snippet_err:
                logger.warning("recording_1_job: stress snippet generation failed recording_id=%s err=%s", recording_id, snippet_err)
        else:
            logger.info(
                "recording_1_job: stress snippet auto-extract disabled by runtime_config recording_id=%s",
                recording_id,
            )
        # Generate candidate charisma snippets (best-effort, non-blocking for completion).
        if _runtime_bool("charisma_snippets_auto_extract_enabled", True):
            try:
                generate_charisma_snippets_for_recording(
                    str(recording_id),
                    source_type="student",
                    max_snippets=8,
                    clip_seconds=CHARISMA_SNIPPET_CLIP_SEC_DEFAULT,
                    clear_existing=True,
                )
            except Exception as charisma_err:
                logger.warning("recording_1_job: charisma snippet generation failed recording_id=%s err=%s", recording_id, charisma_err)
        else:
            logger.info(
                "recording_1_job: charisma snippet auto-extract disabled by runtime_config recording_id=%s",
                recording_id,
            )
        logger.info(
            "recording_1_job: stage=score_ready session_id=%s elapsed_ms=%d",
            session_id,
            int((time.monotonic() - job_started) * 1000),
        )
        # If the student already submitted self-rating (or skip), finish in background now.
        latest = db.v2_get_session(session_id, user_id)
        if latest and latest.get("status") == "completing_from_recording_1" and latest.get("self_rating_submitted_at"):
            try:
                complete_session_recording_1_only(
                    session_id,
                    user_id,
                    preferred_student_email=db.get_user_email_from_auth(user_id),
                )
                logger.info("recording_1_job: background completion ran after processing (self-rating already submitted) session_id=%s", session_id)
            except Exception as auto_complete_err:
                logger.warning("recording_1_job: background completion failed session_id=%s: %s", session_id, auto_complete_err)
    except Exception as e:
        _mark_failed(session_id, user_id, ERROR_UNKNOWN, e)
        return

    logger.info(
        "recording_1_job: processing done, waiting for self-rating to complete session_id=%s recording_id=%s",
        session_id, recording_id,
    )
