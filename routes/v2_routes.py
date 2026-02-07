"""
V2: admin CRUD only. Student flow is homework only (routes/homework.py).
All /v2/admin/* require auth + admin.
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from routes.admin import require_admin
from services.db import db
from services.email_service import email_service
import logging
import sentry_sdk

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
    """List students with email (and optional stats). Required: user_id, email for UI."""
    try:
        limit = request.args.get("limit", default=20, type=int)
        offset = request.args.get("offset", default=0, type=int)
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
                    pass  # optional stats: skip on error
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
@require_admin
def v2_admin_student_profile(user_id):
    """Student profile for simplified admin panel: one page with Homework Configuration, Speaker Profile, Reports History.
    Contract: user_id, email, overrides (assigned_post_question_ids[], assigned_next_task_ids[]), speaker_profile (coach_notes),
    sessions (id, created_at, status, report_preview.report_text_preview)."""
    try:
        email = db.get_user_email_from_auth(user_id)
        raw_overrides = db.v2_get_student_overrides(user_id)
        overrides = dict(raw_overrides) if raw_overrides else {}
        overrides["assigned_post_question_ids"] = overrides.get("assigned_post_question_ids") or []
        overrides["assigned_next_task_ids"] = overrides.get("assigned_next_task_ids") or []
        speaker_profile = db.v2_get_speaker_profile(user_id)
        warm_up_tasks = db.v2_get_warm_up_tasks(user_id)
        last_report = db.v2_get_last_report_for_user(user_id)
        sessions = db.v2_get_sessions_with_previews(user_id, limit=50)
        return jsonify({
            "user_id": user_id,
            "email": email,
            "overrides": overrides,
            "speaker_profile": speaker_profile,
            "warm_up_tasks": warm_up_tasks,
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


@v2_bp.route("/admin/students/<user_id>/overrides", methods=["PUT"])
@require_admin
def v2_admin_student_overrides(user_id):
    """Set prompts, assigned post Qs (0 or any number of question IDs), next exercise/task."""
    try:
        data = request.get_json() or {}
        ids = data.get("assigned_post_question_ids")
        if ids is not None and not isinstance(ids, list):
            return jsonify({"code": "INVALID_INPUT", "error": "assigned_post_question_ids must be an array"}), 400
        db.v2_upsert_student_overrides(user_id, data)
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/send-assignment", methods=["POST"])
@require_admin
def v2_admin_send_assignment(user_id):
    """Send homework email to the student. Requires student to have an email in Supabase Auth."""
    try:
        from config import Config
        config = Config()
        student_email = db.get_user_email_from_auth(user_id)
        if not student_email or not student_email.strip():
            return jsonify({"code": "NO_EMAIL", "error": "Student has no email in auth"}), 400
        result = email_service.send_assignment_to_student(
            to_email=student_email.strip(),
            frontend_url=config.FRONTEND_URL,
        )
        if result.get("status") == "failed":
            return jsonify({"code": "EMAIL_FAILED", "error": result.get("error", "Failed to send email")}), 500
        return jsonify({"status": "ok", "message": "Assignment sent", "sent": result.get("sent", False)}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/sessions/<session_id>", methods=["GET"])
@require_admin
def v2_admin_student_session_detail(user_id, session_id):
    """Get full session for admin (e.g. report history context_long_entries). Session must belong to user_id."""
    try:
        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        return jsonify({"session": session}), 200
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
    row = db.v2_insert_exercise(data)
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


# ---------- Admin CRUD: post-recording questions pool ----------
@v2_bp.route("/admin/post-recording-questions", methods=["GET"])
@require_admin
def v2_admin_post_questions_list():
    result = db.client.table("v2_post_recording_questions").select("*").execute()
    return jsonify({"questions": result.data or []}), 200


@v2_bp.route("/admin/post-recording-questions", methods=["POST"])
@require_admin
def v2_admin_post_questions_create():
    data = request.get_json() or {}
    row = db.v2_insert_post_question_pool(data)
    return jsonify({"question": row}), 201


@v2_bp.route("/admin/post-recording-questions/<question_id>", methods=["PUT"])
@require_admin
def v2_admin_post_questions_update(question_id):
    data = request.get_json() or {}
    row = db.v2_update_post_question_pool(question_id, data)
    return jsonify({"question": row}), 200


@v2_bp.route("/admin/post-recording-questions/<question_id>", methods=["DELETE"])
@require_admin
def v2_admin_post_questions_delete(question_id):
    db.v2_delete_post_question_pool(question_id)
    return jsonify({"status": "ok"}), 200


# ---------- Admin: warm-up task pool (same pattern as post-recording-questions) ----------
@v2_bp.route("/admin/warm-up-task-pool", methods=["GET"])
@require_admin
def v2_admin_warm_up_task_pool_list():
    try:
        result = db.client.table("v2_warm_up_task_pool").select("*").order("order_index").order("created_at").execute()
        data = result.data or []
    except Exception:
        data = []
    return jsonify({"warm_up_task_pool": data}), 200


@v2_bp.route("/admin/warm-up-task-pool", methods=["POST"])
@require_admin
def v2_admin_warm_up_task_pool_create():
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
        return jsonify({"warm_up_task": row}), 201
    except Exception as e:
        err = str(e).lower()
        hint = "Run migrations/v2_warm_up_task_pool.sql to create the table." if ("relation" in err or "does not exist" in err or "42p01" in err) else None
        out = {"error": str(e)}
        if hint:
            out["hint"] = hint
        return jsonify(out), 500


@v2_bp.route("/admin/warm-up-task-pool/<pool_id>", methods=["PUT"])
@require_admin
def v2_admin_warm_up_task_pool_update(pool_id):
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
    return jsonify({"warm_up_task": row}), 200


@v2_bp.route("/admin/warm-up-task-pool/<pool_id>", methods=["DELETE"])
@require_admin
def v2_admin_warm_up_task_pool_delete(pool_id):
    try:
        db.client.table("v2_warm_up_task_pool").delete().eq("id", pool_id).execute()
    except Exception:
        pass
    return jsonify({"status": "ok"}), 200


# ---------- Admin: warm-up tasks (per student; homework flow) ----------
@v2_bp.route("/admin/students/<user_id>/warm-up-tasks", methods=["GET"])
@require_admin
def v2_admin_warm_up_tasks_list(user_id):
    rows = db.v2_get_warm_up_tasks(user_id)
    return jsonify({"warm_up_tasks": rows}), 200


@v2_bp.route("/admin/students/<user_id>/warm-up-tasks", methods=["PUT"])
@require_admin
def v2_admin_warm_up_tasks_sync(user_id):
    """Set this student's warm-up tasks from the pool. Body: { "pool_task_ids": [uuid, ...] } (order = display order)."""
    data = request.get_json() or {}
    pool_task_ids = data.get("pool_task_ids")
    if pool_task_ids is None:
        return jsonify({"error": "pool_task_ids is required"}), 400
    if not isinstance(pool_task_ids, list):
        return jsonify({"error": "pool_task_ids must be a list"}), 400
    pool_task_ids = [str(x) for x in pool_task_ids]
    rows = db.v2_sync_student_warm_up_tasks_from_pool(user_id, pool_task_ids)
    return jsonify({"warm_up_tasks": rows}), 200


