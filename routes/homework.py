"""
Homework flow (TEMPORARY: steps 2–4 removed): warm_up + recording_1 → report only.
All routes under /v2/homework, require auth. Restore steps 2–4 from docs/TEMPORARY-REMOVED-STEPS-2-3-4-BACKUP.md or git history.
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from config import Config
from services.db import db
from services.email_service import email_service
from services.homework_completion import (
    complete_session_recording_1_only,
    minimal_complete_and_notify,
    ensure_student_completion_email,
)
from services.sniper_realtime import clear_sniper_session
import logging
import os
import time
import uuid
import sentry_sdk
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
homework_bp = Blueprint("homework", __name__, url_prefix="/v2/homework")

# #region agent log
import json as _json
_DEBUG_LOG_PATH = "/Users/arturwillonski/Documents/backend-cursor/.cursor/debug.log"
_DEBUG_LOG_FALLBACK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "debug_runtime.log")

def _debug_log_write(payload):
    """Write one NDJSON line to debug log; try primary path then fallback."""
    line = _json.dumps(payload) + "\n"
    for path in (_DEBUG_LOG_PATH, _DEBUG_LOG_FALLBACK):
        try:
            d = os.path.dirname(path)
            if d:
                os.makedirs(d, exist_ok=True)
            with open(path, "a") as f:
                f.write(line)
            return
        except Exception:
            continue

def _agent_log(msg, data=None, hypothesis_id=None):
    try:
        payload = {"location": "homework.py", "message": msg, "timestamp": int(time.time() * 1000)}
        if data is not None:
            payload["data"] = data
        if hypothesis_id is not None:
            payload["hypothesisId"] = hypothesis_id
        _debug_log_write(payload)
    except Exception:
        pass
# #endregion

# Homework session statuses (internal DB values)
STATUS_WARM_UP = "warm_up"
STATUS_TASK_BLOCK = "task_block"
STATUS_FINAL_TASK_READY = "final_task_ready"
# Legacy compatibility only; the current web client does not use the post-questions step.
STATUS_POST_QUESTIONS = "post_questions"
STATUS_COMPLETED = "completed"
# No focus tasks: skip step 2 and 3; job will complete session from recording 1 only
STATUS_COMPLETING_FROM_RECORDING_1 = "completing_from_recording_1"

# Public API status vocabulary. Frontend uses ONLY top-level "status"; never derive from session.status.
PUBLIC_STATUS_NONE = "none"
PUBLIC_STATUS_RECORDING_1_REQUIRED = "recording_1_required"
PUBLIC_STATUS_COMPLETED = "completed"
PUBLIC_STATUS_REPORT_GENERATING = "report_generating"


def _public_status(db_status):
    """Map internal DB status to public API status. Frontend depends only on this."""
    if db_status is None:
        return PUBLIC_STATUS_NONE
    m = {
        STATUS_WARM_UP: PUBLIC_STATUS_RECORDING_1_REQUIRED,
        STATUS_TASK_BLOCK: PUBLIC_STATUS_REPORT_GENERATING,
        STATUS_FINAL_TASK_READY: PUBLIC_STATUS_REPORT_GENERATING,
        # Old sessions may still exist in this state, but the public API should
        # still expose the simplified single-recording report-generating state.
        STATUS_POST_QUESTIONS: PUBLIC_STATUS_REPORT_GENERATING,
        STATUS_COMPLETED: PUBLIC_STATUS_COMPLETED,
        STATUS_COMPLETING_FROM_RECORDING_1: PUBLIC_STATUS_REPORT_GENERATING,
    }
    return m.get(db_status, PUBLIC_STATUS_NONE)


def _session_for_json(obj):
    """Return a JSON-serializable copy of a session dict (Supabase returns datetime/datetime-like objects; Flask jsonify does not serialize them)."""
    if obj is None:
        return None
    if hasattr(obj, "isoformat") and callable(getattr(obj, "isoformat", None)):
        dt = obj
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _session_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_session_for_json(v) for v in obj]
    return obj


def _task_payload(task_id, text):
    text = (text or "").strip()
    if not text:
        return None
    return {"id": task_id, "text": text}


def _task_text(text):
    text = (text or "").strip()
    return text or None


def _parse_isoish_datetime(value):
    if not value:
        return None
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    elif hasattr(value, "isoformat"):
        dt = value
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _public_recording_id(session: dict):
    if not session:
        return None
    recording_id = session.get("recording_2_id") or session.get("recording_1_id")
    return str(recording_id) if recording_id else None


def _build_step0_payload(user_id: str) -> dict:
    """Build the session/status payload when there is no active session (step 0). Used by GET status and POST leave-report."""
    config = Config()
    sniper_profile = db.get_sniper_profile_payload(user_id)
    coach_name = (getattr(config, "COACH_NAME", "Artur") or "Artur").strip().title() or "Artur"
    payload = {
        "status": PUBLIC_STATUS_NONE,
        "session_id": None,
        "recording_id": None,
        "task": None,
        "assigned_exercises": [],
        "tutor_feedback_deadline": None,
        "tutor_feedback_message": None,
        "tutor_video_description": None,
        "review_pending": False,
        "report_delivered": False,
        "main_screen_state": "assignment_ready",
        "main_screen_message": None,
        "sniper_profile": sniper_profile,
        "realtime_level": sniper_profile.get("realtime_level"),
        "realtime_step": sniper_profile.get("realtime_step"),
    }
    review_pending = False
    feedback_sent_at = None
    try:
        last_completed = db.v2_get_last_completed_session(user_id)
        completed_at = _parse_isoish_datetime((last_completed or {}).get("completed_at") or (last_completed or {}).get("created_at"))
        feedback_sent_at = _parse_isoish_datetime((last_completed or {}).get("tutor_feedback_sent_at"))
        report_email_sent_at = _parse_isoish_datetime((last_completed or {}).get("student_completion_email_sent_at"))
        if report_email_sent_at and feedback_sent_at is None:
            review_pending = True
            if completed_at:
                deadline = completed_at + timedelta(hours=float(config.TUTOR_FEEDBACK_WINDOW_HOURS))
                payload["tutor_feedback_deadline"] = deadline.isoformat().replace("+00:00", "Z")
            payload["review_pending"] = True
            payload["main_screen_state"] = "review_pending"
            payload["main_screen_message"] = f"{coach_name} is analysing your homework and will send you the grading and comment soon. If you pass, we will see each other in the next step!"
            payload["tutor_feedback_message"] = payload["main_screen_message"]
            payload["report_delivered"] = True
    except Exception:
        pass
    if not review_pending:
        try:
            payload["assigned_exercises"] = db.v2_get_assigned_exercises_for_user(user_id)
            for ex in payload.get("assigned_exercises") or []:
                if (ex.get("title") or "").strip().lower() == "0-intro":
                    if not (ex.get("video_url") or "").strip() and getattr(config, "INTRO_0_VIDEO_URL", None):
                        ex["video_url"] = config.INTRO_0_VIDEO_URL
                    if not (ex.get("description") or "").strip() and getattr(config, "INTRO_0_DESCRIPTION", None):
                        ex["description"] = config.INTRO_0_DESCRIPTION
                    break
        except Exception:
            payload["assigned_exercises"] = []
    try:
        overrides = db.v2_get_student_overrides(user_id) or {}
        msg = (overrides.get("pending_tutor_video_description") or "").strip()
        if msg and feedback_sent_at is not None:
            payload["tutor_video_description"] = msg
    except Exception:
        pass
    return payload


# ---------- Start & status ----------
@homework_bp.route("/session/start", methods=["POST"])
@require_auth
def homework_session_start():
    """Start or resume homework session. Returns session_id and one task string."""
    try:
        user_id = request.user_id

        active = db.v2_get_active_homework_session(user_id)
        if active and db.v2_session_expired(active):
            db.v2_delete_session(active["id"], user_id)
            active = None
        if active:
            wid = active.get("warm_up_task_id")
            wtext = (active.get("warm_up_task_text") or "").strip()

            task = _task_payload(wid, wtext)
            if task is None:
                db.v2_ensure_default_warm_up_task(user_id)
                warm_up = db.v2_get_assigned_warm_up_task(user_id)
                if not warm_up:
                    return jsonify({
                        "code": "NO_WARMUP_CONFIGURED",
                        "message": "No task is configured for your account. Please contact your coach to get started.",
                        "details": {},
                    }), 422
                text = (warm_up.get("text") or "").strip()
                if not text:
                    return jsonify({"code": "INVALID_STATE", "error": "Task has empty text"}), 500
                db.v2_update_session(active["id"], user_id, {
                    "warm_up_task_id": warm_up.get("id"),
                    "warm_up_task_text": text,
                })
                task = _task_payload(warm_up.get("id"), text)

            return jsonify({
                "session_id": active["id"],
                "task": _task_text(task.get("text") if task else None),
            }), 200

        db.v2_ensure_default_warm_up_task(user_id)
        warm_up = db.v2_get_assigned_warm_up_task(user_id)
        if not warm_up:
            return jsonify({
                "code": "NO_WARMUP_CONFIGURED",
                "message": "No task is configured for your account. Please contact your coach to get started.",
                "details": {},
            }), 422

        text = (warm_up.get("text") or "").strip()
        if not text:
            return jsonify({"code": "INVALID_STATE", "error": "Task has empty text"}), 500

        session = db.v2_create_homework_session(user_id)
        if not session:
            return jsonify({"code": "V2_ERROR", "error": "Failed to create session"}), 500

        pending_video_url, pending_video_description = db.v2_get_and_clear_pending_tutor_video(user_id)
        prefs = db.v2_get_user_metric_questions(user_id)
        session_update = {
            "session_metric_question_1": (prefs.get("metric_question_1") or "").strip(),
            "session_metric_question_2": (prefs.get("metric_question_2") or "").strip(),
            "session_metric_question_3": (prefs.get("metric_question_3") or "").strip(),
            "warm_up_task_id": warm_up.get("id"),
            "warm_up_task_text": text,
        }
        if pending_video_url:
            session_update["tutor_video_url"] = pending_video_url
        if pending_video_description is not None:
            session_update["tutor_video_description"] = pending_video_description
        db.v2_update_session(session["id"], user_id, session_update)

        return jsonify({
            "session_id": session["id"],
            "task": _task_text(text),
        }), 201

    except Exception as e:
        logger.error(f"Homework session start: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@homework_bp.route("/session/status", methods=["GET"])
@require_auth
def homework_session_status():
    """Get simplified single-recording homework session state."""
    # #region agent log
    try:
        _uid = getattr(request, "user_id", None)
        _agent_log("session/status entry", {"user_id": str(_uid) if _uid else None}, "E")
    except Exception:
        pass
    # #endregion
    try:
        user_id = request.user_id
        # #region agent log
        _agent_log("session/status before get_active", {"user_id": str(user_id)}, "C")
        # #endregion
        active = db.v2_get_active_homework_session(user_id)
        # #region agent log
        _agent_log("session/status after get_active", {"has_active": active is not None, "active_keys": list(active.keys()) if active else [], "date_types": [k for k, v in (active or {}).items() if hasattr(v, "isoformat")]}, "C")
        # #endregion
        if active and db.v2_session_expired(active):
            # #region agent log
            _agent_log("session/status expiring session", {"session_id": str(active["id"])}, "D")
            # #endregion
            db.v2_delete_session(active["id"], user_id)
            active = None
        if not active:
            _agent_log("session/status no active, building step0 payload", {}, "A")
            return jsonify(_build_step0_payload(user_id)), 200

        task = None
        wid = active.get("warm_up_task_id")
        wtext = (active.get("warm_up_task_text") or "").strip()

        if wtext:
            task = _task_payload(wid, wtext)
        elif active.get("status") == STATUS_WARM_UP:
            db.v2_ensure_default_warm_up_task(user_id)
            warm_up = db.v2_get_assigned_warm_up_task(user_id)
            if warm_up and (warm_up.get("text") or "").strip():
                text = (warm_up.get("text") or "").strip()
                db.v2_update_session(active["id"], user_id, {
                    "warm_up_task_id": warm_up.get("id"),
                    "warm_up_task_text": text,
                })
                task = _task_payload(warm_up.get("id"), text)

        # #region agent log
        _sid = str(active.get("id") or "")
        _agent_log("session/status about to jsonify active", {"session_id": _sid, "session_id_len": len(_sid), "user_id": user_id, "has_datetime_values": [k for k, v in active.items() if hasattr(v, "isoformat")]}, "B")
        # #endregion
        # Debug: confirm row still exists in DB at the moment we return it (rules out "status not reading from DB")
        _row_check = db.v2_get_session_by_id(_sid)
        logger.info(
            "STATUS returning session_id: %s | row_still_exists_in_db: %s",
            _sid,
            _row_check is not None,
        )
        resp = {
            "status": _public_status(active.get("status")),
            "session_id": str(active["id"]),
            "recording_id": _public_recording_id(active),
            "task": _task_text(task.get("text") if task else None),
            "assigned_exercises": [],
            "tutor_feedback_deadline": None,
            "tutor_feedback_message": None,
            "tutor_video_description": None,
        }
        # Coach message for "A message for you" block (text-only on homework; tutor_video_url not used by frontend)
        msg = (active.get("tutor_video_description") or "").strip()
        if msg:
            resp["tutor_video_description"] = msg
        return jsonify(resp), 200

    except Exception as e:
        # #region agent log
        _agent_log("session/status exception", {"type": type(e).__name__, "message": str(e)}, "ALL")
        # #endregion
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@homework_bp.route("/session/<session_id>/abandon", methods=["POST"])
@require_auth
def homework_abandon_session(session_id):
    """Delete the homework session (owner only). Works for any status including completed. User has no active session afterward; GET status returns has_active_session: false. Client should refetch status and show the first page (Start)."""
    try:
        user_id = request.user_id
        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        db.v2_delete_session(session_id, user_id)
        # Clear in-memory sniper state; non-fatal if it fails.
        try:
            clear_sniper_session(session_id)
        except Exception as ce:
            logger.warning(f"clear_sniper_session failed (non-fatal): {ce}")
        return jsonify({"deleted": True, "message": "Session deleted. Refetch status and show the start page."}), 200
    except Exception as e:
        logger.error(f"Homework abandon session: {str(e)}", exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@homework_bp.route("/sessions", methods=["GET"])
@require_auth
def homework_list_sessions():
    """List the current user's sessions with report previews and recording info.
    Used by the step-0 'View reports' panel on the frontend.
    Returns up to 20 most-recent sessions that have either a recording or a report."""
    try:
        user_id = request.user_id
        sessions = db.v2_get_sessions_with_previews(user_id, limit=20)
        sessions = [s for s in sessions if s.get("report_delivered")]
        return jsonify({"sessions": sessions}), 200
    except Exception as e:
        logger.error(f"homework_list_sessions: {str(e)}", exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@homework_bp.route("/session/<session_id>/leave-report", methods=["POST"])
@require_auth
def homework_leave_report(session_id):
    """Leave the report screen and return to step 0. Use when the user clicks the report CTA (e.g. 'Send the homework to the coach!'). Session must be completed. Returns the same payload as GET session/status when there is no active session, so the frontend can transition to step 0 in one call."""
    try:
        user_id = request.user_id
        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        if session.get("status") != STATUS_COMPLETED:
            return jsonify({
                "code": "REPORT_NOT_COMPLETED",
                "error": "Session must be completed to leave the report",
                "status": session.get("status"),
            }), 409
        payload = _build_step0_payload(user_id)
        return jsonify(payload), 200
    except Exception as e:
        logger.exception("Homework leave-report: %s", e)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Step 1: task (GET) + recording_1 (POST) ----------
@homework_bp.route("/session/<session_id>/warm-up-task", methods=["GET"])
@require_auth
def homework_get_warm_up_task(session_id):
    """Get the step-1 task for this session. Snapshot-first for deterministic resume."""
    try:
        user_id = request.user_id
        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        if session.get("status") != STATUS_WARM_UP:
            return jsonify({
                "code": "INVALID_SESSION_STATE",
                "error": "Session must be in task",
                "status": session.get("status"),
            }), 409

        wid = session.get("warm_up_task_id")
        wtext = (session.get("warm_up_task_text") or "").strip()

        if wtext:
            return jsonify({"task": _task_text(wtext)}), 200

        db.v2_ensure_default_warm_up_task(user_id)
        warm_up = db.v2_get_assigned_warm_up_task(user_id)
        if not warm_up:
            return jsonify({
                "code": "NO_WARMUP_CONFIGURED",
                "message": "No task is configured for your account. Please contact your coach to get started.",
                "details": {},
            }), 422

        text = (warm_up.get("text") or "").strip()
        if not text:
            return jsonify({"code": "INVALID_STATE", "error": "Task has empty text"}), 500

        db.v2_update_session(session_id, user_id, {
            "warm_up_task_id": warm_up.get("id"),
            "warm_up_task_text": text,
        })
        return jsonify({"task": _task_text(text)}), 200

    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@homework_bp.route("/session/<session_id>/self-rating", methods=["POST"])
@require_auth
def homework_self_rating(session_id):
    """Post-recording self-rate (1–5) or skip. Completion (report + coach email) happens only after this step.
    Body: { "rating": 1-5 } or legacy { "student_rating_1_10": 1-5 }, or { "skipped": true }."""
    try:
        user_id = request.user_id
        session = db.v2_get_session(session_id, user_id)
        token_payload = getattr(request, "token_payload", {}) or {}
        preferred_student_email = token_payload.get("email")
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        status = session.get("status")
        if status not in (STATUS_TASK_BLOCK, STATUS_COMPLETING_FROM_RECORDING_1, STATUS_COMPLETED):
            return jsonify({
                "code": "INVALID_SESSION_STATE",
                "error": "Self-rating is only available after you have submitted your recording.",
                "status": status,
            }), 409
        data = request.get_json() or {}
        skipped = data.get("skipped") is True
        rating = None if skipped else (data.get("student_rating_1_10") if data.get("student_rating_1_10") is not None else data.get("rating"))
        if not skipped and rating is None:
            return jsonify({"code": "MISSING_RATING", "error": "rating or student_rating_1_10 (1-5) required, or skipped: true"}), 400
        if not skipped:
            try:
                r = int(rating)
            except (TypeError, ValueError):
                return jsonify({"code": "INVALID_RATING", "error": "rating must be 1-5"}), 422
            if not (1 <= r <= 5):
                return jsonify({"code": "INVALID_RATING", "error": "rating must be 1-5"}), 422
            ok = db.update_or_set_session_sniper_rating(session_id, user_id, r)
            if not ok:
                return jsonify({"code": "V2_ERROR", "error": "Could not save rating"}), 500
            saved_rating = r
        else:
            saved_rating = None
        try:
            db.v2_update_session(session_id, user_id, {
                "self_rating_submitted_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            })
        except Exception as flag_err:
            logger.warning("homework_self_rating: could not set self_rating_submitted_at: %s", flag_err)

        # Completion depends on self-rating: build report, mark completed, send coach email when job is done.
        session_completed = False
        if status == STATUS_COMPLETING_FROM_RECORDING_1 and session.get("recording_1_processing_status") == "completed":
            # #region agent log
            _agent_log("POST self-rating attempting completion", {"session_id": session_id, "recording_1_processing_status": session.get("recording_1_processing_status")}, "H4")
            # #endregion
            payload_out = complete_session_recording_1_only(
                session_id,
                user_id,
                preferred_student_email=preferred_student_email,
            )
            if payload_out:
                session_completed = True
                logger.info("homework_self_rating: session completed after self-rating session_id=%s", session_id)
            else:
                logger.warning("homework_self_rating: complete_session_recording_1_only returned None session_id=%s", session_id)
            # #region agent log
            _agent_log("POST self-rating completion result", {"session_id": session_id, "session_completed": session_completed}, "H4")
            # #endregion
        elif status == STATUS_COMPLETING_FROM_RECORDING_1 and session.get("recording_1_processing_status") == "failed":
            # Recovery: job failed; give the user a completed session with a minimal report.
            try:
                if minimal_complete_and_notify(
                    session_id,
                    user_id,
                    preferred_student_email=preferred_student_email,
                ):
                    session_completed = True
                    logger.info("homework_self_rating: minimal fallback completion ran session_id=%s", session_id)
                else:
                    logger.warning("homework_self_rating: minimal fallback returned False session_id=%s", session_id)
            except Exception as sr_fallback_err:
                logger.warning("homework_self_rating: minimal fallback failed session_id=%s: %s", session_id, sr_fallback_err)
        elif status == STATUS_COMPLETED:
            session_completed = True
            ensure_student_completion_email(
                session_id,
                user_id,
                preferred_student_email=preferred_student_email,
            )

        sniper_profile = db.get_sniper_profile_payload(user_id)
        out = {
            "status": "ok",
            "session_completed": session_completed,
            "sniper_profile": sniper_profile,
            "realtime_level": sniper_profile.get("realtime_level"),
            "realtime_step": sniper_profile.get("realtime_step"),
        }
        if saved_rating is not None:
            out["rating"] = saved_rating
            out["student_rating_1_10"] = saved_rating
        if skipped:
            out["skipped"] = True
        return jsonify(out), 200
    except Exception as e:
        logger.exception("Homework self-rating: %s", e)
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
    """Mint a storage path for the single homework recording upload."""
    # #region agent log
    try:
        _debug_log_write({"hypothesisId": "H0", "location": "homework.py:recording-upload-url", "message": "entry", "data": {"session_id": str(session_id)[:36]}, "timestamp": int(time.time() * 1000)})
    except Exception:
        pass
    # #endregion
    try:
        from config import Config
        config = Config()
        user_id = request.user_id
        data = request.get_json() or {}

        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        status = session.get("status")
        if status != STATUS_WARM_UP:
            # Already past recording 1 (e.g. report generating or completed) — return 200 so frontend doesn't 409
            if status in (STATUS_COMPLETING_FROM_RECORDING_1, STATUS_COMPLETED):
                return jsonify({
                    "already_submitted": True,
                    "storage_path": None,
                    "bucket": config.AUDIO_BUCKET_NAME,
                    "message": "You already submitted your recording. Your report is being generated or ready.",
                }), 200
            _agent_log("recording-upload-url: 409 rec=1 wrong status", {"session_id": session_id, "status": status}, "H_upload")
            return jsonify({"code": "INVALID_SESSION_STATE", "error": "Session must be in warm_up for recording-1", "status": status}), 409

        storage_path = _storage_path_for_session(user_id, session_id)
        resp_payload = {
            "storage_path": storage_path,
            "bucket": config.AUDIO_BUCKET_NAME,
        }
        # #region agent log
        try:
            _debug_log_write({"hypothesisId": "H1", "location": "homework.py:recording-upload-url", "message": "upload-url response shape", "data": {"keys": list(resp_payload.keys()), "storage_path_type": type(storage_path).__name__, "bucket_type": type(config.AUDIO_BUCKET_NAME).__name__, "has_upload_url": "upload_url" in resp_payload}, "timestamp": int(time.time() * 1000)})
        except Exception:
            pass
        # #endregion
        upload_url_str = db.create_signed_upload_url(config.AUDIO_BUCKET_NAME, storage_path)
        if isinstance(upload_url_str, str) and upload_url_str:
            resp_payload["upload_url"] = upload_url_str
            resp_payload["signed_url_available"] = True
        else:
            resp_payload["signed_url_available"] = False
        # #region agent log
        try:
            _debug_log_write({"hypothesisId": "H2", "location": "homework.py:recording-upload-url", "message": "after upload_url", "data": {"has_upload_url": "upload_url" in resp_payload, "upload_url_type": type(resp_payload.get("upload_url")).__name__ if resp_payload.get("upload_url") else "none"}, "timestamp": int(time.time() * 1000)})
        except Exception:
            pass
        # #endregion
        response = jsonify(resp_payload)
        response.headers["X-Upload-Url-Type"] = "signed" if resp_payload.get("signed_url_available") else "path"
        return response
    except Exception as e:
        logger.error(f"recording-upload-url: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@homework_bp.route("/session/<session_id>/recording-1", methods=["POST"])
@require_auth
def homework_submit_recording_1(session_id):
    """Upload the single homework recording and return the report-generating state."""
    try:
        from config import Config
        from services.recording_1_job import enqueue_recording_1_job

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
        center_hold_ratio = None

        if audio_file:
            # Multipart: upload only, no transcription in request
            ext = ".webm"
            storage_path = f"{user_id}/{session_id}/{uuid.uuid4()}{ext}"
            audio_file.seek(0)
            audio_data = audio_file.read()
            content_type = str(audio_file.content_type or "audio/webm")
            if content_type in ("True", "False"):
                content_type = "audio/webm"
            db.upload_audio(config.AUDIO_BUCKET_NAME, storage_path, audio_data, content_type=content_type)
            try:
                duration_seconds = float(request.form.get("duration_seconds")) if request.form.get("duration_seconds") else None
            except (TypeError, ValueError):
                duration_seconds = None
            chr_raw = request.form.get("center_hold_ratio")
            if chr_raw in (None, ""):
                chr_raw = request.form.get("centerHoldRatio")
            if chr_raw not in (None, ""):
                try:
                    center_hold_ratio = float(chr_raw)
                except (TypeError, ValueError):
                    center_hold_ratio = None
        else:
            # JSON: storage_path + duration_seconds (direct-to-storage)
            storage_path = (data.get("storage_path") or "").strip()
            duration_seconds = data.get("duration_seconds")
            chr_raw = data.get("center_hold_ratio")
            if chr_raw is None:
                chr_raw = data.get("centerHoldRatio")
            if not storage_path or duration_seconds is None:
                return jsonify({"code": "INVALID_INPUT", "error": "Either send multipart 'audio' or JSON with storage_path and duration_seconds"}), 400
            if not _validate_storage_path(storage_path, user_id, session_id):
                return jsonify({"code": "INVALID_INPUT", "error": "storage_path invalid or not allowed for this session"}), 400
            try:
                duration_seconds = float(duration_seconds)
            except (TypeError, ValueError):
                return jsonify({"code": "INVALID_INPUT", "error": "duration_seconds must be a number"}), 400
            if chr_raw is not None:
                try:
                    center_hold_ratio = float(chr_raw)
                except (TypeError, ValueError):
                    center_hold_ratio = None
            # Idempotency: same storage_path → return existing (always report_generating; steps 2–4 removed)
            existing_rid = session.get("recording_1_id")
            if existing_rid:
                existing = db.get_recording(existing_rid, user_id)
                if existing and (existing.get("storage_path") or "").strip() == storage_path:
                    db.v2_update_session(session_id, user_id, {"status": STATUS_COMPLETING_FROM_RECORDING_1})
                    return jsonify({
                        "recording_id": existing["id"],
                        "status": PUBLIC_STATUS_REPORT_GENERATING,
                    }), 200
            # New recording for this session: create minimal, update session, enqueue

        # Client-side Web Speech transcript (fallback when Whisper fails or is slow)
        client_transcript = (data.get("transcript_text") or "").strip() if isinstance(data, dict) else ""

        # Create minimal recording row (job will fill transcript, wpm, etc.)
        minimal_recording = {
            "user_id": user_id,
            "session_id": None,
            "session_v2_id": session_id,
            "storage_path": storage_path,
            "audio_url": "",
            "duration": 0,
        }
        if duration_seconds is not None:
            minimal_recording["duration_seconds"] = duration_seconds
        # Pre-fill transcript from client so it's available immediately even before Whisper runs
        if client_transcript:
            minimal_recording["transcription_text"] = client_transcript
        recording = db.create_recording(minimal_recording)
        if not recording:
            return jsonify({"code": "RECORDING_CREATE_FAILED"}), 500

        db.v2_update_session(session_id, user_id, {
            "recording_1_id": recording["id"],
            "status": STATUS_TASK_BLOCK,
            "recording_1_processing_status": "pending",
        })

        enqueue_recording_1_job(
            session_id,
            str(recording["id"]),
            storage_path,
            user_id,
            duration_seconds,
            center_hold_ratio=center_hold_ratio,
        )

        # TEMPORARY: steps 2–4 fully removed → always complete from recording 1 only
        db.v2_update_session(session_id, user_id, {"status": STATUS_COMPLETING_FROM_RECORDING_1})
        _agent_log("recording-1: completing from recording 1 only (steps 2–4 removed)", {"session_id": session_id}, "H5")
        return jsonify({
            "status": PUBLIC_STATUS_REPORT_GENERATING,
            "recording_id": recording["id"],
        }), 200
    except Exception as e:
        _agent_log("recording-1: exception", {"error": str(e), "type": type(e).__name__}, "H5")
        logger.error(f"Homework recording-1: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Sniper Wheel real-time metrics ----------
_sniper_rate_limit: dict = {}  # (user_id, session_id) -> [timestamps]
SNIPER_RATE_LIMIT_PER_MINUTE = 120


def _sniper_rate_limit_check(user_id: str, session_id: str) -> bool:
    """True if request is within limit (120/min per user+session)."""
    import time as _time
    key = (user_id, session_id)
    now = _time.time()
    cutoff = now - 60.0
    if key not in _sniper_rate_limit:
        _sniper_rate_limit[key] = []
    times = _sniper_rate_limit[key]
    times[:] = [t for t in times if t > cutoff]
    if len(times) >= SNIPER_RATE_LIMIT_PER_MINUTE:
        return False
    times.append(now)
    return True


def _sniper_fallback_payload(seq=0, t_ms=0):
    """Static payload so frontend always gets a valid response on error."""
    return {
        "active": True,
        "seq": seq,
        "t_ms": t_ms,
        "simple_live": {
            "pause_ratio": 0.0,
            "flow_score": None,
            "performance_score": None,
            "flow_offset": 0.0,
            "pace_offset": 0.0,
            "coach_color": "gray",
            "voiced_ratio": 0.0,
            "silence_gated": True,
        },
    }


@homework_bp.route("/session/<session_id>/sniper-metrics-chunk", methods=["GET"])
@require_auth
def homework_sniper_ready(session_id):
    """GET so frontend can probe: backend Sniper is available. Returns 200 + { ready: true }. If 404, use client-side-only wheel."""
    user_id = request.user_id
    session = db.v2_get_session(session_id, user_id)
    if not session:
        return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
    return jsonify({"ready": True, "active": True}), 200


@homework_bp.route("/session/<session_id>/sniper-metrics-chunk", methods=["POST"])
@require_auth
def homework_sniper_metrics_chunk(session_id):
    """
    Real-time Sniper Wheel metrics. Body: raw PCM16 mono (optional). Headers: X-Sample-Rate, X-Seq, X-T-Ms;
    optional X-WPM, X-Debug. Returns segments, overall_score, tier, coaching_message, active, etc.
    On any backend error we return 200 with a fallback payload so the wheel still "starts" (like before: client-side fallback).
    """
    seq = 0
    t_ms = 0
    try:
        seq = int(request.headers.get("X-Seq") or "0")
    except ValueError:
        pass
    try:
        t_ms = int(request.headers.get("X-T-Ms") or "0")
    except ValueError:
        pass

    user_id = request.user_id
    session = db.v2_get_session(session_id, user_id)
    if not session:
        return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
    if not _sniper_rate_limit_check(user_id, session_id):
        return jsonify({"code": "RATE_LIMIT", "error": "Too many requests; 120 per minute per session."}), 429

    try:
        sample_rate = int(request.headers.get("X-Sample-Rate") or "16000")
    except ValueError:
        sample_rate = 16000
    client_wpm = None
    wpm_h = request.headers.get("X-WPM")
    if wpm_h and str(wpm_h).strip():
        try:
            client_wpm = float(wpm_h)
        except ValueError:
            pass
    include_debug = (request.headers.get("X-Debug") or "").strip().lower() in ("true", "1", "yes")

    pcm_bytes = request.get_data(cache=True)
    if not isinstance(pcm_bytes, bytes):
        pcm_bytes = b""

    try:
        from services.sniper_realtime import process_sniper_chunk
        from services.sniper_scoring import compute_simple_live
    except Exception as imp_err:
        logger.warning("Sniper imports failed, using fallback: %s", imp_err)
        return jsonify(_sniper_fallback_payload(seq, t_ms)), 200

    debug = {}
    try:
        inputs, debug = process_sniper_chunk(
            pcm_bytes,
            sample_rate,
            session_id,
            seq=seq,
            t_ms=t_ms,
            client_wpm=client_wpm,
            include_debug=include_debug,
        )
    except Exception as chunk_err:
        logger.warning("Sniper process_sniper_chunk failed, using fallback: %s", chunk_err)
        return jsonify(_sniper_fallback_payload(seq, t_ms)), 200

    try:
        simple_live = compute_simple_live(
            pause_ratio=inputs.get("pause_ratio"),
            client_wpm=inputs.get("client_wpm"),
            voiced_ratio=inputs.get("voiced_ratio", 0.0),
            silence_gated=inputs.get("silence_gated", True),
        )
    except Exception as score_err:
        logger.warning("Sniper compute_simple_live failed, using fallback: %s", score_err)
        return jsonify(_sniper_fallback_payload(seq, t_ms)), 200

    payload = {
        "active": True,
        "seq": seq,
        "t_ms": t_ms,
        "simple_live": simple_live,
    }
    if include_debug:
        payload["_debug"] = debug
    return jsonify(payload), 200


@homework_bp.route("/session/<session_id>/report", methods=["GET"])
@require_auth
def homework_get_report(session_id):
    """Get report data for a completed session (step 5). Returns report_text, scores (warmup, final, overall 0-100), final_recording { id, audio_url } with fresh signed URL, and performance_history (last 5 completed sessions: date, score 0-100, oldest first). Owner-only; session must be completed."""
    try:
        from config import Config
        config = Config()
        user_id = request.user_id
        token_payload = getattr(request, "token_payload", {}) or {}
        preferred_student_email = token_payload.get("email")
        session = db.v2_get_session(session_id, user_id)
        # #region agent log
        _agent_log("GET report entry", {"session_id": session_id, "user_id": user_id, "status": session.get("status") if session else None, "recording_1_processing_status": session.get("recording_1_processing_status") if session else None}, "H1")
        # #endregion
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        if session.get("status") != STATUS_COMPLETED:
            # Fallback: if job is done but frontend never triggered completion (e.g. self-rating was called too early and not retried), run completion once so polling GET report eventually succeeds.
            if session.get("status") == STATUS_COMPLETING_FROM_RECORDING_1 and session.get("recording_1_processing_status") == "completed":
                # #region agent log
                _agent_log("GET report running fallback completion", {"session_id": session_id}, "H2")
                # #endregion
                try:
                    if complete_session_recording_1_only(
                        session_id,
                        user_id,
                        preferred_student_email=preferred_student_email,
                    ):
                        session = db.v2_get_session(session_id, user_id)
                        logger.info("homework_get_report: fallback completion ran session_id=%s", session_id)
                        # #region agent log
                        _agent_log("GET report after fallback re-fetch", {"session_id": session_id, "status": session.get("status") if session else None}, "H2")
                        # #endregion
                except Exception as fallback_err:
                    logger.warning("homework_get_report: fallback completion failed: %s", fallback_err)
            elif session.get("status") == STATUS_COMPLETING_FROM_RECORDING_1 and session.get("recording_1_processing_status") == "failed":
                # Recovery: job failed and its own minimal_complete_and_notify may also have failed.
                # Polling GET report is a second-chance to complete the session so the user isn't stuck forever.
                _agent_log("GET report running minimal fallback for failed job", {"session_id": session_id}, "H2")
                try:
                    if minimal_complete_and_notify(
                        session_id,
                        user_id,
                        preferred_student_email=preferred_student_email,
                    ):
                        session = db.v2_get_session(session_id, user_id)
                        logger.info("homework_get_report: minimal fallback completion ran session_id=%s", session_id)
                except Exception as fallback_err:
                    logger.warning("homework_get_report: minimal fallback completion failed: %s", fallback_err)
            if session.get("status") != STATUS_COMPLETED:
                # #region agent log
                _agent_log("GET report returning 409", {"session_id": session_id, "status": session.get("status")}, "H1")
                # #endregion
                # 409 so frontend can distinguish "not ready yet, retry" from "session not found" (404)
                return jsonify({"code": "REPORT_NOT_READY", "error": "Report is only available for completed sessions", "status": session.get("status")}), 409
        else:
            ensure_student_completion_email(
                session_id,
                user_id,
                preferred_student_email=preferred_student_email,
            )

        report_text = (session.get("context_long") or "").strip()
        if session.get("report_id"):
            try:
                r = db.client.table("v2_reports").select("report_text").eq("id", session["report_id"]).execute()
                if r.data and r.data[0].get("report_text"):
                    report_text = (r.data[0]["report_text"] or "").strip()
            except Exception:
                pass

        has_rec_2 = bool(session.get("recording_2_id"))
        perf_1 = float(session.get("performance_score_1") or 0)
        perf_2 = float(session.get("performance_score_2") or 0) if has_rec_2 else perf_1
        perf_end = float(session.get("performance_score_end") or 0)
        filler_count_for_cap = 0
        try:
            cap_recording_id = session.get("recording_2_id") or session.get("recording_1_id")
            if cap_recording_id:
                cap_rec = db.get_recording(cap_recording_id, user_id)
                cap_fillers = cap_rec.get("filler_words_count") if isinstance(cap_rec, dict) else {}
                if isinstance(cap_fillers, dict):
                    filler_count_for_cap = int(cap_fillers.get("total", 0) or 0)
        except Exception:
            filler_count_for_cap = 0
        # Prefer Sniper (Voice Alignment) as the single display score when available
        score_for_display_100 = round(perf_end * 100)
        session_sniper = None
        try:
            session_sniper = db.get_session_sniper_metrics(session_id)
            if session_sniper and session_sniper.get("stage_score") is not None:
                raw = float(session_sniper["stage_score"])
                score_for_display_100 = round(raw) if raw > 1 else round(raw * 100)
                score_for_display_100 = max(0, min(100, score_for_display_100))
                new_perf_end = score_for_display_100 / 100.0
                # Self-heal: if stored performance_score_end differs significantly from sniper score
                # (race condition: minimal_complete_and_notify ran before sniper metrics reached DB),
                # update the stored value so future performance_history queries show the correct score.
                if abs(perf_end - new_perf_end) > 0.02:
                    try:
                        db.v2_update_session(session_id, user_id, {"performance_score_end": new_perf_end})
                        logger.info(
                            "homework_get_report: corrected performance_score_end %.3f→%.3f session_id=%s",
                            perf_end, new_perf_end, session_id,
                        )
                    except Exception as heal_err:
                        logger.warning("homework_get_report: could not correct performance_score_end: %s", heal_err)
                perf_end = new_perf_end
        except Exception:
            pass
        if filler_count_for_cap > 0 and score_for_display_100 >= 100:
            score_for_display_100 = 99
            perf_end = min(perf_end, 0.99)
        # Frontend: use score_for_display (Sniper Voice Alignment when available) for "your result" and the chart.

        history_rows = db.v2_get_performance_history(user_id, limit=5)
        performance_history = []
        for row in history_rows:
            created_at = row.get("created_at")
            score_01 = row.get("performance_score_end", 0) or 0
            row_session_id = row.get("session_id")
            # Use Sniper score for current session so chart matches Voice Alignment
            if row_session_id == session_id:
                bar_score = score_for_display_100
            else:
                bar_score = round(float(score_01) * 100)
            if isinstance(created_at, str) and len(created_at) >= 10:
                date_str = created_at[:10]
            elif hasattr(created_at, "isoformat"):
                date_str = created_at.isoformat()[:10]
            elif created_at:
                date_str = str(created_at)[:10]
            else:
                date_str = ""
            if date_str:
                performance_history.append({"date": date_str, "score": bar_score})

        # Display recording: recording_2 if present, else recording_1 (for playback, transcript, fillers)
        display_recording_id = session.get("recording_2_id") or session.get("recording_1_id")
        final_recording = {"id": None, "audio_url": None}
        recording_payload = None  # full transcript, fillers, playback for report view
        if display_recording_id:
            rec = db.get_recording(display_recording_id, user_id)
            if rec:
                storage_path = (rec.get("storage_path") or "").strip()
                audio_url = None
                if storage_path:
                    try:
                        audio_url = db.create_signed_url(
                            config.AUDIO_BUCKET_NAME,
                            storage_path,
                            config.SIGNED_URL_EXPIRY_SECONDS,
                        )
                    except Exception as e:
                        logger.warning("Report: could not create signed URL for recording %s: %s", display_recording_id, e)
                        # Fallback 1: use the job-stored audio_url (a recently-created signed URL from the job)
                        fallback_url = (rec.get("audio_url") or "").strip()
                        if fallback_url and fallback_url.startswith("http"):
                            audio_url = fallback_url
                            logger.info("Report: using stored audio_url fallback for recording %s", display_recording_id)
                        else:
                            # Fallback 2: public object URL (works for public buckets; better than no URL)
                            try:
                                supabase_url_base = config.SUPABASE_URL.rstrip("/")
                                audio_url = f"{supabase_url_base}/storage/v1/object/public/{config.AUDIO_BUCKET_NAME}/{storage_path}"
                            except Exception:
                                pass  # audio_url stays None
                final_recording["id"] = str(display_recording_id) if display_recording_id is not None else None
                # Ensure audio_url is always a string or None for JSON (avoid "not transferrable" when frontend expects string)
                if audio_url is not None and not isinstance(audio_url, str):
                    audio_url = str(audio_url) if audio_url else None
                final_recording["audio_url"] = audio_url
                # #region agent log
                try:
                    _debug_log_write({"hypothesisId": "H3", "location": "homework.py:report", "message": "report audio_url type", "data": {"audio_url_type": type(audio_url).__name__ if audio_url is not None else "NoneType", "is_string": isinstance(audio_url, str)}, "timestamp": int(time.time() * 1000)})
                except Exception:
                    pass
                # #endregion
                filler_data = rec.get("filler_words_count") or {}
                if not isinstance(filler_data, dict):
                    filler_data = {}
                recording_payload = {
                    "id": str(display_recording_id) if display_recording_id is not None else None,
                    "audio_url": audio_url if (audio_url is None or isinstance(audio_url, str)) else str(audio_url),
                    "transcription_text": (rec.get("transcription_text") or "").strip(),
                    "filler_words_count": {
                        "total": int(filler_data.get("total", 0) or 0),
                        "breakdown": dict(filler_data.get("breakdown") or {}),
                    },
                    "words_per_minute": round(float(rec.get("words_per_minute") or 0), 1),
                }

        sniper_profile = db.get_sniper_profile_payload(user_id)
        payload = {
            "report_text": report_text,
            # Backward-compat alias: some UIs still read scores.overall.
            "scores": {"overall": score_for_display_100},
            "performance_score_end": perf_end,
            "recording_count": 2 if has_rec_2 else 1,
            "final_recording": final_recording,
            "performance_history": performance_history,
            # Single canonical score (0-100): Sniper Voice Alignment when available. Same as last bar on chart.
            "score_for_display": score_for_display_100,
            "admin_grade": session.get("coach_grade"),
            "report_comment": (session.get("report_comment") or "").strip() or None,
            "sniper_profile": sniper_profile,
            "realtime_level": sniper_profile.get("realtime_level"),
            "realtime_step": sniper_profile.get("realtime_step"),
        }
        if recording_payload is not None:
            payload["recording"] = recording_payload
        context_short = (session.get("context_short") or "").strip()
        if context_short:
            payload["context_short"] = context_short
        coach_insight = (session.get("coach_insight") or "").strip()
        if not coach_insight:
            try:
                speaker_profile = db.v2_get_speaker_profile(user_id) or {}
                speaker_profile_context = (speaker_profile.get("coach_notes") or "").strip()
            except Exception:
                speaker_profile_context = ""
            filler_breakdown = {}
            transcript_excerpt = ""
            if recording_payload is not None:
                transcript_excerpt = (recording_payload.get("transcription_text") or "")[:300]
                filler_breakdown = dict((recording_payload.get("filler_words_count") or {}).get("breakdown") or {})
            history_scores = [float((row.get("score") or 0) / 100.0) for row in performance_history[-3:]]
            self_rating = None
            live_ball_score_100 = None
            if session_sniper:
                try:
                    self_rating = int(session_sniper.get("student_rating_1_10")) if session_sniper.get("student_rating_1_10") is not None else None
                except (TypeError, ValueError):
                    self_rating = None
                if session_sniper.get("stage_score") is not None:
                    try:
                        raw = float(session_sniper.get("stage_score"))
                        live_ball_score_100 = round(raw if raw > 1 else raw * 100)
                    except (TypeError, ValueError):
                        live_ball_score_100 = None
            coach_insight = openai_service.build_coach_insight_fallback(
                context_short=context_short,
                transcript_excerpt=transcript_excerpt,
                filler_breakdown=filler_breakdown,
                filler_count=int((recording_payload or {}).get("filler_words_count", {}).get("total", 0) or 0),
                performance_score=perf_end,
                performance_history_scores=history_scores,
                speaker_profile_context=speaker_profile_context,
                self_rating_1_10=self_rating,
                live_ball_score_100=live_ball_score_100,
            )
        if coach_insight:
            payload["coach_insight"] = coach_insight
        payload["report_cta"] = "Send the homework to the coach!"
        # Frontend: when user clicks the CTA, call POST .../leave-report to get step-0 state and show start screen (or call GET session/status).
        payload["leave_report_path"] = f"session/{session_id}/leave-report"
        # #region agent log
        _agent_log("GET report returning 200", {"session_id": session_id, "status": session.get("status"), "report_id": session.get("report_id")}, "H3")
        # #endregion
        return jsonify(payload), 200
    except Exception as e:
        logger.exception("Homework get report: %s", e)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500
