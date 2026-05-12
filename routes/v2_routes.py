"""
V2: admin CRUD only. Student flow is homework only (routes/homework.py).
All /v2/admin/* require auth + admin.
"""
from flask import Blueprint, request, jsonify, make_response
from config import Config
from auth import require_auth
from routes.admin import require_admin, is_admin
from services.annotation_export import result_to_dict, run_annotation_export
from services.behavioral_profiles import PROFILE_VALUES
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
import re
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from werkzeug.utils import secure_filename
from io import BytesIO
import threading

from services.reference_video_upload_worker import run_reference_video_upload
from services.draft_delivery import (
    auto_approve_payload_for_send,
    infer_delivery_lifecycle,
    log_rlhf_auto_accept_events,
)

logger = logging.getLogger(__name__)
v2_bp = Blueprint("v2", __name__, url_prefix="/v2")
config = Config()


def _json_admin_no_store(payload, status=200):
    """Admin profile responses must not be served from stale caches."""
    response = make_response(jsonify(payload), status)
    response.headers["Cache-Control"] = "private, no-store, max-age=0, must-revalidate"
    response.headers["Vary"] = "Authorization"
    return response


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
_REFERENCE_VIDEO_ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv", ".m4a"}


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


_REFERENCE_UPLOAD_USER_KEYS = (
    "user_id",
    "student_user_id",
    "context_user_id",
    "selected_user_id",
    "selected_context_user_id",
    "user_email",
    "student_email",
    "context_user_email",
    "selected_user_email",
)


def _extract_reference_upload_user_value(getter):
    for key in _REFERENCE_UPLOAD_USER_KEYS:
        try:
            raw = (getter(key) or "").strip()
        except Exception:
            raw = ""
        if raw:
            return raw
    return ""


def _resolve_reference_upload_user_id(raw_user_value: str):
    raw = (raw_user_value or "").strip()
    if not raw:
        return None, "user_id is required (UUID or student email)"
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