@v2_bp.route("/admin/students/<user_id>/warm-up-tasks", methods=["POST"])
@require_admin
def v2_admin_warm_up_tasks_create(user_id):
    data = request.get_json() or {}
    data["user_id"] = user_id
    data.setdefault("order_index", 0)
    data.setdefault("max_performance_score", 1.0)  # 0-1; show if student's last score <= this (easiest = 1.0)
    row = db.v2_insert_warm_up_task(data)
    return jsonify({"warm_up_task": row}), 201


@v2_bp.route("/admin/students/<user_id>/warm-up-tasks/<task_id>", methods=["PUT"])
@require_admin
def v2_admin_warm_up_tasks_update(user_id, task_id):
    data = request.get_json() or {}
    row = db.v2_update_warm_up_task(task_id, data)
    return jsonify({"warm_up_task": row}), 200


@v2_bp.route("/admin/students/<user_id>/warm-up-tasks/<task_id>", methods=["DELETE"])
@require_admin
def v2_admin_warm_up_tasks_delete(user_id, task_id):
    db.v2_delete_warm_up_task(task_id)
    return jsonify({"status": "ok"}), 200


# ---------- Admin: focus question pool (global) ----------
@v2_bp.route("/admin/focus-question-pool", methods=["GET"])
@require_admin
def v2_admin_focus_question_pool_list():
    try:
        data = db.v2_get_focus_question_pool()
    except Exception as err:
        err_str = str(err).lower()
        if "relation" in err_str or "does not exist" in err_str or "42p01" in err_str:
            return jsonify({"focus_question_pool": []}), 200
        raise
    return jsonify({"focus_question_pool": data}), 200


