"""
Homework flow (TEMPORARY: steps 2–4 removed): task step + recording_1 → report only.
All routes under /v2/homework, require auth. Restore steps 2–4 from docs/TEMPORARY-REMOVED-STEPS-2-3-4-BACKUP.md or git history.
"""
from flask import Blueprint, request, jsonify, make_response
from auth import require_auth
from config import Config
from services.db import db
from services.email_service import email_service
from services.homework_completion import (
    complete_session_recording_1_only,
    ensure_student_completion_email,
    best_effort_backfill_recording_1_transcript,
    minimal_complete_and_notify,
)
from services.sniper_realtime import clear_sniper_session
from services.stripe_checkout_credits import apply_paid_checkout_session_credits
from services.utils import utc_now_iso
from services.tutor_video_url import resolve_tutor_video_playable_url
import logging
import os
import time
import uuid
import sentry_sdk
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
config = Config()
homework_bp = Blueprint("homework", __name__, url_prefix="/v2/homework")


def _json_homework_no_store(payload, status=200):
    """Credits and session state must never be served from SW/browser disk cache."""
    r = make_response(jsonify(payload), status)
    r.headers["Cache-Control"] = "private, no-store, max-age=0, must-revalidate"
    r.headers["Vary"] = "Authorization"
    return r


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
STATUS_TASK = "task"
_LEGACY_STATUS_TASK = "warm_up"  # pre-migration rows; see rename_homework_session_status_warm_up_to_task.sql
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
        STATUS_TASK: PUBLIC_STATUS_RECORDING_1_REQUIRED,
        _LEGACY_STATUS_TASK: PUBLIC_STATUS_RECORDING_1_REQUIRED,
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


def _session_status_allows_task_step(status) -> bool:
    return status == STATUS_TASK or status == _LEGACY_STATUS_TASK


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
    recording_id = session.get("recording_1_id")
    return str(recording_id) if recording_id else None


def _session_snap_task_id(session: dict):
    """Homework task row id snapshot on v2_sessions (public.tasks)."""
    tid = session.get("session_task_id")
    return tid


def _session_snap_task_text(session: dict) -> str:
    return (session.get("session_task_text") or "").strip()


def _persist_session_task(task_row_id, text: str) -> dict:
    return {"session_task_id": task_row_id, "session_task_text": text}


