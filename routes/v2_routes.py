"""
V2: admin CRUD only. Student flow is homework only (routes/homework.py).
All /v2/admin/* require auth + admin.
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from routes.admin import require_admin, is_admin
from services.db import db
from services.email_service import email_service
from services.video_url_validation import validate_video_url
import logging
import sentry_sdk
import json
import time

logger = logging.getLogger(__name__)
v2_bp = Blueprint("v2", __name__, url_prefix="/v2")


# ---------- Admin ----------
@v2_bp.route("/admin/health", methods=["GET"])
@require_admin
def v2_admin_health():
    """Debug: verify admin routes are reachable. Returns 200 if token is valid and admin."""
    return jsonify({"status": "ok", "message": "Admin API reachable"}), 200


@v2_bp.route("/admin/students", methods=["GET"])
@require_admin
def v2_admin_students():
    """List students with email (and optional stats). Uses Auth Admin API so new students appear; fallback to session-based list."""
    try:
        limit = request.args.get("limit", default=20, type=int)
        offset = request.args.get("offset", default=0, type=int)
        # Prefer auth user list so newly registered students appear before they have any session
        auth_list = db.v2_list_auth_users(limit=limit, offset=offset)
        if auth_list is not None:
            students = []
            for item in auth_list:
                uid = item.get("user_id")
                email = item.get("email")
                if not uid:
                    continue
                row = {"user_id": uid, "email": email, "user_email": email}
                try:
                    stats = db.v2_get_student_list_stats(uid)
                    if stats:
                        row["sessions_count"] = stats.get("sessions_count")
                        row["last_session_at"] = stats.get("last_session_at")
                        row["avg_performance"] = stats.get("avg_performance")
                except Exception:
                    pass
                students.append(row)
            return jsonify({"students": students, "limit": limit, "offset": offset}), 200
        # Fallback: list only users who have at least one v2_session (legacy; new students won't appear)
        user_ids = db.v2_list_users_with_sessions(limit=limit, offset=offset)
        students = []
        for uid in user_ids:
            try:
                email = db.get_user_email_from_auth(uid)
                row = {"user_id": uid, "email": email, "user_email": email}
                try:
                    stats = db.v2_get_student_list_stats(uid)
                    if stats:
                        row["sessions_count"] = stats.get("sessions_count")
                        row["last_session_at"] = stats.get("last_session_at")
                        row["avg_performance"] = stats.get("avg_performance")
                except Exception:
                    pass
                students.append(row)
            except Exception as e:
                logger.warning("Skipping user %s in students list: %s", uid, e)
                students.append({"user_id": uid, "email": None, "user_email": None})
        return jsonify({"students": students, "limit": limit, "offset": offset}), 200
    except Exception as e:
        logger.exception("v2_admin_students failed")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>", methods=["GET"])
@require_auth
def v2_admin_student_profile(user_id):
    """Student profile: admin can get any user's profile; authenticated user can get own profile (user_id === token sub).
    Same contract: user_id, email, overrides, speaker_profile, task_warm_up[], task_focus[], post_recording_questions[], sessions (reports list)."""
    try:
        if not is_admin(request.user_id) and user_id != request.user_id:
            return jsonify({"code": "FORBIDDEN", "error": "You can only access your own profile"}), 403
        email = db.get_user_email_from_auth(user_id)
        raw_overrides = db.v2_get_student_overrides(user_id)
        overrides = dict(raw_overrides) if raw_overrides else {}
        overrides["assigned_next_task_ids"] = overrides.get("assigned_next_task_ids") or []
        # Ensure skip flags are always booleans for consistent admin UI (false when never set)
        overrides["skip_metric_questions"] = bool(raw_overrides.get("skip_metric_questions") if raw_overrides else False)
        overrides["skip_post_questions"] = bool(raw_overrides.get("skip_post_questions") if raw_overrides else False)
        speaker_profile = db.v2_get_speaker_profile(user_id)
        task_warm_up = db.v2_get_warm_up_tasks(user_id)
        task_focus = db.v2_get_focus_tasks(user_id)
        post_recording_questions = db.v2_get_student_post_recording_questions(user_id)
        last_report = db.v2_get_last_report_for_user(user_id)
        sessions = db.v2_get_sessions_with_previews(user_id, limit=50)
        return jsonify({
            "user_id": user_id,
            "email": email,
            "overrides": overrides,
            "speaker_profile": speaker_profile,
            "task_warm_up": task_warm_up,
            "task_focus": task_focus,
            "post_recording_questions": post_recording_questions,
            "last_report": last_report.get("report_text") if last_report else None,
            "last_report_preview": last_report.get("report_preview") if last_report else None,
            "sessions": sessions,
        }), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/speaker-profile", methods=["PUT"])
@require_admin
def v2_admin_student_speaker_profile(user_id):
    """Update speaker profile (main_goal, motivation, strong_points, weak_points, charismatic_traits, hobbies_interests, personality_type, coach_notes)."""
    try:
        data = request.get_json() or {}
        db.v2_upsert_speaker_profile(user_id, data)
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


def _coerce_override_bool(value, key: str):
    """Coerce a value to bool for skip_metric_questions / skip_post_questions. Returns (bool, None) or (None, error_msg)."""
    if value is True or value is False:
        return (value, None)
    if value in ("true", "1", 1):
        return (True, None)
    if value in ("false", "0", "", 0, None):
        return (False, None)
    return (None, f"{key} must be a boolean (true/false)")


@v2_bp.route("/admin/students/<user_id>/overrides", methods=["PUT"])
@require_admin
def v2_admin_student_overrides(user_id):
    """Set prompts, assigned post Qs, skip_metric_questions, skip_post_questions, next exercise/task."""
    try:
        data = request.get_json() or {}
        # #region agent log
        _log_path = "/Users/arturwillonski/Documents/backend-cursor/.cursor/debug.log"
        try:
            with open(_log_path, "a") as _f:
                _f.write(json.dumps({"message": "PUT overrides request body", "data": {"body_keys": list(data.keys()), "skip_metric_questions": data.get("skip_metric_questions"), "skip_post_questions": data.get("skip_post_questions")}, "hypothesisId": "H1", "location": "v2_routes.py:PUT overrides", "timestamp": int(time.time() * 1000)}) + "\n")
        except Exception as _e:
            try:
                with open("/Users/arturwillonski/Documents/backend-cursor/debug_override.log", "a") as _f:
                    _f.write(json.dumps({"message": "PUT overrides request body", "data": {"body_keys": list(data.keys()), "skip_metric_questions": data.get("skip_metric_questions"), "skip_post_questions": data.get("skip_post_questions")}, "hypothesisId": "H1", "location": "v2_routes.py:PUT overrides", "timestamp": int(time.time() * 1000), "primary_log_error": str(_e)}) + "\n")
            except Exception:
                pass
        # #endregion
        # Normalize camelCase from frontend to snake_case
        if "skipMetricQuestions" in data and "skip_metric_questions" not in data:
            data["skip_metric_questions"] = data.pop("skipMetricQuestions", None)
        if "skipPostQuestions" in data and "skip_post_questions" not in data:
            data["skip_post_questions"] = data.pop("skipPostQuestions", None)
        ids = data.get("assigned_post_question_ids")
        if ids is not None and not isinstance(ids, list):
            return jsonify({"code": "INVALID_INPUT", "error": "assigned_post_question_ids must be an array"}), 400
        for key in ("skip_metric_questions", "skip_post_questions"):
            if key in data:
                val, err = _coerce_override_bool(data[key], key)
                if err:
                    return jsonify({"code": "INVALID_INPUT", "error": err}), 400
                data[key] = val
        db.v2_upsert_student_overrides(user_id, data)
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        # #region agent log
        try:
            with open("/Users/arturwillonski/Documents/backend-cursor/.cursor/debug.log", "a") as _f:
                _f.write(json.dumps({"message": "PUT overrides exception", "data": {"error": str(e), "error_type": type(e).__name__}, "hypothesisId": "H4", "location": "v2_routes.py:PUT overrides except", "timestamp": int(time.time() * 1000)}) + "\n")
        except Exception as _e2:
            try:
                with open("/Users/arturwillonski/Documents/backend-cursor/debug_override.log", "a") as _f:
                    _f.write(json.dumps({"message": "PUT overrides exception", "data": {"error": str(e), "error_type": type(e).__name__}, "hypothesisId": "H4", "location": "v2_routes.py:PUT overrides except", "timestamp": int(time.time() * 1000), "primary_log_error": str(_e2)}) + "\n")
            except Exception:
                pass
        # #endregion
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/send-assignment", methods=["POST"])
@require_admin
def v2_admin_send_assignment(user_id):
    """Send homework email to the student. Body: optional { \"video_url\": \"https://...\", \"video_description\": \"...\" }. Requires student to have an email in Supabase Auth."""
    try:
        from config import Config
        config = Config()
        body = request.get_json(silent=True) or {}
        video_url = validate_video_url(body.get("video_url"))
        if body.get("video_url") is not None and video_url is None:
            return jsonify({"code": "INVALID_VIDEO_URL", "error": "video_url must be a valid URL (http/https, max 2048 chars)"}), 400
        video_description = (body.get("video_description") or "").strip() if body.get("video_description") is not None else None
        if video_description is not None and len(video_description) > 2000:
            return jsonify({"code": "INVALID_VIDEO_DESCRIPTION", "error": "video_description must be at most 2000 characters"}), 400
        student_email = db.get_user_email_from_auth(user_id)
        if not student_email or not student_email.strip():
            return jsonify({"code": "NO_EMAIL", "error": "Student has no email in auth"}), 400
        # Store coach message (and optional video URL) so GET session/status can return tutor_video_description
        if video_url is not None or video_description is not None:
            db.v2_set_pending_tutor_video(user_id, video_url, video_description)
        overrides = db.v2_get_student_overrides(user_id) or {}
        has_assigned_exercise = bool(overrides.get("assigned_next_exercise_id"))
        result = email_service.send_assignment_to_student(
            to_email=student_email.strip(),
            frontend_url=config.FRONTEND_URL,
            video_url=video_url,
            video_description=video_description,
            has_assigned_exercise=has_assigned_exercise,
            student_name=student_email.strip(),
        )
        if result.get("status") == "failed":
            return jsonify({"code": "EMAIL_FAILED", "error": result.get("error", "Failed to send email")}), 500
        db.v2_mark_tutor_feedback_sent_for_user(user_id)
        return jsonify({"status": "ok", "message": "Assignment sent", "sent": result.get("sent", False)}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/sessions/<session_id>", methods=["GET", "PATCH"])
@require_admin
def v2_admin_student_session_detail(user_id, session_id):
    """GET: full session for admin. PATCH: update coach_grade (1-10). Body: { \"coach_grade\": 7 }."""
    try:
        if request.method == "GET":
            session = db.v2_get_session(session_id, user_id)
            if not session:
                return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
            return jsonify({"session": session}), 200
        # PATCH: coach_grade
        data = request.get_json() or {}
        coach_grade = data.get("coach_grade")
        if coach_grade is not None:
            try:
                g = int(coach_grade)
                if g < 1 or g > 10:
                    return jsonify({"code": "INVALID_INPUT", "error": "coach_grade must be between 1 and 10"}), 400
            except (TypeError, ValueError):
                return jsonify({"code": "INVALID_INPUT", "error": "coach_grade must be an integer 1-10"}), 400
        else:
            g = None
        updated = db.v2_update_session(session_id, user_id, {"coach_grade": g})
        if not updated:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        return jsonify({"status": "ok", "coach_grade": updated.get("coach_grade")}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/sessions/<session_id>/grade", methods=["PUT"])
@require_admin
def v2_admin_student_session_grade(user_id, session_id):
    """Set admin/coach grade for a session. Body: { \"admin_grade\": number } (1-10). Persisted as coach_grade; GET report returns admin_grade."""
    try:
        data = request.get_json(silent=True) or {}
        admin_grade = data.get("admin_grade")
        if admin_grade is None:
            return jsonify({"code": "INVALID_INPUT", "error": "admin_grade is required"}), 400
        try:
            g = int(round(float(admin_grade)))
            if g < 1 or g > 10:
                return jsonify({"code": "INVALID_INPUT", "error": "admin_grade must be between 1 and 10"}), 400
        except (TypeError, ValueError):
            return jsonify({"code": "INVALID_INPUT", "error": "admin_grade must be a number 1-10"}), 400
        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        updated = db.v2_update_session(session_id, user_id, {"coach_grade": g})
        if not updated:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        return jsonify({"status": "ok", "admin_grade": g}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/sessions/<session_id>/report", methods=["GET", "POST"])
@require_admin
def v2_admin_student_session_report_get(user_id, session_id):
    """Get report for a completed session. Same payload as student GET report: report_text, scores, final_recording (recording_2 or recording_1), recording (transcript, fillers, wpm), context_short, coach_insight, performance_history, score_for_display. Supports GET and POST."""
    try:
        from config import Config
        config = Config()
        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        if (session.get("status") or "").strip().lower() != "completed":
            return jsonify({
                "code": "REPORT_NOT_READY",
                "error": "Report is only available for completed sessions",
                "status": session.get("status"),
            }), 404

        report_text = (session.get("context_long") or "").strip()
        if session.get("report_id"):
            try:
                r = db.client.table("v2_reports").select("report_text").eq("id", session["report_id"]).execute()
                if r.data and r.data[0].get("report_text"):
                    report_text = (r.data[0]["report_text"] or "").strip()
            except Exception:
                pass

        has_rec_2 = bool(session.get("recording_2_id"))
        perf_end = float(session.get("performance_score_end") or 0)
        score_for_display_100 = round(perf_end * 100)
        try:
            sniper = db.get_session_sniper_metrics(session_id)
            if sniper and sniper.get("stage_score") is not None:
                raw = float(sniper["stage_score"])
                score_for_display_100 = round(raw) if raw > 1 else round(raw * 100)
                score_for_display_100 = max(0, min(100, score_for_display_100))
                perf_end = score_for_display_100 / 100.0
        except Exception:
            pass
        scores = {"overall": score_for_display_100}

        history_rows = db.v2_get_performance_history(user_id, limit=5)
        performance_history = []
        for row in history_rows:
            created_at = row.get("created_at")
            score_01 = row.get("performance_score_end", 0) or 0
            row_session_id = row.get("session_id")
            bar_score = score_for_display_100 if row_session_id == session_id else round(float(score_01) * 100)
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

        # Same as student report: recording_2 if present, else recording_1 (for recording-1-only flow)
        display_recording_id = session.get("recording_2_id") or session.get("recording_1_id")
        final_recording = {"id": None, "audio_url": None}
        recording_payload = None
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
                        logger.warning("Admin report: could not create signed URL for recording %s: %s", display_recording_id, e)
                if audio_url is not None and not isinstance(audio_url, str):
                    audio_url = str(audio_url) if audio_url else None
                final_recording["id"] = str(display_recording_id) if display_recording_id is not None else None
                final_recording["audio_url"] = audio_url
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

        payload = {
            "report_text": report_text,
            "scores": scores,
            "performance_score_end": perf_end,
            "recording_count": 2 if has_rec_2 else 1,
            "final_recording": final_recording,
            "performance_history": performance_history,
            "score_for_display": score_for_display_100,
            "admin_grade": session.get("coach_grade"),
        }
        if recording_payload is not None:
            payload["recording"] = recording_payload
        context_short = (session.get("context_short") or "").strip()
        if context_short:
            payload["context_short"] = context_short
        coach_insight = (session.get("coach_insight") or "").strip()
        if coach_insight:
            payload["coach_insight"] = coach_insight
        return jsonify(payload), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/sessions/<session_id>/report", methods=["PATCH"])
@require_admin
def v2_admin_student_session_report(user_id, session_id):
    """Append or replace report (context_long_entries). Body: { \"action\": \"append\"|\"replace\", \"text\"?: \"...\", \"entries\"?: [{ \"at\", \"text\" }] }."""
    try:
        data = request.get_json() or {}
        action = data.get("action")
        if action == "append":
            text = data.get("text")
            if text is None or (isinstance(text, str) and not text.strip()):
                return jsonify({"code": "INVALID_INPUT", "error": "text required for append"}), 400
            updated = db.v2_append_context_long_entry(session_id, user_id, text.strip())
        elif action == "replace":
            entries = data.get("entries")
            if not isinstance(entries, list):
                return jsonify({"code": "INVALID_INPUT", "error": "entries (array) required for replace"}), 400
            updated = db.v2_set_context_long_entries(session_id, user_id, entries)
        else:
            return jsonify({"code": "INVALID_INPUT", "error": "action must be append or replace"}), 400
        if not updated:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        return jsonify({
            "status": "ok",
            "context_long_entries": updated.get("context_long_entries") or [],
            "context_long": updated.get("context_long") or "",
        }), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Admin CRUD: exercises ----------
@v2_bp.route("/admin/exercises", methods=["GET"])
@require_admin
def v2_admin_exercises_list():
    result = db.client.table("v2_exercises").select("*").order("created_at", desc=True).execute()
    return jsonify({"exercises": result.data or []}), 200


@v2_bp.route("/admin/exercises", methods=["POST"])
@require_admin
def v2_admin_exercises_create():
    data = request.get_json() or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"code": "INVALID_INPUT", "error": "title is required"}), 400
    payload = {
        "title": title,
        "video_url": (data.get("video_url") or "").strip() or None,
        "description": (data.get("description") or "").strip() or None,
        "is_active": data.get("is_active") if "is_active" in data else True,
    }
    if "min_task_score" in data:
        payload["min_task_score"] = data.get("min_task_score")
    if "max_task_score" in data:
        payload["max_task_score"] = data.get("max_task_score")
    row = db.v2_insert_exercise(payload)
    return jsonify({"exercise": row}), 201


@v2_bp.route("/admin/exercises/<exercise_id>", methods=["PUT"])
@require_admin
def v2_admin_exercises_update(exercise_id):
    data = request.get_json() or {}
    row = db.v2_update_exercise(exercise_id, data)
    return jsonify({"exercise": row}), 200


@v2_bp.route("/admin/exercises/<exercise_id>", methods=["DELETE"])
@require_admin
def v2_admin_exercises_delete(exercise_id):
    """Soft-delete: sets is_active=False so exercise no longer appears in student flow."""
    db.v2_delete_exercise(exercise_id)
    return jsonify({"status": "ok"}), 200


# ---------- Admin CRUD: tasks ----------
_TASKS_HEADER = ("X-Backend-Route", "v2-admin-tasks")


@v2_bp.route("/admin/tasks", methods=["GET"])
@require_admin
def v2_admin_tasks_list():
    result = db.client.table("v2_tasks").select("*").order("created_at", desc=True).execute()
    resp = jsonify({"tasks": result.data or []})
    resp.headers[_TASKS_HEADER[0]] = _TASKS_HEADER[1]
    return resp, 200


@v2_bp.route("/admin/tasks", methods=["POST"])
@require_admin
def v2_admin_tasks_create():
    data = request.get_json() or {}
    title = (data.get("title") or "").strip()
    if not title:
        resp = jsonify({"code": "INVALID_INPUT", "error": "title is required", "_debug": {"stage": "validation", "message": "body.title missing or empty"}})
        resp.headers[_TASKS_HEADER[0]] = _TASKS_HEADER[1]
        return resp, 400
    # DB has prompt_text NOT NULL; default to title so "Add" with one field works
    prompt_text = (data.get("prompt_text") or title).strip() or title
    payload = {
        "title": title,
        "prompt_text": prompt_text,
        "min_task_score": data.get("min_task_score") if "min_task_score" in data else 0,
        "max_task_score": data.get("max_task_score") if "max_task_score" in data else 1,
        "is_active": data.get("is_active", True),
    }
    row = db.v2_insert_task(payload)
    if not row:
        resp = jsonify({"code": "V2_ERROR", "error": "Failed to create task", "_debug": {"stage": "v2_insert_task", "message": "insert returned no row"}})
        resp.headers[_TASKS_HEADER[0]] = _TASKS_HEADER[1]
        return resp, 500
    resp = jsonify({"task": row})
    resp.headers[_TASKS_HEADER[0]] = _TASKS_HEADER[1]
    return resp, 201


@v2_bp.route("/admin/tasks/<task_id>", methods=["PUT"])
@require_admin
def v2_admin_tasks_update(task_id):
    data = request.get_json() or {}
    row = db.v2_update_task(task_id, data)
    return jsonify({"task": row}), 200


@v2_bp.route("/admin/tasks/<task_id>", methods=["DELETE"])
@require_admin
def v2_admin_tasks_delete(task_id):
    """Soft-delete: set is_active=False so task no longer appears in student flow."""
    db.v2_delete_task(task_id)
    return jsonify({"status": "ok"}), 200


# ---------- Admin: post-recording questions pool (pool only; per-student below) ----------
@v2_bp.route("/admin/post-recording-questions-pool", methods=["GET"])
@require_admin
def v2_admin_post_recording_questions_pool_list():
    try:
        result = db.client.table("v2_post_recording_questions").select("*").execute()
        return jsonify({"post_recording_questions_pool": result.data or []}), 200
    except Exception as err:
        logger.warning("post-recording-questions-pool GET failed: %s", err, exc_info=True)
        return jsonify({"post_recording_questions_pool": []}), 200


@v2_bp.route("/admin/post-recording-questions-pool", methods=["POST"])
@require_admin
def v2_admin_post_recording_questions_pool_create():
    data = request.get_json() or {}
    try:
        row = db.v2_insert_post_question_pool(data)
        return jsonify({"post_recording_question": row}), 201
    except Exception as err:
        logger.warning("post-recording-questions-pool POST failed: %s", err, exc_info=True)
        return jsonify({"error": "Failed to create post-recording question.", "detail": str(err)}), 503


@v2_bp.route("/admin/post-recording-questions-pool/<question_id>", methods=["PUT"])
@require_admin
def v2_admin_post_recording_questions_pool_update(question_id):
    data = request.get_json() or {}
    try:
        row = db.v2_update_post_question_pool(question_id, data)
        return jsonify({"post_recording_question": row}), 200
    except Exception as err:
        logger.warning("post-recording-questions-pool PUT failed for %s: %s", question_id, err, exc_info=True)
        return jsonify({"error": "Update failed.", "detail": str(err)}), 503


@v2_bp.route("/admin/post-recording-questions-pool/<question_id>", methods=["DELETE"])
@require_admin
def v2_admin_post_recording_questions_pool_delete(question_id):
    try:
        db.v2_delete_post_question_pool(question_id)
        return jsonify({"status": "ok"}), 200
    except Exception as err:
        logger.warning("post-recording-questions-pool DELETE failed for %s: %s", question_id, err, exc_info=True)
        return jsonify({"error": "Delete failed.", "detail": str(err)}), 503


# ---------- Admin: task-warm-up pool (same mechanism as task_focus) ----------
@v2_bp.route("/admin/task-warm-up-pool", methods=["GET"])
@require_admin
def v2_admin_task_warm_up_pool_list():
    try:
        result = db.client.table("v2_warm_up_task_pool").select("*").order("order_index").order("created_at").execute()
        data = result.data or []
    except Exception:
        data = []
    return jsonify({"task_warm_up_pool": data}), 200


@v2_bp.route("/admin/task-warm-up-pool", methods=["POST"])
@require_admin
def v2_admin_task_warm_up_pool_create():
    data = request.get_json() or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required", "hint": "Send JSON body: { \"text\": \"your task text\" }"}), 400
    payload = {"text": text, "order_index": int(data.get("order_index", 0))}
    try:
        payload["max_performance_score"] = float(data.get("max_performance_score", 1.0))
    except (TypeError, ValueError):
        payload["max_performance_score"] = 1.0
    try:
        result = db.client.table("v2_warm_up_task_pool").insert(payload).execute()
        row = result.data[0] if result.data else None
        return jsonify({"task_warm_up": row}), 201
    except Exception as e:
        err = str(e).lower()
        hint = "Run migrations/v2_warm_up_task_pool.sql to create the table." if ("relation" in err or "does not exist" in err or "42p01" in err) else None
        out = {"error": str(e)}
        if hint:
            out["hint"] = hint
        return jsonify(out), 500


@v2_bp.route("/admin/task-warm-up-pool/<pool_id>", methods=["PUT"])
@require_admin
def v2_admin_task_warm_up_pool_update(pool_id):
    data = request.get_json() or {}
    payload = {k: data[k] for k in ("text", "order_index", "max_performance_score") if k in data}
    if "max_performance_score" in payload:
        try:
            payload["max_performance_score"] = float(payload["max_performance_score"])
        except (TypeError, ValueError):
            payload["max_performance_score"] = 1.0
    if not payload:
        try:
            result = db.client.table("v2_warm_up_task_pool").select("*").eq("id", pool_id).execute()
            row = result.data[0] if result.data else None
        except Exception:
            row = None
    else:
        try:
            result = db.client.table("v2_warm_up_task_pool").update(payload).eq("id", pool_id).execute()
            row = result.data[0] if result.data else None
        except Exception:
            row = None
    if not row:
        return jsonify({"error": "Pool task not found"}), 404
    return jsonify({"task_warm_up": row}), 200


@v2_bp.route("/admin/task-warm-up-pool/<pool_id>", methods=["DELETE"])
@require_admin
def v2_admin_task_warm_up_pool_delete(pool_id):
    try:
        db.client.table("v2_warm_up_task_pool").delete().eq("id", pool_id).execute()
    except Exception:
        pass
    return jsonify({"status": "ok"}), 200


# ---------- Admin: task-warm-up (per student) ----------
@v2_bp.route("/admin/students/<user_id>/task-warm-up", methods=["GET"])
@require_admin
def v2_admin_task_warm_up_list(user_id):
    try:
        rows = db.v2_get_warm_up_tasks(user_id)
        return jsonify({"task_warm_up": rows}), 200
    except Exception as err:
        logger.warning("task-warm-up GET failed for user %s: %s", user_id, err, exc_info=True)
        return jsonify({"task_warm_up": []}), 200


@v2_bp.route("/admin/students/<user_id>/task-warm-up", methods=["PUT"])
@require_admin
def v2_admin_task_warm_up_sync(user_id):
    """Set this student's warm-up tasks from the pool. Body: { "pool_task_ids": [uuid, ...] } (order = display order)."""
    data = request.get_json() or {}
    pool_task_ids = data.get("pool_task_ids")
    if pool_task_ids is None:
        return jsonify({"error": "pool_task_ids is required"}), 400
    if not isinstance(pool_task_ids, list):
        return jsonify({"error": "pool_task_ids must be a list"}), 400
    pool_task_ids = [str(x) for x in pool_task_ids]
    # #region agent log
    try:
        import json
        import os
        import time
        _log_path = os.path.join(os.path.dirname(__file__), "..", ".cursor", "debug.log")
        _log_path = os.path.abspath(_log_path)
        with open(_log_path, "a") as _f:
            _f.write(json.dumps({"location": "v2_routes.py:v2_admin_task_warm_up_sync", "message": "PUT task-warm-up entry", "data": {"user_id": user_id, "pool_task_ids": pool_task_ids}, "timestamp": int(time.time() * 1000), "hypothesisId": "entry"}) + "\n")
    except Exception:
        pass
    # #endregion
    try:
        rows = db.v2_sync_student_warm_up_tasks_from_pool(user_id, pool_task_ids)
        return jsonify({"task_warm_up": rows}), 200
    except Exception as err:
        # #region agent log
        try:
            import json
            import os
            import time
            err_msg = str(err)
            _log_path = os.path.join(os.path.dirname(__file__), "..", ".cursor", "debug.log")
            _log_path = os.path.abspath(_log_path)
            with open(_log_path, "a") as _f:
                _f.write(json.dumps({"location": "v2_routes.py:v2_admin_task_warm_up_sync", "message": "PUT task-warm-up exception", "data": {"err_type": type(err).__name__, "err_message": err_msg, "user_id": user_id}, "timestamp": int(time.time() * 1000), "hypothesisId": "exception"}) + "\n")
        except Exception:
            pass
        # #endregion
        logger.warning("task-warm-up PUT sync failed for user %s: %s", user_id, err, exc_info=True)
        detail = str(err)
        return jsonify({
            "error": "v2_warm_up_tasks table missing or sync failed.",
            "detail": detail,
            "message": f"Confirm selection failed. Server said: {detail}",
        }), 503


@v2_bp.route("/admin/students/<user_id>/task-warm-up", methods=["POST"])
@require_admin
def v2_admin_task_warm_up_create(user_id):
    data = request.get_json() or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    data["user_id"] = user_id
    data["text"] = text
    data.setdefault("order_index", int(data.get("order_index", 0)))
    data.setdefault("max_performance_score", float(data.get("max_performance_score", 1.0)))
    try:
        row = db.v2_insert_warm_up_task(data)
        return jsonify({"task_warm_up": row}), 201
    except Exception as err:
        logger.warning("task-warm-up POST failed for user %s: %s", user_id, err, exc_info=True)
        return jsonify({"error": "Failed to create warm-up task. Check v2_warm_up_tasks table exists.", "detail": str(err)}), 503


@v2_bp.route("/admin/students/<user_id>/task-warm-up/<task_id>", methods=["PUT"])
@require_admin
def v2_admin_task_warm_up_update(user_id, task_id):
    data = request.get_json() or {}
    try:
        row = db.v2_update_warm_up_task(task_id, data)
        return jsonify({"task_warm_up": row}), 200
    except Exception as err:
        logger.warning("task-warm-up PUT update failed: %s", err, exc_info=True)
        return jsonify({"error": "Update failed.", "detail": str(err)}), 503


@v2_bp.route("/admin/students/<user_id>/task-warm-up/<task_id>", methods=["DELETE"])
@require_admin
def v2_admin_task_warm_up_delete(user_id, task_id):
    try:
        db.v2_delete_warm_up_task(task_id)
        return jsonify({"status": "ok"}), 200
    except Exception as err:
        logger.warning("task-warm-up DELETE failed: %s", err, exc_info=True)
        return jsonify({"error": "Delete failed.", "detail": str(err)}), 503


# ---------- Admin: task-focus pool (global) ----------
@v2_bp.route("/admin/task-focus-pool", methods=["GET"])
@require_admin
def v2_admin_task_focus_pool_list():
    try:
        data = db.v2_get_focus_task_pool()
        return jsonify({"task_focus_pool": data}), 200
    except Exception as err:
        logger.warning("task-focus-pool GET failed: %s", err, exc_info=True)
        return jsonify({"task_focus_pool": []}), 200


@v2_bp.route("/admin/task-focus-pool", methods=["POST"])
@require_admin
def v2_admin_task_focus_pool_create():
    data = request.get_json() or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    try:
        row = db.v2_insert_focus_task_pool({
            "text": text,
            "order_index": int(data.get("order_index", 0)),
            "max_performance_score": float(data.get("max_performance_score", 1.0)),
        })
        return jsonify({"task_focus": row}), 201
    except Exception as err:
        logger.warning("task-focus-pool POST failed: %s", err, exc_info=True)
        return jsonify({
            "error": "v2_focus_task_pool table missing. Run migrations/v2_focus_tasks.sql.",
            "detail": str(err),
        }), 503


@v2_bp.route("/admin/task-focus-pool/<pool_id>", methods=["PUT"])
@require_admin
def v2_admin_task_focus_pool_update(pool_id):
    data = request.get_json() or {}
    payload = {}
    if "text" in data and (data.get("text") or "").strip():
        payload["text"] = data["text"].strip()
    if "order_index" in data:
        payload["order_index"] = int(data["order_index"])
    if "max_performance_score" in data:
        try:
            payload["max_performance_score"] = float(data["max_performance_score"])
        except (TypeError, ValueError):
            pass
    if not payload:
        try:
            row = db.v2_get_focus_task_pool_by_id(pool_id)
            return jsonify({"task_focus": row}), 200
        except Exception:
            return jsonify({"error": "Not found"}), 404
    try:
        row = db.v2_update_focus_task_pool(pool_id, payload)
        return jsonify({"task_focus": row}), 200
    except Exception:
        return jsonify({"error": "Not found"}), 404


@v2_bp.route("/admin/task-focus-pool/<pool_id>", methods=["DELETE"])
@require_admin
def v2_admin_task_focus_pool_delete(pool_id):
    try:
        db.v2_delete_focus_task_pool(pool_id)
    except Exception:
        pass
    return jsonify({"status": "ok"}), 200


# ---------- Admin: task-focus (per student) ----------
@v2_bp.route("/admin/students/<user_id>/task-focus", methods=["GET"])
@require_admin
def v2_admin_task_focus_list(user_id):
    try:
        rows = db.v2_get_focus_tasks(user_id)
        return jsonify({"task_focus": rows}), 200
    except Exception as err:
        logger.warning("task-focus GET failed for user %s: %s", user_id, err, exc_info=True)
        return jsonify({"task_focus": []}), 200


@v2_bp.route("/admin/students/<user_id>/task-focus", methods=["PUT"])
@require_admin
def v2_admin_task_focus_sync(user_id):
    """Set this student's focus tasks from the pool. Body: { "pool_task_ids": [uuid, ...] } (order = display order)."""
    data = request.get_json() or {}
    pool_task_ids = data.get("pool_task_ids")
    if pool_task_ids is None:
        return jsonify({"error": "pool_task_ids is required"}), 400
    if not isinstance(pool_task_ids, list):
        return jsonify({"error": "pool_task_ids must be a list"}), 400
    pool_task_ids = [str(x) for x in pool_task_ids]
    try:
        rows = db.v2_sync_student_focus_tasks_from_pool(user_id, pool_task_ids)
        return jsonify({"task_focus": rows}), 200
    except Exception as err:
        logger.warning("task-focus PUT sync failed for user %s: %s", user_id, err, exc_info=True)
        return jsonify({
            "error": "v2_focus_tasks table missing or sync failed. Run migrations/v2_focus_tasks.sql.",
            "detail": str(err),
        }), 503


@v2_bp.route("/admin/students/<user_id>/task-focus", methods=["POST"])
@require_admin
def v2_admin_task_focus_create(user_id):
    data = request.get_json() or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    try:
        row = db.v2_insert_focus_task({
            "user_id": user_id,
            "text": text,
            "order_index": int(data.get("order_index", 0)),
            "max_performance_score": float(data.get("max_performance_score", 1.0)),
        })
        return jsonify({"task_focus": row}), 201
    except Exception as err:
        err_str = str(err).lower()
        logger.warning("task-focus POST failed for user %s: %s", user_id, err, exc_info=True)
        detail = str(err)
        if "relation" in err_str or "does not exist" in err_str or "42p01" in err_str:
            msg = "v2_focus_tasks table missing. Run migrations/v2_focus_tasks.sql."
        else:
            msg = "Failed to create focus task. Run migrations/v2_focus_tasks.sql if not done."
        return jsonify({
            "error": msg,
            "detail": detail,
            "message": f"{msg} Server said: {detail}",
        }), 503


@v2_bp.route("/admin/students/<user_id>/task-focus/<task_id>", methods=["PUT"])
@require_admin
def v2_admin_task_focus_update(user_id, task_id):
    data = request.get_json() or {}
    try:
        row = db.v2_update_focus_task(task_id, data)
        if not row:
            return jsonify({"error": "Not found"}), 404
        return jsonify({"task_focus": row}), 200
    except Exception:
        return jsonify({"error": "Not found"}), 404


@v2_bp.route("/admin/students/<user_id>/task-focus/<task_id>", methods=["DELETE"])
@require_admin
def v2_admin_task_focus_delete(user_id, task_id):
    try:
        db.v2_delete_focus_task(task_id)
    except Exception:
        pass
    return jsonify({"status": "ok"}), 200


# ---------- Admin: post-recording questions (per student) ----------
@v2_bp.route("/admin/students/<user_id>/post-recording-questions", methods=["GET"])
@require_admin
def v2_admin_student_post_recording_questions_list(user_id):
    try:
        rows = db.v2_get_student_post_recording_questions(user_id)
        return jsonify({"post_recording_questions": rows}), 200
    except Exception as err:
        logger.warning("post-recording-questions GET failed for user %s: %s", user_id, err, exc_info=True)
        return jsonify({"post_recording_questions": []}), 200


@v2_bp.route("/admin/students/<user_id>/post-recording-questions", methods=["PUT"])
@require_admin
def v2_admin_student_post_recording_questions_sync(user_id):
    """Set this student's post-recording questions from the pool. Body: { "pool_question_ids": [uuid, ...] } (order = display order)."""
    data = request.get_json() or {}
    pool_question_ids = data.get("pool_question_ids")
    if pool_question_ids is None:
        return jsonify({"error": "pool_question_ids is required"}), 400
    if not isinstance(pool_question_ids, list):
        return jsonify({"error": "pool_question_ids must be a list"}), 400
    pool_question_ids = [str(x) for x in pool_question_ids]
    try:
        rows = db.v2_sync_student_post_recording_questions_from_pool(user_id, pool_question_ids)
        return jsonify({"post_recording_questions": rows}), 200
    except Exception as err:
        logger.warning("post-recording-questions PUT sync failed for user %s: %s", user_id, err, exc_info=True)
        return jsonify({
            "error": "v2_student_post_recording_questions sync failed.",
            "detail": str(err),
        }), 503


@v2_bp.route("/admin/students/<user_id>/post-recording-questions", methods=["POST"])
@require_admin
def v2_admin_student_post_recording_questions_create(user_id):
    data = request.get_json() or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    data["user_id"] = user_id
    data["text"] = text
    data.setdefault("order_index", 0)
    data.setdefault("answer_type", "text")
    try:
        row = db.v2_insert_student_post_recording_question(data)
        return jsonify({"post_recording_question": row}), 201
    except Exception as err:
        logger.warning("post-recording-questions POST failed for user %s: %s", user_id, err, exc_info=True)
        return jsonify({"error": "Failed to create post-recording question.", "detail": str(err)}), 503


@v2_bp.route("/admin/students/<user_id>/post-recording-questions/<question_id>", methods=["PUT"])
@require_admin
def v2_admin_student_post_recording_questions_update(user_id, question_id):
    data = request.get_json() or {}
    try:
        row = db.v2_update_student_post_recording_question(question_id, data)
        return jsonify({"post_recording_question": row}), 200
    except Exception as err:
        logger.warning("post-recording-questions PUT update failed: %s", err, exc_info=True)
        return jsonify({"error": "Update failed.", "detail": str(err)}), 503


@v2_bp.route("/admin/students/<user_id>/post-recording-questions/<question_id>", methods=["DELETE"])
@require_admin
def v2_admin_student_post_recording_questions_delete(user_id, question_id):
    try:
        db.v2_delete_student_post_recording_question(question_id)
        return jsonify({"status": "ok"}), 200
    except Exception as err:
        logger.warning("post-recording-questions DELETE failed: %s", err, exc_info=True)
        return jsonify({"error": "Delete failed.", "detail": str(err)}), 503


# ---------- Admin: metric questions (legacy 2-question table) ----------
@v2_bp.route("/admin/metric-questions", methods=["GET"])
@require_admin
def v2_admin_metric_questions_list():
    rows = db.v2_get_metric_questions()
    return jsonify({"questions": rows}), 200


@v2_bp.route("/admin/metric-questions", methods=["POST"])
@require_admin
def v2_admin_metric_questions_create():
    data = request.get_json() or {}
    if data.get("position") not in (1, 2):
        return jsonify({"code": "INVALID_INPUT", "error": "position must be 1 or 2"}), 400
    row = db.v2_insert_metric_question(data)
    return jsonify({"question": row}), 201


@v2_bp.route("/admin/metric-questions/<question_id>", methods=["PUT"])
@require_admin
def v2_admin_metric_questions_update(question_id):
    data = request.get_json() or {}
    row = db.v2_update_metric_question(question_id, data)
    return jsonify({"question": row}), 200


@v2_bp.route("/admin/metric-questions/<question_id>", methods=["DELETE"])
@require_admin
def v2_admin_metric_questions_delete(question_id):
    db.v2_delete_metric_question(question_id)
    return jsonify({"status": "ok"}), 200


# ---------- Admin: metric questions (v2_metric_questions table; positions 1, 2, 3 for task block) ----------
@v2_bp.route("/admin/metric-questions-pool", methods=["GET"])
@require_admin
def v2_admin_metric_questions_pool_list():
    rows = db.v2_get_metric_questions()
    return jsonify({"metric_questions_pool": rows}), 200


@v2_bp.route("/admin/metric-questions-pool", methods=["POST"])
@require_admin
def v2_admin_metric_questions_pool_create():
    data = request.get_json() or {}
    if not (data.get("text") or "").strip():
        return jsonify({"error": "text is required", "hint": "Send JSON body: { \"text\": \"question text\", \"position\": 1|2|3 }"}), 400
    position = int(data.get("position", 1))
    if position not in (1, 2, 3):
        return jsonify({"error": "position must be 1, 2, or 3"}), 400
    payload = {"text": data["text"].strip(), "position": position}
    try:
        row = db.v2_insert_metric_question(payload)
        return jsonify({"metric_question": row}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@v2_bp.route("/admin/metric-questions-pool/<question_id>", methods=["PUT"])
@require_admin
def v2_admin_metric_questions_pool_update(question_id):
    data = request.get_json() or {}
    payload = {k: data[k] for k in ("text", "position") if k in data}
    if "position" in payload:
        payload["position"] = int(payload["position"])
        if payload["position"] not in (1, 2, 3):
            return jsonify({"error": "position must be 1, 2, or 3"}), 400
    if payload:
        row = db.v2_update_metric_question(question_id, payload)
    else:
        rows = db.v2_get_metric_questions()
        row = next((r for r in rows if str(r.get("id")) == str(question_id)), None)
    if not row:
        return jsonify({"error": "Question not found"}), 404
    return jsonify({"metric_question": row}), 200


@v2_bp.route("/admin/metric-questions-pool/<question_id>", methods=["DELETE"])
@require_admin
def v2_admin_metric_questions_pool_delete(question_id):
    try:
        db.v2_delete_metric_question(question_id)
    except Exception:
        pass
    return jsonify({"status": "ok"}), 200


# ---------- Admin: metric definitions (GET + PUT labels) ----------
@v2_bp.route("/admin/metric-definitions", methods=["GET"])
@require_admin
def v2_admin_metric_definitions_get():
    rows = db.v2_get_metric_definitions()
    return jsonify({"metric_definitions": rows}), 200


@v2_bp.route("/admin/metric-definitions", methods=["PUT"])
@require_admin
def v2_admin_metric_definitions_put():
    data = request.get_json() or {}
    for item in data.get("metric_definitions", data) if isinstance(data.get("metric_definitions"), list) else [data]:
        code = item.get("code")
        if not code:
            continue
        db.v2_upsert_metric_definition(code, item.get("left_label", ""), item.get("right_label", ""))
    return jsonify({"status": "ok"}), 200


# ---------- Admin: metrics (alias for frontend spec: GET/PUT /v2/admin/metrics) ----------
@v2_bp.route("/admin/metrics", methods=["GET"])
@require_admin
def v2_admin_metrics_get():
    """Return metric label pairs as metrics or metric_labels for frontend."""
    rows = db.v2_get_metric_definitions()
    return jsonify({"metrics": rows}), 200


@v2_bp.route("/admin/metrics", methods=["PUT"])
@require_admin
def v2_admin_metrics_put():
    """Accept { metrics: [ { code, left_label, right_label }, ... ] }."""
    data = request.get_json() or {}
    items = data.get("metrics", data.get("metric_labels", []))
    if not isinstance(items, list):
        items = [data] if data.get("code") else []
    for item in items:
        code = item.get("code")
        if not code:
            continue
        db.v2_upsert_metric_definition(code, item.get("left_label", ""), item.get("right_label", ""))
    return jsonify({"status": "ok"}), 200
