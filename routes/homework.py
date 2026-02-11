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
from utils.metrics import count_fillers, compute_wpm
import logging
import time
import uuid
import sentry_sdk

logger = logging.getLogger(__name__)
homework_bp = Blueprint("homework", __name__, url_prefix="/v2/homework")

# #region agent log
import json as _json
_DEBUG_LOG_PATH = "/Users/arturwillonski/Documents/backend-cursor/.cursor/debug.log"
def _agent_log(msg, data=None, hypothesis_id=None):
    try:
        payload = {"location": "homework.py", "message": msg, "timestamp": int(time.time() * 1000)}
        if data is not None:
            payload["data"] = data
        if hypothesis_id is not None:
            payload["hypothesisId"] = hypothesis_id
        with open(_DEBUG_LOG_PATH, "a") as f:
            f.write(_json.dumps(payload) + "\n")
    except Exception:
        pass
# #endregion

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
    """Start or resume homework session. Returns session_id and warm_up_task (text) for step 1. Strict: no session if 0 warm-ups."""
    try:
        user_id = request.user_id

        active = db.v2_get_active_homework_session(user_id)
        if active:
            wid = active.get("warm_up_task_id")
            wtext = (active.get("warm_up_task_text") or "").strip()

            warm_up_task = None
            if wtext:
                warm_up_task = {"id": wid, "text": wtext}
            else:
                warm_up = db.v2_get_assigned_warm_up_task(user_id)
                if not warm_up:
                    return jsonify({
                        "code": "NO_WARMUP_CONFIGURED",
                        "message": "No warm-up tasks are configured for your account. Please contact your coach to get started.",
                        "details": {},
                    }), 422
                text = (warm_up.get("text") or "").strip()
                if not text:
                    return jsonify({"code": "INVALID_STATE", "error": "Warm-up task has empty text"}), 500
                db.v2_update_session(active["id"], user_id, {
                    "warm_up_task_id": warm_up.get("id"),
                    "warm_up_task_text": text,
                })
                warm_up_task = {"id": warm_up.get("id"), "text": text}

            return jsonify({
                "session_id": active["id"],
                "status": active.get("status"),
                "warm_up_task": warm_up_task,
            }), 200

        warm_up = db.v2_get_assigned_warm_up_task(user_id)
        if not warm_up:
            return jsonify({
                "code": "NO_WARMUP_CONFIGURED",
                "message": "No warm-up tasks are configured for your account. Please contact your coach to get started.",
                "details": {},
            }), 422

        text = (warm_up.get("text") or "").strip()
        if not text:
            return jsonify({"code": "INVALID_STATE", "error": "Warm-up task has empty text"}), 500

        session = db.v2_create_homework_session(user_id)
        if not session:
            return jsonify({"code": "V2_ERROR", "error": "Failed to create session"}), 500

        prefs = db.v2_get_user_metric_questions(user_id)
        db.v2_update_session(session["id"], user_id, {
            "session_metric_question_1": (prefs.get("metric_question_1") or "").strip(),
            "session_metric_question_2": (prefs.get("metric_question_2") or "").strip(),
            "session_metric_question_3": (prefs.get("metric_question_3") or "").strip(),
            "warm_up_task_id": warm_up.get("id"),
            "warm_up_task_text": text,
        })

        return jsonify({
            "session_id": session["id"],
            "status": STATUS_WARM_UP,
            "warm_up_task": {"id": warm_up.get("id"), "text": text},
        }), 201

    except Exception as e:
        logger.error(f"Homework session start: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@homework_bp.route("/session/status", methods=["GET"])
@require_auth
def homework_session_status():
    """Get active homework session if any. Strict: does NOT create a session. Returns raw v2_sessions row (snake_case)."""
    try:
        user_id = request.user_id
        active = db.v2_get_active_homework_session(user_id)

        if not active:
            return jsonify({"session": None, "has_active_session": False}), 200

        warm_up_task = None
        wid = active.get("warm_up_task_id")
        wtext = (active.get("warm_up_task_text") or "").strip()

        if wtext:
            warm_up_task = {"id": wid, "text": wtext}
        elif active.get("status") == STATUS_WARM_UP:
            warm_up = db.v2_get_assigned_warm_up_task(user_id)
            if warm_up and (warm_up.get("text") or "").strip():
                text = (warm_up.get("text") or "").strip()
                db.v2_update_session(active["id"], user_id, {
                    "warm_up_task_id": warm_up.get("id"),
                    "warm_up_task_text": text,
                })
                warm_up_task = {"id": warm_up.get("id"), "text": text}

        return jsonify({
            "session": active,
            "session_id": active["id"],
            "has_active_session": True,
            "warm_up_task": warm_up_task,
        }), 200

    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@homework_bp.route("/session/<session_id>/abandon", methods=["POST"])
@require_auth
def homework_abandon_session(session_id):
    """Delete the homework session (owner only). User has no active session afterward; GET status returns has_active_session: false. Client should refetch status and show the first page (Start)."""
    try:
        user_id = request.user_id
        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        if session.get("status") == STATUS_COMPLETED:
            return jsonify({"code": "INVALID_SESSION_STATE", "error": "Cannot delete a completed session", "status": session.get("status")}), 409
        deleted = db.v2_delete_session(session_id, user_id)
        if not deleted:
            return jsonify({"code": "V2_ERROR", "error": "Session could not be deleted"}), 500
        return jsonify({"deleted": True, "message": "Session deleted. Refetch status and show the start page."}), 200
    except Exception as e:
        logger.error(f"Homework abandon session: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Step 1: warm-up task (GET) + recording_1 (POST) ----------
@homework_bp.route("/session/<session_id>/warm-up-task", methods=["GET"])
@require_auth
def homework_get_warm_up_task(session_id):
    """Get warm-up task for this session (step 1). Snapshot-first for deterministic resume. No default-text fallback."""
    try:
        user_id = request.user_id
        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        if session.get("status") != STATUS_WARM_UP:
            return jsonify({
                "code": "INVALID_SESSION_STATE",
                "error": "Session must be in warm_up",
                "status": session.get("status"),
            }), 409

        wid = session.get("warm_up_task_id")
        wtext = (session.get("warm_up_task_text") or "").strip()

        if wtext:
            return jsonify({"warm_up_task": {"id": wid, "text": wtext}}), 200

        warm_up = db.v2_get_assigned_warm_up_task(user_id)
        if not warm_up:
            return jsonify({
                "code": "NO_WARMUP_CONFIGURED",
                "message": "No warm-up tasks are configured for your account. Please contact your coach to get started.",
                "details": {},
            }), 422

        text = (warm_up.get("text") or "").strip()
        if not text:
            return jsonify({"code": "INVALID_STATE", "error": "Warm-up task has empty text"}), 500

        db.v2_update_session(session_id, user_id, {
            "warm_up_task_id": warm_up.get("id"),
            "warm_up_task_text": text,
        })
        return jsonify({"warm_up_task": {"id": warm_up.get("id"), "text": text}}), 200

    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@homework_bp.route("/session/<session_id>/task-block", methods=["GET"])
@require_auth
def homework_get_task_block(session_id):
    """Get task block for step 2. Returns session snapshots (session_metric_question_1/2/3) for determinism. Optional helper."""
    try:
        user_id = request.user_id
        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        if session.get("status") != STATUS_TASK_BLOCK:
            return jsonify({
                "code": "INVALID_SESSION_STATE",
                "error": "Session must be in task_block",
                "status": session.get("status"),
            }), 409

        q1 = (session.get("session_metric_question_1") or "").strip()
        q2 = (session.get("session_metric_question_2") or "").strip()
        q3 = (session.get("session_metric_question_3") or "").strip()

        if not (q1 and q2 and q3):
            prefs = db.v2_get_user_metric_questions(user_id)
            q1 = (q1 or prefs.get("metric_question_1") or "").strip()
            q2 = (q2 or prefs.get("metric_question_2") or "").strip()
            q3 = (q3 or prefs.get("metric_question_3") or "").strip()

            if not (q1 and q2 and q3):
                return jsonify({
                    "code": "INVALID_STATE",
                    "error": "Session metric questions are missing",
                    "details": {
                        "session_metric_question_1": bool(q1),
                        "session_metric_question_2": bool(q2),
                        "session_metric_question_3": bool(q3),
                    },
                }), 500

            db.v2_update_session(session_id, user_id, {
                "session_metric_question_1": q1,
                "session_metric_question_2": q2,
                "session_metric_question_3": q3,
            })

        task_block = {
            "metric_question_1": {"id": None, "position": 1, "text": q1},
            "metric_question_2": {"id": None, "position": 2, "text": q2},
            "metric_question_3": {"id": None, "position": 3, "text": q3},
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
            _agent_log("recording-upload-url: 409 rec=1 wrong status", {"session_id": session_id, "status": session.get("status")}, "H_upload")
            return jsonify({"code": "INVALID_SESSION_STATE", "error": "Session must be in warm_up for recording-1", "status": session.get("status")}), 409
        if recording == "2" and session.get("status") != STATUS_FINAL_TASK_READY:
            _agent_log("recording-upload-url: 409 rec=2 wrong status", {"session_id": session_id, "status": session.get("status")}, "H_upload")
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
            _agent_log("recording-1: session not found", {"session_id": session_id}, "H1")
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        if session.get("status") != STATUS_WARM_UP:
            _agent_log("recording-1: wrong status", {"session_id": session_id, "status": session.get("status")}, "H1")
            return jsonify({"code": "INVALID_SESSION_STATE", "error": "Session not found or not in warm_up", "status": session.get("status")}), 409

        audio_file = request.files.get("audio")
        _agent_log("recording-1: entry", {"session_id": session_id, "status": session.get("status"), "has_audio": bool(audio_file), "has_storage_path": bool((request.get_json(silent=True) or {}).get("storage_path"))}, "H1")
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
        _agent_log("recording-1: after create_recording", {"recording_id": recording["id"] if recording else None, "has_recording": bool(recording)}, "H2")
        if not recording:
            return jsonify({"code": "RECORDING_CREATE_FAILED"}), 500

        update_payload = {
            "recording_1_id": recording["id"],
            "performance_score_1": performance_score_1,
            "context_short": context_short,
            "selected_task_id": focus_task["id"] if focus_task else None,
            "status": STATUS_TASK_BLOCK,
        }
        update_result = db.v2_update_session(session_id, user_id, update_payload)
        _agent_log("recording-1: after v2_update_session", {"session_id": session_id, "update_result_is_none": update_result is None, "status_set": STATUS_TASK_BLOCK}, "H3")

        q1 = metric_questions[0] if len(metric_questions) > 0 else {}
        q2 = metric_questions[1] if len(metric_questions) > 1 else {}
        q3 = metric_questions[2] if len(metric_questions) > 2 else {}
        # Metrics step: only 3 questions. context_1 (context_short) and focus_task are stored and used when generating final_task; not displayed at metrics stage.
        task_block = {
            "metric_question_1": q1,
            "metric_question_2": q2,
            "metric_question_3": q3,
        }
        _agent_log("recording-1: success, returning 200 with task_block", {"recording_id": str(recording["id"])}, "H5")
        return jsonify({
            "recording_id": recording["id"],
            "performance_score_1": performance_score_1,
            "task_block": task_block,
        }), 200
    except Exception as e:
        _agent_log("recording-1: exception", {"error": str(e), "type": type(e).__name__}, "H5")
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
        answer_1 = (data.get("answer_1") or data.get("metric_answer_1") or data.get("q1_keywords") or "").strip()
        answer_2 = (data.get("answer_2") or data.get("metric_answer_2") or data.get("q2_emotion") or "").strip()
        answer_3 = (data.get("answer_3") or data.get("metric_answer_3") or data.get("q3_cta") or "").strip()

        session = db.v2_get_session(session_id, user_id)
        if not session:
            _agent_log("metric-answers: session not found", {"session_id": session_id}, "H1")
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        status = session.get("status")
        _agent_log("metric-answers: entry", {"session_id": session_id, "status": status, "has_answer_1": bool((data.get("answer_1") or data.get("metric_answer_1") or data.get("q1_keywords") or "").strip()), "has_answer_2": bool((data.get("answer_2") or data.get("metric_answer_2") or "").strip()), "has_answer_3": bool((data.get("answer_3") or data.get("metric_answer_3") or "").strip())}, "H1")
        if status != STATUS_TASK_BLOCK:
            # Idempotency: already past step and final_task exists → return 200 with existing
            if status == STATUS_FINAL_TASK_READY and (session.get("final_task_text") or "").strip():
                _agent_log("metric-answers: idempotency 200 (already final_task_ready)", {"session_id": session_id}, "H2")
                return jsonify({"final_task": (session.get("final_task_text") or "").strip()}), 200
            _agent_log("metric-answers: wrong status → 409", {"session_id": session_id, "status": status}, "H1")
            return jsonify({"code": "INVALID_SESSION_STATE", "error": "Session must be in task_block for metric-answers", "status": status}), 409

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
        _agent_log("metric-answers: after generate_final_task", {"session_id": session_id, "final_task_len": len(final_task_text) if final_task_text else 0, "has_context_short": bool(context_short)}, "H3")

        update_result = db.v2_update_session(session_id, user_id, {
            "metric_answers": {"answer_1": answer_1, "answer_2": answer_2, "answer_3": answer_3},
            "status": STATUS_FINAL_TASK_READY,
            "final_task_text": final_task_text,
        })
        _agent_log("metric-answers: after v2_update_session", {"session_id": session_id, "update_result_is_none": update_result is None}, "H4")

        _agent_log("metric-answers: success, returning 200 with final_task", {"session_id": session_id}, "H5")
        return jsonify({"final_task": final_task_text}), 200
    except Exception as e:
        _agent_log("metric-answers: exception", {"error": str(e), "type": type(e).__name__}, "H5")
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
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        # Idempotency: already past step and recording_2 exists → return 200 with existing
        if session.get("status") in (STATUS_POST_QUESTIONS, STATUS_COMPLETED) and session.get("recording_2_id"):
            return jsonify({
                "recording_id": session.get("recording_2_id"),
                "performance_score_2": session.get("performance_score_2"),
            }), 200
        if session.get("status") != STATUS_FINAL_TASK_READY:
            return jsonify({"code": "INVALID_SESSION_STATE", "error": "Session must be in final_task_ready for recording-2", "status": session.get("status")}), 409

        MIN_SECONDS = 60
        MAX_SECONDS = 300

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

        if duration_seconds < MIN_SECONDS or duration_seconds > MAX_SECONDS:
            return jsonify({
                "code": "RECORDING_DURATION_OUT_OF_RANGE",
                "message": "Recording must be between 60 and 300 seconds.",
                "details": {
                    "min_seconds": MIN_SECONDS,
                    "max_seconds": MAX_SECONDS,
                    "duration_seconds": duration_seconds,
                },
            }), 422

        transcript_text = transcript_result["text"]

        audio_url = db.create_signed_url(config.AUDIO_BUCKET_NAME, storage_path, config.SIGNED_URL_EXPIRY_SECONDS)
        if not audio_url:
            supabase_url = config.SUPABASE_URL.rstrip("/")
            audio_url = f"{supabase_url}/storage/v1/object/public/{config.AUDIO_BUCKET_NAME}/{storage_path}"

        wpm = compute_wpm(transcript_text, duration_seconds)
        filler_data = count_fillers(transcript_text)
        filler_count = filler_data["total"]
        strength_raw = None
        metric_answers = session.get("metric_answers") or {}
        answer_1 = (metric_answers.get("answer_1") or "").strip()
        keywords = [s.strip() for s in answer_1.replace(";", ",").split(",") if s.strip()] if answer_1 else []
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
            _agent_log("post-answers: session not found", {"session_id": session_id}, "H1")
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        status = session.get("status")
        _agent_log("post-answers: entry", {"session_id": session_id, "status": status, "answers_count": len(data.get("answers", []))}, "H1")
        # Idempotency: if already completed, return existing report (do not create second report row)
        if status == STATUS_COMPLETED:
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
        if status != STATUS_POST_QUESTIONS:
            _agent_log("post-answers: wrong status → 409", {"session_id": session_id, "status": status}, "H1")
            return jsonify({"code": "INVALID_SESSION_STATE", "error": "Session must be in post_questions for post-answers", "status": status}), 409

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
        metric_answers = session.get("metric_answers") or {}
        answer_1 = (metric_answers.get("answer_1") or "").strip()
        keywords = [s.strip() for s in answer_1.replace(";", ",").split(",") if s.strip()] if answer_1 else []
        metric_defs = db.v2_get_metric_definitions()
        final = compute_metrics_v2(
            wpm=wpm,
            strength_raw=strength_raw,
            filler_count=filler_count,
            emotion_achieved=emotion_achieved,
            transcript=transcript,
            keywords=keywords,
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