def _build_step0_payload(user_id: str) -> dict:
    """Build the session/status payload when there is no active session (step 0). Used by GET session/status only."""
    sniper_profile = db.get_sniper_profile_payload(user_id)
    coach_name = (getattr(config, "COACH_NAME", "Artur") or "Artur").strip().title() or "Artur"
    # Fetch credits for this student
    student_details = db.v2_get_student_details(user_id) or {}
    credits = student_details.get("credits")
    if credits is None:
        credits = 15
    payload = {
        "status": PUBLIC_STATUS_NONE,
        "session_id": None,
        "recording_id": None,
        "task": None,
        "assigned_exercises": [],
        "tutor_feedback_deadline": None,
        "tutor_feedback_message": None,
        "tutor_video_url": None,
        "tutor_video_description": None,
        "tutor_video_bucket": None,
        "tutor_video_storage_path": None,
        "review_pending": False,
        "report_delivered": False,
        "main_screen_state": "assignment_ready",
        "main_screen_message": None,
        "sniper_profile": sniper_profile,
        "realtime_level": sniper_profile.get("realtime_level"),
        "realtime_step": sniper_profile.get("realtime_step"),
        "credits": credits,
        # Explicit signal to the frontend that there is no active session.
        # Without this field the cold-load effect cannot distinguish "no active session"
        # from a fresh response, causing restorePersistedFinalReport to be skipped
        # and the cold-load to behave correctly only after a full logout cycle.
        "has_active_session": False,
    }
    review_pending = False
    feedback_sent_at = None
    try:
        last_completed = db.v2_get_last_completed_session(user_id)
        if (last_completed or {}).get("report_id"):
            payload["report_delivered"] = True
        completed_at = _parse_isoish_datetime((last_completed or {}).get("completed_at") or (last_completed or {}).get("created_at"))
        feedback_sent_at = _parse_isoish_datetime((last_completed or {}).get("tutor_feedback_sent_at"))
        report_email_sent_at = _parse_isoish_datetime((last_completed or {}).get("student_completion_email_sent_at"))
        # Treat as review_pending if:
        # (a) completion email already sent, or
        # (b) session is completed but email not yet dispatched by background job
        #     (timing gap: job is async; status is polled immediately after CTA click)
        session_completed = (last_completed or {}).get("status") == "completed"
        if (report_email_sent_at or session_completed) and feedback_sent_at is None:
            review_pending = True
            if completed_at:
                deadline = completed_at + timedelta(hours=float(config.TUTOR_FEEDBACK_WINDOW_HOURS))
                payload["tutor_feedback_deadline"] = deadline.isoformat().replace("+00:00", "Z")
            payload["review_pending"] = True
            payload["main_screen_state"] = "review_pending"
            payload["main_screen_message"] = f"{coach_name} is analysing your homework and will send you the grading and comment soon. If you pass, we will see each other in the next step!"
            payload["tutor_feedback_message"] = payload["main_screen_message"]
    except Exception:
        pass

    # assigned_exercises removed: step-0 media comes from tutor_video_* (send-assignment) only.
    # Pending coach video is for the *next* homework. Do not show it while the student is still in
    # review_pending (coach analysing the submission). Otherwise send-assignment sets
    # tutor_feedback_sent_at on the last completed session and we would expose the new video
    # before the UI leaves the reviewing state — refresh looks "stuck" until logout clears client state.
    if not review_pending:
        try:
            overrides = db.v2_get_student_overrides(user_id) or {}
            playable, tb, tp = resolve_tutor_video_playable_url(
                db=db,
                explicit_video_url=overrides.get("pending_tutor_video_url"),
                video_bucket=overrides.get("pending_tutor_video_bucket"),
                video_storage_path=overrides.get("pending_tutor_video_storage_path"),
            )
            msg = (overrides.get("pending_tutor_video_description") or "").strip()
            # Show pending media whenever not in review_pending (gate above). Do not require
            # tutor_feedback_sent_at — students with no completed session still need the coach video.
            if playable:
                payload["tutor_video_url"] = playable
            if tb:
                payload["tutor_video_bucket"] = tb
            if tp:
                payload["tutor_video_storage_path"] = tp
            if msg:
                payload["tutor_video_description"] = msg
        except Exception:
            pass

    # Fallback: if no personal coach video is queued for this student (first
    # login, never been assigned homework), show the most recent universal
    # welcome video uploaded by an admin in Training Studio (is_universal=true).
    if not payload.get("tutor_video_url") and not review_pending:
        try:
            uni = db.get_latest_universal_welcome_video()
        except Exception:
            uni = None
        if uni:
            uni_src_url = (uni.get("source_video_url") or "").strip() or None
            uni_fm = uni.get("feature_metadata") if isinstance(uni.get("feature_metadata"), dict) else {}
            uni_bucket = (uni.get("bucket") or uni_fm.get("bucket") or "").strip() or None
            uni_path = (uni.get("storage_path") or "").strip().lstrip("/") or None
            if uni_src_url and (uni_src_url.startswith("http://") or uni_src_url.startswith("https://")):
                payload["tutor_video_url"] = uni_src_url
            else:
                try:
                    pl, _b, _p = resolve_tutor_video_playable_url(
                        db=db,
                        explicit_video_url=None,
                        video_bucket=uni_bucket,
                        video_storage_path=uni_path,
                    )
                    if pl:
                        payload["tutor_video_url"] = pl
                        if _b:
                            payload["tutor_video_bucket"] = _b
                        if _p:
                            payload["tutor_video_storage_path"] = _p
                except Exception:
                    pass
            # Generic welcome copy (coach sets this in the upload form's title/description).
            welcome_desc = (
                (uni.get("title") or "").strip()
                or (uni_fm.get("title") or "").strip()
                or "Welcome! Your coach recorded this intro to get you started."
            )
            payload.setdefault("tutor_video_description", welcome_desc)
            payload["tutor_video_is_universal"] = True

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
            wid = _session_snap_task_id(active)
            wtext = _session_snap_task_text(active)

            task = _task_payload(wid, wtext)
            if task is None:
                db.v2_ensure_default_student_task(user_id)
                hw_task = db.v2_get_assigned_task_for_user(user_id)
                if not hw_task:
                    return jsonify({
                        "code": "NO_TASK_CONFIGURED",
                        "message": "No task is configured for your account. Please contact your coach to get started.",
                        "details": {},
                    }), 422
                text = (hw_task.get("text") or "").strip()
                if not text:
                    return jsonify({"code": "INVALID_STATE", "error": "Task has empty text"}), 500
                db.v2_update_session(active["id"], user_id, _persist_session_task(hw_task.get("id"), text))
                task = _task_payload(hw_task.get("id"), text)

            return jsonify({
                "session_id": active["id"],
                "task": _task_text(task.get("text") if task else None),
            }), 200

        # Block if last session is completed but coach hasn't sent feedback yet (review pending).
        last_completed = db.v2_get_last_completed_session(user_id)
        if last_completed and last_completed.get("status") == "completed":
            feedback_sent_at = last_completed.get("tutor_feedback_sent_at")
            if feedback_sent_at is None:
                return jsonify({
                    "code": "REVIEW_PENDING",
                    "message": "Your coach is reviewing your last homework. You'll be able to start a new lesson once they send you feedback.",
                }), 403

        # Block only at zero balance. Completion charges 5 (floored at 0); 1–5 credits is still enough for one lesson.
        student_details = db.v2_get_student_details(user_id) or {}
        current_credits = student_details.get("credits")
        if current_credits is None:
            current_credits = 15
        if int(current_credits) <= 0:
            return jsonify({
                "code": "INSUFFICIENT_CREDITS",
                "message": "You have no credits left. Contact your coach to add more.",
                "credits": int(current_credits),
            }), 402

        db.v2_ensure_default_student_task(user_id)
        hw_task = db.v2_get_assigned_task_for_user(user_id)
        if not hw_task:
            return jsonify({
                "code": "NO_TASK_CONFIGURED",
                "message": "No task is configured for your account. Please contact your coach to get started.",
                "details": {},
            }), 422

        text = (hw_task.get("text") or "").strip()
        if not text:
            return jsonify({"code": "INVALID_STATE", "error": "Task has empty text"}), 500

        session = db.v2_create_homework_session(user_id)
        if not session:
            return jsonify({"code": "V2_ERROR", "error": "Failed to create session"}), 500

        pending_video_url, pending_video_description, pending_bucket, pending_path = db.v2_get_and_clear_pending_tutor_video(
            user_id
        )
        prefs = db.v2_get_user_metric_questions(user_id)
        session_update = {
            "session_metric_question_1": (prefs.get("metric_question_1") or "").strip(),
            "session_metric_question_2": (prefs.get("metric_question_2") or "").strip(),
            "session_metric_question_3": (prefs.get("metric_question_3") or "").strip(),
            **_persist_session_task(hw_task.get("id"), text),
        }
        if pending_video_url:
            session_update["tutor_video_url"] = pending_video_url
        if pending_video_description is not None:
            session_update["tutor_video_description"] = pending_video_description
        if pending_bucket:
            session_update["tutor_video_bucket"] = pending_bucket
        if pending_path:
            session_update["tutor_video_storage_path"] = pending_path
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
            return _json_homework_no_store(_build_step0_payload(user_id))

        task = None
        wid = _session_snap_task_id(active)
        wtext = _session_snap_task_text(active)

        if wtext:
            task = _task_payload(wid, wtext)
        elif _session_status_allows_task_step(active.get("status")):
            db.v2_ensure_default_student_task(user_id)
            hw_task = db.v2_get_assigned_task_for_user(user_id)
            if hw_task and (hw_task.get("text") or "").strip():
                text = (hw_task.get("text") or "").strip()
                db.v2_update_session(active["id"], user_id, _persist_session_task(hw_task.get("id"), text))
                task = _task_payload(hw_task.get("id"), text)

        # #region agent log
        _sid = str(active.get("id") or "")
        _agent_log("session/status about to jsonify active", {"session_id": _sid, "session_id_len": len(_sid), "user_id": user_id, "has_datetime_values": [k for k, v in active.items() if hasattr(v, "isoformat")]}, "B")
        # #endregion
        public_status = _public_status(active.get("status"))
        internal_status = active.get("status")
        student_details_active = db.v2_get_student_details(user_id) or {}
        credits_active = student_details_active.get("credits")
        if credits_active is None:
            credits_active = 15
        _tw = _task_text(task.get("text") if task else None)
        resp = {
            "status": public_status,
            "session_id": str(active["id"]),
            "recording_id": _public_recording_id(active),
            "task": _tw,
            "assigned_exercises": [],
            "tutor_feedback_deadline": None,
            "tutor_feedback_message": None,
            "tutor_video_url": None,
            "tutor_video_description": None,
            "tutor_video_bucket": None,
            "tutor_video_storage_path": None,
            "has_active_session": True,
            "credits": int(credits_active),
        }
        # Hide intro coach video while report is generating; session row still has tutor_video_* from session/start.
        hide_tutor_video = internal_status in (
            STATUS_COMPLETING_FROM_RECORDING_1,
            STATUS_COMPLETING_FROM_RECORDING_2,
        )
        # Once the session is completed, the frontend should transition to the report/reviewing
        # screen instead of continuing to show the pre-homework coach message block.
        playable, tb, tp = resolve_tutor_video_playable_url(
            db=db,
            explicit_video_url=active.get("tutor_video_url"),
            video_bucket=active.get("tutor_video_bucket"),
            video_storage_path=active.get("tutor_video_storage_path"),
        )
        msg = (active.get("tutor_video_description") or "").strip()
        if public_status != PUBLIC_STATUS_COMPLETED and not hide_tutor_video:
            if playable:
                resp["tutor_video_url"] = playable
            if tb:
                resp["tutor_video_bucket"] = tb
            if tp:
                resp["tutor_video_storage_path"] = tp
            if msg:
                resp["tutor_video_description"] = msg
        return _json_homework_no_store(resp)

    except Exception as e:
        # #region agent log
        _agent_log("session/status exception", {"type": type(e).__name__, "message": str(e)}, "ALL")
        # #endregion
        sentry_sdk.capture_exception(e)
        return _json_homework_no_store({"code": "V2_ERROR", "error": str(e)}, 500)