def _extract_learning_profile_update(data: dict | None) -> dict:
    """Accept legacy/frontend aliases and map them to student_profile override fields."""
    data = data if isinstance(data, dict) else {}
    nested = data.get("learning_profile")
    nested = nested if isinstance(nested, dict) else {}

    def _first(*keys):
        for key in keys:
            if key in data:
                return data.get(key)
            if key in nested:
                return nested.get(key)
        return None

    fields: dict = {}

    if any(
        k in data or k in nested
        for k in (
            "coach_override_profile",
            "selectedArchetype",
            "selected_archetype",
            "display_profile",
            "learning_profile_name",
        )
    ):
        raw = _first(
            "coach_override_profile",
            "selectedArchetype",
            "selected_archetype",
            "display_profile",
            "learning_profile_name",
        )
        if raw is None:
            fields["coach_override_profile"] = None
        else:
            s = str(raw).strip()
            fields["coach_override_profile"] = s or None

    if any(
        k in data or k in nested
        for k in (
            "profile_override_justification",
            "learning_profile_justification",
            "justification",
            "display_justification",
        )
    ):
        raw = _first(
            "profile_override_justification",
            "learning_profile_justification",
            "justification",
            "display_justification",
        )
        if raw is None:
            fields["profile_override_justification"] = None
        else:
            s = str(raw).strip()
            fields["profile_override_justification"] = s or None

    if any(k in data or k in nested for k in ("coach_override_stage", "selectedStage", "selected_stage", "display_stage")):
        raw = _first("coach_override_stage", "selectedStage", "selected_stage", "display_stage")
        if raw in (None, ""):
            fields["coach_override_stage"] = None
        else:
            try:
                stage = int(raw)
            except (TypeError, ValueError):
                raise ValueError("coach_override_stage must be integer 1..5 or null")
            if stage < 1 or stage > 5:
                raise ValueError("coach_override_stage must be integer 1..5 or null")
            fields["coach_override_stage"] = stage

    if any(
        k in data or k in nested
        for k in (
            "stage_override_justification",
            "stageJustification",
            "stage_justification",
        )
    ):
        raw = _first("stage_override_justification", "stageJustification", "stage_justification")
        if raw is None:
            fields["stage_override_justification"] = None
        else:
            s = str(raw).strip()
            fields["stage_override_justification"] = s or None

    return fields


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
        return _json_admin_no_store({
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
        }, 200)
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/speaker-profile", methods=["PUT"])
@require_admin
def v2_admin_student_speaker_profile(user_id):
    """Update speaker profile (main_goal, motivation, strong_points, weak_points, charismatic_traits, hobbies_interests, personality_type, coach_notes)."""
    try:
        data = request.get_json() or {}
        learning_update = _extract_learning_profile_update(data)
        db.v2_upsert_speaker_profile(user_id, data)
        if learning_update:
            db.upsert_student_profile_fields(user_id, learning_update)
        speaker_profile = db.v2_get_speaker_profile(user_id) or {"user_id": user_id}
        sniper_profile = db.get_sniper_profile_payload(user_id) or {}
        learning_profile = _learning_profile_payload(sniper_profile)
        if str(speaker_profile.get("user_id") or "") != str(user_id):
            logger.error(
                "speaker-profile mismatch after update: path_user_id=%s row_user_id=%s",
                user_id,
                speaker_profile.get("user_id"),
            )
            return jsonify({"code": "PROFILE_MISMATCH", "error": "Updated profile user mismatch"}), 500
        return _json_admin_no_store(
            {
                "status": "ok",
                "user_id": user_id,
                "speaker_profile": speaker_profile,
                "learning_profile": learning_profile,
            },
            200,
        )
    except ValueError as e:
        return jsonify({"code": "INVALID_INPUT", "error": str(e)}), 400
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

        learning_update = _extract_learning_profile_update(data)
        if "realtime_level" not in data and "realtime_step" not in data and not learning_update:
            return jsonify(
                {"code": "INVALID_INPUT", "error": "realtime_level/realtime_step or learning-profile override fields are required"},
            ), 400

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

        if "realtime_level" in data or "realtime_step" in data:
            db.set_sniper_realtime_progression(
                user_id,
                realtime_level=realtime_level,
                realtime_step=realtime_step,
            )
        if learning_update:
            db.upsert_student_profile_fields(user_id, learning_update)
        sniper_profile = db.get_sniper_profile_payload(user_id)
        return _json_admin_no_store({
            "status": "ok",
            "user_id": user_id,
            "sniper_profile": sniper_profile,
            "learning_profile": _learning_profile_payload(sniper_profile),
            "realtime_level": sniper_profile.get("realtime_level"),
            "realtime_step": sniper_profile.get("realtime_step"),
        }, 200)
    except ValueError as e:
        return jsonify({"code": "INVALID_INPUT", "error": str(e)}), 400
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
        overrides = db.v2_get_student_overrides(user_id) or {"user_id": user_id}
        if str(overrides.get("user_id") or "") != str(user_id):
            logger.error(
                "overrides mismatch after update: path_user_id=%s row_user_id=%s",
                user_id,
                overrides.get("user_id"),
            )
            return jsonify({"code": "OVERRIDES_MISMATCH", "error": "Updated overrides user mismatch"}), 500
        return _json_admin_no_store({"status": "ok", "user_id": user_id, "overrides": overrides}, 200)
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
    # approve-send request unnecessarily. We unlock the student before the
    # background thread runs; email failures are logged + Sentry-reported.
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

    # Synchronous path: always unlock the student after attempting email so
    # enterprise spam filters / Resend outages never block dashboard access.
    result = _send_email_sync()
    db.v2_mark_tutor_feedback_sent_for_user(user_id)
    sniper_profile = db.get_sniper_profile_payload(user_id)
    if result.get("status") == "failed":
        logger.warning(
            "homework delivery: email failed but student unlocked user_id=%s err=%s",
            user_id,
            result.get("error"),
        )
        return {
            "email": result,
            "sniper_profile": sniper_profile,
            "email_failed_but_unlocked": True,
            "email_error": result.get("error"),
        }, None
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
            return jsonify({"code": "DELIVERY_ERROR", "error": send_err}), 500
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
                "delivery_lifecycle": "delivered",
                "delivery_email_soft_failed": bool(delivery.get("email_failed_but_unlocked")),
                "approved_by": request.user_id,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                db.insert_admin_student_send_drafts([sent_row])
            except Exception:
                sent_row.pop("delivery_lifecycle", None)
                sent_row.pop("delivery_email_soft_failed", None)
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
                    continue
                try:
                    db.v2_apply_coach_homework_task_text(extra_uid, ai_task)
                except Exception as extra_task_err:
                    logger.warning("send-assignment: task sync failed for %s: %s", extra_uid, extra_task_err)
                er = extra_delivery["email"]
                additional_results.append(
                    {
                        "user_id": extra_uid,
                        "status": er.get("status", "unknown"),
                        "email": extra_email.strip(),
                        "email_failed_but_unlocked": bool(extra_delivery.get("email_failed_but_unlocked")),
                    }
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
        # Phase 4: coach-approved behavioral profile (must be one of 4 valid labels, or null to clear)
        profile_touched = "coach_approved_profile" in data
        if profile_touched:
            raw_profile = data.get("coach_approved_profile")
            if raw_profile is None:
                updates["coach_approved_profile"] = None
            elif isinstance(raw_profile, str) and raw_profile in PROFILE_VALUES:
                updates["coach_approved_profile"] = raw_profile
            else:
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": f"coach_approved_profile must be one of {sorted(PROFILE_VALUES)} or null",
                }), 400
        # Phase 4: coach-approved behavioral task (must reference a behavioral task aligned with the effective profile)
        task_touched = "coach_approved_task_id" in data
        task_row = None
        if task_touched:
            raw_task_id = data.get("coach_approved_task_id")
            if raw_task_id is None:
                updates["coach_approved_task_id"] = None
            else:
                task_id_str = str(raw_task_id).strip()
                if not task_id_str:
                    updates["coach_approved_task_id"] = None
                else:
                    task_row = db.v2_get_task_pool_by_id(task_id_str)
                    if not task_row or not task_row.get("is_behavioral"):
                        return jsonify({
                            "code": "INVALID_INPUT",
                            "error": "coach_approved_task_id must reference a behavioral task in tasks_pool (is_behavioral = TRUE)",
                        }), 400
                    effective_profile = (
                        updates.get("coach_approved_profile")
                        if profile_touched
                        else current.get("coach_approved_profile")
                    )
                    task_profile = task_row.get("target_profile")
                    if effective_profile and task_profile and effective_profile != task_profile:
                        return jsonify({
                            "code": "INVALID_INPUT",
                            "error": f"coach_approved_task_id belongs to profile '{task_profile}' but coach_approved_profile is '{effective_profile}'",
                        }), 400
                    updates["coach_approved_task_id"] = task_id_str
        # Stamp approval timestamp when either field is touched (lets the dashboard show "approved 2h ago").
        if profile_touched or task_touched:
            updates["coach_approved_at"] = datetime.now(timezone.utc).isoformat()
        if not updates:
            return jsonify({"code": "INVALID_INPUT", "error": "Provide report_grade, report_comment, coach_override_score, coach_override_justification, coach_approved_profile, and/or coach_approved_task_id"}), 400
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
            # Phase 4: RLHF capture for profile/task approvals. reason_chip distinguishes
            # approve (coach kept AI suggestion) from override (coach changed it) so the
            # training-data pipeline can weigh disagreements separately.
            if "coach_approved_profile" in updates:
                ai_profile = current.get("ai_suggested_profile")
                new_profile = updates.get("coach_approved_profile")
                chip = data.get("reason_chip")
                if not chip:
                    chip = "approve" if new_profile == ai_profile else "override"
                db.create_admin_annotation_event(
                    user_id=user_id,
                    session_id=session_id,
                    section_type="profile_approval",
                    field_name="coach_approved_profile",
                    ai_original_text=ai_profile,
                    coach_final_text=new_profile,
                    reason_chip=chip,
                    custom_reason=data.get("coach_approved_justification"),
                    created_by=request.user_id,
                )
            if "coach_approved_task_id" in updates:
                ai_task = current.get("ai_suggested_task_id")
                new_task = updates.get("coach_approved_task_id")
                ai_task_str = str(ai_task) if ai_task else None
                new_task_str = str(new_task) if new_task else None
                chip = data.get("reason_chip")
                if not chip:
                    chip = "approve" if new_task_str == ai_task_str else "override"
                db.create_admin_annotation_event(
                    user_id=user_id,
                    session_id=session_id,
                    section_type="profile_approval",
                    field_name="coach_approved_task_id",
                    ai_original_text=ai_task_str,
                    coach_final_text=new_task_str,
                    reason_chip=chip,
                    custom_reason=data.get("coach_approved_justification"),
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
            "coach_approved_profile": updated.get("coach_approved_profile"),
            "coach_approved_task_id": updated.get("coach_approved_task_id"),
            "coach_approved_at": updated.get("coach_approved_at"),
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

        # Use services.audio_storage so the bytes land in the same bucket
        # recording_1_job + stress/charisma services read from. Without
        # this the admin import would land in Supabase Storage while
        # recording_1_job (now using audio_storage) looks for it in R2,
        # leaving every admin-imported recording un-analysable.
        try:
            from services.audio_storage import put_audio_bytes
            put_audio_bytes(storage_path, file_bytes, content_type=content_type)
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

        # Interview audio (including the per-recording bytes anchored by
        # recordings.storage_path) lives in the R2 audio bucket now.
        # Resolve through audio_public_url first; fall back to Supabase
        # signed URL only when R2 isn't configured (dev). The prior
        # db.create_signed_url(AUDIO_BUCKET_NAME, ...) call always queried
        # Supabase and 400'd for every recording uploaded after the R2
        # migration — that's the source of the "Audio unavailable" badge
        # on the Full Recording player.
        audio_url = ""
        try:
            from services.audio_storage import audio_public_url
            audio_url = audio_public_url(storage_path) or ""
        except Exception as e:
            logger.warning("Admin playback URL: R2 build failed for %s: %s", recording_id, e)
        if not audio_url:
            try:
                audio_url = db.create_signed_url(
                    config.AUDIO_BUCKET_NAME, storage_path, config.SIGNED_URL_EXPIRY_SECONDS
                ) or ""
            except Exception as e:
                logger.warning("Admin playback URL: signed URL fallback failed for %s: %s", recording_id, e)
        if not audio_url:
            # Last-resort: synthesise the Supabase public URL pattern
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
    return (
        "idx_tasks_pool_active_slot_unique" in text
        or "ux_tasks_pool_active_slot" in text
        or (
            "duplicate key value violates unique constraint" in text
            and "target_profile" in text
            and "step_in_level" in text
        )
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


@v2_bp.route("/admin/students/<user_id>/coach-suggestions/message/<int:message_index>", methods=["PATCH"])
@require_admin
def v2_admin_edit_coach_message(user_id, message_index):
    """Human-in-the-Loop: edit a single AI message in the coach conversation history.

    Updating the stored message content causes the LLM to adopt the admin's
    preferred tone/terminology automatically on the next turn, because the full
    history is passed as context on every call.

    Body: { "content": "corrected text" }
    Returns: { status, message_index, updated_message, total_messages }
    """
    try:
        body = request.get_json(silent=True) or {}
        new_content = (body.get("content") or "").strip()
        if not new_content:
            return jsonify({"code": "INVALID_INPUT", "error": "content is required and must not be empty"}), 400
        if len(new_content) > 10_000:
            return jsonify({"code": "INVALID_INPUT", "error": "content must be at most 10 000 characters"}), 400

        updated_conv = db.update_coach_ai_message(user_id, message_index, new_content)
        if updated_conv is None:
            # Could be: user has no conversation yet, or index is out of range
            conv = db.get_coach_ai_conversation(user_id)
            if not conv:
                return jsonify({"code": "NOT_FOUND", "error": "No conversation history found for this user"}), 404
            raw = conv.get("messages") or "[]"
            messages = json.loads(raw) if isinstance(raw, str) else raw
            total = len(messages)
            return jsonify({
                "code": "OUT_OF_RANGE",
                "error": f"message_index {message_index} is out of range (conversation has {total} messages)",
            }), 422

        raw = updated_conv.get("messages") or "[]"
        messages = json.loads(raw) if isinstance(raw, str) else raw
        updated_msg = messages[message_index] if 0 <= message_index < len(messages) else None

        logger.info(
            "admin HITL: edited message idx=%d for user=%s",
            message_index, user_id,
        )
        return jsonify({
            "status": "ok",
            "message_index": message_index,
            "updated_message": updated_msg,
            "total_messages": len(messages),
        }), 200

    except Exception as e:
        logger.error("admin/coach-suggestions/message PATCH failed for %s: %s", user_id, e, exc_info=True)
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


def _copilot_row_video_for_delivery(
    row: dict, payload: dict, body: dict | None = None
) -> tuple[str | None, str | None, str | None]:
    """Resolve video_url (+ optional bucket/path) for send-assignment / copilot send / email retry."""
    body = body or {}
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
    sp = (row.get("feedback_video_storage_path") or "").strip()
    if not video_url and not (video_bucket_override and video_storage_path_override) and sp:
        video_url = _signed_feedback_video_url(sp, expires_in=48 * 3600)
        video_bucket_override = config.COACH_FEEDBACK_VIDEO_BUCKET
        video_storage_path_override = sp.lstrip("/")
    return video_url, video_bucket_override, video_storage_path_override


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
    email_soft_failed = bool(delivery.get("email_failed_but_unlocked"))

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
    merged_payload = auto_approve_payload_for_send(_normalize_copilot_payload(row))
    updated = db.mark_admin_student_send_draft_pipeline_sent(
        draft_id=str(row.get("id") or ""),
        user_id=str(row.get("user_id") or ""),
        approved_by=approved_by,
        feedback_video_storage_path=storage_path,
        script_manifest=script_manifest or {},
        delivery_email_soft_failed=email_soft_failed,
        draft_payload=merged_payload,
    )
    try:
        log_rlhf_auto_accept_events(
            db=db,
            user_id=str(row.get("user_id") or ""),
            session_id=row.get("session_id"),
            draft_id=str(row.get("id") or "") or None,
            row=row,
            payload=merged_payload,
            created_by=str(approved_by or "system"),
        )
    except Exception as rlhf_err:
        logger.warning("pipeline finalize RLHF auto-accept log failed: %s", rlhf_err)
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
        "delivery_lifecycle": infer_delivery_lifecycle(row),
        "delivery_failed_step": row.get("delivery_failed_step"),
        "delivery_email_soft_failed": bool(row.get("delivery_email_soft_failed")),
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
    # If session-filtered rows exist but are all sent, fall back to any editable draft.
    # This avoids false DRAFT_NOT_FOUND when client session_id is stale.
    if search_space is not rows:
        for row in rows:
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


@v2_bp.route("/admin/copilot/students/<user_id>/queue-archive", methods=["POST", "DELETE"])
@require_admin
def v2_admin_copilot_queue_archive(user_id):
    """Persist per-(student, session) archive flag for the Training Studio queue.

    POST   body { session_id }  → archived:true
    DELETE body { session_id }  → archived:false
    """
    try:
        data = request.get_json(silent=True) or {}
        session_id = str(
            data.get("session_id")
            or data.get("sessionId")
            or data.get("draft_generation_session_id")
            or data.get("draftGenerationSessionId")
            or ""
        ).strip()
        draft_id = str(data.get("draft_id") or data.get("draftId") or "").strip() or None
        if not session_id and draft_id:
            row = _pick_student_draft(user_id, draft_id=draft_id, include_sent=True)
            session_id = str(_effective_session_id_for_copilot_draft(row, user_id) or "").strip()
        if not session_id:
            row = _pick_student_draft(user_id, include_sent=True)
            session_id = str(_effective_session_id_for_copilot_draft(row, user_id) or "").strip()
        if not session_id:
            return jsonify({"code": "INVALID_INPUT", "error": "session_id required"}), 400
        if request.method == "DELETE":
            db.unarchive_copilot_queue_row(user_id, session_id)
            return _json_admin_no_store({"user_id": user_id, "session_id": session_id, "archived": False}, 200)
        db.archive_copilot_queue_row(user_id, session_id, request.user_id)
        return _json_admin_no_store({"user_id": user_id, "session_id": session_id, "archived": True}, 200)
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
        include_archived = (request.args.get("include_archived") or "").strip().lower() in ("1", "true", "yes")

        archived_ids = db.v2_get_archived_user_ids()
        archived_pairs = db.get_copilot_queue_archived_pairs()
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
            effective_session_id = _effective_session_id_for_copilot_draft(row, uid)
            key = f"{uid}:{str(effective_session_id or '')}"
            if key not in latest_by_key:
                row_copy = dict(row)
                row_copy["_effective_session_id"] = effective_session_id
                latest_by_key[key] = row_copy

        items = []
        for i, row in enumerate(latest_by_key.values()):
            uid = str(row.get("user_id") or "")
            session_id = row.get("_effective_session_id") or _effective_session_id_for_copilot_draft(row, uid)
            is_archived = (uid, str(session_id or "")) in archived_pairs
            if is_archived and not include_archived:
                continue
            details = db.v2_get_student_details(uid) or {}
            email = db.get_user_email_from_auth(uid)
            latest_session = db.v2_get_last_completed_session(uid) or {}
            profile_row = db.get_sniper_profile(uid) or {}
            items.append(
                {
                    "student_id": uid,
                    "session_id": session_id,
                    "queue_position": i,
                    "state": _draft_state_ui(row),
                    "draft_count": int((counts.get(uid) or {}).get("Draft", 0)),
                    "ready_count": int((counts.get(uid) or {}).get("Ready", 0)),
                    "sent_count": int((counts.get(uid) or {}).get("Sent", 0)),
                    "queue_archived": is_archived,
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
            session_id = latest_session.get("id")
            is_archived = (uid, str(session_id or "")) in archived_pairs
            if is_archived and not include_archived:
                continue
            items.append(
                {
                    "student_id": uid,
                    "session_id": session_id,
                    "queue_position": len(items),
                    "state": "Draft",
                    "draft_count": 0,
                    "ready_count": 0,
                    "sent_count": 0,
                    "queue_archived": is_archived,
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


@v2_bp.route("/admin/students/<user_id>/drafts", methods=["GET", "PUT"])
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
            return _json_admin_no_store({"drafts": [_serialize_copilot_draft(r) for r in rows], **status_meta}, 200)

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
        if str((out or {}).get("user_id") or "") != str(user_id):
            logger.error(
                "draft mismatch after update: path_user_id=%s row_user_id=%s draft_id=%s",
                user_id,
                (out or {}).get("user_id"),
                row.get("id"),
            )
            return jsonify({"code": "DRAFT_MISMATCH", "error": "Updated draft user mismatch"}), 500
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
        return _json_admin_no_store({"status": "ok", "user_id": user_id, "draft": _serialize_copilot_draft(out)}, 200)
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
        return _json_admin_no_store({"status": "ok", "items": rows, "limit": limit, "offset": offset}, 200)
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
                    "error": "Supported formats: .mp4, .mov, .webm, .m4v, .avi, .mkv, .m4a",
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

        student_user_raw = _extract_reference_upload_user_value(lambda k: request.form.get(k))
        student_user_id, uid_err = _resolve_reference_upload_user_id(student_user_raw)
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
                "error": "Supported formats: .mp4, .mov, .webm, .m4v, .avi, .mkv, .m4a",
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
                "error": "Supported formats: .mp4, .mov, .webm, .m4v, .avi, .mkv, .m4a",
                "details": {"ext": ext},
            }), 400

        student_user_raw = _extract_reference_upload_user_value(
            lambda k: (body.get(k) if isinstance(body, dict) else "")
        )
        student_user_id, uid_err = _resolve_reference_upload_user_id(student_user_raw)
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
                return _json_admin_no_store({"status": "ok", "job": synthetic_job}, 200)
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
        return _json_admin_no_store({"status": "ok", "job": payload}, 200)
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


@v2_bp.route("/admin/students/<user_id>/drafts/audit", methods=["GET", "PUT", "PATCH", "POST"])
@v2_bp.route("/admin/copilot/students/<user_id>/drafts/audit", methods=["GET", "PUT", "PATCH", "POST"])
@v2_bp.route("/admin/students/<user_id>/audit", methods=["GET", "PUT", "PATCH", "POST"])
@v2_bp.route("/admin/copilot/students/<user_id>/audit", methods=["GET", "PUT", "PATCH", "POST"])
@require_admin
def v2_admin_copilot_student_audit(user_id):
    try:
        if request.method == "GET":
            session_id = (request.args.get("session_id") or "").strip() or None
            row = _pick_student_draft(user_id, session_id=session_id, include_sent=True)
            audit = _serialize_copilot_draft(row) if row else None
            return jsonify({"audit": audit, "session_id": (audit or {}).get("session_id")}), 200

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
        audit = _serialize_copilot_draft(out)
        return jsonify({"status": "ok", "audit": audit, "session_id": audit.get("session_id")}), 200
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
        if infer_delivery_lifecycle(row) == "delivering":
            return jsonify(
                {
                    "code": "DELIVERY_IN_PROGRESS",
                    "error": "Delivery already in progress. Wait for the pipeline or refresh.",
                }
            ), 409
        payload = _normalize_copilot_payload(row, _draft_payload(row))
        video_url_raw = body.get("video_url")
        if video_url_raw is None or (isinstance(video_url_raw, str) and not str(video_url_raw).strip()):
            video_url_raw = payload.get("video_url")
        video_url, video_bucket_override, video_storage_path_override = _copilot_row_video_for_delivery(
            row, payload, body,
        )
        if video_url_raw is not None and str(video_url_raw).strip() and video_url is None:
            return jsonify({"code": "INVALID_VIDEO_URL", "error": "video_url must be a valid URL (http/https, max 2048 chars)"}), 400
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
        draft_pk = str(row.get("id") or "").strip()
        if not draft_pk:
            return jsonify({"code": "INVALID_STATE", "error": "Draft has no id"}), 500
        claimed_send = db.try_claim_admin_send_draft_delivery_in_progress(draft_pk, user_id)
        if not claimed_send:
            return jsonify(
                {
                    "code": "DELIVERY_CONFLICT",
                    "error": "Could not start delivery (concurrent request or invalid lifecycle state).",
                }
            ), 409
        desc = (final_message or "").strip() or None
        try:
            delivery, send_err = _deliver_homework_assignment_core(
                user_id,
                student_email,
                video_url=video_url,
                video_description=desc,
                video_bucket=video_bucket_override,
                video_storage_path=video_storage_path_override,
            )
            if send_err:
                raise RuntimeError(send_err)
            send_result = delivery["email"]
            sniper_profile = delivery["sniper_profile"]
            email_soft_failed = bool(delivery.get("email_failed_but_unlocked"))
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
            merged_payload = auto_approve_payload_for_send(payload)
            updated = (
                db.mark_admin_student_send_draft_sent(
                    draft_pk,
                    user_id,
                    request.user_id,
                    delivery_email_soft_failed=email_soft_failed,
                    draft_payload=merged_payload,
                )
                or row
            )
            try:
                log_rlhf_auto_accept_events(
                    db=db,
                    user_id=user_id,
                    session_id=row.get("session_id"),
                    draft_id=draft_pk,
                    row=row,
                    payload=merged_payload,
                    created_by=str(getattr(request, "user_id", "") or "system"),
                )
            except Exception as rlhf_err:
                logger.warning("copilot send RLHF auto-accept log failed: %s", rlhf_err)
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
        except Exception:
            db.reset_admin_send_draft_delivery_idle(draft_pk, user_id)
            raise
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
        if infer_delivery_lifecycle(row) == "delivering":
            return jsonify(
                {
                    "code": "DELIVERY_IN_PROGRESS",
                    "error": "Delivery already in progress. Wait for the pipeline or refresh.",
                }
            ), 409
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
                    db.reset_admin_send_draft_delivery_idle(str(row.get("id")), user_id)
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
                claimed = db.try_claim_admin_send_draft_delivery_in_progress(draft_id, user_id)
                if not claimed:
                    return jsonify(
                        {
                            "code": "DELIVERY_CONFLICT",
                            "error": "Could not start delivery (concurrent request or invalid lifecycle state).",
                        }
                    ), 409
                try:
                    updated, pipeline_job_id = _queue_video_pipeline_for_draft(
                        row,
                        user_id=user_id,
                        actor_id=getattr(request, "user_id", None),
                    )
                except Exception as queue_err:
                    db.reset_admin_send_draft_delivery_idle(draft_id, user_id)
                    raise queue_err
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
        video_url, video_bucket_override, video_storage_path_override = _copilot_row_video_for_delivery(
            row, payload, body,
        )
        if video_url_raw is not None and str(video_url_raw).strip() and video_url is None:
            return jsonify({"code": "INVALID_VIDEO_URL", "error": "video_url must be a valid URL (http/https, max 2048 chars)"}), 400
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
        claimed_sync = db.try_claim_admin_send_draft_delivery_in_progress(draft_id, user_id)
        if not claimed_sync:
            return jsonify(
                {
                    "code": "DELIVERY_CONFLICT",
                    "error": "Could not start delivery (concurrent request or invalid lifecycle state).",
                }
            ), 409
        desc = (final_message or "").strip() or None
        try:
            delivery, send_err = _deliver_homework_assignment_core(
                user_id,
                student_email,
                video_url=video_url,
                video_description=desc,
                video_bucket=video_bucket_override,
                video_storage_path=video_storage_path_override,
            )
            if send_err:
                raise RuntimeError(send_err)
            send_result = delivery["email"]
            sniper_profile = delivery["sniper_profile"]
            email_soft_failed = bool(delivery.get("email_failed_but_unlocked"))
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
            merged_payload = auto_approve_payload_for_send(payload)
            updated = db.mark_admin_student_send_draft_sent(
                draft_id,
                user_id,
                request.user_id,
                delivery_email_soft_failed=email_soft_failed,
                draft_payload=merged_payload,
            )
            try:
                log_rlhf_auto_accept_events(
                    db=db,
                    user_id=user_id,
                    session_id=row.get("session_id"),
                    draft_id=draft_id,
                    row=row,
                    payload=merged_payload,
                    created_by=str(getattr(request, "user_id", "") or "system"),
                )
            except Exception as rlhf_err:
                logger.warning("approve-send RLHF auto-accept log failed: %s", rlhf_err)
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
        except Exception:
            db.reset_admin_send_draft_delivery_idle(draft_id, user_id)
            raise
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


@v2_bp.route("/admin/students/<user_id>/drafts/<draft_id>/retry-assignment-email", methods=["POST"])
@v2_bp.route("/admin/copilot/students/<user_id>/drafts/<draft_id>/retry-assignment-email", methods=["POST"])
@require_admin
def v2_admin_retry_assignment_email(user_id, draft_id):
    """Re-send assignment email only (no video re-render). For drafts with delivery_email_soft_failed."""
    try:
        row = db.get_admin_student_send_draft(draft_id, user_id)
        if not row:
            return jsonify({"code": "DRAFT_NOT_FOUND", "error": "Draft not found"}), 404
        if str(row.get("status") or "").lower() != "sent":
            return jsonify({"code": "INVALID_STATE", "error": "Can only retry email for a sent draft"}), 400
        if not bool(row.get("delivery_email_soft_failed")):
            return jsonify(
                {"code": "NO_EMAIL_RETRY", "error": "No prior email soft failure recorded for this draft."}
            ), 400
        if infer_delivery_lifecycle(row) == "delivering":
            return jsonify({"code": "DELIVERY_IN_PROGRESS", "error": "Delivery in progress"}), 409
        student_email = (db.get_user_email_from_auth(user_id) or "").strip()
        if not student_email:
            return jsonify({"code": "NO_EMAIL", "error": "Student has no email in auth"}), 400
        raw_payload = row.get("draft_payload") if isinstance(row.get("draft_payload"), dict) else {}
        payload = _normalize_copilot_payload(row, raw_payload)
        video_url, video_bucket_override, video_storage_path_override = _copilot_row_video_for_delivery(
            row, payload, {},
        )
        final_message = (
            payload.get("email_draft")
            or payload.get("email_message")
            or payload.get("homework_comment")
            or payload.get("ai_email_draft")
            or row.get("ai_draft_message")
            or ""
        )
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
            return jsonify({"code": "DELIVERY_ERROR", "error": send_err}), 500
        er = delivery.get("email") or {}
        if not bool(delivery.get("email_failed_but_unlocked")) and (er.get("status") in ("sent", "pending")):
            db.clear_admin_send_draft_email_soft_failure(draft_id, user_id)
        return jsonify(
            {
                "status": "ok",
                "email": er,
                "email_failed_but_unlocked": bool(delivery.get("email_failed_but_unlocked")),
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
                "delivery_lifecycle": infer_delivery_lifecycle(row),
                "delivery_failed_step": row.get("delivery_failed_step"),
                "delivery_email_soft_failed": bool(row.get("delivery_email_soft_failed")),
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


# =============================================================================
# Curiosity Gate funnel — anonymous-first acquisition
# =============================================================================
# Two endpoints:
#   POST /v2/public/shaky-voice/upload  (no auth, rate-limited per IP)
#     Stores audio bytes, creates an unclaimed v2_sessions row (user_id=NULL).
#     Returns guest_session_id which the BFF stores in an httpOnly cookie.
#     Does NOT enqueue the analysis pipeline — paid Whisper / OpenAI calls
#     never run on anonymous traffic.
#
#   POST /v2/public/shaky-voice/claim  (auth required)
#     Binds an unclaimed session to auth.uid() and enqueues recording_1_job.
#     Idempotent: if the same user re-claims, returns 200; if a different
#     user attempts to claim a taken session, returns 409.
# =============================================================================

# In-process rate limiter: (ip_or_global) -> [unix_timestamps].
# Lost on restart, which is fine — these are anti-abuse caps, not auth.
_guest_funnel_rate_limit: dict = {}
_GUEST_FUNNEL_GLOBAL_KEY = "__global__"


def _guest_funnel_rate_limit_check(client_ip: str) -> tuple[bool, str]:
    """Return (allowed, reason). Sliding 1-hour window per IP and global."""
    import time as _time
    now = _time.time()
    window_start = now - 3600.0
    per_ip_cap = int(getattr(config, "GUEST_FUNNEL_RATE_LIMIT_PER_IP_PER_HOUR", 5) or 5)
    global_cap = int(getattr(config, "GUEST_FUNNEL_RATE_LIMIT_GLOBAL_PER_HOUR", 200) or 200)
    # Trim the IP bucket
    bucket = [t for t in _guest_funnel_rate_limit.get(client_ip, []) if t >= window_start]
    if len(bucket) >= per_ip_cap:
        _guest_funnel_rate_limit[client_ip] = bucket
        return False, "per_ip"
    # Trim the global bucket
    g_bucket = [t for t in _guest_funnel_rate_limit.get(_GUEST_FUNNEL_GLOBAL_KEY, []) if t >= window_start]
    if len(g_bucket) >= global_cap:
        _guest_funnel_rate_limit[_GUEST_FUNNEL_GLOBAL_KEY] = g_bucket
        return False, "global"
    bucket.append(now)
    g_bucket.append(now)
    _guest_funnel_rate_limit[client_ip] = bucket
    _guest_funnel_rate_limit[_GUEST_FUNNEL_GLOBAL_KEY] = g_bucket
    return True, ""


def _client_ip_from_request() -> str:
    """Best-effort client IP. Trusts X-Forwarded-For first (Railway/CDN), then remote_addr."""
    xff = (request.headers.get("X-Forwarded-For") or "").strip()
    if xff:
        # First entry is the original client per RFC 7239 conventions.
        return xff.split(",")[0].strip() or (request.remote_addr or "0.0.0.0")
    return request.remote_addr or "0.0.0.0"


@v2_bp.route("/public/shaky-voice/upload", methods=["POST"])
def v2_public_shaky_voice_upload():
    """Anonymous upload for the Curiosity Gate funnel.

    Stores audio in `guest_funnel/<guest_session_id>/...` and creates an
    unclaimed v2_sessions row. The analysis pipeline is NOT enqueued here —
    it fires only on POST /claim after the user signs in. This keeps paid
    compute (Whisper / OpenAI) off the anonymous surface.
    """
    if not getattr(config, "GUEST_FUNNEL_ENABLED", False):
        return jsonify({"code": "GUEST_FUNNEL_DISABLED", "error": "Guest funnel is disabled"}), 503

    try:
        client_ip = _client_ip_from_request()
        allowed, reason = _guest_funnel_rate_limit_check(client_ip)
        if not allowed:
            logger.info("guest_funnel: rate limited ip=%s reason=%s", client_ip, reason)
            return jsonify({
                "code": "RATE_LIMITED",
                "error": "Too many trial uploads — please wait a few minutes and try again.",
            }), 429

        if "audio_file" not in request.files:
            return jsonify({"code": "AUDIO_FILE_REQUIRED", "error": "audio_file is required"}), 400
        audio_file = request.files.get("audio_file")
        try:
            original_name, ext = _admin_import_validate_audio_file(audio_file)
        except ValueError as ve:
            msg = str(ve)
            if msg == "unsupported audio format":
                return jsonify({"code": "UNSUPPORTED_AUDIO_FORMAT", "error": "unsupported audio format"}), 415
            return jsonify({"code": "AUDIO_FILE_REQUIRED", "error": msg}), 400

        max_mb_raw = getattr(config, "GUEST_FUNNEL_MAX_AUDIO_SIZE_MB", 5)
        max_mb = int(max_mb_raw) if max_mb_raw is not None else 5
        max_bytes = max_mb * 1024 * 1024
        cl = request.content_length or 0
        if cl and cl > max_bytes:
            return jsonify({"code": "FILE_TOO_LARGE", "error": f"audio_file exceeds {max_mb}MB limit"}), 413
        file_bytes = audio_file.read()
        if not file_bytes:
            return jsonify({"code": "INVALID_MULTIPART", "error": "audio_file is empty"}), 400
        if len(file_bytes) > max_bytes:
            return jsonify({"code": "FILE_TOO_LARGE", "error": f"audio_file exceeds {max_mb}MB limit"}), 413

        guest_session_id = str(uuid.uuid4())
        recording_id = str(uuid.uuid4())
        storage_path = f"guest_funnel/{guest_session_id}/recording_{uuid.uuid4().hex}{ext}"
        content_type = (audio_file.mimetype or mimetypes.guess_type(original_name)[0] or "application/octet-stream").strip()
        if content_type in ("True", "False"):
            content_type = "application/octet-stream"

        # Cold-start funnel: upload via services.audio_storage so the
        # bytes land in the same bucket extract_recording_snippets reads
        # from. Otherwise the cold-start admin view shows "No interview
        # turns recorded" because the snippet-extraction reader can't
        # find the audio.
        try:
            from services.audio_storage import put_audio_bytes
            put_audio_bytes(storage_path, file_bytes, content_type=content_type)
        except Exception as upload_err:
            logger.warning("guest_funnel: storage upload failed ip=%s: %s", client_ip, upload_err, exc_info=True)
            return jsonify({"code": "UPLOAD_FAILED", "error": "Failed to store uploaded audio"}), 500

        duration_raw = (request.form or {}).get("duration_seconds")
        try:
            duration_seconds = float(duration_raw) if duration_raw not in (None, "") else None
        except (TypeError, ValueError):
            duration_seconds = None

        # ORDER MATTERS: recordings.session_v2_id has FK -> v2_sessions(id), so the
        # session row must exist BEFORE the recording row. We then update the
        # session to set recording_1_id once the recording row exists.
        try:
            db.v2_create_guest_session(guest_session_id)
        except Exception as session_err:
            logger.warning("guest_funnel: v2_create_guest_session failed: %s", session_err, exc_info=True)
            return jsonify({"code": "SESSION_CREATE_FAILED", "error": "Failed to create guest session"}), 500

        recording_payload = {
            "id": recording_id,
            "user_id": None,
            "session_id": None,
            "session_v2_id": guest_session_id,
            "storage_path": storage_path,
            "audio_url": "",
            "duration": 0,
            "recording_origin": "guest_funnel",
        }
        if duration_seconds is not None:
            recording_payload["duration_seconds"] = duration_seconds

        try:
            db.create_recording(recording_payload)
        except Exception as create_err:
            err_low = str(create_err).lower()
            if "recording_origin" in err_low or "pgrst204" in err_low:
                fallback = {k: v for k, v in recording_payload.items() if k != "recording_origin"}
                try:
                    db.create_recording(fallback)
                except Exception as e2:
                    logger.warning("guest_funnel: create_recording failed: %s", e2, exc_info=True)
                    return jsonify({"code": "RECORDING_CREATE_FAILED", "error": "Failed to create recording"}), 500
            else:
                logger.warning("guest_funnel: create_recording failed: %s", create_err, exc_info=True)
                return jsonify({"code": "RECORDING_CREATE_FAILED", "error": "Failed to create recording"}), 500

        try:
            db.v2_set_guest_session_recording(guest_session_id, recording_id)
        except Exception as link_err:
            # Non-fatal: the recording row already carries session_v2_id, so the
            # claim path can still find it. Log and continue.
            logger.warning("guest_funnel: link recording_1_id failed (non-fatal): %s", link_err)

        logger.info(
            "guest_funnel: upload ok ip=%s guest_session_id=%s storage_path=%s bytes=%d",
            client_ip, guest_session_id, storage_path, len(file_bytes),
        )
        return jsonify({
            "status": "ok",
            "guest_session_id": guest_session_id,
        }), 201

    except Exception as e:
        logger.error("guest_funnel: upload failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Upload failed"}), 500


############################################################################
# Multi-Turn Interview endpoints
############################################################################

_INTERVIEW_QUESTIONS_FALLBACK = {
    "charisma": [
        "Tell us, in your own words: do you think you're a good communicator? Why?",
        "What's something you're genuinely passionate about?",
        "Describe a moment in your life or career that you're really proud of.",
        "If you could teach anyone one thing, what would it be and why?",
        "What's the best piece of advice you've ever received?",
        "What makes you unique compared to other people in your field?",
    ],
    "stress": [
        "What's your biggest professional weakness, and how does it show up day-to-day?",
        "Describe a time you completely failed at something that mattered to you.",
        "If I told you your communication style sometimes puts people off, how would you respond?",
        "Explain a complex topic from your field as if you're talking to a 10-year-old.",
        "What would your harshest critic say about you — and would they be right?",
        "Tell me about a decision you made that you still regret.",
    ],
}

_INTERVIEW_SYSTEM_PROMPT = """You are an interview coach conducting a voice charisma assessment.
Your job is to ask questions that alternate between two tones:

1. CHARISMA-PROVOKING questions: These let the interviewee shine — topics where they can show passion, storytelling ability, warmth, and vocal energy. Examples: achievements, passions, advice they'd give.

2. STRESS-PROVOKING questions: These are challenging, slightly uncomfortable, or technical — designed to test how the person handles pressure, pauses, and uncertainty. Examples: failures, weaknesses, defending a controversial stance.

RULES:
- You MUST alternate tones: if the previous question was charisma, the next MUST be stress, and vice versa.
- Keep questions concise (1-2 sentences max).
- Never repeat a question you've already asked in this session.
- Make follow-up questions contextual when possible (reference what the user said).
- Never break character or explain what you're doing.
- FORMATTING RULE: If you include a brief acknowledgment or validation before your question,
  separate it from the question using the exact delimiter `|||`.
  Example: `That was a vivid story! ||| Now tell me about a time you completely failed at something that mattered to you.`
  If there is no acknowledgment, return ONLY the question text with no delimiter.
"""

from services.skills import (
    get_skill as _get_skill,
    list_skill_ids as _list_skill_ids,
    resolve_for_snippet as _skill_for_snippet,
)


# Phase 7 — the registry in services/skills/ is the source of truth
# for which intents the contextual /chat flow accepts. The literal
# {"charisma", "stress"} that used to live here is gone; adding a
# skill is now a package-level change, not a route-level edit.
_CONTEXTUAL_INTENTS = _list_skill_ids()

# ---------------------------------------------------------------------------
# EBCP Baseline Mapping — system prompt & generation
# ---------------------------------------------------------------------------

_EBCP_BASELINE_SYSTEM_PROMPT = """You are an EBCP Baseline Mapping coach conducting a structured 3-stage voice assessment for sales professionals.
You MUST follow this EXACT sequential flow based on the turn number provided in the user message.

=== STAGE 1: FRUSTRATION FACTOR (Turn 2) ===
The user was just asked: "Are you good at math?"
Analyze their transcript to determine confidence level.

IF the user indicated YES (confident, positive, eager — "yes", "love it", "pretty good", "great", "sure"):
Return EXACTLY:
"Love the confidence! ||| Let's test that sales brain. Imagine you have a prospect on the phone. They want to buy 15 software licenses at $100 each, but they are demanding a 20% discount to close today. Walk me through your calculation out loud: What is the final deal size, and how would you deliver that number to the client?"

IF the user indicated NO (hesitant, unsure, negative — "no", "not really", "bad at math", "hate math", "not good"):
Return EXACTLY:
"No worries, that is exactly what CRM software and calculators are for! ||| Let's keep it simple. Imagine you just closed a $3,000 deal, and your commission is 10%. Tell me: How much money did you just make, and what is the very first thing you are going to spend it on?"

GUARDRAIL — If the transcript is unclear or ambiguous: Default to the NO branch.

=== STAGE 2: RELIEF FACTOR (Turn 3) ===
The user just attempted a math challenge. Generate a response that:
1. Opens with ONE brief warm acknowledgment sentence of their math effort (e.g. "Great job crunching those numbers! Let's leave the math behind us now.")
   — GUARDRAIL: If the user refused math or gave a clearly wrong/confused answer, open with "OK, thanks for that a lot! Let's move on!" instead.
2. Separates the acknowledgment from the question using the exact delimiter `|||`.
3. Immediately follows with EXACTLY this question (note the `|||` between the setup sentence and the "Hit record" prompt — keep it):
"Think about the most charismatic leader or salesperson you have ever worked with—someone who naturally inspires others. ||| Hit record and tell me: What is the one specific trait they have that makes people instantly trust them? And how do you feel when you talk to them?"
   — GUARDRAIL: If the transcript reveals the user has never met a charismatic leader, append: " That's fair! Think of a public figure, a famous CEO, or anyone you admire from afar. What makes them so trustworthy?"

=== STAGE 3: FAMILIARITY FACTOR (Turn 4) ===
The user just described a charismatic leader. Generate a response that:
1. Opens with ONE brief validation sentence (e.g. "That's a great observation. It is definitely easier to buy from someone we naturally trust.")
2. Separates the validation from the question using the exact delimiter `|||`.
3. Immediately follows with EXACTLY this question:
"Let's wrap up this baseline mapping with something a bit more fun. Think about your favorite movie, show, or book. If you could bring one fictional character with you to the toughest negotiation of your life to help you close the deal, who would it be and why? Hit record and tell me how they would handle a difficult client."
   — GUARDRAIL: If the transcript reveals the user doesn't watch movies or read books, append: " No problem at all. Just think of any historical figure or famous personality you'd want by your side in a tough negotiation. Who would it be and why?"

=== GLOBAL GUARDRAILS ===
- FORMATTING RULE: Separate your acknowledgment/validation from your question using the exact delimiter `|||`.
  Example: `OK, thanks for that a lot! Let's move on! ||| Think about the most charismatic leader or salesperson you have ever worked with...`
  Turn 1 has no acknowledgment prefix — return ONLY the question text with no `|||`.
- Return ONLY the formatted text. No labels, no stage headers, no meta-commentary.
- NEVER correct the user's math. NEVER force them to retry. NEVER argue.
- Your primary goal: keep them speaking to collect their vocal baseline.
- If any answer is unexpected, validate gracefully and advance the sequence.
- Low temperature: be deterministic and stick closely to the exact wording specified above.
"""

# Deterministic fallbacks when the LLM fails — keyed by turn_number
_EBCP_FALLBACKS: dict[int, str] = {
    1: "Are you good at math?",
    2: (
        "No worries, that is exactly what CRM software and calculators are for! ||| "
        "Let's keep it simple. Imagine you just closed a $3,000 deal, and your commission is 10%. "
        "Tell me: How much money did you just make, and what is the very first thing you are going to spend it on?"
    ),
    3: (
        "Great effort! Let's leave the math behind us now. ||| "
        "Think about the most charismatic leader or salesperson you have ever worked with—someone who naturally inspires others. ||| "
        "Hit record and tell me: What is the one specific trait they have that makes people instantly trust them? "
        "And how do you feel when you talk to them?"
    ),
    4: (
        "That's a great observation. It is definitely easier to buy from someone we naturally trust. ||| "
        "Let's wrap up this baseline mapping with something a bit more fun. "
        "Think about your favorite movie, show, or book. If you could bring one fictional character with you to the "
        "toughest negotiation of your life to help you close the deal, who would it be and why? "
        "Hit record and tell me how they would handle a difficult client."
    ),
}


def _generate_ebcp_question(
    turn_number: int,
    previous_turns: list | None = None,
) -> str | None:
    """Generate the EBCP Baseline Mapping question for turns 1-4.

    Turn 1 → fixed opener ("Are you good at math?"), no LLM needed.
    Turn 2 → Math branching: LLM reads turn-1 transcript for YES/NO.
    Turn 3 → Relief/Charisma: LLM acknowledges math effort, asks about charismatic leader.
    Turn 4 → Familiarity: LLM acknowledges charisma response, asks about fictional character.
    """
    # Turn 1: hardcoded EBCP opener — no LLM call needed
    if turn_number == 1:
        return _EBCP_FALLBACKS[1]

    # Turns 2-4: ask the LLM with EBCP system prompt + conversation history
    if turn_number > 4:
        return None  # caller should fall through to regular charisma/stress questions

    try:
        from services.openai_service import OpenAIService
        service = OpenAIService()
        if not service.client:
            return None

        messages: list[dict] = [{"role": "system", "content": _EBCP_BASELINE_SYSTEM_PROMPT}]

        # Build conversation history so the LLM sees prior turns & transcripts
        if previous_turns:
            for turn in previous_turns:
                q = (turn.get("question") or "").strip()
                t = (turn.get("transcript") or "").strip()
                if q:
                    messages.append({"role": "assistant", "content": q})
                if t:
                    messages.append({"role": "user", "content": t})

        messages.append({
            "role": "user",
            "content": (
                f"This is turn {turn_number}. "
                "Generate the appropriate EBCP stage response based on the conversation history above. "
                "Return ONLY the question text, nothing else."
            ),
        })

        response = service.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=300,
            temperature=0.25,  # Low temperature: deterministic EBCP wording
        )
        question = response.choices[0].message.content.strip()
        if question.startswith('"') and question.endswith('"'):
            question = question[1:-1]
        return question if question else None

    except Exception as e:
        logger.warning("_generate_ebcp_question(turn=%d) failed (will use fallback): %s", turn_number, e)
        return None


def _generate_snippet_follow_up_question(
    snippet_type: str,
    transcript: str,
    admin_comment: str,
) -> str | None:
    """Generate a single follow-up question for the Infinite Retention Loop.

    Called when an admin labels/comments on a snippet. The question is stored
    on the snippet row so it can be served instantly when the user later clicks
    the snippet — no latency at click time.

    snippet_type: "charisma" | "stress" | "unlabeled"
    transcript:   Whisper transcript of the snippet audio.
    admin_comment: Coach's text note on the snippet.

    Returns the generated question string, or None on failure.
    """
    try:
        from services.openai_service import OpenAIService
        service = OpenAIService()
        if not service.client:
            return None

        if snippet_type == "charisma":
            system_prompt = (
                "You are a charisma coaching assistant. "
                "An admin coach has flagged this audio snippet as a HIGH-CHARISMA moment "
                "and left a comment about it. Your task is to write a response that:\n"
                "1. Opens with ONE brief warm acknowledgment of this specific moment (1 sentence)\n"
                "2. Follows with ONE powerful question that helps the user deconstruct WHY they "
                "felt so confident and how they can deliberately replicate that energy "
                "(e.g. in cold calls, presentations, or negotiations)\n"
                "The question must be:\n"
                "- Specific to the transcript content (reference what they actually said)\n"
                "- High-energy and motivating in tone\n"
                "- Focused on replicability (how to trigger this state on demand)\n"
                "- No longer than 2 sentences\n"
                "FORMATTING RULE: Separate your acknowledgment from your question using the exact "
                "delimiter `|||`. "
                "Example: `That energy you described is magnetic! ||| What specific conditions were "
                "present that day that let you access that state so easily?`\n"
                "Return ONLY these two parts separated by `|||`, nothing else."
            )
        elif snippet_type == "stress":
            system_prompt = (
                "You are a performance coaching assistant. "
                "An admin coach has flagged this audio snippet as a HIGH-STRESS or VOCAL-STRAIN moment "
                "and left a comment. Your task is to write a response that:\n"
                "1. Opens with ONE brief empathetic acknowledgment of this specific moment (1 sentence)\n"
                "2. Follows with ONE targeted question that addresses the cognitive load or emotional "
                "trigger that caused the vocal stress spike\n"
                "The question must be:\n"
                "- Specific to what the speaker was saying in the transcript\n"
                "- Empathetic but direct (not dismissive)\n"
                "- Focused on uncovering the root cause of that specific stress moment\n"
                "- No longer than 2 sentences\n"
                "FORMATTING RULE: Separate your acknowledgment from your question using the exact "
                "delimiter `|||`. "
                "Example: `That moment sounds genuinely tough. ||| What was running through your mind "
                "right before your voice shifted?`\n"
                "Return ONLY these two parts separated by `|||`, nothing else."
            )
        else:
            # unlabeled or unknown — generic deepening question
            system_prompt = (
                "You are a voice coaching assistant. "
                "Based on this audio transcript and the coach's comment, write a response that:\n"
                "1. Opens with ONE brief acknowledgment of the moment (1 sentence)\n"
                "2. Follows with ONE insightful question to help the speaker reflect on it\n"
                "FORMATTING RULE: Separate your acknowledgment from your question using the exact "
                "delimiter `|||`. "
                "Return ONLY these two parts separated by `|||`, nothing else."
            )

        user_content = (
            f"Transcript: \"{transcript}\"\n"
            f"Coach comment: \"{admin_comment}\""
        )

        response = service.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_tokens=120,
            temperature=0.7,
        )
        question = response.choices[0].message.content.strip()
        if question.startswith('"') and question.endswith('"'):
            question = question[1:-1]
        return question if question else None

    except Exception as e:
        logger.warning("_generate_snippet_follow_up_question failed: %s", e)
        return None


def _build_few_shot_block(
    *,
    intent: str,
    exclude_snippet_id: str | None = None,
    limit: int = 3,
    viewer_user_id: str | None = None,
) -> str:
    """Render the top-N high-scoring past exchanges as a system-prompt
    preamble for contextual question generation.

    Pulls from db.get_top_followup_examples which returns charisma_snippets
    rows whose follow_up_outcome.score is at least min_score. Each example
    is rendered with four pieces of context:
      - the original user transcript (the moment the coach annotated)
      - the coach's insight
      - the question that was asked
      - the user's actual answer + the evaluator's score

    When ``viewer_user_id`` is provided AND Config.FEW_SHOT_TENANT_SCOPED
    is on, retrieval is scoped to the viewer's company (joined via
    user_settings.company_id) plus any 'canonical' rows. Otherwise the
    legacy cross-tenant retrieval is preserved exactly. Every call
    writes one row to ``few_shot_retrievals`` for compliance + Phase 1
    pool-depth telemetry.

    Returns an empty string when no qualifying examples exist (early
    days of the loop, before enough outcomes have accumulated) — the
    caller is responsible for handling the empty case.

    Example budget: we trim each field to a sane character cap so a
    handful of long transcripts can't blow the context window. The
    examples block typically lands in the 400-1200 char range.
    """
    examples = db.get_top_followup_examples(
        intent,
        limit=limit,
        exclude_snippet_id=exclude_snippet_id,
        viewer_user_id=viewer_user_id,
    )
    if not examples:
        return ""

    def _truncate(s: str | None, cap: int) -> str:
        text = (s or "").strip()
        if not text:
            return ""
        if len(text) <= cap:
            return text
        return text[:cap].rstrip() + "…"

    chunks: list[str] = [
        "Below are examples of past coaching follow-ups that the user "
        "actually engaged with deeply (each scored highly by an automated "
        "evaluator). Study the STYLE of the questions: specific, somatic, "
        "concrete, non-leading. Use the SAME style when you generate the "
        "new question further down."
    ]
    for i, ex in enumerate(examples, start=1):
        outcome = ex.get("follow_up_outcome") or {}
        evaluator = (outcome.get("evaluator") or {}) if isinstance(outcome, dict) else {}
        score_raw = outcome.get("score") if isinstance(outcome, dict) else None
        try:
            score_pct = int(round(float(score_raw) * 100))
        except (TypeError, ValueError):
            score_pct = 0
        question = (
            ex.get("follow_up_question")
            or (outcome.get("question_text") if isinstance(outcome, dict) else None)
            or ""
        )
        user_answer = (
            (outcome.get("user_answer") or {}).get("text")
            if isinstance(outcome, dict)
            else None
        ) or ""
        chunks.append(
            f"\nEXAMPLE {i} (score: {score_pct}/100)\n"
            f"Original moment: \"{_truncate(ex.get('transcript'), 240)}\"\n"
            f"Coach insight:   \"{_truncate(ex.get('admin_comment'), 200)}\"\n"
            f"Question asked:  \"{_truncate(question, 200)}\"\n"
            f"User responded:  \"{_truncate(user_answer, 280)}\""
        )
    return "\n".join(chunks)


def _generate_llm_question(
    turn_number: int,
    tone: str,
    previous_turns: list | None = None,
    user_id: str | None = None,
    *,
    contextual_init: dict | None = None,
) -> str | None:
    """Call GPT-4o-mini to generate the next interview question.

    Falls back to the hardcoded bank on failure.
    Returns the question text, or None on error (caller uses fallback).
    """
    try:
        from services.openai_service import OpenAIService
        import openai

        service = OpenAIService()
        if not service.client:
            return None

        # Special: contextual "retention loop" init question (single deepening question)
        if contextual_init and int(turn_number or 1) == 1:
            intent = (contextual_init.get("intent") or "").strip().lower()
            transcript = (contextual_init.get("transcript") or "").strip()
            admin_comment = (contextual_init.get("admin_comment") or "").strip()
            source_snippet_id = contextual_init.get("source_snippet_id")
            if intent in _CONTEXTUAL_INTENTS and transcript and admin_comment:
                # ── Few-shot retrieval ──────────────────────────────
                # Pull the top-scoring past exchanges with the SAME intent
                # so the model is anchored on wording that historically
                # produced specific, emotionally-rich answers. Falls
                # silent when there aren't enough labeled outcomes yet
                # (no examples block in the prompt, model generates
                # purely from the current snippet's context).
                few_shot_block = _build_few_shot_block(
                    intent=intent,
                    exclude_snippet_id=source_snippet_id,
                    # Phase 1 tenant scoping flows through the caller's
                    # user_id so retrieval can JOIN through
                    # user_settings.company_id. When None (background
                    # script, internal caller), the legacy path runs.
                    viewer_user_id=user_id,
                )

                if intent == "charisma":
                    base = (
                        "You are a coaching assistant. "
                        "The user clicked 'Understand your charisma' on a past recording. "
                        f"In that recording, they said: '{transcript}'. "
                        f"The human coach commented: '{admin_comment}'. "
                        "Respond with two parts: (1) a brief warm acknowledgment of this specific moment, "
                        "then (2) ONE deepening question to help them deconstruct WHY they felt so confident "
                        "and how they can replicate it. "
                        "FORMATTING RULE: Separate the acknowledgment from the question using the exact "
                        "delimiter `|||`. "
                        "Example: `That moment you described is exactly where charisma lives! ||| "
                        "What were you thinking about right before you said that?` "
                        "Return ONLY these two parts separated by `|||`, nothing else."
                    )
                else:
                    base = (
                        "You are a coaching assistant. "
                        "The user clicked 'Release your stress'. "
                        f"In that recording, they said: '{transcript}'. "
                        f"The human coach commented: '{admin_comment}'. "
                        "Respond with two parts: (1) a brief empathetic acknowledgment of this moment, "
                        "then (2) ONE deepening question to help them identify the root cause of that "
                        "specific stress spike. "
                        "FORMATTING RULE: Separate the acknowledgment from the question using the exact "
                        "delimiter `|||`. "
                        "Example: `That sounds like a genuinely pressured moment. ||| "
                        "What was the thing you most feared would go wrong right then?` "
                        "Return ONLY these two parts separated by `|||`, nothing else."
                    )

                # Few-shot block goes BEFORE the task description so the
                # examples set tone before the task constraints are read.
                system_prompt = (
                    f"{few_shot_block}\n\n{base}" if few_shot_block else base
                )

                response = service.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "system", "content": system_prompt}],
                    max_tokens=150,
                    temperature=0.7,
                )
                question = response.choices[0].message.content.strip()
                if question.startswith('"') and question.endswith('"'):
                    question = question[1:-1]
                return question if question else None

        # Build system prompt with optional user-specific injection
        system_prompt = _INTERVIEW_SYSTEM_PROMPT
        if user_id:
            settings = db.get_user_settings(user_id)
            if settings and settings.get("custom_llm_instructions"):
                system_prompt += f"\n\nADDITIONAL INSTRUCTIONS FOR THIS USER:\n{settings['custom_llm_instructions']}"

        # Build conversation history for context
        messages = [{"role": "system", "content": system_prompt}]

        if previous_turns:
            for turn in previous_turns:
                messages.append({"role": "assistant", "content": turn.get("question", "")})
                if turn.get("transcript"):
                    messages.append({"role": "user", "content": turn["transcript"]})

        # Request next question
        messages.append({
            "role": "user",
            "content": f"Generate the next question. This is turn {turn_number}. Required tone: {tone}.",
        })

        response = service.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=150,
            temperature=0.8,
        )

        question = response.choices[0].message.content.strip()
        # Strip quotes if the LLM wrapped it
        if question.startswith('"') and question.endswith('"'):
            question = question[1:-1]
        return question if question else None

    except Exception as e:
        logger.warning("_generate_llm_question failed (will use fallback): %s", e)
        return None


