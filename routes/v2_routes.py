"""
V2: admin CRUD only. Student flow is homework only (routes/homework.py).
All /v2/admin/* require auth + admin.
"""
from flask import Blueprint, request, jsonify
from config import Config
from auth import require_auth
from routes.admin import require_admin, is_admin
from services.annotation_export import result_to_dict, run_annotation_export
from services.db import db
from services.email_service import email_service
from services.copilot_video_pipeline import (
    build_feedback_video_storage_path,
    build_script_manifest,
    fetch_override_video_bytes,
    generate_video_from_script,
    parse_bool,
    parse_reference_tags,
    resolve_script_mode,
)
from services.stress_snippet_service import (
    STRESS_SNIPPET_CLIP_SEC_DEFAULT,
    STRESS_SNIPPET_CLIP_SEC_MAX,
    STRESS_SNIPPET_CLIP_SEC_MIN,
    generate_stress_snippets_for_recording,
)
from services.charisma_snippet_service import (
    CHARISMA_SNIPPET_CLIP_SEC_DEFAULT,
    CHARISMA_SNIPPET_CLIP_SEC_MAX,
    CHARISMA_SNIPPET_CLIP_SEC_MIN,
    generate_charisma_snippets_for_recording,
)
from services.video_url_validation import validate_video_url
from services.tutor_video_url import parse_r2_uri, parse_storage_uri
from services.coach_video_storage import (
    coach_media_public_url,
    coach_videos_use_r2,
    guess_video_content_type,
    presigned_get_coach_object,
    presigned_put_coach_object,
    put_coach_object_bytes,
    get_coach_object_bytes,
    r2_bucket_name,
)
import logging
import sentry_sdk
import json
import time
import hashlib
import random
import mimetypes
import os
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from werkzeug.utils import secure_filename
from io import BytesIO
import threading

from services.reference_video_upload_worker import run_reference_video_upload

logger = logging.getLogger(__name__)
v2_bp = Blueprint("v2", __name__, url_prefix="/v2")
config = Config()

_STRESS_ALLOWED_SOURCE_TYPES = {"student", "internet"}
_STRESS_ALLOWED_LABELS = {"stress", "no_stress"}
_CHARISMA_ALLOWED_LABELS = {"charisma", "no_charisma"}
_TASK_TEMPLATE_ALLOWED_PROFILES = {
    "The Overwhelmed",
    "The Stressor",
    "The Drifter",
    "The Master",
}
_TASK_TEMPLATE_DEFAULT_PROFILE = "The Overwhelmed"
_TASK_TEMPLATE_DEFAULT_LEVEL = 1
_TASK_TEMPLATE_DEFAULT_STEP = 1
_COPILOT_DRAFT_EDITABLE_FIELDS = {
    "email_draft",
    "task_draft",
    "script_draft",
    "grade_draft",
    "comment_draft",
    "corrected_insight",
    "metadata",
    "video_url",
    "script_mode",
    "full_override_video_url",
    "full_override_video_storage_path",
    "reference_tags",
    "is_universal_video",
    "reference_transcript_text",
    "universal_blocks",
    "personalized_blocks",
    "coach_override_blocks",
}
_COPILOT_DRAFT_CONTROL_FIELDS = {
    "session_id",
    "draft_id",
    "reason_chip",
    "reason_chips",
    "reason_chip_custom",
    "video_script",  # legacy alias -> script_draft
}
_COPILOT_DRAFT_IMMUTABLE_FIELDS = {
    "ai_email_draft",
    "ai_task_suggestion",
    "ai_script_draft",
    "ai_grade_draft",
    "ai_comment_draft",
    "ai_insight",
    "ai_suggested_task_text",
    "ai_draft_message",
    "ai_draft_video_script",
}

_PIPELINE_RUNNING_STATES = {"queued", "running_tts", "running_video", "uploading"}
_REFERENCE_VIDEO_ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"}


def _normalize_upload_content_type(raw: str, fallback_filename: str) -> str:
    """
    Normalize client-provided content type for signed PUT:
    - strip parameters (e.g. '; codecs=...; charset=...')
    - lowercase + trim
    - fallback from filename when missing/invalid
    """
    base = ""
    if isinstance(raw, str):
        base = raw.split(";", 1)[0].strip().lower()
    if not base or "/" not in base:
        base = guess_video_content_type(fallback_filename).strip().lower()
    return base or "application/octet-stream"


def _resolve_reference_upload_user_id(form_user_id: str, fallback_admin_id: str):
    raw = (form_user_id or "").strip()
    if not raw:
        try:
            return str(uuid.UUID(str(fallback_admin_id).strip())), None
        except (ValueError, TypeError, AttributeError):
            return None, "user_id is required"
    try:
        return str(uuid.UUID(raw)), None
    except (ValueError, TypeError, AttributeError):
        pass
    if "@" in raw:
        uid = db.get_auth_user_id_by_email(raw)
        if uid:
            return uid, None
        return None, "No Supabase user found for that email"
    return None, "user_id must be a UUID or student email"


