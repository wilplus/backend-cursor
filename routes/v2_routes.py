"""
V2 flow: student endpoints + admin CRUD.
All /v2/* require auth; /v2/admin/* require admin.
"""
from flask import Blueprint, request, jsonify
from auth import require_auth
from routes.admin import require_admin
from services.db import db
from services.email_service import email_service
from services.v2_flow_service import compute_task_score, select_exercise_for_task_score
from services.question_service import calculate_cursor
from routes.session import run_v1_planning, _build_plan_response
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


# ---------- Student: universal answers -> exercise (if any) or v1 plan ----------
@v2_bp.route("/session/<session_id>/universal-answers", methods=["POST"])
@require_auth
def v2_universal_answers(session_id):
    """POST body: mood (0|1 or 0..1), readiness (1..10), mode_preference (0=guide me, 1=I'll choose).
    Computes task_score. If there is an active exercise for that score → return exercise (status=exercise).
    Else → create v1 session, run v1 planning, return v1 plan + task_score (status=pre_questions).
    Frontend: if exercise returned, show exercise div then POST exercise-feedback; then get v1 plan from exercise-feedback. Else use returned v1 plan for pre-answers, record, post-answers."""
    try:
        user_id = request.user_id
        data = request.get_json() or {}
        mood = data.get("mood")
        readiness = data.get("readiness", 5)
        mode_preference = data.get("mode_preference", 0)

        v2_session = db.v2_get_session(session_id, user_id)
        if not v2_session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        if v2_session.get("status") != "universal_questions":
            return jsonify({"code": "INVALID_STATE", "error": "Session already past universal questions"}), 400

        task_score = compute_task_score(mood, readiness, mode_preference)
        overrides = db.v2_get_student_overrides(user_id)
        exercises = db.v2_get_active_exercises()
        exercise = select_exercise_for_task_score(
            exercises,
            task_score,
            (overrides.get("assigned_next_exercise_id") if overrides else None),
        )

        # Store universal answers and task_score in all cases
        db.v2_update_session(session_id, user_id, {
            "universal_answers": {"mood": mood, "readiness": readiness, "mode_preference": mode_preference},
            "task_score": task_score,
            "mode_preference": mode_preference,
        })

        # If we have an exercise → return exercise only; frontend shows exercise div, then calls exercise-feedback
        if exercise:
            db.v2_update_session(session_id, user_id, {
                "selected_exercise_id": exercise["id"],
                "status": "exercise",
            })
            exercise_out = {
                "id": exercise["id"],
                "title": exercise.get("title"),
                "video_url": exercise.get("video_url"),
                "description": exercise.get("description"),
            }
            return jsonify({
                "task_score": task_score,
                "exercise": exercise_out,
                "status": "exercise",
            }), 200

        # No exercise → create v1 session and return v1 plan (same as before)
        mood_str = "positive" if (mood is not None and float(mood) >= 0.5) else "negative"
        readiness_int = max(1, min(10, int(readiness) if readiness is not None else 5))
        mode_str = "guided" if mode_preference == 0 else "open"
        cursor = calculate_cursor(mood_str, readiness_int)
        v1_session = db.create_session(
            user_id=user_id,
            cursor=cursor,
            mode=mode_str,
            mood=mood_str,
            readiness=readiness_int,
            inspiration_needed=False,
            pre_questions_completed=False,
            status="pre_questions_pending",
        )
        if not v1_session:
            return jsonify({"code": "V2_ERROR", "error": "Failed to create session"}), 500
        v1_session_id = str(v1_session["id"])
        db.client.table("recording_sessions").update({"structure": mode_str}).eq("id", v1_session_id).execute()
        session, pre_questions, command_options = run_v1_planning(v1_session_id, user_id, theme_code_override=None)
        if not session:
            return jsonify({"code": "V2_ERROR", "error": "Planning failed"}), 500
        db.v2_update_session(session_id, user_id, {
            "v1_session_id": v1_session_id,
            "status": "pre_questions",
        })
        return jsonify(_build_plan_response(v1_session_id, session, pre_questions, command_options, extra={"task_score": task_score})), 200
    except Exception as e:
        logger.error(f"V2 universal-answers error: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Student: exercise feedback -> v1 plan ----------
@v2_bp.route("/session/<session_id>/exercise-feedback", methods=["POST"])
@require_auth
def v2_exercise_feedback(session_id):
    """POST body: exercise_liked (bool). When status is 'exercise', creates v1 session from stored universal_answers, runs v1 planning, returns v1 plan so frontend continues to pre-questions → record → post-answers."""
    try:
        user_id = request.user_id
        data = request.get_json() or {}
        liked = data.get("exercise_liked")

        v2_session = db.v2_get_session(session_id, user_id)
        if not v2_session:
            return jsonify({"code": "SESSION_NOT_FOUND"}), 404
        if v2_session.get("status") != "exercise":
            return jsonify({"code": "INVALID_STATE", "error": "Not in exercise step"}), 400

        # Build v1 session from stored universal_answers
        ua = v2_session.get("universal_answers") or {}
        mood = ua.get("mood")
        readiness = ua.get("readiness", 5)
        mode_preference = v2_session.get("mode_preference", 0)
        mood_str = "positive" if (mood is not None and float(mood) >= 0.5) else "negative"
        readiness_int = max(1, min(10, int(readiness) if readiness is not None else 5))
        mode_str = "guided" if mode_preference == 0 else "open"
        cursor = calculate_cursor(mood_str, readiness_int)

        v1_session = db.create_session(
            user_id=user_id,
            cursor=cursor,
            mode=mode_str,
            mood=mood_str,
            readiness=readiness_int,
            inspiration_needed=False,
            pre_questions_completed=False,
            status="pre_questions_pending",
        )
        if not v1_session:
            return jsonify({"code": "V2_ERROR", "error": "Failed to create session"}), 500
        v1_session_id = str(v1_session["id"])
        db.client.table("recording_sessions").update({"structure": mode_str}).eq("id", v1_session_id).execute()
        session, pre_questions, command_options = run_v1_planning(v1_session_id, user_id, theme_code_override=None)
        if not session:
            return jsonify({"code": "V2_ERROR", "error": "Planning failed"}), 500

        db.v2_update_session(session_id, user_id, {
            "exercise_liked": liked,
            "v1_session_id": v1_session_id,
            "status": "pre_questions",
        })

        return jsonify(_build_plan_response(v1_session_id, session, pre_questions, command_options, extra={"task_score": v2_session.get("task_score")})), 200
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
    """List students with email (and optional stats). Required: user_id, email for UI."""
    try:
        limit = request.args.get("limit", default=20, type=int)
        offset = request.args.get("offset", default=0, type=int)
        user_ids = db.v2_list_users_with_sessions(limit=limit, offset=offset)
        students = []
        for uid in user_ids:
            email = db.get_user_email_from_auth(uid)
            row = {"user_id": uid, "email": email}
            stats = db.v2_get_student_list_stats(uid)
            if stats:
                row["sessions_count"] = stats.get("sessions_count")
                row["last_session_at"] = stats.get("last_session_at")
                row["avg_performance"] = stats.get("avg_performance")
            students.append(row)
        return jsonify({"students": students, "limit": limit, "offset": offset}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>", methods=["GET"])
@require_admin
def v2_admin_student_profile(user_id):
    """Student profile for admin panel: email, overrides, speaker_profile, sessions with recording/report previews."""
    try:
        email = db.get_user_email_from_auth(user_id)
        overrides = db.v2_get_student_overrides(user_id)
        speaker_profile = db.v2_get_speaker_profile(user_id)
        sessions = db.v2_get_sessions_with_previews(user_id, limit=50)
        return jsonify({
            "user_id": user_id,
            "email": email,
            "overrides": overrides,
            "speaker_profile": speaker_profile,
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
    """Set prompts, assigned post Qs (exactly 3), next exercise/task."""
    try:
        data = request.get_json() or {}
        ids = data.get("assigned_post_question_ids")
        if ids is not None and not isinstance(ids, list):
            return jsonify({"code": "INVALID_INPUT", "error": "assigned_post_question_ids must be an array"}), 400
        if ids is not None and len(ids) != 3:
            return jsonify({"code": "INVALID_INPUT", "error": "assigned_post_question_ids must have exactly 3 items"}), 400
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