@v2_bp.route("/user/results/<session_id>", methods=["GET"])
@require_auth
def v2_user_get_results(session_id):
    """User results endpoint for /results dual-state page.

    Always returns { session_id, status }. Status is determined by:
      - results_published_at IS NOT NULL → "completed" (admin has reviewed & published)
      - otherwise → "processing"

    When completed, payload includes all non-skipped snippets with their
    metrics, admin_comment, snippet_type, and audio URLs.
    """
    try:
        if not _is_valid_uuid(session_id):
            return jsonify({"code": "INVALID_INPUT", "error": "session_id must be a valid UUID"}), 400

        user_id = request.user_id
        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "NOT_FOUND", "error": "Session not found"}), 404

        # Dual-state: admin must explicitly publish before user sees results
        is_published = bool(session.get("results_published_at"))
        status = "completed" if is_published else "processing"

        payload = {
            "session_id": str(session_id),
            "status": status,
            "created_at": session.get("created_at"),
        }

        if status == "completed":
            snippets = db.v2_get_results_snippets_for_session(session_id, user_id)
            # Shape each snippet for frontend consumption.
            #
            # IMPORTANT: audio_url comes from _resolve_snippet_audio_url
            # (NOT the raw audio_segment_path column) so:
            #   - Concat'd session snippets (storage_path =
            #     session_recordings/<sid>/full.webm) get the R2 audio
            #     bucket public URL — playable directly in the
            #     <audio> tag without RLS / signing dance.
            #   - Student / Path-C rows (storage_path =
            #     charisma_snippets/<uuid>) get a short-lived Supabase
            #     signed URL.
            #   - Legacy rows (audio_segment_path = an absolute URL)
            #     fall through to that URL.
            # The previous version returned audio_segment_path verbatim,
            # which was NULL for every auto_extracted snippet — so the
            # /results page rendered un-playable cards.
            #
            # start_offset_ms ships too so the frontend can clamp
            # playback when audio_url points at a concat'd full.webm.
            payload["snippets"] = [
                {
                    "id": s.get("id"),
                    "snippet_type": s.get("snippet_type"),
                    "admin_comment": s.get("admin_comment"),
                    "audio_url": _resolve_snippet_audio_url(s),
                    "transcript": s.get("transcript"),
                    "turn_number": s.get("turn_number"),
                    "question_text": s.get("question_text"),
                    "question_tone": s.get("question_tone"),
                    "start_offset_ms": s.get("start_offset_ms") or 0,
                    "duration_ms": s.get("duration_ms"),
                    "metrics": {
                        "wpm": s.get("wpm"),
                        "fillers": s.get("fillers"),
                        "pause_ms": s.get("pause_ms"),
                        "dynamic_db": s.get("dynamic_db"),
                        "pitch_center": s.get("pitch_center"),
                        "energy": s.get("energy"),
                    },
                }
                for s in snippets
            ]
            # Include session-level summary if available
            payload["ai_summary"] = session.get("ai_task_alignment_comment")
            payload["ai_score"] = session.get("ai_task_alignment_score")
            payload["kpi_score"] = session.get("kpi_score")

        return jsonify(payload), 200

    except Exception as e:
        logger.error("user/results failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch results"}), 500


@v2_bp.route("/user/results/latest", methods=["GET"])
@require_auth
def v2_user_get_latest_results():
    """Redirect helper: find the user's most recent published session.

    Returns { session_id, status } so the frontend can redirect to
    /results/<session_id> or show "no results yet".
    """
    try:
        user_id = request.user_id
        session = db.v2_get_latest_published_session_for_user(user_id)
        if not session:
            return jsonify({
                "session_id": None,
                "status": "no_results",
            }), 200

        return jsonify({
            "session_id": str(session.get("id")),
            "status": "completed",
            "results_published_at": session.get("results_published_at"),
        }), 200

    except Exception as e:
        logger.error("user/results/latest failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch latest results"}), 500


def _derive_session_status(session: dict, snippet_counts: dict) -> str:
    """Compute a single user-facing status string from the raw session row.

    Status values map to the frontend routing decisions on /results:
        no_session     — user has zero sessions (caller handles)
        processing     — recording exists but ML hasn't extracted snippets yet
        pending_review — snippets exist, admin still labelling / writing comments
        completed      — admin has clicked "Publish Results" (results_published_at set)
        error          — recording_1_processing_status is "failed"

    The transitions are deliberately one-way for the user-facing surface:
    pending_review never goes back to processing once snippets exist; if the
    admin un-publishes a session we leave it as pending_review.
    """
    if session.get("results_published_at"):
        return "completed"

    rec_status = (session.get("recording_1_processing_status") or "").lower()
    if rec_status == "failed":
        return "error"

    total_snippets = snippet_counts.get("total", 0)
    if total_snippets > 0:
        # Snippets have been extracted; we're now waiting on the admin
        # human-in-the-loop review. Note: we don't gate on
        # `with_admin_comment > 0` here because a session can be
        # legitimately published with no comments (rare but allowed).
        return "pending_review"

    # No snippets yet — still in the ML extraction / processing phase.
    return "processing"


@v2_bp.route("/user/sessions/current", methods=["GET"])
@require_auth
def v2_user_sessions_current():
    """Rich session-state surface for post-auth routing decisions.

    Replaces the narrow /user/results/latest by exposing every column the
    frontend needs to decide where to send a freshly-authenticated user
    (record screen, processing/waiting screen, results page) without
    multiple round-trips.

    Returns 200 with:
        {
            "has_session": bool,
            "session_id": str | None,
            "status": "no_session" | "processing" | "pending_review"
                    | "completed" | "error",
            "has_recordings": bool,
            "turn_count": int,             # interview turns answered (rec'd snippets)
            "snippet_count": int,          # total non-skipped snippets
            "published_snippet_count": int,# snippets the admin has commented on
            "results_published_at": str | None,
            "recording_processing_status": str | None,  # raw ML pipeline state
            "created_at": str | None
        }

    The endpoint NEVER returns mock data. When the user has no sessions the
    response is { has_session: false, status: "no_session", ...zeros }.
    """
    try:
        user_id = request.user_id
        session = db.v2_get_latest_session_for_user(user_id)

        if not session:
            return jsonify({
                "has_session": False,
                "session_id": None,
                "status": "no_session",
                "has_recordings": False,
                "turn_count": 0,
                "snippet_count": 0,
                "published_snippet_count": 0,
                "results_published_at": None,
                "recording_processing_status": None,
                "created_at": None,
            }), 200

        session_id = str(session.get("id"))
        snippet_counts = db.v2_count_session_snippets(session_id)
        status = _derive_session_status(session, snippet_counts)

        # `has_recordings` is true iff the session has a bound recording.
        # We check the recording_1 link rather than counting rows on the
        # recordings table — same answer, one fewer query.
        has_recordings = bool(session.get("recording_1_id"))

        return jsonify({
            "has_session": True,
            "session_id": session_id,
            "status": status,
            "has_recordings": has_recordings,
            # Each charisma_snippet row corresponds to one interview turn
            # the user actually answered, so total snippet count == turn count.
            "turn_count": snippet_counts.get("total", 0),
            "snippet_count": snippet_counts.get("total", 0),
            "published_snippet_count": snippet_counts.get("with_admin_comment", 0),
            "results_published_at": session.get("results_published_at"),
            "recording_processing_status": session.get("recording_1_processing_status"),
            "created_at": session.get("created_at"),
        }), 200

    except Exception as e:
        logger.error("user/sessions/current failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch session state"}), 500


def _format_duration(duration_ms: int | None) -> str:
    """Format a duration in ms as M:SS for the timeline UI (e.g. 12000 -> '0:12')."""
    if not duration_ms or duration_ms < 0:
        return "0:00"
    total_seconds = int(duration_ms // 1000)
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


def _snippet_to_journey_card(snippet: dict) -> dict:
    """Map a charisma_snippets row into the `Snippet` shape the
    /results Voice-Journey page expects (lib/results/types.ts).

    The page's existing typed interface is the contract; we transform once
    here on the backend so the frontend can drop its mock without inventing
    a translation layer.
    """
    coach_label = (snippet.get("coach_label") or "").lower()
    snippet_type = "charisma" if coach_label == "charisma" else "stress"

    badge_label = (
        "Charisma Moment" if snippet_type == "charisma" else "Stress Pattern"
    )
    cta_label = (
        "Understand your charisma"
        if snippet_type == "charisma"
        else "Work on this stress"
    )

    # Build the metrics list — we omit any metric whose value is null so
    # the UI accordion doesn't render empty rows.
    metrics_src = snippet.get("metrics") or {}
    raw_metrics = [
        ("WPM", metrics_src.get("wpm"), lambda v: f"{int(v)}"),
        ("Pitch", metrics_src.get("pitch_center"), lambda v: f"{int(v)} Hz"),
        ("Pause", metrics_src.get("pause_ms"), lambda v: f"{(v / 1000):.1f}s"),
        ("Energy", metrics_src.get("energy"), lambda v: f"{int(v * 100)}%"),
        ("Fillers", metrics_src.get("fillers"), lambda v: f"{int(v)}"),
        ("Dynamic dB", metrics_src.get("dynamic_db"), lambda v: f"{int(v)}"),
    ]
    metrics: list[dict] = []
    for label, value, fmt in raw_metrics:
        if value is None:
            continue
        try:
            metrics.append({"label": label, "value": fmt(value)})
        except Exception:
            # Defensive — never let a formatting error blank out a snippet.
            continue

    return {
        "id": str(snippet.get("id")),
        "type": snippet_type,
        "duration": _format_duration(snippet.get("duration_ms")),
        "badgeLabel": badge_label,
        "insight": snippet.get("admin_comment") or "",
        "ctaLabel": cta_label,
        "metrics": metrics,
        "audioUrl": snippet.get("audio_url"),
    }


@v2_bp.route("/user/results/me", methods=["GET"])
@require_auth
def v2_user_results_me():
    """The Voice-Journey timeline: every published session for the user.

    Returns the `VoiceJourneyPayload` shape consumed by /results/page.tsx
    (lib/results/types.ts). The endpoint NEVER returns mock data — when
    the user has no published sessions the response is a status-aware
    empty payload the page can render as a "record your first session"
    state.

    Response (200):
        {
            "status": "processing" | "ready" | "completed",
            "current_session_index": int,   # 1-based
            "total_sessions": int,
            "sessions": [
                {
                    "id": str,
                    "title": str,            # "Session N: Baseline Audio"
                    "snippets": [Snippet]    # see _snippet_to_journey_card
                }
            ],
            "ai_summary": str | None
        }

    Status semantics:
        completed — at least one published session, snippets to show
        ready     — alias for completed (kept for legacy frontend code)
        processing — user has a session but admin hasn't published yet
                    (or no session at all — the page handles both with the
                    same waiting screen)
    """
    try:
        user_id = request.user_id
        sessions = db.v2_get_published_sessions_for_user(user_id)

        if not sessions:
            # Determine whether they have ANY session (in flight) so the
            # frontend can pick between the founder-video waiting screen
            # and the "record your first session" empty state.
            latest = db.v2_get_latest_session_for_user(user_id)
            return jsonify({
                "status": "processing" if latest else "processing",
                "current_session_index": 0,
                "total_sessions": 0,
                "sessions": [],
                "ai_summary": None,
            }), 200

        total = len(sessions)
        journey_sessions = []
        for idx, session in enumerate(sessions):
            session_id = str(session.get("id"))
            raw_snippets = db.v2_get_results_snippets_for_session(session_id, user_id)
            # Show every published snippet (admin_comment present). The
            # admin can hide individual snippets by toggling is_skipped,
            # which the DB query already filters out.
            visible = [s for s in raw_snippets if s.get("admin_comment")]
            journey_sessions.append({
                "id": session_id,
                # Index oldest → newest for the user-facing label so
                # "Session 1" is their baseline.
                "title": f"Session {total - idx}: " + (
                    "Baseline Audio" if (total - idx) == 1 else "Follow-up"
                ),
                "snippets": [_snippet_to_journey_card(s) for s in visible],
            })

        # The UI shows newest first, but its progress tracker is 1-based
        # over the total count of published sessions. current = total here
        # because we always surface the most recent on top.
        return jsonify({
            "status": "completed",
            "current_session_index": total,
            "total_sessions": total,
            "sessions": journey_sessions,
            "ai_summary": (sessions[0] or {}).get("ai_task_alignment_comment"),
        }), 200

    except Exception as e:
        logger.error("user/results/me failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch voice journey"}), 500


# ─────────────────────────────────────────────────────────────────────
# Coaching loop — micro-coaching session on a single snippet
#
# v1: stress intent only, two technical stages (awareness → trial) with
# the reframe baked into the awareness prompt. The flow:
#
#   /v2/coaching/start
#     POST { snippet_id }
#     → reads charisma_snippets row, validates ownership + admin_comment,
#       creates coaching_sessions row, returns the admin_comment as the
#       awareness "first bubble" so the frontend can render it instantly.
#
#   /v2/coaching/turn
#     POST { coaching_id, user_message }
#     → looks up the active skill via services.skills.get_skill(intent),
#       calls the LLM with that skill's awareness_system_prompt, parses
#       the structured JSON (validation_bubble / challenge_bubble /
#       advance) and advances stage to 'trial' when advance is true.
#
#   /v2/coaching/trial-recording
#     POST multipart audio_file + coaching_id
#     → uploads audio, creates v2_session + recording rows, runs the
#       existing extract_recording_snippets pipeline, marks the
#       coaching_session 'complete' and binds trial_session_id.
# ─────────────────────────────────────────────────────────────────────


def _system_prompt_for_intent(intent: str) -> str:
    """Pick the awareness-stage system prompt for a given coaching intent.

    Phase 7 — the prompts themselves moved to services/skills/. This
    function is a thin shim over the registry kept around so existing
    call sites don't have to change; new code should call
    ``services.skills.get_skill(intent).awareness_system_prompt``
    directly. The fallback path (unknown intent) lands on the stress
    skill, matching pre-refactor behaviour.
    """
    skill = _get_skill(intent) or _get_skill("stress")
    return skill.awareness_system_prompt if skill else ""


def _merge_admin_override_into_profile(
    *,
    inferred: dict | None,
    override: dict | None,
) -> dict | None:
    """Combine the inferred profile with any admin override.

    Phase 9. The override is layered on TOP of the inferred profile
    field-by-field so an admin can correct one trait (say
    score_trend) without re-stating every other trait they wanted to
    leave alone.

    Rules:
      - No override and no inferred → None (nothing to inject).
      - Override only (no inferred yet) → override as-is.
      - Inferred only → inferred as-is (Phase 3 behaviour).
      - Both → override.traits replaces matching keys from
        inferred.traits; top-level attempts_analyzed comes from the
        override so the injection gate in format_profile_for_prompt
        always clears when an override is set.

    The returned dict matches the shape format_profile_for_prompt
    expects: ``{attempts_analyzed: int, traits: {...}, ...}``.
    """
    if not inferred and not override:
        return None
    if override and not inferred:
        return override
    if inferred and not override:
        return inferred

    base_traits = dict((inferred or {}).get("traits") or {})
    override_traits = dict((override or {}).get("traits") or {})
    base_traits.update(override_traits)

    return {
        **inferred,
        "attempts_analyzed": int(
            (override or {}).get("attempts_analyzed")
            or (inferred or {}).get("attempts_analyzed")
            or 0
        ),
        "traits": base_traits,
    }


def _augment_coaching_system_prompt(base_prompt: str, user_id: str) -> str:
    """Append the long-term user profile to a coaching system prompt.

    Three sources of personalisation, stacked top-to-bottom in the
    system prompt:
      - user_settings.custom_llm_instructions — free-text instructions
        the admin set in Admin Tab 3 ("Global LLM Instructions"). Goes
        verbatim into the prompt so the admin's wording is preserved.
      - student profile.behavioral_profile — the user's classified
        learner type (e.g. Stressor, Racer, Freezer) from the
        behavioural-profile classifier.
      - Phase 3: user_settings.inferred_learner_profile — AI-inferred
        traits derived from coaching_attempts aggregates (weakest
        component, score trend, self-rating gap, etc.). Flag-gated by
        LEARNER_PROFILE_INJECTION_ENABLED and additionally gated by
        sample-size threshold in services/learner_profile.py.

    Any of these can be absent. When all three are silent we return
    the base prompt unchanged — no [USER LONG-TERM PROFILE] block.

    Failure modes are swallowed: a DB read miss returns the base
    prompt rather than blocking the coaching turn. Personalisation is
    additive — the awareness loop must keep running even when the
    profile is unreadable.
    """
    learner_type: str = ""
    custom_instructions: str = ""
    inferred_profile: dict | None = None

    settings: dict = {}
    try:
        settings = db.get_user_settings(user_id) or {}
        custom_instructions = (settings.get("custom_llm_instructions") or "").strip()
    except Exception as e:
        logger.warning("coaching/turn: settings load failed user=%s: %s", user_id, e)

    try:
        profile = db.get_sniper_profile(user_id) or {}
        # Admin's manual override wins when set — same precedence used
        # everywhere else (admin/students endpoints, snippet display).
        learner_type = (
            (profile.get("coach_override_profile") or "").strip()
            or (profile.get("behavioral_profile") or "").strip()
        )
    except Exception as e:
        logger.warning("coaching/turn: profile load failed user=%s: %s", user_id, e)

    # Phase 3 + Phase 9 — inferred profile, possibly overridden by
    # an admin. The override (when present) wins trait-by-trait over
    # the inferred profile so an admin can correct one signal without
    # discarding the rest. Read both from the same user_settings row
    # we already pulled above so we don't issue a second query.
    # Injection-gated by LEARNER_PROFILE_INJECTION_ENABLED so the
    # recompute can run live without the block influencing the AI
    # until we backtest it.
    insights_block: str | None = None
    override_active: bool = False
    try:
        from config import Config
        if Config().LEARNER_PROFILE_INJECTION_ENABLED:
            inferred_profile = settings.get("inferred_learner_profile") or None
            override_profile = settings.get("admin_profile_override") or None
            effective_profile = _merge_admin_override_into_profile(
                inferred=inferred_profile,
                override=override_profile,
            )
            override_active = override_profile is not None
            if effective_profile:
                from services.learner_profile import format_profile_for_prompt
                insights_block = format_profile_for_prompt(effective_profile)
    except Exception as e:
        logger.warning(
            "coaching/turn: inferred profile render failed user=%s: %s",
            user_id, e,
        )

    if not learner_type and not custom_instructions and not insights_block:
        return base_prompt

    lines: list[str] = ["[USER LONG-TERM PROFILE]"]
    if learner_type:
        lines.append(f"Learner Type: {learner_type}")
    if custom_instructions:
        lines.append(f"Custom Coaching Instructions: {custom_instructions}")
    if insights_block:
        lines.append("")
        header = (
            "[LEARNER INSIGHTS — admin-curated overrides applied]"
            if override_active
            else "[LEARNER INSIGHTS — inferred from recent attempts]"
        )
        lines.append(header)
        lines.append(insights_block)
    lines.append("")
    lines.append(
        "CRITICAL: You must adhere to these custom instructions and "
        "tailor your feedback to this learner type."
    )

    return f"{base_prompt}\n\n" + "\n".join(lines)


def _coach_intent_for_snippet(snippet: dict) -> str:
    """Map a snippet's coach_label to a coaching intent.

    Phase 7 — thin shim over services.skills.resolve_for_snippet.
    Kept under the old name so existing call sites in this module
    keep working; new code should import resolve_for_snippet
    directly from the skills package.
    """
    return _skill_for_snippet(snippet)


