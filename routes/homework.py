"""
Homework flow: warm_up task + recording_1 → task block + metric answers → recording_2 → questions → report.
All routes under /v2/homework, require auth. Replaces the classic v2 flow for the student dashboard.
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from services.db import db
from services.v2_flow_service import select_focus_task_for_performance_score_1
from services.metrics_v2 import compute_performance_score_1, compute_metrics_v2
from services.openai_service import openai_service
from services.realtime_audio_metrics import process_pcm_chunk
from utils.metrics import count_fillers, compute_wpm
import logging
import time
import uuid
import sentry_sdk

logger = logging.getLogger(__name__)
homework_bp = Blueprint("homework", __name__, url_prefix="/v2/homework")

# Rate limit for recording-metrics-chunk: 120 per minute per (user_id, session_id)
_metrics_chunk_timestamps = {}
_METRICS_CHUNK_LIMIT = 120
_METRICS_CHUNK_WINDOW_SEC = 60

# Homework session statuses
STATUS_WARM_UP = "warm_up"
STATUS_TASK_BLOCK = "task_block"
STATUS_FINAL_TASK_READY = "final_task_ready"
STATUS_POST_QUESTIONS = "post_questions"
STATUS_COMPLETED = "completed"


# ---------- Start & status ----------
@homework_bp.route("/session/start", methods=["POST"])
@require_auth
def homework_session_start():
    """Start or resume homework session. Returns session_id and warm_up_task (text) for step 1."""
    try:
        user_id = request.user_id
        active = db.v2_get_active_homework_session(user_id)
        if active:
            warm_up = db.v2_get_assigned_warm_up_task(user_id)
            # If no warm-up is configured, do not allow proceeding (same as on start)
            if not warm_up:
                return jsonify({
                    "code": "NO_WARMUP_CONFIGURED",
                    "message": "No warm-up tasks are configured for your account. Please contact your coach to get started.",
                    "details": {},
                }), 422
            # Snapshot warm-up for resume/reproducibility (idempotent if already set)
            if not active.get("warm_up_task_id") or not active.get("warm_up_task_text"):
                db.v2_update_session(active["id"], user_id, {
                    "warm_up_task_id": warm_up["id"],
                    "warm_up_task_text": warm_up.get("text") or "",
                })
            return jsonify({
                "session_id": active["id"],
                "status": active["status"],
                "warm_up_task": {"id": warm_up["id"], "text": warm_up["text"]},
            }), 200
        # Require at least one warm-up task; otherwise do not create session (prevents broken flow)
        warm_up = db.v2_get_assigned_warm_up_task(user_id)
        if not warm_up:
            return jsonify({
                "code": "NO_WARMUP_CONFIGURED",
                "message": "No warm-up tasks are configured for your account. Please contact your coach to get started.",
                "details": {},
            }), 422
        session = db.v2_create_homework_session(user_id)
        if not session:
            return jsonify({"code": "V2_ERROR", "error": "Failed to create session"}), 500
        # Snapshot user's custom metric questions for this session (used at end for LLM analysis)
        prefs = db.v2_get_user_metric_questions(user_id)
        db.v2_update_session(session["id"], user_id, {
            "session_metric_question_1": prefs.get("metric_question_1") or "",
            "session_metric_question_2": prefs.get("metric_question_2") or "",
            "session_metric_question_3": prefs.get("metric_question_3") or "",
            "warm_up_task_id": warm_up["id"] if warm_up else None,
            "warm_up_task_text": (warm_up.get("text") or "") if warm_up else "",
        })
        return jsonify({
            "session_id": session["id"],
            "status": STATUS_WARM_UP,
            "warm_up_task": {"id": warm_up["id"], "text": warm_up["text"]} if warm_up else None,
        }), 201
    except Exception as e:
        logger.error(f"Homework session start: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@homework_bp.route("/session/status", methods=["GET"])
@require_auth
def homework_session_status():
    """Get active homework session if any. Includes warm_up_task (id, text) from v2_warm_up_tasks so the UI can display it."""
    try:
        user_id = request.user_id
        active = db.v2_get_active_homework_session(user_id)
        if not active:
            return jsonify({"session": None, "has_active_session": False}), 200
        payload = {
            "session": active,
            "session_id": active["id"],
            "has_active_session": True,
        }
        # When in warm_up, always fetch warm-up task from v2_warm_up_tasks so the UI has the prompt text
        if active.get("status") == STATUS_WARM_UP:
            warm_up = db.v2_get_assigned_warm_up_task(user_id)
            if warm_up:
                payload["warm_up_task"] = {
                    "id": warm_up.get("id"),
                    "text": (warm_up.get("text") or "").strip() or db.DEFAULT_WARM_UP_TASK_TEXT,
                }
                # Persist snapshot on session for resume/audit
                if not active.get("warm_up_task_id") or not active.get("warm_up_task_text"):
                    db.v2_update_session(active["id"], user_id, {
                        "warm_up_task_id": warm_up.get("id"),
                        "warm_up_task_text": payload["warm_up_task"]["text"],
                    })
            else:
                payload["warm_up_task"] = None
        else:
            # Other statuses: use session snapshot if present
            wid = active.get("warm_up_task_id")
            wtext = active.get("warm_up_task_text")
            if wid or wtext:
                payload["warm_up_task"] = {"id": wid, "text": (wtext or "").strip()}
            else:
                payload["warm_up_task"] = None
        return jsonify(payload), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Real-time metrics chunk (Ambient Glow): PCM in → raw features out (stateless) ----------
@homework_bp.route("/session/<session_id>/recording-metrics-chunk", methods=["POST"])
@require_auth
def homework_recording_metrics_chunk(session_id):
    """
    Pause-only glow: accept binary PCM16 mono, maintain 10 s rolling window per session, return pause_score.
    Request: body = raw PCM16 LE bytes; headers X-Sample-Rate (16000), X-Seq, X-T-Ms (optional), X-Debug (1|true for _debug).
    Response: { seq, t_ms, voiced_ratio, pause_score }. Brightness = function(pause_score).
    Rate limit: 120 requests per 60s per (user_id, session_id).
    """
    try:
        user_id = request.user_id
        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        # Allow any active status (user may be in warm_up or final_task_ready while recording)
        status = session.get("status")
        if status not in (STATUS_WARM_UP, STATUS_TASK_BLOCK, STATUS_FINAL_TASK_READY, STATUS_POST_QUESTIONS):
            return jsonify({"code": "INVALID_SESSION_STATE", "error": "Session not in recording state", "status": status}), 409

        # Rate limit
        key = (str(user_id), str(session_id))
        now = time.time()
        if key not in _metrics_chunk_timestamps:
            _metrics_chunk_timestamps[key] = []
        timestamps = _metrics_chunk_timestamps[key]
        timestamps[:] = [t for t in timestamps if t > now - _METRICS_CHUNK_WINDOW_SEC]
        if len(timestamps) >= _METRICS_CHUNK_LIMIT:
            return jsonify({"code": "RATE_LIMITED", "error": "Too many chunk requests"}), 429
        timestamps.append(now)

        pcm_bytes = request.get_data()
        if not pcm_bytes:
            return jsonify({"code": "INVALID_INPUT", "error": "Missing PCM body"}), 400

        sample_rate = request.headers.get("X-Sample-Rate", "16000")
        try:
            sample_rate = int(sample_rate)
        except ValueError:
            sample_rate = 16000
        sample_rate = max(8000, min(48000, sample_rate))

        seq = request.headers.get("X-Seq", "0")
        try:
            seq = int(seq)
        except ValueError:
            seq = 0

        t_ms = request.headers.get("X-T-Ms", "0")
        try:
            t_ms = int(t_ms)
        except ValueError:
            t_ms = 0

        include_debug = request.headers.get("X-Debug", "").strip().lower() in ("1", "true")
        result = process_pcm_chunk(
            pcm_bytes,
            sample_rate,
            session_id=session_id,
            seq=seq,
            t_ms=t_ms,
            include_debug=include_debug,
        )
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Homework recording-metrics-chunk: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Step 1: warm-up task (GET) + recording_1 (POST) ----------
@homework_bp.route("/session/<session_id>/warm-up-task", methods=["GET"])
@require_auth
def homework_get_warm_up_task(session_id):
    """Get the single warm-up task text for this session (step 1 screen)."""
    try:
        user_id = request.user_id
        session = db.v2_get_session(session_id, user_id)
        if not session or session.get("status") != STATUS_WARM_UP:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found or not in warm_up"}), 404
        warm_up = db.v2_get_assigned_warm_up_task(user_id)
        if not warm_up:
            return jsonify({"code": "NO_WARM_UP", "error": "No warm-up task assigned"}), 404
        return jsonify({"warm_up_task": {"id": warm_up["id"], "text": warm_up["text"]}}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@homework_bp.route("/session/<session_id>/task-block", methods=["GET"])
@require_auth
def homework_get_task_block(session_id):
    """Get task block (metric_question_1/2/3 only) for step 2. context_1 and focus_task are used when generating final_task; not returned here. Use when resuming so the 3 questions can be shown."""
    try:
        user_id = request.user_id
        session = db.v2_get_session(session_id, user_id)
        if not session or session.get("status") != STATUS_TASK_BLOCK:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found or not in task_block"}), 404
        # Metrics step: only 3 questions. context_1 (context_short) and focus_task are used when generating final_task; not displayed here.
        metric_questions = db.v2_get_metric_questions_for_flow()
        q1 = metric_questions[0] if len(metric_questions) > 0 else {}
        q2 = metric_questions[1] if len(metric_questions) > 1 else {}
        q3 = metric_questions[2] if len(metric_questions) > 2 else {}
        task_block = {
            "metric_question_1": q1,
            "metric_question_2": q2,
            "metric_question_3": q3,
        }
        return jsonify({"task_block": task_block}), 200
    except Exception as e:
        logger.error(f"Homework get task-block: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


def _storage_path_for_session(user_id: str, session_id: str) -> str:
    return f"{user_id}/{session_id}/{uuid.uuid4()}.webm"


def _validate_storage_path(storage_path: str, user_id: str, session_id: str) -> bool:
    """Path must be under user_id/session_id/ and end with .webm."""
    if not storage_path or not isinstance(storage_path, str):
        return False
    prefix = f"{user_id}/{session_id}/"
    return storage_path.startswith(prefix) and storage_path.endswith(".webm")


@homework_bp.route("/session/<session_id>/recording-upload-url", methods=["POST"])
@require_auth
def homework_recording_upload_url(session_id):
    """Mint a storage path for direct-to-storage upload. Client uploads audio to this path (e.g. via Supabase JS), then calls recording-1 or recording-2 with storage_path + duration_seconds. Reduces 413 by not sending audio through API."""
    try:
        from config import Config
        config = Config()
        user_id = request.user_id
        data = request.get_json() or {}
        recording = str(data.get("recording", "1")).strip()
        if recording not in ("1", "2"):
            return jsonify({"code": "INVALID_INPUT", "error": "recording must be '1' or '2'"}), 400

        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        if recording == "1" and session.get("status") != STATUS_WARM_UP:
            return jsonify({"code": "INVALID_SESSION_STATE", "error": "Session must be in warm_up for recording-1", "status": session.get("status")}), 409
        if recording == "2" and session.get("status") != STATUS_FINAL_TASK_READY:
            return jsonify({"code": "INVALID_SESSION_STATE", "error": "Session must be in final_task_ready for recording-2", "status": session.get("status")}), 409

        storage_path = _storage_path_for_session(user_id, session_id)
        return jsonify({
            "storage_path": storage_path,
            "bucket": config.AUDIO_BUCKET_NAME,
        }), 200
    except Exception as e:
        logger.error(f"recording-upload-url: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@homework_bp.route("/session/<session_id>/recording-1", methods=["POST"])
@require_auth
def homework_submit_recording_1(session_id):
    """Upload recording_1 (warm-up). Accepts (A) multipart with 'audio' file, or (B) JSON with storage_path + duration_seconds (direct-to-storage). Returns performance_score_1, task_block."""
    try:
        from config import Config
        from io import BytesIO

        config = Config()
        user_id = request.user_id
        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        if session.get("status") != STATUS_WARM_UP:
            return jsonify({"code": "INVALID_SESSION_STATE", "error": "Session not found or not in warm_up", "status": session.get("status")}), 409

        audio_file = request.files.get("audio")
        data = request.get_json(silent=True) or (request.form or {})
        duration_seconds = None
        storage_path = None

        if audio_file:
            # Legacy: multipart upload
            ext = ".webm"
            storage_path = f"{user_id}/{session_id}/{uuid.uuid4()}{ext}"
            audio_file.seek(0)
            audio_data = audio_file.read()
            content_type = str(audio_file.content_type or "audio/webm")
            if content_type in ("True", "False"):
                content_type = "audio/webm"
            db.upload_audio(config.AUDIO_BUCKET_NAME, storage_path, audio_data, content_type=content_type)
            audio_file.seek(0)
            transcript_result = openai_service.transcribe_audio(audio_file, "audio.webm")
            duration_seconds = transcript_result.get("duration") or float(request.form.get("duration_seconds") or 60.0)
        else:
            # By URL: JSON with storage_path + duration_seconds
            storage_path = (data.get("storage_path") or "").strip()
            duration_seconds = data.get("duration_seconds")
            if not storage_path or duration_seconds is None:
                return jsonify({"code": "INVALID_INPUT", "error": "Either send multipart 'audio' or JSON with storage_path and duration_seconds"}), 400
            if not _validate_storage_path(storage_path, user_id, session_id):
                return jsonify({"code": "INVALID_INPUT", "error": "storage_path invalid or not allowed for this session"}), 400
            try:
                duration_seconds = float(duration_seconds)
            except (TypeError, ValueError):
                return jsonify({"code": "INVALID_INPUT", "error": "duration_seconds must be a number"}), 400
            # Idempotency: if we already have a recording for this session with this storage_path, return same response (retry/abort safe)
            existing_rid = session.get("recording_1_id")
            if existing_rid:
                existing = db.get_recording(existing_rid, user_id)
                if existing and (existing.get("storage_path") or "").strip() == storage_path:
                    metric_questions = db.v2_get_metric_questions_for_flow()
                    q1 = metric_questions[0] if len(metric_questions) > 0 else {}
                    q2 = metric_questions[1] if len(metric_questions) > 1 else {}
                    q3 = metric_questions[2] if len(metric_questions) > 2 else {}
                    task_block = {"metric_question_1": q1, "metric_question_2": q2, "metric_question_3": q3}
                    return jsonify({
                        "recording_id": existing["id"],
                        "performance_score_1": session.get("performance_score_1"),
                        "task_block": task_block,
                    }), 200
            audio_bytes = db.download_audio(config.AUDIO_BUCKET_NAME, storage_path)
            transcript_result = openai_service.transcribe_audio(BytesIO(audio_bytes), "audio.webm")
            duration_seconds = transcript_result.get("duration") or duration_seconds

        transcript_text = transcript_result["text"]

        audio_url = db.create_signed_url(config.AUDIO_BUCKET_NAME, storage_path, config.SIGNED_URL_EXPIRY_SECONDS)
        if not audio_url:
            supabase_url = config.SUPABASE_URL.rstrip("/")
            audio_url = f"{supabase_url}/storage/v1/object/public/{config.AUDIO_BUCKET_NAME}/{storage_path}"

        wpm = compute_wpm(transcript_text, duration_seconds)
        filler_data = count_fillers(transcript_text)
        filler_count = filler_data["total"]
        strength_raw = None

        performance_score_1 = compute_performance_score_1(wpm=wpm, strength_raw=strength_raw, filler_count=filler_count)

        context_short = openai_service.generate_context_short(transcript_text)

        # Prefer per-student focus tasks (admin panel); fall back to global v2_tasks; then default
        focus_task = db.v2_select_student_focus_task_for_score(user_id, performance_score_1)
        if not focus_task:
            overrides = db.v2_get_student_overrides(user_id)
            assigned_task_ids = (overrides.get("assigned_next_task_ids") or []) if overrides else None
            all_tasks = db.v2_get_active_tasks()
            focus_task = select_focus_task_for_performance_score_1(
                all_tasks, performance_score_1, assigned_task_ids
            )
        if not focus_task:
            # No suited option or new student: use default so flow never blocks
            default_text = db.DEFAULT_FOCUS_TASK_TEXT
            focus_task = {"id": None, "title": default_text, "prompt_text": default_text}

        metric_questions = db.v2_get_metric_questions_for_flow()

        duration_int = int(round(duration_seconds))
        recording_data = {
            "user_id": user_id,
            "session_id": None,
            "session_v2_id": session_id,
            "task_id": focus_task["id"] if focus_task else None,
            "audio_url": audio_url,
            "storage_path": storage_path,
            "duration": duration_int,
            "duration_seconds": duration_seconds,
            "transcription_text": transcript_text,
            "words_per_minute": wpm,
            "filler_words_count": {"breakdown": filler_data.get("breakdown", {}), "total": filler_count},
        }
        recording = db.create_recording(recording_data)
        if not recording:
            return jsonify({"code": "RECORDING_CREATE_FAILED"}), 500

        db.v2_update_session(session_id, user_id, {
            "recording_1_id": recording["id"],
            "performance_score_1": performance_score_1,
            "context_short": context_short,
            "selected_task_id": focus_task["id"] if focus_task else None,
            "status": STATUS_TASK_BLOCK,
        })

        q1 = metric_questions[0] if len(metric_questions) > 0 else {}
        q2 = metric_questions[1] if len(metric_questions) > 1 else {}
        q3 = metric_questions[2] if len(metric_questions) > 2 else {}
        # Metrics step: only 3 questions. context_1 (context_short) and focus_task are stored and used when generating final_task; not displayed at metrics stage.
        task_block = {
            "metric_question_1": q1,
            "metric_question_2": q2,
            "metric_question_3": q3,
        }
        return jsonify({
            "recording_id": recording["id"],
            "performance_score_1": performance_score_1,
            "task_block": task_block,
        }), 200
    except Exception as e:
        logger.error(f"Homework recording-1: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Step 2: metric answers → final_task ----------
@homework_bp.route("/session/<session_id>/metric-answers", methods=["POST"])
@require_auth
def homework_submit_metric_answers(session_id):
    """Submit metric_question_1, metric_question_2, metric_question_3 answers. Returns final_task text for step 3."""
    try:
        user_id = request.user_id
        data = request.get_json() or {}
        answer_1 = (data.get("answer_1") or data.get("metric_answer_1") or "").strip()
        answer_2 = (data.get("answer_2") or data.get("metric_answer_2") or "").strip()
        answer_3 = (data.get("answer_3") or data.get("metric_answer_3") or "").strip()

        session = db.v2_get_session(session_id, user_id)
        if not session or session.get("status") != STATUS_TASK_BLOCK:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found or not in task_block"}), 404

        # Require all three metric answers before continuing
        if not answer_1 or not answer_2 or not answer_3:
            return jsonify({
                "code": "VALIDATION_ERROR",
                "message": "Please answer all three questions before continuing.",
                "details": {"field": "metric_answers"},
            }), 422

        context_short = session.get("context_short") or ""
        task_id = session.get("selected_task_id")
        focus_task = db.v2_get_task_or_focus_task(task_id) if task_id else None
        default_focus = db.DEFAULT_FOCUS_TASK_TEXT
        focus_title = (focus_task.get("title") or default_focus) if focus_task else default_focus
        focus_prompt = (focus_task.get("prompt_text") or default_focus) if focus_task else default_focus

        final_task_text = openai_service.generate_final_task(
            context_short=context_short,
            focus_task_title=focus_title,
            focus_task_prompt=focus_prompt,
            metric_answer_1=answer_1,
            metric_answer_2=answer_2,
            metric_answer_3=answer_3,
        )

        db.v2_update_session(session_id, user_id, {
            "metric_answers": {"answer_1": answer_1, "answer_2": answer_2, "answer_3": answer_3},
            "status": STATUS_FINAL_TASK_READY,
            "final_task_text": final_task_text,
        })

        return jsonify({"final_task": final_task_text}), 200
    except Exception as e:
        logger.error(f"Homework metric-answers: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Step 3: recording_2 ----------
@homework_bp.route("/session/<session_id>/recording-2", methods=["POST"])
@require_auth
def homework_submit_recording_2(session_id):
    """Upload recording_2. Accepts (A) multipart with 'audio' file, or (B) JSON with storage_path + duration_seconds (direct-to-storage). Returns performance_score_2."""
    try:
        from config import Config
        from io import BytesIO

        config = Config()
        user_id = request.user_id
        session = db.v2_get_session(session_id, user_id)
        if not session or session.get("status") != STATUS_FINAL_TASK_READY:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found or not in final_task_ready"}), 404

        audio_file = request.files.get("audio")
        data = request.get_json(silent=True) or (request.form or {})
        duration_seconds = None
        storage_path = None

        if audio_file:
            ext = ".webm"
            storage_path = f"{user_id}/{session_id}/{uuid.uuid4()}{ext}"
            audio_file.seek(0)
            audio_data = audio_file.read()
            content_type = str(audio_file.content_type or "audio/webm")
            if content_type in ("True", "False"):
                content_type = "audio/webm"
            db.upload_audio(config.AUDIO_BUCKET_NAME, storage_path, audio_data, content_type=content_type)
            audio_file.seek(0)
            transcript_result = openai_service.transcribe_audio(audio_file, "audio.webm")
            duration_seconds = transcript_result.get("duration") or float(request.form.get("duration_seconds") or 60.0)
        else:
            storage_path = (data.get("storage_path") or "").strip()
            duration_seconds = data.get("duration_seconds")
            if not storage_path or duration_seconds is None:
                return jsonify({"code": "INVALID_INPUT", "error": "Either send multipart 'audio' or JSON with storage_path and duration_seconds"}), 400
            if not _validate_storage_path(storage_path, user_id, session_id):
                return jsonify({"code": "INVALID_INPUT", "error": "storage_path invalid or not allowed for this session"}), 400
            try:
                duration_seconds = float(duration_seconds)
            except (TypeError, ValueError):
                return jsonify({"code": "INVALID_INPUT", "error": "duration_seconds must be a number"}), 400
            # Idempotency: if we already have recording_2 for this session with this storage_path, return same response
            existing_rid = session.get("recording_2_id")
            if existing_rid:
                existing = db.get_recording(existing_rid, user_id)
                if existing and (existing.get("storage_path") or "").strip() == storage_path:
                    return jsonify({
                        "recording_id": existing["id"],
                        "performance_score_2": session.get("performance_score_2"),
                    }), 200
            audio_bytes = db.download_audio(config.AUDIO_BUCKET_NAME, storage_path)
            transcript_result = openai_service.transcribe_audio(BytesIO(audio_bytes), "audio.webm")
            duration_seconds = transcript_result.get("duration") or duration_seconds

        transcript_text = transcript_result["text"]

        audio_url = db.create_signed_url(config.AUDIO_BUCKET_NAME, storage_path, config.SIGNED_URL_EXPIRY_SECONDS)
        if not audio_url:
            supabase_url = config.SUPABASE_URL.rstrip("/")
            audio_url = f"{supabase_url}/storage/v1/object/public/{config.AUDIO_BUCKET_NAME}/{storage_path}"

        wpm = compute_wpm(transcript_text, duration_seconds)
        filler_data = count_fillers(transcript_text)
        filler_count = filler_data["total"]
        strength_raw = None
        keywords = []
        metric_defs = db.v2_get_metric_definitions()
        prelim = compute_metrics_v2(
            wpm=wpm,
            strength_raw=strength_raw,
            filler_count=filler_count,
            emotion_achieved=False,
            transcript=transcript_text,
            keywords=keywords,
            metric_definitions=metric_defs,
        )
        performance_score_2 = prelim["performance_score"]

        duration_int = int(round(duration_seconds))
        recording_data = {
            "user_id": user_id,
            "session_id": None,
            "session_v2_id": session_id,
            "task_id": session.get("selected_task_id"),
            "audio_url": audio_url,
            "storage_path": storage_path,
            "duration": duration_int,
            "duration_seconds": duration_seconds,
            "transcription_text": transcript_text,
            "words_per_minute": wpm,
            "filler_words_count": {"breakdown": filler_data.get("breakdown", {}), "total": filler_count},
            "performance_score_v2": performance_score_2,
            "performance_metrics_v2": prelim["metrics"],
            "metric_labels_snapshot_v2": prelim["metric_labels_snapshot"],
        }
        recording = db.create_recording(recording_data)
        if not recording:
            return jsonify({"code": "RECORDING_CREATE_FAILED"}), 500

        db.v2_update_session(session_id, user_id, {
            "recording_2_id": recording["id"],
            "performance_score_2": performance_score_2,
            "status": STATUS_POST_QUESTIONS,
        })

        return jsonify({
            "recording_id": recording["id"],
            "performance_score_2": performance_score_2,
        }), 200
    except Exception as e:
        logger.exception("Homework recording-2 failed")
        sentry_sdk.capture_exception(e)
        err_msg = str(e)
        payload = {"code": "V2_ERROR", "error": err_msg}
        # Hint for schema/cache errors (e.g. PGRST204 missing column)
        if "PGRST204" in err_msg or "schema cache" in err_msg or "column" in err_msg.lower():
            payload["hint"] = "Database schema may be missing columns or PostgREST cache stale. Run migrations for recordings and v2_sessions; reload PostgREST schema if using Supabase."
        return jsonify(payload), 500


# ---------- Step 4: questions (GET) + post-answers (POST) ----------
@homework_bp.route("/session/<session_id>/questions", methods=["GET"])
@require_auth
def homework_get_questions(session_id):
    """Get post-recording questions for this session from v2_student_post_recording_questions. If none, frontend skips step 4."""
    try:
        user_id = request.user_id
        session = db.v2_get_session(session_id, user_id)
        if not session or session.get("status") not in (STATUS_POST_QUESTIONS, STATUS_COMPLETED):
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found or wrong status"}), 404

        questions = db.v2_get_student_post_recording_questions(user_id)
        if not questions:
            return jsonify({"questions": []}), 200
        # Store per-student row ids in session so post-answers can match by question_id
        db.v2_update_session(session_id, user_id, {"post_question_ids": [str(q["id"]) for q in questions]})
        return jsonify({"questions": [{"id": q["id"], "text": q["text"], "answer_type": q.get("answer_type", "text")} for q in questions]}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@homework_bp.route("/session/<session_id>/post-answers", methods=["POST"])
@require_auth
def homework_submit_post_answers(session_id):
    """Submit post-recording answers. Compute performance_score_end, generate report, append to context_long_entries. Returns report_text and performance_score_end."""
    try:
        user_id = request.user_id
        data = request.get_json() or {}
        answers = data.get("answers", [])

        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        # Idempotency: if already completed, return existing report (do not create second report row)
        if session.get("status") == STATUS_COMPLETED:
            rec_id = session.get("recording_2_id") or session.get("recording_id")
            rec = db.get_recording(rec_id, user_id) if rec_id else None
            metrics = (rec.get("performance_metrics_v2") or {}) if rec else {}
            return jsonify({
                "report_text": session.get("context_long") or "",
                "performance_score_end": float(session.get("performance_score_end") or 0),
                "performance_metrics": metrics,
                "question_1_analysis": session.get("question_1_analysis") or "",
                "question_1_score": float(session.get("question_1_score") or 0),
                "question_2_analysis": session.get("question_2_analysis") or "",
                "question_2_score": float(session.get("question_2_score") or 0),
                "question_3_analysis": session.get("question_3_analysis") or "",
                "question_3_score": float(session.get("question_3_score") or 0),
            }), 200
        if session.get("status") != STATUS_POST_QUESTIONS:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found or not in post_questions"}), 404

        recording_2_id = session.get("recording_2_id") or session.get("recording_id")
        if not recording_2_id:
            return jsonify({"code": "INVALID_STATE", "error": "No recording_2"}), 400

        recording = db.get_recording(recording_2_id, user_id)
        if not recording:
            return jsonify({"code": "RECORDING_NOT_FOUND"}), 404

        post_question_ids = session.get("post_question_ids") or []
        student_questions = db.v2_get_student_post_recording_questions_by_ids(post_question_ids)
        emotion_achieved = False
        for ans in answers:
            qid = str(ans.get("question_id", ""))
            if qid not in post_question_ids:
                continue
            for q in student_questions:
                if str(q["id"]) == qid and q.get("code") == "emotion_achieved_check":
                    text = (ans.get("answer_text") or "").strip().upper()
                    emotion_achieved = text in ("YES", "Y", "1", "TRUE")
                    break

        transcript = recording.get("transcription_text") or ""
        wpm = float(recording.get("words_per_minute") or 0)
        filler_data = recording.get("filler_words_count") or {}
        filler_count = int(filler_data.get("total", 0)) if isinstance(filler_data, dict) else 0
        strength_raw = None
        if isinstance(recording.get("performance_metrics_v2"), dict):
            strength_raw = recording["performance_metrics_v2"].get("strength", {}).get("raw")
        metric_defs = db.v2_get_metric_definitions()
        final = compute_metrics_v2(
            wpm=wpm,
            strength_raw=strength_raw,
            filler_count=filler_count,
            emotion_achieved=emotion_achieved,
            transcript=transcript,
            keywords=[],
            metric_definitions=metric_defs,
        )
        db.update_recording(recording_2_id, {
            "performance_score_v2": final["performance_score"],
            "performance_metrics_v2": final["metrics"],
            "metric_labels_snapshot_v2": final["metric_labels_snapshot"],
        })

        performance_score_1 = float(session.get("performance_score_1") or 0)
        performance_score_2 = float(session.get("performance_score_2") or final["performance_score"])
        performance_score_end = (performance_score_1 + performance_score_2) / 2.0
        performance_score_end = max(0.0, min(1.0, performance_score_end))

        report_text = f"Your performance score: {performance_score_end:.0%}. "
        context_short = (session.get("context_short") or "").strip()
        metric_answers = session.get("metric_answers") or {}
        try:
            report_text = openai_service.generate_final_report(
                transcript=transcript[:500],
                pre_answers=[],
                post_answers=[{"question_text": "", "answer_text": a.get("answer_text", "")} for a in answers],
                wpm=wpm,
                filler_count=filler_count,
                filler_breakdown={},
                user_id=user_id,
                admin_context=db.get_user_admin_context(user_id),
                recording_id=recording_2_id,
                homework_context_short=context_short or None,
                homework_metric_answers=metric_answers if metric_answers else None,
                homework_performance_score_1=performance_score_1,
                homework_performance_score_2=performance_score_2,
                homework_metric_1_name="pacing",
                homework_metric_2_name="vocal strength",
            ) or report_text
        except Exception as e:
            logger.warning(f"Homework report generation failed: {e}")
            report_text += "Details: pace, strength, fillers, emotion, keywords."

        db.v2_append_context_long_entry(session_id, user_id, report_text)
        report_row = db.v2_create_report(session_id, recording_2_id, report_text)

        # Custom metric questions: LLM analysis per question (pitch_variance + 3 custom questions flow)
        q1 = (session.get("session_metric_question_1") or "").strip()
        q2 = (session.get("session_metric_question_2") or "").strip()
        q3 = (session.get("session_metric_question_3") or "").strip()
        custom_results = openai_service.analyze_custom_questions(transcript, [q1, q2, q3])
        r1, r2, r3 = (custom_results + [{"analysis": "", "score": 0}] * 3)[:3]
        session_update = {
            "post_answers": answers,
            "report_id": report_row["id"] if report_row else None,
            "performance_score_end": performance_score_end,
            "status": STATUS_COMPLETED,
            "question_1_analysis": r1.get("analysis") or "",
            "question_1_score": float(r1.get("score", 0)),
            "question_2_analysis": r2.get("analysis") or "",
            "question_2_score": float(r2.get("score", 0)),
            "question_3_analysis": r3.get("analysis") or "",
            "question_3_score": float(r3.get("score", 0)),
        }
        db.v2_update_session(session_id, user_id, session_update)

        return jsonify({
            "report_text": report_text,
            "performance_score_end": performance_score_end,
            "performance_metrics": final["metrics"],
            "question_1_analysis": session_update["question_1_analysis"],
            "question_1_score": session_update["question_1_score"],
            "question_2_analysis": session_update["question_2_analysis"],
            "question_2_score": session_update["question_2_score"],
            "question_3_analysis": session_update["question_3_analysis"],
            "question_3_score": session_update["question_3_score"],
        }), 200
    except Exception as e:
        logger.error(f"Homework post-answers: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500
