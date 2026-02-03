"""
V2 flow: student endpoints + admin CRUD.
All /v2/* require auth; /v2/admin/* require admin.
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from routes.admin import require_admin
from services.db import db
from services.v2_flow_service import (
    compute_task_score,
    select_exercise_for_task_score,
    select_tasks_for_task_score,
    select_post_questions_v2,
)
from services.metrics_v2 import compute_metrics_v2
from utils.metrics import count_fillers, compute_wpm
import logging
import json
import uuid
import sentry_sdk

logger = logging.getLogger(__name__)
v2_bp = Blueprint("v2", __name__, url_prefix="/v2")


# ---------- Student: universal questions ----------
@v2_bp.route("/universal-questions", methods=["GET"])
@require_auth
def get_universal_questions():
    """GET /v2/universal-questions. Returns array of questions so frontend can use .find() on the response."""
    try:
        questions = db.v2_get_universal_questions()
        return jsonify(questions), 200
    except Exception as e:
        logger.error(f"V2 universal-questions error: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Student: session start (resume or new) ----------
@v2_bp.route("/session/start", methods=["POST"])
@require_auth
def v2_session_start():
    """POST /v2/session/start. Resume active or create new."""
    try:
        user_id = request.user_id
        data = request.get_json() or {}
        session_id = data.get("session_id")

        active = db.v2_get_active_session(user_id)
        if active:
            return jsonify({"session": active, "session_id": active["id"]}), 200

        session = db.v2_create_session(user_id)
        if not session:
            return jsonify({"code": "V2_ERROR", "error": "Failed to create session"}), 500
        return jsonify({"session": session, "session_id": session["id"]}), 201
    except Exception as e:
        logger.error(f"V2 session start error: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Student: universal answers -> plan ----------
@v2_bp.route("/session/<session_id>/universal-answers", methods=["POST"])
@require_auth
def v2_universal_answers(session_id):
    """POST body: mood (0..1), readiness (1..10), mode_preference (0|1). Returns task_score, exercise, tasks, post_questions."""
    try:
        user_id = request.user_id
        data = request.get_json() or {}
        mood = data.get("mood")
        readiness = data.get("readiness", 5)
        mode_preference = data.get("mode_preference", 0)

        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        if session.get("status") != "universal_questions":
            return jsonify({"code": "INVALID_STATE", "error": "Session already past universal questions"}), 400

        task_score = compute_task_score(mood, readiness, mode_preference)
        overrides = db.v2_get_student_overrides(user_id)
        exercises = db.v2_get_active_exercises()
        exercise = select_exercise_for_task_score(
            exercises,
            task_score,
            (overrides.get("assigned_next_exercise_id") if overrides else None),
        )
        tasks = db.v2_get_active_tasks()
        task_options = select_tasks_for_task_score(
            tasks,
            task_score,
            mode_preference,
            count=3,
            assigned_task_ids=overrides.get("assigned_next_task_ids") if overrides else None,
            exclude_recent_ids=None,
        )
        pool = db.v2_get_post_questions_pool()
        assigned_ids = overrides.get("assigned_post_question_ids") if overrides else None
        post_questions = select_post_questions_v2(pool, assigned_ids=assigned_ids)

        if mode_preference == 0:
            selected_task = task_options[0] if task_options else None
            task_option_ids = None
        else:
            selected_task = None
            task_option_ids = [str(t["id"]) for t in task_options[:3]]

        intent_prompts = {}
        if overrides:
            if overrides.get("intended_emotion_prompt"):
                intent_prompts["intended_emotion"] = overrides["intended_emotion_prompt"]
            if overrides.get("keywords_prompt"):
                intent_prompts["keywords"] = overrides["keywords_prompt"]
        if "intended_emotion" not in intent_prompts:
            intent_prompts["intended_emotion"] = "What emotion do you intend to convey?"
        if "keywords" not in intent_prompts:
            intent_prompts["keywords"] = "Enter 3 keywords you want to use."

        emotion_check_text = (overrides.get("emotion_check_question_text") if overrides else None) or "Did you achieve the intended emotion?"

        # Update session
        update = {
            "universal_answers": {"mood": mood, "readiness": readiness, "mode_preference": mode_preference},
            "task_score": task_score,
            "mode_preference": mode_preference,
            "selected_exercise_id": exercise["id"] if exercise else None,
            "selected_task_id": selected_task["id"] if selected_task else None,
            "task_option_ids": task_option_ids,
            "post_question_ids": [str(q["id"]) for q in post_questions],
            "status": "exercise" if exercise else "task",
        }
        db.v2_update_session(session_id, user_id, update)

        # Build response
        exercise_out = None
        if exercise:
            exercise_out = {"id": exercise["id"], "title": exercise.get("title"), "video_url": exercise.get("video_url"), "description": exercise.get("description")}

        tasks_out = []
        if selected_task:
            tasks_out = [{"id": selected_task["id"], "title": selected_task.get("title"), "prompt_text": selected_task.get("prompt_text")}]
        else:
            for t in task_options[:3]:
                tasks_out.append({"id": t["id"], "title": t.get("title"), "prompt_text": t.get("prompt_text")})

        post_out = []
        for q in post_questions:
            text = emotion_check_text if q.get("code") == "emotion_achieved_check" else q.get("text", "")
            post_out.append({"id": q["id"], "code": q.get("code"), "text": text, "answer_type": q.get("answer_type")})

        return jsonify({
            "task_score": task_score,
            "exercise": exercise_out,
            "selected_task": tasks_out[0] if mode_preference == 0 and tasks_out else None,
            "task_options": tasks_out if mode_preference == 1 else None,
            "intent_prompts": intent_prompts,
            "post_recording_questions": post_out,
        }), 200
    except Exception as e:
        logger.error(f"V2 universal-answers error: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Student: exercise feedback ----------
@v2_bp.route("/session/<session_id>/exercise-feedback", methods=["POST"])
@require_auth
def v2_exercise_feedback(session_id):
    """POST body: exercise_liked (bool)."""
    try:
        user_id = request.user_id
        data = request.get_json() or {}
        liked = data.get("exercise_liked")

        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND"}), 404
        db.v2_update_session(session_id, user_id, {"exercise_liked": liked, "status": "task"})
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Student: select task (choose mode) ----------
@v2_bp.route("/session/<session_id>/select-task", methods=["POST"])
@require_auth
def v2_select_task(session_id):
    """POST body: task_id (uuid)."""
    try:
        user_id = request.user_id
        data = request.get_json() or {}
        task_id = data.get("task_id")
        if not task_id:
            return jsonify({"code": "INVALID_INPUT", "error": "task_id required"}), 400

        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND"}), 404
        task = db.v2_get_task(task_id)
        if not task:
            return jsonify({"code": "NOT_FOUND", "error": "Task not found"}), 404
        db.v2_update_session(session_id, user_id, {"selected_task_id": task_id, "status": "recording_ready"})
        return jsonify({"task": {"id": task["id"], "title": task.get("title"), "prompt_text": task.get("prompt_text")}}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Student: intent (emotion + keywords) ----------
@v2_bp.route("/session/<session_id>/intent", methods=["POST"])
@require_auth
def v2_intent(session_id):
    """POST body: intended_emotion (text), keywords ([3] strings)."""
    try:
        user_id = request.user_id
        data = request.get_json() or {}
        intended_emotion = data.get("intended_emotion", "")
        keywords = data.get("keywords")
        if not isinstance(keywords, list):
            keywords = []
        keywords = [str(k).strip() for k in keywords[:3]]
        while len(keywords) < 3:
            keywords.append("")

        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND"}), 404
        db.v2_update_session(session_id, user_id, {"intended_emotion": intended_emotion, "keywords": keywords, "status": "recording_ready"})
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Student: recording upload ----------
@v2_bp.route("/recordings/upload", methods=["POST"])
@require_auth
def v2_recordings_upload():
    """Multipart: session_id, task_id, audio, duration_seconds (optional). Transcribe, compute preliminary metrics (pace, strength stub, fillers, keywords)."""
    try:
        from config import Config
        from services.openai_service import openai_service

        user_id = request.user_id
        session_id = request.form.get("session_id")
        task_id = request.form.get("task_id")
        audio_file = request.files.get("audio")

        if not session_id or not task_id or not audio_file:
            return jsonify({"code": "INVALID_INPUT", "error": "session_id, task_id, and audio required"}), 400

        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND"}), 404

        config = Config()
        ext = ".webm"
        storage_path = f"{user_id}/{session_id}/{uuid.uuid4()}{ext}"
        audio_file.seek(0)
        audio_data = audio_file.read()
        content_type = str(audio_file.content_type or "audio/webm")
        if content_type in ("True", "False"):
            content_type = "audio/webm"

        db.upload_audio(config.AUDIO_BUCKET_NAME, storage_path, audio_data, content_type=content_type)
        audio_url = db.create_signed_url(config.AUDIO_BUCKET_NAME, storage_path, config.SIGNED_URL_EXPIRY_SECONDS)
        if not audio_url:
            supabase_url = config.SUPABASE_URL.rstrip("/")
            audio_url = f"{supabase_url}/storage/v1/object/public/{config.AUDIO_BUCKET_NAME}/{storage_path}"

        audio_file.seek(0)
        transcript_result = openai_service.transcribe_audio(audio_file, "audio.webm")
        transcript_text = transcript_result["text"]
        duration_seconds = transcript_result.get("duration") or float(request.form.get("duration_seconds") or 60.0)

        wpm = compute_wpm(transcript_text, duration_seconds)
        filler_data = count_fillers(transcript_text)
        filler_count = filler_data["total"]
        keywords = session.get("keywords") or []
        strength_raw = None  # TODO: compute RMS from audio if needed; stub for now

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
        performance_metrics_v2 = prelim["metrics"]
        performance_score_v2 = prelim["performance_score"]
        metric_labels_snapshot_v2 = prelim["metric_labels_snapshot"]

        duration_int = int(round(duration_seconds))
        recording_data = {
            "user_id": user_id,
            "session_id": None,
            "session_v2_id": session_id,
            "task_id": task_id,
            "audio_url": audio_url,
            "storage_path": storage_path,
            "duration": duration_int,
            "duration_seconds": duration_seconds,
            "transcription_text": transcript_text,
            "words_per_minute": wpm,
            "filler_words_count": {"breakdown": filler_data.get("breakdown", {}), "total": filler_count},
            "performance_score_v2": performance_score_v2,
            "performance_metrics_v2": performance_metrics_v2,
            "metric_labels_snapshot_v2": metric_labels_snapshot_v2,
        }
        recording = db.create_recording(recording_data)
        if not recording:
            return jsonify({"code": "RECORDING_CREATE_FAILED"}), 500

        db.v2_update_session(session_id, user_id, {"recording_id": recording["id"], "status": "post_questions"})
        return jsonify({
            "recording_id": recording["id"],
            "performance_score": performance_score_v2,
            "performance_metrics": performance_metrics_v2,
            "metric_labels_snapshot": metric_labels_snapshot_v2,
        }), 200
    except Exception as e:
        logger.error(f"V2 upload error: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Student: post-answers -> finalize metrics + report ----------
@v2_bp.route("/session/<session_id>/post-answers", methods=["POST"])
@require_auth
def v2_post_answers(session_id):
    """POST body: answers [{ question_id, answer_text }]. Finalize emotion_achieved, recompute performance_score, generate report."""
    try:
        from services.openai_service import openai_service

        user_id = request.user_id
        data = request.get_json() or {}
        answers = data.get("answers", [])

        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND"}), 404
        recording_id = session.get("recording_id")
        if not recording_id:
            return jsonify({"code": "INVALID_STATE", "error": "No recording for session"}), 400

        recording = db.get_recording(recording_id, user_id)
        if not recording:
            return jsonify({"code": "RECORDING_NOT_FOUND"}), 404

        post_question_ids = session.get("post_question_ids") or []
        emotion_achieved = False
        for ans in answers:
            qid = str(ans.get("question_id", ""))
            if qid not in post_question_ids:
                continue
            # Find which question has code emotion_achieved_check (we need to resolve by id -> code)
            pool = db.v2_get_post_questions_by_ids(post_question_ids)
            for q in pool:
                if str(q["id"]) == qid and q.get("code") == "emotion_achieved_check":
                    text = (ans.get("answer_text") or "").strip().upper()
                    emotion_achieved = text in ("YES", "Y", "1", "TRUE")
                    break

        transcript = recording.get("transcription_text") or ""
        wpm = float(recording.get("words_per_minute") or 0)
        filler_data = recording.get("filler_words_count") or {}
        filler_count = int(filler_data.get("total", 0)) if isinstance(filler_data, dict) else 0
        keywords = session.get("keywords") or []
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
            keywords=keywords,
            metric_definitions=metric_defs,
        )

        db.update_recording(recording_id, {
            "performance_score_v2": final["performance_score"],
            "performance_metrics_v2": final["metrics"],
            "metric_labels_snapshot_v2": final["metric_labels_snapshot"],
        })

        report_text = f"Your performance score: {final['performance_score']:.0%}. "
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
                recording_id=recording_id,
            ) or report_text
        except Exception as e:
            logger.warning(f"Report generation failed: {e}")
            report_text += "Details: pace, strength, fillers, emotion, keywords."

        report = db.v2_create_report(session_id, recording_id, report_text)
        db.v2_update_session(session_id, user_id, {
            "post_answers": answers,
            "report_id": report["id"] if report else None,
            "status": "completed",
        })

        return jsonify({
            "report_text": report_text,
            "performance_score": final["performance_score"],
            "performance_metrics": final["metrics"],
            "metric_labels_snapshot": final["metric_labels_snapshot"],
        }), 200
    except Exception as e:
        logger.error(f"V2 post-answers error: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Student: session status ----------
@v2_bp.route("/session/status", methods=["GET"])
@require_auth
def v2_session_status():
    """GET /v2/session/status. Returns active v2 session or null."""
    try:
        user_id = request.user_id
        active = db.v2_get_active_session(user_id)
        if not active:
            return jsonify({"session": None, "has_active_session": False}), 200
        return jsonify({"session": active, "session_id": active["id"], "has_active_session": True}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Admin ----------
@v2_bp.route("/admin/students", methods=["GET"])
@require_admin
def v2_admin_students():
    """List user_ids with v2 sessions (paginated)."""
    try:
        limit = request.args.get("limit", default=20, type=int)
        offset = request.args.get("offset", default=0, type=int)
        user_ids = db.v2_list_users_with_sessions(limit=limit, offset=offset)
        # TODO: enrich with email from auth if needed
        return jsonify({"students": [{"user_id": uid} for uid in user_ids], "limit": limit, "offset": offset}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>", methods=["GET"])
@require_admin
def v2_admin_student_profile(user_id):
    """Speaker profile + overrides + sessions + recordings."""
    try:
        overrides = db.v2_get_student_overrides(user_id)
        sessions = db.client.table("v2_sessions").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(50).execute()
        return jsonify({
            "user_id": user_id,
            "overrides": overrides,
            "sessions": sessions.data or [],
        }), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/overrides", methods=["PUT"])
@require_admin
def v2_admin_student_overrides(user_id):
    """Set prompts, assigned post Qs, next exercise/task."""
    try:
        data = request.get_json() or {}
        db.v2_upsert_student_overrides(user_id, data)
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/send-assignment", methods=["POST"])
@require_admin
def v2_admin_send_assignment(user_id):
    """Stub: store assignment and optionally email (Resend)."""
    try:
        # TODO: create assignment record and send email via email_service
        return jsonify({"status": "ok", "message": "Assignment sent"}), 200
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


# ---------- Admin CRUD: tasks ----------
@v2_bp.route("/admin/tasks", methods=["GET"])
@require_admin
def v2_admin_tasks_list():
    result = db.client.table("v2_tasks").select("*").order("created_at", desc=True).execute()
    return jsonify({"tasks": result.data or []}), 200


@v2_bp.route("/admin/tasks", methods=["POST"])
@require_admin
def v2_admin_tasks_create():
    data = request.get_json() or {}
    row = db.v2_insert_task(data)
    return jsonify({"task": row}), 201


@v2_bp.route("/admin/tasks/<task_id>", methods=["PUT"])
@require_admin
def v2_admin_tasks_update(task_id):
    data = request.get_json() or {}
    row = db.v2_update_task(task_id, data)
    return jsonify({"task": row}), 200


# ---------- Admin CRUD: post-recording questions pool ----------
@v2_bp.route("/admin/post-recording-questions", methods=["GET"])
@require_admin
def v2_admin_post_questions_list():
    result = db.client.table("v2_post_recording_questions_pool").select("*").execute()
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