@v2_bp.route("/internal/whisper-health", methods=["GET"])
def v2_internal_whisper_health():
    """Diagnostic: does the running process actually have OPENAI_API_KEY?

    Hit this from a browser or curl. The response tells us deterministically
    whether the OpenAI client can be constructed at runtime AND whether a
    real API call to OpenAI succeeds — without needing to trigger a real
    recording or sift through Railway logs.

    Auth: intentionally none — leaks no secret material; only metadata
    (length, first 7 chars masked, model count) about whether the integration
    is wired up.
    """
    try:
        from services.openai_service import OpenAIService
        svc = OpenAIService()
        key = (config.OPENAI_API_KEY or "")

        # Live API reachability check — list models. Cheap call (one
        # request, ~100ms), proves the key is valid AND the network can
        # reach api.openai.com from this Railway container.
        api_reachable = False
        api_error: str | None = None
        api_model_count = 0
        if svc.client:
            try:
                models = svc.client.models.list()
                api_reachable = True
                # `data` is a list of Model objects on the response
                api_model_count = len(getattr(models, "data", []) or [])
            except Exception as call_err:
                api_error = f"{type(call_err).__name__}: {call_err}"

        # Also verify which git commit this process is running. Helps
        # confirm Railway has picked up the latest deploy (e.g. the
        # explicit transcription log in e7271b8). Read from RAILWAY_GIT_COMMIT_SHA
        # (Railway-injected) or fall back to RAILWAY_DEPLOYMENT_ID.
        git_sha = (
            os.environ.get("RAILWAY_GIT_COMMIT_SHA")
            or os.environ.get("RAILWAY_DEPLOYMENT_ID")
            or None
        )

        return jsonify({
            "client_initialized": svc.client is not None,
            "api_key_present": bool(key),
            "api_key_length": len(key),
            "api_key_prefix": (key[:7] + "...") if key else None,
            "api_reachable": api_reachable,
            "api_error": api_error,
            "api_model_count": api_model_count,
            "git_sha": git_sha,
            # Echo back which env vars are actually visible at runtime so we
            # can spot Railway-scoped misses (preview vs production env).
            "env_visible": {
                "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
                "GUEST_FUNNEL_ENABLED": os.environ.get("GUEST_FUNNEL_ENABLED"),
                "BACKEND_URL_INTERNAL": bool(os.environ.get("BACKEND_URL_INTERNAL")),
                "R2_PUBLIC_BASE_URL": bool(os.environ.get("R2_PUBLIC_BASE_URL")),
            },
        }), 200
    except Exception as e:
        logger.error("whisper-health failed: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@v2_bp.route("/coaching/start", methods=["POST"])
@require_auth
def v2_coaching_start():
    """Open a micro-coaching session on one snippet.

    Body: { "snippet_id": "<uuid>" }

    Validates the user owns the snippet and that the admin has left a
    comment (no comment ⇒ nothing to coach about). Creates a
    coaching_sessions row in the awareness stage.

    Response (200):
        {
            "coaching_id": str,
            "intent": "stress" | "charisma",
            "awareness_message": str,   # admin_comment, served verbatim
            "source_snippet": {
                "id": str, "transcript": str | None, "audio_url": str | None,
                "duration_ms": int | None
            }
        }
    """
    try:
        body = request.get_json(silent=True) or {}
        snippet_id = (body.get("snippet_id") or "").strip()
        if not _is_valid_uuid(snippet_id):
            return jsonify({"code": "INVALID_INPUT", "error": "snippet_id must be a UUID"}), 400

        user_id = request.user_id
        snippet = db.get_snippet_by_id(snippet_id, user_id=user_id)
        if not snippet:
            return jsonify({
                "code": "SNIPPET_NOT_FOUND",
                "error": "Snippet not found or not yours.",
            }), 404

        admin_comment = (snippet.get("admin_comment") or "").strip()
        if not admin_comment:
            return jsonify({
                "code": "SNIPPET_NOT_COACHABLE",
                "error": "This snippet has no coach comment yet — nothing to coach on.",
            }), 422

        intent = _coach_intent_for_snippet(snippet)
        # Both 'stress' and 'charisma' intents are now live; the prompt
        # router in v2_coaching_turn picks the right system prompt.
        coaching = db.create_coaching_session(user_id, snippet_id, intent)
        if not coaching:
            return jsonify({"code": "V2_ERROR", "error": "Failed to start coaching"}), 500

        return jsonify({
            "coaching_id": str(coaching.get("id")),
            "intent": intent,
            "awareness_message": admin_comment,
            "source_snippet": {
                "id": str(snippet.get("id")),
                "transcript": snippet.get("transcript"),
                "audio_url": snippet.get("audio_url"),
                "duration_ms": snippet.get("duration_ms"),
            },
        }), 200

    except Exception as e:
        logger.error("coaching/start failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to start coaching"}), 500


@v2_bp.route("/coaching/<coaching_id>", methods=["GET"])
@require_auth
def v2_coaching_get(coaching_id):
    """Re-hydrate a coaching session — survive reloads of /coach/[id].

    Returns the same shape as /coaching/start except with current_stage
    and trial_session_id reflecting any progress already made.

    404 GET semantics: NOT_FOUND covers both "doesn't exist" and "owned
    by someone else" so we don't leak coaching id existence.
    """
    try:
        if not _is_valid_uuid(coaching_id):
            return jsonify({"code": "INVALID_INPUT", "error": "coaching_id must be a UUID"}), 400
        user_id = request.user_id
        coaching = db.get_coaching_session(coaching_id, user_id)
        if not coaching:
            return jsonify({
                "code": "COACHING_NOT_FOUND",
                "error": "Coaching session not found.",
            }), 404
        snippet = db.get_snippet_by_id(coaching.get("source_snippet_id"), user_id=user_id)
        if not snippet:
            return jsonify({
                "code": "SNIPPET_NOT_FOUND",
                "error": "Source snippet missing.",
            }), 404
        return jsonify({
            "coaching_id": str(coaching.get("id")),
            "intent": coaching.get("intent"),
            "current_stage": coaching.get("current_stage"),
            "awareness_message": (snippet.get("admin_comment") or "").strip(),
            "source_snippet": {
                "id": str(snippet.get("id")),
                "transcript": snippet.get("transcript"),
                "audio_url": snippet.get("audio_url"),
                "duration_ms": snippet.get("duration_ms"),
            },
            "trial_session_id": coaching.get("trial_session_id"),
        }), 200
    except Exception as e:
        logger.error("coaching/<id> failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to load coaching"}), 500


@v2_bp.route("/coaching/turn", methods=["POST"])
@require_auth
def v2_coaching_turn():
    """Run one LLM turn of the awareness stage.

    Body: { "coaching_id": "<uuid>", "user_message": "..." }

    Loads the coaching session + source snippet, builds the awareness
    prompt with admin_comment / transcript / user_message context, calls
    GPT, parses the `|||` + `[ADVANCE]` shape, and advances to the trial
    stage when [ADVANCE] is present.

    Response (200):
        {
            "bubbles": [str, str],   # second may be empty if model
                                     # forgot the delimiter
            "advance": bool,
            "next_stage": "awareness" | "trial" | "complete"
        }
    """
    try:
        body = request.get_json(silent=True) or {}
        coaching_id = (body.get("coaching_id") or "").strip()
        user_message = (body.get("user_message") or "").strip()

        if not _is_valid_uuid(coaching_id):
            return jsonify({"code": "INVALID_INPUT", "error": "coaching_id must be a UUID"}), 400
        if not user_message:
            return jsonify({"code": "INVALID_INPUT", "error": "user_message is required"}), 400

        user_id = request.user_id
        coaching = db.get_coaching_session(coaching_id, user_id)
        if not coaching:
            return jsonify({"code": "COACHING_NOT_FOUND", "error": "Coaching session not found"}), 404
        if coaching.get("current_stage") == "complete":
            return jsonify({
                "code": "COACHING_COMPLETE",
                "error": "This coaching loop is already complete.",
            }), 409

        snippet = db.get_snippet_by_id(coaching.get("source_snippet_id"), user_id=user_id)
        if not snippet:
            return jsonify({"code": "SNIPPET_NOT_FOUND", "error": "Source snippet missing"}), 404

        intent = coaching.get("intent") or "stress"
        base_system_prompt = _system_prompt_for_intent(intent)

        # ── Long-term profile injection ─────────────────────────────
        # Pulls the admin-set custom_llm_instructions (Admin Tab 3) +
        # the user's behavioral_profile classification (e.g. Stressor,
        # Racer, Freezer). When either is present, we append a
        # [USER LONG-TERM PROFILE] block to the system prompt so the
        # coaching turn adapts to who this specific user is rather
        # than coaching every learner identically.
        system_prompt = _augment_coaching_system_prompt(base_system_prompt, user_id)

        from services.openai_service import OpenAIService
        service = OpenAIService()
        if not service.client:
            return jsonify({"code": "LLM_UNAVAILABLE", "error": "Coaching LLM is not configured"}), 503

        admin_comment = (snippet.get("admin_comment") or "").strip()
        user_transcript = (snippet.get("transcript") or "").strip()

        user_content = (
            f'admin_comment: "{admin_comment}"\n'
            f'user_transcript: "{user_transcript}"\n'
            f'user_first_reply: "{user_message}"'
        )

        # Persist the user side of the exchange before calling the LLM.
        # If the LLM call fails downstream we still want admins to see
        # what the user actually said. Best-effort — append never blocks
        # the response if the JSONB column hasn't been migrated yet.
        try:
            db.append_coaching_message(coaching_id, "user", user_message)
        except Exception as msg_err:
            logger.warning("coaching/turn user-msg append failed: %s", msg_err)

        # Phase 0 — structured output. The model returns a strict
        # JSON object {validation_bubble, challenge_bubble, advance}
        # so the prior |||  + [ADVANCE] string-parsing dance is gone.
        # System prompt still tells the model what each field means;
        # the schema enforces shape, the prompt enforces semantics.
        from services.llm_schemas import (
            AWARENESS_TURN_SCHEMA,
            response_format as _response_format,
        )
        structured_prompt = (
            f"{system_prompt}\n\n"
            "RESPONSE SHAPE — return JSON only with exactly these keys:\n"
            "  validation_bubble — 1-2 sentence acknowledgment of the user's reply.\n"
            "  challenge_bubble  — the mic-on instruction telling them what to do next.\n"
            "  advance           — true when the user is ready to record the trial.\n"
        )

        try:
            response = service.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": structured_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.6,
                max_tokens=240,
                response_format=_response_format(AWARENESS_TURN_SCHEMA),
            )
            raw = response.choices[0].message.content or ""
        except Exception as llm_err:
            logger.error("coaching/turn LLM call failed: %s", llm_err, exc_info=True)
            return jsonify({
                "code": "LLM_ERROR",
                "error": "Coach is unavailable. Please try again in a moment.",
            }), 502

        # Schema enforces the shape — only failure left is a transport
        # blip that returns malformed text. We log + fall back below.
        bubble_1 = ""
        bubble_2 = ""
        advance = False
        try:
            parsed = json.loads(raw) if raw else {}
            bubble_1 = (parsed.get("validation_bubble") or "").strip()
            bubble_2 = (parsed.get("challenge_bubble") or "").strip()
            advance = bool(parsed.get("advance"))
        except (json.JSONDecodeError, ValueError, AttributeError) as parse_err:
            logger.warning(
                "coaching/turn: structured output not parseable: %r err=%s",
                raw[:300], parse_err,
            )

        if not bubble_1 and not bubble_2:
            # Total LLM failure — return a graceful fallback instead of
            # an empty payload so the user always sees something. The
            # bubbles come from the skill registry so a degraded
            # response stays tonally consistent with the active skill.
            fallback_skill = _get_skill(intent) or _get_skill("stress")
            if fallback_skill is not None:
                bubble_1 = fallback_skill.fallback_validation_bubble
                bubble_2 = fallback_skill.fallback_challenge_bubble
            advance = True

        # Persist the AI side of the exchange. Both bubbles together so
        # the admin transcript reads as one assistant message rather
        # than two synthetic ones — the `||| / [ADVANCE]` is an LLM
        # output detail, not a semantic separation.
        try:
            ai_content_parts = [b for b in (bubble_1, bubble_2) if b]
            db.append_coaching_message(
                coaching_id,
                "assistant",
                " ||| ".join(ai_content_parts),
                extra={
                    "bubbles": [bubble_1, bubble_2],
                    "advance": advance,
                    "raw_llm_output": raw,
                },
            )
        except Exception as msg_err:
            logger.warning("coaching/turn assistant-msg append failed: %s", msg_err)

        next_stage = "trial" if advance else coaching.get("current_stage", "awareness")
        if advance and coaching.get("current_stage") != "trial":
            db.update_coaching_stage(coaching_id, "trial")

        return jsonify({
            "bubbles": [bubble_1, bubble_2],
            "advance": advance,
            "next_stage": next_stage,
        }), 200

    except Exception as e:
        logger.error("coaching/turn failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Coaching turn failed"}), 500


@v2_bp.route("/coaching/trial-recording", methods=["POST"])
@require_auth
def v2_coaching_trial_recording():
    """Bind the user's trial re-performance to their coaching session.

    Multipart body:
      - audio_file: the recorded re-performance
      - coaching_id: (form field) the coaching_sessions row to mark complete

    Side effects on success:
      - audio uploaded to the same audio bucket the cold-start funnel uses
      - new v2_sessions row created (so the existing snippet pipeline
        treats this like any other authenticated recording)
      - new recordings row created and linked to that v2_session
      - existing extract_recording_snippets fires — its output snippets
        land back on /results, closing the loop
      - coaching_session marked complete, trial_session_id bound

    Response (201):
        { status: "ok", coaching_id, trial_session_id, recording_id }
    """
    import uuid as _uuid
    from services.recording_1_job import enqueue_recording_1_job

    try:
        coaching_id = (request.form.get("coaching_id") or "").strip()
        if not _is_valid_uuid(coaching_id):
            return jsonify({"code": "INVALID_INPUT", "error": "coaching_id must be a UUID"}), 400

        audio = request.files.get("audio_file")
        if not audio:
            return jsonify({"code": "INVALID_INPUT", "error": "audio_file is required"}), 400

        user_id = request.user_id
        coaching = db.get_coaching_session(coaching_id, user_id)
        if not coaching:
            return jsonify({"code": "COACHING_NOT_FOUND", "error": "Coaching session not found"}), 404
        if coaching.get("current_stage") == "complete":
            # Idempotent: trial already submitted. Return the bound IDs.
            return jsonify({
                "status": "ok",
                "coaching_id": coaching_id,
                "trial_session_id": coaching.get("trial_session_id"),
                "already_complete": True,
            }), 200

        # 1. Upload audio — use the same bucket + helper the cold-start
        # funnel uses so the analysis pipeline reads it the same way.
        try:
            file_bytes = audio.read()
        except Exception:
            return jsonify({"code": "AUDIO_READ_FAILED", "error": "Could not read audio"}), 400
        if not file_bytes:
            return jsonify({"code": "AUDIO_EMPTY", "error": "Empty audio payload"}), 400

        recording_id = str(_uuid.uuid4())
        # Coaching trials live under their own prefix so admin queries can
        # tell them apart from baseline recordings at a glance.
        storage_path = f"coaching_trials/{user_id}/{recording_id}.webm"
        content_type = (audio.mimetype or "audio/webm").strip() or "audio/webm"
        # services.audio_storage puts bytes in the same bucket the
        # stress/charisma analysis services read from. Without this the
        # coaching trial upload would land in Supabase while readers
        # look in R2.
        try:
            from services.audio_storage import put_audio_bytes
            put_audio_bytes(storage_path, file_bytes, content_type=content_type)
        except Exception as upload_err:
            logger.error("coaching trial: upload failed: %s", upload_err, exc_info=True)
            return jsonify({"code": "STORAGE_ERROR", "error": "Failed to store audio"}), 502

        # 2. Create the v2_session row that will parent the new snippets
        trial_session = db.v2_create_session(user_id)
        if not trial_session:
            return jsonify({"code": "V2_ERROR", "error": "Failed to create trial session"}), 500
        trial_session_id = str(trial_session.get("id"))

        # 3. Create the recording row
        recording_payload = {
            "id": recording_id,
            "user_id": user_id,
            "session_v2_id": trial_session_id,
            "storage_path": storage_path,
            "audio_url": "",
            "duration": 0,
            "recording_origin": "coaching_trial",
        }
        try:
            db.create_recording(recording_payload)
        except Exception as create_err:
            err_low = str(create_err).lower()
            if "recording_origin" in err_low or "pgrst204" in err_low:
                fallback = {k: v for k, v in recording_payload.items() if k != "recording_origin"}
                db.create_recording(fallback)
            else:
                logger.error("coaching trial: create_recording failed: %s", create_err, exc_info=True)
                return jsonify({"code": "RECORDING_CREATE_FAILED", "error": "Failed to create recording"}), 500

        # 4. Bind the recording to the session and stamp the lifecycle
        # fields so the recording-1 pipeline auto-completes.
        try:
            db.v2_update_session(trial_session_id, user_id, {
                "recording_1_id": recording_id,
                "status": "completing_from_recording_1",
                "recording_1_processing_status": "pending",
                "self_rating_submitted_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as link_err:
            logger.warning("coaching trial: session link failed (non-fatal): %s", link_err)

        # 5. Kick off analysis + snippet extraction. Both are non-fatal:
        # if either fails the row is bound and admins can re-run.
        try:
            enqueue_recording_1_job(trial_session_id, recording_id, storage_path, user_id, None)
        except Exception as q_err:
            logger.warning("coaching trial: enqueue failed: %s", q_err, exc_info=True)
        try:
            from services.snippet_extraction import extract_recording_snippets
            extract_recording_snippets(
                session_id=trial_session_id,
                user_id=str(user_id),
                recording_id=recording_id,
                recording_path=storage_path,
                duration_seconds=None,
            )
        except Exception as snippet_err:
            logger.warning("coaching trial: extract_recording_snippets failed: %s", snippet_err)

        # 6. Mark the coaching session complete and bind the trial session
        db.update_coaching_stage(coaching_id, "complete", trial_session_id=trial_session_id)

        # 7. Record the trial recording on the coaching session so admin
        # review tooling can replay the full loop (admin comment →
        # awareness bubbles → user's re-performance audio) from one
        # row. We resolve a playable URL the same way the admin
        # snippet panel does so the saved value is directly usable in
        # an <audio> tag without further translation.
        try:
            from services.audio_storage import audio_public_url
            playable_url = audio_public_url(storage_path) or storage_path
            db.set_coaching_trial_recording(coaching_id, playable_url)
            db.append_coaching_message(
                coaching_id,
                "trial_audio",
                playable_url,
                extra={
                    "storage_path": storage_path,
                    "recording_id": recording_id,
                    "trial_session_id": trial_session_id,
                },
            )
        except Exception as bind_err:
            logger.warning(
                "coaching trial: log trial recording failed (non-fatal): %s",
                bind_err,
            )

        logger.info(
            "coaching trial: ok user_id=%s coaching_id=%s trial_session_id=%s",
            user_id, coaching_id, trial_session_id,
        )
        return jsonify({
            "status": "ok",
            "coaching_id": coaching_id,
            "trial_session_id": trial_session_id,
            "recording_id": recording_id,
        }), 201

    except Exception as e:
        logger.error("coaching/trial-recording failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Trial recording failed"}), 500


@v2_bp.route("/user/chat/first-question", methods=["POST"])
@require_auth
def v2_user_chat_first_question():
    """Start a contextual chat by generating the first AI question.

    Query params:
      - sourceSnippetId (UUID)
      - intent: charisma|stress
    """
    try:
        user_id = request.user_id
        source_snippet_id = (request.args.get("sourceSnippetId") or "").strip() or None
        intent = (request.args.get("intent") or "").strip().lower() or None

        contextual_init = None
        if source_snippet_id or intent:
            if not (source_snippet_id and intent):
                return jsonify({"code": "INVALID_INPUT", "error": "sourceSnippetId and intent must be provided together"}), 400
            if not _is_valid_uuid(source_snippet_id):
                return jsonify({"code": "INVALID_INPUT", "error": "sourceSnippetId must be a valid UUID"}), 400
            if intent not in _CONTEXTUAL_INTENTS:
                return jsonify({"code": "INVALID_INPUT", "error": "intent must be 'charisma' or 'stress'"}), 400

            snippet = db.v2_get_charisma_snippet_for_user(source_snippet_id, user_id)
            if not snippet:
                return jsonify({"code": "NOT_FOUND", "error": "Snippet not found"}), 404

            # ── Infinite Retention Trigger: use stored follow_up_question first ──
            # The admin pre-generated (and may have hand-edited) this question when
            # labeling the snippet. Serving it directly avoids latency at click time
            # and ensures the admin's wording is used verbatim.
            stored_follow_up = (snippet.get("follow_up_question") or "").strip()
            if stored_follow_up:
                return jsonify({
                    "status": "ok",
                    "question": stored_follow_up,
                    "source": "stored_follow_up",
                }), 200

            # No pre-stored question → fall back to dynamic LLM generation
            transcript = (
                (snippet.get("transcript") or "")
                or (snippet.get("transcription_text") or "")
                or (snippet.get("transcript_text") or "")
                or (snippet.get("transcript_excerpt") or "")
            ).strip()
            admin_comment = (snippet.get("admin_comment") or "").strip()
            if not transcript or not admin_comment:
                return jsonify({
                    "code": "SNIPPET_CONTEXT_UNAVAILABLE",
                    "error": "Snippet transcript/admin_comment is not available yet",
                }), 422

            contextual_init = {
                "intent": intent,
                "transcript": transcript,
                "admin_comment": admin_comment,
                # Forwarded so the few-shot retrieval doesn't echo this
                # exact snippet back as one of its own examples.
                "source_snippet_id": source_snippet_id,
            }

        # Generate the first question dynamically
        tone = "charisma" if (intent != "stress") else "stress"
        question = _generate_llm_question(
            turn_number=1,
            tone=tone,
            previous_turns=None,
            user_id=user_id,
            contextual_init=contextual_init,
        )
        if not question:
            # Phase 7 — first-question fallback lives on the Skill
            # object so it stays consistent with the rest of that
            # skill's tone. Defaults to stress's question when the
            # intent doesn't resolve.
            fallback_skill = _get_skill(intent) or _get_skill("stress")
            if fallback_skill is not None:
                question = fallback_skill.contextual_first_question

        return jsonify({
            "status": "ok",
            "question": question,
            "source": "llm_generated",
        }), 200

    except Exception as e:
        logger.error("user/chat/first-question failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to generate first question"}), 500


@v2_bp.route("/user/coaching/progress", methods=["GET"])
@require_auth
def v2_user_coaching_progress():
    """All attempts the requesting user has made on one source snippet.

    Phase 2 of the snippet-CTA learning loop. Returns the per-snippet
    progress timeline plus a delta between the first attempt and the
    best-scoring attempt. Powers the "see your progress" view on /results
    and is also consumable by self-rating UX in a later phase.

    Query params:
      - snippet_id (UUID, required)

    Response shape::

        {
          "snippet_id": "...",
          "attempts": [
            {
              "attempt_number": 1,
              "score": 0.7123,
              "components": {...},
              "user_answer_word_count": 47,
              "user_answer_duration_ms": 12300,
              "acoustic_features": null,
              "source": "post_turn_1_evaluation",
              "is_eligible_for_few_shot": true,
              "created_at": "2026-..."
            },
            ...
          ],
          "delta": {
            "best_attempt_number": 3,
            "first_score": 0.7123,
            "best_score": 0.8421,
            "score": 0.1298,
            "word_count": 12,
            "duration_ms": 4100
          }
        }

    Owner-scoped: only attempts authored by the requesting user are
    returned. Returns 404 when the snippet doesn't belong to the user
    (mirrors v2_get_charisma_snippet_for_user's ownership check).
    """
    try:
        user_id = request.user_id
        snippet_id = (request.args.get("snippet_id") or "").strip()
        if not snippet_id or not _is_valid_uuid(snippet_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "snippet_id must be a valid UUID",
            }), 400

        # Owner check — block users from probing other people's snippets.
        snippet = db.v2_get_charisma_snippet_for_user(snippet_id, user_id)
        if not snippet:
            return jsonify({
                "code": "NOT_FOUND",
                "error": "Snippet not found",
            }), 404

        attempts = db.list_coaching_attempts_for_snippet(snippet_id, user_id=user_id)

        def _to_float(v):
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        attempt_payload: list[dict] = []
        for a in attempts:
            self_rating = a.get("self_rating")
            try:
                self_rating = int(self_rating) if self_rating is not None else None
            except (TypeError, ValueError):
                self_rating = None
            attempt_payload.append({
                "attempt_number": a.get("attempt_number"),
                "score": _to_float(a.get("score")),
                "components": a.get("components") or {},
                "user_answer_word_count": a.get("user_answer_word_count"),
                "user_answer_duration_ms": a.get("user_answer_duration_ms"),
                "acoustic_features": a.get("acoustic_features"),
                "source": a.get("source"),
                "is_eligible_for_few_shot": bool(a.get("is_eligible_for_few_shot")),
                "self_rating": self_rating,
                "self_rating_text": a.get("self_rating_text"),
                "self_rating_submitted_at": a.get("self_rating_submitted_at"),
                # Phase 4 — per-attempt entities. Pre-Phase-4 rows
                # have this as NULL; the frontend renders nothing.
                "entities": a.get("entities"),
                "created_at": a.get("created_at"),
            })

        delta: dict | None = None
        if attempt_payload:
            scored = [
                a for a in attempt_payload
                if isinstance(a.get("score"), (int, float))
            ]
            if scored:
                first = min(scored, key=lambda a: a.get("attempt_number") or 0)
                best = max(scored, key=lambda a: a.get("score") or 0.0)
                delta = {
                    "best_attempt_number": best.get("attempt_number"),
                    "first_score": first.get("score"),
                    "best_score": best.get("score"),
                    "score": round(
                        (best.get("score") or 0.0) - (first.get("score") or 0.0),
                        4,
                    ),
                    "word_count": (
                        (best.get("user_answer_word_count") or 0)
                        - (first.get("user_answer_word_count") or 0)
                    ),
                    "duration_ms": (
                        (best.get("user_answer_duration_ms") or 0)
                        - (first.get("user_answer_duration_ms") or 0)
                    ),
                    # Self-rating delta is independent of the score-based
                    # best/first pair: a user can rate themselves higher
                    # on an attempt the LLM scored lower. Carry first and
                    # best self_ratings (across all attempts that have one)
                    # so the frontend can show both progression signals.
                    "self_rating_first": _first_self_rating(attempt_payload),
                    "self_rating_best": _best_self_rating(attempt_payload),
                }

        return jsonify({
            "snippet_id": snippet_id,
            "attempts": attempt_payload,
            "delta": delta,
        }), 200

    except Exception as e:
        logger.error("user/coaching/progress failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to load coaching progress",
        }), 500


# Capture the FIRST digit 1-10 in a string. We anchor on word-
# boundaries so "1000" won't match "10" and "v8" won't match. The
# "10|[1-9]" ordering matters — alternation is greedy left-to-right,
# so "10" must come first or "8 out of 10" would match "8" inside
# "10".
_SELF_RATING_RE = re.compile(r"\b(10|[1-9])\b")
# Phase 8 self-rating: bound the free-text payload so an abusive
# client can't ship megabytes through the endpoint. The frontend
# input is the chat composer (typically <200 chars).
_SELF_RATING_TEXT_MAX = 500