@homework_bp.route("/stripe/claim-checkout", methods=["POST"])
@require_auth
def homework_stripe_claim_checkout():
    """Apply credits for a completed Checkout Session immediately after redirect (idempotent; same as webhook)."""
    try:
        body = request.get_json(silent=True) or {}
        sid = (body.get("checkout_session_id") or body.get("session_id") or "").strip()
        if not sid:
            return _json_homework_no_store({"code": "INVALID_INPUT", "error": "checkout_session_id is required"}, 400)
        result = apply_paid_checkout_session_credits(sid, auth_user_id=request.user_id, app_config=config)
        if result.ok:
            sk = result.payload.get("skipped")
            if sk in ("not_paid", "not_payment_mode"):
                return _json_homework_no_store({
                    "code": "CHECKOUT_NOT_CREDITABLE",
                    "error": "Checkout is not a completed one-time payment, or line items are not ready yet. Retry in a few seconds.",
                    "skipped": sk,
                }, 422)
        return _json_homework_no_store(result.payload, result.http_status)
    except Exception as e:
        logger.error("stripe claim-checkout: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return _json_homework_no_store({"code": "V2_ERROR", "error": str(e)}, 500)


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


# ---------- Step 1: task (GET) + recording_1 (POST) ----------
@homework_bp.route("/session/<session_id>/task", methods=["GET"])
@require_auth
def homework_get_session_task(session_id):
    """Get the homework task for this session. Snapshot-first for deterministic resume."""
    try:
        user_id = request.user_id
        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        if not _session_status_allows_task_step(session.get("status")):
            return jsonify({
                "code": "INVALID_SESSION_STATE",
                "error": "Session must be in task",
                "status": session.get("status"),
            }), 409

        wtext = _session_snap_task_text(session)

        if wtext:
            return jsonify({"task": _task_text(wtext)}), 200

        db.v2_ensure_default_student_task(user_id)
        hw_task = db.v2_get_assigned_task_for_user(user_id)
        if not hw_task:
            return jsonify({
                "code": "NO_TASK_CONFIGURED",
                "message": "No task is configured for your account. Please contact your coach to get started.",
                "details": {},
            }), 422

        text = (hw_task.get("text") or "").strip()
        if not text:
            return jsonify({"code": "INVALID_STATE", "error": "Task has empty text"}), 500

        db.v2_update_session(session_id, user_id, _persist_session_task(hw_task.get("id"), text))
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
            try:
                db.v2_update_session(session_id, user_id, {"student_self_rating": r})
            except Exception as snap_err:
                msg = str(snap_err).lower()
                if "student_self_rating" in msg or "42703" in msg or "does not exist" in msg:
                    pass  # optional column until migration runs
                else:
                    logger.warning("homework_self_rating: student_self_rating snapshot failed: %s", snap_err)
        else:
            saved_rating = None
        try:
            db.v2_update_session(session_id, user_id, {
                "self_rating_submitted_at": utc_now_iso()
            })
        except Exception as flag_err:
            logger.warning("homework_self_rating: could not set self_rating_submitted_at: %s", flag_err)

        # Completion depends on self-rating: build report, mark completed, send coach email when job is done.
        session_completed = False
        processing = False
        proc_status = session.get("recording_1_processing_status")

        if status == STATUS_TASK_BLOCK and session.get("recording_1_id"):
            # Legacy / edge: recording submitted but status still task_block — same completion rules as report_generating.
            if proc_status == "completed":
                payload_out = complete_session_recording_1_only(
                    session_id,
                    user_id,
                    allow_task_block=True,
                    preferred_student_email=preferred_student_email,
                )
                if payload_out:
                    session_completed = True
                    logger.info("homework_self_rating: completed from task_block after self-rating session_id=%s", session_id)
                else:
                    logger.warning(
                        "homework_self_rating: complete_session_recording_1_only returned None (task_block) session_id=%s",
                        session_id,
                    )
            elif proc_status == "pending":
                processing = True
                logger.info("homework_self_rating: task_block job still pending session_id=%s", session_id)
            elif proc_status == "failed":
                recovered = False
                try:
                    recovered = minimal_complete_and_notify(
                        session_id,
                        user_id,
                        preferred_student_email=preferred_student_email,
                    )
                except Exception as fallback_err:
                    logger.warning("homework_self_rating: minimal fallback failed (task_block): %s", fallback_err)
                if recovered:
                    session_completed = True
                else:
                    return jsonify({
                        "code": "RECORDING_PROCESSING_FAILED",
                        "error": "Recording processing failed. Please retry the recording.",
                        "status": status,
                        "recording_1_processing_status": proc_status,
                        "recording_1_processing_error_code": session.get("recording_1_processing_error_code"),
                    }), 409
        elif status == STATUS_COMPLETING_FROM_RECORDING_1 and proc_status == "completed":
            # Job already finished before self-rating arrived — complete now.
            # #region agent log
            _agent_log("POST self-rating attempting completion", {"session_id": session_id, "recording_1_processing_status": proc_status}, "H4")
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
        elif status == STATUS_COMPLETING_FROM_RECORDING_1 and proc_status == "pending":
            # Job still running — return immediately; job will call complete_session_recording_1_only
            # when it finishes and sees self_rating_submitted_at is set.
            processing = True
            logger.info("homework_self_rating: job still pending, deferring completion to job session_id=%s", session_id)
        elif status == STATUS_COMPLETING_FROM_RECORDING_1 and proc_status == "failed":
            # Last-resort recovery: finalize with a minimal report so the student
            # can still see a score and complete the lesson.
            recovered = False
            try:
                recovered = minimal_complete_and_notify(
                    session_id,
                    user_id,
                    preferred_student_email=preferred_student_email,
                )
            except Exception as fallback_err:
                logger.warning("homework_self_rating: minimal fallback failed: %s", fallback_err)
            if recovered:
                session_completed = True
            else:
                return jsonify({
                    "code": "RECORDING_PROCESSING_FAILED",
                    "error": "Recording processing failed. Please retry the recording.",
                    "status": status,
                    "recording_1_processing_status": proc_status,
                    "recording_1_processing_error_code": session.get("recording_1_processing_error_code"),
                }), 409
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
            "processing": processing,
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


def _normalize_recording_slot(value) -> str:
    slot = str(value or "1").strip()
    if slot not in ("1", "2"):
        raise ValueError("recording must be '1' or '2'")
    return slot


def _recording_slot_fields(slot: str) -> dict:
    if slot == "1":
        return {
            "label": "recording-1",
            "session_field": "recording_1_id",
            "processing_field": "recording_1_processing_status",
            "allowed_statuses": (STATUS_TASK, _LEGACY_STATUS_TASK),
            "completing_status": STATUS_COMPLETING_FROM_RECORDING_1,
            "already_submitted_statuses": (STATUS_COMPLETING_FROM_RECORDING_1, STATUS_COMPLETED),
        }


def _parse_recording_submission(session_id: str, user_id: str, require_duration: bool = False):
    audio_file = request.files.get("audio")
    data = request.get_json(silent=True) or (request.form or {})
    duration_seconds = None
    storage_path = None
    center_hold_ratio = None

    if audio_file:
        storage_path = f"{user_id}/{session_id}/{uuid.uuid4()}.webm"
        audio_file.seek(0)
        audio_data = audio_file.read()
        content_type = str(audio_file.content_type or "audio/webm")
        if content_type in ("True", "False"):
            content_type = "audio/webm"
        duration_raw = request.form.get("duration_seconds")
        try:
            duration_seconds = float(duration_raw) if duration_raw not in (None, "") else None
        except (TypeError, ValueError):
            return jsonify({"code": "INVALID_INPUT", "error": "duration_seconds must be a number"}), 400
        chr_raw = request.form.get("center_hold_ratio")
        if chr_raw in (None, ""):
            chr_raw = request.form.get("centerHoldRatio")
        if chr_raw not in (None, ""):
            try:
                center_hold_ratio = float(chr_raw)
            except (TypeError, ValueError):
                center_hold_ratio = None
        return data, storage_path, duration_seconds, center_hold_ratio, (audio_data, content_type)

    storage_path = (data.get("storage_path") or "").strip()
    duration_raw = data.get("duration_seconds")
    chr_raw = data.get("center_hold_ratio")
    if chr_raw is None:
        chr_raw = data.get("centerHoldRatio")
    if not storage_path:
        return jsonify({"code": "INVALID_INPUT", "error": "Either send multipart 'audio' or JSON with storage_path and duration_seconds"}), 400
    if not _validate_storage_path(storage_path, user_id, session_id):
        return jsonify({"code": "INVALID_INPUT", "error": "storage_path invalid or not allowed for this session"}), 400
    if duration_raw is None and require_duration:
        return jsonify({"code": "INVALID_INPUT", "error": "duration_seconds is required for this recording"}), 400
    if duration_raw is not None:
        try:
            duration_seconds = float(duration_raw)
        except (TypeError, ValueError):
            return jsonify({"code": "INVALID_INPUT", "error": "duration_seconds must be a number"}), 400
    if chr_raw is not None:
        try:
            center_hold_ratio = float(chr_raw)
        except (TypeError, ValueError):
            center_hold_ratio = None
    return data, storage_path, duration_seconds, center_hold_ratio, None


def _submit_recording(session_id: str, slot: str):
    from services.recording_1_job import enqueue_recording_1_job

    user_id = request.user_id
    session = db.v2_get_session(session_id, user_id)
    fields = _recording_slot_fields(slot)
    label = fields["label"]
    session_field = fields["session_field"]
    processing_field = fields["processing_field"]
    allowed_statuses = fields["allowed_statuses"]
    completing_status = fields["completing_status"]
    already_submitted_statuses = fields["already_submitted_statuses"]
    if not session:
        _agent_log(f"{label}: session not found", {"session_id": session_id}, "H1")
        return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404

    status = session.get("status")
    if status not in allowed_statuses:
        if status in already_submitted_statuses:
            existing_recording_id = session.get(session_field)
            existing_payload = {
                "already_submitted": True,
                "status": PUBLIC_STATUS_REPORT_GENERATING if status != STATUS_COMPLETED else PUBLIC_STATUS_COMPLETED,
                "recording_id": existing_recording_id,
            }
            return jsonify(existing_payload), 200
        _agent_log(f"{label}: wrong status", {"session_id": session_id, "status": status}, "H1")
        return jsonify({
            "code": "INVALID_SESSION_STATE",
            "error": f"Session not found or not in one of {allowed_statuses}",
            "status": status,
        }), 409

    parsed = _parse_recording_submission(session_id, user_id, require_duration=False)
    if len(parsed) == 2:
        return parsed
    data, storage_path, duration_seconds, center_hold_ratio, audio_upload = parsed

    if audio_upload is not None:
        audio_data, content_type = audio_upload
        db.upload_audio(config.AUDIO_BUCKET_NAME, storage_path, audio_data, content_type=content_type)

    existing_rid = session.get(session_field)
    if existing_rid:
        existing = db.get_recording(existing_rid, user_id)
        if existing and (existing.get("storage_path") or "").strip() == storage_path:
            db.v2_update_session(session_id, user_id, {"status": completing_status})
            payload = {
                "recording_id": existing["id"],
                "status": PUBLIC_STATUS_REPORT_GENERATING,
            }
            return jsonify(payload), 200

    client_transcript = (data.get("transcript_text") or "").strip() if isinstance(data, dict) else ""
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
    if client_transcript:
        minimal_recording["transcription_text"] = client_transcript
    recording = db.create_recording(minimal_recording)
    if not recording:
        return jsonify({"code": "RECORDING_CREATE_FAILED"}), 500

    db.v2_update_session(session_id, user_id, {
        session_field: recording["id"],
        "status": completing_status,
        processing_field: "pending",
    })

    enqueue_recording_1_job(
        session_id,
        str(recording["id"]),
        storage_path,
        user_id,
        duration_seconds,
        center_hold_ratio=center_hold_ratio,
    )

    payload = {
        "status": PUBLIC_STATUS_REPORT_GENERATING,
        "recording_id": recording["id"],
    }
    return jsonify(payload), 200


@homework_bp.route("/session/<session_id>/recording-upload-url", methods=["POST"])
@require_auth
def homework_recording_upload_url(session_id):
    """Mint a storage path for a homework recording upload."""
    # #region agent log
    try:
        _debug_log_write({"hypothesisId": "H0", "location": "homework.py:recording-upload-url", "message": "entry", "data": {"session_id": str(session_id)[:36]}, "timestamp": int(time.time() * 1000)})
    except Exception:
        pass
    # #endregion
    try:
        user_id = request.user_id
        data = request.get_json() or {}
        try:
            recording_slot = _normalize_recording_slot(data.get("recording"))
        except ValueError as e:
            return jsonify({"code": "INVALID_INPUT", "error": str(e)}), 400
        fields = _recording_slot_fields(recording_slot)

        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        status = session.get("status")
        if status not in fields["allowed_statuses"]:
            if status in fields["already_submitted_statuses"]:
                return jsonify({
                    "already_submitted": True,
                    "storage_path": None,
                    "bucket": config.AUDIO_BUCKET_NAME,
                    "message": f"You already submitted {fields['label']}. Your report is being generated or ready.",
                }), 200
            _agent_log("recording-upload-url: wrong status", {"session_id": session_id, "status": status, "recording": recording_slot}, "H_upload")
            return jsonify({
                "code": "INVALID_SESSION_STATE",
                "error": f"Session must be in one of {fields['allowed_statuses']} for {fields['label']}",
                "status": status,
            }), 409

        storage_path = _storage_path_for_session(user_id, session_id)
        resp_payload = {
            "storage_path": storage_path,
            "bucket": config.AUDIO_BUCKET_NAME,
            "recording": recording_slot,
        }
        # #region agent log
        try:
            _debug_log_write({"hypothesisId": "H1", "location": "homework.py:recording-upload-url", "message": "upload-url response shape", "data": {"keys": list(resp_payload.keys()), "storage_path_type": type(storage_path).__name__, "bucket_type": type(config.AUDIO_BUCKET_NAME).__name__, "has_upload_url": "upload_url" in resp_payload}, "timestamp": int(time.time() * 1000)})
        except Exception:
            pass
        # #endregion
        upload_info = db.create_signed_upload_url(config.AUDIO_BUCKET_NAME, storage_path)
        if isinstance(upload_info, dict) and upload_info.get("signed_url"):
            resp_payload["upload_url"] = upload_info["signed_url"]
            if upload_info.get("token"):
                resp_payload["upload_token"] = upload_info["token"]
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
    """Upload recording 1 and return the report-generating state."""
    try:
        _agent_log("recording-1: entry", {"session_id": session_id}, "H1")
        return _submit_recording(session_id, "1")
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
    """Get report data for a completed session (step 5). Returns report_text, scores (task step, final, overall 0-100), final_recording { id, audio_url } with fresh signed URL, and performance_history (last 5 completed sessions: date, score 0-100, oldest first). Owner-only; session must be completed."""
    try:
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
            # If job is done but frontend never triggered completion, run completion once.
            _st = session.get("status")
            _proc = session.get("recording_1_processing_status")
            _can_fallback_complete = _proc == "completed" and (
                _st == STATUS_COMPLETING_FROM_RECORDING_1
                or (_st == STATUS_TASK_BLOCK and session.get("recording_1_id"))
            )
            if _can_fallback_complete:
                # #region agent log
                _agent_log("GET report running fallback completion", {"session_id": session_id}, "H2")
                # #endregion
                try:
                    if complete_session_recording_1_only(
                        session_id,
                        user_id,
                        allow_task_block=(_st == STATUS_TASK_BLOCK),
                        preferred_student_email=preferred_student_email,
                    ):
                        session = db.v2_get_session(session_id, user_id)
                        logger.info("homework_get_report: fallback completion ran session_id=%s", session_id)
                        # #region agent log
                        _agent_log("GET report after fallback re-fetch", {"session_id": session_id, "status": session.get("status") if session else None}, "H2")
                        # #endregion
                except Exception as fallback_err:
                    logger.warning("homework_get_report: fallback completion failed: %s", fallback_err)
            elif session.get("status") == STATUS_COMPLETING_FROM_RECORDING_1 and session.get("recording_1_processing_status") == "pending":
                # Self-heal for in-process worker restarts: re-enqueue the processing job from persisted storage_path.
                try:
                    from services.recording_1_job import enqueue_recording_1_job
                    rec_id = session.get("recording_1_id")
                    rec = db.get_recording(rec_id, user_id) if rec_id else None
                    storage_path = (rec or {}).get("storage_path")
                    if rec_id and storage_path:
                        enqueue_recording_1_job(
                            session_id=session_id,
                            recording_id=str(rec_id),
                            storage_path=storage_path,
                            user_id=user_id,
                            duration_seconds=(rec or {}).get("duration_seconds"),
                        )
                        _agent_log("GET report re-enqueued pending recording job", {"session_id": session_id, "recording_id": str(rec_id)}, "H2")
                except Exception as requeue_err:
                    logger.warning("homework_get_report: pending job re-enqueue failed: %s", requeue_err)
            elif session.get("status") == STATUS_COMPLETING_FROM_RECORDING_1 and session.get("recording_1_processing_status") == "failed":
                recovered = False
                try:
                    recovered = minimal_complete_and_notify(
                        session_id,
                        user_id,
                        preferred_student_email=preferred_student_email,
                    )
                    if recovered:
                        session = db.v2_get_session(session_id, user_id)
                        logger.info("homework_get_report: minimal fallback completion ran session_id=%s", session_id)
                except Exception as fallback_err:
                    logger.warning("homework_get_report: minimal fallback failed: %s", fallback_err)
                if not recovered:
                    return jsonify({
                        "code": "RECORDING_PROCESSING_FAILED",
                        "error": "Recording processing failed. Please retry the recording.",
                        "status": session.get("status"),
                        "recording_1_processing_status": session.get("recording_1_processing_status"),
                        "recording_1_processing_error_code": session.get("recording_1_processing_error_code"),
                    }), 409
            if session.get("status") != STATUS_COMPLETED:
                # #region agent log
                _agent_log("GET report returning 409", {"session_id": session_id, "status": session.get("status")}, "H1")
                # #endregion
                # 409 so frontend can distinguish "not ready yet, retry" from "session not found" (404)
                return jsonify({
                    "code": "REPORT_NOT_READY",
                    "error": "Report is only available for completed sessions",
                    "status": session.get("status"),
                    "recording_1_processing_status": session.get("recording_1_processing_status"),
                    "recording_1_processing_error_code": session.get("recording_1_processing_error_code"),
                }), 409
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

        has_rec_2 = False
        score_for_display_100 = session.get("score_for_display")
        try:
            score_for_display_100 = int(score_for_display_100) if score_for_display_100 is not None else None
        except (TypeError, ValueError):
            score_for_display_100 = None
        if score_for_display_100 is None:
            raw_score = session.get("score")
            if raw_score is not None:
                try:
                    s01 = float(raw_score)
                    if s01 > 1.0:
                        s01 = max(0.0, min(1.0, s01 / 100.0))
                    score_for_display_100 = max(0, min(100, int(round(s01 * 100.0))))
                except (TypeError, ValueError):
                    pass
        if score_for_display_100 is None:
            return jsonify({
                "code": "REPORT_NOT_READY",
                "error": "Report score is not finalized yet.",
                "status": session.get("status"),
            }), 409
        score_for_display_100 = max(0, min(100, score_for_display_100))
        perf_end = round(score_for_display_100 / 100.0, 4)

        filler_count_for_cap = 0
        try:
            cap_recording_id = session.get("recording_1_id")
            if cap_recording_id:
                cap_rec = db.get_recording_for_homework_session(cap_recording_id, user_id, session)
                cap_fillers = cap_rec.get("filler_words_count") if isinstance(cap_rec, dict) else {}
                if isinstance(cap_fillers, dict):
                    filler_count_for_cap = int(cap_fillers.get("total", 0) or 0)
        except Exception:
            filler_count_for_cap = 0
        session_sniper = None
        try:
            session_sniper = db.get_session_sniper_metrics(session_id)
        except Exception:
            pass
        if filler_count_for_cap > 0 and score_for_display_100 >= 100:
            score_for_display_100 = 99
            perf_end = min(perf_end, 0.99)

        history_rows = db.v2_get_performance_history(user_id, limit=5)
        performance_history = []
        for row in history_rows:
            created_at = row.get("created_at")
            score_01 = row.get("score", 0) or 0
            row_session_id = row.get("session_id")
            # Current session bar uses the same score as the report header (recording-based end score).
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

        # Display recording: recording_1 (for playback, transcript, fillers)
        display_recording_id = session.get("recording_1_id")
        final_recording = {"id": None, "audio_url": None}
        recording_payload = None  # full transcript, fillers, playback for report view
        if display_recording_id:
            rec = db.get_recording_for_homework_session(display_recording_id, user_id, session)
            if rec and (
                not (rec.get("transcription_text") or "").strip()
                or rec.get("words_per_minute") is None
            ):
                rec = db.get_recording(str(display_recording_id), None) or rec
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
                tt = (rec.get("transcription_text") or "").strip()
                recording_payload = {
                    "id": str(display_recording_id) if display_recording_id is not None else None,
                    "audio_url": audio_url if (audio_url is None or isinstance(audio_url, str)) else str(audio_url),
                    "transcription_text": tt,
                    "transcript": tt,
                    "filler_words_count": {
                        "total": int(filler_data.get("total", 0) or 0),
                        "breakdown": dict(filler_data.get("breakdown") or {}),
                    },
                    "words_per_minute": round(float(rec.get("words_per_minute") or 0), 1),
                }

        if (
            session.get("status") == STATUS_COMPLETED
            and recording_payload is not None
            and not (recording_payload.get("transcription_text") or "").strip()
        ):
            # Recovery path for old fallback-completed sessions where Whisper failed earlier.
            # Try a one-shot transcript backfill from stored audio.
            recovered = best_effort_backfill_recording_1_transcript(session_id, user_id)
            if recovered:
                session = db.v2_get_session(session_id, user_id) or session
                rec2 = db.get_recording_for_homework_session(display_recording_id, user_id, session) or db.get_recording(str(display_recording_id), None)
                if rec2:
                    filler_data2 = rec2.get("filler_words_count") or {}
                    if not isinstance(filler_data2, dict):
                        filler_data2 = {}
                    tt2 = (rec2.get("transcription_text") or "").strip()
                    recording_payload["transcription_text"] = tt2
                    recording_payload["transcript"] = tt2
                    recording_payload["words_per_minute"] = round(float(rec2.get("words_per_minute") or 0), 1)
                    recording_payload["filler_words_count"] = {
                        "total": int(filler_data2.get("total", 0) or 0),
                        "breakdown": dict(filler_data2.get("breakdown") or {}),
                    }

        context_ready = bool((session.get("context_short") or "").strip())
        transcript_ready = bool(recording_payload and (recording_payload.get("transcription_text") or "").strip())
        degraded_missing_transcript = False
        if not context_ready or not recording_payload:
            return jsonify({
                "code": "REPORT_NOT_READY",
                "error": "Transcript and context are still processing.",
                "status": session.get("status"),
            }), 409
        if not transcript_ready:
            # Never trap completed sessions in infinite loading when fallback completion
            # produced a report without transcript.
            if session.get("status") == STATUS_COMPLETED and report_text:
                degraded_missing_transcript = True
                recording_payload["transcription_text"] = ""
                recording_payload["transcript"] = ""
            else:
                return jsonify({
                    "code": "REPORT_NOT_READY",
                    "error": "Transcript and context are still processing.",
                    "status": session.get("status"),
                }), 409

        sniper_profile = db.get_sniper_profile_payload(user_id)
        # Build sniper_metrics from session_sniper_metrics for frontend display
        sniper_metrics = None
        if session_sniper:
            def _safe_float(v, decimals=1):
                if v is None:
                    return None
                try:
                    return round(float(v), decimals)
                except (TypeError, ValueError):
                    return None
            _sr = session_sniper.get("student_rating_1_10")
            try:
                student_rating_out = int(_sr) if _sr is not None else None
            except (TypeError, ValueError):
                student_rating_out = None
            sniper_metrics = {
                "wpm": _safe_float(session_sniper.get("wpm")),
                "pause_ms": _safe_float(session_sniper.get("pause_ms"), 0),
                "dynamic_db": _safe_float(session_sniper.get("dynamic_db")),
                "emphasis_per_min": _safe_float(session_sniper.get("emphasis_per_min")),
                "energy_ratio": _safe_float(session_sniper.get("energy_ratio"), 2),
                "pitch_center_st": _safe_float(session_sniper.get("pitch_center_st")),
                "pitch_frame_count": int(session_sniper["pitch_frame_count"]) if session_sniper.get("pitch_frame_count") is not None else None,
                "stage_score": _safe_float(session_sniper.get("stage_score")),
                "voiced_duration_sec": _safe_float(session_sniper.get("voiced_duration_sec")),
                "student_rating_1_10": student_rating_out,
            }
            # Also fall back to recording WPM if sniper wpm is missing
            if sniper_metrics["wpm"] is None and recording_payload and recording_payload.get("words_per_minute"):
                sniper_metrics["wpm"] = round(float(recording_payload["words_per_minute"]), 1)
        elif recording_payload and recording_payload.get("words_per_minute") is not None:
            sniper_metrics = {"wpm": round(float(recording_payload["words_per_minute"]), 1)}
            try:
                smx = db.get_session_sniper_metrics(session_id)
                if smx and smx.get("student_rating_1_10") is not None:
                    sniper_metrics["student_rating_1_10"] = int(smx["student_rating_1_10"])
            except Exception:
                pass
        payload = {
            "report_text": report_text,
            # Backward-compat alias: some UIs still read scores.overall.
            "scores": {"overall": score_for_display_100},
            "score": perf_end,
            "performance_score_end": perf_end,
            "recording_count": 1,
            "final_recording": final_recording,
            "performance_history": performance_history,
            # Single canonical score (0-100): performance_score_end (recording job), same as last bar on chart.
            "score_for_display": score_for_display_100,
            "report_grade": session.get("report_grade"),
            "report_comment": (session.get("report_comment") or "").strip() or None,
            "sniper_profile": sniper_profile,
            "realtime_level": sniper_profile.get("realtime_level"),
            "realtime_step": sniper_profile.get("realtime_step"),
        }
        if sniper_metrics is not None:
            payload["sniper_metrics"] = sniper_metrics
        if recording_payload is not None:
            payload["recording"] = recording_payload
            _tt = recording_payload.get("transcription_text") or recording_payload.get("transcript") or ""
            payload["transcription_text"] = _tt
            payload["transcript"] = _tt
        if degraded_missing_transcript:
            payload["report_quality"] = "degraded_missing_transcript"
            payload["transcript_available"] = False
        context_short = (session.get("context_short") or "").strip()
        if context_short:
            payload["context_short"] = context_short
        coach_insight = (session.get("coach_insight") or "").strip()
        if not coach_insight:
            from services.openai_service import openai_service
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
            context_fit_01 = None
            try:
                score_components = session.get("score_components")
                if isinstance(score_components, dict):
                    ctx_component = ((score_components.get("components") or {}).get("context") or {})
                    raw_fit = ctx_component.get("normalized")
                    if raw_fit is not None:
                        context_fit_01 = max(0.0, min(1.0, float(raw_fit)))
            except (TypeError, ValueError):
                context_fit_01 = None
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
                context_fit_01=context_fit_01,
            )
        if coach_insight:
            payload["coach_insight"] = coach_insight
        payload["report_cta"] = "Finish the lesson and sign out"
        # Frontend: on CTA, navigate to step 0 and call GET session/status only (single source of truth for waiting/video/can_start_homework).
        # #region agent log
        _agent_log("GET report returning 200", {"session_id": session_id, "status": session.get("status"), "report_id": session.get("report_id")}, "H3")
        # #endregion
        return jsonify(payload), 200
    except Exception as e:
        logger.exception("Homework get report: %s", e)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@homework_bp.route("/feedback-video-url", methods=["GET"])