@v2_bp.route("/admin/focus-question-pool", methods=["POST"])
@require_admin
def v2_admin_focus_question_pool_create():
    data = request.get_json() or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    try:
        row = db.v2_insert_focus_question_pool({
            "text": text,
            "order_index": int(data.get("order_index", 0)),
            "max_performance_score": float(data.get("max_performance_score", 1.0)),
        })
        return jsonify({"focus_question": row}), 201
    except Exception as err:
        err_str = str(err).lower()
        if "relation" in err_str or "does not exist" in err_str or "42p01" in err_str:
            return jsonify({"error": "v2_focus_question_pool table missing. Run migrations/v2_focus_questions.sql."}), 503
        raise


@v2_bp.route("/admin/focus-question-pool/<pool_id>", methods=["PUT"])
@require_admin
def v2_admin_focus_question_pool_update(pool_id):
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
            row = db.v2_get_focus_question_pool_by_id(pool_id)
            return jsonify({"focus_question": row}), 200
        except Exception:
            return jsonify({"error": "Not found"}), 404
    try:
        row = db.v2_update_focus_question_pool(pool_id, payload)
        return jsonify({"focus_question": row}), 200
    except Exception:
        return jsonify({"error": "Not found"}), 404


@v2_bp.route("/admin/focus-question-pool/<pool_id>", methods=["DELETE"])
@require_admin
def v2_admin_focus_question_pool_delete(pool_id):
    try:
        db.v2_delete_focus_question_pool(pool_id)
    except Exception:
        pass
    return jsonify({"status": "ok"}), 200


# ---------- Admin: focus questions (per student) ----------
@v2_bp.route("/admin/students/<user_id>/focus-questions", methods=["GET"])
@require_admin
def v2_admin_focus_questions_list(user_id):
    try:
        rows = db.v2_get_focus_questions(user_id)
    except Exception as err:
        err_str = str(err).lower()
        if "relation" in err_str or "does not exist" in err_str or "42p01" in err_str:
            return jsonify({"focus_questions": []}), 200
        raise
    return jsonify({"focus_questions": rows}), 200


@v2_bp.route("/admin/students/<user_id>/focus-questions", methods=["PUT"])
@require_admin
def v2_admin_focus_questions_sync(user_id):
    """Set this student's focus questions from the pool. Body: { "pool_question_ids": [uuid, ...] } (order = display order)."""
    data = request.get_json() or {}
    pool_question_ids = data.get("pool_question_ids")
    if pool_question_ids is None:
        return jsonify({"error": "pool_question_ids is required"}), 400
    if not isinstance(pool_question_ids, list):
        return jsonify({"error": "pool_question_ids must be a list"}), 400
    pool_question_ids = [str(x) for x in pool_question_ids]
    try:
        rows = db.v2_sync_student_focus_questions_from_pool(user_id, pool_question_ids)
    except Exception as err:
        err_str = str(err).lower()
        if "relation" in err_str or "does not exist" in err_str or "42p01" in err_str:
            return jsonify({"error": "v2_focus_questions table missing. Run migrations/v2_focus_questions.sql."}), 503
        raise
    return jsonify({"focus_questions": rows}), 200


@v2_bp.route("/admin/students/<user_id>/focus-questions", methods=["POST"])
@require_admin
def v2_admin_focus_questions_create(user_id):
    data = request.get_json() or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    try:
        row = db.v2_insert_focus_question({
            "user_id": user_id,
            "text": text,
            "order_index": int(data.get("order_index", 0)),
            "max_performance_score": float(data.get("max_performance_score", 1.0)),
        })
        return jsonify({"focus_question": row}), 201
    except Exception as err:
        err_str = str(err).lower()
        if "relation" in err_str or "does not exist" in err_str or "42p01" in err_str:
            return jsonify({"error": "v2_focus_questions table missing. Run migrations/v2_focus_questions.sql."}), 503
        raise


@v2_bp.route("/admin/students/<user_id>/focus-questions/<question_id>", methods=["PUT"])
@require_admin
def v2_admin_focus_questions_update(user_id, question_id):
    data = request.get_json() or {}
    try:
        row = db.v2_update_focus_question(question_id, data)
        if not row:
            return jsonify({"error": "Not found"}), 404
        return jsonify({"focus_question": row}), 200
    except Exception:
        return jsonify({"error": "Not found"}), 404


@v2_bp.route("/admin/students/<user_id>/focus-questions/<question_id>", methods=["DELETE"])
@require_admin
def v2_admin_focus_questions_delete(user_id, question_id):
    try:
        db.v2_delete_focus_question(question_id)
    except Exception:
        pass
    return jsonify({"status": "ok"}), 200


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