def _parse_self_rating_from_text(text: str) -> int | None:
    """Pull a 1..10 integer out of a free-form user reply.

    Returns the FIRST 1-10 number found, or None when nothing matches.
    A None return signals the caller to ask the user to retry (vs.
    silently defaulting to a wrong rating).
    """
    if not text:
        return None
    m = _SELF_RATING_RE.search(text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _first_self_rating(attempts: list[dict]) -> int | None:
    """First chronological self-rating present in ``attempts``.

    Used by /coaching/progress to show first → best progression.
    Attempts are already ordered by attempt_number ASC when the
    progress endpoint builds them.
    """
    for a in attempts:
        r = a.get("self_rating")
        if isinstance(r, int) and 1 <= r <= 10:
            return r
    return None


def _best_self_rating(attempts: list[dict]) -> int | None:
    """Highest self-rating across ``attempts``. None when no attempt has one."""
    ratings = [
        a.get("self_rating") for a in attempts
        if isinstance(a.get("self_rating"), int)
        and 1 <= a.get("self_rating") <= 10
    ]
    return max(ratings) if ratings else None


@v2_bp.route("/user/coaching/self-rating", methods=["POST"])
@require_auth
def v2_user_coaching_self_rating():
    """Capture the user's in-chat 1..10 self-rating for a coaching attempt.

    Phase 8 of the snippet-CTA learning loop. After the LLM evaluation
    lands in coaching_attempts (Phase 2), the frontend asks the user
    "on a scale of 1-10, how do you feel about that response?" inside
    the chat thread and POSTs the reply here.

    Body (any of these shapes works; ``rating`` wins when both are set)::

        { "snippet_id": "<uuid>", "rating": 8 }
        { "snippet_id": "<uuid>", "rating_text": "I'd say 8" }
        { "snippet_id": "<uuid>", "rating_text": "8", "attempt_number": 3 }

    ``attempt_number`` is optional — when omitted we target the most
    recent attempt for this (snippet, user). That is the common path
    because the rating ask follows the latest evaluation in the chat.

    Status codes:
      200 — rating accepted; response carries the persisted row.
      400 — input invalid (missing snippet_id, can't parse a 1..10).
      404 — snippet not owned by the requesting user.
      425 — no coaching_attempts row exists yet (race with the
            evaluation daemon). Client should retry after a beat.
      500 — unexpected error.
    """
    try:
        user_id = request.user_id
        body = request.get_json(silent=True) or {}

        snippet_id = (body.get("snippet_id") or "").strip()
        if not snippet_id or not _is_valid_uuid(snippet_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "snippet_id must be a valid UUID",
            }), 400

        attempt_number = body.get("attempt_number")
        if attempt_number is not None:
            try:
                attempt_number = int(attempt_number)
                if attempt_number < 1:
                    raise ValueError
            except (TypeError, ValueError):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "attempt_number must be a positive integer",
                }), 400

        rating_text_raw = (body.get("rating_text") or "")
        if not isinstance(rating_text_raw, str):
            rating_text_raw = str(rating_text_raw)
        rating_text = rating_text_raw[:_SELF_RATING_TEXT_MAX].strip() or None

        # rating wins when both shapes are sent — it's the explicit
        # numeric path the frontend uses when it already parsed the
        # number client-side.
        rating_val = body.get("rating")
        rating: int | None = None
        if rating_val is not None:
            try:
                rating = int(rating_val)
            except (TypeError, ValueError):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "rating must be an integer 1..10",
                }), 400
        elif rating_text:
            rating = _parse_self_rating_from_text(rating_text)

        if rating is None or not (1 <= rating <= 10):
            return jsonify({
                "code": "RATING_UNPARSEABLE",
                "error": "Could not read a number from 1 to 10 in the reply",
            }), 400

        # Owner check — block users from rating someone else's snippet.
        snippet = db.v2_get_charisma_snippet_for_user(snippet_id, user_id)
        if not snippet:
            return jsonify({
                "code": "NOT_FOUND",
                "error": "Snippet not found",
            }), 404

        updated = db.update_coaching_attempt_self_rating(
            snippet_id=snippet_id,
            user_id=user_id,
            rating=rating,
            rating_text=rating_text,
            attempt_number=attempt_number,
        )
        if not updated:
            # No row found for (snippet, user[, attempt_number]).
            # Most likely cause: the eval daemon hasn't finished
            # writing the coaching_attempts row yet. 425 (Too Early)
            # tells the client to retry shortly.
            return jsonify({
                "code": "ATTEMPT_NOT_READY",
                "error": (
                    "No coaching attempt found for this snippet yet. "
                    "Wait a moment and retry."
                ),
            }), 425

        return jsonify({
            "status": "ok",
            "snippet_id": snippet_id,
            "attempt_number": updated.get("attempt_number"),
            "self_rating": updated.get("self_rating"),
            "self_rating_text": updated.get("self_rating_text"),
            "self_rating_submitted_at": updated.get("self_rating_submitted_at"),
        }), 200

    except Exception as e:
        logger.error("user/coaching/self-rating failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to save self-rating",
        }), 500


@v2_bp.route("/user/learner-profile", methods=["GET"])
@require_auth
def v2_user_learner_profile():
    """Return the requesting user's inferred learner profile blob.

    Phase 3 — read-only diagnostic so admins can verify the recompute
    pipeline and the user can be shown their own progress narrative
    (frontend opt-in). The blob itself is whatever services/
    learner_profile.py wrote on the last successful recompute; this
    endpoint does NOT trigger a recompute (that runs on the outcome
    persist path).

    Response shape::

        {
          "profile": { ... } | null,
          "updated_at": "..." | null,
          "injection_enabled": true | false,
          "injection_eligible": true | false  # would the augmenter
                                              # actually use this blob
                                              # if injection was on?
        }

    ``injection_eligible`` mirrors the sample-size gate inside
    format_profile_for_prompt — it answers "does this profile have
    enough signal to actually shape the coaching prompt?" without
    leaking the raw threshold to the client.
    """
    try:
        user_id = request.user_id
        settings = db.get_user_settings(user_id) or {}
        profile = settings.get("inferred_learner_profile") or None
        updated_at = settings.get("inferred_learner_profile_updated_at")
        # Phase 9: surface override state so the frontend can show a
        # "Admin override active" badge. The override JSONB itself
        # is intentionally NOT returned to the end user — it may
        # contain admin notes meant for internal use only.
        override = settings.get("admin_profile_override") or None
        override_set_at = settings.get("admin_profile_override_set_at")

        from services.learner_profile import format_profile_for_prompt
        from config import Config

        injection_enabled = bool(Config().LEARNER_PROFILE_INJECTION_ENABLED)
        effective = _merge_admin_override_into_profile(
            inferred=profile,
            override=override,
        )
        injection_eligible = bool(format_profile_for_prompt(effective))

        return jsonify({
            "profile": profile,
            "updated_at": updated_at,
            "admin_override_active": override is not None,
            "admin_override_set_at": override_set_at,
            "injection_enabled": injection_enabled,
            "injection_eligible": injection_eligible,
        }), 200
    except Exception as e:
        logger.error("user/learner-profile failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to load learner profile",
        }), 500


_MIRROR_ERROR_STATUS: dict[str, tuple[int, str]] = {
    # services.learner_mirror error code → (HTTP status, client message)
    "NOT_ENOUGH_DATA": (
        409,
        "Not enough coaching attempts yet to generate a reflection.",
    ),
    "PROFILE_MISSING": (
        409,
        "No learner profile yet — record a coaching attempt first.",
    ),
    "LLM_UNAVAILABLE": (
        503,
        "The reflection generator is temporarily unavailable.",
    ),
    "LLM_ERROR": (
        502,
        "The reflection generator returned an unusable response. "
        "Try again in a moment.",
    ),
    "PERSIST_FAILED": (
        500,
        "Generated the reflection but couldn't save it. Try again.",
    ),
}


@v2_bp.route("/user/mirror", methods=["GET"])
@require_auth
def v2_user_mirror_get():
    """Return the requesting user's current learner mirror, if any.

    Phase 6 — read-only. Does NOT trigger generation. The frontend
    typically calls this on /results render and falls back to
    "tap to generate" UX when ``mirror`` is null.

    Response shape::

        {
          "feature_enabled": true,            # flag state
          "mirror": { ... } | null,            # the JSONB blob
          "generated_at": "..." | null
        }
    """
    try:
        user_id = request.user_id
        from config import Config

        feature_enabled = bool(Config().LEARNER_MIRROR_ENABLED)
        settings = db.get_user_settings(user_id) or {}
        mirror = settings.get("current_learner_mirror") or None
        generated_at = settings.get("current_learner_mirror_generated_at")
        return jsonify({
            "feature_enabled": feature_enabled,
            "mirror": mirror,
            "generated_at": generated_at,
        }), 200
    except Exception as e:
        logger.error("user/mirror GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to load mirror",
        }), 500


@v2_bp.route("/user/mirror/generate", methods=["POST"])
@require_auth
def v2_user_mirror_generate():
    """Generate a fresh learner mirror for the requesting user.

    Phase 6 — on-demand, user-triggered. One LLM call per request,
    grounded in the user's inferred learner profile + recent
    coaching attempts. Replaces the prior mirror on success.

    Response (200):
        { "mirror": {...}, "generated_at": "..." }
    Failure codes map to HTTP via _MIRROR_ERROR_STATUS — clients
    can switch on the ``code`` field to render appropriate UX
    (e.g. NOT_ENOUGH_DATA → "keep practising, come back at 3 attempts").
    """
    try:
        user_id = request.user_id
        from config import Config
        if not Config().LEARNER_MIRROR_ENABLED:
            return jsonify({
                "code": "FEATURE_DISABLED",
                "error": "Learner mirror is not enabled for this deployment.",
            }), 503

        from services.learner_mirror import generate_learner_mirror
        mirror, err = generate_learner_mirror(user_id)
        if err:
            status, message = _MIRROR_ERROR_STATUS.get(
                err, (500, "Failed to generate mirror"),
            )
            return jsonify({"code": err, "error": message}), status

        return jsonify({
            "mirror": mirror,
            "generated_at": mirror.get("generated_at") if mirror else None,
        }), 200
    except Exception as e:
        logger.error("user/mirror/generate failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to generate mirror",
        }), 500


# ── Phase 9: admin RLHF + profile override ──────────────────────────────


# How many coaching-attempt annotations an admin needs before
# bulk-approve unlocks on the frontend. Exposed by the annotations
# count endpoint so the UI can render a progress indicator. Tuneable
# without a release: just change the constant.
_BULK_APPROVE_THRESHOLD = 100

_ANNOTATION_ACTIONS = {"approved", "edited", "flagged", "rejected"}


@v2_bp.route(
    "/admin/coaching-attempts/<attempt_id>/annotations",
    methods=["POST"],
)
@require_admin
def v2_admin_coaching_attempt_annotation_create(attempt_id):
    """Persist an admin annotation on one coaching attempt.

    Phase 9 — captures admin RLHF on a Phase 2 attempt row. Each
    POST creates a NEW annotation; the same attempt can be reviewed
    by multiple admins and an admin can revise their own verdict by
    posting again (history is preserved by design).

    Body (all fields optional except admin_action)::

        {
          "admin_action": "approved" | "edited" | "flagged" | "rejected",
          "admin_score": 0.78,
          "admin_components": { "specificity": 0.7, ... },
          "admin_note": "Score was generous on engagement.",
          "ai_score_was_correct": false,
          "reason_chip": "score_inflated"
        }

    Response: 201 with the persisted row + the admin's running
    annotations count (for the bulk-approve gate).
    """
    try:
        admin_user_id = request.user_id
        if not _is_valid_uuid(attempt_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "attempt_id must be a valid UUID",
            }), 400

        body = request.get_json(silent=True) or {}
        action = (body.get("admin_action") or "").strip().lower()
        if action not in _ANNOTATION_ACTIONS:
            return jsonify({
                "code": "INVALID_ACTION",
                "error": (
                    "admin_action must be one of: "
                    + ", ".join(sorted(_ANNOTATION_ACTIONS))
                ),
            }), 400

        admin_score = body.get("admin_score")
        if admin_score is not None:
            try:
                admin_score = float(admin_score)
                if not (0.0 <= admin_score <= 1.0):
                    raise ValueError
            except (TypeError, ValueError):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "admin_score must be a number in [0, 1]",
                }), 400

        admin_components = body.get("admin_components")
        if admin_components is not None and not isinstance(admin_components, dict):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "admin_components must be an object",
            }), 400

        admin_note = body.get("admin_note")
        if isinstance(admin_note, str):
            admin_note = admin_note.strip()[:2000] or None
        else:
            admin_note = None

        ai_correct = body.get("ai_score_was_correct")
        if ai_correct is not None and not isinstance(ai_correct, bool):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "ai_score_was_correct must be boolean",
            }), 400

        reason_chip = body.get("reason_chip")
        if isinstance(reason_chip, str):
            reason_chip = reason_chip.strip()[:80] or None
        else:
            reason_chip = None

        inserted = db.insert_coaching_attempt_annotation(
            coaching_attempt_id=attempt_id,
            admin_user_id=admin_user_id,
            admin_action=action,
            admin_score=admin_score,
            admin_components=admin_components,
            admin_note=admin_note,
            ai_score_was_correct=ai_correct,
            reason_chip=reason_chip,
        )
        if not inserted:
            return jsonify({
                "code": "PERSIST_FAILED",
                "error": (
                    "Could not save annotation — the attempt may not "
                    "exist or the annotations table is not migrated."
                ),
            }), 500

        admin_count = db.count_annotations_by_admin(admin_user_id)

        return jsonify({
            "annotation": inserted,
            "admin_annotations_count": admin_count,
            "bulk_approve_threshold": _BULK_APPROVE_THRESHOLD,
            "bulk_approve_unlocked": admin_count >= _BULK_APPROVE_THRESHOLD,
        }), 201

    except Exception as e:
        logger.error(
            "admin/coaching-attempts/<id>/annotations POST failed: %s",
            e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to save annotation",
        }), 500


@v2_bp.route(
    "/admin/coaching-attempts/<attempt_id>/annotations",
    methods=["GET"],
)
@require_admin
def v2_admin_coaching_attempt_annotation_list(attempt_id):
    """List all annotations on one coaching attempt, newest first."""
    try:
        if not _is_valid_uuid(attempt_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "attempt_id must be a valid UUID",
            }), 400
        annotations = db.list_annotations_for_coaching_attempt(attempt_id)
        return jsonify({
            "attempt_id": attempt_id,
            "annotations": annotations,
        }), 200
    except Exception as e:
        logger.error(
            "admin/coaching-attempts/<id>/annotations GET failed: %s",
            e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to load annotations",
        }), 500


@v2_bp.route(
    "/admin/users/<user_id>/learner-profile-override",
    methods=["PUT", "DELETE"],
)
@require_admin
def v2_admin_user_learner_profile_override(user_id):
    """Set, replace, or clear an admin override of the inferred profile.

    Phase 9. The override wins over the inferred profile inside
    _augment_coaching_system_prompt when present. Same shape as
    inferred_learner_profile.traits — admins typically set a small
    diff (e.g. flip score_trend to "improving") and leave other
    traits unset, in which case the augmenter merges field-by-field
    from the inferred profile.

    PUT body::

        {
          "traits": { ... },          # required
          "note": "Short rationale"   # optional, stored verbatim
        }

    DELETE clears the override (resets to inferred).
    """
    try:
        if not _is_valid_uuid(user_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "user_id must be a valid UUID",
            }), 400

        if request.method == "DELETE":
            row = db.set_user_admin_profile_override(
                user_id=user_id,
                override=None,
                set_by=request.user_id,
            )
            if not row:
                return jsonify({
                    "code": "PERSIST_FAILED",
                    "error": "Could not clear override",
                }), 500
            return jsonify({"status": "cleared"}), 200

        body = request.get_json(silent=True) or {}
        traits = body.get("traits")
        if not isinstance(traits, dict) or not traits:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "traits must be a non-empty object",
            }), 400
        note_raw = body.get("note")
        note = (
            note_raw.strip()[:1000]
            if isinstance(note_raw, str) and note_raw.strip()
            else None
        )

        override = {
            "version": "override-v1",
            "set_by": str(request.user_id),
            "set_at": datetime.now(timezone.utc).isoformat(),
            "note": note,
            # The injection gate in services/learner_profile.py
            # checks attempts_analyzed >= MIN_ATTEMPTS_TO_INJECT;
            # the override should always be eligible regardless of
            # how many real attempts the user has, so we stamp a
            # synthetic value that clears the gate.
            "attempts_analyzed": 999,
            "traits": traits,
        }
        row = db.set_user_admin_profile_override(
            user_id=user_id,
            override=override,
            set_by=request.user_id,
        )
        if not row:
            return jsonify({
                "code": "PERSIST_FAILED",
                "error": "Could not save override",
            }), 500
        return jsonify({"status": "ok", "override": override}), 200

    except Exception as e:
        logger.error(
            "admin/users/<id>/learner-profile-override failed: %s",
            e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to update profile override",
        }), 500


@v2_bp.route("/admin/me/annotation-progress", methods=["GET"])
@require_admin
def v2_admin_me_annotation_progress():
    """How many coaching-attempt annotations the requesting admin has logged.

    Drives the frontend's bulk-approve gate (unlocks once count
    reaches _BULK_APPROVE_THRESHOLD).
    """
    try:
        count = db.count_annotations_by_admin(request.user_id)
        return jsonify({
            "admin_annotations_count": count,
            "bulk_approve_threshold": _BULK_APPROVE_THRESHOLD,
            "bulk_approve_unlocked": count >= _BULK_APPROVE_THRESHOLD,
        }), 200
    except Exception as e:
        logger.error(
            "admin/me/annotation-progress failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to load annotation progress",
        }), 500


@v2_bp.route("/public/interview/next-question", methods=["POST"])
def v2_public_interview_next_question():
    """Return the next interview question.

    Turns 1-4: EBCP Baseline Mapping (Frustration → Relief → Familiarity factors).
    Turns 5+:  Open-ended charisma/stress alternating questions.

    Input:  { turn_number: int, user_id?: str, previous_turns?: [{question, transcript?}] }
    Output: { question: str, tone: "charisma"|"stress"|"ebcp", turn_number: int, source: str }
    """
    try:
        body = request.get_json(silent=True) or {}
        turn_number = int(body.get("turn_number", 1))
        if turn_number < 1:
            turn_number = 1

        user_id = (body.get("user_id") or "").strip() or None
        previous_turns = body.get("previous_turns") or None

        # ── EBCP Baseline Mapping: turns 1-4 ─────────────────────────────────
        if turn_number <= 4:
            question = _generate_ebcp_question(turn_number, previous_turns)
            if not question:
                question = _EBCP_FALLBACKS.get(turn_number, _EBCP_FALLBACKS[4])
                source = "ebcp_fallback"
            else:
                source = "ebcp_llm"

            return jsonify({
                "question": question,
                "tone": "charisma",  # EBCP turns register as charisma
                "turn_number": turn_number,
                "source": source,
            }), 200

        # ── Regular charisma/stress alternation: turns 5+ ────────────────────
        # Offset so turn 5 is the first post-EBCP turn (charisma), turn 6 is stress, etc.
        post_ebcp_index = turn_number - 4  # 1, 2, 3 …
        tone = "charisma" if post_ebcp_index % 2 == 1 else "stress"

        question = _generate_llm_question(
            turn_number=turn_number,
            tone=tone,
            previous_turns=previous_turns,
            user_id=user_id,
        )
        source = "llm" if question else "fallback"

        if not question:
            pool = _INTERVIEW_QUESTIONS_FALLBACK[tone]
            question_index = ((post_ebcp_index - 1) // 2) % len(pool)
            question = pool[question_index]

        return jsonify({
            "question": question,
            "tone": tone,
            "turn_number": turn_number,
            "source": source,
        }), 200

    except Exception as e:
        logger.error("interview/next-question failed: %s", e, exc_info=True)
        return jsonify({"code": "V2_ERROR", "error": "Failed to get question"}), 500


@v2_bp.route("/public/interview/upload-answer", methods=["POST"])
def v2_public_interview_upload_answer():
    """Upload one interview answer (audio chunk) and attach it to a session.

    First call (no guest_session_id): creates a new guest session.
    Subsequent calls (with guest_session_id): appends to existing session.

    Each chunk becomes a charisma_snippet with pre-computed acoustic metrics.

    Returns: {
        guest_session_id, snippet_id, duration_seconds,
        total_session_duration_seconds, metrics
    }
    """
    if not getattr(config, "GUEST_FUNNEL_ENABLED", False):
        return jsonify({"code": "GUEST_FUNNEL_DISABLED", "error": "Guest funnel is disabled"}), 503

    try:
        client_ip = _client_ip_from_request()
        allowed, reason = _guest_funnel_rate_limit_check(client_ip)
        if not allowed:
            return jsonify({"code": "RATE_LIMITED", "error": "Too many uploads — please wait."}), 429

        if "audio_file" not in request.files:
            return jsonify({"code": "AUDIO_FILE_REQUIRED", "error": "audio_file is required"}), 400
        audio_file = request.files.get("audio_file")

        try:
            original_name, ext = _admin_import_validate_audio_file(audio_file)
        except ValueError as ve:
            msg = str(ve)
            if msg == "unsupported audio format":
                return jsonify({"code": "UNSUPPORTED_AUDIO_FORMAT", "error": msg}), 415
            return jsonify({"code": "AUDIO_FILE_REQUIRED", "error": msg}), 400

        max_mb = int(getattr(config, "GUEST_FUNNEL_MAX_AUDIO_SIZE_MB", 10) or 10)
        max_bytes = max_mb * 1024 * 1024
        file_bytes = audio_file.read()
        if not file_bytes or len(file_bytes) > max_bytes:
            return jsonify({"code": "FILE_TOO_LARGE", "error": f"File exceeds {max_mb}MB"}), 413

        form = request.form or {}
        guest_session_id = (form.get("guest_session_id") or "").strip() or None
        turn_number = int(form.get("turn_number", 1) or 1)
        question_tone = (form.get("question_tone") or "charisma").strip()

        duration_raw = form.get("duration_seconds")
        try:
            duration_seconds = float(duration_raw) if duration_raw not in (None, "") else None
        except (TypeError, ValueError):
            duration_seconds = None

        content_type = (audio_file.mimetype or mimetypes.guess_type(original_name)[0] or "application/octet-stream").strip()
        if content_type in ("True", "False"):
            content_type = "application/octet-stream"

        # Create session on first turn, reuse on subsequent turns
        is_first_turn = guest_session_id is None
        if is_first_turn:
            guest_session_id = str(uuid.uuid4())
            try:
                db.v2_create_guest_session(guest_session_id)
            except Exception as session_err:
                logger.warning("interview: create session failed: %s", session_err, exc_info=True)
                return jsonify({"code": "SESSION_CREATE_FAILED", "error": "Failed to create session"}), 500

        # Upload audio to the dedicated R2 audio bucket via the
        # services.audio_storage helper. The helper writes to
        # R2_AUDIO_BUCKET_NAME when configured (production) and falls
        # back to Supabase Storage AUDIO_BUCKET_NAME in dev. Single
        # source of truth — every reader downstream uses the matching
        # get_audio_bytes() helper so writes and reads can never drift
        # apart again.
        storage_path = f"guest_funnel/{guest_session_id}/turn_{turn_number}_{uuid.uuid4().hex[:8]}{ext}"
        try:
            from services.audio_storage import put_audio_bytes
            put_audio_bytes(storage_path, file_bytes, content_type=content_type)
        except Exception as upload_err:
            logger.warning("interview: storage upload failed: %s", upload_err, exc_info=True)
            return jsonify({"code": "UPLOAD_FAILED", "error": "Failed to store audio"}), 500

        # Create a recording_1 row on first turn (so claim flow works).
        # On subsequent turns we reuse the SAME recording_id by reading it
        # back from the session — generating a fresh uuid on every call
        # caused a silent foreign-key violation on the snippet insert
        # (charisma_snippets.recording_id references recordings.id) and
        # was the reason only turn 1 ever showed up in the admin
        # timeline. Multiple turns conceptually share one parent
        # recording on the guest interview path.
        if is_first_turn:
            recording_id = str(uuid.uuid4())
            rec_payload = {
                "id": recording_id,
                "user_id": None,
                "session_id": None,
                "session_v2_id": guest_session_id,
                "storage_path": storage_path,
                "audio_url": "",
                "duration": 0,
                "recording_origin": "guest_funnel",
            }
            if duration_seconds is not None:
                rec_payload["duration_seconds"] = duration_seconds
            try:
                db.create_recording(rec_payload)
            except Exception as create_err:
                err_low = str(create_err).lower()
                if "recording_origin" in err_low:
                    fallback = {k: v for k, v in rec_payload.items() if k != "recording_origin"}
                    try:
                        db.create_recording(fallback)
                    except Exception:
                        pass
            try:
                db.v2_set_guest_session_recording(guest_session_id, recording_id)
            except Exception:
                pass
        else:
            # Re-use the session's bound recording. If for any reason it
            # isn't bound, fail loudly rather than insert a snippet with
            # a dangling FK that would silently crash the row.
            recording_id = None
            try:
                existing_session = db.v2_get_session_by_id(guest_session_id)
                if existing_session:
                    recording_id = existing_session.get("recording_1_id")
            except Exception as lookup_err:
                logger.warning(
                    "interview: turn %d session lookup failed: %s",
                    turn_number, lookup_err,
                )
            if not recording_id:
                logger.error(
                    "interview: turn %d for session %s has no parent recording — "
                    "first-turn create must have failed; refusing snippet insert",
                    turn_number, guest_session_id,
                )
                return jsonify({
                    "code": "RECORDING_MISSING",
                    "error": "Parent recording is missing — record turn 1 again.",
                }), 409

        # Read optional question_text from form (so we can store it with the snippet)
        question_text = (form.get("question_text") or "").strip() or None

        # Read optional source_snippet_id from form. Set by the /chat
        # client when this chat was initiated by clicking a CTA on a
        # published snippet (/chat?sourceSnippet=<id>&intent=…). When
        # present AND this is turn 1, we score the user's answer
        # against the source snippet's admin_comment + transcript in a
        # background thread and write the result onto the source
        # snippet's follow_up_outcome column. This is how the system
        # starts learning whether the admin's coaching annotation
        # actually produced meaningful reflection.
        source_snippet_id_raw = (form.get("source_snippet_id") or "").strip()
        source_snippet_id = (
            source_snippet_id_raw if _is_valid_uuid(source_snippet_id_raw) else None
        )

        # Compute acoustic metrics for this chunk
        snippet_metrics = None
        try:
            from services.snippet_extraction import _compute_snippet_metrics
            snippet_metrics = _compute_snippet_metrics(audio_bytes=file_bytes, duration_seconds=duration_seconds)
        except Exception as m_err:
            logger.warning("interview: metrics failed (non-fatal): %s", m_err)

        # Transcribe audio via Whisper — used for EBCP branching logic in next-question
        transcript_text = None
        try:
            import io as _io
            from services.openai_service import OpenAIService as _OAI
            _ai = _OAI()
            if _ai.client:
                _result = _ai.transcribe_audio(
                    audio_file=_io.BytesIO(file_bytes),
                    filename=original_name,
                    content_type=content_type if content_type != "application/octet-stream" else None,
                )
                transcript_text = (_result.get("text") or "").strip() or None
                # Log at WARNING so the line is visible regardless of
                # Railway's log-level filter (their default surface
                # often hides INFO). Two states to distinguish:
                #   - Whisper ran, returned text → useful transcript
                #   - Whisper ran, returned empty → audio was silent
                if transcript_text:
                    logger.warning(
                        "interview: Whisper OK session=%s turn=%s "
                        "text_chars=%d size=%d",
                        guest_session_id, turn_number,
                        len(transcript_text), len(file_bytes),
                    )
                else:
                    logger.warning(
                        "interview: Whisper returned empty transcript "
                        "(audio likely silent) session=%s turn=%s size=%d",
                        guest_session_id, turn_number, len(file_bytes),
                    )
            else:
                # Loud failure mode: silent skip is what made every row's
                # transcript NULL despite operators believing the key was
                # set. Now there's an explicit signal in Railway logs.
                logger.error(
                    "interview: OpenAI client is None — OPENAI_API_KEY is "
                    "missing or empty in this process's environment. "
                    "Transcription skipped for session=%s turn=%s",
                    guest_session_id, turn_number,
                )
        except Exception as t_err:
            logger.warning("interview: transcription failed (non-fatal): %s", t_err)

        # Build the stable public URL for the snippet audio via the
        # audio-bucket helper (R2_AUDIO_PUBLIC_BASE_URL in production).
        # Mirrors the put_audio_bytes call above — same bucket on the
        # write, same bucket on the URL.
        snippet_url = ""
        try:
            from services.audio_storage import audio_public_url
            snippet_url = audio_public_url(storage_path) or ""
        except Exception:
            pass
        if not snippet_url:
            snippet_url = storage_path

        # Create charisma_snippet row — one per interview turn
        # user_id is NULL until guest signs up and claims the session.
        # update_snippets_user_id() in the claim flow sets the real user_id.
        snippet_dict = None
        try:
            snippet_payload = {
                # Schema canonical column is `transcript` (see
                # migrations/add_charisma_snippet_pipeline.sql); using
                # the legacy `transcript_text` here caused PostgREST
                # PGRST204 ("unknown column") on every insert, dropping
                # us into the fallback path that strips the turn_number
                # / question_text / transcript metadata — which is why
                # the admin timeline rendered "No interview turns".
                "transcript": transcript_text,  # Whisper output (may be None)
                "session_id": guest_session_id,
                "recording_id": recording_id,
                # Canonical boundary representation (the ONLY pair that
                # exists in the schema). The seconds-float pair
                # (start_time/end_time) used to be written here too but
                # the columns are phantom — PostgREST silently drops
                # them on INSERT and erroneously rolls back on UPDATE
                # (see services/db.py::update_snippet_boundaries for
                # the PGRST204 trail). Don't reintroduce.
                "start_offset_ms": 0,
                "duration_ms": int((duration_seconds or 10) * 1000),
                "audio_segment_path": snippet_url,
                "snippet_type": "unlabeled",
                "turn_number": turn_number,
                "question_text": question_text,
                "question_tone": question_tone,
            }
            # Store individual metric columns + JSONB blob
            if snippet_metrics:
                snippet_payload["metrics"] = snippet_metrics
                snippet_payload["wpm"] = snippet_metrics.get("wpm")
                snippet_payload["pause_ms"] = snippet_metrics.get("pause_ms")
                snippet_payload["dynamic_db"] = snippet_metrics.get("dynamic_db")
                snippet_payload["pitch_center"] = snippet_metrics.get("pitch_center_st")
                snippet_payload["energy"] = snippet_metrics.get("energy_ratio")
                # fillers require transcript (done later via Whisper if available)
                snippet_payload["fillers"] = None

            result = db.client.table("charisma_snippets").insert(snippet_payload).execute()
            snippet_dict = result.data[0] if result.data else None
        except Exception as s_err:
            logger.warning("interview: create snippet failed: %s", s_err, exc_info=True)
            # Fallback to old create function (in case new columns don't exist yet)
            try:
                snippet_dict = db.create_charisma_snippet(
                    session_id=guest_session_id,
                    user_id=None,
                    recording_id=recording_id,
                    start_offset_ms=0,
                    duration_ms=int((duration_seconds or 10) * 1000),
                    audio_segment_path=snippet_url,
                    metrics=snippet_metrics,
                )
            except Exception:
                pass

        # Calculate total session duration across all snippets
        total_duration = 0.0
        try:
            all_snippets = db.get_snippets_by_session(guest_session_id)
            for s in all_snippets:
                total_duration += (s.get("duration_ms") or 0) / 1000.0
        except Exception:
            total_duration = duration_seconds or 0.0

        logger.info(
            "interview: uploaded turn=%d tone=%s duration=%.1fs total=%.1fs session=%s",
            turn_number, question_tone, duration_seconds or 0, total_duration, guest_session_id,
        )

        # Auto-finalize: kick off ffmpeg concat + session-level metric
        # aggregation in a background thread so the upload response isn't
        # blocked. Idempotent — running after every turn just means the
        # canonical recording is always up-to-date; the final run (after
        # the last turn) is the one that matters for admin playback.
        # Errors inside the thread are logged but never raised; a finalize
        # failure must not affect the turn-upload response.
        try:
            _run_session_finalize_in_bg(guest_session_id)
        except Exception as bg_err:
            # _run_session_finalize_in_bg itself shouldn't raise (it only
            # starts a thread) — but if it does, swallow so we don't fail
            # the upload that already succeeded.
            logger.warning(
                "auto-finalize: failed to schedule for session=%s: %s",
                guest_session_id, bg_err,
            )

        # Coaching outcome capture: when this turn is the FIRST turn of
        # a contextual chat (frontend passed source_snippet_id, set
        # via /chat?sourceSnippet=<id>&intent=…), spawn a daemon thread
        # that scores the user's answer against the source snippet's
        # admin coach insight + transcript and writes the outcome onto
        # the source snippet's follow_up_outcome JSONB column.
        #
        # First piece of the learning loop. Collect silently for now;
        # later commits surface the score in the admin UI and feed
        # successful exchanges into few-shot question generation.
        #
        # This endpoint is otherwise unauthenticated (guest funnel
        # supports anon uploads). We do a best-effort JWT extract from
        # the Authorization header just for the contextual branch —
        # the snippet load inside evaluate_and_record_followup_outcome
        # is owner-scoped on the decoded user_id, so a missing/invalid
        # token simply skips the outcome write.
        if (
            source_snippet_id is not None
            and turn_number == 1
            and (transcript_text or "").strip()
        ):
            authed_user_id = None
            try:
                from auth import verify_supabase_token
                auth_header = request.headers.get("Authorization") or ""
                if auth_header.startswith("Bearer "):
                    _payload = verify_supabase_token(
                        auth_header[len("Bearer "):].strip()
                    )
                    authed_user_id = (_payload or {}).get("sub")
            except Exception as auth_err:
                logger.info(
                    "outcome:skip reason=auth_decode_failed source_snippet=%s err=%s",
                    source_snippet_id, auth_err,
                )

            if authed_user_id:
                _scored_user_id = str(authed_user_id)
                _scored_snippet_id = source_snippet_id
                _scored_answer = transcript_text or ""
                _scored_duration_ms = int((duration_seconds or 0) * 1000)
                _scored_question = question_text

                def _outcome_worker():
                    try:
                        from services.coaching_outcomes import (
                            evaluate_and_record_followup_outcome,
                        )
                        evaluate_and_record_followup_outcome(
                            source_snippet_id=_scored_snippet_id,
                            user_id=_scored_user_id,
                            user_answer_text=_scored_answer,
                            user_answer_duration_ms=_scored_duration_ms,
                            asked_question=_scored_question,
                        )
                    except Exception as inner:
                        logger.warning(
                            "outcome:bg-thread failure source_snippet=%s err=%s",
                            _scored_snippet_id, inner,
                        )

                try:
                    threading.Thread(
                        target=_outcome_worker,
                        daemon=True,
                        name=f"outcome-{source_snippet_id[:8]}",
                    ).start()
                except Exception as out_err:
                    logger.warning(
                        "outcome: failed to schedule for source_snippet=%s: %s",
                        source_snippet_id, out_err,
                    )

        return jsonify({
            "status": "ok",
            "guest_session_id": guest_session_id,
            "snippet_id": snippet_dict.get("id") if snippet_dict else None,
            "duration_seconds": duration_seconds,
            "total_session_duration_seconds": round(total_duration, 1),
            "metrics": snippet_metrics,
            "transcript": transcript_text,  # Whisper transcript for EBCP branching
        }), 201

    except Exception as e:
        logger.error("interview: upload failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Upload failed"}), 500