@require_auth
def homework_feedback_video_url():
    """Return a short-lived signed URL for the latest generated coach feedback video."""
    try:
        user_id = request.user_id
        try:
            expires_in = int(request.args.get("expires_in", 48 * 3600))
        except (TypeError, ValueError):
            expires_in = 48 * 3600
        expires_in = max(60, min(172800, expires_in))
        row_res = (
            db.client.table("admin_student_send_drafts")
            .select("id, feedback_video_storage_path, sent_at")
            .eq("user_id", user_id)
            .eq("status", "sent")
            .order("sent_at", desc=True)
            .limit(20)
            .execute()
        )
        row = None
        for item in (row_res.data or []):
            if str(item.get("feedback_video_storage_path") or "").strip():
                row = item
                break
        if not row:
            return jsonify({"code": "VIDEO_NOT_FOUND", "error": "No coach feedback video available"}), 404
        storage_path = (row.get("feedback_video_storage_path") or "").strip()
        if not storage_path:
            return jsonify({"code": "VIDEO_NOT_FOUND", "error": "No coach feedback video available"}), 404
        from services.coach_video_storage import presigned_get_coach_object

        signed_url = presigned_get_coach_object(
            config.COACH_FEEDBACK_VIDEO_BUCKET, storage_path, expires_in, supabase_db=db
        )
        if not signed_url:
            return jsonify({"code": "SIGNED_URL_FAILED", "error": "Could not create signed URL"}), 500
        return jsonify(
            {
                "status": "ok",
                "storage_path": storage_path,
                "signed_url": signed_url,
                "expires_in": expires_in,
            }
        ), 200
    except Exception as e:
        logger.exception("Homework feedback video url failed: %s", e)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500