def _is_valid_uuid(val):
    import re
    return bool(re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', str(val or ''), re.I))


def _public_storage_url(bucket: str, path: str):
    supabase_url = (getattr(config, "SUPABASE_URL", "") or "").rstrip("/")
    if not supabase_url or not bucket or not path:
        return ""
    return f"{supabase_url}/storage/v1/object/public/{bucket}/{path}"


def _infer_stress_source_type(recording: dict) -> str:
    origin = (recording or {}).get("recording_origin")
    return "internet" if origin == "admin_import" else "student"


_IMPORT_ALLOWED_EXTENSIONS = {".mp3", ".wav", ".webm", ".m4a", ".ogg", ".flac"}
# `student` is sent by some Training Studio uploads (Student recordings tab); stored in source_metadata only.
_IMPORT_SOURCE_KINDS = {"upload", "youtube", "podcast", "external", "other", "student"}


def _admin_import_clean_text(val, max_len: int) -> str:
    if val is None:
        return ""
    if not isinstance(val, str):
        return ""
    return val.strip()[:max_len]


def _admin_import_validate_audio_file(file_storage):
    if file_storage is None or not (getattr(file_storage, "filename", "") or "").strip():
        raise ValueError("audio_file is required")
    original_name = secure_filename(file_storage.filename or "")
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in _IMPORT_ALLOWED_EXTENSIONS:
        raise ValueError("unsupported audio format")
    return original_name, ext


def _admin_import_storage_path(recording_id: str, original_filename: str) -> str:
    safe_name = secure_filename(original_filename or "") or "audio"
    ext = os.path.splitext(safe_name)[1].lower() or ".bin"
    now = datetime.now(timezone.utc)
    return f"admin_imports/{now:%Y/%m}/{recording_id}/{uuid.uuid4().hex}{ext}"


def _admin_import_source_metadata(
    *,
    source_kind: str,
    source_url,
    source_title,
    speaker_label,
    language_code,
    transcript_text,
    import_notes,
    reviewer_id: str,
):
    return {
        "recording_origin": "admin_import",
        "source_kind": source_kind,
        "source_url": source_url,
        "source_title": source_title,
        "speaker_label": speaker_label,
        "language_code": language_code,
        "transcript_text": transcript_text,
        "import_notes": import_notes,
        "imported_by": reviewer_id,
        "imported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _stress_snippet_payload(row: dict) -> dict:
    storage_path = (row.get("storage_path") or "").strip()
    audio_url = None
    if storage_path:
        try:
            audio_url = db.create_signed_url(config.AUDIO_BUCKET_NAME, storage_path, config.SIGNED_URL_EXPIRY_SECONDS)
        except Exception:
            audio_url = _public_storage_url(config.AUDIO_BUCKET_NAME, storage_path) or None
    payload = dict(row)
    try:
        sm = int(row.get("start_ms") or 0)
    except (TypeError, ValueError):
        sm = 0
    try:
        em = int(row.get("end_ms") or 0)
    except (TypeError, ValueError):
        em = 0
    try:
        dm = int(row.get("duration_ms") or 0)
    except (TypeError, ValueError):
        dm = 0
    if em <= sm and dm > 0:
        em = sm + dm
    start_sec = round(sm / 1000.0, 3)
    end_sec = round(em / 1000.0, 3)
    duration_sec = max(0.0, round((em - sm) / 1000.0, 3))
    if duration_sec <= 0 and dm > 0:
        duration_sec = round(dm / 1000.0, 3)
        end_sec = round(start_sec + duration_sec, 3)
    payload["start_sec"] = start_sec
    payload["end_sec"] = end_sec
    payload["duration_sec"] = duration_sec
    # Common client shapes (Training Studio / Next may expect camelCase).
    payload["startSec"] = start_sec
    payload["endSec"] = end_sec
    payload["durationSec"] = duration_sec
    payload["audio_url"] = audio_url
    payload["playable"] = bool(audio_url and storage_path)
    feats = row.get("features") if isinstance(row.get("features"), dict) else {}
    payload["queue_skipped"] = bool(feats.get("queue_skipped"))
    return payload


def _runtime_bool(key: str, default: bool) -> bool:
    raw = (db.get_runtime_config(key) or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_report_comment(value):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("report_comment must be a string or null")
    comment = value.strip()
    if not comment:
        return None
    if len(comment) > 2000:
        raise ValueError("report_comment must be at most 2000 characters")
    return comment


def _learning_profile_payload(row: dict | None) -> dict:
    """Expose AI vs coach learning-profile fields and what the UI should show by default."""
    row = row or {}
    ai_profile = (row.get("behavioral_profile") or "").strip() or None
    ai_justification = (row.get("behavioral_profile_justification") or "").strip() or None
    coach_profile = (row.get("coach_override_profile") or "").strip() or None
    coach_justification = (row.get("profile_override_justification") or "").strip() or None
    display_profile = coach_profile or ai_profile or "Unclassified"
    display_justification = coach_justification or ai_justification or ""
    return {
        "behavioral_profile": ai_profile,
        "behavioral_profile_justification": ai_justification,
        "coach_override_profile": coach_profile,
        "profile_override_justification": coach_justification,
        "display_profile": display_profile,
        "display_justification": display_justification,
    }


def _display_learning_profile_justification(profile_row: dict | None) -> str | None:
    row = profile_row or {}
    coach_j = (row.get("profile_override_justification") or "").strip()
    if coach_j:
        return coach_j
    ai_j = (row.get("behavioral_profile_justification") or "").strip()
    return ai_j or None


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
                details = db.v2_get_student_details(uid) or {}
                row = {
                    "user_id": uid,
                    "email": email,
                    "user_email": email,
                    "name": details.get("name") or item.get("name"),
                    "price_per_live_lesson": details.get("price_per_live_lesson"),
                }
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
                details = db.v2_get_student_details(uid) or {}
                row = {
                    "user_id": uid,
                    "email": email,
                    "user_email": email,
                    "name": details.get("name"),
                    "price_per_live_lesson": details.get("price_per_live_lesson"),
                }
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


@v2_bp.route("/admin/students/<user_id>", methods=["GET", "PATCH", "DELETE"])
@require_auth
def v2_admin_student_profile(user_id):
    """Student profile: admin can get any user's profile; authenticated user can get own profile (user_id === token sub).
    Same contract: user_id, email, overrides, speaker_profile, tasks[], sessions (reports list)."""
    try:
        if request.method == "DELETE":
            if not is_admin(request.user_id):
                return jsonify({"code": "FORBIDDEN", "error": "Admin access required"}), 403
            deleted = db.v2_delete_student(user_id)
            return jsonify({"status": "ok", "deleted": deleted}), 200

        if request.method == "PATCH":
            if not is_admin(request.user_id):
                return jsonify({"code": "FORBIDDEN", "error": "Admin access required"}), 403
            data = request.get_json(silent=True) or {}
            payload = {}
            if "name" in data:
                name_val = data.get("name")
                if name_val is None:
                    payload["name"] = None
                elif not isinstance(name_val, str):
                    return jsonify({"code": "INVALID_INPUT", "error": "name must be a string or null"}), 400
                else:
                    payload["name"] = name_val.strip() or None
            if "price_per_live_lesson" in data:
                price_val = data.get("price_per_live_lesson")
                if price_val is None or price_val == "":
                    payload["price_per_live_lesson"] = None
                else:
                    try:
                        p = float(price_val)
                    except (TypeError, ValueError):
                        return jsonify({"code": "INVALID_INPUT", "error": "price_per_live_lesson must be a number or null"}), 400
                    if p < 0:
                        return jsonify({"code": "INVALID_INPUT", "error": "price_per_live_lesson must be non-negative"}), 400
                    payload["price_per_live_lesson"] = round(p, 2)
            if "credits" in data:
                credits_val = data.get("credits")
                if credits_val is None or credits_val == "":
                    payload["credits"] = None
                else:
                    try:
                        c = int(credits_val)
                    except (TypeError, ValueError):
                        return jsonify({"code": "INVALID_INPUT", "error": "credits must be an integer or null"}), 400
                    if c < 0:
                        return jsonify({"code": "INVALID_INPUT", "error": "credits must be non-negative"}), 400
                    payload["credits"] = c
            if "is_archived" in data:
                payload["is_archived"] = bool(data.get("is_archived"))
            if not payload:
                return jsonify({"code": "INVALID_INPUT", "error": "No updatable fields provided"}), 400
            row = db.v2_upsert_student_details(user_id, payload)
            return jsonify({
                "status": "ok",
                "user_id": user_id,
                "name": row.get("name") if row else payload.get("name"),
                "price_per_live_lesson": row.get("price_per_live_lesson") if row else payload.get("price_per_live_lesson"),
                "credits": row.get("credits") if row else payload.get("credits"),
                "is_archived": row.get("is_archived") if row else payload.get("is_archived"),
            }), 200

        if not is_admin(request.user_id) and user_id != request.user_id:
            return jsonify({"code": "FORBIDDEN", "error": "You can only access your own profile"}), 403
        try:
            from services.student_profile_service import refresh_student_profile_state
            refresh_student_profile_state(user_id)
        except Exception:
            pass
        email = db.get_user_email_from_auth(user_id)
        details = db.v2_get_student_details(user_id) or {}
        raw_overrides = db.v2_get_student_overrides(user_id)
        overrides = dict(raw_overrides) if raw_overrides else {}
        # Ensure skip flags are always booleans for consistent admin UI (false when never set)
        overrides["skip_metric_questions"] = bool(raw_overrides.get("skip_metric_questions") if raw_overrides else False)
        speaker_profile = db.v2_get_speaker_profile(user_id)
        sniper_profile = db.get_sniper_profile_payload(user_id)
        learning_profile = _learning_profile_payload(sniper_profile)
        coaching_memory = db.v2_get_student_coaching_memory(user_id)
        tasks = db.v2_get_student_tasks(user_id)
        last_report = db.v2_get_last_report_for_user(user_id)
        sessions = db.v2_get_sessions_with_previews(user_id, limit=50)
        delivered_sessions = [s for s in sessions if s.get("report_delivered")]
        latest_assignment_row = _pick_student_draft(user_id, include_sent=True)
        latest_assignment = _serialize_copilot_draft(latest_assignment_row) if latest_assignment_row else None
        measured_metrics = db.v2_get_admin_measured_metrics_snapshot(user_id)
        similar_students = []
        try:
            if measured_metrics.get("wpm_high"):
                similar_students = db.get_similar_students_by_wpm(user_id)
        except Exception as sim_err:
            logger.warning("admin profile: similar_students_by_wpm failed: %s", sim_err)
        return jsonify({
            "user_id": user_id,
            "email": email,
            "name": details.get("name"),
            "price_per_live_lesson": details.get("price_per_live_lesson"),
            "credits": details.get("credits") if details.get("credits") is not None else 15,
            "overrides": overrides,
            "speaker_profile": speaker_profile,
            "sniper_profile": sniper_profile,
            "learning_profile": learning_profile,
            "coaching_memory": coaching_memory,
            "realtime_level": sniper_profile.get("realtime_level"),
            "realtime_step": sniper_profile.get("realtime_step"),
            "measured_metrics": measured_metrics,
            "tasks": tasks,
            "last_report": last_report.get("report_text") if last_report else None,
            "last_report_preview": last_report.get("report_preview") if last_report else None,
            "last_report_delivered": bool(last_report.get("report_delivered")) if last_report else False,
            "latest_assignment_draft": latest_assignment,
            "sessions": delivered_sessions,
            "similar_students_by_wpm": similar_students,
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
    """Coerce a value to bool for skip_metric_questions. Returns (bool, None) or (None, error_msg)."""
    if value is True or value is False:
        return (value, None)
    if value in ("true", "1", 1):
        return (True, None)
    if value in ("false", "0", "", 0, None):
        return (False, None)
    return (None, f"{key} must be a boolean (true/false)")


def _coerce_optional_positive_int(value, key: str, *, maximum: int | None = None):
    """Coerce optional int input for admin overrides. Returns (int|None, None) or (None, error_msg)."""
    if value in (None, ""):
        return (None, None)
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return (None, f"{key} must be an integer")
    if ivalue < 1:
        return (None, f"{key} must be at least 1")
    if maximum is not None and ivalue > maximum:
        return (None, f"{key} must be at most {maximum}")
    return (ivalue, None)


@v2_bp.route("/admin/students/<user_id>/sniper-profile", methods=["GET", "PUT"])
@require_admin
def v2_admin_student_sniper_profile(user_id):
    """Update the student's currently unlocked realtime progression."""
    try:
        if request.method == "GET":
            sniper_profile = db.get_sniper_profile_payload(user_id)
            return jsonify({
                "status": "ok",
                "sniper_profile": sniper_profile,
                "realtime_level": sniper_profile.get("realtime_level"),
                "realtime_step": sniper_profile.get("realtime_step"),
            }), 200

        data = request.get_json(silent=True) or {}
        if "realtimeLevel" in data and "realtime_level" not in data:
            data["realtime_level"] = data.pop("realtimeLevel")
        if "realtimeStep" in data and "realtime_step" not in data:
            data["realtime_step"] = data.pop("realtimeStep")
        if "current_realtime_level" in data and "realtime_level" not in data:
            data["realtime_level"] = data.pop("current_realtime_level")
        if "current_realtime_step" in data and "realtime_step" not in data:
            data["realtime_step"] = data.pop("current_realtime_step")

        if "realtime_level" not in data and "realtime_step" not in data:
            return jsonify({"code": "INVALID_INPUT", "error": "realtime_level or realtime_step is required"}), 400

        realtime_level = None
        realtime_step = None
        if "realtime_level" in data:
            realtime_level, err = _coerce_optional_positive_int(data.get("realtime_level"), "realtime_level")
            if err:
                return jsonify({"code": "INVALID_INPUT", "error": err}), 400
        if "realtime_step" in data:
            realtime_step, err = _coerce_optional_positive_int(data.get("realtime_step"), "realtime_step", maximum=10)
            if err:
                return jsonify({"code": "INVALID_INPUT", "error": err}), 400

        sniper_profile = db.set_sniper_realtime_progression(
            user_id,
            realtime_level=realtime_level,
            realtime_step=realtime_step,
        )
        return jsonify({
            "status": "ok",
            "sniper_profile": sniper_profile,
            "realtime_level": sniper_profile.get("realtime_level"),
            "realtime_step": sniper_profile.get("realtime_step"),
        }), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/overrides", methods=["PUT"])
@require_admin
def v2_admin_student_overrides(user_id):
    """Set prompts, skip_metric_questions, assigned_task_id, pending tutor video fields."""
    try:
        data = request.get_json() or {}
        # Normalize camelCase from frontend to snake_case
        if "skipMetricQuestions" in data and "skip_metric_questions" not in data:
            data["skip_metric_questions"] = data.pop("skipMetricQuestions", None)
        for key in ("skip_metric_questions",):
            if key in data:
                val, err = _coerce_override_bool(data[key], key)
                if err:
                    return jsonify({"code": "INVALID_INPUT", "error": err}), 400
                data[key] = val
        db.v2_upsert_student_overrides(user_id, data)
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error("PUT overrides error for user_id=%s: %s", user_id, e)
        return jsonify({"code": "V2_ERROR", "error": "Internal server error"}), 500


def _deliver_homework_assignment_core(
    user_id: str,
    student_email: str,
    *,
    video_url: str | None,
    video_description: str | None,
    video_bucket: str | None = None,
    video_storage_path: str | None = None,
):
    """Shared path for student homework unlock: pending tutor media + email + tutor_feedback_sent.

    Matches POST /admin/students/<id>/send-assignment delivery semantics (not the draft provenance insert).
    Returns (success_payload, None) or (None, error_string) on email failure.
    """
    vb = (video_bucket or "").strip() or None
    sp = (video_storage_path or "").strip().lstrip("/") or None
    vu = (video_url or "").strip() if video_url else None

    # Fallback B: if the caller didn't pass any video reference, use the most
    # recent admin-uploaded reference video for this student (Training Studio
    # upload). Without this the student's step-0 screen shows "No video" even
    # when the coach just uploaded one, because the draft row never had the
    # storage path attached.
    if not vu and not (vb and sp):
        try:
            ref = db.get_latest_admin_uploaded_reference_video_for_user(user_id)
        except Exception as ref_err:
            logger.warning("deliver: reference-video fallback lookup failed user_id=%s: %s", user_id, ref_err)
            ref = None
        if not ref:
            logger.warning(
                "deliver: no reference video found for user_id=%s — student will see 'No video'. "
                "Likely the admin_uploaded_reference_videos insert failed (check PGRST204 retry logs).",
                user_id,
            )
        if ref:
            ref_fm = ref.get("feature_metadata") or {}
            ref_fm = ref_fm if isinstance(ref_fm, dict) else {}
            # Prefer the stable public URL (R2 CDN URL written by the upload
            # worker) when present — no presigning needed, plays directly.
            ref_src_url = (ref.get("source_video_url") or "").strip() or None
            if ref_src_url and (ref_src_url.startswith("http://") or ref_src_url.startswith("https://")):
                vu = ref_src_url
                logger.info(
                    "deliver: falling back to reference_video.source_video_url id=%s url=%s for user_id=%s",
                    ref.get("id"), ref_src_url[:80], user_id,
                )
            else:
                ref_storage_path = (ref.get("storage_path") or "").strip().lstrip("/") or None
                ref_bucket = (
                    (ref.get("bucket") or "").strip()
                    or (ref_fm.get("bucket") or "").strip()
                    or config.COACH_FEEDBACK_VIDEO_BUCKET
                )
                if ref_storage_path:
                    sp = ref_storage_path
                    vb = ref_bucket or None
                    logger.info(
                        "deliver: falling back to reference_video storage_path id=%s bucket=%s for user_id=%s",
                        ref.get("id"), ref_bucket, user_id,
                    )

    email_link = vu
    pending_uri: str | None = None
    if vb and sp:
        pending_uri = f"storage://{vb}/{sp}"
        if not email_link:
            try:
                email_link = presigned_get_coach_object(vb, sp, 48 * 3600, supabase_db=db)
            except Exception:
                email_link = None
    elif vu and vu.startswith("storage://"):
        pending_uri = vu
        parsed = parse_storage_uri(vu)
        if parsed and not email_link:
            try:
                email_link = presigned_get_coach_object(parsed[0], parsed[1], 48 * 3600, supabase_db=db)
            except Exception:
                email_link = None
    elif vu and vu.startswith("r2://"):
        pending_uri = vu
        parsed = parse_r2_uri(vu)
        if parsed and not email_link:
            try:
                email_link = presigned_get_coach_object(parsed[0], parsed[1], 48 * 3600, supabase_db=db)
            except Exception:
                email_link = None
    else:
        pending_uri = vu

    if pending_uri is not None or video_description is not None or (vb and sp):
        db.v2_set_pending_tutor_video(
            user_id,
            video_url=pending_uri,
            video_description=video_description,
            video_bucket=vb,
            video_storage_path=sp,
        )

    # Fix A: send the email off the request path. The admin UI only needs the
    # 202 to flip "Sending…" → "Sent"; SMTP can take 3–10s which blocks the
    # approve-send request unnecessarily. We unlock the student optimistically
    # (same semantics as HOMEWORK_UNLOCK_WHEN_EMAIL_FAILS=true) and log+Sentry
    # on background failure.
    # Default: synchronous. Resend API call takes ~0.5–2s which is fine for an
    # admin action done a few times per day, and the admin gets an honest
    # "sent" status (email was actually accepted by Resend, not just queued).
    # Set HOMEWORK_SEND_EMAIL_ASYNC=true to restore background-thread behavior.
    send_email_async = str(getattr(config, "HOMEWORK_SEND_EMAIL_ASYNC", "false")).strip().lower() in ("1", "true", "yes")

    def _send_email_sync():
        return email_service.send_assignment_to_student(
            to_email=student_email.strip(),
            frontend_url=config.FRONTEND_URL,
            video_url=email_link,
            video_description=video_description,
            student_name=student_email.strip(),
        )

    if send_email_async:
        db.v2_mark_tutor_feedback_sent_for_user(user_id)
        sniper_profile = db.get_sniper_profile_payload(user_id)

        def _bg_email():
            try:
                r = _send_email_sync()
                if (r or {}).get("status") == "failed":
                    err = r.get("error")
                    logger.error("deliver (async email): send failed user_id=%s err=%s", user_id, err)
                    sentry_sdk.capture_message(f"assignment email failed (async) user_id={user_id}: {err}")
            except Exception as e:
                logger.error("deliver (async email): unexpected error user_id=%s: %s", user_id, e)
                sentry_sdk.capture_exception(e)

        try:
            import threading
            threading.Thread(target=_bg_email, daemon=True, name=f"send-assignment-{user_id[:8]}").start()
        except Exception as th_err:
            logger.warning("deliver: could not spawn email thread, sending inline: %s", th_err)
            r = _send_email_sync()
            return {"email": r, "sniper_profile": sniper_profile, "email_failed_but_unlocked": (r or {}).get("status") == "failed"}, None
        return {
            # Optimistic "sent" so the admin UI flips to Sent immediately.
            # Real delivery happens in the daemon thread; failures are logged +
            # Sentry-reported. If you need strict semantics, set
            # HOMEWORK_SEND_EMAIL_ASYNC=false.
            "email": {"status": "sent", "sent": True, "async": True},
            "sniper_profile": sniper_profile,
            "email_failed_but_unlocked": False,
        }, None

    # Legacy synchronous path (HOMEWORK_SEND_EMAIL_ASYNC=false)
    result = _send_email_sync()
    if result.get("status") == "failed":
        if getattr(config, "HOMEWORK_UNLOCK_WHEN_EMAIL_FAILS", False):
            logger.warning(
                "homework delivery: email failed but unlock applied (HOMEWORK_UNLOCK_WHEN_EMAIL_FAILS=true) user_id=%s err=%s",
                user_id,
                result.get("error"),
            )
            db.v2_mark_tutor_feedback_sent_for_user(user_id)
            sniper_profile = db.get_sniper_profile_payload(user_id)
            return {
                "email": result,
                "sniper_profile": sniper_profile,
                "email_failed_but_unlocked": True,
                "email_error": result.get("error"),
            }, None
        return None, result.get("error", "Failed to send email")
    db.v2_mark_tutor_feedback_sent_for_user(user_id)
    sniper_profile = db.get_sniper_profile_payload(user_id)
    return {"email": result, "sniper_profile": sniper_profile, "email_failed_but_unlocked": False}, None


@v2_bp.route("/admin/students/<user_id>/send-assignment", methods=["POST"])
@require_admin
def v2_admin_send_assignment(user_id):
    """Send homework email to the student. Body optional: video_url (https, storage://, r2://), video_bucket + video_storage_path, video_description. Requires student email in Supabase Auth."""
    try:
        from config import Config
        config = Config()
        body = request.get_json(silent=True) or {}
        raw_vu = body.get("video_url")
        video_url = None
        if raw_vu is not None:
            s = str(raw_vu).strip()
            if s.startswith("storage://"):
                video_url = s if parse_storage_uri(s) else None
            elif s.startswith("r2://"):
                video_url = s if parse_r2_uri(s) else None
            else:
                video_url = validate_video_url(raw_vu)
        video_bucket = (body.get("video_bucket") or "").strip() or None
        video_storage_path = (body.get("video_storage_path") or "").strip().lstrip("/") or None
        if raw_vu is not None and video_url is None and not (video_bucket and video_storage_path):
            return jsonify(
                {
                    "code": "INVALID_VIDEO_URL",
                    "error": "video_url must be https URL, storage://bucket/path, r2://bucket/key, or pass video_bucket + video_storage_path",
                }
            ), 400
        video_description = (body.get("video_description") or "").strip() if body.get("video_description") is not None else None
        if video_description is not None and len(video_description) > 2000:
            return jsonify({"code": "INVALID_VIDEO_DESCRIPTION", "error": "video_description must be at most 2000 characters"}), 400
        additional_user_ids = body.get("additional_user_ids") or []
        if not isinstance(additional_user_ids, list):
            additional_user_ids = []
        # Deduplicate and exclude the primary user
        additional_user_ids = [uid for uid in additional_user_ids if isinstance(uid, str) and uid != user_id]

        student_email = db.get_user_email_from_auth(user_id)
        if not student_email or not student_email.strip():
            return jsonify({"code": "NO_EMAIL", "error": "Student has no email in auth"}), 400
        ai_prefill = _generate_assignment_prefill_for_user(user_id, fallback_task_text="")
        ai_message = (ai_prefill.get("ai_draft_message") or "").strip() or None
        ai_task = (ai_prefill.get("ai_suggested_task_text") or "").strip() or None
        ai_script = (ai_prefill.get("ai_draft_video_script") or "").strip() or None
        final_video_description = video_description if video_description is not None else ai_message
        delivery, send_err = _deliver_homework_assignment_core(
            user_id,
            student_email.strip(),
            video_url=video_url,
            video_description=final_video_description,
            video_bucket=video_bucket,
            video_storage_path=video_storage_path,
        )
        if send_err:
            err_lower = (send_err or "").lower()
            if "resend api key" in err_lower or "api key not set" in err_lower:
                return jsonify(
                    {
                        "code": "EMAIL_NOT_CONFIGURED",
                        "error": send_err,
                        "hint": "Set RESEND_API_KEY and RESEND_FROM_EMAIL with SEND_EMAILS=true, or use SEND_EMAILS=false to unlock without sending email. For staging, HOMEWORK_UNLOCK_WHEN_EMAIL_FAILS=true still unlocks if email fails.",
                    }
                ), 503
            return jsonify({"code": "EMAIL_FAILED", "error": send_err}), 500
        result = delivery["email"]
        sniper_profile = delivery["sniper_profile"]
        try:
            db.v2_apply_coach_homework_task_text(user_id, ai_task)
        except Exception as task_sync_err:
            logger.warning("send-assignment: task sync failed for %s: %s", user_id, task_sync_err)
        try:
            last_completed = db.v2_get_last_completed_session(user_id) or {}
            sent_row = {
                "user_id": user_id,
                "session_id": last_completed.get("id"),
                "cohort_profile": (db.get_sniper_profile(user_id) or {}).get("behavioral_profile") or "Unclassified",
                "cohort_stage": int((db.get_sniper_profile(user_id) or {}).get("computed_stage") or 1),
                "master_task_text": (ai_task or "Homework follow-up from coach")[:8000],
                "ai_suggested_task_text": ai_task,
                "ai_draft_message": ai_message,
                "ai_draft_video_script": ai_script,
                "draft_payload": {
                    "ai_task_suggestion": ai_task,
                    "ai_email_draft": ai_message,
                    "ai_script_draft": ai_script,
                    "task_draft": ai_task,
                    "email_draft": final_video_description,
                    "script_draft": ai_script,
                    "task_text": ai_task,
                    "email_message": final_video_description,
                    "video_script": ai_script,
                    "state": "Sent",
                },
                "status": "sent",
                "approved_by": request.user_id,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                db.insert_admin_student_send_drafts([sent_row])
            except Exception:
                # Backward-compatible insert if ai_* columns are not migrated yet.
                sent_row.pop("ai_suggested_task_text", None)
                sent_row.pop("ai_draft_message", None)
                sent_row.pop("ai_draft_video_script", None)
                db.insert_admin_student_send_drafts([sent_row])
            if ai_message and final_video_description and ai_message.strip() != final_video_description.strip():
                db.create_admin_annotation_event(
                    user_id=user_id,
                    session_id=last_completed.get("id"),
                    section_type="assignment",
                    field_name="email_message",
                    ai_original_text=ai_message,
                    coach_final_text=final_video_description,
                    reason_chip="manual_edit",
                    custom_reason=None,
                    created_by=request.user_id,
                )
        except Exception as prefill_err:
            logger.warning("send-assignment: draft provenance save failed for %s: %s", user_id, prefill_err)

        # Send to additional (similar) students
        additional_results = []
        for extra_uid in additional_user_ids:
            try:
                extra_email = db.get_user_email_from_auth(extra_uid)
                if not extra_email or not extra_email.strip():
                    additional_results.append({"user_id": extra_uid, "status": "skipped", "reason": "no_email"})
                    continue
                extra_delivery, extra_err = _deliver_homework_assignment_core(
                    extra_uid,
                    extra_email.strip(),
                    video_url=video_url,
                    video_description=final_video_description,
                    video_bucket=video_bucket,
                    video_storage_path=video_storage_path,
                )
                if extra_err:
                    additional_results.append({"user_id": extra_uid, "status": "failed", "reason": extra_err})
                else:
                    try:
                        db.v2_apply_coach_homework_task_text(extra_uid, ai_task)
                    except Exception as extra_task_err:
                        logger.warning("send-assignment: task sync failed for %s: %s", extra_uid, extra_task_err)
                    er = extra_delivery["email"]
                    additional_results.append(
                        {"user_id": extra_uid, "status": er.get("status", "unknown"), "email": extra_email.strip()}
                    )
            except Exception as extra_err:
                logger.warning("send-assignment: additional user %s failed: %s", extra_uid, extra_err)
                additional_results.append({"user_id": extra_uid, "status": "failed", "reason": str(extra_err)})

        return jsonify({
            "status": "ok",
            "message": "Assignment sent",
            "sent": result.get("sent", False),
            "email_status": result.get("status"),
            "email_failed_but_unlocked": bool(delivery.get("email_failed_but_unlocked")),
            "homework_message": final_video_description,
            "task_suggestion": ai_task,
            "video_script": ai_script,
            "ai_draft_message": ai_message,
            "ai_suggested_task_text": ai_task,
            "ai_draft_video_script": ai_script,
            "sniper_profile": sniper_profile,
            "realtime_level": sniper_profile.get("realtime_level"),
            "realtime_step": sniper_profile.get("realtime_step"),
            "additional_sends": additional_results if additional_user_ids else None,
        }), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/send-completion-email", methods=["POST"])
@require_admin
def v2_admin_send_completion_email(user_id):
    """Manually send the student completion email and return detailed delivery result."""
    try:
        from config import Config
        config = Config()
        student_email = (db.get_user_email_from_auth(user_id) or "").strip()
        if not student_email:
            return jsonify({"code": "NO_EMAIL", "error": "Student has no email in auth"}), 400
        last_completed = db.v2_get_last_completed_session(user_id) or {}
        perf_end = last_completed.get("score")
        last_report = db.v2_get_last_report_for_user(user_id) or {}
        report_preview = (last_report.get("report_preview") or last_report.get("report_text") or "")
        result = email_service.send_lesson_complete_to_student(
            to_email=student_email,
            frontend_url=config.FRONTEND_URL,
            score=perf_end,
            report_preview=report_preview,
            student_name=student_email.split("@")[0] if "@" in student_email else "there",
        )
        if result.get("status") != "sent":
            return jsonify({
                "code": "EMAIL_FAILED",
                "error": result.get("error", "Failed to send completion email"),
                "details": result,
                "student_email": student_email,
            }), 500
        return jsonify({
            "status": "ok",
            "sent": True,
            "student_email": student_email,
            "details": result,
        }), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/sessions/<session_id>", methods=["GET", "PATCH"])
@require_admin
def v2_admin_student_session_detail(user_id, session_id):
    """GET: full session for admin. PATCH: update report_grade/report_comment."""
    try:
        if request.method == "GET":
            session = db.v2_get_session(session_id, user_id)
            if not session:
                return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
            return jsonify({"session": session}), 200
        # PATCH: report_grade / report_comment / coach_override_score
        data = request.get_json() or {}
        current = db.v2_get_session(session_id, user_id)
        if not current:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        updates = {}
        # Accept coach_grade (admin client alias) or report_grade (legacy)
        raw_grade = data.get("coach_grade") if "coach_grade" in data else data.get("report_grade")
        if raw_grade is not None:
            try:
                g = int(raw_grade)
                if g < 1 or g > 10:
                    return jsonify({"code": "INVALID_INPUT", "error": "report_grade must be between 1 and 10"}), 400
            except (TypeError, ValueError):
                return jsonify({"code": "INVALID_INPUT", "error": "report_grade must be an integer 1-10"}), 400
            updates["report_grade"] = g
        elif "coach_grade" in data or "report_grade" in data:
            # Explicit null → clear grade
            updates["report_grade"] = None
        # Accept both field names: coach_message (admin client) and report_comment (legacy)
        raw_comment = data.get("coach_message") if "coach_message" in data else data.get("report_comment")
        if "report_comment" in data or "coach_message" in data:
            try:
                updates["report_comment"] = _parse_report_comment(raw_comment)
            except ValueError as ve:
                return jsonify({"code": "INVALID_INPUT", "error": str(ve)}), 400
        # coach_override_score: 0-100 integer (RLHF pipeline — overrides AI shadow score)
        if "coach_override_score" in data:
            raw_cos = data.get("coach_override_score")
            if raw_cos is None:
                updates["coach_override_score"] = None
            else:
                try:
                    cos = int(raw_cos)
                    if cos < 0 or cos > 100:
                        return jsonify({"code": "INVALID_INPUT", "error": "coach_override_score must be 0-100"}), 400
                except (TypeError, ValueError):
                    return jsonify({"code": "INVALID_INPUT", "error": "coach_override_score must be an integer 0-100"}), 400
                updates["coach_override_score"] = cos
        # coach_override_justification: why the coach overrode the AI (DPO training signal)
        if "coach_override_justification" in data:
            raw_coj = data.get("coach_override_justification")
            updates["coach_override_justification"] = (str(raw_coj).strip()[:2000] if raw_coj else None)
        if not updates:
            return jsonify({"code": "INVALID_INPUT", "error": "Provide report_grade, report_comment, coach_override_score, and/or coach_override_justification"}), 400
        updated = db.v2_update_session(session_id, user_id, updates)
        if not updated:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        try:
            if "coach_override_score" in updates:
                db.create_admin_annotation_event(
                    user_id=user_id,
                    session_id=session_id,
                    section_type="scoring",
                    field_name="coach_override_score",
                    ai_original_text=str(current.get("ai_task_score")) if current.get("ai_task_score") is not None else None,
                    coach_final_text=str(updates.get("coach_override_score")) if updates.get("coach_override_score") is not None else None,
                    reason_chip=(data.get("reason_chip") or "manual_override"),
                    custom_reason=updates.get("coach_override_justification"),
                    created_by=request.user_id,
                )
            if "report_grade" in updates:
                db.create_admin_annotation_event(
                    user_id=user_id,
                    session_id=session_id,
                    section_type="report",
                    field_name="report_grade",
                    ai_original_text=str(current.get("ai_draft_grade")) if current.get("ai_draft_grade") is not None else None,
                    coach_final_text=str(updates.get("report_grade")) if updates.get("report_grade") is not None else None,
                    reason_chip=(data.get("reason_chip") or "manual_grade"),
                    custom_reason=None,
                    created_by=request.user_id,
                )
            if "report_comment" in updates:
                db.create_admin_annotation_event(
                    user_id=user_id,
                    session_id=session_id,
                    section_type="report",
                    field_name="report_comment",
                    ai_original_text=(current.get("ai_draft_comment") or "").strip() or None,
                    coach_final_text=(updates.get("report_comment") or "").strip() or None,
                    reason_chip=(data.get("reason_chip") or "manual_comment"),
                    custom_reason=None,
                    created_by=request.user_id,
                )
        except Exception as ann_err:
            logger.warning("session patch annotation event failed: %s", ann_err)
        return jsonify({
            "status": "ok",
            "report_grade": updated.get("report_grade"),
            "report_comment": updated.get("report_comment"),
            "coach_override_score": updated.get("coach_override_score"),
            "coach_override_justification": updated.get("coach_override_justification"),
        }), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/sessions/<session_id>/grade", methods=["PUT"])
@require_admin
def v2_admin_student_session_grade(user_id, session_id):
    """Set admin/coach grade for a session. Body: { \"report_grade\": number, \"report_comment\"?: string|null }."""
    try:
        data = request.get_json(silent=True) or {}
        admin_grade = data.get("report_grade")
        if admin_grade is None:
            return jsonify({"code": "INVALID_INPUT", "error": "report_grade is required"}), 400
        try:
            g = int(round(float(admin_grade)))
            if g < 1 or g > 10:
                return jsonify({"code": "INVALID_INPUT", "error": "report_grade must be between 1 and 10"}), 400
        except (TypeError, ValueError):
            return jsonify({"code": "INVALID_INPUT", "error": "report_grade must be a number 1-10"}), 400
        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        try:
            report_comment = _parse_report_comment(data.get("report_comment")) if "report_comment" in data else session.get("report_comment")
        except ValueError as ve:
            return jsonify({"code": "INVALID_INPUT", "error": str(ve)}), 400
        updated = db.v2_update_session(session_id, user_id, {
            "report_grade": g,
            "report_comment": report_comment,
        })
        if not updated:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        try:
            db.create_admin_annotation_event(
                user_id=user_id,
                session_id=session_id,
                section_type="report",
                field_name="report_grade",
                ai_original_text=str(session.get("ai_draft_grade")) if session.get("ai_draft_grade") is not None else None,
                coach_final_text=str(g),
                reason_chip=(data.get("reason_chip") or "manual_grade"),
                custom_reason=None,
                created_by=request.user_id,
            )
            if "report_comment" in data:
                db.create_admin_annotation_event(
                    user_id=user_id,
                    session_id=session_id,
                    section_type="report",
                    field_name="report_comment",
                    ai_original_text=(session.get("ai_draft_comment") or "").strip() or None,
                    coach_final_text=(report_comment or "").strip() or None,
                    reason_chip=(data.get("reason_chip") or "manual_comment"),
                    custom_reason=None,
                    created_by=request.user_id,
                )
        except Exception as ann_err:
            logger.warning("session grade annotation event failed: %s", ann_err)
        return jsonify({
            "status": "ok",
            "report_grade": g,
            "report_comment": updated.get("report_comment"),
        }), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/sessions/<session_id>/report", methods=["GET", "POST"])
@require_admin
def v2_admin_student_session_report_get(user_id, session_id):
    """Get report for a completed session. Same payload as student GET report: report_text, scores, final_recording (recording_1), recording (transcript, fillers, wpm), context_short, coach_insight, performance_history, score_for_display. Supports GET and POST."""
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
            }), 409

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
        # Legacy rows (pre-migration) or edge cases: student route stays strict; admin must not 409 forever.
        if score_for_display_100 is None:
            try:
                s01 = float(session.get("score") or 0)
                if s01 > 1:
                    score_for_display_100 = max(0, min(100, int(round(s01))))
                else:
                    score_for_display_100 = max(0, min(100, int(round(s01 * 100))))
            except (TypeError, ValueError):
                score_for_display_100 = None
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

        # Same as student report: recording_1 (for recording-1-only flow)
        display_recording_id = session.get("recording_1_id")
        final_recording = {"id": None, "audio_url": None}
        recording_payload = None
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
                        logger.warning("Admin report: could not create signed URL for recording %s: %s", display_recording_id, e)
                if audio_url is not None and not isinstance(audio_url, str):
                    audio_url = str(audio_url) if audio_url else None
                final_recording["id"] = str(display_recording_id) if display_recording_id is not None else None
                final_recording["audio_url"] = audio_url
                filler_data = rec.get("filler_words_count") or {}
                if not isinstance(filler_data, dict):
                    filler_data = {}
                tt = (rec.get("transcription_text") or "").strip()
                _rec_wpm = rec.get("words_per_minute")
                recording_payload = {
                    "id": str(display_recording_id) if display_recording_id is not None else None,
                    "audio_url": audio_url if (audio_url is None or isinstance(audio_url, str)) else str(audio_url),
                    "transcription_text": tt,
                    "transcript": tt,
                    "filler_words_count": {
                        "total": int(filler_data.get("total", 0) or 0),
                        "breakdown": dict(filler_data.get("breakdown") or {}),
                    },
                    "words_per_minute": round(float(_rec_wpm), 1) if _rec_wpm is not None else None,
                }

        has_context = bool((session.get("context_short") or "").strip())
        has_transcript = bool(
            recording_payload and (recording_payload.get("transcription_text") or "").strip()
        )
        if not has_context or not recording_payload or not has_transcript:
            # Student GET report blocks until ready; admin polling must terminate for completed sessions.
            if not report_text:
                return jsonify({
                    "code": "REPORT_NOT_READY",
                    "error": "Transcript and context are still processing.",
                    "status": session.get("status"),
                }), 409

        sniper_profile = db.get_sniper_profile_payload(user_id)
        sniper_metrics = None
        if session_sniper:

            def _safe_float_adm(v, decimals=1):
                if v is None:
                    return None
                try:
                    return round(float(v), decimals)
                except (TypeError, ValueError):
                    return None

            _sr_adm = session_sniper.get("student_rating_1_10")
            try:
                student_rating_adm = int(_sr_adm) if _sr_adm is not None else None
            except (TypeError, ValueError):
                student_rating_adm = None
            sniper_metrics = {
                "wpm": _safe_float_adm(session_sniper.get("wpm")),
                "pause_ms": _safe_float_adm(session_sniper.get("pause_ms"), 0),
                "dynamic_db": _safe_float_adm(session_sniper.get("dynamic_db")),
                "emphasis_per_min": _safe_float_adm(session_sniper.get("emphasis_per_min")),
                "energy_ratio": _safe_float_adm(session_sniper.get("energy_ratio"), 2),
                "pitch_center_st": _safe_float_adm(session_sniper.get("pitch_center_st")),
                "pitch_frame_count": int(session_sniper["pitch_frame_count"]) if session_sniper.get("pitch_frame_count") is not None else None,
                "stage_score": _safe_float_adm(session_sniper.get("stage_score")),
                "voiced_duration_sec": _safe_float_adm(session_sniper.get("voiced_duration_sec")),
                "student_rating_1_10": student_rating_adm,
            }
            if sniper_metrics["wpm"] is None and recording_payload and recording_payload.get("words_per_minute") is not None:
                sniper_metrics["wpm"] = round(float(recording_payload["words_per_minute"]), 1)
        elif recording_payload and recording_payload.get("words_per_minute") is not None:
            # Homework-only path: no session_sniper_metrics row; UIs often read sniper_metrics.wpm only.
            sniper_metrics = {"wpm": round(float(recording_payload["words_per_minute"]), 1)}
            try:
                smx = db.get_session_sniper_metrics(session_id)
                if smx and smx.get("student_rating_1_10") is not None:
                    sniper_metrics["student_rating_1_10"] = int(smx["student_rating_1_10"])
            except Exception:
                pass

        payload = {
            "report_text": report_text,
            # Backward-compat alias: some admin UIs still read scores.overall.
            "scores": {"overall": score_for_display_100},
            "score": perf_end,
            "performance_score_end": perf_end,
            "recording_count": 1,
            "final_recording": final_recording,
            "performance_history": performance_history,
            "score_for_display": score_for_display_100,
            "report_grade": session.get("report_grade"),
            "report_comment": (session.get("report_comment") or "").strip() or None,
            "sniper_profile": sniper_profile,
            "realtime_level": sniper_profile.get("realtime_level"),
            "realtime_step": sniper_profile.get("realtime_step"),
        }
        if sniper_metrics is not None:
            payload["sniper_metrics"] = sniper_metrics
        if recording_payload is not None and recording_payload.get("words_per_minute") is not None:
            payload["words_per_minute"] = recording_payload["words_per_minute"]
        if recording_payload is not None:
            payload["recording"] = recording_payload
            _tt = recording_payload.get("transcription_text") or recording_payload.get("transcript") or ""
            payload["transcription_text"] = _tt
            payload["transcript"] = _tt
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


@v2_bp.route("/admin/recordings/import", methods=["POST"])
@require_admin
def v2_admin_recordings_import():
    """Multipart admin upload for Voice Pipeline (internet source_type stress snippets).

    Must stay **above** ``/admin/recordings/<recording_id>`` so ``import`` is not captured as an id
    (otherwise POST hits the GET-only detail route →405).
    """
    try:
        if "audio_file" not in request.files:
            return jsonify({"code": "AUDIO_FILE_REQUIRED", "error": "audio_file is required"}), 400
        audio_file = request.files.get("audio_file")
        try:
            original_name, _ext = _admin_import_validate_audio_file(audio_file)
        except ValueError as ve:
            msg = str(ve)
            if msg == "unsupported audio format":
                return jsonify({"code": "UNSUPPORTED_AUDIO_FORMAT", "error": "unsupported audio format"}), 415
            return jsonify({"code": "AUDIO_FILE_REQUIRED", "error": msg}), 400

        max_bytes = int((getattr(config, "MAX_AUDIO_SIZE_MB", 25) or 25) * 1024 * 1024)
        cl = request.content_length or 0
        if cl and cl > max_bytes:
            return jsonify({"code": "FILE_TOO_LARGE", "error": f"audio_file exceeds {config.MAX_AUDIO_SIZE_MB}MB limit"}), 413

        file_bytes = audio_file.read()
        if not file_bytes:
            return jsonify({"code": "INVALID_MULTIPART", "error": "audio_file is empty"}), 400
        if len(file_bytes) > max_bytes:
            return jsonify({"code": "FILE_TOO_LARGE", "error": f"audio_file exceeds {config.MAX_AUDIO_SIZE_MB}MB limit"}), 413

        form = request.form or {}
        source_kind = _admin_import_clean_text(form.get("source_kind"), 64).lower() or "upload"
        if source_kind not in _IMPORT_SOURCE_KINDS:
            logger.info("admin import: unknown source_kind=%r; using upload", source_kind)
            source_kind = "upload"
        source_url_raw = _admin_import_clean_text(form.get("source_url"), 2048)
        source_url = None
        if source_url_raw:
            parsed = urlparse(source_url_raw)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                return jsonify({"code": "INVALID_INPUT", "error": "source_url must be a valid http/https URL"}), 400
            source_url = source_url_raw

        source_title = _admin_import_clean_text(form.get("source_title"), 500) or None
        speaker_label = _admin_import_clean_text(form.get("speaker_label"), 200) or None
        language_code = _admin_import_clean_text(form.get("language_code"), 32) or None
        transcript_text = _admin_import_clean_text(form.get("transcript_text"), 12000) or None
        import_notes = _admin_import_clean_text(form.get("import_notes"), 4000) or None

        recording_id = str(uuid.uuid4())
        storage_path = _admin_import_storage_path(recording_id, original_name)
        content_type = (audio_file.mimetype or mimetypes.guess_type(original_name)[0] or "application/octet-stream").strip()
        if content_type in ("True", "False"):
            content_type = "application/octet-stream"

        try:
            db.upload_audio(config.AUDIO_BUCKET_NAME, storage_path, file_bytes, content_type=content_type)
        except Exception as upload_err:
            logger.warning("Admin recording import upload failed: %s", upload_err, exc_info=True)
            return jsonify({"code": "IMPORT_UPLOAD_FAILED", "error": "Failed to store uploaded audio"}), 500

        public_audio_url = _public_storage_url(config.AUDIO_BUCKET_NAME, storage_path)
        source_metadata = _admin_import_source_metadata(
            source_kind=source_kind,
            source_url=source_url,
            source_title=source_title,
            speaker_label=speaker_label,
            language_code=language_code,
            transcript_text=transcript_text,
            import_notes=import_notes,
            reviewer_id=str(request.user_id),
        )

        insert_payload = {
            "id": recording_id,
            "user_id": None,
            "session_id": None,
            "audio_url": public_audio_url or "",
            "duration": 0,
            "duration_seconds": None,
            "transcription_text": transcript_text,
            "storage_path": storage_path,
            "recording_origin": "admin_import",
            "source_metadata": source_metadata,
        }
        recording = None
        try:
            recording = db.create_recording(insert_payload)
        except Exception as create_err:
            err_low = str(create_err).lower()
            if "recording_origin" in err_low or "source_metadata" in err_low or "pgrst204" in err_low:
                fallback = {k: v for k, v in insert_payload.items() if k not in ("recording_origin", "source_metadata")}
                try:
                    recording = db.create_recording(fallback)
                except Exception as e2:
                    logger.warning("Admin recording import create_recording failed: %s", e2, exc_info=True)
                    return jsonify({"code": "IMPORT_RECORDING_CREATE_FAILED", "error": str(e2)}), 500
            else:
                logger.warning("Admin recording import create_recording failed: %s", create_err, exc_info=True)
                return jsonify({"code": "IMPORT_RECORDING_CREATE_FAILED", "error": str(create_err)}), 500

        if not recording:
            return jsonify({"code": "IMPORT_RECORDING_CREATE_FAILED", "error": "Failed to create recording row"}), 500

        playback_url = None
        try:
            playback_url = db.create_signed_url(config.AUDIO_BUCKET_NAME, storage_path, config.SIGNED_URL_EXPIRY_SECONDS)
        except Exception as playback_err:
            logger.warning("Admin recording import signed URL failed: %s", playback_err)
            playback_url = public_audio_url or None

        generated_snippets = []
        try:
            generated_snippets = generate_stress_snippets_for_recording(
                recording_id,
                source_type="internet",
                max_snippets=8,
                clip_seconds=STRESS_SNIPPET_CLIP_SEC_DEFAULT,
                clear_existing=True,
            )
        except Exception as snippet_err:
            logger.warning("Admin recording import snippet generation failed: %s", snippet_err, exc_info=True)

        return jsonify({
            "status": "ok",
            "recording_id": recording_id,
            "playback_url": playback_url,
            "generated_snippets_count": len(generated_snippets),
            "message": "Recording imported; stress snippets generated when ffmpeg and audio decode succeed.",
        }), 201
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "IMPORT_FAILED", "error": str(e)}), 500


@v2_bp.route("/admin/recordings/<recording_id>/playback-url", methods=["GET"])
@require_admin
def v2_admin_recording_playback_url(recording_id):
    """Return a fresh signed playback URL for any recording (admin). Used as fallback when report API returns no audio_url."""
    try:
        from config import Config
        config = Config()

        if not _is_valid_uuid(recording_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid recording ID"}), 400

        # Admin can look up any recording without user_id constraint.
        result = db.client.table("recordings").select("storage_path, audio_url").eq("id", recording_id).limit(1).execute()
        if not result.data:
            return jsonify({"code": "RECORDING_NOT_FOUND", "error": "Recording not found"}), 404

        rec = result.data[0]
        storage_path = (rec.get("storage_path") or "").strip()
        if not storage_path:
            return jsonify({"code": "NO_STORAGE_PATH", "error": "Recording has no storage path"}), 404

        try:
            audio_url = db.create_signed_url(config.AUDIO_BUCKET_NAME, storage_path, config.SIGNED_URL_EXPIRY_SECONDS)
        except Exception as e:
            logger.warning("Admin playback URL: signed URL failed for %s: %s", recording_id, e)
            # Fallback to public URL pattern
            supabase_url = (getattr(config, "SUPABASE_URL", "") or "").rstrip("/")
            audio_url = f"{supabase_url}/storage/v1/object/public/{config.AUDIO_BUCKET_NAME}/{storage_path}" if supabase_url else None

        if not audio_url:
            return jsonify({"code": "URL_GENERATION_FAILED", "error": "Could not generate playback URL"}), 500

        return jsonify({"audio_url": audio_url}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/recordings/<recording_id>", methods=["GET"])
@require_admin
def v2_admin_recording_detail(recording_id):
    """Return one recording row with signed playback URL when possible."""
    try:
        if not _is_valid_uuid(recording_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid recording ID"}), 400
        recording = db.get_recording(recording_id, None)
        if not recording:
            return jsonify({"code": "RECORDING_NOT_FOUND", "error": "Recording not found"}), 404
        playback_url = None
        storage_path = (recording.get("storage_path") or "").strip()
        if storage_path:
            try:
                playback_url = db.create_signed_url(config.AUDIO_BUCKET_NAME, storage_path, config.SIGNED_URL_EXPIRY_SECONDS)
            except Exception:
                playback_url = _public_storage_url(config.AUDIO_BUCKET_NAME, storage_path) or None
        recording_payload = dict(recording)
        recording_payload["recording_id"] = recording_payload.get("id")
        if playback_url:
            recording_payload["audio_url"] = playback_url
        return jsonify({
            "recording_id": recording_id,
            "recording": recording_payload,
            "playback_url": playback_url,
        }), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Admin: stress snippets (binary stress/no_stress labeling) ----------
@v2_bp.route("/admin/recordings/<recording_id>/stress-snippets/generate", methods=["POST"])
@require_admin
def v2_admin_generate_stress_snippets(recording_id):
    try:
        if not _is_valid_uuid(recording_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid recording ID"}), 400
        recording = db.get_recording(recording_id, None)
        if not recording:
            return jsonify({"code": "RECORDING_NOT_FOUND", "error": "Recording not found"}), 404

        data = request.get_json(silent=True) or {}
        max_snippets = data.get("max_snippets", 8)
        clip_seconds = data.get("clip_seconds", STRESS_SNIPPET_CLIP_SEC_DEFAULT)
        clear_existing = data.get("clear_existing", True)
        try:
            max_snippets = int(max_snippets)
        except (TypeError, ValueError):
            return jsonify({"code": "INVALID_INPUT", "error": "max_snippets must be an integer"}), 400
        try:
            clip_seconds = float(clip_seconds)
        except (TypeError, ValueError):
            return jsonify({"code": "INVALID_INPUT", "error": "clip_seconds must be a number"}), 400
        max_snippets = max(1, min(max_snippets, 16))
        clip_seconds = max(
            float(STRESS_SNIPPET_CLIP_SEC_MIN),
            min(clip_seconds, float(STRESS_SNIPPET_CLIP_SEC_MAX)),
        )

        source_type = _infer_stress_source_type(recording)
        created = generate_stress_snippets_for_recording(
            recording_id,
            source_type=source_type,
            max_snippets=max_snippets,
            clip_seconds=clip_seconds,
            clear_existing=bool(clear_existing),
        )
        return jsonify(
            {
                "status": "ok",
                "recording_id": recording_id,
                "source_type": source_type,
                "generated_count": len(created),
                "snippets": [_stress_snippet_payload(r) for r in created],
            }
        ), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/stress-snippets", methods=["GET"])
@require_admin
def v2_admin_list_stress_snippets():
    try:
        source_type = (request.args.get("source_type", "all") or "all").strip().lower()
        if source_type != "all" and source_type not in _STRESS_ALLOWED_SOURCE_TYPES:
            return jsonify({"code": "INVALID_INPUT", "error": "source_type must be one of: all, student, internet"}), 400
        label_state = (request.args.get("label_state", "all") or "all").strip().lower()
        if label_state not in {"all", "labeled", "unlabeled"}:
            return jsonify({"code": "INVALID_INPUT", "error": "label_state must be one of: all, labeled, unlabeled"}), 400
        recording_id = (request.args.get("recording_id") or "").strip() or None
        if recording_id and not _is_valid_uuid(recording_id):
            return jsonify({"code": "INVALID_INPUT", "error": "recording_id must be a valid UUID"}), 400
        try:
            limit = int(request.args.get("limit", 50))
            offset = int(request.args.get("offset", 0))
        except (TypeError, ValueError):
            return jsonify({"code": "INVALID_INPUT", "error": "limit and offset must be integers"}), 400
        limit = max(1, min(limit, 200))
        offset = max(0, offset)

        sort_raw = (request.args.get("sort") or "newest").strip().lower()
        if sort_raw not in {"newest", "oldest"}:
            return jsonify({"code": "INVALID_INPUT", "error": "sort must be newest or oldest"}), 400
        sort_created_desc = sort_raw != "oldest"

        ex_raw = (request.args.get("exclude_queue_skipped") or "").strip().lower()
        if ex_raw in ("0", "false", "no"):
            exclude_queue_skipped = False
        elif ex_raw in ("1", "true", "yes"):
            exclude_queue_skipped = True
        else:
            exclude_queue_skipped = label_state == "unlabeled"

        rows = db.v2_list_stress_snippets(
            source_type=None if source_type == "all" else source_type,
            recording_id=recording_id,
            label_state=label_state,
            limit=limit,
            offset=offset,
            sort_created_desc=sort_created_desc,
            exclude_queue_skipped=exclude_queue_skipped,
        )
        snippets = [_stress_snippet_payload(r) for r in rows]
        return jsonify(
            {
                "snippets": snippets,
                "source_type": source_type,
                "label_state": label_state,
                "sort": sort_raw,
                "exclude_queue_skipped": exclude_queue_skipped,
                "limit": limit,
                "offset": offset,
                "count": len(snippets),
            }
        ), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/stress-snippets/settings", methods=["GET", "PUT"])
@require_admin
def v2_admin_stress_snippets_settings():
    runtime_key = "stress_snippets_auto_extract_enabled"
    try:
        if request.method == "GET":
            raw = db.get_runtime_config(runtime_key)
            return jsonify(
                {
                    "settings": {
                        "auto_extract_enabled": _runtime_bool(runtime_key, True),
                        "runtime_key": runtime_key,
                        "raw_value": raw,
                    }
                }
            ), 200

        data = request.get_json(silent=True) or {}
        if "auto_extract_enabled" not in data:
            return jsonify({"code": "INVALID_INPUT", "error": "auto_extract_enabled is required"}), 400
        value = data.get("auto_extract_enabled")
        if not isinstance(value, bool):
            return jsonify({"code": "INVALID_INPUT", "error": "auto_extract_enabled must be boolean"}), 400
        saved = db.upsert_runtime_config(
            key=runtime_key,
            value="true" if value else "false",
            updated_by=str(request.user_id),
            metadata={"source": "v2_admin_stress_snippets_settings"},
        )
        return jsonify(
            {
                "status": "ok",
                "settings": {
                    "auto_extract_enabled": bool(value),
                    "runtime_key": runtime_key,
                    "saved": saved,
                },
            }
        ), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/stress-snippets/audit-sample", methods=["GET"])
@require_admin
def v2_admin_stress_snippets_audit_sample():
    """Return a random sample of labeled snippets for weekly QA audit."""
    try:
        source_type = (request.args.get("source_type", "all") or "all").strip().lower()
        if source_type != "all" and source_type not in _STRESS_ALLOWED_SOURCE_TYPES:
            return jsonify({"code": "INVALID_INPUT", "error": "source_type must be one of: all, student, internet"}), 400
        try:
            sample_rate = float(request.args.get("sample_rate", 0.1))
            max_pool = int(request.args.get("max_pool", 1000))
            limit = int(request.args.get("limit", 100))
            seed = int(request.args.get("seed", int(time.time())))
        except (TypeError, ValueError):
            return jsonify({"code": "INVALID_INPUT", "error": "sample_rate, max_pool, limit, seed must be numeric"}), 400
        sample_rate = max(0.01, min(sample_rate, 1.0))
        max_pool = max(50, min(max_pool, 5000))
        limit = max(1, min(limit, 500))
        rows = db.v2_list_stress_snippets(
            source_type=None if source_type == "all" else source_type,
            label_state="labeled",
            limit=max_pool,
            offset=0,
            sort_created_desc=True,
            exclude_queue_skipped=False,
        )
        if not rows:
            return jsonify({"status": "ok", "snippets": [], "count": 0, "sample_rate": sample_rate}), 200
        rng = random.Random(seed)
        pool = list(rows)
        rng.shuffle(pool)
        target = max(1, int(round(len(pool) * sample_rate)))
        target = min(target, limit)
        picked = pool[:target]
        return jsonify(
            {
                "status": "ok",
                "source_type": source_type,
                "sample_rate": sample_rate,
                "seed": seed,
                "pool_count": len(pool),
                "count": len(picked),
                "snippets": [_stress_snippet_payload(r) for r in picked],
            }
        ), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/stress-snippets/<snippet_id>", methods=["GET"])
@require_admin
def v2_admin_get_stress_snippet(snippet_id):
    try:
        if not _is_valid_uuid(snippet_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid snippet ID"}), 400
        row = db.v2_get_stress_snippet(snippet_id)
        if not row:
            return jsonify({"code": "SNIPPET_NOT_FOUND", "error": "Snippet not found"}), 404
        return jsonify({"status": "ok", "snippet": _stress_snippet_payload(row)}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/stress-snippets/<snippet_id>/playback-url", methods=["GET"])
@require_admin
def v2_admin_stress_snippet_playback_url(snippet_id):
    """Mint a fresh 1h signed URL for this snippet's audio, Just-In-Time.

    Frontend calls this when the audio component renders so it never plays a
    stale/expired URL from a long-lived list payload.
    """
    try:
        if not _is_valid_uuid(snippet_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid snippet ID"}), 400
        row = db.v2_get_stress_snippet(snippet_id)
        if not row:
            return jsonify({"code": "SNIPPET_NOT_FOUND", "error": "Snippet not found"}), 404
        storage_path = (row.get("storage_path") or "").strip()
        if not storage_path:
            return jsonify({"code": "SNIPPET_NO_AUDIO", "error": "Snippet has no audio file"}), 400
        ttl_seconds = 3600
        try:
            playback_url = db.create_signed_url(config.AUDIO_BUCKET_NAME, storage_path, ttl_seconds)
        except Exception as sign_err:
            sentry_sdk.capture_exception(sign_err)
            playback_url = _public_storage_url(config.AUDIO_BUCKET_NAME, storage_path) or None
        if not playback_url:
            return jsonify({"code": "SIGN_FAILED", "error": "Could not mint signed URL"}), 500
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        ).isoformat().replace("+00:00", "Z")
        return jsonify(
            {
                "playback_url": playback_url,
                "expires_at": expires_at,
                "snippet_id": snippet_id,
            }
        ), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/stress-snippets/<snippet_id>/label", methods=["PATCH", "DELETE"])
@require_admin
def v2_admin_label_stress_snippet(snippet_id):
    """Set label (PATCH), clear label (DELETE or PATCH { clear: true })."""
    try:
        if not _is_valid_uuid(snippet_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid snippet ID"}), 400
        snippet = db.v2_get_stress_snippet(snippet_id)
        if not snippet:
            return jsonify({"code": "SNIPPET_NOT_FOUND", "error": "Snippet not found"}), 404
        if request.method == "DELETE":
            updated = db.v2_clear_stress_snippet_label(snippet_id)
            return jsonify({"status": "ok", "cleared": True, "snippet": _stress_snippet_payload(updated or snippet)}), 200
        data = request.get_json(silent=True) or {}
        if data.get("clear") is True:
            updated = db.v2_clear_stress_snippet_label(snippet_id)
            return jsonify({"status": "ok", "cleared": True, "snippet": _stress_snippet_payload(updated or snippet)}), 200
        label = data.get("label")
        if label is None:
            return jsonify({"code": "INVALID_INPUT", "error": "label is required (or pass clear: true)"}), 422
        label = str(label).strip().lower()
        if label not in _STRESS_ALLOWED_LABELS:
            return jsonify({"code": "INVALID_INPUT", "error": "label must be one of: stress, no_stress"}), 422
        notes = data.get("notes")
        if notes is not None and not isinstance(notes, str):
            return jsonify({"code": "INVALID_INPUT", "error": "notes must be a string or null"}), 422
        cleaned_notes = notes.strip() if isinstance(notes, str) else None
        if label == "stress" and not cleaned_notes:
            return jsonify({"code": "INVALID_INPUT", "error": "notes are required when label=stress"}), 422
        if isinstance(cleaned_notes, str) and len(cleaned_notes) > 2000:
            return jsonify({"code": "INVALID_INPUT", "error": "notes must be <= 2000 chars"}), 422
        reviewer_email = (getattr(request, "token_payload", {}) or {}).get("email")
        if not reviewer_email:
            reviewer_email = db.get_user_email_from_auth(str(request.user_id))
        updated = db.v2_set_stress_snippet_label(
            snippet_id,
            reviewer_id=str(request.user_id),
            label=label,
            notes=cleaned_notes,
            reviewer_email=reviewer_email,
        )
        return jsonify({"status": "ok", "snippet": _stress_snippet_payload(updated or snippet)}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/stress-snippets/<snippet_id>/queue-skip", methods=["POST"])
@require_admin
def v2_admin_stress_snippet_queue_skip(snippet_id):
    """Defer this clip in the unlabeled queue (hidden when exclude_queue_skipped is on)."""
    try:
        if not _is_valid_uuid(snippet_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid snippet ID"}), 400
        snippet = db.v2_get_stress_snippet(snippet_id)
        if not snippet:
            return jsonify({"code": "SNIPPET_NOT_FOUND", "error": "Snippet not found"}), 404
        now = datetime.now(timezone.utc).isoformat()
        updated = db.v2_merge_stress_snippet_features(
            snippet_id,
            {
                "queue_skipped": True,
                "queue_skipped_at": now,
                "queue_skipped_by": str(request.user_id),
            },
        )
        return jsonify({"status": "ok", "snippet": _stress_snippet_payload(updated or snippet)}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/stress-snippets/<snippet_id>/queue-unskip", methods=["POST"])
@require_admin
def v2_admin_stress_snippet_queue_unskip(snippet_id):
    """Bring a deferred clip back into the default unlabeled queue."""
    try:
        if not _is_valid_uuid(snippet_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid snippet ID"}), 400
        snippet = db.v2_get_stress_snippet(snippet_id)
        if not snippet:
            return jsonify({"code": "SNIPPET_NOT_FOUND", "error": "Snippet not found"}), 404
        updated = db.v2_merge_stress_snippet_features(
            snippet_id,
            {
                "queue_skipped": None,
                "queue_skipped_at": None,
                "queue_skipped_by": None,
            },
        )
        return jsonify({"status": "ok", "snippet": _stress_snippet_payload(updated or snippet)}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Admin: charisma snippets (binary charisma/no_charisma labeling) ----------

def _charisma_snippet_payload(row: dict) -> dict:
    storage_path = (row.get("storage_path") or "").strip()
    audio_url = None
    if storage_path:
        try:
            audio_url = db.create_signed_url(config.AUDIO_BUCKET_NAME, storage_path, config.SIGNED_URL_EXPIRY_SECONDS)
        except Exception:
            audio_url = _public_storage_url(config.AUDIO_BUCKET_NAME, storage_path) or None
    payload = dict(row)
    try:
        sm = int(row.get("start_ms") or 0)
    except (TypeError, ValueError):
        sm = 0
    try:
        em = int(row.get("end_ms") or 0)
    except (TypeError, ValueError):
        em = 0
    try:
        dm = int(row.get("duration_ms") or 0)
    except (TypeError, ValueError):
        dm = 0
    if em <= sm and dm > 0:
        em = sm + dm
    start_sec = round(sm / 1000.0, 3)
    end_sec = round(em / 1000.0, 3)
    duration_sec = max(0.0, round((em - sm) / 1000.0, 3))
    if duration_sec <= 0 and dm > 0:
        duration_sec = round(dm / 1000.0, 3)
        end_sec = round(start_sec + duration_sec, 3)
    payload["start_sec"] = start_sec
    payload["end_sec"] = end_sec
    payload["duration_sec"] = duration_sec
    payload["startSec"] = start_sec
    payload["endSec"] = end_sec
    payload["durationSec"] = duration_sec
    payload["audio_url"] = audio_url
    payload["playable"] = bool(audio_url and storage_path)
    feats = row.get("features") if isinstance(row.get("features"), dict) else {}
    payload["queue_skipped"] = bool(feats.get("queue_skipped"))
    return payload


@v2_bp.route("/admin/recordings/<recording_id>/charisma-snippets/generate", methods=["POST"])
@require_admin
def v2_admin_generate_charisma_snippets(recording_id):
    try:
        if not _is_valid_uuid(recording_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid recording ID"}), 400
        recording = db.get_recording(recording_id, None)
        if not recording:
            return jsonify({"code": "RECORDING_NOT_FOUND", "error": "Recording not found"}), 404
        data = request.get_json(silent=True) or {}
        max_snippets = data.get("max_snippets", 8)
        clip_seconds = data.get("clip_seconds", CHARISMA_SNIPPET_CLIP_SEC_DEFAULT)
        clear_existing = data.get("clear_existing", True)
        try:
            max_snippets = int(max_snippets)
        except (TypeError, ValueError):
            return jsonify({"code": "INVALID_INPUT", "error": "max_snippets must be an integer"}), 400
        try:
            clip_seconds = float(clip_seconds)
        except (TypeError, ValueError):
            return jsonify({"code": "INVALID_INPUT", "error": "clip_seconds must be a number"}), 400
        max_snippets = max(1, min(max_snippets, 16))
        clip_seconds = max(
            float(CHARISMA_SNIPPET_CLIP_SEC_MIN),
            min(clip_seconds, float(CHARISMA_SNIPPET_CLIP_SEC_MAX)),
        )
        source_type = _infer_stress_source_type(recording)
        created = generate_charisma_snippets_for_recording(
            recording_id,
            source_type=source_type,
            max_snippets=max_snippets,
            clip_seconds=clip_seconds,
            clear_existing=bool(clear_existing),
        )
        return jsonify(
            {
                "status": "ok",
                "recording_id": recording_id,
                "source_type": source_type,
                "generated_count": len(created),
                "snippets": [_charisma_snippet_payload(r) for r in created],
            }
        ), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/charisma-snippets", methods=["GET"])
@require_admin
def v2_admin_list_charisma_snippets():
    try:
        source_type = request.args.get("source_type", "all")
        if source_type not in ("all", "student", "internet"):
            return jsonify({"code": "INVALID_INPUT", "error": "source_type must be all, student, or internet"}), 400
        label_state = request.args.get("label_state", "all")
        if label_state not in ("all", "labeled", "unlabeled"):
            return jsonify({"code": "INVALID_INPUT", "error": "label_state must be all, labeled, or unlabeled"}), 400
        recording_id = request.args.get("recording_id")
        if recording_id and not _is_valid_uuid(recording_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid recording_id"}), 400
        try:
            limit = max(1, min(int(request.args.get("limit", 50)), 200))
        except (TypeError, ValueError):
            return jsonify({"code": "INVALID_INPUT", "error": "limit must be an integer"}), 400
        try:
            offset = max(0, int(request.args.get("offset", 0)))
        except (TypeError, ValueError):
            return jsonify({"code": "INVALID_INPUT", "error": "offset must be an integer"}), 400
        sort = request.args.get("sort", "newest")
        sort_desc = sort != "oldest"
        exclude_skipped_raw = request.args.get("exclude_queue_skipped")
        if exclude_skipped_raw is None:
            exclude_queue_skipped = label_state == "unlabeled"
        else:
            exclude_queue_skipped = exclude_skipped_raw.lower() in ("1", "true", "yes")
        rows = db.v2_list_charisma_snippets(
            source_type=source_type if source_type != "all" else None,
            recording_id=recording_id,
            label_state=label_state,
            limit=limit,
            offset=offset,
            sort_created_desc=sort_desc,
            exclude_queue_skipped=exclude_queue_skipped,
        )
        return jsonify(
            {
                "status": "ok",
                "source_type": source_type,
                "label_state": label_state,
                "limit": limit,
                "offset": offset,
                "count": len(rows),
                "snippets": [_charisma_snippet_payload(r) for r in rows],
            }
        ), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/charisma-snippets/settings", methods=["GET", "PUT"])
@require_admin
def v2_admin_charisma_snippets_settings():
    runtime_key = "charisma_snippets_auto_extract_enabled"
    try:
        if request.method == "GET":
            enabled = _runtime_bool(runtime_key, True)
            raw = (db.get_runtime_config(runtime_key) or "").strip()
            return jsonify({"status": "ok", "settings": {"auto_extract_enabled": enabled}, "runtime_key": runtime_key, "raw_value": raw or None}), 200
        data = request.get_json(silent=True) or {}
        if "auto_extract_enabled" not in data:
            return jsonify({"code": "INVALID_INPUT", "error": "auto_extract_enabled is required"}), 422
        val = data["auto_extract_enabled"]
        if not isinstance(val, bool):
            return jsonify({"code": "INVALID_INPUT", "error": "auto_extract_enabled must be a boolean"}), 422
        db.set_runtime_config(runtime_key, "true" if val else "false")
        return jsonify({"status": "ok", "settings": {"auto_extract_enabled": val}, "runtime_key": runtime_key}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/charisma-snippets/audit-sample", methods=["GET"])
@require_admin
def v2_admin_charisma_snippets_audit_sample():
    try:
        source_type = request.args.get("source_type")
        try:
            sample_rate = max(0.01, min(1.0, float(request.args.get("sample_rate", 0.10))))
        except (TypeError, ValueError):
            sample_rate = 0.10
        try:
            seed = int(request.args.get("seed", 0))
        except (TypeError, ValueError):
            seed = 0
        rows = db.v2_list_charisma_snippets(
            source_type=source_type if source_type in ("student", "internet") else None,
            label_state="labeled",
            limit=200,
            offset=0,
            sort_created_desc=False,
        )
        import random
        rng = random.Random(seed or None)
        k = max(1, int(len(rows) * sample_rate))
        picked = rng.sample(rows, min(k, len(rows)))
        return jsonify(
            {
                "status": "ok",
                "source_type": source_type,
                "sample_rate": sample_rate,
                "seed": seed,
                "pool_count": len(rows),
                "count": len(picked),
                "snippets": [_charisma_snippet_payload(r) for r in picked],
            }
        ), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/charisma-snippets/<snippet_id>", methods=["GET"])
@require_admin
def v2_admin_get_charisma_snippet(snippet_id):
    try:
        if not _is_valid_uuid(snippet_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid snippet ID"}), 400
        row = db.v2_get_charisma_snippet(snippet_id)
        if not row:
            return jsonify({"code": "SNIPPET_NOT_FOUND", "error": "Snippet not found"}), 404
        return jsonify({"status": "ok", "snippet": _charisma_snippet_payload(row)}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/charisma-snippets/<snippet_id>/playback-url", methods=["GET"])
@require_admin
def v2_admin_charisma_snippet_playback_url(snippet_id):
    """Mint a fresh 1h signed URL for this snippet's audio, Just-In-Time."""
    try:
        if not _is_valid_uuid(snippet_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid snippet ID"}), 400
        row = db.v2_get_charisma_snippet(snippet_id)
        if not row:
            return jsonify({"code": "SNIPPET_NOT_FOUND", "error": "Snippet not found"}), 404
        storage_path = (row.get("storage_path") or "").strip()
        if not storage_path:
            return jsonify({"code": "SNIPPET_NO_AUDIO", "error": "Snippet has no audio file"}), 400
        ttl_seconds = 3600
        try:
            playback_url = db.create_signed_url(config.AUDIO_BUCKET_NAME, storage_path, ttl_seconds)
        except Exception as sign_err:
            sentry_sdk.capture_exception(sign_err)
            playback_url = _public_storage_url(config.AUDIO_BUCKET_NAME, storage_path) or None
        if not playback_url:
            return jsonify({"code": "SIGN_FAILED", "error": "Could not mint signed URL"}), 500
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        ).isoformat().replace("+00:00", "Z")
        return jsonify({"playback_url": playback_url, "expires_at": expires_at, "snippet_id": snippet_id}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/charisma-snippets/<snippet_id>/label", methods=["PATCH", "DELETE"])
@require_admin
def v2_admin_label_charisma_snippet(snippet_id):
    """Set label (PATCH), clear label (DELETE or PATCH { clear: true })."""
    try:
        if not _is_valid_uuid(snippet_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid snippet ID"}), 400
        snippet = db.v2_get_charisma_snippet(snippet_id)
        if not snippet:
            return jsonify({"code": "SNIPPET_NOT_FOUND", "error": "Snippet not found"}), 404
        if request.method == "DELETE":
            updated = db.v2_clear_charisma_snippet_label(snippet_id)
            return jsonify({"status": "ok", "cleared": True, "snippet": _charisma_snippet_payload(updated or snippet)}), 200
        data = request.get_json(silent=True) or {}
        if data.get("clear") is True:
            updated = db.v2_clear_charisma_snippet_label(snippet_id)
            return jsonify({"status": "ok", "cleared": True, "snippet": _charisma_snippet_payload(updated or snippet)}), 200
        label = data.get("label")
        if label is None:
            return jsonify({"code": "INVALID_INPUT", "error": "label is required (or pass clear: true)"}), 422
        label = str(label).strip().lower()
        if label not in _CHARISMA_ALLOWED_LABELS:
            return jsonify({"code": "INVALID_INPUT", "error": "label must be one of: charisma, no_charisma"}), 422
        notes = data.get("notes")
        if notes is not None and not isinstance(notes, str):
            return jsonify({"code": "INVALID_INPUT", "error": "notes must be a string or null"}), 422
        cleaned_notes = notes.strip() if isinstance(notes, str) else None
        if label == "charisma" and not cleaned_notes:
            return jsonify({"code": "INVALID_INPUT", "error": "notes are required when label=charisma"}), 422
        if isinstance(cleaned_notes, str) and len(cleaned_notes) > 2000:
            return jsonify({"code": "INVALID_INPUT", "error": "notes must be <= 2000 chars"}), 422
        reviewer_email = (getattr(request, "token_payload", {}) or {}).get("email")
        if not reviewer_email:
            reviewer_email = db.get_user_email_from_auth(str(request.user_id))
        updated = db.v2_set_charisma_snippet_label(
            snippet_id,
            reviewer_id=str(request.user_id),
            label=label,
            notes=cleaned_notes,
            reviewer_email=reviewer_email,
        )
        return jsonify({"status": "ok", "snippet": _charisma_snippet_payload(updated or snippet)}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/charisma-snippets/<snippet_id>/queue-skip", methods=["POST"])
@require_admin
def v2_admin_charisma_snippet_queue_skip(snippet_id):
    """Defer this clip in the unlabeled queue."""
    try:
        if not _is_valid_uuid(snippet_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid snippet ID"}), 400
        snippet = db.v2_get_charisma_snippet(snippet_id)
        if not snippet:
            return jsonify({"code": "SNIPPET_NOT_FOUND", "error": "Snippet not found"}), 404
        now = datetime.now(timezone.utc).isoformat()
        updated = db.v2_merge_charisma_snippet_features(
            snippet_id,
            {
                "queue_skipped": True,
                "queue_skipped_at": now,
                "queue_skipped_by": str(request.user_id),
            },
        )
        return jsonify({"status": "ok", "snippet": _charisma_snippet_payload(updated or snippet)}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/charisma-snippets/<snippet_id>/queue-unskip", methods=["POST"])
@require_admin
def v2_admin_charisma_snippet_queue_unskip(snippet_id):
    """Restore a deferred clip to the unlabeled queue."""
    try:
        if not _is_valid_uuid(snippet_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid snippet ID"}), 400
        snippet = db.v2_get_charisma_snippet(snippet_id)
        if not snippet:
            return jsonify({"code": "SNIPPET_NOT_FOUND", "error": "Snippet not found"}), 404
        updated = db.v2_merge_charisma_snippet_features(
            snippet_id,
            {
                "queue_skipped": None,
                "queue_skipped_at": None,
                "queue_skipped_by": None,
            },
        )
        return jsonify({"status": "ok", "snippet": _charisma_snippet_payload(updated or snippet)}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Admin: tasks_pool (global pool) + tasks (per student) ----------


def _admin_tasks_pool_list_payload(data: list):
    """JSON key matches DB table name public.tasks_pool (plural)."""
    return {"tasks_pool": data}


def _admin_tasks_pool_row_payload(row):
    if row is None:
        return {"tasks_pool": None}
    return {"tasks_pool": row}


def _task_template_validation_error(code: str, field: str, message: str):
    return jsonify({"code": code, "error": message, "details": {field: message}}), 400


def _is_duplicate_active_slot_error(err: Exception) -> bool:
    text = str(err).lower()
    return ("idx_tasks_pool_active_slot_unique" in text) or (
        "duplicate key value violates unique constraint" in text and "target_profile" in text and "step_in_level" in text
    )


def _normalize_task_template_payload(data: dict, *, is_create: bool, allow_partial: bool = False):
    payload = {}
    if is_create or "text" in data:
        text = (data.get("text") or "").strip()
        if not text:
            return None, _task_template_validation_error("INVALID_TEXT", "text", "text is required and must be non-empty")
        payload["text"] = text
    if "order_index" in data:
        try:
            payload["order_index"] = int(data.get("order_index"))
        except (TypeError, ValueError):
            payload["order_index"] = 0
    if "max_performance_score" in data:
        try:
            payload["max_performance_score"] = float(data.get("max_performance_score"))
        except (TypeError, ValueError):
            payload["max_performance_score"] = 1.0

    needs_profile = is_create or (not allow_partial) or ("target_profile" in data)
    if needs_profile:
        target_profile = (data.get("target_profile") or _TASK_TEMPLATE_DEFAULT_PROFILE).strip()
        if target_profile not in _TASK_TEMPLATE_ALLOWED_PROFILES:
            return None, _task_template_validation_error(
                "INVALID_TARGET_PROFILE",
                "target_profile",
                "target_profile must be one of: The Overwhelmed, The Stressor, The Drifter, The Master",
            )
        payload["target_profile"] = target_profile

    needs_level = is_create or (not allow_partial) or ("level" in data)
    if needs_level:
        raw_level = data.get("level", _TASK_TEMPLATE_DEFAULT_LEVEL)
        try:
            level = int(raw_level)
        except (TypeError, ValueError):
            return None, _task_template_validation_error("INVALID_LEVEL", "level", "level must be an integer >= 1")
        if level < 1:
            return None, _task_template_validation_error("INVALID_LEVEL", "level", "level must be an integer >= 1")
        payload["level"] = level

    needs_step = is_create or (not allow_partial) or ("step_in_level" in data)
    if needs_step:
        raw_step = data.get("step_in_level", _TASK_TEMPLATE_DEFAULT_STEP)
        try:
            step_in_level = int(raw_step)
        except (TypeError, ValueError):
            return None, _task_template_validation_error("INVALID_STEP_IN_LEVEL", "step_in_level", "step_in_level must be an integer in [1..10]")
        if step_in_level < 1 or step_in_level > 10:
            return None, _task_template_validation_error("INVALID_STEP_IN_LEVEL", "step_in_level", "step_in_level must be an integer in [1..10]")
        payload["step_in_level"] = step_in_level

    if is_create:
        payload["is_active"] = bool(data.get("is_active", True))
    elif "is_active" in data:
        payload["is_active"] = bool(data.get("is_active"))

    if is_create or "replaces_task_id" in data:
        payload["replaces_task_id"] = data.get("replaces_task_id") or None

    return payload, None


@v2_bp.route("/admin/tasks-pool", methods=["GET"])
@v2_bp.route("/admin/task-pool", methods=["GET"])
@v2_bp.route("/admin/task-warm-up-pool", methods=["GET"])
@require_admin
def v2_admin_tasks_pool_list():
    try:
        include_inactive = (request.args.get("include_inactive") or "").strip().lower() in ("1", "true", "yes")
        data = db.v2_get_task_pool(include_inactive=include_inactive)
    except Exception:
        data = []
    return jsonify(_admin_tasks_pool_list_payload(data)), 200


@v2_bp.route("/admin/tasks-pool", methods=["POST"])
@v2_bp.route("/admin/task-pool", methods=["POST"])
@v2_bp.route("/admin/task-warm-up-pool", methods=["POST"])
@require_admin
def v2_admin_tasks_pool_create():
    data = request.get_json() or {}
    payload, err_resp = _normalize_task_template_payload(data, is_create=True, allow_partial=False)
    if err_resp:
        return err_resp
    payload = payload or {}
    try:
        payload.setdefault("order_index", int(data.get("order_index", 0)))
    except (TypeError, ValueError):
        payload.setdefault("order_index", 0)
    try:
        payload.setdefault("max_performance_score", float(data.get("max_performance_score", 1.0)))
    except (TypeError, ValueError):
        payload.setdefault("max_performance_score", 1.0)
    replaces_task_id = payload.get("replaces_task_id")
    if replaces_task_id:
        if not _is_valid_uuid(replaces_task_id):
            return jsonify({"code": "INVALID_INPUT", "error": "replaces_task_id must be a valid UUID", "details": {"replaces_task_id": "invalid uuid"}}), 400
        if not db.v2_get_task_pool_by_id(replaces_task_id):
            return jsonify({"code": "INVALID_INPUT", "error": "replaces_task_id not found", "details": {"replaces_task_id": "not found"}}), 400
    try:
        row = db.v2_insert_task_pool(payload)
        return jsonify(_admin_tasks_pool_row_payload(row)), 201
    except Exception as e:
        if _is_duplicate_active_slot_error(e):
            return jsonify({
                "code": "DUPLICATE_ACTIVE_SLOT",
                "error": "Active template for this target_profile/level/step_in_level already exists",
                "details": {
                    "target_profile": payload.get("target_profile"),
                    "level": payload.get("level"),
                    "step_in_level": payload.get("step_in_level"),
                },
            }), 400
        err = str(e).lower()
        hint = "Run migrations/rename_warmup_to_tasks_and_drop_focus.sql if public.tasks / public.tasks_pool are missing." if ("relation" in err or "does not exist" in err or "42p01" in err) else None
        out = {"error": str(e)}
        if hint:
            out["hint"] = hint
        return jsonify(out), 500


@v2_bp.route("/admin/tasks-pool/<pool_id>", methods=["PUT"])
@v2_bp.route("/admin/task-pool/<pool_id>", methods=["PUT"])
@v2_bp.route("/admin/task-warm-up-pool/<pool_id>", methods=["PUT"])
@require_admin
def v2_admin_tasks_pool_update(pool_id):
    data = request.get_json() or {}
    payload, err_resp = _normalize_task_template_payload(data, is_create=False, allow_partial=True)
    if err_resp:
        return err_resp
    payload = payload or {}
    for key in ("order_index", "max_performance_score"):
        if key in data and key not in payload:
            payload[key] = data[key]
    if "max_performance_score" in payload:
        try:
            payload["max_performance_score"] = float(payload["max_performance_score"])
        except (TypeError, ValueError):
            payload["max_performance_score"] = 1.0
    if "replaces_task_id" in payload and payload.get("replaces_task_id"):
        rid = payload.get("replaces_task_id")
        if not _is_valid_uuid(rid):
            return jsonify({"code": "INVALID_INPUT", "error": "replaces_task_id must be a valid UUID", "details": {"replaces_task_id": "invalid uuid"}}), 400
        if not db.v2_get_task_pool_by_id(rid):
            return jsonify({"code": "INVALID_INPUT", "error": "replaces_task_id not found", "details": {"replaces_task_id": "not found"}}), 400
    if not payload:
        row = db.v2_get_task_pool_by_id(pool_id)
    else:
        try:
            row = db.v2_update_task_pool(pool_id, payload)
        except Exception as e:
            if _is_duplicate_active_slot_error(e):
                return jsonify({
                    "code": "DUPLICATE_ACTIVE_SLOT",
                    "error": "Active template for this target_profile/level/step_in_level already exists",
                    "details": {
                        "target_profile": payload.get("target_profile"),
                        "level": payload.get("level"),
                        "step_in_level": payload.get("step_in_level"),
                    },
                }), 400
            raise
    if not row:
        return jsonify({"error": "Pool task not found"}), 404
    return jsonify(_admin_tasks_pool_row_payload(row)), 200


@v2_bp.route("/admin/tasks-pool/<pool_id>", methods=["DELETE"])
@v2_bp.route("/admin/task-pool/<pool_id>", methods=["DELETE"])
@v2_bp.route("/admin/task-warm-up-pool/<pool_id>", methods=["DELETE"])
@require_admin
def v2_admin_tasks_pool_delete(pool_id):
    try:
        row = db.v2_get_task_pool_by_id(pool_id)
        if not row:
            return jsonify({"error": "Pool task not found"}), 404
        row = db.v2_update_task_pool(pool_id, {"is_active": False})
        return jsonify({"status": "ok", "tasks_pool": row, "soft_deleted": True}), 200
    except Exception as err:
        logger.warning("task pool delete soft-delete failed for pool_id=%s: %s", pool_id, err, exc_info=True)
        return jsonify({"error": "Delete failed.", "detail": str(err)}), 503


@v2_bp.route("/admin/students/<user_id>/tasks", methods=["GET"])
@v2_bp.route("/admin/students/<user_id>/task-warm-up", methods=["GET"])
@require_admin
def v2_admin_student_tasks_list(user_id):
    try:
        rows = db.v2_get_student_tasks(user_id)
        return jsonify({"tasks": rows}), 200
    except Exception as err:
        logger.warning("student tasks GET failed for user %s: %s", user_id, err, exc_info=True)
        return jsonify({"tasks": []}), 200


@v2_bp.route("/admin/students/<user_id>/tasks", methods=["PUT"])
@v2_bp.route("/admin/students/<user_id>/task-warm-up", methods=["PUT"])
@require_admin
def v2_admin_student_tasks_sync(user_id):
    """Body: { "pool_task_ids": [uuid, ...] } display order."""
    data = request.get_json() or {}
    pool_task_ids = data.get("pool_task_ids")
    if pool_task_ids is None:
        return jsonify({"error": "pool_task_ids is required"}), 400
    if not isinstance(pool_task_ids, list):
        return jsonify({"error": "pool_task_ids must be a list"}), 400
    pool_task_ids = [str(x) for x in pool_task_ids]
    try:
        rows = db.v2_sync_student_tasks_from_pool(user_id, pool_task_ids)
        return jsonify({"tasks": rows}), 200
    except Exception as err:
        logger.warning("student tasks PUT sync failed for user %s: %s", user_id, err, exc_info=True)
        detail = str(err)
        return jsonify({
            "error": "tasks sync failed (run DB migration rename_warmup_to_tasks_and_drop_focus.sql).",
            "detail": detail,
            "message": f"Confirm selection failed. Server said: {detail}",
        }), 503


@v2_bp.route("/admin/students/<user_id>/tasks", methods=["POST"])
@v2_bp.route("/admin/students/<user_id>/task-warm-up", methods=["POST"])
@require_admin
def v2_admin_student_tasks_create(user_id):
    data = request.get_json() or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
    data["user_id"] = user_id
    data["text"] = text
    data.setdefault("order_index", int(data.get("order_index", 0)))
    data.setdefault("max_performance_score", float(data.get("max_performance_score", 1.0)))
    try:
        row = db.v2_insert_student_task(data)
        return jsonify({"task": row}), 201
    except Exception as err:
        logger.warning("student tasks POST failed for user %s: %s", user_id, err, exc_info=True)
        return jsonify({"error": "Failed to create task.", "detail": str(err)}), 503


@v2_bp.route("/admin/students/<user_id>/tasks/create-pool-and-assign", methods=["POST"])
@v2_bp.route("/admin/students/<user_id>/task-warm-up/create-pool-and-assign", methods=["POST"])
@require_admin
def v2_admin_student_tasks_create_pool_and_assign(user_id):
    data = request.get_json() or {}
    payload, err_resp = _normalize_task_template_payload(data, is_create=True, allow_partial=False)
    if err_resp:
        return err_resp
    text = payload["text"]
    replaces_task_id = payload.get("replaces_task_id")
    if replaces_task_id:
        if not _is_valid_uuid(replaces_task_id):
            return jsonify({"code": "INVALID_INPUT", "error": "replaces_task_id must be a valid UUID", "details": {"replaces_task_id": "invalid uuid"}}), 400
        if not db.v2_get_task_pool_by_id(replaces_task_id):
            return jsonify({"code": "INVALID_INPUT", "error": "replaces_task_id not found", "details": {"replaces_task_id": "not found"}}), 400
    insert_at = data.get("insert_at", "end")
    if insert_at != "end" and insert_at is not None:
        try:
            insert_at = int(insert_at)
        except (TypeError, ValueError):
            insert_at = "end"
    try:
        order_index = int(data.get("order_index", 0))
    except (TypeError, ValueError):
        order_index = 0
    try:
        mps = float(data.get("max_performance_score", 1.0))
    except (TypeError, ValueError):
        mps = 1.0
    try:
        result = db.v2_create_task_pool_entry_and_assign_student(
            user_id,
            text=text,
            order_index=order_index,
            max_performance_score=mps,
            insert_at=insert_at,
            target_profile=payload.get("target_profile", _TASK_TEMPLATE_DEFAULT_PROFILE),
            level=payload.get("level", _TASK_TEMPLATE_DEFAULT_LEVEL),
            step_in_level=payload.get("step_in_level", _TASK_TEMPLATE_DEFAULT_STEP),
            is_active=payload.get("is_active", True),
            replaces_task_id=payload.get("replaces_task_id"),
        )
        return jsonify(result), 201
    except ValueError as ve:
        code = str(ve)
        if code in ("INVALID_TARGET_PROFILE", "INVALID_LEVEL", "INVALID_STEP_IN_LEVEL", "INVALID_TEXT"):
            field_map = {
                "INVALID_TARGET_PROFILE": "target_profile",
                "INVALID_LEVEL": "level",
                "INVALID_STEP_IN_LEVEL": "step_in_level",
                "INVALID_TEXT": "text",
            }
            field = field_map.get(code, "field")
            return jsonify({"code": code, "error": code, "details": {field: code}}), 400
        return jsonify({"error": str(ve)}), 400
    except Exception as err:
        if _is_duplicate_active_slot_error(err):
            return jsonify({
                "code": "DUPLICATE_ACTIVE_SLOT",
                "error": "Active template for this target_profile/level/step_in_level already exists",
                "details": {
                    "target_profile": payload.get("target_profile"),
                    "level": payload.get("level"),
                    "step_in_level": payload.get("step_in_level"),
                },
            }), 400
        logger.warning("create-pool-and-assign failed for user %s: %s", user_id, err, exc_info=True)
        return jsonify({"error": "create-pool-and-assign failed", "detail": str(err)}), 503


@v2_bp.route("/admin/students/<user_id>/tasks/<task_id>", methods=["PUT"])
@v2_bp.route("/admin/students/<user_id>/task-warm-up/<task_id>", methods=["PUT"])
@require_admin
def v2_admin_student_tasks_update(user_id, task_id):
    data = request.get_json() or {}
    try:
        row = db.v2_update_student_task(task_id, data)
        return jsonify({"task": row}), 200
    except Exception as err:
        logger.warning("student tasks PUT update failed: %s", err, exc_info=True)
        return jsonify({"error": "Update failed.", "detail": str(err)}), 503


@v2_bp.route("/admin/students/<user_id>/tasks/<task_id>", methods=["DELETE"])
@v2_bp.route("/admin/students/<user_id>/task-warm-up/<task_id>", methods=["DELETE"])
@require_admin
def v2_admin_student_tasks_delete(user_id, task_id):
    try:
        db.v2_delete_student_task(task_id)
        return jsonify({"status": "ok"}), 200
    except Exception as err:
        logger.warning("student tasks DELETE failed: %s", err, exc_info=True)
        return jsonify({"error": "Delete failed.", "detail": str(err)}), 503


@v2_bp.route("/admin/students/<user_id>/task-focus", methods=["GET"])
@v2_bp.route("/admin/students/<user_id>/focus-tasks", methods=["GET"])
@require_admin
def v2_admin_task_focus_removed(user_id):
    """Focus tasks removed; returns empty lists so older admin clients do not crash."""
    _ = user_id
    return jsonify({"task_focus": [], "focus_tasks": []}), 200


@v2_bp.route("/admin/students/<user_id>/task-focus/create-pool-and-assign", methods=["POST"])
@v2_bp.route("/admin/students/<user_id>/focus-tasks/create-pool-and-assign", methods=["POST"])
@require_admin
def v2_admin_task_focus_create_removed(user_id):
    return jsonify({
        "error": "removed",
        "message": "Focus tasks were removed. Use POST .../tasks/create-pool-and-assign instead.",
    }), 410


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


# ---------- Admin: AI Coach Suggestions (per-student ChatGPT-like assistant) ----------

def _build_student_context_for_ai(user_id: str) -> str:
    """Gather all available student data into a text block for the AI system prompt."""
    parts = []

    # Basic info
    email = db.get_user_email_from_auth(user_id)
    details = db.v2_get_student_details(user_id) or {}
    name = details.get("name") or email or user_id
    parts.append(f"Student: {name} ({email})")

    # Speaker profile
    sp = db.v2_get_speaker_profile(user_id)
    if sp:
        sp_lines = []
        for key in ("main_goal", "motivation", "strong_points", "weak_points", "charismatic_traits", "hobbies_interests", "personality_type", "coach_notes"):
            val = sp.get(key)
            if val:
                sp_lines.append(f"  {key}: {val}")
        if sp_lines:
            parts.append("Speaker Profile:\n" + "\n".join(sp_lines))

    # Measured metrics
    metrics = db.v2_get_admin_measured_metrics_snapshot(user_id)
    if metrics:
        latest = metrics.get("latest") or {}
        baselines = metrics.get("baselines") or {}
        m_lines = []
        for key in ("wpm", "pause_ms", "dynamic_db", "emphasis_per_min", "energy_ratio", "pitch_center_st", "voiced_duration_sec"):
            val = latest.get(key)
            if val is not None:
                baseline_key = f"baseline_{key}"
                baseline_val = baselines.get(baseline_key)
                line = f"  {key}: {val}"
                if baseline_val is not None:
                    line += f" (baseline: {baseline_val})"
                m_lines.append(line)
        if metrics.get("wpm_high"):
            m_lines.append("  ⚠ WPM > 110 (speaking too fast)")
        if m_lines:
            parts.append("Latest Metrics:\n" + "\n".join(m_lines))

    # Coaching memory
    cm = db.v2_get_student_coaching_memory(user_id)
    if cm:
        cm_lines = []
        scores = cm.get("last_5_scores")
        if scores:
            cm_lines.append(f"  Last 5 scores: {scores}")
        issues = cm.get("recurring_issues")
        if issues:
            cm_lines.append(f"  Recurring issues: {', '.join(issues)}")
        if cm_lines:
            parts.append("Coaching Memory:\n" + "\n".join(cm_lines))

    # Recent sessions (last 5)
    sessions = db.v2_get_sessions_with_previews(user_id, limit=5)
    if sessions:
        s_lines = []
        for s in sessions[:5]:
            date = s.get("created_at", "")[:10]
            score = s.get("score")
            status = s.get("status", "")
            task = (
                s.get("session_task_text")
                or s.get("selected_task_title")
                or s.get("selected_task_id")
                or ""
            )
            preview = s.get("recording_preview") or {}
            wpm = preview.get("words_per_minute")
            line = f"  {date}: status={status}"
            if score is not None:
                line += f", score={score}"
            if task:
                line += f", task={task}"
            if wpm:
                line += f", wpm={wpm}"
            s_lines.append(line)
        parts.append("Recent Sessions:\n" + "\n".join(s_lines))

    # Sniper profile (realtime level/step)
    sniper = db.get_sniper_profile_payload(user_id)
    if sniper:
        level = sniper.get("realtime_level")
        step = sniper.get("realtime_step")
        if level is not None or step is not None:
            parts.append(f"Sniper Profile: level={level}, step={step}")

    return "\n\n".join(parts) if parts else f"Student ID: {user_id} (no profile data available yet)"


def _generate_assignment_prefill_for_user(user_id: str, fallback_task_text: str) -> dict:
    """Best-effort AI prefill for task/email/script drafts; deterministic fallback on errors."""
    fallback_task = (fallback_task_text or "").strip() or "Continue with your next speaking task based on recent feedback."
    fallback_message = "Short update: keep building clarity and pacing using your latest report guidance."
    fallback_script = "1) Praise one improvement. 2) Name one focus for next recording. 3) Encourage consistency."
    try:
        from services.openai_service import openai_service

        student_context = _build_student_context_for_ai(user_id)
        result = openai_service.generate_coach_suggestions(
            student_context=student_context,
            conversation_history=[],
            user_message=(
                "Create the next assignment for this student. "
                "Return all three sections: homework message, task suggestion, video script."
            ),
        )
        ai_message = (result.get("homework_message") or "").strip()
        ai_task = (result.get("task_suggestion") or "").strip()
        ai_script = (result.get("video_script") or "").strip()
        return {
            "ai_draft_message": ai_message or fallback_message,
            "ai_suggested_task_text": ai_task or fallback_task,
            "ai_draft_video_script": ai_script or fallback_script,
            "raw_text": (result.get("raw_text") or "").strip() or None,
        }
    except Exception as e:
        logger.warning("AI assignment prefill failed for user=%s: %s", user_id, e)
        return {
            "ai_draft_message": fallback_message,
            "ai_suggested_task_text": fallback_task,
            "ai_draft_video_script": fallback_script,
            "raw_text": None,
        }


@v2_bp.route("/admin/students/<user_id>/coach-suggestions", methods=["POST"])
@require_admin
def v2_admin_coach_suggestions(user_id):
    """AI coach assistant: send a message, get suggestions for homework/task/video.
    Body: { "message": "..." }
    Returns: { homework_message, task_suggestion, video_script, raw_text }
    Conversation history is stored per-student."""
    try:
        from services.openai_service import openai_service

        body = request.get_json(silent=True) or {}
        user_message = (body.get("message") or "").strip()
        if not user_message:
            return jsonify({"code": "INVALID_INPUT", "error": "message is required"}), 400
        if len(user_message) > 5000:
            return jsonify({"code": "INVALID_INPUT", "error": "message must be at most 5000 characters"}), 400

        # Load existing conversation history
        conv = db.get_coach_ai_conversation(user_id)
        history = []
        if conv and conv.get("messages"):
            messages_raw = conv["messages"]
            if isinstance(messages_raw, str):
                history = json.loads(messages_raw)
            else:
                history = messages_raw

        # Build student context
        student_context = _build_student_context_for_ai(user_id)

        # Generate suggestions
        result = openai_service.generate_coach_suggestions(
            student_context=student_context,
            conversation_history=history,
            user_message=user_message,
        )

        if result.get("error"):
            return jsonify({"code": "AI_ERROR", "error": result["error"]}), 500

        # Append user message + assistant response to history
        now = datetime.now(timezone.utc).isoformat()
        history.append({"role": "user", "content": user_message, "timestamp": now})
        history.append({"role": "assistant", "content": result["raw_text"], "timestamp": now})

        # Save conversation
        db.upsert_coach_ai_conversation(user_id, history)

        return jsonify({
            "status": "ok",
            "homework_message": result["homework_message"],
            "task_suggestion": result["task_suggestion"],
            "video_script": result["video_script"],
            "raw_text": result["raw_text"],
        }), 200

    except Exception as e:
        logger.error("coach-suggestions failed for %s: %s", user_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "INTERNAL_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/coach-suggestions/history", methods=["GET", "DELETE"])
@require_admin
def v2_admin_coach_suggestions_history(user_id):
    """GET: return conversation history. DELETE: clear conversation history."""
    try:
        if request.method == "DELETE":
            db.clear_coach_ai_conversation(user_id)
            return jsonify({"status": "ok", "message": "Conversation cleared"}), 200

        conv = db.get_coach_ai_conversation(user_id)
        messages = []
        if conv and conv.get("messages"):
            messages_raw = conv["messages"]
            if isinstance(messages_raw, str):
                messages = json.loads(messages_raw)
            else:
                messages = messages_raw

        return jsonify({
            "status": "ok",
            "user_id": user_id,
            "messages": messages,
            "updated_at": conv.get("updated_at") if conv else None,
        }), 200

    except Exception as e:
        logger.error("coach-suggestions/history failed for %s: %s", user_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "INTERNAL_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/sessions/<session_id>/insight-audit", methods=["PATCH"])
@require_admin
def v2_admin_insight_audit(user_id, session_id):
    try:
        body = request.get_json(silent=True) or {}
        is_audited = body.get("is_insight_audited")
        corrected = body.get("coach_corrected_insight")
        reason_chip = (body.get("reason_chip") or "").strip() or None
        custom_reason = (body.get("custom_reason") or "").strip() or None
        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        updates = {}
        if is_audited is not None:
            updates["is_insight_audited"] = bool(is_audited)
        if corrected is not None:
            updates["coach_corrected_insight"] = (corrected or "").strip() or None
        if not updates:
            return jsonify({"code": "INVALID_INPUT", "error": "Nothing to update"}), 400
        db.v2_update_session(session_id, user_id, updates)
        if reason_chip or custom_reason or corrected is not None:
            db.create_admin_annotation_event(
                user_id=user_id,
                session_id=session_id,
                section_type="post_hoc_audit",
                field_name="coach_insight",
                ai_original_text=(session.get("coach_insight") or "").strip() or None,
                coach_final_text=(updates.get("coach_corrected_insight") or "").strip() or None,
                reason_chip=reason_chip,
                custom_reason=custom_reason,
                created_by=request.user_id,
            )
        return jsonify({"status": "ok", "session_id": session_id, **updates}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/profile-classification", methods=["PATCH"])
@require_admin
def v2_admin_profile_classification_override(user_id):
    try:
        from services.student_profile_service import refresh_student_profile_state

        body = request.get_json(silent=True) or {}
        reason_chip = (body.get("reason_chip") or "").strip() or None
        refresh_student_profile_state(user_id)
        current = db.get_sniper_profile(user_id) or {}

        # Partial updates: omitting a key preserves the existing DB value (do not clear override by accident).
        override_profile = current.get("coach_override_profile")
        if "coach_override_profile" in body:
            raw = body.get("coach_override_profile")
            if raw is None:
                override_profile = None
            else:
                s = str(raw).strip()
                override_profile = s or None

        justification = current.get("profile_override_justification")
        if "profile_override_justification" in body:
            raw_j = body.get("profile_override_justification")
            if raw_j is None:
                justification = None
            else:
                sj = str(raw_j).strip()
                justification = sj or None

        updated = db.upsert_student_profile_fields(
            user_id,
            {
                "coach_override_profile": override_profile,
                "profile_override_justification": justification,
            },
        )
        db.create_admin_annotation_event(
            user_id=user_id,
            session_id=None,
            section_type="classification",
            field_name="behavioral_profile",
            ai_original_text=(updated.get("behavioral_profile") or "").strip() or None,
            coach_final_text=override_profile,
            reason_chip=reason_chip,
            custom_reason=justification,
            created_by=request.user_id,
        )
        lp = _learning_profile_payload(updated)
        return jsonify(
            {
                "status": "ok",
                "display_profile": lp["display_profile"],
                "display_justification": lp["display_justification"],
                "learning_profile": lp,
                "profile": updated,
            }
        ), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/stage-override", methods=["PATCH"])
@require_admin
def v2_admin_stage_override(user_id):
    try:
        from services.student_profile_service import refresh_student_profile_state

        body = request.get_json(silent=True) or {}
        raw_stage = body.get("coach_override_stage")
        justification = (body.get("stage_override_justification") or "").strip() or None
        reason_chip = (body.get("reason_chip") or "").strip() or None
        if raw_stage is None:
            override_stage = None
        else:
            try:
                override_stage = int(raw_stage)
            except (TypeError, ValueError):
                return jsonify({"code": "INVALID_INPUT", "error": "coach_override_stage must be integer 1..5 or null"}), 400
            if override_stage < 1 or override_stage > 5:
                return jsonify({"code": "INVALID_INPUT", "error": "coach_override_stage must be integer 1..5 or null"}), 400
        refresh_student_profile_state(user_id)
        updated = db.upsert_student_profile_fields(
            user_id,
            {
                "coach_override_stage": override_stage,
                "stage_override_justification": justification,
            },
        )
        db.create_admin_annotation_event(
            user_id=user_id,
            session_id=None,
            section_type="classification",
            field_name="stage",
            ai_original_text=str(updated.get("computed_stage")) if updated.get("computed_stage") is not None else None,
            coach_final_text=str(override_stage) if override_stage is not None else None,
            reason_chip=reason_chip,
            custom_reason=justification,
            created_by=request.user_id,
        )
        display_stage = override_stage or updated.get("computed_stage") or 1
        return jsonify({"status": "ok", "display_stage": int(display_stage), "profile": updated}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


def _draft_payload(row):
    payload = row.get("draft_payload")
    return payload if isinstance(payload, dict) else {}


def _video_pipeline_enabled() -> bool:
    return bool(getattr(config, "COPILOT_VIDEO_PIPELINE_ENABLED", False))


def _pipeline_secret_matches() -> bool:
    secret = (getattr(config, "COPILOT_VIDEO_PIPELINE_SECRET", None) or "").strip()
    if not secret:
        return False
    provided = (request.headers.get("X-Internal-Secret") or "").strip()
    return provided == secret


def _pipeline_phase_from_mode(script_mode: str) -> str:
    return "uploading" if script_mode == "full_video_override" else "running_tts"


def _is_pipeline_running(row: dict | None) -> bool:
    if not row:
        return False
    return str(row.get("pipeline_status") or "").strip().lower() in _PIPELINE_RUNNING_STATES


def _queue_video_pipeline_for_draft(row: dict, *, user_id: str, actor_id: str | None) -> tuple[dict | None, str]:
    payload = _normalize_copilot_payload(row)
    script_mode = resolve_script_mode(payload)
    manifest = build_script_manifest(row, payload, script_mode)
    pipeline_job_id = str(uuid.uuid4())
    updated = db.queue_admin_student_send_draft_pipeline(
        draft_id=str(row.get("id") or ""),
        user_id=user_id,
        pipeline_job_id=pipeline_job_id,
        script_mode=script_mode,
        script_manifest=manifest,
        created_by=actor_id,
    )
    return updated, pipeline_job_id


def _signed_feedback_video_url(storage_path: str, expires_in: int | None = None) -> str | None:
    if not storage_path:
        return None
    ttl = int(expires_in or (48 * 3600))
    return presigned_get_coach_object(config.COACH_FEEDBACK_VIDEO_BUCKET, storage_path, ttl, supabase_db=db)


def _storage_uri(bucket: str, path: str) -> str:
    return f"storage://{bucket}/{path.lstrip('/')}"


def _finalize_pipeline_delivery_for_row(
    *,
    row: dict,
    storage_path: str,
    script_manifest: dict | None,
    approved_by: str,
) -> tuple[dict | None, dict, str | None]:
    payload = _normalize_copilot_payload(row)
    final_message = (
        payload.get("email_draft")
        or payload.get("email_message")
        or payload.get("homework_comment")
        or payload.get("ai_email_draft")
        or row.get("ai_draft_message")
        or ""
    )
    student_email = (db.get_user_email_from_auth(row.get("user_id")) or "").strip()
    if not student_email:
        raise ValueError("Student has no email in auth")
    signed_video_url = _signed_feedback_video_url(storage_path, expires_in=48 * 3600)
    delivery, send_err = _deliver_homework_assignment_core(
        row.get("user_id"),
        student_email,
        video_url=signed_video_url,
        video_description=(final_message or "").strip() or None,
        video_bucket=config.COACH_FEEDBACK_VIDEO_BUCKET,
        video_storage_path=storage_path.lstrip("/"),
    )
    if send_err:
        raise RuntimeError(send_err)

    task_sync = _first_non_empty(
        payload.get("task_draft"),
        payload.get("task_text"),
        row.get("master_task_text"),
        payload.get("ai_task_suggestion"),
        row.get("ai_suggested_task_text"),
    )
    try:
        db.v2_apply_coach_homework_task_text(row.get("user_id"), task_sync)
    except Exception as task_sync_err:
        logger.warning("pipeline finalize: task sync failed user_id=%s: %s", row.get("user_id"), task_sync_err)
    updated = db.mark_admin_student_send_draft_pipeline_sent(
        draft_id=str(row.get("id") or ""),
        user_id=str(row.get("user_id") or ""),
        approved_by=approved_by,
        feedback_video_storage_path=storage_path,
        script_manifest=script_manifest or {},
    )
    return updated, delivery.get("email") or {}, task_sync


def _first_non_empty(*values):
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _value_hash(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize_copilot_payload(row: dict, payload: dict | None = None) -> dict:
    """Canonical payload contract for Training Studio drafts.

    Editable fields:
      - email_draft
      - task_draft
      - script_draft
    Immutable AI baselines:
      - ai_email_draft
      - ai_task_suggestion
      - ai_script_draft
    Back-compat aliases:
      - video_script mirrors script_draft
    """
    base = dict(payload if isinstance(payload, dict) else _draft_payload(row))

    ai_email = _first_non_empty(base.get("ai_email_draft"), row.get("ai_draft_message"))
    ai_task = _first_non_empty(
        base.get("ai_task_suggestion"),
        row.get("ai_suggested_task_text"),
        row.get("master_task_text"),
    )
    ai_script = _first_non_empty(base.get("ai_script_draft"), row.get("ai_draft_video_script"))

    email_draft = _first_non_empty(
        base.get("email_draft"),
        base.get("email_message"),
        base.get("homework_comment"),
        ai_email,
    )
    task_draft = _first_non_empty(
        base.get("task_draft"),
        base.get("task_text"),
        ai_task,
        row.get("master_task_text"),
    )
    script_draft = _first_non_empty(
        base.get("script_draft"),
        base.get("video_script"),
        ai_script,
    )

    base["ai_email_draft"] = ai_email
    base["ai_task_suggestion"] = ai_task
    base["ai_script_draft"] = ai_script
    base["email_draft"] = email_draft
    base["task_draft"] = task_draft
    base["script_draft"] = script_draft
    # Keep alias in sync for older clients that still read/write video_script.
    base["video_script"] = script_draft
    # Optional coach video link (same as send-assignment video_url for step-0 media).
    if "video_url" in base:
        base["video_url"] = validate_video_url(base.get("video_url"))
    return base


def _normalize_draft_rows_in_db(rows: list[dict]) -> list[dict]:
    """Idempotently normalize existing draft rows to canonical payload shape."""
    normalized_rows = []
    for row in rows:
        original = _draft_payload(row)
        normalized = _normalize_copilot_payload(row, original)
        if normalized != original:
            try:
                update_body = {
                    "draft_payload": normalized,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                task_text = _first_non_empty(normalized.get("task_draft"))
                if task_text:
                    update_body["master_task_text"] = task_text
                db.client.table("admin_student_send_drafts").update(update_body).eq("id", row.get("id")).execute()
                row = dict(row)
                row["draft_payload"] = normalized
                if task_text:
                    row["master_task_text"] = task_text
            except Exception as norm_err:
                logger.warning("copilot normalize row failed id=%s: %s", row.get("id"), norm_err)
        normalized_rows.append(row)
    return normalized_rows


def _draft_state_ui(row):
    payload = _draft_payload(row)
    state = payload.get("state")
    if state in ("Draft", "Ready", "Sent"):
        return state
    status = str(row.get("status") or "").lower()
    if status == "sent":
        return "Sent"
    if payload.get("approved_at") or payload.get("good_as_is") is True or payload.get("corrected_insight"):
        return "Ready"
    return "Draft"


def _effective_session_id_for_copilot_draft(row: dict | None, user_id: str | None = None) -> str | None:
    """Draft rows may omit session_id; Training Studio clients require a session id to send.

    Resolution order: draft column → draft_payload.metadata.session_id → last completed session
    → active homework session → any latest session by created_at.
    """
    if row and row.get("session_id"):
        return str(row["session_id"])
    uid = user_id or (str(row.get("user_id")) if row and row.get("user_id") else None)
    if not uid:
        return None
    if row:
        p = _draft_payload(row)
        meta = p.get("metadata") if isinstance(p.get("metadata"), dict) else {}
        mid = meta.get("session_id")
        if mid and _is_valid_uuid(str(mid)):
            return str(mid)
    last_done = db.v2_get_last_completed_session(uid) or {}
    if last_done.get("id"):
        return str(last_done["id"])
    active = db.v2_get_active_homework_session(uid)
    if active and active.get("id"):
        return str(active["id"])
    return db.v2_get_latest_session_id_for_user(uid)


def _draft_has_prefill_content(row: dict | None) -> bool:
    if not row:
        return False
    payload = _normalize_copilot_payload(row)
    for key in ("task_draft", "email_draft", "script_draft", "ai_task_suggestion", "ai_email_draft", "ai_script_draft"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _copilot_draft_generation_status(user_id: str, rows: list[dict]) -> dict:
    """Expose draft generation state so UI can differentiate pending vs truly empty."""
    latest_completed = db.v2_get_last_completed_session_full(user_id) or {}
    latest_completed_id = str(latest_completed.get("id") or "").strip() or None
    latest_proc_status = str(latest_completed.get("recording_1_processing_status") or "").strip().lower() or None

    if latest_completed_id:
        matching = [
            r for r in (rows or [])
            if _effective_session_id_for_copilot_draft(r, user_id) == latest_completed_id
        ]
        if matching:
            return {
                "draft_generation_status": "ready" if _draft_has_prefill_content(matching[0]) else "pending",
                "draft_generation_session_id": latest_completed_id,
            }
        if latest_proc_status == "failed":
            return {
                "draft_generation_status": "failed",
                "draft_generation_session_id": latest_completed_id,
            }
        return {
            "draft_generation_status": "pending",
            "draft_generation_session_id": latest_completed_id,
        }

    active = db.v2_get_active_homework_session(user_id) or {}
    active_status = str(active.get("status") or "").strip().lower()
    if active_status in {"completing_from_recording_1", "task_block", "final_task_ready", "post_questions"}:
        return {
            "draft_generation_status": "pending",
            "draft_generation_session_id": str(active.get("id") or "") or None,
        }

    if rows and _draft_has_prefill_content(rows[0]):
        return {
            "draft_generation_status": "ready",
            "draft_generation_session_id": _effective_session_id_for_copilot_draft(rows[0], user_id),
        }
    return {
        "draft_generation_status": "not_started",
        "draft_generation_session_id": None,
    }


def _serialize_copilot_draft(row):
    payload = _normalize_copilot_payload(row)
    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    uid = str(row.get("user_id") or "") or None
    return {
        "id": str(row.get("id") or ""),
        "student_id": str(row.get("user_id") or ""),
        "session_id": _effective_session_id_for_copilot_draft(row, uid),
        "status": _draft_state_ui(row),
        "cohort_profile": row.get("cohort_profile"),
        "cohort_stage": row.get("cohort_stage"),
        "score_for_display": meta.get("score_for_display") if meta else None,
        # AI originals (baselines for DPO — what the AI suggested)
        "ai_insight": payload.get("ai_insight"),
        "ai_grade_draft": payload.get("ai_grade_draft"),
        "ai_comment_draft": payload.get("ai_comment_draft"),
        "ai_email_draft": payload.get("ai_email_draft") or row.get("ai_draft_message"),
        "ai_task_suggestion": payload.get("ai_task_suggestion") or row.get("ai_suggested_task_text"),
        "ai_script_draft": payload.get("ai_script_draft") or row.get("ai_draft_video_script"),
        # Current draft values (admin-editable — start as AI draft, change on override)
        "grade_draft": payload.get("grade_draft"),
        "comment_draft": payload.get("comment_draft"),
        "task_draft": payload.get("task_draft"),
        "email_draft": payload.get("email_draft"),
        "script_draft": payload.get("script_draft"),
        "video_url": payload.get("video_url"),
        # Audit state
        "corrected_insight": payload.get("corrected_insight"),
        "good_as_is": payload.get("good_as_is"),
        "reason_chip_required": bool(payload.get("reason_chip_required", False)),
        "metadata": meta or None,
        "script_mode": row.get("script_mode") or payload.get("script_mode"),
        "script_manifest": row.get("script_manifest") if isinstance(row.get("script_manifest"), dict) else {},
        "feedback_video_storage_path": row.get("feedback_video_storage_path"),
        "pipeline_status": row.get("pipeline_status"),
        "pipeline_error": row.get("pipeline_error"),
        "pipeline_job_id": row.get("pipeline_job_id"),
        "pipeline_started_at": row.get("pipeline_started_at"),
        "pipeline_finished_at": row.get("pipeline_finished_at"),
    }


def _pick_student_draft(user_id: str, *, session_id: str | None = None, draft_id: str | None = None, include_sent: bool = False):
    if draft_id:
        row = db.get_admin_student_send_draft(draft_id, user_id)
        if row and (include_sent or str(row.get("status") or "").lower() != "sent"):
            return row
        if row and include_sent:
            return row
    q = db.client.table("admin_student_send_drafts").select("*").eq("user_id", user_id).order("updated_at", desc=True).order("created_at", desc=True)
    rows = q.limit(20).execute().data or []
    search_space = rows
    if session_id:
        filtered = [
            r
            for r in rows
            if str(r.get("session_id") or "") == session_id
            or _effective_session_id_for_copilot_draft(r, user_id) == session_id
        ]
        # Stale/wrong session_id from the client must not hide editable drafts.
        search_space = filtered if filtered else rows
    if include_sent and search_space:
        return search_space[0]
    for row in search_space:
        if str(row.get("status") or "").lower() != "sent":
            return row
    return None


def _cohort_id(profile: str, stage: int) -> str:
    return f"{profile}::{int(stage)}"


def _parse_cohort_id(raw: str):
    text = (raw or "").strip()
    if "::" in text:
        profile, stage = text.rsplit("::", 1)
    elif "__" in text:
        profile, stage = text.rsplit("__", 1)
    else:
        return text, None
    try:
        return profile, int(stage)
    except (TypeError, ValueError):
        return profile, None


def _student_cohort_from_state(state: dict | None) -> tuple[str, int]:
    """Profile bucket and stage (1–5) from student_profile / sniper row or refresh payload."""
    state = state or {}
    p = (
        (state.get("coach_override_profile") or "").strip()
        or (state.get("behavioral_profile") or "").strip()
        or "Unclassified"
    )
    try:
        raw = state.get("coach_override_stage")
        if raw is None:
            raw = state.get("computed_stage")
        stg = int(raw) if raw is not None else 1
    except (TypeError, ValueError):
        stg = 1
    return p, max(1, min(5, stg))


def _copilot_backfill_draft_row_for_user(user_id: str) -> dict:
    """Build one admin_student_send_drafts insert dict from profile + last completed session."""
    from services.student_profile_service import refresh_student_profile_state

    refresh_student_profile_state(user_id)
    sp = db.get_sniper_profile(user_id) or {}
    profile = (
        (sp.get("coach_override_profile") or "").strip()
        or (sp.get("behavioral_profile") or "").strip()
        or "Unclassified"
    )
    try:
        raw_stage = sp.get("coach_override_stage")
        if raw_stage is None:
            raw_stage = sp.get("computed_stage")
        stage = int(raw_stage) if raw_stage is not None else 1
    except (TypeError, ValueError):
        stage = 1
    stage = max(1, min(5, stage))

    sess = db.v2_get_last_completed_session_full(user_id)
    session_id = str(sess["id"]) if sess and sess.get("id") else None

    coach_insight = ""
    report_comment = ""
    report_grade = None
    score_for_display = None
    ai_draft_grade = None
    ai_draft_comment = None
    context_short = ""
    if sess:
        coach_insight = (sess.get("coach_insight") or "").strip()
        report_comment = (sess.get("report_comment") or "").strip()
        report_grade = sess.get("report_grade")
        score_for_display = sess.get("score_for_display")
        ai_draft_grade = sess.get("ai_draft_grade")
        ai_draft_comment = (sess.get("ai_draft_comment") or "").strip() or None
        context_short = (sess.get("context_short") or "").strip()

    task_text = ""
    if sess:
        task_text = (sess.get("session_task_text") or "").strip()
    if not task_text and sess and sess.get("selected_task_id"):
        try:
            t = (
                db.client.table("tasks")
                .select("text")
                .eq("id", sess["selected_task_id"])
                .limit(1)
                .execute()
            )
            if t.data:
                task_text = (t.data[0].get("text") or "").strip()
        except Exception:
            pass
    if not task_text:
        lr = db.v2_get_last_report_for_user(user_id)
        if lr and lr.get("report_text"):
            rt = (lr["report_text"] or "").strip()
            task_text = (rt[:240] + "...") if len(rt) > 240 else rt
    if not task_text:
        task_text = (
            "Follow-up: review your last homework feedback and continue with your next speaking task."
        )

    master_task_text = task_text[:8000]

    reference_examples = db.list_reference_transcripts_for_copilot(user_id=user_id, limit=4)
    reference_lines = []
    reference_ids = []
    for ref in reference_examples:
        rid = str(ref.get("id") or "").strip()
        if rid:
            reference_ids.append(rid)
        title = (ref.get("title") or "").strip() or "Reference video"
        tags = ref.get("tags") if isinstance(ref.get("tags"), list) else []
        tag_text = f" [{', '.join([str(t).strip() for t in tags if str(t).strip()])}]" if tags else ""
        transcript = (ref.get("transcript_text") or "").strip()
        if transcript:
            reference_lines.append(f"- {title}{tag_text}: {transcript[:360]}")
    reference_transcript_context = "\n".join(reference_lines).strip()

    # --- Generate AI pre-fills for all draft fields ---
    from services.openai_service import openai_service

    # AI grade + comment: prefer session values, generate if missing
    if ai_draft_grade is None or not ai_draft_comment:
        try:
            score_100 = None
            if score_for_display is not None:
                try:
                    score_100 = int(score_for_display)
                except (TypeError, ValueError):
                    pass
            gc = openai_service.generate_admin_grade_comment_draft(
                context_short=context_short,
                coach_insight=coach_insight,
                score_for_display_100=score_100,
            )
            if ai_draft_grade is None:
                ai_draft_grade = gc.get("grade")
            if not ai_draft_comment:
                ai_draft_comment = gc.get("comment")
        except Exception:
            pass

    # Use AI draft as the starting draft value (admin can override)
    grade_draft = report_grade if report_grade is not None else ai_draft_grade
    comment_draft = report_comment or ai_draft_comment or None

    student_details = db.v2_get_student_details(user_id) or {}
    student_name = (student_details.get("name") or "").strip() or (db.get_user_email_from_auth(user_id) or "Student")
    score_int = int(score_for_display) if score_for_display is not None else None

    # AI task suggestion first — email + script should reference this, not only the legacy session task.
    ai_task_suggestion = None
    try:
        ai_task_suggestion = openai_service.generate_next_task_suggestion(
            context_short=context_short,
            coach_insight=coach_insight,
            current_task_text=master_task_text,
            score_for_display_100=score_int,
            behavioral_profile=profile,
            stage=stage,
            reference_transcript_context=reference_transcript_context,
        )
    except Exception:
        pass

    display_task = (ai_task_suggestion or "").strip() or master_task_text
    display_task = display_task[:8000]

    # AI email draft (after task so body matches suggested homework)
    ai_email_draft = None
    try:
        ai_email_draft = openai_service.generate_student_email_draft(
            student_name=student_name,
            coach_insight=coach_insight,
            score_for_display_100=score_int,
            grade=ai_draft_grade,
            comment=ai_draft_comment or "",
            task_text=display_task,
            reference_transcript_context=reference_transcript_context,
        )
    except Exception:
        pass

    # AI video script — was missing from draft_payload before, so Training Studio showed empty script fields.
    ai_script_draft = None
    try:
        ai_script_draft = openai_service.generate_video_script_draft(
            student_name=student_name,
            coach_insight=coach_insight,
            task_text=display_task,
            score_for_display_100=score_int,
            reference_transcript_context=reference_transcript_context,
        )
    except Exception:
        pass

    meta = {
        "backfilled_at": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
    }
    if score_for_display is not None:
        try:
            meta["score_for_display"] = float(score_for_display)
        except (TypeError, ValueError):
            meta["score_for_display"] = score_for_display
    if reference_ids:
        meta["reference_video_ids"] = reference_ids
        meta["reference_transcript_context_used"] = True

    payload = {
        "state": "Draft",
        "ai_insight": coach_insight or None,
        "grade_draft": grade_draft,
        "comment_draft": comment_draft,
        # Editable fields start as AI output so corrections become DPO pairs vs ai_* baselines.
        "task_draft": display_task,
        "email_draft": ai_email_draft,
        "script_draft": ai_script_draft,
        "video_script": ai_script_draft,
        "ai_grade_draft": ai_draft_grade,
        "ai_comment_draft": ai_draft_comment,
        "ai_email_draft": ai_email_draft,
        "ai_task_suggestion": ai_task_suggestion or display_task,
        "ai_script_draft": ai_script_draft,
        "metadata": meta,
    }

    return {
        "user_id": user_id,
        "session_id": session_id,
        "cohort_profile": profile,
        "cohort_stage": stage,
        "master_task_text": display_task,
        "ai_suggested_task_text": ai_task_suggestion or display_task,
        "ai_draft_message": ai_email_draft,
        "ai_draft_video_script": ai_script_draft,
        "draft_payload": payload,
        "status": "pending",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@v2_bp.route("/admin/copilot/annotation-chips", methods=["GET", "POST"])
@v2_bp.route("/admin/acoustic-dojo/annotation-chips", methods=["GET"])
@require_admin
def v2_admin_copilot_annotation_chips():
    """Reason chips used by copilot audit/override actions."""
    chips = [
        {"chip_key": "misread_context", "label": "Misread context", "section": "insight"},
        {"chip_key": "overly_generic", "label": "Too generic", "section": "insight"},
        {"chip_key": "missed_specific_issue", "label": "Missed specific issue", "section": "insight"},
        {"chip_key": "tone_mismatch", "label": "Tone mismatch", "section": "insight"},
        {"chip_key": "profile_incorrect", "label": "Profile incorrect", "section": "classification"},
        {"chip_key": "stage_incorrect", "label": "Stage incorrect", "section": "classification"},
    ]
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        chip_key = (body.get("chip_key") or "").strip()
        label = (body.get("label") or "").strip()
        if not chip_key or not label:
            return jsonify({"code": "INVALID_INPUT", "error": "chip_key and label are required"}), 400
        chip = {
            "chip_key": chip_key,
            "label": label,
            "description": (body.get("description") or "").strip() or None,
            "is_active": bool(body.get("is_active", True)),
        }
        return jsonify({"status": "ok", "chip": chip}), 201
    return jsonify({"annotation_chips": chips, "chips": chips}), 200


@v2_bp.route("/admin/acoustic-dojo/next-clips", methods=["GET"])
@require_admin
def v2_admin_acoustic_dojo_next_clips():
    """Audio-only queue for acoustic dojo (latest recordings as clips)."""
    try:
        limit_raw = request.args.get("limit")
        source_type = str(request.args.get("source_type", "student")).strip().lower()
        try:
            limit = max(1, min(200, int(limit_raw))) if limit_raw is not None else 6
        except (TypeError, ValueError):
            limit = 6
        if source_type == "external":
            return jsonify({"clips": [], "count": 0, "streak": 0, "today_count": 0, "leaderboard": []}), 200
        rows = (
            db.client.table("recordings")
            .select("id, user_id, session_v2_id, audio_url, duration, duration_seconds, created_at")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        )
        clips = []
        for row in rows:
            dur = row.get("duration_seconds")
            if dur is None:
                dur = row.get("duration")
            try:
                dur_f = float(dur) if dur is not None else None
            except (TypeError, ValueError):
                dur_f = None
            end_sec = dur_f if dur_f is not None else 10.0
            start_sec = max(0.0, end_sec - 10.0)
            clips.append(
                {
                    "clip_id": str(row.get("id") or ""),
                    "source_type": "student",
                    "audio_url": row.get("audio_url"),
                    "duration_sec": dur_f,
                    "student_id": row.get("user_id"),
                    "session_id": row.get("session_v2_id"),
                    "source_metadata": {
                        "recording_id": row.get("id"),
                        "created_at": row.get("created_at"),
                        "clip_start_sec": round(start_sec, 2),
                        "clip_end_sec": round(end_sec, 2),
                    },
                }
            )
        return jsonify({"clips": clips, "count": len(clips), "streak": 0, "today_count": 0, "leaderboard": []}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/acoustic-dojo/labels", methods=["POST"])
@require_admin
def v2_admin_acoustic_dojo_labels():
    try:
        body = request.get_json(silent=True) or {}
        clip_id = (body.get("clip_id") or "").strip()
        if not clip_id:
            return jsonify({"code": "INVALID_INPUT", "error": "clip_id is required"}), 400
        source_meta = body.get("source_metadata") if isinstance(body.get("source_metadata"), dict) else {}
        start_sec = source_meta.get("clip_start_sec", source_meta.get("start_sec", 0))
        end_sec = source_meta.get("clip_end_sec", source_meta.get("end_sec", 10))
        try:
            start_ms = int(max(0, float(start_sec) * 1000))
        except (TypeError, ValueError):
            start_ms = 0
        try:
            end_ms = int(max(start_ms + 1, float(end_sec) * 1000))
        except (TypeError, ValueError):
            end_ms = max(start_ms + 1, 10000)
        conf_raw = body.get("confidence")
        try:
            confidence = int(round(float(conf_raw))) if conf_raw is not None else 2
        except (TypeError, ValueError):
            confidence = 2
        confidence = max(1, min(3, confidence))
        payload = {
            "clip_source": "student_recording",
            "recording_id": clip_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "external_url": None,
            "label_stress": bool(body.get("label_stress", False)),
            "label_charisma": bool(body.get("label_charisma", False)),
            "confidence": confidence,
            "labeled_by": request.user_id,
        }
        db.client.table("acoustic_labels").insert(payload).execute()
        return jsonify({"status": "ok", "accepted": True, "next_clip_id": None}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/copilot/next-clips", methods=["GET"])
@require_admin
def v2_admin_copilot_next_clips():
    """Pending copilot inbox items derived from admin_student_send_drafts."""
    try:
        limit_raw = request.args.get("limit")
        try:
            limit = max(1, min(200, int(limit_raw))) if limit_raw is not None else 50
        except (TypeError, ValueError):
            limit = 50
        rows = db.list_admin_student_send_drafts(status="pending")
        items = []
        for row in rows[:limit]:
            uid = str(row.get("user_id") or "")
            draft = _serialize_copilot_draft(row)
            items.append(
                {
                    "id": row.get("id"),
                    "draft_id": row.get("id"),
                    "user_id": uid,
                    "email": db.get_user_email_from_auth(uid) if uid else None,
                    "session_id": draft.get("session_id"),
                    "cohort_profile": row.get("cohort_profile"),
                    "cohort_stage": row.get("cohort_stage"),
                    "master_task_text": row.get("master_task_text"),
                    "status": row.get("status"),
                    "updated_at": row.get("updated_at"),
                    "created_at": row.get("created_at"),
                    "email_draft": draft.get("email_draft"),
                    "task_draft": draft.get("task_draft"),
                    "script_draft": draft.get("script_draft"),
                    "ai_email_draft": draft.get("ai_email_draft"),
                    "ai_task_suggestion": draft.get("ai_task_suggestion"),
                    "ai_script_draft": draft.get("ai_script_draft"),
                    "draft": draft,
                }
            )
        return jsonify({"next_clips": items, "clips": items, "count": len(items)}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/copilot/backfill-drafts", methods=["POST"])
@v2_bp.route("/admin/cohorts/backfill-drafts", methods=["POST"])
@require_admin
def v2_admin_copilot_backfill_drafts():
    """Seed admin_student_send_drafts from Supabase Auth users + last session so Training Studio cohorts populate.

    Body (optional): ``user_ids`` (list) — only these users; else all auth users up to ``max_users`` (default 2000).
    ``skip_if_pending`` (bool, default true) — skip users who already have a pending draft.
    ``dry_run`` (bool, default false) — return counts and sample rows without inserting.
    """
    try:
        body = request.get_json(silent=True) or {}
        dry_run = str(body.get("dry_run", False)).lower() in ("1", "true", "yes")
        skip_if_pending = body.get("skip_if_pending", True)
        if isinstance(skip_if_pending, str):
            skip_if_pending = skip_if_pending.strip().lower() in ("1", "true", "yes")
        else:
            skip_if_pending = bool(skip_if_pending)

        raw_ids = body.get("user_ids")
        if raw_ids is not None:
            if not isinstance(raw_ids, list):
                return jsonify({"code": "INVALID_INPUT", "error": "user_ids must be an array"}), 400
            targets = [str(x).strip() for x in raw_ids if str(x).strip()]
        else:
            try:
                cap = int(body.get("max_users", 2000))
            except (TypeError, ValueError):
                cap = 2000
            cap = max(1, min(5000, cap))
            targets = db.v2_list_all_auth_user_ids(cap=cap)

        inserted_preview: list = []
        skipped: list = []
        to_insert: list = []

        for uid in targets:
            if skip_if_pending and db.v2_user_has_pending_copilot_draft(uid):
                skipped.append({"user_id": uid, "reason": "pending_exists"})
                continue
            try:
                row = _copilot_backfill_draft_row_for_user(uid)
            except Exception as ex:
                logger.warning("copilot backfill: skip %s: %s", uid, ex)
                skipped.append({"user_id": uid, "reason": f"error:{ex}"})
                continue
            to_insert.append(row)
            if len(inserted_preview) < 5:
                inserted_preview.append(
                    {
                        "user_id": row["user_id"],
                        "cohort_profile": row["cohort_profile"],
                        "cohort_stage": row["cohort_stage"],
                        "session_id": row["session_id"],
                        "master_task_text_preview": (row["master_task_text"] or "")[:120],
                    }
                )

        if dry_run:
            return (
                jsonify(
                    {
                        "status": "ok",
                        "dry_run": True,
                        "would_insert": len(to_insert),
                        "skipped_count": len(skipped),
                        "sample": inserted_preview,
                    }
                ),
                200,
            )

        inserted = db.insert_admin_student_send_drafts(to_insert) if to_insert else []
        return (
            jsonify(
                {
                    "status": "ok",
                    "inserted_count": len(inserted),
                    "skipped_count": len(skipped),
                    "skipped": skipped[:100],
                    "sample": inserted_preview,
                }
            ),
            201,
        )
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/copilot/normalize-drafts", methods=["POST"])
@require_admin
def v2_admin_copilot_normalize_drafts():
    """One-time/idempotent contract normalization for existing draft rows."""
    try:
        body = request.get_json(silent=True) or {}
        dry_run = str(body.get("dry_run", False)).lower() in ("1", "true", "yes")
        status = (body.get("status") or "").strip().lower() or None
        raw_ids = body.get("user_ids")
        user_ids = None
        if raw_ids is not None:
            if not isinstance(raw_ids, list):
                return jsonify({"code": "INVALID_INPUT", "error": "user_ids must be an array"}), 400
            user_ids = {str(x).strip() for x in raw_ids if str(x).strip()}
        try:
            limit = int(body.get("limit", 3000))
        except (TypeError, ValueError):
            limit = 3000
        limit = max(1, min(10000, limit))

        rows = db.list_admin_student_send_drafts(status=status)[:limit]
        if user_ids is not None:
            rows = [r for r in rows if str(r.get("user_id") or "") in user_ids]

        changed = []
        skipped_count = 0
        failed_count = 0
        for row in rows:
            original = _draft_payload(row)
            normalized = _normalize_copilot_payload(row, original)
            if normalized == original:
                skipped_count += 1
                continue
            changed.append(
                {
                    "id": row.get("id"),
                    "user_id": row.get("user_id"),
                    "session_id": row.get("session_id"),
                    "task_preview": (_first_non_empty(normalized.get("task_draft")) or "")[:120],
                }
            )
            if not dry_run:
                try:
                    update_body = {
                        "draft_payload": normalized,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                    task_text = _first_non_empty(normalized.get("task_draft"))
                    if task_text:
                        update_body["master_task_text"] = task_text
                    db.client.table("admin_student_send_drafts").update(update_body).eq("id", row.get("id")).execute()
                except Exception:
                    failed_count += 1

        return jsonify(
            {
                "status": "ok",
                "dry_run": dry_run,
                "scanned_count": len(rows),
                "normalized_count": len(changed),
                "skipped_count": skipped_count,
                "failed_count": failed_count,
                "sample": changed[:20],
            }
        ), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/copilot/learning-health", methods=["GET"])
@require_admin
def v2_admin_copilot_learning_health():
    """Operational health for annotation-event -> dataset export pipeline."""
    try:
        now = datetime.now(timezone.utc)
        runs = (
            db.client.table("admin_annotation_export_runs")
            .select("*")
            .order("started_at", desc=True)
            .limit(100)
            .execute()
            .data
            or []
        )
        last_success = next((r for r in runs if str(r.get("status") or "").lower() == "success"), None)
        last_failure = next((r for r in runs if str(r.get("status") or "").lower() == "failed"), None)
        checkpoint = last_success.get("checkpoint_created_at") if last_success else None

        unprocessed_query = db.client.table("admin_annotation_events").select("id", count="exact")
        if checkpoint:
            unprocessed_query = unprocessed_query.gt("created_at", checkpoint)
        unprocessed = unprocessed_query.limit(1).execute()
        unprocessed_count = int(unprocessed.count or 0)

        oldest_pending_at = None
        if unprocessed_count > 0:
            oldest_rows = db.client.table("admin_annotation_events").select("created_at")
            if checkpoint:
                oldest_rows = oldest_rows.gt("created_at", checkpoint)
            oldest = oldest_rows.order("created_at", desc=False).limit(1).execute().data or []
            if oldest:
                oldest_pending_at = oldest[0].get("created_at")

        ingestion_lag_minutes = 0
        if oldest_pending_at:
            parsed = datetime.fromisoformat(str(oldest_pending_at).replace("Z", "+00:00"))
            ingestion_lag_minutes = max(0, int((now - parsed).total_seconds() // 60))

        failed_last_24h = 0
        since_24h = (now.timestamp() - 86400)
        for run in runs:
            if str(run.get("status") or "").lower() != "failed":
                continue
            started_at = run.get("started_at")
            if not started_at:
                continue
            try:
                parsed = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
            except Exception:
                continue
            if parsed.timestamp() >= since_24h:
                failed_last_24h += 1

        return jsonify(
            {
                "status": "ok",
                "pipeline": {
                    "sla_minutes": 24 * 60,
                    "checkpoint_created_at": checkpoint,
                    "unprocessed_events": unprocessed_count,
                    "oldest_unprocessed_created_at": oldest_pending_at,
                    "ingestion_lag_minutes": ingestion_lag_minutes,
                },
                "last_successful_export": last_success,
                "last_failed_export": last_failure,
                "failed_runs_last_24h": failed_last_24h,
            }
        ), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/copilot/export-annotation-events", methods=["POST"])
@require_admin
def v2_admin_copilot_export_annotation_events():
    """Run annotation export (same job as scripts/export_annotation_events.py).

    Body JSON (optional): ``limit``, ``dry_run``, ``upload_bucket``, ``upload_prefix``, ``output_dir``
    Env defaults: ``ANNOTATION_EXPORT_BUCKET``, ``ANNOTATION_EXPORT_PREFIX``, ``ANNOTATION_EXPORT_OUTPUT_DIR``
    """
    try:
        body = request.get_json(silent=True) or {}
        try:
            limit = int(body.get("limit", 5000))
        except (TypeError, ValueError):
            return jsonify({"code": "INVALID_INPUT", "error": "limit must be an integer"}), 400
        dry_raw = body.get("dry_run", False)
        dry_run = str(dry_raw).lower() in ("1", "true", "yes")

        bucket = (body.get("upload_bucket") or getattr(config, "ANNOTATION_EXPORT_BUCKET", None) or "").strip() or None
        output_dir = (body.get("output_dir") or getattr(config, "ANNOTATION_EXPORT_OUTPUT_DIR", None) or "").strip() or None
        prefix = (body.get("upload_prefix") or getattr(config, "ANNOTATION_EXPORT_PREFIX", None) or "annotation-events").strip()

        if not dry_run and not bucket and not output_dir:
            return jsonify(
                {
                    "code": "EXPORT_SINK_MISSING",
                    "error": "Set ANNOTATION_EXPORT_BUCKET and/or ANNOTATION_EXPORT_OUTPUT_DIR on the server, "
                    "or pass upload_bucket / output_dir in the body.",
                }
            ), 400

        result = run_annotation_export(
            limit=limit,
            output_dir=None if dry_run else output_dir,
            dry_run=dry_run,
            created_by=f"admin:{request.user_id}",
            upload_bucket=bucket,
            upload_prefix=prefix,
        )
        return jsonify({"status": "ok", **result_to_dict(result)}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/cohorts", methods=["GET"])
@v2_bp.route("/admin/copilot/cohorts", methods=["GET"])
@v2_bp.route("/admin/acoustic-dojo/cohorts", methods=["GET"])
@require_admin
def v2_admin_cohorts():
    try:
        from services.student_profile_service import refresh_student_profile_state

        only_pending = str(request.args.get("only_pending", "false")).strip().lower() in ("1", "true", "yes")
        profile_bucket = (request.args.get("profile_bucket") or "").strip()
        stage_key = (request.args.get("stage_key") or "").strip()
        try:
            cap_ms = int(request.args.get("max_students", 2500))
        except (TypeError, ValueError):
            cap_ms = 2500
        cap_ms = max(50, min(5000, cap_ms))

        rows = db.list_admin_student_send_drafts(status=None)
        profile_cache: dict[str, dict] = {}
        groups: dict[tuple[str, int], dict] = {}

        def _ensure_group(profile: str, stage: int):
            key = (profile, int(stage))
            if key not in groups:
                groups[key] = {
                    "id": _cohort_id(profile, int(stage)),
                    "profile_bucket": profile,
                    "stage_key": str(int(stage)),
                    "profile": profile,
                    "stage": int(stage),
                    "pending_count": 0,
                    "students": {},
                    "metadata": None,
                }
            return groups[key]

        # Baseline: same student pool as Admin → Students (Auth). Fallback if Auth admin list fails.
        archived_ids = db.v2_get_archived_user_ids()
        baseline_uids = db.v2_list_all_auth_user_ids(cap=cap_ms)
        if not baseline_uids:
            baseline_uids = db.list_recent_student_ids(limit=cap_ms)
        for uid in baseline_uids:
            if not uid or uid in archived_ids:
                continue
            sp = db.get_sniper_profile(uid) or {}
            draft_profile, draft_stage = _student_cohort_from_state(sp)
            if profile_bucket and draft_profile != profile_bucket:
                continue
            if stage_key and str(draft_stage) != str(stage_key):
                continue
            g = _ensure_group(draft_profile, draft_stage)
            if uid not in g["students"]:
                g["students"][uid] = {
                    "user_id": uid,
                    "email": db.get_user_email_from_auth(uid),
                    "pending_count": 0,
                }

        for row in rows:
            uid = str(row.get("user_id") or "")
            if not uid or uid in archived_ids:
                continue
            draft_profile = (row.get("cohort_profile") or "").strip()
            try:
                draft_stage = int(row.get("cohort_stage")) if row.get("cohort_stage") is not None else None
            except (TypeError, ValueError):
                draft_stage = None
            if not draft_profile or draft_stage is None:
                if uid not in profile_cache:
                    profile_cache[uid] = refresh_student_profile_state(uid)
                state = profile_cache[uid] or {}
                draft_profile, draft_stage = _student_cohort_from_state(state)
            else:
                draft_stage = max(1, min(5, int(draft_stage)))
            if profile_bucket and draft_profile != profile_bucket:
                continue
            if stage_key and str(draft_stage) != str(stage_key):
                continue
            g = _ensure_group(draft_profile, int(draft_stage))
            if str(row.get("status") or "").lower() == "pending":
                g["pending_count"] += 1
            email = db.get_user_email_from_auth(uid)
            st = g["students"].setdefault(uid, {"user_id": uid, "email": email, "pending_count": 0})
            if str(row.get("status") or "").lower() == "pending":
                st["pending_count"] += 1

        out = []
        for g in groups.values():
            if only_pending and int(g["pending_count"]) <= 0:
                if not g.get("students"):
                    continue
            g["students"] = list((g.get("students") or {}).values())
            out.append(g)
        out.sort(key=lambda g: (-int(g["pending_count"]), str(g["profile"]), int(g["stage"])))
        return jsonify({"cohorts": out, "count": len(out)}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/copilot/cohorts/<cohort_id>/students", methods=["GET"])
@v2_bp.route("/admin/acoustic-dojo/cohorts/<cohort_id>/students", methods=["GET"])
@require_admin
def v2_admin_copilot_cohort_students(cohort_id):
    try:
        from services.student_profile_service import refresh_student_profile_state

        profile, stage = _parse_cohort_id(cohort_id)
        if stage is None:
            return jsonify({"code": "INVALID_INPUT", "error": "cohortId must be '<profile>::<stage>'"}), 400
        try:
            cap_ms = int(request.args.get("max_students", 2500))
        except (TypeError, ValueError):
            cap_ms = 2500
        cap_ms = max(50, min(5000, cap_ms))

        archived_ids = db.v2_get_archived_user_ids()
        rows = db.list_admin_student_send_drafts(status=None)
        profile_cache = {}
        filtered = []
        for row in rows:
            uid = str(row.get("user_id") or "")
            if not uid or uid in archived_ids:
                continue
            p = (row.get("cohort_profile") or "").strip()
            try:
                s = int(row.get("cohort_stage")) if row.get("cohort_stage") is not None else None
            except (TypeError, ValueError):
                s = None
            if not p or s is None:
                if uid not in profile_cache:
                    profile_cache[uid] = refresh_student_profile_state(uid)
                st_prof = profile_cache[uid] or {}
                p, s = _student_cohort_from_state(st_prof)
            else:
                s = max(1, min(5, int(s)))
            if p == profile and int(s) == int(stage):
                filtered.append(row)

        counts = {}
        latest_by_key = {}
        for row in filtered:
            uid = str(row.get("user_id") or "")
            state = _draft_state_ui(row)
            c = counts.setdefault(uid, {"Draft": 0, "Ready": 0, "Sent": 0})
            c[state] = c.get(state, 0) + 1
            key = f"{uid}:{str(row.get('session_id') or '')}"
            if key not in latest_by_key:
                latest_by_key[key] = row

        items = []
        for i, row in enumerate(latest_by_key.values()):
            uid = str(row.get("user_id") or "")
            details = db.v2_get_student_details(uid) or {}
            email = db.get_user_email_from_auth(uid)
            latest_session = db.v2_get_last_completed_session(uid) or {}
            profile_row = db.get_sniper_profile(uid) or {}
            items.append(
                {
                    "student_id": uid,
                    "session_id": _effective_session_id_for_copilot_draft(row, uid),
                    "queue_position": i,
                    "state": _draft_state_ui(row),
                    "draft_count": int((counts.get(uid) or {}).get("Draft", 0)),
                    "ready_count": int((counts.get(uid) or {}).get("Ready", 0)),
                    "sent_count": int((counts.get(uid) or {}).get("Sent", 0)),
                    "profile": {
                        "name": details.get("name"),
                        "email": email,
                        "stage": str(stage),
                        "justification": _display_learning_profile_justification(profile_row),
                        "canonical_score_for_display": latest_session.get("score_for_display"),
                    },
                }
            )

        uids_in_queue = {str(it["student_id"]) for it in items}
        extra_uids = db.v2_list_all_auth_user_ids(cap=cap_ms)
        if not extra_uids:
            extra_uids = db.list_recent_student_ids(limit=cap_ms)
        for uid in extra_uids:
            if not uid or uid in uids_in_queue or uid in archived_ids:
                continue
            sp = db.get_sniper_profile(uid) or {}
            p, stg = _student_cohort_from_state(sp)
            if p != profile or int(stg) != int(stage):
                continue
            details = db.v2_get_student_details(uid) or {}
            email = db.get_user_email_from_auth(uid)
            latest_session = db.v2_get_last_completed_session(uid) or {}
            profile_row = db.get_sniper_profile(uid) or {}
            items.append(
                {
                    "student_id": uid,
                    "session_id": latest_session.get("id"),
                    "queue_position": len(items),
                    "state": "Draft",
                    "draft_count": 0,
                    "ready_count": 0,
                    "sent_count": 0,
                    "profile": {
                        "name": details.get("name"),
                        "email": email,
                        "stage": str(stage),
                        "justification": _display_learning_profile_justification(profile_row),
                        "canonical_score_for_display": latest_session.get("score_for_display"),
                    },
                }
            )
            uids_in_queue.add(uid)

        return jsonify({"students": items, "count": len(items)}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


def _insert_copilot_backfill_draft(user_id: str) -> list:
    """Insert one backfilled admin_student_send_drafts row; returns inserted rows or [dict] on failure."""
    insert_dict = _copilot_backfill_draft_row_for_user(user_id)
    try:
        inserted = db.insert_admin_student_send_drafts([insert_dict])
    except Exception:
        legacy = dict(insert_dict)
        legacy.pop("ai_suggested_task_text", None)
        legacy.pop("ai_draft_message", None)
        legacy.pop("ai_draft_video_script", None)
        inserted = db.insert_admin_student_send_drafts([legacy])
    return inserted if inserted else [insert_dict]


def _ensure_draft_exists_for_user(user_id: str) -> list:
    """Ensure there is at least one draft row usable for Training Studio (pending or editable).

    - No rows → backfill one.
    - Only ``sent`` rows (previous homework already emailed) → add a fresh pending draft for the next cycle.

    Returns the (possibly extended) list of draft rows.
    """
    rows = (
        db.client.table("admin_student_send_drafts")
        .select("*")
        .eq("user_id", user_id)
        .order("updated_at", desc=True)
        .limit(50)
        .execute()
        .data or []
    )
    if not rows:
        try:
            out = _insert_copilot_backfill_draft(user_id)
            logger.info("create-on-missing: auto-created draft for user_id=%s", user_id)
            return out
        except Exception as auto_err:
            logger.warning("create-on-missing failed for user_id=%s: %s", user_id, auto_err)
            return []

    rows = _normalize_draft_rows_in_db(rows)
    all_sent = rows and all(str(r.get("status") or "").lower() == "sent" for r in rows)
    if all_sent:
        try:
            new_rows = _insert_copilot_backfill_draft(user_id)
            logger.info("create-after-all-sent: auto-created draft for user_id=%s", user_id)
            return rows + new_rows
        except Exception as auto_err:
            logger.warning("create-after-all-sent failed for user_id=%s: %s", user_id, auto_err)
    return rows


@v2_bp.route("/admin/copilot/students/<user_id>/drafts", methods=["GET", "PUT"])
@require_admin
def v2_admin_copilot_student_drafts(user_id):
    try:
        if request.method == "GET":
            session_id = (request.args.get("session_id") or "").strip() or None
            rows = _ensure_draft_exists_for_user(user_id)
            if session_id:
                filtered = [
                    r
                    for r in rows
                    if str(r.get("session_id") or "") == session_id
                    or _effective_session_id_for_copilot_draft(r, user_id) == session_id
                ]
                # Stale or UI-mismatched session_id must not return an empty list while rows exist.
                rows = filtered if filtered else rows
            status_meta = _copilot_draft_generation_status(user_id, rows)
            return jsonify({"drafts": [_serialize_copilot_draft(r) for r in rows], **status_meta}), 200

        body = request.get_json(silent=True) or {}
        immutable_fields = sorted(
            k for k in body.keys() if k in _COPILOT_DRAFT_IMMUTABLE_FIELDS or k.startswith("ai_")
        )
        if immutable_fields:
            return jsonify(
                {
                    "code": "IMMUTABLE_FIELD",
                    "error": "AI baseline fields are immutable and cannot be edited.",
                    "fields": immutable_fields,
                }
            ), 400
        unknown_fields = sorted(
            k
            for k in body.keys()
            if k not in _COPILOT_DRAFT_EDITABLE_FIELDS and k not in _COPILOT_DRAFT_CONTROL_FIELDS
        )
        if unknown_fields:
            return jsonify(
                {
                    "code": "INVALID_FIELD",
                    "error": "Request contains unsupported fields for draft updates.",
                    "fields": unknown_fields,
                }
            ), 400
        session_id = (body.get("session_id") or "").strip() or None
        draft_id = (body.get("draft_id") or "").strip() or None
        row = _pick_student_draft(user_id, session_id=session_id, draft_id=draft_id, include_sent=False)
        if not row:
            # Create-on-missing for PUT: auto-create then retry
            created = _ensure_draft_exists_for_user(user_id)
            if created:
                row = _pick_student_draft(user_id, session_id=session_id, draft_id=draft_id, include_sent=False)
        if not row:
            return jsonify({"code": "DRAFT_NOT_FOUND", "error": "No editable draft found for student"}), 404
        payload = _normalize_copilot_payload(row)
        old_grade = payload.get("grade_draft")
        old_comment = (payload.get("comment_draft") or "").strip()
        old_task = (
            (payload.get("task_draft") or payload.get("task_text") or row.get("master_task_text") or "").strip()
        )
        old_email = (
            (
                payload.get("email_draft")
                or payload.get("ai_email_draft")
                or payload.get("email_message")
                or payload.get("homework_comment")
                or row.get("ai_draft_message")
                or ""
            )
        ).strip()
        old_script = (
            (
                payload.get("script_draft")
                or payload.get("video_script")
                or row.get("ai_draft_video_script")
                or ""
            )
        ).strip()
        ai_grade_baseline = payload.get("ai_grade_draft")
        ai_comment_baseline = (payload.get("ai_comment_draft") or "").strip() or None
        ai_task_baseline = (
            (payload.get("ai_task_suggestion") or row.get("ai_suggested_task_text") or "").strip() or None
        )
        ai_email_baseline = (
            (payload.get("ai_email_draft") or (row.get("ai_draft_message") or "")).strip() or None
        )
        ai_script_baseline = (
            (payload.get("ai_script_draft") or (row.get("ai_draft_video_script") or "")).strip() or None
        )
        old_corrected_insight = (payload.get("corrected_insight") or "").strip()
        ai_insight_baseline = (payload.get("ai_insight") or "").strip() or None
        for k in (
            "grade_draft",
            "comment_draft",
            "task_draft",
            "email_draft",
            "script_draft",
            "corrected_insight",
            "metadata",
            "video_url",
            "script_mode",
            "full_override_video_url",
            "full_override_video_storage_path",
            "reference_tags",
            "is_universal_video",
            "reference_transcript_text",
            "universal_blocks",
            "personalized_blocks",
            "coach_override_blocks",
        ):
            if k in body:
                payload[k] = body.get(k)
        if "reason_chips" in body:
            payload["reason_chips"] = body.get("reason_chips")
        if "reason_chip_custom" in body:
            payload["reason_chip_custom"] = body.get("reason_chip_custom")
        # Canonical write target is script_draft; video_script remains alias.
        if "video_script" in body and "script_draft" not in body:
            payload["script_draft"] = body.get("video_script")
        if "script_draft" in body or "video_script" in body:
            payload["video_script"] = payload.get("script_draft")
        payload = _normalize_copilot_payload(row, payload)
        new_task = (
            (payload.get("task_draft") or payload.get("task_text") or row.get("master_task_text") or "").strip()
        )
        new_email = (
            (
                payload.get("email_draft")
                or payload.get("ai_email_draft")
                or payload.get("email_message")
                or payload.get("homework_comment")
                or ""
            )
        ).strip()
        new_script = (
            (payload.get("script_draft") or payload.get("video_script") or "").strip()
        )
        new_corrected_insight = (payload.get("corrected_insight") or "").strip()
        update_body = {"draft_payload": payload, "updated_at": datetime.now(timezone.utc).isoformat()}
        if "task_draft" in body and new_task:
            update_body["master_task_text"] = new_task
        updated = (
            db.client.table("admin_student_send_drafts")
            .update(update_body)
            .eq("id", row.get("id"))
            .eq("user_id", user_id)
            .execute()
        )
        out = updated.data[0] if updated.data else row
        try:
            new_grade = payload.get("grade_draft")
            new_comment = (payload.get("comment_draft") or "").strip()
            if "grade_draft" in body and str(old_grade) != str(new_grade):
                db.create_admin_annotation_event(
                    user_id=user_id,
                    session_id=row.get("session_id"),
                    section_type="report",
                    field_name="report_grade",
                    ai_original_text=str(ai_grade_baseline) if ai_grade_baseline is not None else (str(old_grade) if old_grade is not None else None),
                    coach_final_text=str(new_grade) if new_grade is not None else None,
                    reason_chip=(body.get("reason_chip") or "manual_grade"),
                    custom_reason=(body.get("reason_chip_custom") or None),
                    created_by=request.user_id,
                )
            if "comment_draft" in body and old_comment != new_comment:
                db.create_admin_annotation_event(
                    user_id=user_id,
                    session_id=row.get("session_id"),
                    section_type="report",
                    field_name="report_comment",
                    ai_original_text=ai_comment_baseline or old_comment or None,
                    coach_final_text=new_comment or None,
                    reason_chip=(body.get("reason_chip") or "manual_comment"),
                    custom_reason=(body.get("reason_chip_custom") or None),
                    created_by=request.user_id,
                )
            if "task_draft" in body and old_task != new_task:
                db.create_admin_annotation_event(
                    user_id=user_id,
                    session_id=row.get("session_id"),
                    section_type="assignment",
                    field_name="task_draft",
                    ai_original_text=ai_task_baseline or old_task,
                    coach_final_text=new_task or None,
                    reason_chip=(body.get("reason_chip") or "task_swap"),
                    custom_reason=(body.get("reason_chip_custom") or None),
                    created_by=request.user_id,
                    draft_id=str(row.get("id") or "") or None,
                    previous_value_hash=_value_hash(ai_task_baseline or old_task),
                    new_value_hash=_value_hash(new_task),
                )
            if "email_draft" in body and old_email != new_email:
                db.create_admin_annotation_event(
                    user_id=user_id,
                    session_id=row.get("session_id"),
                    section_type="assignment",
                    field_name="email_draft",
                    ai_original_text=ai_email_baseline or old_email or None,
                    coach_final_text=new_email or None,
                    reason_chip=(body.get("reason_chip") or "manual_edit"),
                    custom_reason=(body.get("reason_chip_custom") or None),
                    created_by=request.user_id,
                    draft_id=str(row.get("id") or "") or None,
                    previous_value_hash=_value_hash(ai_email_baseline or old_email or None),
                    new_value_hash=_value_hash(new_email or None),
                )
            if ("script_draft" in body or "video_script" in body) and old_script != new_script:
                db.create_admin_annotation_event(
                    user_id=user_id,
                    session_id=row.get("session_id"),
                    section_type="assignment",
                    field_name="script_draft",
                    ai_original_text=ai_script_baseline or old_script or None,
                    coach_final_text=new_script or None,
                    reason_chip=(body.get("reason_chip") or "manual_edit"),
                    custom_reason=(body.get("reason_chip_custom") or None),
                    created_by=request.user_id,
                    draft_id=str(row.get("id") or "") or None,
                    previous_value_hash=_value_hash(ai_script_baseline or old_script or None),
                    new_value_hash=_value_hash(new_script or None),
                )
            if "corrected_insight" in body and old_corrected_insight != new_corrected_insight:
                db.create_admin_annotation_event(
                    user_id=user_id,
                    session_id=row.get("session_id"),
                    section_type="insight",
                    field_name="corrected_insight",
                    ai_original_text=ai_insight_baseline,
                    coach_final_text=new_corrected_insight or None,
                    reason_chip=(body.get("reason_chip") or "manual_insight"),
                    custom_reason=(body.get("reason_chip_custom") or None),
                    created_by=request.user_id,
                    draft_id=str(row.get("id") or "") or None,
                    previous_value_hash=_value_hash(ai_insight_baseline),
                    new_value_hash=_value_hash(new_corrected_insight or None),
                )
        except Exception as ann_err:
            logger.warning("task swap annotation failed: %s", ann_err)
        return jsonify({"status": "ok", "draft": _serialize_copilot_draft(out)}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/copilot/reference-videos", methods=["GET"])
@require_admin
def v2_admin_copilot_reference_videos_list():
    try:
        try:
            limit = int(request.args.get("limit", 50))
        except (TypeError, ValueError):
            limit = 50
        try:
            offset = int(request.args.get("offset", 0))
        except (TypeError, ValueError):
            offset = 0
        include_preview = str(request.args.get("include_preview_url", "false")).strip().lower() in ("1", "true", "yes")
        rows = db.list_admin_uploaded_reference_videos(limit=max(1, min(200, limit)), offset=max(0, offset), is_active=True)
        if include_preview:
            for row in rows:
                storage_path = (row.get("storage_path") or "").strip()
                meta = row.get("feature_metadata") if isinstance(row.get("feature_metadata"), dict) else {}
                bucket = (meta.get("bucket") or config.COACH_FEEDBACK_VIDEO_BUCKET).strip()
                try:
                    row["preview_url"] = (
                        presigned_get_coach_object(bucket, storage_path, 3600, supabase_db=db) if storage_path else None
                    )
                except Exception:
                    row["preview_url"] = None
        return jsonify({"status": "ok", "items": rows, "limit": limit, "offset": offset}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error("reference-videos list error: %s", e)
        return jsonify({"code": "V2_ERROR", "error": "Internal server error"}), 500


@v2_bp.route("/admin/copilot/reference-videos/upload", methods=["POST"])
@require_admin
def v2_admin_copilot_reference_videos_upload():
    try:
        max_video_mb = max(1, int(getattr(config, "MAX_REFERENCE_VIDEO_SIZE_MB", 500)))
        max_video_bytes = max_video_mb * 1024 * 1024
        content_length = request.content_length or 0
        if content_length and content_length > max_video_bytes:
            return jsonify(
                {
                    "code": "PAYLOAD_TOO_LARGE",
                    "error": f"Reference video is too large. Max allowed is {max_video_mb}MB.",
                }
            ), 413
        video_file = request.files.get("video_file")
        if video_file is None or not (video_file.filename or "").strip():
            return jsonify({"code": "INVALID_INPUT", "error": "video_file is required"}), 400
        safe_name = secure_filename(video_file.filename or "")
        ext = os.path.splitext(safe_name)[1].lower()
        if ext not in _REFERENCE_VIDEO_ALLOWED_EXTENSIONS:
            return jsonify(
                {
                    "code": "INVALID_VIDEO_FORMAT",
                    "error": "Supported formats: .mp4, .mov, .webm, .m4v, .avi, .mkv",
                }
            ), 400
        video_bytes = video_file.read() or b""
        if not video_bytes:
            return jsonify({"code": "INVALID_INPUT", "error": "video_file is empty"}), 400
        if len(video_bytes) > max_video_bytes:
            return jsonify(
                {
                    "code": "PAYLOAD_TOO_LARGE",
                    "error": f"Reference video is too large. Max allowed is {max_video_mb}MB.",
                }
            ), 413

        student_user_id, uid_err = _resolve_reference_upload_user_id(
            (request.form.get("user_id") or "").strip(), request.user_id
        )
        if uid_err:
            return jsonify({"code": "INVALID_USER_ID", "error": uid_err}), 400
        session_id = (request.form.get("session_id") or "").strip() or None
        draft_id = (request.form.get("draft_id") or "").strip() or None
        if session_id:
            try:
                session_id = str(uuid.UUID(session_id))
            except (ValueError, TypeError, AttributeError):
                return jsonify({"code": "INVALID_INPUT", "error": "session_id must be a UUID"}), 400
        if draft_id:
            try:
                draft_id = str(uuid.UUID(draft_id))
            except (ValueError, TypeError, AttributeError):
                return jsonify({"code": "INVALID_INPUT", "error": "draft_id must be a UUID"}), 400
        title = (request.form.get("title") or "").strip() or None
        tags_raw = (request.form.get("reference_tags") or request.form.get("tags") or "").strip()
        tags = [x.strip() for x in tags_raw.split(",") if x.strip()]
        is_universal = str(request.form.get("is_universal_video", "false")).strip().lower() in ("1", "true", "yes")

        track_raw = (request.form.get("track_progress") or request.args.get("track_progress") or "").strip().lower()
        track_progress = track_raw in ("1", "true", "yes")

        def _fail_upload_job(jid: str | None, err: Exception) -> None:
            if not jid:
                return
            try:
                db.update_copilot_reference_upload_job(
                    jid,
                    {
                        "stage": "failed",
                        "percent": 0,
                        "error": str(err)[:2000],
                        "message": "Processing failed",
                    },
                )
            except Exception:
                pass

        if track_progress:
            job_row = None
            try:
                job_row = db.create_copilot_reference_upload_job(
                    created_by=request.user_id,
                    student_user_id=student_user_id,
                )
            except Exception as job_err:
                logger.warning(
                    "reference upload async job unavailable (did you run migrations/add_copilot_reference_upload_jobs.sql?): %s",
                    job_err,
                )
                job_row = None
            if job_row:
                jid = str(job_row["id"])
                db.update_copilot_reference_upload_job(
                    jid,
                    {
                        "stage": "received",
                        "percent": 5,
                        "message": "File received; processing on server (storage → database → transcription if applicable)…",
                    },
                )

                def _run_async_upload() -> None:
                    try:
                        run_reference_video_upload(
                            job_id=jid,
                            video_bytes=video_bytes,
                            safe_name=safe_name,
                            ext=ext,
                            student_user_id=student_user_id,
                            session_id=session_id,
                            draft_id=draft_id,
                            title=title,
                            tags=tags,
                            is_universal=is_universal,
                            admin_user_id=request.user_id,
                        )
                    except Exception as e:
                        sentry_sdk.capture_exception(e)
                        _fail_upload_job(jid, e)

                threading.Thread(
                    target=_run_async_upload,
                    daemon=True,
                    name=f"refvid-{jid[:8]}",
                ).start()
                return (
                    jsonify(
                        {
                            "status": "accepted",
                            "job_id": jid,
                            "poll_url": f"/v2/admin/copilot/reference-videos/upload-jobs/{jid}",
                            "message": "Poll GET poll_url until job.stage is completed or failed.",
                        }
                    ),
                    202,
                )

        try:
            out = run_reference_video_upload(
                job_id=None,
                video_bytes=video_bytes,
                safe_name=safe_name,
                ext=ext,
                student_user_id=student_user_id,
                session_id=session_id,
                draft_id=draft_id,
                title=title,
                tags=tags,
                is_universal=is_universal,
                admin_user_id=request.user_id,
            )
        except Exception as e:
            sentry_sdk.capture_exception(e)
            emsg = str(e)
            emsg_l = emsg.lower()
            if (
                "payload too large" in emsg_l
                or "exceeded the maximum allowed size" in emsg_l
                or "object exceeded the maximum allowed size" in emsg_l
            ):
                return (
                    jsonify(
                        {
                            "code": "PAYLOAD_TOO_LARGE",
                            "error": (
                                f"Storage bucket rejected file size. Increase Supabase bucket "
                                f"`{config.COACH_FEEDBACK_VIDEO_BUCKET}` file size limit to at least "
                                f"{max_video_mb}MB."
                            ),
                        }
                    ),
                    413,
                )
            logger.error("Reference video upload failed: %s", emsg)
            return jsonify(
                {"code": "UPLOAD_FAILED", "error": emsg[:2000] or "Reference video upload failed"}
            ), 500
        return (
            jsonify(
                {
                    "status": "ok",
                    "reference_video": out["reference_video"],
                    "preview_url": out.get("preview_url"),
                }
            ),
            201,
        )
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error("reference-videos/upload unexpected error: %s", e)
        return jsonify({"code": "V2_ERROR", "error": "Internal server error"}), 500


@v2_bp.route("/admin/copilot/reference-videos/upload-url", methods=["POST"])
@require_admin
def v2_admin_copilot_reference_videos_upload_url():
    """Mint a Cloudflare R2 presigned PUT URL for direct browser upload."""
    try:
        body = request.get_json(silent=True) or {}
        filename = (body.get("filename") or "").strip()
        if not filename:
            return jsonify({"code": "INVALID_INPUT", "error": "filename is required", "message": "Missing required field: filename"}), 400
        safe_name = secure_filename(filename)
        ext = os.path.splitext(safe_name)[1].lower()
        if ext not in _REFERENCE_VIDEO_ALLOWED_EXTENSIONS:
            return jsonify({
                "code": "INVALID_VIDEO_FORMAT",
                "error": "Supported formats: .mp4, .mov, .webm, .m4v, .avi, .mkv",
                "details": {"ext": ext},
            }), 400

        requested_provider = (body.get("storage_provider") or "r2").strip().lower()
        if requested_provider != "r2":
            return jsonify({
                "code": "UNSUPPORTED_STORAGE_PROVIDER",
                "error": "Only storage_provider='r2' is supported by this endpoint",
                "details": {"storage_provider": requested_provider},
            }), 400
        if not coach_videos_use_r2():
            return jsonify({
                "code": "STORAGE_PROVIDER_NOT_CONFIGURED",
                "error": "Cloudflare R2 credentials are not configured on backend",
                "message": "Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, and R2_SECRET_ACCESS_KEY",
            }), 503

        file_size_bytes = body.get("file_size_bytes")
        if file_size_bytes is not None:
            try:
                if int(file_size_bytes) <= 0:
                    raise ValueError("must be > 0")
            except Exception:
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "file_size_bytes must be a positive integer",
                    "details": {"file_size_bytes": file_size_bytes},
                }), 400

        bucket = r2_bucket_name()
        now = datetime.now(timezone.utc)
        ref_id = uuid.uuid4().hex
        storage_path = f"copilot/reference_videos/{now:%Y/%m}/{ref_id}{ext}"
        content_type = _normalize_upload_content_type((body.get("content_type") or "").strip(), safe_name)

        try:
            put_url = presigned_put_coach_object(bucket, storage_path, content_type, expires_in=3600)
        except Exception as ex:
            logger.error("reference-videos/upload-url R2 presign failed: %s", ex)
            return jsonify({
                "code": "SIGNED_URL_FAILED",
                "error": "Could not create R2 signed upload URL",
                "details": {"provider": "r2"},
            }), 500
        return jsonify(
            {
                "upload_url": put_url,
                "storage_path": storage_path,
                "content_type": content_type,
                "bucket": bucket,
            }
        ), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error("reference-videos/upload-url error: %s", e)
        return jsonify({"code": "V2_ERROR", "error": "Internal server error", "message": str(e)}), 500


@v2_bp.route("/admin/copilot/reference-videos/register-from-storage", methods=["POST"])
@require_admin
def v2_admin_copilot_reference_videos_register_from_storage():
    """After direct R2 PUT upload, register object and run Whisper.

    Uses async job + 202 when ``copilot_reference_upload_jobs`` exists; otherwise
    processes synchronously and returns 201 with ``reference_video`` (no ``job_id``).
    """
    try:
        body = request.get_json(silent=True) or {}
        storage_path = (body.get("storage_path") or "").strip()
        bucket = (body.get("bucket") or r2_bucket_name()).strip()
        sp_raw = (body.get("storage_provider") or "r2").strip().lower()
        storage_provider = sp_raw if sp_raw in ("r2", "supabase") else "r2"
        if storage_provider != "r2":
            return jsonify({
                "code": "UNSUPPORTED_STORAGE_PROVIDER",
                "error": "Only storage_provider='r2' is supported by this endpoint",
                "details": {"storage_provider": storage_provider},
            }), 400
        if not coach_videos_use_r2():
            return jsonify({
                "code": "STORAGE_PROVIDER_NOT_CONFIGURED",
                "error": "Cloudflare R2 credentials are not configured on backend",
                "message": "Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, and R2_SECRET_ACCESS_KEY",
            }), 503
        if not storage_path:
            return jsonify({"code": "INVALID_INPUT", "error": "storage_path is required", "message": "Missing required field: storage_path"}), 400

        safe_name = os.path.basename(storage_path)
        ext = os.path.splitext(safe_name)[1].lower()
        if ext not in _REFERENCE_VIDEO_ALLOWED_EXTENSIONS:
            return jsonify({
                "code": "INVALID_VIDEO_FORMAT",
                "error": "Supported formats: .mp4, .mov, .webm, .m4v, .avi, .mkv",
                "details": {"ext": ext},
            }), 400

        student_user_id, uid_err = _resolve_reference_upload_user_id(
            (body.get("user_id") or "").strip(), request.user_id
        )
        if uid_err:
            return jsonify({"code": "INVALID_USER_ID", "error": uid_err}), 400
        session_id = (body.get("session_id") or "").strip() or None
        draft_id = (body.get("draft_id") or "").strip() or None
        if session_id:
            try:
                session_id = str(uuid.UUID(session_id))
            except (ValueError, TypeError, AttributeError):
                return jsonify({"code": "INVALID_INPUT", "error": "session_id must be a UUID"}), 400
        if draft_id:
            try:
                draft_id = str(uuid.UUID(draft_id))
            except (ValueError, TypeError, AttributeError):
                return jsonify({"code": "INVALID_INPUT", "error": "draft_id must be a UUID"}), 400
        title = (body.get("title") or "").strip() or None
        tags_raw = (body.get("reference_tags") or body.get("tags") or "").strip() if isinstance(body.get("reference_tags") or body.get("tags"), str) else ""
        tags = [x.strip() for x in tags_raw.split(",") if x.strip()] if tags_raw else []
        if isinstance(body.get("reference_tags"), list):
            tags = [str(x).strip() for x in body["reference_tags"] if str(x).strip()]
        is_universal = str(body.get("is_universal_video", "false")).strip().lower() in ("1", "true", "yes")
        # track_progress is accepted for compatibility; processing is async in all cases.
        _ = str(body.get("track_progress", "true")).strip().lower() in ("1", "true", "yes")

        # Duplicate-upload short-circuit: if the admin just uploaded the same
        # filename for this student (optionally scoped to draft/session) within
        # the last hour, return that existing row instead of creating a second
        # admin_uploaded_reference_videos entry + re-running Whisper.
        original_filename = (body.get("original_filename") or "").strip() or safe_name
        allow_duplicate = str(body.get("allow_duplicate", "false")).strip().lower() in ("1", "true", "yes")
        if not allow_duplicate:
            try:
                existing = db.find_duplicate_admin_uploaded_reference_video(
                    student_user_id,
                    original_filename=original_filename,
                    draft_id=draft_id,
                    session_id=session_id,
                    within_minutes=60,
                )
            except Exception as dup_err:
                logger.warning("register-from-storage: duplicate-check failed: %s", dup_err)
                existing = None
            if existing:
                logger.info(
                    "register-from-storage: duplicate detected for user_id=%s filename=%s id=%s",
                    student_user_id, original_filename, existing.get("id"),
                )
                return jsonify({
                    "status": "duplicate",
                    "duplicate": True,
                    "reference_video": existing,
                    "job_id": str(existing.get("id")),
                    "message": (
                        "A reference video with the same filename was already uploaded "
                        "for this student in the last hour. Using the existing one. "
                        "Pass allow_duplicate=true to force a new upload."
                    ),
                }), 200

        job_row = None
        try:
            job_row = db.create_copilot_reference_upload_job(
                created_by=request.user_id,
                student_user_id=student_user_id,
            )
        except Exception as job_err:
            logger.warning(
                "register-from-storage: job tracking unavailable (%s); processing synchronously",
                job_err,
            )

        if job_row:
            jid = str(job_row["id"])
            db.update_copilot_reference_upload_job(
                jid,
                {"stage": "received", "percent": 20, "message": "File in storage; creating record + transcribing..."},
            )

            def _run_async_register() -> None:
                try:
                    video_bytes = get_coach_object_bytes(bucket, storage_path)
                    run_reference_video_upload(
                        job_id=jid,
                        video_bytes=video_bytes,
                        safe_name=safe_name,
                        ext=ext,
                        student_user_id=student_user_id,
                        session_id=session_id,
                        draft_id=draft_id,
                        title=title,
                        tags=tags,
                        is_universal=is_universal,
                        admin_user_id=request.user_id,
                        existing_storage_path=storage_path,
                        existing_bucket=bucket,
                    )
                except Exception as e:
                    sentry_sdk.capture_exception(e)
                    try:
                        db.update_copilot_reference_upload_job(
                            jid,
                            {"stage": "failed", "percent": 0, "error": str(e)[:2000], "message": "Processing failed"},
                        )
                    except Exception:
                        pass

            threading.Thread(target=_run_async_register, daemon=True, name=f"refvid-reg-{jid[:8]}").start()
            return jsonify({
                "job_id": jid,
                "poll_url": f"/v2/admin/copilot/reference-videos/upload-jobs/{jid}",
                "message": "File registered from storage. Poll GET poll_url for progress.",
            }), 202

        try:
            video_bytes = get_coach_object_bytes(bucket, storage_path)
            out = run_reference_video_upload(
                job_id=None,
                video_bytes=video_bytes,
                safe_name=safe_name,
                ext=ext,
                student_user_id=student_user_id,
                session_id=session_id,
                draft_id=draft_id,
                title=title,
                tags=tags,
                is_universal=is_universal,
                admin_user_id=request.user_id,
                existing_storage_path=storage_path,
                existing_bucket=bucket,
            )
        except Exception as e:
            sentry_sdk.capture_exception(e)
            emsg = str(e)
            logger.error("register-from-storage sync processing failed: %s", emsg)
            return jsonify(
                {
                    "code": "PROCESSING_FAILED",
                    "error": emsg[:2000] or "Reference video processing failed",
                }
            ), 500

        # Sync fallback: frontend expects a job_id. Reuse the reference_video id
        # so polling the (non-existent) job endpoint just shows "completed".
        ref_row = out.get("reference_video") or {}
        synthetic_job_id = str(ref_row.get("id") or uuid.uuid4())
        return jsonify(
            {
                "status": "ok",
                "job_id": synthetic_job_id,
                "sync": True,
                "reference_video": ref_row,
                "preview_url": out.get("preview_url"),
                "message": (
                    "Processed inline (upload-jobs table missing). "
                    "Run migrations/add_copilot_reference_upload_jobs.sql for async polling."
                ),
            }
        ), 201
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error("register-from-storage unexpected error: %s", e)
        return jsonify({"code": "V2_ERROR", "error": "Internal server error", "message": str(e)}), 500


def _json_safe_row(row: dict | None) -> dict | None:
    if not row:
        return None
    out: dict = {}
    for k, v in row.items():
        if hasattr(v, "isoformat") and callable(getattr(v, "isoformat", None)):
            dt = v
            if getattr(dt, "tzinfo", None) is None:
                dt = dt.replace(tzinfo=timezone.utc)
            out[k] = dt.isoformat().replace("+00:00", "Z")
        else:
            out[k] = v
    return out


@v2_bp.route("/admin/copilot/reference-videos/upload-jobs/<job_id>", methods=["GET"])
@require_admin
def v2_admin_copilot_reference_upload_job_status(job_id):
    try:
        try:
            job = db.get_copilot_reference_upload_job(job_id)
        except Exception as job_err:
            # Jobs table may not exist in this deployment; fall back to treating
            # the id as a reference_video id (sync-fallback path returns that).
            logger.info("upload-jobs status: jobs table unavailable (%s) — trying reference_video lookup", job_err)
            job = None
        if not job:
            # Sync-fallback synthetic job_id == reference_video.id. If that row
            # exists, the upload is effectively "completed" — synthesize a job
            # payload so the frontend polling loop terminates successfully.
            ref_row = None
            try:
                ref_row = db.get_admin_uploaded_reference_video(job_id)
            except Exception:
                ref_row = None
            if ref_row:
                storage_path = (ref_row.get("storage_path") or "").strip()
                meta = ref_row.get("feature_metadata") if isinstance(ref_row.get("feature_metadata"), dict) else {}
                bucket = (meta.get("bucket") or config.COACH_FEEDBACK_VIDEO_BUCKET).strip()
                preview_url = None
                if storage_path:
                    try:
                        preview_url = presigned_get_coach_object(bucket, storage_path, 3600, supabase_db=db)
                    except Exception:
                        preview_url = None
                synthetic_job = {
                    "id": job_id,
                    "stage": "completed",
                    "percent": 100,
                    "message": "Processed inline (upload-jobs table missing).",
                    "reference_video_id": ref_row.get("id"),
                    "reference_video": _json_safe_row(ref_row),
                    "preview_url": preview_url,
                    "synthetic": True,
                }
                return jsonify({"status": "ok", "job": synthetic_job}), 200
            return jsonify({"code": "JOB_NOT_FOUND", "error": "Upload job not found"}), 404
        payload = _json_safe_row(job) or {}
        rid = payload.get("reference_video_id")
        ref_row = None
        preview_url = None
        if rid:
            ref_row = db.get_admin_uploaded_reference_video(str(rid))
            if ref_row:
                storage_path = (ref_row.get("storage_path") or "").strip()
                meta = ref_row.get("feature_metadata") if isinstance(ref_row.get("feature_metadata"), dict) else {}
                bucket = (meta.get("bucket") or config.COACH_FEEDBACK_VIDEO_BUCKET).strip()
                if storage_path:
                    try:
                        preview_url = presigned_get_coach_object(bucket, storage_path, 3600, supabase_db=db)
                    except Exception:
                        preview_url = None
        payload["reference_video"] = _json_safe_row(ref_row) if ref_row else None
        payload["preview_url"] = preview_url
        return jsonify({"status": "ok", "job": payload}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error("upload-jobs status error: %s", e)
        return jsonify({"code": "V2_ERROR", "error": "Internal server error"}), 500


@v2_bp.route("/admin/copilot/reference-videos/<reference_video_id>/playback-url", methods=["GET"])
@require_admin
def v2_admin_copilot_reference_video_playback_url(reference_video_id):
    try:
        row = db.get_admin_uploaded_reference_video(reference_video_id)
        if not row:
            return jsonify({"code": "REFERENCE_VIDEO_NOT_FOUND", "error": "Reference video not found"}), 404
        meta = row.get("feature_metadata") if isinstance(row.get("feature_metadata"), dict) else {}
        bucket = (meta.get("bucket") or config.COACH_FEEDBACK_VIDEO_BUCKET).strip()
        storage_path = (row.get("storage_path") or "").strip()
        if not storage_path:
            return jsonify({"code": "INVALID_STATE", "error": "Reference video has no storage path"}), 500
        try:
            expires_in = int(request.args.get("expires_in", 48 * 3600))
        except (TypeError, ValueError):
            expires_in = 48 * 3600
        expires_in = max(60, min(172800, expires_in))
        signed_url = presigned_get_coach_object(bucket, storage_path, expires_in, supabase_db=db)
        if not signed_url:
            return jsonify({"code": "SIGNED_URL_FAILED", "error": "Could not create playback URL"}), 500
        return jsonify(
            {
                "status": "ok",
                "reference_video_id": reference_video_id,
                "storage_path": storage_path,
                "signed_url": signed_url,
                "expires_in": expires_in,
            }
        ), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.error("playback-url error: %s", e)
        return jsonify({"code": "V2_ERROR", "error": "Internal server error"}), 500


@v2_bp.route("/admin/copilot/students/<user_id>/drafts/<draft_id>/attach-reference-video", methods=["POST"])
@require_admin
def v2_admin_copilot_attach_reference_video(user_id, draft_id):
    try:
        body = request.get_json(silent=True) or {}
        reference_video_id = (body.get("reference_video_id") or "").strip()
        if not reference_video_id:
            return jsonify({"code": "INVALID_INPUT", "error": "reference_video_id is required"}), 400
        row = db.get_admin_student_send_draft(draft_id, user_id)
        if not row:
            return jsonify({"code": "DRAFT_NOT_FOUND", "error": "Draft not found"}), 404
        ref = db.get_admin_uploaded_reference_video(reference_video_id)
        if not ref:
            return jsonify({"code": "REFERENCE_VIDEO_NOT_FOUND", "error": "Reference video not found"}), 404
        meta = ref.get("feature_metadata") if isinstance(ref.get("feature_metadata"), dict) else {}
        bucket = (meta.get("bucket") or config.COACH_FEEDBACK_VIDEO_BUCKET).strip()
        path_clean = str(ref.get("storage_path") or "").strip().lstrip("/")
        if str(meta.get("storage_provider") or "").strip().lower() == "r2" and path_clean:
            storage_uri = f"r2://{bucket}/{path_clean}"
        else:
            storage_uri = _storage_uri(bucket, path_clean)

        payload = _normalize_copilot_payload(row)
        payload["script_mode"] = "full_video_override"
        payload["full_override_video_storage_path"] = storage_uri
        payload["full_override_video_url"] = None
        payload["reference_transcript_text"] = ref.get("transcript_text")
        payload["reference_tags"] = ref.get("tags") or []
        payload["is_universal_video"] = bool(ref.get("is_universal"))
        payload["reference_video_id"] = reference_video_id
        payload = _normalize_copilot_payload(row, payload)
        updated = (
            db.client.table("admin_student_send_drafts")
            .update({"draft_payload": payload, "updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", draft_id)
            .eq("user_id", user_id)
            .execute()
        )
        out = updated.data[0] if updated.data else row
        transcript_text = (ref.get("transcript_text") or "").strip()
        if transcript_text:
            try:
                db.create_admin_annotation_event(
                    user_id=user_id,
                    session_id=row.get("session_id"),
                    section_type="assignment",
                    field_name="reference_video_transcript",
                    ai_original_text=(
                        (_normalize_copilot_payload(row).get("ai_script_draft") or row.get("ai_draft_video_script") or "")
                    )[:4000] or None,
                    coach_final_text=transcript_text[:4000],
                    reason_chip="video_override",
                    custom_reason=f"reference_video_id={reference_video_id}",
                    created_by=request.user_id,
                    draft_id=str(row.get("id") or "") or None,
                    previous_value_hash=None,
                    new_value_hash=_value_hash(transcript_text[:4000]),
                )
            except Exception as ann_err:
                logger.warning("attach reference video annotation failed: %s", ann_err)
        return jsonify({"status": "ok", "draft": _serialize_copilot_draft(out), "reference_video": ref}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/copilot/students/<user_id>/audit", methods=["GET", "PUT"])
@require_admin
def v2_admin_copilot_student_audit(user_id):
    try:
        if request.method == "GET":
            session_id = (request.args.get("session_id") or "").strip() or None
            row = _pick_student_draft(user_id, session_id=session_id, include_sent=True)
            return jsonify({"audit": _serialize_copilot_draft(row) if row else None}), 200

        body = request.get_json(silent=True) or {}
        session_id = (body.get("session_id") or "").strip() or None
        draft_id = (body.get("draft_id") or "").strip() or None
        row = _pick_student_draft(user_id, session_id=session_id, draft_id=draft_id, include_sent=True)
        if not row:
            # Create-on-missing: auto-create draft row, then retry
            _ensure_draft_exists_for_user(user_id)
            row = _pick_student_draft(user_id, session_id=session_id, draft_id=draft_id, include_sent=True)
        if not row:
            return jsonify({"code": "DRAFT_NOT_FOUND", "error": "Draft not found"}), 404
        payload = _draft_payload(row)
        old_corrected = (payload.get("corrected_insight") or "").strip()
        old_good_as_is = bool(payload.get("good_as_is"))
        ai_insight = (payload.get("ai_insight") or "").strip() or None
        if "good_as_is" in body:
            payload["good_as_is"] = bool(body.get("good_as_is"))
        if "corrected_insight" in body:
            payload["corrected_insight"] = body.get("corrected_insight")
        if "reason_chips" in body:
            payload["reason_chips"] = body.get("reason_chips")
        if "reason_chip_custom" in body:
            payload["reason_chip_custom"] = body.get("reason_chip_custom")
        payload["approved_at"] = datetime.now(timezone.utc).isoformat()
        payload["state"] = "Ready" if str(row.get("status") or "").lower() != "sent" else "Sent"
        updated = (
            db.client.table("admin_student_send_drafts")
            .update({"draft_payload": payload, "updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", row.get("id"))
            .eq("user_id", user_id)
            .execute()
        )
        out = updated.data[0] if updated.data else row
        if out.get("session_id"):
            try:
                db.v2_update_session(str(out.get("session_id")), user_id, {
                    "is_insight_audited": True,
                    "coach_corrected_insight": payload.get("corrected_insight"),
                })
            except Exception:
                pass
        try:
            new_corrected = (payload.get("corrected_insight") or "").strip()
            new_good_as_is = bool(payload.get("good_as_is"))
            if "corrected_insight" in body and old_corrected != new_corrected:
                db.create_admin_annotation_event(
                    user_id=user_id,
                    session_id=row.get("session_id"),
                    section_type="post_hoc_audit",
                    field_name="coach_insight",
                    ai_original_text=ai_insight,
                    coach_final_text=new_corrected or None,
                    reason_chip=((body.get("reason_chips") or [None])[0] if isinstance(body.get("reason_chips"), list) else body.get("reason_chip")),
                    custom_reason=body.get("reason_chip_custom"),
                    created_by=request.user_id,
                )
            elif "good_as_is" in body and (not old_good_as_is and new_good_as_is):
                db.create_admin_annotation_event(
                    user_id=user_id,
                    session_id=row.get("session_id"),
                    section_type="post_hoc_audit",
                    field_name="coach_insight",
                    ai_original_text=ai_insight,
                    coach_final_text=ai_insight,
                    reason_chip="good_as_is",
                    custom_reason=None,
                    created_by=request.user_id,
                )
        except Exception as ann_err:
            logger.warning("copilot audit annotation event failed: %s", ann_err)
        return jsonify({"status": "ok", "audit": _serialize_copilot_draft(out)}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/copilot/students/<user_id>/approve", methods=["POST"])
@require_admin
def v2_admin_copilot_student_approve(user_id):
    try:
        body = request.get_json(silent=True) or {}
        session_id = (body.get("session_id") or "").strip() or None
        draft_id = (body.get("draft_id") or "").strip() or None
        row = _pick_student_draft(user_id, session_id=session_id, draft_id=draft_id, include_sent=False)
        if not row:
            _ensure_draft_exists_for_user(user_id)
            row = _pick_student_draft(user_id, session_id=session_id, draft_id=draft_id, include_sent=False)
        if not row:
            return jsonify({"code": "DRAFT_NOT_FOUND", "error": "Draft not found"}), 404
        payload = _draft_payload(row)
        payload["state"] = "Ready"
        payload["approved_at"] = datetime.now(timezone.utc).isoformat()
        updated = (
            db.client.table("admin_student_send_drafts")
            .update({"draft_payload": payload, "updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", row.get("id"))
            .eq("user_id", user_id)
            .execute()
        )
        out = updated.data[0] if updated.data else row
        return jsonify({"status": "ok", "state": "Ready", "draft": _serialize_copilot_draft(out)}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/copilot/students/<user_id>/send", methods=["POST"])
@require_admin
def v2_admin_copilot_student_send(user_id):
    try:
        body = request.get_json(silent=True) or {}
        session_id = (body.get("session_id") or "").strip() or None
        draft_id = (body.get("draft_id") or "").strip() or None
        row = _pick_student_draft(user_id, session_id=session_id, draft_id=draft_id, include_sent=True)
        if not row:
            _ensure_draft_exists_for_user(user_id)
            row = _pick_student_draft(user_id, session_id=session_id, draft_id=draft_id, include_sent=True)
        if not row:
            return jsonify({"code": "DRAFT_NOT_FOUND", "error": "Draft not found"}), 404
        if str(row.get("status") or "").lower() == "sent":
            return jsonify({"status": "ok", "state": "Sent", "sent_at": row.get("sent_at")}), 200
        payload = _normalize_copilot_payload(row, _draft_payload(row))
        video_url_raw = body.get("video_url")
        if video_url_raw is None or (isinstance(video_url_raw, str) and not str(video_url_raw).strip()):
            video_url_raw = payload.get("video_url")
        video_url = None
        if video_url_raw is not None and str(video_url_raw).strip():
            s2 = str(video_url_raw).strip()
            video_url = validate_video_url(video_url_raw)
            if video_url is None and s2.startswith("storage://") and parse_storage_uri(s2):
                video_url = s2
            if video_url is None and s2.startswith("r2://") and parse_r2_uri(s2):
                video_url = s2
        if video_url_raw is not None and str(video_url_raw).strip() and video_url is None:
            return jsonify({"code": "INVALID_VIDEO_URL", "error": "video_url must be a valid URL (http/https, max 2048 chars)"}), 400
        # Same fallback as approve-send: when no plain video_url is set, use the reference-video
        # storage URI that /attach-reference-video wrote into the draft payload. See the matching
        # comment block in v2_admin_student_draft_approve_send for details.
        video_bucket_override: str | None = None
        video_storage_path_override: str | None = None
        if not video_url:
            override_storage = payload.get("full_override_video_storage_path")
            if isinstance(override_storage, str):
                s_override = override_storage.strip()
                if s_override.startswith("r2://") and parse_r2_uri(s_override):
                    video_url = s_override
                elif s_override.startswith("storage://"):
                    parsed_override = parse_storage_uri(s_override)
                    if parsed_override:
                        video_bucket_override, video_storage_path_override = parsed_override
            if not (video_bucket_override and video_storage_path_override):
                override_url = payload.get("full_override_video_url")
                if isinstance(override_url, str) and override_url.strip():
                    validated_override = validate_video_url(override_url.strip())
                    if validated_override:
                        video_url = validated_override
        final_message = (
            payload.get("email_draft")
            or payload.get("email_message")
            or payload.get("homework_comment")
            or payload.get("ai_email_draft")
            or row.get("ai_draft_message")
            or ""
        )
        student_email = (db.get_user_email_from_auth(user_id) or "").strip()
        if not student_email:
            return jsonify({"code": "NO_EMAIL", "error": "Student has no email in auth"}), 400
        desc = (final_message or "").strip() or None
        delivery, send_err = _deliver_homework_assignment_core(
            user_id,
            student_email,
            video_url=video_url,
            video_description=desc,
            video_bucket=video_bucket_override,
            video_storage_path=video_storage_path_override,
        )
        if send_err:
            err_lower = (send_err or "").lower()
            if "resend api key" in err_lower or "api key not set" in err_lower:
                return jsonify(
                    {
                        "code": "EMAIL_NOT_CONFIGURED",
                        "error": send_err,
                        "hint": "Set RESEND_API_KEY and RESEND_FROM_EMAIL with SEND_EMAILS=true, or use SEND_EMAILS=false to unlock without sending email. For staging, HOMEWORK_UNLOCK_WHEN_EMAIL_FAILS=true still unlocks if email fails.",
                    }
                ), 503
            return jsonify({"code": "EMAIL_FAILED", "error": send_err}), 500
        send_result = delivery["email"]
        sniper_profile = delivery["sniper_profile"]
        task_sync = _first_non_empty(
            payload.get("task_draft"),
            payload.get("task_text"),
            row.get("master_task_text"),
            payload.get("ai_task_suggestion"),
            row.get("ai_suggested_task_text"),
        )
        try:
            db.v2_apply_coach_homework_task_text(user_id, task_sync)
        except Exception as task_sync_err:
            logger.warning("copilot send: task sync failed user_id=%s: %s", user_id, task_sync_err)
        updated = db.mark_admin_student_send_draft_sent(str(row.get("id")), user_id, request.user_id) or row
        try:
            ai_message = (
                payload.get("ai_email_draft")
                or row.get("ai_draft_message")
                or ""
            )
            if (ai_message or "").strip() and (final_message or "").strip() and ai_message.strip() != final_message.strip():
                db.create_admin_annotation_event(
                    user_id=user_id,
                    session_id=row.get("session_id"),
                    section_type="assignment",
                    field_name="email_message",
                    ai_original_text=ai_message,
                    coach_final_text=final_message,
                    reason_chip="manual_edit",
                    custom_reason=None,
                    created_by=request.user_id,
                )
        except Exception as ann_err:
            logger.warning("copilot send annotation event failed: %s", ann_err)
        return jsonify(
            {
                "status": "ok",
                "state": "Sent",
                "sent_at": updated.get("sent_at"),
                "sent": send_result.get("sent", False),
                "email_status": send_result.get("status"),
                "email_failed_but_unlocked": bool(delivery.get("email_failed_but_unlocked")),
                "sniper_profile": sniper_profile,
                "realtime_level": sniper_profile.get("realtime_level"),
                "realtime_step": sniper_profile.get("realtime_step"),
                "draft": _serialize_copilot_draft(updated),
                "synced_task_to_student": bool((task_sync or "").strip()),
            }
        ), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/cohorts/<profile>/<int:stage>/approve-task", methods=["POST"])
@v2_bp.route("/admin/copilot/cohorts/<profile>/<int:stage>/approve-task", methods=["POST"])
@v2_bp.route("/admin/acoustic-dojo/cohorts/<profile>/<int:stage>/approve-task", methods=["POST"])
@require_admin
def v2_admin_cohort_approve_task(profile, stage):
    try:
        body = request.get_json(silent=True) or {}
        master_task_text = (body.get("master_task_text") or "").strip()
        if not master_task_text:
            return jsonify({"code": "INVALID_INPUT", "error": "master_task_text is required"}), 400
        try:
            ai_prefill_limit = int(body.get("ai_prefill_limit", 25))
        except (TypeError, ValueError):
            ai_prefill_limit = 25
        ai_prefill_limit = max(0, min(500, ai_prefill_limit))
        target_ids = body.get("user_ids")
        if target_ids is not None and not isinstance(target_ids, list):
            return jsonify({"code": "INVALID_INPUT", "error": "user_ids must be an array"}), 400
        target_ids = {str(x) for x in (target_ids or []) if str(x).strip()}

        rows = []
        ai_prefill_count = 0
        all_ids = db.list_recent_student_ids(limit=600)
        for uid in all_ids:
            sp = db.get_sniper_profile(uid) or {}
            display_profile = (sp.get("coach_override_profile") or "").strip() or (sp.get("behavioral_profile") or "").strip() or "Unclassified"
            display_stage = int(sp.get("coach_override_stage") or sp.get("computed_stage") or 1)
            if display_profile != profile or display_stage != int(stage):
                continue
            if target_ids and uid not in target_ids:
                continue
            latest_session = db.v2_get_last_completed_session(uid) or {}
            prefill = {}
            if ai_prefill_count < ai_prefill_limit:
                prefill = _generate_assignment_prefill_for_user(uid, master_task_text)
                ai_prefill_count += 1
            ai_task = (prefill.get("ai_suggested_task_text") or "").strip() or master_task_text
            ai_message = (prefill.get("ai_draft_message") or "").strip() or None
            ai_script = (prefill.get("ai_draft_video_script") or "").strip() or None
            rows.append(
                {
                    "user_id": uid,
                    "session_id": latest_session.get("id"),
                    "cohort_profile": profile,
                    "cohort_stage": int(stage),
                    "master_task_text": master_task_text,
                    "ai_suggested_task_text": ai_task,
                    "ai_draft_message": ai_message,
                    "ai_draft_video_script": ai_script,
                    "draft_payload": {
                        "ai_task_suggestion": ai_task,
                        "ai_email_draft": ai_message,
                        "ai_script_draft": ai_script,
                        "task_draft": ai_task,
                        "email_draft": (body.get("email_message") or "").strip() or ai_message or None,
                        "script_draft": (body.get("video_script") or "").strip() or ai_script or None,
                        "video_script": (body.get("video_script") or "").strip() or ai_script or None,
                        "task_text": master_task_text,
                        "email_message": (body.get("email_message") or "").strip() or ai_message or None,
                        "homework_comment": (body.get("homework_comment") or "").strip() or None,
                    },
                    "status": "pending",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        try:
            inserted = db.insert_admin_student_send_drafts(rows)
        except Exception:
            # Backward-compatible insert if ai_* columns are not migrated yet.
            rows_legacy = []
            for r in rows:
                rr = dict(r)
                rr.pop("ai_suggested_task_text", None)
                rr.pop("ai_draft_message", None)
                rr.pop("ai_draft_video_script", None)
                rows_legacy.append(rr)
            inserted = db.insert_admin_student_send_drafts(rows_legacy)
        return jsonify({"status": "ok", "inserted_count": len(inserted), "drafts": inserted}), 201
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/drafts/<draft_id>/approve-send", methods=["POST"])
@v2_bp.route("/admin/copilot/students/<user_id>/drafts/<draft_id>/approve-send", methods=["POST"])
@require_admin
def v2_admin_student_draft_approve_send(user_id, draft_id):
    try:
        body = request.get_json(silent=True) or {}
        row = db.get_admin_student_send_draft(draft_id, user_id)
        if not row:
            return jsonify({"code": "DRAFT_NOT_FOUND", "error": "Draft not found"}), 404
        if row.get("status") == "sent":
            return jsonify({"status": "ok", "already_sent": True, "draft_id": draft_id}), 200
        payload_for_mode = _normalize_copilot_payload(row)
        script_mode = resolve_script_mode(payload_for_mode)
        # If the coach already uploaded a reference video for this draft via
        # Training Studio, skip the AI pipeline entirely — we have a real
        # video, no need to generate one. Treat it as full_video_override.
        has_uploaded_ref_video = False
        try:
            _ref_preview = db.get_latest_admin_uploaded_reference_video_for_user(
                user_id, draft_id=str(row.get("id") or "") or None,
            )
            if _ref_preview and (_ref_preview.get("storage_path") or _ref_preview.get("source_video_url")):
                has_uploaded_ref_video = True
                logger.info(
                    "approve-send: skipping pipeline — admin uploaded reference video id=%s for draft=%s",
                    _ref_preview.get("id"), row.get("id"),
                )
        except Exception as ref_check_err:
            logger.warning("approve-send: ref video pre-check failed: %s", ref_check_err)
        # If we're skipping the pipeline because the admin uploaded a real
        # video, clear any stale pipeline_status on the draft so the frontend
        # polling loop terminates (otherwise the UI keeps GET'ing
        # /pipeline-status forever because it sees "queued" on the old row).
        if has_uploaded_ref_video:
            stale_status = (row.get("pipeline_status") or "").strip().lower()
            if stale_status and stale_status not in ("sent", "failed", ""):
                try:
                    db.update_admin_student_send_draft_pipeline_status(
                        draft_id=str(row.get("id")),
                        user_id=user_id,
                        status="sent",
                        error=None,
                    )
                    logger.info(
                        "approve-send: cleared stale pipeline_status=%s on draft=%s (using uploaded ref video)",
                        stale_status, row.get("id"),
                    )
                except Exception as clear_err:
                    logger.warning("approve-send: could not clear stale pipeline_status: %s", clear_err)
        if _video_pipeline_enabled() and not has_uploaded_ref_video:
            # full_video_override already points to a coach-selected video; no render job is needed,
            # so send immediately instead of queueing a pipeline job.
            if script_mode != "full_video_override":
                if _is_pipeline_running(row):
                    return jsonify(
                        {
                            "status": "ok",
                            "queued": True,
                            "already_processing": True,
                            "pipeline_job_id": row.get("pipeline_job_id"),
                            "pipeline_status": row.get("pipeline_status"),
                            "draft": _serialize_copilot_draft(row),
                        }
                    ), 202
                updated, pipeline_job_id = _queue_video_pipeline_for_draft(
                    row,
                    user_id=user_id,
                    actor_id=getattr(request, "user_id", None),
                )
                payload = _normalize_copilot_payload(updated or row)
                ai_script = (payload.get("ai_script_draft") or row.get("ai_draft_video_script") or "").strip()
                final_script = (payload.get("script_draft") or payload.get("video_script") or "").strip()
                if ai_script and final_script and ai_script != final_script:
                    try:
                        db.create_admin_annotation_event(
                            user_id=user_id,
                            session_id=row.get("session_id"),
                            section_type="assignment",
                            field_name="script_draft",
                            ai_original_text=ai_script,
                            coach_final_text=final_script,
                            reason_chip="manual_edit",
                            custom_reason=None,
                            created_by=request.user_id,
                            draft_id=str(row.get("id") or "") or None,
                            previous_value_hash=_value_hash(ai_script),
                            new_value_hash=_value_hash(final_script),
                        )
                    except Exception as ann_err:
                        logger.warning("pipeline enqueue annotation failed: %s", ann_err)
                return jsonify(
                    {
                        "status": "ok",
                        "queued": True,
                        "pipeline_job_id": pipeline_job_id,
                        "pipeline_status": (updated or {}).get("pipeline_status") or "queued",
                        "draft": _serialize_copilot_draft(updated or row),
                    }
                ), 202
        raw_payload = row.get("draft_payload") if isinstance(row.get("draft_payload"), dict) else {}
        payload = _normalize_copilot_payload(row, raw_payload)
        video_url_raw = body.get("video_url")
        if video_url_raw is None or (isinstance(video_url_raw, str) and not str(video_url_raw).strip()):
            video_url_raw = payload.get("video_url")
        video_url = None
        if video_url_raw is not None and str(video_url_raw).strip():
            s2 = str(video_url_raw).strip()
            video_url = validate_video_url(video_url_raw)
            if video_url is None and s2.startswith("storage://") and parse_storage_uri(s2):
                video_url = s2
            if video_url is None and s2.startswith("r2://") and parse_r2_uri(s2):
                video_url = s2
        if video_url_raw is not None and str(video_url_raw).strip() and video_url is None:
            return jsonify({"code": "INVALID_VIDEO_URL", "error": "video_url must be a valid URL (http/https, max 2048 chars)"}), 400
        # If no plain video_url was set, fall back to the reference-video the coach attached from
        # Training Studio. POST /admin/copilot/students/<id>/drafts/<id>/attach-reference-video
        # writes the upload's location into draft_payload.full_override_video_storage_path as a
        # "storage://bucket/path" URI (see _storage_uri() / attach handler). We parse it here and
        # pass bucket+path explicitly so _deliver_homework_assignment_core persists all three
        # fields atomically into v2_student_overrides (matching the pipeline finalize path); the
        # student's step-0 screen then resolves a signed playable URL via
        # services.tutor_video_url.resolve_tutor_video_playable_url.
        video_bucket_override: str | None = None
        video_storage_path_override: str | None = None
        if not video_url:
            override_storage = payload.get("full_override_video_storage_path")
            if isinstance(override_storage, str):
                s_override = override_storage.strip()
                if s_override.startswith("r2://") and parse_r2_uri(s_override):
                    video_url = s_override
                elif s_override.startswith("storage://"):
                    parsed_override = parse_storage_uri(s_override)
                    if parsed_override:
                        video_bucket_override, video_storage_path_override = parsed_override
            if not (video_bucket_override and video_storage_path_override):
                override_url = payload.get("full_override_video_url")
                if isinstance(override_url, str) and override_url.strip():
                    validated_override = validate_video_url(override_url.strip())
                    if validated_override:
                        video_url = validated_override
        final_message = (
            payload.get("email_draft")
            or payload.get("email_message")
            or payload.get("homework_comment")
            or payload.get("ai_email_draft")
            or row.get("ai_draft_message")
            or ""
        )
        student_email = (db.get_user_email_from_auth(user_id) or "").strip()
        if not student_email:
            return jsonify({"code": "NO_EMAIL", "error": "Student has no email in auth"}), 400
        desc = (final_message or "").strip() or None
        delivery, send_err = _deliver_homework_assignment_core(
            user_id,
            student_email,
            video_url=video_url,
            video_description=desc,
            video_bucket=video_bucket_override,
            video_storage_path=video_storage_path_override,
        )
        if send_err:
            err_lower = (send_err or "").lower()
            if "resend api key" in err_lower or "api key not set" in err_lower:
                return jsonify(
                    {
                        "code": "EMAIL_NOT_CONFIGURED",
                        "error": send_err,
                        "hint": "Set RESEND_API_KEY and RESEND_FROM_EMAIL with SEND_EMAILS=true, or use SEND_EMAILS=false to unlock without sending email. For staging, HOMEWORK_UNLOCK_WHEN_EMAIL_FAILS=true still unlocks if email fails.",
                    }
                ), 503
            return jsonify({"code": "EMAIL_FAILED", "error": send_err}), 500
        send_result = delivery["email"]
        sniper_profile = delivery["sniper_profile"]
        task_sync = _first_non_empty(
            payload.get("task_draft"),
            payload.get("task_text"),
            row.get("master_task_text"),
            payload.get("ai_task_suggestion"),
            row.get("ai_suggested_task_text"),
        )
        try:
            db.v2_apply_coach_homework_task_text(user_id, task_sync)
        except Exception as task_sync_err:
            logger.warning("approve-send: task sync failed user_id=%s: %s", user_id, task_sync_err)
        updated = db.mark_admin_student_send_draft_sent(draft_id, user_id, request.user_id)
        try:
            ai_message = (
                payload.get("ai_email_draft")
                or row.get("ai_draft_message")
                or ""
            )
            if (ai_message or "").strip() and (final_message or "").strip() and ai_message.strip() != final_message.strip():
                db.create_admin_annotation_event(
                    user_id=user_id,
                    session_id=row.get("session_id"),
                    section_type="assignment",
                    field_name="email_message",
                    ai_original_text=ai_message,
                    coach_final_text=final_message,
                    reason_chip="manual_edit",
                    custom_reason=None,
                    created_by=request.user_id,
                )
        except Exception as ann_err:
            logger.warning("approve-send annotation event failed: %s", ann_err)
        return jsonify(
            {
                "status": "ok",
                "draft": updated,
                "email": send_result,
                "sent": send_result.get("sent", False),
                "email_status": send_result.get("status"),
                "email_failed_but_unlocked": bool(delivery.get("email_failed_but_unlocked")),
                "sniper_profile": sniper_profile,
                "realtime_level": sniper_profile.get("realtime_level"),
                "realtime_step": sniper_profile.get("realtime_step"),
                "synced_task_to_student": bool((task_sync or "").strip()),
            }
        ), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/drafts/<draft_id>/pipeline-status", methods=["GET"])
@v2_bp.route("/admin/copilot/students/<user_id>/drafts/<draft_id>/pipeline-status", methods=["GET"])
@require_admin
def v2_admin_student_draft_pipeline_status(user_id, draft_id):
    try:
        row = db.get_admin_student_send_draft(draft_id, user_id)
        if not row:
            return jsonify({"code": "DRAFT_NOT_FOUND", "error": "Draft not found"}), 404
        return jsonify(
            {
                "status": "ok",
                "pipeline_status": row.get("pipeline_status"),
                "pipeline_error": row.get("pipeline_error"),
                "pipeline_job_id": row.get("pipeline_job_id"),
                "pipeline_started_at": row.get("pipeline_started_at"),
                "pipeline_finished_at": row.get("pipeline_finished_at"),
                "feedback_video_storage_path": row.get("feedback_video_storage_path"),
                "draft": _serialize_copilot_draft(row),
            }
        ), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/drafts/<draft_id>/feedback-video-url", methods=["GET"])
@v2_bp.route("/admin/copilot/students/<user_id>/drafts/<draft_id>/feedback-video-url", methods=["GET"])
@require_admin
def v2_admin_student_draft_feedback_video_url(user_id, draft_id):
    try:
        row = db.get_admin_student_send_draft(draft_id, user_id)
        if not row:
            return jsonify({"code": "DRAFT_NOT_FOUND", "error": "Draft not found"}), 404
        storage_path = (row.get("feedback_video_storage_path") or "").strip()
        if not storage_path:
            return jsonify({"code": "VIDEO_NOT_READY", "error": "No generated feedback video yet"}), 409
        try:
            expires_in = int(request.args.get("expires_in", 48 * 3600))
        except (TypeError, ValueError):
            expires_in = 48 * 3600
        expires_in = max(60, min(172800, expires_in))
        signed_url = _signed_feedback_video_url(storage_path, expires_in=expires_in)
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
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/internal/copilot/drafts/<draft_id>/pipeline/finalize", methods=["POST"])
def v2_admin_internal_copilot_pipeline_finalize(draft_id):
    try:
        if not _pipeline_secret_matches():
            return jsonify({"code": "UNAUTHORIZED", "error": "Invalid or missing X-Internal-Secret"}), 401
        body = request.get_json(silent=True) or {}
        row_res = db.client.table("admin_student_send_drafts").select("*").eq("id", draft_id).limit(1).execute()
        row = row_res.data[0] if row_res.data else None
        if not row:
            return jsonify({"code": "DRAFT_NOT_FOUND", "error": "Draft not found"}), 404
        storage_path = (body.get("feedback_video_storage_path") or row.get("feedback_video_storage_path") or "").strip()
        if not storage_path:
            return jsonify({"code": "INVALID_INPUT", "error": "feedback_video_storage_path is required"}), 400
        script_manifest = body.get("script_manifest") if isinstance(body.get("script_manifest"), dict) else (
            row.get("script_manifest") if isinstance(row.get("script_manifest"), dict) else {}
        )
        db.update_admin_student_send_draft_pipeline_status(
            draft_id=str(row.get("id") or ""),
            user_id=str(row.get("user_id") or ""),
            status="uploading",
            error=None,
        )
        updated, email_result, task_sync = _finalize_pipeline_delivery_for_row(
            row=row,
            storage_path=storage_path,
            script_manifest=script_manifest,
            approved_by=str(body.get("approved_by") or "internal:copilot-video-pipeline"),
        )
        if str((row.get("script_mode") or "")).strip().lower() == "full_video_override":
            payload = _normalize_copilot_payload(row)
            db.create_admin_uploaded_reference_video(
                draft_id=str(row.get("id") or ""),
                user_id=str(row.get("user_id") or ""),
                session_id=row.get("session_id"),
                storage_path=storage_path,
                source_video_url=payload.get("full_override_video_url"),
                transcript_text=payload.get("reference_transcript_text"),
                feature_metadata={"script_manifest": script_manifest or {}},
                tags=parse_reference_tags(payload),
                is_universal=parse_bool(payload.get("is_universal_video"), False),
                created_by=None,
            )
        return jsonify(
            {
                "status": "ok",
                "draft": _serialize_copilot_draft(updated or row),
                "email": email_result,
                "synced_task_to_student": bool((task_sync or "").strip()),
            }
        ), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/internal/copilot/drafts/<draft_id>/pipeline/process", methods=["POST"])
def v2_admin_internal_copilot_pipeline_process(draft_id):
    try:
        if not _pipeline_secret_matches():
            return jsonify({"code": "UNAUTHORIZED", "error": "Invalid or missing X-Internal-Secret"}), 401
        row_res = db.client.table("admin_student_send_drafts").select("*").eq("id", draft_id).limit(1).execute()
        row = row_res.data[0] if row_res.data else None
        if not row:
            return jsonify({"code": "DRAFT_NOT_FOUND", "error": "Draft not found"}), 404
        if str(row.get("status") or "").lower() == "sent":
            return jsonify({"status": "ok", "already_sent": True, "draft": _serialize_copilot_draft(row)}), 200

        payload = _normalize_copilot_payload(row)
        script_mode = str(row.get("script_mode") or resolve_script_mode(payload)).strip().lower()
        script_manifest = row.get("script_manifest") if isinstance(row.get("script_manifest"), dict) else {}
        if not script_manifest:
            script_manifest = build_script_manifest(row, payload, script_mode)
            db.queue_admin_student_send_draft_pipeline(
                draft_id=str(row.get("id") or ""),
                user_id=str(row.get("user_id") or ""),
                pipeline_job_id=str(row.get("pipeline_job_id") or uuid.uuid4()),
                script_mode=script_mode,
                script_manifest=script_manifest,
                created_by=str(row.get("approved_by") or ""),
            )

        db.update_admin_student_send_draft_pipeline_status(
            draft_id=str(row.get("id") or ""),
            user_id=str(row.get("user_id") or ""),
            status=_pipeline_phase_from_mode(script_mode),
            error=None,
        )

        if script_mode == "full_video_override":
            video_bytes = fetch_override_video_bytes(script_manifest)
        else:
            video_bytes = generate_video_from_script(script_manifest)

        db.update_admin_student_send_draft_pipeline_status(
            draft_id=str(row.get("id") or ""),
            user_id=str(row.get("user_id") or ""),
            status="uploading",
            error=None,
        )
        storage_path = build_feedback_video_storage_path(str(row.get("user_id") or ""), row.get("session_id"))
        put_coach_object_bytes(config.COACH_FEEDBACK_VIDEO_BUCKET, storage_path, video_bytes, "video/mp4")

        updated, email_result, task_sync = _finalize_pipeline_delivery_for_row(
            row=row,
            storage_path=storage_path,
            script_manifest=script_manifest,
            approved_by=str(row.get("approved_by") or "internal:copilot-video-pipeline"),
        )
        if script_mode == "full_video_override":
            db.create_admin_uploaded_reference_video(
                draft_id=str(row.get("id") or ""),
                user_id=str(row.get("user_id") or ""),
                session_id=row.get("session_id"),
                storage_path=storage_path,
                source_video_url=payload.get("full_override_video_url") or coach_media_public_url(storage_path),
                transcript_text=payload.get("reference_transcript_text"),
                feature_metadata={
                    "script_manifest": script_manifest or {},
                    "storage_provider": "r2" if coach_videos_use_r2() else "supabase",
                    "bucket": r2_bucket_name() if coach_videos_use_r2() else config.COACH_FEEDBACK_VIDEO_BUCKET,
                },
                tags=parse_reference_tags(payload),
                is_universal=parse_bool(payload.get("is_universal_video"), False),
                created_by=None,
            )
        return jsonify(
            {
                "status": "ok",
                "draft": _serialize_copilot_draft(updated or row),
                "email": email_result,
                "synced_task_to_student": bool((task_sync or "").strip()),
            }
        ), 200
    except Exception as e:
        logger.warning("copilot video pipeline process failed for draft_id=%s: %s", draft_id, e, exc_info=True)
        row = None
        try:
            row_res = db.client.table("admin_student_send_drafts").select("id,user_id").eq("id", draft_id).limit(1).execute()
            row = row_res.data[0] if row_res.data else None
            if row:
                db.update_admin_student_send_draft_pipeline_status(
                    draft_id=str(row.get("id") or ""),
                    user_id=str(row.get("user_id") or ""),
                    status="failed",
                    error=str(e)[:1000],
                )
        except Exception:
            pass
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "PIPELINE_FAILED", "error": str(e)}), 500