def _merge_anonymous_session_into_user(session_id: str, user_id: str):
    """Bind an unclaimed anonymous session to an authenticated user.

    Shared between two endpoints that differ only in payload field name:
      * POST /v2/public/shaky-voice/claim   (cold-start funnel, field=guest_session_id)
      * POST /v2/auth/merge-session         (post-OAuth merge, field=anonymous_session_id)

    Idempotent semantics:
      * Unclaimed                          → claim, enqueue pipeline, 200 + session_id
      * Already claimed by same user       → 200 + session_id (no-op)
      * Already claimed by different user  → 409 ALREADY_CLAIMED
      * Not found                          → 404 GUEST_SESSION_NOT_FOUND
      * Older than TTL                     → 410 GUEST_SESSION_EXPIRED

    Side effects on a successful first claim:
      * UPDATE v2_sessions SET user_id, guest_claimed_at, status, ...
      * UPDATE recording row's user_id
      * Enqueue recording_1_job (analysis pipeline)
      * Extract initial charisma snippets
      * Re-stamp interview snippets with real user_id

    Returns:
        (response_body: dict, http_status: int)
    """
    from services.recording_1_job import enqueue_recording_1_job

    if not getattr(config, "GUEST_FUNNEL_ENABLED", False):
        return ({"code": "GUEST_FUNNEL_DISABLED", "error": "Guest funnel is disabled"}, 503)

    # Probe the session's current state first so we can return precise error
    # codes. The atomic claim happens in v2_claim_guest_session.
    existing = db.v2_get_session_by_id(session_id)
    if not existing:
        return ({
            "code": "GUEST_SESSION_NOT_FOUND",
            "error": "That trial recording was not found. It may have expired — please record again.",
        }, 404)

    existing_user = existing.get("user_id")
    if existing_user and str(existing_user) != str(user_id):
        return ({
            "code": "ALREADY_CLAIMED",
            "error": "This trial recording was already claimed by a different account.",
        }, 409)
    if existing_user and str(existing_user) == str(user_id):
        # Idempotent re-claim: return the bound session_id without re-enqueueing.
        return ({
            "status": "ok",
            "session_id": str(existing.get("id")),
            "analysis_status": "already_claimed",
        }, 200)

    # TTL guard: even if the cleanup job hasn't run yet, refuse to claim
    # a row older than the configured window.
    try:
        from datetime import datetime, timedelta, timezone
        ttl_hours = int(getattr(config, "GUEST_FUNNEL_TTL_HOURS", 24) or 24)
        created_raw = existing.get("created_at")
        if created_raw:
            if isinstance(created_raw, str):
                created_dt = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            else:
                created_dt = created_raw
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - created_dt > timedelta(hours=ttl_hours):
                return ({
                    "code": "GUEST_SESSION_EXPIRED",
                    "error": "Your trial recording expired. Please record again.",
                }, 410)
    except Exception as ttl_err:
        logger.warning("guest_funnel: ttl check failed (continuing): %s", ttl_err)

    claimed = db.v2_claim_guest_session(session_id, user_id)
    if not claimed:
        # Race lost: someone (or the same user via duplicate request) just
        # bound the row between our probe and the atomic update.
        after = db.v2_get_session_by_id(session_id) or {}
        after_user = after.get("user_id")
        if after_user and str(after_user) == str(user_id):
            return ({
                "status": "ok",
                "session_id": str(after.get("id")),
                "analysis_status": "already_claimed",
            }, 200)
        return ({
            "code": "ALREADY_CLAIMED",
            "error": "This trial recording was already claimed.",
        }, 409)

    # Pipeline: same recording_1_job that handles live student recordings
    # and admin calibration uploads. The job will auto-complete because
    # v2_claim_guest_session stamps self_rating_submitted_at.
    rec_id = claimed.get("recording_1_id")
    rec_row = db.get_recording(rec_id, user_id) if rec_id else None
    storage_path = (rec_row or {}).get("storage_path")
    duration_seconds = (rec_row or {}).get("duration_seconds")
    if rec_id and storage_path:
        try:
            enqueue_recording_1_job(
                str(claimed.get("id")),
                str(rec_id),
                storage_path,
                user_id,
                duration_seconds,
            )
        except Exception as q_err:
            logger.warning("guest_funnel: enqueue_recording_1_job failed: %s", q_err, exc_info=True)
            # Don't unwind the claim — the row is bound; admin can retry.

        # Extract charisma snippets from the recording (MVP: entire recording as one snippet)
        try:
            from services.snippet_extraction import extract_recording_snippets
            extract_recording_snippets(
                session_id=str(claimed.get("id")),
                user_id=str(user_id),
                recording_id=str(rec_id),
                recording_path=storage_path,
                duration_seconds=duration_seconds,
            )
        except Exception as snippet_err:
            logger.warning("guest_funnel: extract_recording_snippets failed: %s", snippet_err, exc_info=True)
            # Non-fatal: admin can manually extract snippets later if needed

    # Update all interview snippets to point to the real user
    try:
        updated_count = db.update_snippets_user_id(session_id, str(user_id))
        if updated_count:
            logger.info("guest_funnel: updated %d snippet user_ids", updated_count)
    except Exception as uid_err:
        logger.warning("guest_funnel: update_snippets_user_id failed: %s", uid_err)

    logger.info(
        "guest_funnel: claim ok user_id=%s session_id=%s recording_id=%s",
        user_id, session_id, rec_id,
    )
    return ({
        "status": "ok",
        "session_id": str(claimed.get("id")),
        "analysis_status": "queued",
    }, 200)


@v2_bp.route("/public/shaky-voice/claim", methods=["POST"])
@require_auth
def v2_public_shaky_voice_claim():
    """Bind an unclaimed funnel session (cold-start funnel) to the authenticated user.

    Thin wrapper around `_merge_anonymous_session_into_user`. Accepts
    `guest_session_id` for backwards compatibility with the existing funnel
    client. New OAuth callers should prefer POST /v2/auth/merge-session.
    """
    try:
        body = request.get_json(silent=True) or {}
        guest_session_id = (body.get("guest_session_id") or "").strip()
        if not _is_valid_uuid(guest_session_id):
            return jsonify({"code": "INVALID_INPUT", "error": "guest_session_id must be a UUID"}), 400

        response, status = _merge_anonymous_session_into_user(guest_session_id, request.user_id)
        return jsonify(response), status

    except Exception as e:
        logger.error("guest_funnel: claim failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Claim failed"}), 500


@v2_bp.route("/auth/merge-session", methods=["POST"])
@require_auth
def v2_auth_merge_session():
    """Merge an anonymous cold-start session into the authenticated user account.

    Built for the LinkedIn OAuth flow: the user records anonymously, the
    frontend stashes the `anonymous_session_id`, the OAuth roundtrip
    establishes a session, and the frontend posts the stashed id here so
    the recording, messages, audio files, and snippets are linked to the
    new (or returning) user.

    Auth: required (Bearer token from Supabase session).

    Body: { "anonymous_session_id": "<uuid>" }

    Responses:
        200 { status, session_id, analysis_status: "queued" | "already_claimed" }
        400 INVALID_INPUT          — id missing / not a UUID
        404 GUEST_SESSION_NOT_FOUND — id doesn't match any session
        409 ALREADY_CLAIMED        — session belongs to a different user
        410 GUEST_SESSION_EXPIRED  — older than GUEST_FUNNEL_TTL_HOURS
        500 V2_ERROR               — unexpected server error
        503 GUEST_FUNNEL_DISABLED  — feature flag off
    """
    try:
        body = request.get_json(silent=True) or {}
        anonymous_session_id = (body.get("anonymous_session_id") or "").strip()
        if not _is_valid_uuid(anonymous_session_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "anonymous_session_id must be a UUID",
            }), 400

        response, status = _merge_anonymous_session_into_user(
            anonymous_session_id, request.user_id
        )
        return jsonify(response), status

    except Exception as e:
        logger.error("merge_session: merge failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Session merge failed"}), 500


@v2_bp.route("/auth/signup", methods=["POST"])
def v2_auth_signup():
    """Alias for /auth/signup under the /v2/auth/* namespace.

    The native registration handler lives on `auth_bp` (mounted at `/auth`),
    but the BFF posts to `/v2/auth/signup` to match the sibling
    `/v2/auth/merge-session` endpoint and keep the BFF surface consistent
    under one namespace. This route delegates to the same function so both
    paths produce identical behaviour and the legal-consent gate is
    enforced regardless of which path callers hit.
    """
    from routes.auth import signup as _native_signup
    return _native_signup()


@v2_bp.route("/admin/funnel/afterwards-video", methods=["POST"])
@require_admin
def v2_admin_funnel_afterwards_video_upload():
    """Admin endpoint to upload and configure the afterwards video for Curiosity Gate funnel.

    Accepts multipart form with video_file field, uploads to storage, and stores the URL
    in the funnel_config table.
    """
    from services.coach_video_storage import coach_media_public_url, put_coach_object_bytes
    from datetime import datetime
    import os

    try:
        max_video_mb = max(1, int(getattr(config, "FUNNEL_AFTERWARDS_VIDEO_MAX_MB", 100)))
        max_video_bytes = max_video_mb * 1024 * 1024
        content_length = request.content_length or 0
        if content_length and content_length > max_video_bytes:
            return jsonify({
                "code": "PAYLOAD_TOO_LARGE",
                "error": f"Video is too large. Max allowed is {max_video_mb}MB.",
            }), 413

        video_file = request.files.get("video_file")
        if video_file is None or not (video_file.filename or "").strip():
            return jsonify({"code": "INVALID_INPUT", "error": "video_file is required"}), 400

        safe_name = secure_filename(video_file.filename or "")
        ext = os.path.splitext(safe_name)[1].lower()
        if ext not in {".mp4", ".mov", ".webm", ".m4v"}:
            return jsonify({
                "code": "INVALID_VIDEO_FORMAT",
                "error": "Supported formats: .mp4, .mov, .webm, .m4v",
            }), 415

        video_bytes = video_file.read() or b""
        if not video_bytes:
            return jsonify({"code": "INVALID_INPUT", "error": "video_file is empty"}), 400

        if len(video_bytes) > max_video_bytes:
            return jsonify({
                "code": "PAYLOAD_TOO_LARGE",
                "error": f"Video is too large. Max allowed is {max_video_mb}MB.",
            }), 413

        # Generate storage path with timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        storage_key = f"funnel/afterwards-video/{timestamp}{ext}"
        bucket = getattr(config, "COACH_FEEDBACK_VIDEO_BUCKET", "coach_feedback_videos")

        # Upload to storage (R2 or Supabase)
        try:
            put_coach_object_bytes(bucket, storage_key, video_bytes, video_file.content_type or "video/mp4")
        except Exception as upload_err:
            logger.error("funnel afterwards-video upload failed: %s", upload_err)
            return jsonify({
                "code": "UPLOAD_FAILED",
                "error": "Failed to upload video to storage.",
            }), 502

        # Generate public URL
        video_url = coach_media_public_url(storage_key)

        # Store URL in funnel_config
        config_row = db.set_funnel_config("afterwards_video_url", video_url)

        logger.info("funnel: uploaded afterwards-video storage_key=%s url=%s", storage_key, video_url)

        return jsonify({
            "status": "ok",
            "video_url": video_url,
            "storage_key": storage_key,
        }), 200

    except Exception as e:
        logger.error("funnel: afterwards-video admin upload failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Upload failed"}), 500


@v2_bp.route("/public/funnel/afterwards-video", methods=["GET"])
def v2_public_funnel_afterwards_video():
    """Public endpoint to fetch the afterwards video URL for Curiosity Gate funnel.

    Returns the configured video URL or null if not set.
    No authentication required.
    """
    try:
        config_row = db.get_funnel_config("afterwards_video_url")
        video_url = (config_row or {}).get("value") if config_row else None

        return jsonify({
            "video_url": video_url,
        }), 200

    except Exception as e:
        logger.error("funnel: afterwards-video public read failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch video"}), 500


@v2_bp.route("/admin/snippets/<snippet_id>/comment", methods=["POST"])
@require_admin
def v2_admin_update_snippet_comment(snippet_id):
    """Admin endpoint to add/update a comment on a charisma snippet.

    Allows admin to label snippets as charisma, stress, or unlabeled, add text feedback,
    and optionally override the pre-generated follow_up_question.

    Body:
      - admin_comment (str, optional)
      - snippet_type  ("charisma"|"stress"|"unlabeled", default "unlabeled")
      - follow_up_question (str, optional) — if omitted AND admin_comment is set,
        the LLM auto-generates one based on snippet_type + transcript + comment.
        Pass null explicitly to clear an existing follow_up_question.

    Returns: { status, snippet, follow_up_question_source }
      follow_up_question_source: "admin_provided" | "llm_generated" | "llm_failed" | "cleared" | "unchanged"
    """
    try:
        body = request.get_json(silent=True) or {}
        admin_comment = (body.get("admin_comment") or "").strip() or None
        snippet_type = (body.get("snippet_type") or "unlabeled").strip().lower()
        # "follow_up_question" key present → honour it (including null to clear)
        # key absent → auto-generate if admin_comment is being set
        follow_up_key_present = "follow_up_question" in body
        follow_up_from_body = body.get("follow_up_question")
        if isinstance(follow_up_from_body, str):
            follow_up_from_body = follow_up_from_body.strip() or None

        if snippet_type not in ("charisma", "stress", "unlabeled"):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "snippet_type must be 'charisma', 'stress', or 'unlabeled'",
            }), 400

        admin_user_id = request.user_id

        updated = db.update_snippet_comment(
            snippet_id=snippet_id,
            admin_comment=admin_comment,
            snippet_type=snippet_type,
            admin_user_id=admin_user_id,
        )

        if not updated:
            return jsonify({
                "code": "NOT_FOUND",
                "error": "Snippet not found",
            }), 404

        # ── follow_up_question resolution ─────────────────────────────────────
        follow_up_source = "unchanged"
        follow_up_question = updated.get("follow_up_question")

        if follow_up_key_present:
            # Admin explicitly provided (or nulled) the follow-up question
            if follow_up_from_body != follow_up_question:
                db.update_snippet_follow_up_question(snippet_id, follow_up_from_body)
                follow_up_question = follow_up_from_body
            follow_up_source = "cleared" if follow_up_from_body is None else "admin_provided"

        elif admin_comment:
            # No explicit override → auto-generate based on snippet type + transcript
            transcript = (
                (updated.get("transcript") or "")
                or (updated.get("transcript_text") or "")
                or (updated.get("transcript_excerpt") or "")
            ).strip()

            if transcript:
                generated = _generate_snippet_follow_up_question(
                    snippet_type=snippet_type,
                    transcript=transcript,
                    admin_comment=admin_comment,
                )
                if generated:
                    db.update_snippet_follow_up_question(snippet_id, generated)
                    follow_up_question = generated
                    follow_up_source = "llm_generated"
                else:
                    follow_up_source = "llm_failed"
            else:
                follow_up_source = "llm_failed"  # no transcript available

        logger.info(
            "admin: updated snippet comment snippet_id=%s admin_user_id=%s type=%s follow_up_source=%s",
            snippet_id, admin_user_id, snippet_type, follow_up_source,
        )

        # Return the snippet with updated follow_up_question reflected
        final_snippet = {**updated, "follow_up_question": follow_up_question}
        return jsonify({
            "status": "ok",
            "snippet": final_snippet,
            "follow_up_question_source": follow_up_source,
        }), 200

    except Exception as e:
        logger.error("admin: update snippet comment failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to update snippet"}), 500


@v2_bp.route("/admin/users/<user_id>/snippets", methods=["GET"])
@require_admin
def v2_admin_get_user_snippets(user_id):
    """Admin endpoint to fetch all snippets for a specific user, paginated."""
    try:
        limit = request.args.get("limit", 100, type=int)
        offset = request.args.get("offset", 0, type=int)

        # Clamp to reasonable ranges
        limit = max(1, min(limit, 500))
        offset = max(0, offset)

        snippets = db.get_snippets_by_user(user_id, limit=limit, offset=offset)

        logger.info(
            "admin: fetched snippets user_id=%s limit=%s offset=%s count=%s",
            user_id, limit, offset, len(snippets),
        )

        return jsonify({
            "status": "ok",
            "snippets": snippets,
            "limit": limit,
            "offset": offset,
            "count": len(snippets),
        }), 200

    except Exception as e:
        logger.error("admin: get user snippets failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch snippets"}), 500


@v2_bp.route("/internal/publish-session-results", methods=["POST"])
@require_admin
def v2_internal_publish_session_results():
    """Admin endpoint to publish (email) results for a completed session.

    Sends "Charisma Snippets Ready" email with CTA to /results page.
    """
    from services.email_service import send_email_resend

    try:
        body = request.get_json(silent=True) or {}
        session_id = (body.get("session_id") or "").strip()

        if not _is_valid_uuid(session_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "session_id must be a valid UUID",
            }), 400

        # Fetch session to get user email
        session = db.v2_get_session_by_id(session_id)
        if not session:
            return jsonify({
                "code": "NOT_FOUND",
                "error": "Session not found",
            }), 404

        # Flip results status so frontend transitions from waiting → results
        try:
            db.v2_update_session_status_unscoped(session_id, "completed")
        except Exception as flip_err:
            logger.warning("publish-results: status flip failed (non-fatal): %s", flip_err)

        user_id = session.get("user_id")
        if not user_id:
            return jsonify({
                "code": "NO_USER",
                "error": "Session has no associated user (not yet claimed)",
            }), 400

        # Fetch user email from Supabase auth
        try:
            import httpx
            auth_headers = {
                "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
                "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
            }
            user_url = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{user_id}"
            resp = httpx.get(user_url, headers=auth_headers, timeout=10)
            if resp.status_code != 200:
                logger.warning("publish-results: failed to fetch user %s from auth", user_id)
                return jsonify({
                    "code": "AUTH_ERROR",
                    "error": "Could not fetch user email",
                }), 502
            user_data = resp.json()
            user_email = user_data.get("email")
        except Exception as fetch_err:
            logger.error("publish-results: fetch user error: %s", fetch_err)
            return jsonify({
                "code": "AUTH_ERROR",
                "error": "Could not fetch user email",
            }), 502

        if not user_email:
            return jsonify({
                "code": "NO_EMAIL",
                "error": "User has no email",
            }), 400

        # Build email content
        frontend_url = getattr(config, "FRONTEND_URL", "https://willonski.com").rstrip("/")
        results_url = f"{frontend_url}/results/{session_id}"
        subject = "Your Charisma Baseline Analysis is ready"
        html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #333; background-color: #f9fafb; margin: 0; padding: 0;">
  <div style="max-width: 600px; margin: 0 auto; background-color: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
    <div style="background: linear-gradient(135deg, #000 0%, #333 100%); color: white; padding: 32px 24px; text-align: center;">
      <h1 style="margin: 0; font-size: 22px; font-weight: 600;">Your Charisma Baseline Analysis is Ready</h1>
    </div>
    <div style="padding: 32px 24px;">
      <p style="font-size: 16px; line-height: 1.6; margin: 16px 0;">Hi,</p>
      <p style="font-size: 16px; line-height: 1.6; margin: 16px 0;">
        Your voice analysis is complete. We've reviewed your recording and added personalized feedback from our coaches.
      </p>
      <div style="text-align: center; margin: 32px 0;">
        <a href="{results_url}" style="display: inline-block; background-color: #000; color: white; padding: 14px 32px; border-radius: 6px; text-decoration: none; font-weight: 600; font-size: 16px;">
          View Your Results
        </a>
      </div>
      <p style="font-size: 14px; color: #6b7280; margin-top: 24px;">
        Each snippet includes detailed feedback to help you understand what made that moment stand out.
      </p>
    </div>
    <div style="background-color: #f9fafb; padding: 24px; text-align: center; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280;">
      <p style="margin: 0;">&copy; {__import__('datetime').datetime.now().year} Willab. All rights reserved.</p>
    </div>
  </div>
</body>
</html>"""

        # Flip the session status so /results page shows snippets
        db.v2_publish_session_results(session_id)

        # Send email via Resend
        try:
            send_email_resend(
                to=user_email,
                subject=subject,
                html=html_body,
            )
        except Exception as email_err:
            logger.error("publish-results: send email failed: %s", email_err)
            # Results are still published even if email delivery fails —
            # the user can reach /results via direct link.
            return jsonify({
                "status": "ok",
                "email_sent_to": None,
                "results_url": results_url,
                "warning": "Results published but email delivery failed",
            }), 200

        logger.info(
            "publish-results: email sent session_id=%s user_id=%s email=%s",
            session_id, user_id, user_email,
        )

        return jsonify({
            "status": "ok",
            "email_sent_to": user_email,
            "results_url": results_url,
        }), 200

    except Exception as e:
        logger.error("publish-results: failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to publish results"}), 500


############################################################################
# Admin: Snippet boundary adjustment (the +/- 2s feature)
############################################################################

@v2_bp.route("/admin/snippets/<snippet_id>/boundaries", methods=["POST"])
@require_admin
def v2_admin_adjust_snippet_boundaries(snippet_id):
    """Update a snippet's start_time/end_time and re-compute metrics for the new slice.

    Input: { start_time: float, end_time: float }
    On update: re-runs audio_metrics.py for the adjusted timeframe,
    updates the snippet's metric columns.
    """
    try:
        body = request.get_json(silent=True) or {}
        start_time = body.get("start_time")
        end_time = body.get("end_time")

        if start_time is None or end_time is None:
            return jsonify({"code": "MISSING_FIELDS", "error": "start_time and end_time are required"}), 400

        start_time = float(start_time)
        end_time = float(end_time)

        if end_time <= start_time:
            return jsonify({"code": "INVALID_BOUNDARIES", "error": "end_time must be greater than start_time"}), 400

        # Update boundaries in DB
        updated = db.update_snippet_boundaries(snippet_id, start_time, end_time)
        if not updated:
            return jsonify({"code": "NOT_FOUND", "error": "Snippet not found"}), 404

        # Re-compute metrics for the new time range
        # Fetch the snippet's audio, decode, slice, and analyze
        recomputed_metrics = None
        try:
            snippet = updated
            audio_path = snippet.get("audio_segment_path", "")
            if audio_path:
                from services.audio_metrics import analyze_audio, decode_audio_to_pcm, SAMPLE_RATE
                from services.coach_video_storage import get_coach_object_bytes
                import numpy as np

                # Try to download audio
                audio_bytes = None
                try:
                    audio_bytes = get_coach_object_bytes("coach_feedback_videos", audio_path)
                except Exception:
                    # Try the bucket name from audio_recordings
                    try:
                        audio_bytes = get_coach_object_bytes("audio_recordings", audio_path)
                    except Exception:
                        pass

                if audio_bytes:
                    # Decode full audio to PCM
                    pcm = decode_audio_to_pcm(audio_bytes)
                    if pcm is not None and len(pcm) > 0:
                        # Slice to the new boundaries
                        start_sample = int(start_time * SAMPLE_RATE)
                        end_sample = int(end_time * SAMPLE_RATE)
                        start_sample = max(0, min(start_sample, len(pcm)))
                        end_sample = max(start_sample, min(end_sample, len(pcm)))
                        sliced = pcm[start_sample:end_sample]

                        if len(sliced) >= SAMPLE_RATE:
                            # Re-encode sliced PCM to bytes for analyze_audio
                            import subprocess
                            sliced_int16 = (sliced * 32768.0).astype(np.int16)
                            raw_bytes = sliced_int16.tobytes()

                            # analyze_audio expects encoded audio, so use raw PCM via a minimal approach
                            # We'll directly call the internal functions instead
                            from services.audio_metrics import (
                                _frame_rms_db, _compute_pause_ms, _compute_dynamic_db,
                                _compute_emphasis_per_min, _compute_energy_ratio, _compute_pitch_center_st,
                                SILENCE_DB_THRESHOLD
                            )
                            duration_sec = len(sliced) / float(SAMPLE_RATE)
                            dbs = _frame_rms_db(sliced)

                            recomputed_metrics = {
                                "wpm": None,  # requires transcript
                                "pause_ms": _compute_pause_ms(dbs),
                                "dynamic_db": _compute_dynamic_db(dbs),
                                "emphasis_per_min": _compute_emphasis_per_min(dbs, duration_sec),
                                "energy_ratio": _compute_energy_ratio(sliced, dbs),
                                "pitch_center_st": None,
                                "pitch_frame_count": 0,
                                "voiced_duration_sec": round(
                                    float(np.sum(dbs >= SILENCE_DB_THRESHOLD)) * 0.02, 1
                                ),
                            }
                            pitch_st, pitch_frames = _compute_pitch_center_st(sliced)
                            recomputed_metrics["pitch_center_st"] = pitch_st
                            recomputed_metrics["pitch_frame_count"] = pitch_frames

                            # Update snippet metric columns
                            db.update_snippet_metrics(
                                snippet_id=snippet_id,
                                wpm=recomputed_metrics.get("wpm"),
                                fillers=None,
                                pause_ms=recomputed_metrics.get("pause_ms"),
                                dynamic_db=recomputed_metrics.get("dynamic_db"),
                                pitch_center=recomputed_metrics.get("pitch_center_st"),
                                energy=recomputed_metrics.get("energy_ratio"),
                                metrics_json=recomputed_metrics,
                            )
        except Exception as metrics_err:
            logger.warning("admin: re-compute metrics after boundary adjust failed: %s", metrics_err, exc_info=True)
            # Non-fatal: boundaries are updated even if metrics re-computation fails

        # Re-fetch the final state
        final_snippet = db.client.table("charisma_snippets").select("*").eq("id", snippet_id).execute()
        final = final_snippet.data[0] if final_snippet.data else updated

        return jsonify({
            "status": "ok",
            "snippet": final,
            "metrics_recomputed": recomputed_metrics is not None,
        }), 200

    except Exception as e:
        logger.error("admin: adjust snippet boundaries failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to adjust boundaries"}), 500


@v2_bp.route("/admin/snippets/<snippet_id>", methods=["PATCH"])
@require_admin
def v2_admin_patch_snippet(snippet_id):
    """Consolidated partial-update endpoint for a single snippet.

    Replaces the need to call /comment, /boundaries, and /skip
    separately when the admin saves a snippet card. Accepts any
    combination of the editable fields and applies each to the row,
    then returns the final state.

    Body (all fields optional — only present keys are applied):
        {
          "start_time":     float,
          "end_time":       float,
          "coach_label":    "charisma" | "stress" | "no_charisma" | null,
                            // alias of snippet_type for the admin-facing
                            // taxonomy; persisted to `snippet_type`
                            // since that's what the user-facing /results
                            // renders from
          "snippet_type":   "charisma" | "stress" | "unlabeled",
                            // direct passthrough — same effect as
                            // coach_label, kept for client compatibility
          "admin_comment":  string | null,
          "status":         "draft" | "skipped" | "published"
                            // "skipped" → is_skipped = true
                            // "draft"   → is_skipped = false
                            // "published" rejected (session-level
                            // operation — use POST /admin/sessions/<id>/publish)
        }

    Responses:
        200 { status: "ok", snippet: {...full row...} }
        400 INVALID_INPUT, INVALID_BOUNDARIES
        404 NOT_FOUND
        500 V2_ERROR
    """
    try:
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({
                "code": "INVALID_PAYLOAD",
                "error": "Request body must be a JSON object.",
            }), 400

        snippet = None  # latest persisted state — keeps the final return tidy

        # ── 1. Boundaries ─────────────────────────────────────────────
        # Only update if BOTH start_time and end_time are present and
        # form a valid window. Partial { start_time only } is rejected
        # because the boundary update is atomic in the DB helper.
        has_start = "start_time" in body and body["start_time"] is not None
        has_end = "end_time" in body and body["end_time"] is not None
        if has_start or has_end:
            if not (has_start and has_end):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "start_time and end_time must be provided together.",
                }), 400
            try:
                start_time = float(body["start_time"])
                end_time = float(body["end_time"])
            except (TypeError, ValueError):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "start_time and end_time must be numeric.",
                }), 400
            if end_time <= start_time:
                return jsonify({
                    "code": "INVALID_BOUNDARIES",
                    "error": "end_time must be greater than start_time.",
                }), 400
            snippet = db.update_snippet_boundaries(snippet_id, start_time, end_time)
            if not snippet:
                return jsonify({"code": "NOT_FOUND", "error": "Snippet not found."}), 404

        # ── 2. Label + comment (TRUE partial update) ─────────────────
        # Only touch columns that the admin explicitly named in the body.
        # The destructive default to "unlabeled" was wrong: if the admin
        # is just editing the comment text on a snippet they already
        # labelled "charisma", the previous label MUST stay.
        #
        # `coach_label` is the admin-friendly alias of `snippet_type` —
        # both keys, if present, route to the same DB column.
        patch: dict = {}

        label_provided = "snippet_type" in body or "coach_label" in body
        if label_provided:
            raw_label = (
                body["snippet_type"]
                if "snippet_type" in body
                else body["coach_label"]
            )
            if raw_label is None:
                # Explicit null clears the label
                patch["snippet_type"] = None
            else:
                label = str(raw_label).strip().lower()
                # Legacy "no_charisma" → "unlabeled" for the newer taxonomy.
                if label == "no_charisma":
                    label = "unlabeled"
                if label not in ("charisma", "stress", "unlabeled"):
                    return jsonify({
                        "code": "INVALID_INPUT",
                        "error": (
                            "coach_label/snippet_type must be 'charisma', "
                            "'stress', 'unlabeled', or 'no_charisma'."
                        ),
                    }), 400
                patch["snippet_type"] = label

        if "admin_comment" in body:
            raw_comment = body["admin_comment"]
            if raw_comment is None:
                patch["admin_comment"] = None
            elif isinstance(raw_comment, str):
                patch["admin_comment"] = raw_comment.strip() or None
            else:
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "admin_comment must be a string or null.",
                }), 400

        if patch:
            # Stamp the admin who made the change whenever either column
            # is touched, so the audit trail reflects the last editor
            # even on a comment-only update.
            patch["admin_user_id"] = request.user_id
            try:
                result = (
                    db.client.table("charisma_snippets")
                    .update(patch)
                    .eq("id", snippet_id)
                    .execute()
                )
                snippet = result.data[0] if result.data else None
            except Exception as upd_err:
                logger.error("admin: snippet partial update failed: %s", upd_err, exc_info=True)
                return jsonify({
                    "code": "V2_ERROR",
                    "error": "Failed to update snippet.",
                }), 500
            if not snippet:
                return jsonify({"code": "NOT_FOUND", "error": "Snippet not found."}), 404

        # ── 3. Status (skipped / draft / published) ───────────────────
        # The user-facing surface keys off `is_skipped` for visibility
        # gating, so map admin-friendly status strings here.
        if "status" in body and body["status"] is not None:
            status = str(body["status"]).strip().lower()
            if status == "skipped":
                snippet = db.skip_snippet(snippet_id, True)
            elif status == "draft":
                snippet = db.skip_snippet(snippet_id, False)
            elif status == "published":
                # Per-snippet "publish" doesn't exist — publication is a
                # session-level operation that flips results_published_at.
                # Reject loudly so callers don't think this did anything.
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": (
                        "Snippet status='published' is not supported. "
                        "Use POST /v2/admin/sessions/<id>/publish to "
                        "publish a whole session."
                    ),
                }), 400
            else:
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "status must be 'draft' or 'skipped'.",
                }), 400
            if not snippet:
                return jsonify({"code": "NOT_FOUND", "error": "Snippet not found."}), 404

        # If no editable keys were present, the caller hit this endpoint
        # for nothing — surface it rather than silently 200ing.
        if snippet is None:
            return jsonify({
                "code": "NO_FIELDS_TO_UPDATE",
                "error": (
                    "Request body had no recognised fields. Provide one or "
                    "more of: start_time+end_time, coach_label/snippet_type, "
                    "admin_comment, status."
                ),
            }), 400

        return jsonify({"status": "ok", "snippet": snippet}), 200

    except Exception as e:
        logger.error("admin: patch snippet failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to update snippet"}), 500


@v2_bp.route("/admin/sessions/<session_id>/publish", methods=["POST"])
@require_admin
def v2_admin_publish_session(session_id):
    """Publish results for a session — flips visibility for the user.

    Mirrors the existing /v2/internal/publish-session-results endpoint
    but takes session_id as a URL path param instead of a body field,
    so it slots cleanly under the /admin/sessions/* namespace the
    admin UI consumes.

    Side effects:
      * Sets results_published_at = NOW() on the session
      * Flips status to 'completed'
      * Sends the "Charisma Snippets Ready" email via Resend
        (same as the internal endpoint — failure is non-fatal so the
        publish itself still goes through)

    Snippets with is_skipped = true stay hidden from the user-facing
    /results page; only non-skipped rows are returned by
    v2_get_results_snippets_for_session.

    Responses:
        200 { status: "ok", session_id, results_published_at, email_sent }
        400 INVALID_INPUT
        404 SESSION_NOT_FOUND
        500 V2_ERROR
    """
    try:
        if not _is_valid_uuid(session_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "session_id must be a valid UUID",
            }), 400

        session = db.v2_get_session_by_id(session_id)
        if not session:
            return jsonify({
                "code": "SESSION_NOT_FOUND",
                "error": "Session not found",
            }), 404

        # 1. Stamp results_published_at
        published = db.v2_publish_session_results(session_id)
        if not published:
            return jsonify({
                "code": "V2_ERROR",
                "error": "Failed to publish session",
            }), 500

        # 2. Flip session status so the user-facing routing recognises
        #    the completed state immediately.
        try:
            db.v2_update_session_status_unscoped(session_id, "completed")
        except Exception as flip_err:
            logger.warning("publish: status flip failed (non-fatal): %s", flip_err)

        # 3. Best-effort email notify. Reuses the same internal helper
        #    so the email template and Resend wiring stay in one place.
        email_sent = False
        try:
            email_sent = _send_results_ready_email(session_id, session)
        except Exception as mail_err:
            logger.warning("publish: email failed (non-fatal): %s", mail_err)

        return jsonify({
            "status": "ok",
            "session_id": session_id,
            "results_published_at": published.get("results_published_at"),
            "email_sent": email_sent,
        }), 200

    except Exception as e:
        logger.error("admin: publish session failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to publish session"}), 500


def _send_results_ready_email(session_id: str, session: dict) -> bool:
    """Send the "Results Ready" email. Returns True iff the email was
    enqueued / sent successfully. Non-fatal: callers decide whether a
    failure here should affect the overall response.

    Centralised so /admin/sessions/<id>/publish and the legacy
    /internal/publish-session-results don't drift apart.
    """
    from services.email_service import send_email_resend
    import httpx

    user_id = session.get("user_id")
    if not user_id:
        logger.warning("publish: session has no user_id, skipping email")
        return False

    auth_headers = {
        "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
        "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
    }
    user_url = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{user_id}"
    resp = httpx.get(user_url, headers=auth_headers, timeout=10)
    if resp.status_code != 200:
        logger.warning("publish: failed to fetch user %s (status %d)", user_id, resp.status_code)
        return False
    user_email = (resp.json() or {}).get("email")
    if not user_email:
        return False

    app_base = (
        getattr(config, "APP_PUBLIC_BASE_URL", None)
        or os.environ.get("APP_PUBLIC_BASE_URL")
        or "https://www.willonski.com"
    ).rstrip("/")
    results_url = f"{app_base}/results/{session_id}"

    send_email_resend(
        to=user_email,
        subject="Your Charisma Snippets Are Ready",
        html=(
            f'<p>Hi,</p>'
            f'<p>Your voice analysis is complete. We extracted your best moments '
            f'and added detailed feedback.</p>'
            f'<p><a href="{results_url}" '
            f'style="display:inline-block;padding:12px 20px;background:#f97316;'
            f'color:#fff;text-decoration:none;border-radius:8px;font-weight:600;">'
            f'View your Charisma Snippets</a></p>'
            f'<p style="color:#666;font-size:14px;">— Team Willab</p>'
        ),
    )
    return True


@v2_bp.route("/admin/snippets/<snippet_id>/skip", methods=["POST"])
@require_admin
def v2_admin_skip_snippet(snippet_id):
    """Mark a snippet as skipped (hidden from user results).

    Input: { is_skipped: bool }
    """
    try:
        body = request.get_json(silent=True) or {}
        is_skipped = bool(body.get("is_skipped", True))

        updated = db.skip_snippet(snippet_id, is_skipped)
        if not updated:
            return jsonify({"code": "NOT_FOUND", "error": "Snippet not found"}), 404

        return jsonify({"status": "ok", "snippet": updated}), 200

    except Exception as e:
        logger.error("admin: skip snippet failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to skip snippet"}), 500


############################################################################
# Admin: User settings (LLM instructions)
############################################################################

@v2_bp.route("/admin/users/<user_id>/settings", methods=["GET"])
@require_admin
def v2_admin_get_user_settings(user_id):
    """Get user's custom LLM instructions and settings."""
    try:
        settings = db.get_user_settings(user_id)
        return jsonify({
            "status": "ok",
            "settings": settings or {"user_id": user_id, "custom_llm_instructions": None},
        }), 200
    except Exception as e:
        logger.error("admin: get user settings failed: %s", e, exc_info=True)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch settings"}), 500


@v2_bp.route("/admin/users/<user_id>/settings", methods=["POST"])
@require_admin
def v2_admin_update_user_settings(user_id):
    """Update user's custom LLM instructions.

    Input: { custom_llm_instructions: string | null }
    """
    try:
        body = request.get_json(silent=True) or {}
        instructions = body.get("custom_llm_instructions")

        result = db.upsert_user_settings(user_id, instructions)
        return jsonify({"status": "ok", "settings": result}), 200

    except Exception as e:
        logger.error("admin: update user settings failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to update settings"}), 500


############################################################################
# Admin: User interview timeline
############################################################################

@v2_bp.route("/admin/users/<user_id>/timeline", methods=["GET"])
@require_admin
def v2_admin_get_user_timeline(user_id):
    """Fetch a user's complete interview timeline (chronological Q&A thread).

    Returns an array sorted by time: [Bot Question] → [User Audio] → [Snippet Metrics].
    Optional query param: ?session_id=UUID to filter to one session.
    """
    try:
        session_id = request.args.get("session_id") or None

        # Get all snippets in order
        snippets = db.get_user_interview_timeline(user_id, session_id=session_id)

        # Get session-level data if specific session requested
        session_data = None
        if session_id:
            session_data = db.get_session_with_global_metrics(session_id)

        # Build timeline: each snippet becomes a turn with question + answer + metrics
        timeline = []
        for snippet in snippets:
            turn = {
                "turn_number": snippet.get("turn_number"),
                "question": {
                    "text": snippet.get("question_text"),
                    "tone": snippet.get("question_tone"),
                },
                "answer": {
                    "snippet_id": snippet.get("id"),
                    "audio_url": snippet.get("audio_segment_path"),
                    "duration_ms": snippet.get("duration_ms"),
                    # start_time / end_time are derived at the API
                    # boundary — they are NOT persisted (phantom
                    # columns; see services/db.py::update_snippet_
                    # boundaries). The frontend may consume seconds.
                    "start_time": _snippet_start_time(snippet),
                    "end_time": _snippet_end_time(snippet),
                    "is_skipped": snippet.get("is_skipped", False),
                    # Whisper transcription of the user's spoken answer.
                    # The /admin timeline cards render this on each turn;
                    # without it they fall back to a placeholder.
                    "transcript": snippet.get("transcript"),
                },
                "metrics": {
                    "wpm": snippet.get("wpm"),
                    "fillers": snippet.get("fillers"),
                    "pause_ms": snippet.get("pause_ms"),
                    "dynamic_db": snippet.get("dynamic_db"),
                    "pitch_center": snippet.get("pitch_center"),
                    "energy": snippet.get("energy"),
                },
                "admin": {
                    "comment": snippet.get("admin_comment"),
                    "snippet_type": snippet.get("snippet_type"),
                },
                "created_at": snippet.get("created_at"),
            }
            timeline.append(turn)

        return jsonify({
            "status": "ok",
            "user_id": user_id,
            "session": session_data,
            "timeline": timeline,
            "total_turns": len(timeline),
        }), 200

    except Exception as e:
        logger.error("admin: get user timeline failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch timeline"}), 500


@v2_bp.route("/admin/turns/<turn_id>/question", methods=["PATCH"])
@require_admin
def v2_admin_patch_turn_question(turn_id):
    """Human-in-the-Loop: edit the bot question text for a single interview turn.

    A "turn" is a charisma_snippet row — its `question_text` field stores the
    AI question that was shown to the user before they recorded that answer.
    Editing it retunes the transcript display and improves LLM context on
    subsequent sessions (because `previous_turns[].question` is passed to GPT).

    Path param: turn_id — the UUID primary key of the charisma_snippets row.
    Body: { "text": "corrected question text" }
    Returns: { status, turn_id, turn } — turn shaped like the timeline object.
    """
    try:
        if not _is_valid_uuid(turn_id):
            return jsonify({"code": "INVALID_INPUT", "error": "turn_id must be a valid UUID"}), 400

        body = request.get_json(silent=True) or {}
        new_text = (body.get("text") or "").strip()
        if not new_text:
            return jsonify({"code": "INVALID_INPUT", "error": "text is required and must not be empty"}), 400
        if len(new_text) > 5000:
            return jsonify({"code": "INVALID_INPUT", "error": "text must be at most 5 000 characters"}), 400

        updated = db.update_turn_question_text(turn_id, new_text)
        if updated is None:
            return jsonify({"code": "NOT_FOUND", "error": "Turn not found"}), 404

        # Shape the response like the timeline endpoint so the admin UI can
        # drop the updated object directly into its local state.
        turn = {
            "turn_number": updated.get("turn_number"),
            "question": {
                "text": updated.get("question_text"),
                "tone": updated.get("question_tone"),
            },
            "answer": {
                "snippet_id": updated.get("id"),
                "audio_url": updated.get("audio_segment_path"),
                "duration_ms": updated.get("duration_ms"),
                # Derived seconds (phantom columns — see
                # services/db.py::update_snippet_boundaries).
                "start_time": _snippet_start_time(updated),
                "end_time": _snippet_end_time(updated),
                "is_skipped": updated.get("is_skipped", False),
            },
            "metrics": {
                "wpm": updated.get("wpm"),
                "fillers": updated.get("fillers"),
                "pause_ms": updated.get("pause_ms"),
                "dynamic_db": updated.get("dynamic_db"),
                "pitch_center": updated.get("pitch_center"),
                "energy": updated.get("energy"),
            },
            "admin": {
                "comment": updated.get("admin_comment"),
                "snippet_type": updated.get("snippet_type"),
                "follow_up_question": updated.get("follow_up_question"),
            },
            "created_at": updated.get("created_at"),
            "updated_at": updated.get("updated_at"),
        }

        logger.info("admin HITL: edited question text for turn_id=%s", turn_id)
        return jsonify({
            "status": "ok",
            "turn_id": turn_id,
            "turn": turn,
        }), 200

    except Exception as e:
        logger.error("admin: patch turn question failed turn_id=%s: %s", turn_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to update turn"}), 500


############################################################################
# Admin: Compute global session metrics + AI alignment
############################################################################

def _snippet_start_time(snippet: dict) -> float | None:
    """API-boundary derivation of seconds-float start time.

    The seconds-float pair (start_time / end_time) referenced through
    older API contracts is NOT a persisted schema column — every
    attempt to write it raises PGRST204 (see
    services/db.py::update_snippet_boundaries). All snippets store
    their bounds in the canonical millisecond-integer pair
    (start_offset_ms / duration_ms). We synthesise the seconds-float
    values at response time so any frontend that still consumes the
    old contract keeps working without a stale write.
    """
    ms = snippet.get("start_offset_ms")
    return None if ms is None else round(float(ms) / 1000.0, 3)


def _snippet_end_time(snippet: dict) -> float | None:
    """API-boundary derivation of seconds-float end time. See
    :func:`_snippet_start_time` for why this is computed rather than
    read from the row.
    """
    start_ms = snippet.get("start_offset_ms")
    dur_ms = snippet.get("duration_ms")
    if start_ms is None or dur_ms is None:
        return None
    return round((float(start_ms) + float(dur_ms)) / 1000.0, 3)


def _resolve_turn_audio_url(snippet: dict) -> str | None:
    """Playback URL for a *turn* row (Chat Transcript / Conversation Timeline).

    Distinct from ``_resolve_snippet_audio_url``: a turn is the ORIGINAL
    per-turn recording, not a slice of the concat'd session file. The
    chat-history bubble plays it through a plain ``<audio>`` element with
    no offset clamping, so we must hand back a URL that resolves to a
    standalone-playable file — i.e. the per-turn ``audio_segment_path``
    (the R2 public URL written at upload time), NOT the concat'd
    storage_path the snippet panel uses.

    Fallback chain:
      1. audio_segment_path (set at turn upload, never NULL'd by finalize)
      2. storage_path signed via audio bucket — only when audio_segment_path
         is missing for legacy / cold-start rows
      3. None
    """
    seg = (snippet.get("audio_segment_path") or "").strip()
    if seg:
        return seg
    storage = (snippet.get("storage_path") or "").strip()
    if storage and not storage.startswith("charisma_snippets/"):
        try:
            from services.audio_storage import audio_public_url
            url = audio_public_url(storage)
            if url:
                return url
        except Exception as e:
            logger.warning(
                "turn audio URL: R2 build failed for %s: %s", storage, e
            )
    if storage:
        try:
            return db.create_signed_url(
                config.AUDIO_BUCKET_NAME, storage, config.SIGNED_URL_EXPIRY_SECONDS
            )
        except Exception:
            return None
    return None


def _resolve_snippet_audio_url(snippet: dict) -> str | None:
    """Pick a playable audio URL from whichever column the writer used.

    The four snippet states we have to play through one <audio> element:
      - Path A pre-finalize: audio_segment_path = R2 public URL for the
        per-turn .webm, storage_path NULL.
      - Path A post-finalize: storage_path = bucket-relative key of the
        concat'd session full.webm (Supabase Storage). audio_segment_path
        is left intact (historical record + idempotent re-finalize), but
        storage_path is what start_offset_ms / duration_ms are RELATIVE TO,
        so it must win.
      - Path B (extract_recording_snippets): audio_segment_path = full URL,
        storage_path NULL.
      - Path C (charisma_snippet_service) and student uploads: storage_path
        set, audio_segment_path NULL.

    Precedence is therefore: storage_path → audio_segment_path → None.
    Returning None means there's truly nothing playable. Keeping
    audio_segment_path as the fallback (rather than the primary) is what
    makes the per-turn → canonical-recording migration safe — the moment
    finalize_session_recording populates storage_path, the snippet flips
    from playing its per-turn file to playing a slice of the concat'd
    session audio, no DB cleanup required.
    """
    storage = (snippet.get("storage_path") or "").strip()
    if storage:
        # Two classes of storage_path coexist:
        #   - "session_recordings/<sid>/full.webm" and
        #     "guest_funnel/<sid>/turn_N.webm" — interview audio in R2,
        #     served via the audio bucket's public base URL.
        #   - "charisma_snippets/<uuid>" — student-uploaded clips in
        #     Supabase Storage, served via signed URLs.
        # Disambiguate by prefix. Anything that isn't a known
        # Supabase-only prefix is assumed to be audio-bucket content.
        is_supabase_prefix = storage.startswith("charisma_snippets/")
        if not is_supabase_prefix:
            try:
                from services.audio_storage import audio_public_url
                url = audio_public_url(storage)
                if url:
                    return url
            except Exception as e:
                logger.warning(
                    "snippet audio URL: R2 audio URL build failed for %s: %s",
                    storage, e,
                )
            # R2_AUDIO_PUBLIC_BASE_URL not set (local dev) — fall through
            # to the Supabase signed-URL path so dev still works.
        try:
            return db.create_signed_url(
                config.AUDIO_BUCKET_NAME, storage, config.SIGNED_URL_EXPIRY_SECONDS
            )
        except Exception as e:
            logger.warning(
                "snippet audio URL: signed url failed for %s: %s — falling back",
                storage, e,
            )
            # fall through to audio_segment_path
    seg = (snippet.get("audio_segment_path") or "").strip()
    if seg:
        return seg
    return None


@v2_bp.route("/admin/sessions/<session_id>", methods=["GET"])
@require_admin
def v2_admin_get_session(session_id):
    """Comprehensive admin payload for one session.

    Eager-loads everything the admin user-detail view needs:
      - the session row + global metrics
      - the chronological conversation turns (AI question / user answer
        pairs) flattened into a `[{role, content, ...}, ...]` array
      - the full list of charisma_snippets associated with the session
        (both interview turn rows and any extraction-only snippets) so
        the snippet panel and the conversation transcript share one
        source of truth

    The shape is deliberately denormalised — readers don't need to do a
    second round-trip per turn or per snippet to render the page.

    Auth: admin only (via @require_admin).

    Response (200):
        {
            "id":             str,
            "user_id":        str,
            "status":         str | null,
            "results_published_at": str | null,
            "created_at":     str | null,
            "global_metrics": { wpm, fillers, pause_ms, dynamic_db,
                                pitch_center, energy, kpi_score,
                                ai_score, ai_summary },
            "turns": [
                { "role": "ai",   "content": str, "tone": str | null,
                  "turn_number": int },
                { "role": "user", "content": str, "audio_url": str | null,
                  "duration_ms": int | null, "snippet_id": str,
                  "turn_number": int, "metrics": {...} },
                ...
            ],
            "snippets": [
                { "id": str, "type": str | null, "audio_url": str | null,
                  "transcript": str | null, "duration_ms": int | null,
                  "admin_comment": str | null, "is_skipped": bool,
                  "turn_number": int | null, "coach_label": str | null },
                ...
            ],
            "total_turns": int,
            "total_snippets": int
        }
    """
    try:
        session = db.get_session_with_global_metrics(session_id)
        if not session:
            return jsonify({
                "code": "SESSION_NOT_FOUND",
                "error": "Session not found.",
            }), 404

        user_id = session.get("user_id")

        # One DB read for every snippet on this session — interview turns
        # AND extracted moments live in the same charisma_snippets table,
        # distinguished by whether `turn_number` is populated.
        all_snippets = db.get_snippets_by_session(session_id) or []

        # ── Turns: flatten interview rows into AI/user message pairs ────
        # Interview rows are the ones with turn_number set. We sort by
        # turn_number then start_offset_ms so within-turn ordering stays
        # stable even if turn_number duplicates appear.
        interview_rows = [s for s in all_snippets if s.get("turn_number") is not None]
        interview_rows.sort(
            key=lambda s: (
                s.get("turn_number") or 0,
                s.get("start_offset_ms") or 0,
            )
        )

        turns: list[dict] = []
        for s in interview_rows:
            q_text = (s.get("question_text") or "").strip()
            if q_text:
                turns.append({
                    "role": "ai",
                    "content": q_text,
                    "tone": s.get("question_tone"),
                    "turn_number": s.get("turn_number"),
                })
            turns.append({
                "role": "user",
                "content": (s.get("transcript") or "").strip(),
                # Per-turn ORIGINAL audio URL — plays standalone in the
                # chat bubble. Distinct from the snippet panel below
                # which gets concat'd-file slice URLs.
                "audio_url": _resolve_turn_audio_url(s),
                "duration_ms": s.get("duration_ms"),
                # Offset within the audio_url, for chat bubbles that need
                # to clamp playback. ZERO when audio_url points at the
                # per-turn original file (the common case); the row's
                # actual start_offset_ms (set by finalize) when audio_url
                # falls through to the concat'd full.webm. Frontend uses
                # (start_offset_ms, duration_ms) to seek+stop on play.
                "start_offset_ms": (
                    0
                    if (s.get("audio_segment_path") or "").strip()
                    else int(s.get("start_offset_ms") or 0)
                ),
                "snippet_id": str(s.get("id")) if s.get("id") else None,
                "turn_number": s.get("turn_number"),
                "metrics": {
                    "wpm": s.get("wpm"),
                    "fillers": s.get("fillers"),
                    "pause_ms": s.get("pause_ms"),
                    "dynamic_db": s.get("dynamic_db"),
                    "pitch_center": s.get("pitch_center"),
                    "energy": s.get("energy"),
                },
            })

        # ── Snippets: ONLY extracted highlight snippets ──────────────────
        # The snippet panel in the admin UI is a highlight reel — moments
        # of interest within the full session recording, NOT one row per
        # turn. Turn rows belong in the Chat Transcript / Conversation
        # Timeline (served via the `turns` array above).
        #
        # Distinction: turn rows have `turn_number IS NOT NULL` (set at
        # upload time by /v2/public/interview/upload-answer). Extracted
        # snippets have `turn_number IS NULL` and `source_type` populated
        # (typically "auto_extracted" or "student").
        extracted_only = [s for s in all_snippets if s.get("turn_number") is None]
        snippets = [
            {
                "id": str(s.get("id")) if s.get("id") else None,
                "session_id": str(s.get("session_id")) if s.get("session_id") else str(session_id),
                "user_id": str(s.get("user_id")) if s.get("user_id") else None,
                "recording_id": str(s.get("recording_id")) if s.get("recording_id") else None,
                "type": s.get("snippet_type") or s.get("coach_label"),
                "snippet_type": s.get("snippet_type"),
                # Provenance tag — "auto_extracted" for highlights from
                # services.snippet_truncation, "student" for user-uploaded
                # clips, NULL for legacy path-B rows. Frontend filters
                # the snippet panel on this so legacy noise stays hidden.
                "source_type": s.get("source_type"),
                "coach_label": s.get("coach_label"),
                "audio_url": _resolve_snippet_audio_url(s),
                "audio_segment_path": s.get("audio_segment_path"),
                "storage_path": s.get("storage_path"),
                "transcript": s.get("transcript"),
                "duration_ms": s.get("duration_ms"),
                "start_offset_ms": s.get("start_offset_ms"),
                "admin_comment": s.get("admin_comment"),
                "is_skipped": bool(s.get("is_skipped", False)),
                "turn_number": s.get("turn_number"),
                # Derived at API boundary — these columns don't exist
                # in the schema. See services/db.py::update_snippet_
                # boundaries for the canonical model rationale.
                "start_time": _snippet_start_time(s),
                "end_time": _snippet_end_time(s),
                # Coaching-outcome blob written by
                # services.coaching_outcomes.evaluate_and_record_followup_
                # outcome after the user answered turn 1 of a contextual
                # chat that this snippet seeded (via /chat?sourceSnippet=
                # <id>). Surfaced here so the admin page can render the
                # score + the user's actual answer next to the comment
                # the admin originally wrote — closing the feedback
                # loop. NULL until the user has clicked the CTA AND
                # answered the first question.
                "follow_up_outcome": s.get("follow_up_outcome"),
                "created_at": s.get("created_at"),
            }
            for s in extracted_only
        ]

        global_metrics = {
            "wpm": session.get("global_wpm"),
            "fillers": session.get("global_fillers"),
            "pause_ms": session.get("global_pause_ms"),
            "dynamic_db": session.get("global_dynamic_db"),
            "pitch_center": session.get("global_pitch_center"),
            "energy": session.get("global_energy"),
            "kpi_score": session.get("kpi_score"),
            "ai_score": session.get("ai_task_alignment_score"),
            "ai_summary": session.get("ai_task_alignment_comment"),
        }

        return jsonify({
            "id": str(session_id),
            "user_id": str(user_id) if user_id else None,
            "status": session.get("status"),
            "results_published_at": session.get("results_published_at"),
            "created_at": session.get("created_at"),
            "global_metrics": global_metrics,
            "turns": turns,
            "snippets": snippets,
            "total_turns": len(turns),
            "total_snippets": len(snippets),
        }), 200

    except Exception as e:
        logger.error("admin/sessions/<id> GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch session"}), 500


def _compute_session_global_metrics(session_id: str) -> dict | None:
    """Aggregate snippet-level metrics into session-level averages and persist.

    Extracted from v2_admin_compute_session_metrics so it can be called
    from the auto-finalize background thread (no LLM call, no HTTP shell).
    Returns the computed metrics dict on success, or None when the session
    has no active snippets (caller decides whether that's an error).

    The aggregation rule is averages for rates (wpm, pause_ms, dynamic_db,
    pitch_center, energy) and sum for counts (fillers). Falls back to the
    JSONB ``metrics`` column when individual metric columns are NULL —
    older snippet rows wrote metrics into the blob before the dedicated
    columns existed.
    """
    snippets = db.get_snippets_by_session(session_id)
    active_snippets = [s for s in snippets if not s.get("is_skipped", False)]
    if not active_snippets:
        return None

    wpms = [s.get("wpm") for s in active_snippets if s.get("wpm") is not None]
    fillers_list = [s.get("fillers") for s in active_snippets if s.get("fillers") is not None]
    pauses = [s.get("pause_ms") for s in active_snippets if s.get("pause_ms") is not None]
    dynamics = [s.get("dynamic_db") for s in active_snippets if s.get("dynamic_db") is not None]
    pitches = [s.get("pitch_center") for s in active_snippets if s.get("pitch_center") is not None]
    energies = [s.get("energy") for s in active_snippets if s.get("energy") is not None]

    # JSONB ``metrics`` fallback for any field whose dedicated column is empty
    if not pauses:
        pauses = [s["metrics"]["pause_ms"] for s in active_snippets
                  if s.get("metrics") and s["metrics"].get("pause_ms") is not None]
    if not dynamics:
        dynamics = [s["metrics"]["dynamic_db"] for s in active_snippets
                    if s.get("metrics") and s["metrics"].get("dynamic_db") is not None]
    if not pitches:
        pitches = [s["metrics"]["pitch_center_st"] for s in active_snippets
                   if s.get("metrics") and s["metrics"].get("pitch_center_st") is not None]
    if not energies:
        energies = [s["metrics"]["energy_ratio"] for s in active_snippets
                    if s.get("metrics") and s["metrics"].get("energy_ratio") is not None]

    global_wpm = round(sum(wpms) / len(wpms), 1) if wpms else None
    global_fillers = sum(fillers_list) if fillers_list else None
    global_pause_ms = round(sum(pauses) / len(pauses), 1) if pauses else None
    global_dynamic_db = round(sum(dynamics) / len(dynamics), 1) if dynamics else None
    global_pitch_center = round(sum(pitches) / len(pitches), 1) if pitches else None
    global_energy = round(sum(energies) / len(energies), 3) if energies else None

    # KPI from the existing performance formula
    kpi_score = None
    kpi_debug = None
    try:
        from services.metrics_v2 import compute_recording_performance_score
        kpi_result = compute_recording_performance_score(
            center_hold_ratio=global_energy,
            filler_count=global_fillers or 0,
            wpm=global_wpm or 140.0,
        )
        kpi_score = round(kpi_result["score_01"] * 100, 1)
        kpi_debug = kpi_result
    except Exception as kpi_err:
        logger.warning("session metrics: KPI score compute failed: %s", kpi_err)

    db.update_session_global_metrics(
        session_id=session_id,
        global_wpm=global_wpm,
        global_fillers=global_fillers,
        global_pause_ms=global_pause_ms,
        global_dynamic_db=global_dynamic_db,
        global_pitch_center=global_pitch_center,
        global_energy=global_energy,
        kpi_score=kpi_score,
    )

    return {
        "wpm": global_wpm,
        "fillers": global_fillers,
        "pause_ms": global_pause_ms,
        "dynamic_db": global_dynamic_db,
        "pitch_center": global_pitch_center,
        "energy": global_energy,
        "kpi_score": kpi_score,
        "kpi_debug": kpi_debug,
        "snippets_analyzed": len(active_snippets),
        "active_snippets": active_snippets,
    }


# ── Per-session debounce + lock state (module-local) ────────────────────────
#
# The previous design spawned a daemon thread on every turn upload that
# immediately ran concat + extract. With turns landing seconds apart, two
# threads frequently overlapped — and because finalize publishes derived
# state (full.webm in R2, snippet anchor rewrites in DB) without any
# notion of "session version", the LATER-finishing thread could regress
# the canonical recording back to an earlier turn count. That's the bug
# behind both:
#   1. Full Recording showing only turn-1 length (3 s instead of 48 s)
#   2. Duplicate auto-extracted snippets cut from the truncated file
#
# Two layers of protection:
#   - Debounce: every upload reschedules. The actual work only runs after
#     FINALIZE_DEBOUNCE_SEC of upload silence — naturally collapsing a
#     burst of N turns into a single finalize run against the latest
#     state. Catches the common case (rapid sequential turns).
#   - In-process per-session lock: defensive — if the debounce doesn't
#     catch a race (e.g. an upload arrives exactly at the debounce
#     deadline of another), the lock serializes runs so the later one
#     waits for the earlier to finish, then runs against fresh data.
#
# Both are per-worker. With 2 gunicorn workers the cross-worker race
# window shrinks but isn't fully closed; if we still see it, the next
# step is a Postgres advisory lock on hashtext(session_id). Keeping that
# in reserve.
_finalize_state_lock = threading.Lock()
_finalize_timers: dict[str, threading.Timer] = {}
_finalize_locks: dict[str, threading.Lock] = {}
FINALIZE_DEBOUNCE_SEC = 2.0


def _get_session_finalize_lock(session_id: str) -> threading.Lock:
    """Lazily allocate one Lock per session_id. Holding the meta-lock
    while we create the per-session lock guarantees the two workers
    inside the same process never end up with two different locks."""
    with _finalize_state_lock:
        lock = _finalize_locks.get(session_id)
        if lock is None:
            lock = threading.Lock()
            _finalize_locks[session_id] = lock
        return lock


def _run_session_finalize_in_bg(session_id: str) -> None:
    """Schedule a debounced finalize run for ``session_id``.

    Called from the interview turn upload endpoint after every successful
    turn. Each call cancels any pending timer for the same session and
    schedules a fresh one. Only the timer that survives a full
    ``FINALIZE_DEBOUNCE_SEC`` window of silence actually fires the real
    finalize work — so a burst of N turn uploads produces exactly one
    finalize run against the final session state.

    Returns immediately. The upload response is never blocked by ffmpeg,
    storage I/O, or metric aggregation.
    """
    with _finalize_state_lock:
        existing_timer = _finalize_timers.pop(session_id, None)
        if existing_timer is not None:
            existing_timer.cancel()

        timer = threading.Timer(
            FINALIZE_DEBOUNCE_SEC,
            _do_session_finalize,
            args=(session_id,),
        )
        timer.daemon = True
        timer.name = f"finalize-debounce-{session_id[:8]}"
        _finalize_timers[session_id] = timer
        timer.start()


def _do_session_finalize(session_id: str) -> None:
    """Run the actual concat + metrics + extract pipeline under the
    per-session lock. Fired by the debounce timer in _run_session_
    finalize_in_bg, NOT by every upload.

    Every log line carries the same ``run`` UUID so the timeline of any
    one finalize is grep-able. The run also records:
      - start / end timestamps
      - per-step turn counts and durations
      - whether the lock had to wait

    If another worker is already finalizing this session, we wait
    behind it rather than racing — by the time we get the lock, the
    DB and R2 reflect the prior worker's writes, so our re-read will
    see the latest turns.
    """
    run_id = uuid.uuid4().hex[:8]
    lock = _get_session_finalize_lock(session_id)
    started = time.monotonic()

    waited_for_lock = not lock.acquire(blocking=False)
    if waited_for_lock:
        # Another finalize for this session is in-flight inside this
        # worker process. Wait for it — when we get the lock the prior
        # writer's state is visible, so our re-read covers any turn that
        # landed since we were scheduled.
        logger.warning(
        "finalize:wait run=%s sid=%s", run_id, session_id)
        lock.acquire()

    try:
        wait_ms = int((time.monotonic() - started) * 1000) if waited_for_lock else 0
        logger.warning(
        "finalize:start run=%s sid=%s lock_wait_ms=%d", run_id, session_id, wait_ms,
        )

        # Concat step: glue per-turn .webm files into one full.webm and
        # rewrite turn rows' (storage_path, start_offset_ms).
        try:
            from services.session_concatenation import (
                finalize_session_recording,
                ConcatError,
            )
            meta = finalize_session_recording(session_id)
            logger.warning(
        "finalize:concat run=%s sid=%s storage=%s turns_rewritten=%d turns_failed=%d duration_ms=%d",
                run_id, session_id,
                meta.get("storage_path"),
                meta.get("n_turns_rewritten", 0),
                meta.get("n_turns_failed", 0),
                meta.get("duration_ms", 0),
            )
        except ConcatError as e:
            logger.warning(
        "finalize:concat-skip run=%s sid=%s reason=%s",
                run_id, session_id, e,
            )
        except Exception as e:
            logger.warning(
                "finalize:concat-fail run=%s sid=%s err=%s",
                run_id, session_id, e,
            )

        # Metrics aggregation step.
        try:
            m = _compute_session_global_metrics(session_id)
            if m is not None:
                logger.warning(
        "finalize:metrics run=%s sid=%s wpm=%s fillers=%s kpi=%s n=%d",
                    run_id, session_id,
                    m.get("wpm"), m.get("fillers"),
                    m.get("kpi_score"), m.get("snippets_analyzed"),
                )
        except Exception as e:
            logger.warning(
                "finalize:metrics-fail run=%s sid=%s err=%s",
                run_id, session_id, e,
            )

        # Snippet extraction step: highlights cut from the just-published
        # full.webm. Idempotent by window-keyed diff (see apply_extracted_
        # snippets), so re-running converges to the same set of windows
        # without producing duplicates.
        try:
            from services.snippet_truncation import apply_extracted_snippets
            summary = apply_extracted_snippets(session_id)
            logger.warning(
        "finalize:extract run=%s sid=%s proposed=%s frozen=%s inserted=%s deleted=%s skipped=%s",
                run_id, session_id,
                summary.get("candidates_proposed", 0),
                summary.get("frozen_preserved", 0),
                summary.get("new_inserted", 0),
                summary.get("deleted", 0),
                summary.get("skipped", "no"),
            )
        except Exception as e:
            logger.warning(
                "finalize:extract-fail run=%s sid=%s err=%s",
                run_id, session_id, e,
            )

        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.warning(
        "finalize:done run=%s sid=%s elapsed_ms=%d",
            run_id, session_id, elapsed_ms,
        )
    finally:
        lock.release()


@v2_bp.route("/admin/sessions/<session_id>/compute-metrics", methods=["POST"])
@require_admin
def v2_admin_compute_session_metrics(session_id):
    """Trigger computation of global session metrics and AI alignment review.

    1. Aggregates snippet-level metrics into session-level averages
       (delegated to _compute_session_global_metrics; same logic the
       auto-finalize background trigger uses).
    2. Calls LLM to evaluate the transcript and produce alignment
       score + comment (unique to this admin-triggered path — the auto
       trigger skips the LLM call because it's heavyweight).
    """
    try:
        m = _compute_session_global_metrics(session_id)
        if m is None:
            return jsonify({"code": "NO_SNIPPETS", "error": "No active snippets in this session"}), 404

        active_snippets = m["active_snippets"]
        global_wpm = m["wpm"]
        global_fillers = m["fillers"]
        global_pause_ms = m["pause_ms"]
        global_dynamic_db = m["dynamic_db"]
        global_pitch_center = m["pitch_center"]
        global_energy = m["energy"]
        kpi_score = m["kpi_score"]
        kpi_debug = m["kpi_debug"]
        # _compute_session_global_metrics has already persisted the row
        # via db.update_session_global_metrics — no second write needed.

        # AI alignment: evaluate the full interview transcript via LLM
        # Includes KPI score as context so the LLM factors it in
        ai_score = None
        ai_comment = None
        try:
            from services.openai_service import OpenAIService
            service = OpenAIService()
            if service.client:
                # Build transcript summary for the LLM
                transcript_parts = []
                for s in active_snippets:
                    q = s.get("question_text") or "Unknown question"
                    tone = s.get("question_tone") or "unknown"
                    turn = s.get("turn_number") or "?"
                    transcript_parts.append(
                        f"Turn {turn} ({tone}): Q: {q}\n"
                        f"  [Audio: {s.get('duration_ms', 0) / 1000:.1f}s, "
                        f"WPM={s.get('wpm', '?')}, Pause={s.get('pause_ms', '?')}ms, "
                        f"Energy={s.get('energy', '?')}]"
                    )

                # Include the KPI score for the LLM to reference
                kpi_context = ""
                if kpi_score is not None:
                    kpi_context = (
                        f"\n\nPERFORMANCE KPI: {kpi_score}/100 "
                        f"(computed from vocal energy, filler count, and pacing). "
                        f"Factor this into your evaluation — it represents the "
                        f"quantitative delivery quality.\n"
                    )

                eval_prompt = (
                    "You are an expert speech and communication evaluator. "
                    "Review this interview session and provide:\n"
                    "1. A score from 0-100 representing overall communication quality "
                    "(considering charisma, confidence, engagement, vocal delivery, "
                    "AND the KPI score provided below).\n"
                    "2. A 2-3 sentence comment summarizing strengths and areas for improvement.\n\n"
                    "INTERVIEW TRANSCRIPT:\n" + "\n".join(transcript_parts) +
                    kpi_context + "\n\n"
                    "Respond in JSON format: {\"score\": <number>, \"comment\": \"<text>\"}"
                )

                response = service.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": eval_prompt}],
                    max_tokens=300,
                    temperature=0.5,
                )

                import json as json_module
                raw_text = response.choices[0].message.content.strip()
                # Try to parse JSON (handle code blocks)
                if raw_text.startswith("```"):
                    raw_text = raw_text.split("```")[1]
                    if raw_text.startswith("json"):
                        raw_text = raw_text[4:]
                eval_result = json_module.loads(raw_text)
                ai_score = float(eval_result.get("score", 0))
                ai_comment = str(eval_result.get("comment", ""))

                db.update_session_ai_alignment(session_id, ai_score, ai_comment)
        except Exception as ai_err:
            logger.warning("admin: AI alignment eval failed (non-fatal): %s", ai_err)

        return jsonify({
            "status": "ok",
            "global_metrics": {
                "wpm": global_wpm,
                "fillers": global_fillers,
                "pause_ms": global_pause_ms,
                "dynamic_db": global_dynamic_db,
                "pitch_center": global_pitch_center,
                "energy": global_energy,
            },
            "kpi": {
                "score": kpi_score,
                "debug": kpi_debug,
            },
            "ai_alignment": {
                "score": ai_score,
                "comment": ai_comment,
            },
            "snippets_analyzed": len(active_snippets),
        }), 200

    except Exception as e:
        logger.error("admin: compute session metrics failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to compute metrics"}), 500


@v2_bp.route("/admin/sessions/<session_id>/finalize-recording", methods=["POST"])
@require_admin
def v2_admin_finalize_session_recording(session_id):
    """Concatenate per-turn audio for a session into one canonical recording
    and rewrite that session's interview-turn snippet anchors to point into it.

    Manual trigger for the migration toward "snippets are slices of one
    canonical audio". Wraps services.session_concatenation.finalize_session_recording.

    Use this endpoint to backfill historical sessions or to verify the
    pipeline on a session before commit 3/5 wires automatic finalization
    into the session-completion handler.

    Idempotent — re-invoking on an already-finalized session re-uploads
    the same storage key and rewrites the same offsets.

    Response (200):
        {
            "session_id":        str,
            "bucket":            str,
            "storage_path":      str,
            "duration_ms":       int,
            "turn_snippet_ids":  [str, ...],
            "turn_offsets_ms":   [int, ...],
            "turn_durations_ms": [int, ...],
            "n_turns_rewritten": int,
            "n_turns_failed":    int,
            "failed_snippet_ids": [str, ...]
        }
    """
    if not _is_valid_uuid(session_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "session_id must be a valid UUID",
        }), 400

    try:
        from services.session_concatenation import (
            finalize_session_recording,
            ConcatError,
        )
    except Exception as e:
        logger.error("admin: failed to import session_concatenation: %s", e, exc_info=True)
        return jsonify({
            "code": "V2_ERROR",
            "error": "session_concatenation service unavailable",
        }), 500

    try:
        result = finalize_session_recording(session_id)
        logger.info(
            "admin: finalized session=%s rewritten=%d failed=%d storage=%s",
            session_id,
            result.get("n_turns_rewritten", 0),
            result.get("n_turns_failed", 0),
            result.get("storage_path"),
        )
        return jsonify(result), 200
    except ConcatError as e:
        # Concrete, expected failure mode (no turns to glue, ffmpeg
        # failure, upload failure). 422 — caller's payload is fine but
        # the resource isn't in a finalize-able state.
        logger.warning("admin: finalize-recording rejected session=%s: %s", session_id, e)
        return jsonify({
            "code": "FINALIZE_REJECTED",
            "error": str(e),
        }), 422
    except Exception as e:
        logger.error("admin: finalize-recording failed session=%s: %s", session_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to finalize session recording",
        }), 500
