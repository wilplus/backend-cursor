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


# Phase 12 / 13 — admin user context. The frontend BFF hits the
# PLURAL path with PATCH; we register both spellings (singular +
# plural) and accept GET/PUT/PATCH on the same handler so old and
# new callers both resolve without an extra hop.
@v2_bp.route("/admin/user/<user_id>/context", methods=["GET", "PUT", "PATCH"])
@v2_bp.route("/admin/users/<user_id>/context", methods=["GET", "PUT", "PATCH"])
@require_admin
def v2_admin_user_context(user_id):
    """Admin user view: full longitudinal context.

    Phase 12. Backs the admin user view at /admin/users/<id>. The
    frontend BFF proxies /api/admin/user/<id>/context here.

    GET response shape::

        {
          "user": {
            "id", "email", "name",
            "custom_llm_instructions", "private_admin_notes",
            "behavioral_profile", "behavioral_profile_auto",
            "behavioral_profile_source",     # "auto" | "admin_override"
            "coach_override_profile",
            "inferred_learner_profile",
            "admin_profile_override_active",
            "admin_profile_override_set_at"
          },
          "sessions": [    # newest first; full history
            {
              "id", "created_at",
              "date":   "12 May 2026",
              "score":  "8.5/10" | null,
              "status": "Pending Review" | "Completed",
              "summary":   "...",
              "metrics":   [{label, value}, ...],
              "snippets":  [{id, range, wpm, pitch, type, status}, ...],
              "chat":      [{from: "bot"|"user", text}, ...]
            }, ...
          ]
        }

    PUT body (every field optional — only included keys are written)::

        {
          "custom_llm_instructions": "...",
          "private_admin_notes": "...",
          "coach_override_profile": "Stressor" # null clears
        }

    NOTE: The legacy ``queued_override_question`` body field was
    removed in the Week-1 cleanup. The admin override path is now
    the directives-queue endpoint:
    POST /v2/admin/users/<user_id>/directives-queue. If a caller
    still sends ``queued_override_question`` here, it is silently
    ignored — log line emitted so we can spot any straggler.

    PUT response: same shape as GET so the frontend re-renders from
    one request.
    """
    if not _is_valid_uuid(user_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "user_id must be a valid UUID",
        }), 400

    try:
        # PATCH and PUT share the partial-update semantics — only keys
        # present in the body are written, missing keys leave the
        # existing value alone. GET falls through to the read-back.
        if request.method in ("PUT", "PATCH"):
            body = request.get_json(silent=True) or {}

            def has(k):
                return k in body

            instructions = body.get("custom_llm_instructions")
            if isinstance(instructions, str):
                instructions = instructions.strip() or None
            notes = body.get("private_admin_notes")
            if isinstance(notes, str):
                notes = notes.strip() or None
            override_profile = body.get("coach_override_profile")
            if isinstance(override_profile, str):
                override_profile = override_profile.strip() or None

            # Legacy field detection — log once so we can spot any
            # straggler admin tooling still sending it. Silently
            # ignored otherwise. Removed from the writer in Week-1
            # cleanup; directives-queue is the replacement path.
            if "queued_override_question" in body:
                logger.warning(
                    "admin/user/context PUT: ignoring legacy "
                    "queued_override_question field user=%s — use "
                    "POST /v2/admin/users/<id>/directives-queue",
                    user_id,
                )

            db.upsert_admin_user_context_fields(
                user_id=user_id,
                custom_llm_instructions=instructions,
                private_admin_notes=notes,
                coach_override_profile=override_profile,
                update_instructions=has("custom_llm_instructions"),
                update_notes=has("private_admin_notes"),
                update_override_profile=has("coach_override_profile"),
            )
            # Fall through to read-back.

        return jsonify(_build_admin_user_context_payload(user_id)), 200

    except Exception as e:
        logger.error(
            "admin/user/<id>/context %s failed: %s",
            request.method, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to load admin user context",
        }), 500


@v2_bp.route("/admin/users/<user_id>/reset-baseline", methods=["POST"])
@require_admin
def v2_admin_reset_baseline(user_id):
    """Force a user back into the scripted EBCP opener regime.

    Phase 13 admin reset path. Flips
    user_settings.baseline_established back to FALSE so the user's
    next session opens with the hardcoded "Are you good at math?"
    EBCP script (turns 1-4) before handing off to LLM continuation
    on turn 5. Use cases: new microphone, new cohort, suspected
    acoustic drift, or any time the admin wants fresh calibration
    data.

    Idempotent: re-hitting on an already-reset user just stamps
    updated_at; no error. Returns 200 with the new state so the
    frontend can update its local copy without a second GET.

    Response::

        {
          "status": "ok",
          "user_id": "<uuid>",
          "baseline_established": false,
          "baseline_established_at": null
        }
    """
    if not _is_valid_uuid(user_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "user_id must be a valid UUID",
        }), 400

    try:
        ok = db.reset_baseline_established(user_id)
        if not ok:
            return jsonify({
                "code": "PERSIST_FAILED",
                "error": (
                    "Could not reset baseline — user_settings write "
                    "failed. Check Railway logs."
                ),
            }), 500

        logger.info(
            "admin: baseline reset user=%s by admin=%s",
            user_id, getattr(request, "user_id", None),
        )
        return jsonify({
            "status": "ok",
            "user_id": user_id,
            "baseline_established": False,
            "baseline_established_at": None,
        }), 200

    except Exception as e:
        logger.error(
            "admin/users/<id>/reset-baseline failed: %s",
            e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to reset baseline",
        }), 500


def _build_admin_user_context_payload(user_id: str) -> dict:
    """Compose the multi-session admin user context payload.

    Pulls user-level state from user_settings + user_sniper_profile,
    then loads ALL the user's v2_sessions (newest first) and bulk-
    loads their charisma_snippets in one IN-list query (no N+1).
    Renders each session into the frontend's session-block shape.
    """
    settings = db.get_user_settings(user_id) or {}
    sniper = db.get_sniper_profile(user_id) or {}
    email = None
    name = None
    try:
        email = db.get_user_email_from_auth(user_id)
    except Exception:
        pass
    try:
        details = db.v2_get_student_details(user_id) or {}
        name = details.get("name")
    except Exception:
        pass

    behavioral_profile_auto = (
        (sniper.get("behavioral_profile") or "").strip() or None
    )
    coach_override = (
        (sniper.get("coach_override_profile") or "").strip() or None
    )
    effective_profile = coach_override or behavioral_profile_auto

    user_block = {
        "id": user_id,
        "email": email,
        "name": name,
        "custom_llm_instructions": settings.get("custom_llm_instructions"),
        "private_admin_notes": settings.get("private_admin_notes"),
        # queued_override_question removed from response in Week-1
        # cleanup. The DB column persists (no migration) but is
        # no longer surfaced to the FE. Admin override path is
        # POST /v2/admin/users/<id>/directives-queue.
        "behavioral_profile": effective_profile,
        "behavioral_profile_auto": behavioral_profile_auto,
        "behavioral_profile_source": (
            "admin_override" if coach_override else "auto"
        ),
        "coach_override_profile": coach_override,
        "inferred_learner_profile": settings.get(
            "inferred_learner_profile"
        ),
        "admin_profile_override_active": bool(
            settings.get("admin_profile_override")
        ),
        "admin_profile_override_set_at": settings.get(
            "admin_profile_override_set_at"
        ),
    }

    sessions = db.list_sessions_for_user_admin(user_id)
    session_ids = [str(s.get("id")) for s in sessions if s.get("id")]
    snippets_by_session = db.list_snippets_for_sessions(session_ids)

    session_blocks: list[dict] = [
        _build_session_block(s, snippets_by_session.get(str(s.get("id")), []))
        for s in sessions
    ]

    return {"user": user_block, "sessions": session_blocks}


def _build_session_block(session: dict, snippets: list[dict]) -> dict:
    """Render one session for the multi-session admin payload.

    snippets are the charisma_snippets rows belonging to this session.
    They serve double-duty: the chat-transcript rendering iterates
    them ordered by turn_number to build the Q/A bubble list, and the
    snippet-card list reads the same rows for the highlight cards.
    """
    session_id = session.get("id")
    created_at = session.get("created_at")

    kpi = session.get("kpi_score")
    score_label: str | None = None
    if isinstance(kpi, (int, float)):
        # /10 format per the frontend contract — divide 0..100 by 10
        # and round to one decimal place.
        score_label = f"{round(float(kpi) / 10.0, 1)}/10"

    status = (
        "Completed"
        if (session.get("results_published_at") or "")
        else "Pending Review"
    )

    summary = _build_session_summary(session)

    metrics = _build_session_metrics_list(session)

    # Sort snippets: turn_number ASC then start_offset_ms ASC. The
    # bulk loader already returns this order, but we re-sort
    # defensively in case the response shape changes upstream.
    ordered_snippets = sorted(
        snippets,
        key=lambda s: (
            s.get("turn_number") or 0,
            s.get("start_offset_ms") or 0,
        ),
    )

    snippet_cards = [_render_snippet_card(s) for s in ordered_snippets]
    chat = _render_chat_thread(ordered_snippets)

    return {
        "id": str(session_id) if session_id else None,
        "created_at": created_at,
        "date": _format_admin_date(created_at),
        "score": score_label,
        "status": status,
        "summary": summary,
        "metrics": metrics,
        "snippets": snippet_cards,
        "chat": chat,
    }


def _build_session_summary(session: dict) -> str | None:
    """One-line summary string for the session-list accordion header.

    Replaces the legacy ai_task_alignment_comment with a deterministic
    KPI + Stickiness line. Returns None when neither metric has run
    yet so the frontend can show "Compute metrics to see a summary".
    """
    kpi = session.get("kpi_score")
    top_topic = (session.get("stickiness_top_topic") or "").strip() or None
    stickiness = session.get("stickiness_score")

    parts: list[str] = []
    if isinstance(kpi, (int, float)):
        parts.append(f"KPI {round(float(kpi))}/100")
    if top_topic and isinstance(stickiness, (int, float)):
        parts.append(
            f"Sticky topic: {top_topic} ({round(float(stickiness) * 100)}%)"
        )
    elif top_topic:
        parts.append(f"Sticky topic: {top_topic}")

    if parts:
        return " · ".join(parts)

    # Legacy fallback — historical sessions wrote ai_task_alignment_
    # comment before the panel was redesigned; surface it so the row
    # isn't blank when the new metrics haven't run.
    legacy = (session.get("ai_task_alignment_comment") or "").strip()
    return legacy or None


def _build_session_metrics_list(session: dict) -> list[dict]:
    """Flat [{label, value}] list for the metrics card on the session header."""
    out: list[dict] = []

    def add(label: str, value, unit: str = ""):
        if value is None:
            return
        if isinstance(value, float):
            text = f"{value:g}{unit}"
        else:
            text = f"{value}{unit}"
        out.append({"label": label, "value": text})

    add("KPI", session.get("kpi_score"), "/100")
    add("WPM", session.get("global_wpm"))
    add("Fillers", session.get("global_fillers"))
    add("Pause", session.get("global_pause_ms"), "ms")
    add("Dynamic", session.get("global_dynamic_db"), "dB")
    add("Pitch", session.get("global_pitch_center"))
    add("Energy", session.get("global_energy"))

    sticky = session.get("stickiness_score")
    sticky_topic = (session.get("stickiness_top_topic") or "").strip() or None
    if sticky_topic and isinstance(sticky, (int, float)):
        out.append({
            "label": "Sticky topic",
            "value": f"{sticky_topic} ({round(float(sticky) * 100)}%)",
        })

    return out


def _render_snippet_card(snippet: dict) -> dict:
    """One snippet → frontend snippet card shape."""
    start = snippet.get("start_offset_ms")
    duration = snippet.get("duration_ms")
    range_label: str | None = None
    if start is not None and duration is not None:
        start_sec = int(float(start) / 1000.0)
        end_sec = int((float(start) + float(duration)) / 1000.0)
        range_label = f"{_mmss(start_sec)} - {_mmss(end_sec)}"

    snippet_type = (snippet.get("snippet_type") or "unlabeled").strip().lower()

    # status taxonomy for the card: published when admin commented +
    # snippet has a type; saved when only one of those is set;
    # otherwise raw.
    has_comment = bool((snippet.get("admin_comment") or "").strip())
    has_type = snippet_type in ("charisma", "stress")
    if has_comment and has_type:
        status = "published"
    elif has_comment or has_type:
        status = "saved"
    elif snippet.get("is_skipped"):
        status = "skipped"
    else:
        status = "raw"

    # Full per-window metrics JSONB. The admin card renders these
    # raw — pace + fillers + pause + dynamic dB + pitch + energy
    # are read straight from this dict so the +/- 2 s buttons can
    # repaint the card the moment recompute_snippet_metrics_for_window
    # returns. The denormalised top-level wpm/pitch fields are kept
    # for back-compat with any caller that still reads them.
    metrics_blob = snippet.get("metrics") if isinstance(
        snippet.get("metrics"), dict
    ) else None

    return {
        "id": str(snippet.get("id")) if snippet.get("id") else None,
        "turn_number": snippet.get("turn_number"),
        "range": range_label,
        "start_offset_ms": snippet.get("start_offset_ms"),
        "duration_ms": snippet.get("duration_ms"),
        "wpm": snippet.get("wpm"),
        "pitch": snippet.get("pitch_center"),
        "fillers": snippet.get("fillers"),
        "pause_ms": snippet.get("pause_ms"),
        "dynamic_db": snippet.get("dynamic_db"),
        "energy": snippet.get("energy"),
        "metrics": metrics_blob,
        "type": snippet_type,
        "status": status,
        "admin_comment": snippet.get("admin_comment"),
        "ai_draft_admin_comment": snippet.get("ai_draft_admin_comment"),
        "follow_up_question": snippet.get("follow_up_question"),
        "ai_draft_follow_up_question": snippet.get(
            "ai_draft_follow_up_question"
        ),
        "transcript": snippet.get("transcript"),
        "is_skipped": bool(snippet.get("is_skipped")),
    }


def _render_chat_thread(snippets: list[dict]) -> list[dict]:
    """Build [{from, text}, ...] chat from snippets, oldest first.

    For each turn we emit a 'bot' bubble (the question) followed by a
    'user' bubble (their answer transcript). Bubbles with empty text
    are skipped — better to render a clean thread than to print empty
    cards for missing transcripts.
    """
    thread: list[dict] = []
    for s in snippets:
        question = (s.get("question_text") or "").strip()
        answer = (s.get("transcript") or "").strip()
        if question:
            thread.append({
                "from": "bot",
                "text": question,
                "turn_number": s.get("turn_number"),
                "snippet_id": str(s.get("id")) if s.get("id") else None,
            })
        if answer:
            thread.append({
                "from": "user",
                "text": answer,
                "turn_number": s.get("turn_number"),
                "snippet_id": str(s.get("id")) if s.get("id") else None,
            })
    return thread


def _mmss(total_seconds: int) -> str:
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


def _format_admin_date(value) -> str | None:
    """ISO/datetime → '12 May 2026'. Returns None on parse failure."""
    if value is None:
        return None
    try:
        if isinstance(value, str):
            from datetime import datetime as _dt
            # Supabase returns ISO 8601 with a trailing 'Z' OR offset.
            cleaned = value.replace("Z", "+00:00")
            dt = _dt.fromisoformat(cleaned)
        else:
            dt = value
        return dt.strftime("%-d %b %Y")
    except Exception:
        return None


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
- You must dynamically build upon a specific element from the user's most recent answer to challenge them further. DO NOT parrot or awkwardly repeat their words back to them. Push the conversation forward contextually.
- Never break character or explain what you're doing.
- FORMATTING RULE: If you include a brief acknowledgment or validation before your question,
  separate it from the question using the exact delimiter `|||`.
  Example: `That was a vivid story! ||| Now tell me about a time you completely failed at something that mattered to you.`
  If there is no acknowledgment, return ONLY the question text with no delimiter.

LANGUAGE HANDLING — English-only with a one-shot disclaimer:
- You always speak ENGLISH, regardless of the language the user uses. Do NOT mirror, translate into, or switch to the user's language.
- The FIRST time in this conversation that you detect the user has spoken a language other than English (e.g. Polish, Spanish, French, etc.), prepend EXACTLY this disclaimer as the acknowledgment segment before your next question, separated by `|||`:
  "I only speak English, but feel free to continue in your native language! The acoustic analysis will still be completed perfectly."
  Example: `I only speak English, but feel free to continue in your native language! The acoustic analysis will still be completed perfectly. ||| Tell me about a moment when…`
- Inspect the conversation history before issuing this disclaimer. If you have ALREADY issued it once in this session (look for the exact phrase in your prior turns), do NOT repeat it — just continue with your next question in English.
- After the disclaimer fires, immediately continue with your normal coaching agenda (in English).

IDENTITY & PERSONA — graceful pivot, never get stuck:
- If the user asks about your identity, name, whether you're real, human, or an AI (e.g. "Who are you?", "Are you real?", "What is your name?", "Am I talking to a bot?"), respond with a brief, graceful acknowledgment IMMEDIATELY followed by your next coaching question, separated by `|||`.
  Example: `I am your AI coaching chatbot! But let's get back to it... ||| Tell me about the toughest decision you've ever had to defend.`
- Never give a long, robotic AI disclaimer. Never let the conversation get stuck on your identity.
- On repeat identity probes within the same session, shorten the acknowledgment further (or drop it entirely) and pivot straight back to the coaching agenda. You are always in control of the dialogue flow.
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
# Cold-start onboarding (turns 1-4) — REMOVED IN PHASE 18.
#
# Per docs/ARCHITECTURE_SINGLE_SOURCE_OF_TRUTH.md, the frontend now
# owns turns 1-4 entirely as hardcoded ONBOARDING_MESSAGES strings.
# The backend's scripted EBCP path (the long _EBCP_BASELINE_SYSTEM_
# PROMPT, the _EBCP_FALLBACKS dict, and _generate_ebcp_question) was
# deleted to eliminate duplicate ownership. /v2/public/interview/
# next-question now refuses turn_number <= 4 with 400 TURN_OWNED_BY_
# FRONTEND so a confused client surfaces the violation immediately
# instead of silently regressing into "backend owns turn 1 again".
# ---------------------------------------------------------------------------


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


def _build_longitudinal_context_block(
    *,
    snippet_id: str | None,
    user_id: str | None,
) -> str | None:
    """Phase 15 — assemble per-user longitudinal context for the
    first-question prompt of a contextual /chat click.

    Returns a multi-section string ready to splice into the system
    prompt, or None when no signal is available for this user.

    Sections (each independently optional):

      [LEARNER PROFILE]              — behavioral_profile + recurring
                                       themes from inferred profile,
                                       layered with any admin override.
      [RECENT REFLECTION]            — current_learner_mirror narrative
                                       (truncated to 600 chars so it
                                       doesn't dominate the prompt).
      [PRIOR ATTEMPTS ON THIS MOMENT]— last 3 coaching_attempts for
                                       this snippet+user, with the
                                       questions previously asked so
                                       the LLM avoids repeating
                                       angles and acknowledges
                                       progress.

    Failure modes swallow + log — a partial block is better than
    blocking the first-question generation. Returns None when ALL
    three sections come back empty (caller falls through to the
    pre-Phase-15 behaviour).
    """
    if not user_id or not snippet_id:
        return None

    sections: list[str] = []
    settings: dict = {}

    # ── Learner profile ───────────────────────────────────────────
    try:
        settings = db.get_user_settings(user_id) or {}
        sniper = db.get_sniper_profile(user_id) or {}
        learner_type = (
            (sniper.get("coach_override_profile") or "").strip()
            or (sniper.get("behavioral_profile") or "").strip()
        )
        profile = settings.get("inferred_learner_profile") or {}
        override = settings.get("admin_profile_override") or None
        base_traits = (profile.get("traits") or {}) if isinstance(profile, dict) else {}
        override_traits = (
            (override.get("traits") or {}) if isinstance(override, dict) else {}
        )
        merged_traits = {**base_traits, **override_traits}
        recurring = merged_traits.get("recurring_entities") or {}
        themes = []
        if isinstance(recurring, dict):
            for t in (recurring.get("themes") or [])[:3]:
                if isinstance(t, dict) and t.get("label"):
                    themes.append(str(t.get("label")))

        if learner_type or themes:
            lines = ["[LEARNER PROFILE]"]
            if learner_type:
                lines.append(f"Learner type: {learner_type}")
            if themes:
                lines.append(
                    f"Recurring themes the user keeps returning to: "
                    f"{', '.join(themes)}"
                )
            lines.append(
                "Frame your question to push them past their comfort zone "
                "given this profile — don't pander to their stated "
                "strengths."
            )
            sections.append("\n".join(lines))
    except Exception as e:
        logger.warning(
            "first-question: profile load failed user=%s err=%s",
            user_id, e,
        )

    # ── Recent reflection (mirror) ────────────────────────────────
    try:
        mirror = (settings or db.get_user_settings(user_id) or {}).get(
            "current_learner_mirror"
        ) or {}
        narrative = (mirror.get("narrative") or "").strip() if isinstance(mirror, dict) else ""
        if narrative:
            if len(narrative) > 600:
                narrative = narrative[:600].rstrip() + "…"
            sections.append(f"[RECENT REFLECTION]\n{narrative}")
    except Exception as e:
        logger.warning(
            "first-question: mirror load failed user=%s err=%s",
            user_id, e,
        )

    # ── Prior sessions: archetype + recent admin coaching notes ──
    # Cross-session memory. The infinite-flywheel UX is "each loop
    # is wiser than the last" — the LLM should see what archetype
    # the user landed on in their previous session(s) and what the
    # admin has been telling them, so the new opening question
    # builds on (not repeats) that thread.
    try:
        prior_sessions = (
            db.v2_get_published_sessions_for_user(user_id) or []
        )
        last_session = prior_sessions[0] if prior_sessions else None

        archetype: str | None = None
        if isinstance(last_session, dict):
            cp = last_session.get("charisma_profile") or {}
            if isinstance(cp, dict):
                archetype = (cp.get("archetype") or "").strip() or None

        # Pull the most recent admin coaching notes the user has
        # received across ALL their published snippets. We cap at 3
        # so the LLM has continuity without the prompt ballooning.
        recent_notes: list[str] = []
        try:
            note_rows = (
                db.client.table("charisma_snippets")
                .select("admin_comment, created_at, session_id")
                .eq("user_id", user_id)
                .not_.is_("admin_comment", "null")
                .order("created_at", desc=True)
                .limit(8)
                .execute()
                .data
            ) or []
            for r in note_rows:
                # Exclude the snippet the user is currently working
                # on — the parent prompt already has its admin_comment.
                if r.get("session_id") and r.get("session_id") == snippet_id:
                    continue
                note = (r.get("admin_comment") or "").strip()
                if not note:
                    continue
                if len(note) > 180:
                    note = note[:180].rstrip() + "…"
                recent_notes.append(note)
                if len(recent_notes) >= 3:
                    break
        except Exception as note_err:
            logger.warning(
                "first-question: recent admin notes load failed "
                "user=%s err=%s", user_id, note_err,
            )

        if archetype or recent_notes:
            lines = ["[PRIOR SESSIONS]"]
            if archetype:
                lines.append(
                    f"Last session's archetype read: {archetype}. "
                    "Use this as a continuity anchor — acknowledge "
                    "the trajectory, don't restart from zero."
                )
            if recent_notes:
                lines.append(
                    "Recent admin coaching notes (most-recent first):"
                )
                for note in recent_notes:
                    lines.append(f"  • {note}")
                lines.append(
                    "Build on these threads — do NOT repeat advice "
                    "the admin already gave; probe the next layer."
                )
            sections.append("\n".join(lines))
    except Exception as e:
        logger.warning(
            "first-question: prior-sessions load failed user=%s err=%s",
            user_id, e,
        )

    # ── Prior attempts on THIS snippet ────────────────────────────
    try:
        attempts = db.list_coaching_attempts_for_snippet(
            snippet_id, user_id=user_id,
        ) or []
        # list_coaching_attempts_for_snippet returns chronological
        # (attempt_number ASC) — last 3 means the most recent three.
        recent = attempts[-3:] if attempts else []
        question_lines: list[str] = []
        for a in recent:
            q = (a.get("question_text") or "").strip()
            if not q:
                continue
            if len(q) > 200:
                q = q[:200].rstrip() + "…"
            question_lines.append(f"  - {q}")
        if question_lines:
            lines = ["[PRIOR ATTEMPTS ON THIS MOMENT]"]
            lines.append(
                f"The user has already worked through these "
                f"{len(question_lines)} angle(s) on THIS snippet:"
            )
            lines.extend(question_lines)
            lines.append(
                "Open with ONE sentence acknowledging their progress "
                "(\"You've already worked the X angle…\"), then ask a "
                "NEW question that probes a different dimension — "
                "emotion if they covered mechanics, mechanics if they "
                "covered emotion, the people involved if they covered "
                "the situation, etc. DO NOT repeat any prior question's "
                "angle."
            )
            sections.append("\n".join(lines))
    except Exception as e:
        logger.warning(
            "first-question: prior attempts load failed "
            "snippet=%s user=%s err=%s",
            snippet_id, user_id, e,
        )

    if not sections:
        return None
    return "\n\n".join(sections)


def _generate_llm_question(
    turn_number: int,
    tone: str,
    previous_turns: list | None = None,
    user_id: str | None = None,
    *,
    contextual_init: dict | None = None,
    timeout_seconds: float | None = None,
    baseline_objective: str | None = None,
    conversation_summary: str | None = None,
) -> str | None:
    """Call GPT-4o-mini to generate the next interview question.

    Falls back to the hardcoded bank on failure.
    Returns the question text, or None on error (caller uses fallback).

    timeout_seconds — Phase 13. When set, the OpenAI call is bounded
    by this wall-clock budget. Used by the smart-EBCP-bypass path so
    a stalled LLM doesn't keep a returning user staring at a blank
    chat; the caller catches None and substitutes the scripted EBCP
    turn 1 as a safety net.

    baseline_objective — Directed-freestyle pivot. When the caller
    supplies a per-turn objective string (turns 1-4 for users with
    baseline_established=False), it's spliced into the system prompt
    as a [CURRENT_TURN_OBJECTIVE] block so the LLM has a concrete
    psychological target for THIS turn (icebreaker, empathy,
    pressure, quick reflex) rather than freelancing across the four
    onboarding turns. Returning users get None and the prompt
    falls back to standard alternation.

    conversation_summary — Phase A2.1 rolling digest. When passed,
    replaces the quadratic-cost full-history replay: the prompt
    gets the digest as a context block + only the last 2 raw
    turns in chat history. NULL on the very first turn (cold-
    start) or when the async summary writer hasn't caught up; the
    prompt builder degrades to using all of previous_turns in
    that case so we never serve a turn with NO context.
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
            # Transcript is OPTIONAL — the publish gate only demands
            # admin_comment, so we mirror that here. When transcript
            # is empty the base prompt below substitutes a neutral
            # "the user just recorded a moment" phrasing so the LLM
            # still has a coherent setup.
            if intent in _CONTEXTUAL_INTENTS and admin_comment:
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

                # ── Phase 15 longitudinal context ───────────────────
                # When enabled, splice in learner-profile + mirror +
                # prior attempts on THIS snippet so the LLM stops
                # producing the same opener on every click. Gated by
                # LONGITUDINAL_FIRST_QUESTION_ENABLED so deploy is a
                # no-op until the operator flips it; falls silent if
                # the user has no signal yet (cold-start unaffected).
                longitudinal_block: str | None = None
                try:
                    from config import Config
                    if Config().LONGITUDINAL_FIRST_QUESTION_ENABLED:
                        longitudinal_block = _build_longitudinal_context_block(
                            snippet_id=source_snippet_id,
                            user_id=user_id,
                        )
                except Exception as long_err:
                    logger.warning(
                        "first-question: longitudinal block failed: %s",
                        long_err,
                    )

                # ── Phase 16 baseline insight ───────────────────────
                # Pre-baked digest of the user's EBCP turns 1-4. Read
                # from the cache only — we don't compute here because
                # this is the contextual /chat path, not the
                # interview funnel where compute happens at turn 5.
                # Gated by BASELINE_SUMMARY_ENABLED.
                baseline_block: str | None = None
                try:
                    from config import Config
                    if Config().BASELINE_SUMMARY_ENABLED and user_id:
                        summary = db.get_user_baseline_summary(user_id)
                        if summary:
                            from services.baseline_summary import (
                                format_baseline_for_prompt,
                            )
                            baseline_block = format_baseline_for_prompt(summary)
                except Exception as bs_err:
                    logger.warning(
                        "first-question: baseline block failed: %s",
                        bs_err,
                    )

                # When transcript is missing (Whisper miss / extracted
                # highlight without a captured slice), fall back to a
                # neutral framing that grounds the LLM in the coach
                # insight alone. The "What did the user say" line is
                # built once so both branches share the substitution.
                if transcript:
                    moment_line = f"In that recording, they said: '{transcript}'."
                else:
                    moment_line = (
                        "We don't have a transcript of the exact words, "
                        "but the coach flagged this moment specifically."
                    )

                if intent == "charisma":
                    base = (
                        "You are a coaching assistant. "
                        "The user clicked 'Understand your charisma' on a past recording. "
                        f"{moment_line} "
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
                        f"{moment_line} "
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

                # Few-shot examples first (anchors wording), then
                # Phase 16 baseline insight (who this user is from
                # their EBCP run), then Phase 15 longitudinal context
                # (recent attempts on this snippet + recurring
                # entities), then the base task description.
                #
                # Order matters: the LLM should read who-this-user-is
                # BEFORE the imperative task block. Baseline (stable
                # identity) comes before longitudinal (recent state)
                # so the model anchors on identity and adapts on
                # recent — not the other way around.
                prompt_parts: list[str] = []
                if few_shot_block:
                    prompt_parts.append(few_shot_block)
                if baseline_block:
                    prompt_parts.append(baseline_block)
                if longitudinal_block:
                    prompt_parts.append(longitudinal_block)
                prompt_parts.append(base)
                system_prompt = "\n\n".join(prompt_parts)

                # Phase 15 / 16 — bump temperature when ANY user-
                # specific context is in play (longitudinal block OR
                # the Phase 16 baseline insight) so even identical
                # raw inputs produce verbal variety. Falls back to
                # the legacy 0.7 when both blocks are empty
                # (preserves cold-start behaviour byte-for-byte).
                ctx_temperature = (
                    0.85
                    if (longitudinal_block or baseline_block)
                    else 0.7
                )

                response = service.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "system", "content": system_prompt}],
                    max_tokens=180,
                    temperature=ctx_temperature,
                )
                question = response.choices[0].message.content.strip()
                if question.startswith('"') and question.endswith('"'):
                    question = question[1:-1]
                return question if question else None

        # Build system prompt with optional user-specific injection
        system_prompt = _INTERVIEW_SYSTEM_PROMPT
        if user_id:
            system_prompt = _augment_interview_prompt_with_profile(
                system_prompt, user_id,
            )
            # Phase 16 — splice in the pre-baked baseline digest so
            # the LLM doesn't redo extraction + generation in one
            # call. Flag-gated; falls through silently when the
            # summary hasn't been computed yet (cold-start users or
            # admin resets that haven't graduated again).
            try:
                from config import Config
                if Config().BASELINE_SUMMARY_ENABLED:
                    summary = db.get_user_baseline_summary(user_id)
                    if summary:
                        from services.baseline_summary import (
                            format_baseline_for_prompt,
                        )
                        baseline_block = format_baseline_for_prompt(summary)
                        if baseline_block:
                            system_prompt = (
                                f"{system_prompt}\n\n{baseline_block}"
                            )
            except Exception as bs_err:
                logger.warning(
                    "interview: baseline_summary inject failed "
                    "user=%s err=%s", user_id, bs_err,
                )

        # ── Phase A2.1 — rolling conversation summary ───────────────
        # Splice order (pitfall #7 in the learning-loop spec —
        # augmentation order is load-bearing, later blocks get more
        # model attention):
        #
        #   1. base interview prompt
        #   2. profile / [LEARNER PROFILE] (existing)
        #   3. baseline_summary (Phase 16, stable identity)
        #   4. conversation_summary (THIS BLOCK — per-session digest)
        #   5. baseline_objective ([CURRENT_TURN_OBJECTIVE], per-turn
        #      directive — stays last so it anchors the generate step)
        #
        # The summary goes BETWEEN baseline (stable user identity) and
        # baseline_objective (per-turn imperative) because it's
        # per-session ephemera that's more recent than baseline but
        # less imperative than the current-turn directive. Keeping
        # baseline_objective last preserves its anchoring effect.
        if conversation_summary:
            try:
                from services.conversation_summary import (
                    format_summary_for_prompt,
                )
                summary_block = format_summary_for_prompt(conversation_summary)
                if summary_block:
                    system_prompt = (
                        f"{system_prompt}\n\n{summary_block}"
                    )
            except Exception as sum_err:
                logger.warning(
                    "interview: conversation_summary splice failed "
                    "(continuing without): %s", sum_err,
                )

        # Directed-freestyle objective for the 4 onboarding turns.
        # When the caller passes a baseline_objective, the LLM gets
        # a hard psychological target for THIS turn instead of free-
        # styling across the onboarding phase. Goes AFTER the
        # profile/baseline/summary blocks so identity context is
        # read first, then the per-turn directive is the last
        # instruction the model sees before "generate" — anchoring
        # effect on the response.
        if baseline_objective:
            system_prompt = (
                f"{system_prompt}\n\n[CURRENT_TURN_OBJECTIVE]\n"
                f"{baseline_objective.strip()}\n\n"
                "Build a one-question scenario that delivers the "
                "objective above. Stay in the interview-coach voice. "
                "Do NOT explain the objective to the user — just ask "
                "the question."
            )

        # Build conversation history for context.
        # Phase A2.1: when a conversation_summary is in play, the
        # digest covers the older turns and we only need the LAST 2
        # raw turns for short-range fidelity (the model gets
        # "what was JUST said" verbatim, longer-range memory from
        # the summary block above). When no summary exists yet
        # (cold-start), fall back to replaying ALL previous_turns
        # so the first few turns don't lose context.
        messages = [{"role": "system", "content": system_prompt}]

        if previous_turns:
            turns_to_render = (
                previous_turns[-2:]
                if conversation_summary
                else previous_turns
            )
            for turn in turns_to_render:
                messages.append({"role": "assistant", "content": turn.get("question", "")})
                if turn.get("transcript"):
                    messages.append({"role": "user", "content": turn["transcript"]})

        # Request next question
        messages.append({
            "role": "user",
            "content": f"Generate the next question. This is turn {turn_number}. Required tone: {tone}.",
        })

        # Phase 13 — optional per-call timeout for the bypass-EBCP
        # path. The OpenAI Python SDK accepts a ``timeout`` kwarg on
        # the request that maps to httpx; if it isn't honoured for
        # some reason the outer try/except still catches the slow
        # call and falls back to the scripted EBCP turn 1.
        create_kwargs = {
            "model": "gpt-4o-mini",
            "messages": messages,
            "max_tokens": 150,
            "temperature": 0.8,
        }
        if timeout_seconds is not None:
            create_kwargs["timeout"] = float(timeout_seconds)
        response = service.client.chat.completions.create(**create_kwargs)

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

    Optional query param ``include_contrast=true`` (Phase
    Stress-Contrast / BE-3) attaches a ``contrast`` field powered
    by ``db.compute_stress_contrast``: median deltas between the
    user's last 5 published snippets ("official / high-stakes")
    and their last 5 casual voice benchmarks captured during
    /v2/chat/query. ``contrast`` is None when either side has
    fewer than 3 samples; the frontend uses None to omit the card
    entirely (do not render a placeholder).
    """
    try:
        if not _is_valid_uuid(session_id):
            return jsonify({"code": "INVALID_INPUT", "error": "session_id must be a valid UUID"}), 400

        user_id = request.user_id
        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "NOT_FOUND", "error": "Session not found"}), 404

        # BE-3: stress contrast is opt-in via query param so callers
        # that don't render the dashboard section don't pay for two
        # extra table reads. Cheap when included (≤10 indexed rows
        # per side) but still gated for hygiene.
        include_contrast = (
            (request.args.get("include_contrast") or "")
            .strip()
            .lower()
            in ("1", "true", "yes")
        )

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

            # Charisma Awareness Dashboard payload. Read straight off
            # the session row — the blob was computed and persisted
            # during publish-session-results (and overwritten by the
            # admin compute-metrics endpoint). Pre-existing sessions
            # that haven't been recomputed since the column was
            # added return NULL, which the frontend treats as
            # "hide the dashboard section entirely".
            payload["charisma_profile"] = session.get("charisma_profile")

        # ── BE-3 Stress Contrast ─────────────────────────────────────
        # Gated by ?include_contrast=true. Computed across the WHOLE
        # user (last 5 published snippets vs last 5 casual chat
        # benchmarks), not just this session — that's the point: the
        # delta is a per-user trait, not a per-session one. Surface
        # it on the same payload so the dashboard renders it in the
        # session-review view without a second round-trip.
        #
        # Returns None when either pool has <3 samples; the frontend
        # treats None as "omit the section entirely" (do NOT render
        # a 'not enough data' placeholder — see FE Prompt 3 C7).
        if include_contrast:
            try:
                payload["contrast"] = db.compute_stress_contrast(user_id)
            except Exception as contrast_err:
                # Aggregator failure must not break the rest of the
                # results payload. Log and surface None so the FE
                # uniformly handles "no contrast available".
                logger.warning(
                    "user/results: stress contrast failed user=%s "
                    "session=%s err=%s",
                    user_id, session_id, contrast_err,
                )
                payload["contrast"] = None

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
                # Per-session charisma blob — straight cache read so
                # the timeline doesn't fan-out N LLM calls. NULL when
                # the session pre-dates the column or was too sparse
                # to compute.
                "charisma_profile": session.get("charisma_profile"),
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


def _augment_interview_prompt_with_profile(
    base_prompt: str,
    user_id: str,
) -> str:
    """Phase 13 — soft profile injection for the interview-question generator.

    Appends a [COACHING CONTEXT] block with the user's effective
    learner type + admin's global LLM instructions. Adds a stability
    directive telling the model to USE the profile to shape tone
    without becoming locked-in by it ("still probe beyond their
    stated strengths"). Custom instructions remain available as the
    legacy ADDITIONAL INSTRUCTIONS block so the existing wording
    admins typed in keeps applying.

    Failure modes swallow — a missing settings row or DB hiccup
    returns the base prompt unchanged so question generation never
    hard-fails on profile load.
    """
    learner_type = ""
    custom_instructions = ""
    try:
        settings = db.get_user_settings(user_id) or {}
        custom_instructions = (
            settings.get("custom_llm_instructions") or ""
        ).strip()
    except Exception as e:
        logger.warning(
            "interview: settings load failed user=%s: %s", user_id, e,
        )

    try:
        sniper = db.get_sniper_profile(user_id) or {}
        learner_type = (
            (sniper.get("coach_override_profile") or "").strip()
            or (sniper.get("behavioral_profile") or "").strip()
        )
    except Exception as e:
        logger.warning(
            "interview: profile load failed user=%s: %s", user_id, e,
        )

    # ── Phase 17 — Master Score (B6) block ───────────────────────
    # Pulls the most recent session's persisted kpi_score / global
    # acoustic aggregates and renders them as a tight
    # [PERFORMANCE METRICS] block. Anti-parrot directive can now
    # cite concrete numbers ("your pace landed at 145 wpm, well in
    # band, but your dynamic range came in low") rather than
    # generic shape. Falls silent when no recent session has
    # measurements — protects cold-start users from a misleading
    # "your score" line in the prompt.
    metrics_block: str | None = None
    try:
        metrics_block = _build_master_score_block(user_id)
    except Exception as e:
        logger.warning(
            "interview: master-score block failed user=%s: %s", user_id, e,
        )

    if not learner_type and not custom_instructions and not metrics_block:
        return base_prompt

    block_lines = ["", "[COACHING CONTEXT]"]
    if learner_type:
        block_lines.append(f"Learner Profile: {learner_type}")
    if custom_instructions:
        block_lines.append(f"Admin Notes: {custom_instructions}")
    block_lines.append("")
    block_lines.append(
        "Directive: Use this profile to shape your challenge style and "
        "tone, but DO NOT become trapped by it. You must still probe "
        "beyond their stated strengths and test their boundaries under "
        "pressure."
    )

    augmented = base_prompt + "\n" + "\n".join(block_lines)

    if metrics_block:
        augmented += "\n\n" + metrics_block

    # Keep the legacy verbatim block as well — admins relying on the
    # old "ADDITIONAL INSTRUCTIONS FOR THIS USER" wording in their
    # custom_llm_instructions content still see it surface unchanged.
    if custom_instructions:
        augmented += (
            "\n\nADDITIONAL INSTRUCTIONS FOR THIS USER:\n"
            f"{custom_instructions}"
        )

    return augmented


def _build_master_score_block(user_id: str) -> str | None:
    """Phase 17 — render the user's latest B6 Master Score for the LLM.

    Source: the most recent v2_sessions row that has computed
    metrics. Surfaces kpi_score (B7, the persisted 0..100 score),
    plus the global acoustic averages that fed it, plus the
    stickiness topic (C4) when present.

    Returns None when no recent session has metrics — better to
    omit the block than to print "—" placeholders the LLM would
    parrot back at the user.

    Uses the LATEST session's data on purpose: the next interview
    question is FORWARD-looking from the user's last completed run,
    not their lifetime average. If we ever want a lifetime view, it
    belongs in a separate block (e.g. learner profile).
    """
    if not user_id:
        return None
    try:
        latest = db.v2_get_latest_published_session_for_user(user_id) or {}
    except Exception as e:
        logger.warning(
            "master-score-block: session load failed user=%s: %s", user_id, e,
        )
        return None
    if not latest:
        return None

    kpi = latest.get("kpi_score")
    g_wpm = latest.get("global_wpm")
    g_fillers = latest.get("global_fillers")
    g_dynamic = latest.get("global_dynamic_db")
    g_pitch = latest.get("global_pitch_center")
    g_pause = latest.get("global_pause_ms")
    sticky_topic = (latest.get("stickiness_top_topic") or "").strip() or None

    # Nothing measurable on the latest session — bail rather than
    # render a hollow block.
    if all(v is None for v in (kpi, g_wpm, g_fillers, g_dynamic, g_pitch, g_pause)):
        return None

    lines: list[str] = [
        "[PERFORMANCE METRICS — from this user's most recent session]"
    ]
    if isinstance(kpi, (int, float)):
        lines.append(f"Master score (KPI, 0-100): {round(float(kpi), 1)}")
    if isinstance(g_wpm, (int, float)):
        lines.append(f"Pace: {round(float(g_wpm), 1)} WPM (target band 120-160)")
    if isinstance(g_fillers, (int, float)):
        lines.append(f"Fillers across session: {int(g_fillers)}")
    if isinstance(g_dynamic, (int, float)):
        lines.append(f"Dynamic range: {round(float(g_dynamic), 1)} dB")
    if isinstance(g_pitch, (int, float)):
        lines.append(f"Pitch centre: {round(float(g_pitch), 1)} st")
    if isinstance(g_pause, (int, float)):
        lines.append(f"Average pause: {round(float(g_pause), 0)} ms")
    if sticky_topic:
        lines.append(f"Sticky topic last session: {sticky_topic}")
    lines.append("")
    lines.append(
        "Directive: cite ONE specific metric above when it would "
        "ground your question — e.g. \"your pace ran at 175 WPM in "
        "the last session, so this time...\". Do NOT recite the "
        "whole block; pick the most coachable number for THIS turn."
    )
    return "\n".join(lines)


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


@v2_bp.route("/coaching/state-machine/turn", methods=["POST"])
@require_auth
def v2_coaching_state_machine_turn():
    """One turn of the 5-step coaching state machine.

    Parallel to ``/v2/coaching/turn`` (which runs the older
    awareness→trial loop). Doesn't touch the existing flow — the
    frontend opts in by hitting this endpoint instead.

    Body::

        {
          "coaching_id": "<uuid>",   // existing coaching_sessions row
          "user_message": "..."       // optional on the very first
                                      // call (STEP 1 has no user
                                      // message yet — the AI opens)
        }

    Response (200) — mirrors the structured-output schema verbatim
    plus an ``ai_message_id`` placeholder the frontend can ignore::

        {
          "narration":    str,
          "step":         1..5,
          "triggers":     [str, ...],
          "end":          bool,
          "current_question_position": 1..5 | null,  // Director's
                                                      // Script position
          "snippet_player":   { snippet_id } | omitted,
          "label_buttons":    { snippet_id, yes_label, no_label } | omitted,
          "acoustic_targets": { target_wpm, ... } | omitted
        }

    Persists each turn to ``coaching_sessions.messages`` so the
    admin transcript view replays the full chat. The state itself
    is implicit in the conversation history — we hand the LLM the
    full prior turns and it follows the protocol from the system
    prompt.
    """
    try:
        body = request.get_json(silent=True) or {}
        coaching_id = (body.get("coaching_id") or "").strip()
        user_message = (body.get("user_message") or "").strip()
        # Optional language hint for STEP 1 (which has no prior
        # user message to infer language from). Accept either key
        # so the frontend BFF doesn't have to be picky. Plain
        # display name ("Polish", "English") or ISO code — the
        # prompt builder hands it to the LLM verbatim.
        user_language_hint = (
            body.get("user_language")
            or body.get("user_language_hint")
            or body.get("language")
            or ""
        ).strip() or None

        if not _is_valid_uuid(coaching_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "coaching_id must be a UUID",
            }), 400

        user_id = request.user_id
        coaching = db.get_coaching_session(coaching_id, user_id)
        if not coaching:
            return jsonify({
                "code": "COACHING_NOT_FOUND",
                "error": "Coaching session not found",
            }), 404
        if coaching.get("current_stage") == "complete":
            return jsonify({
                "code": "COACHING_COMPLETE",
                "error": "This coaching loop is already complete.",
            }), 409

        snippet = db.get_snippet_by_id(
            coaching.get("source_snippet_id"), user_id=user_id,
        )
        if not snippet:
            return jsonify({
                "code": "SNIPPET_NOT_FOUND",
                "error": "Source snippet missing",
            }), 404

        # Acoustic targets are computed against the snippet's parent
        # session — its global metrics are the user's baseline for
        # this conversation. Falls through to None targets when the
        # session row hasn't been finalized yet (the prompt builder
        # drops missing lines).
        parent_session: dict = {}
        if snippet.get("session_id"):
            try:
                parent_session = db.v2_get_session_by_id(
                    snippet.get("session_id"),
                ) or {}
            except Exception as e:
                logger.warning(
                    "coaching/state-machine: parent session load failed sid=%s err=%s",
                    snippet.get("session_id"), e,
                )

        from services.coaching_state_machine import (
            compute_acoustic_targets,
            build_state_machine_system_prompt,
            STATE_MACHINE_RESPONSE_SCHEMA,
            parse_state_machine_response,
        )
        targets = compute_acoustic_targets(
            global_wpm=parent_session.get("global_wpm"),
            global_fillers=parent_session.get("global_fillers"),
            global_dynamic_db=parent_session.get("global_dynamic_db"),
            session_duration_ms=parent_session.get("duration_ms"),
        )

        # Director's Script — admin-edited array wins; fall through
        # to AI-pre-generated draft; empty list if neither exists
        # (the prompt handles the empty case by skipping straight
        # from STEP 2 to STEP 8).
        director_script_questions = (
            parent_session.get("final_human_next_questions")
            or parent_session.get("ai_predicted_next_questions")
            or []
        )
        if not isinstance(director_script_questions, list):
            director_script_questions = []

        # First-name + org-context are nice-to-haves; missing both
        # is fine, the prompt builder degrades gracefully.
        first_name: str | None = None
        try:
            details = db.v2_get_student_details(user_id) or {}
            full_name = (details.get("name") or "").strip()
            if full_name:
                first_name = full_name.split()[0]
        except Exception:
            pass

        system_prompt = build_state_machine_system_prompt(
            snippet=snippet,
            acoustic_targets=targets,
            director_script_questions=director_script_questions,
            user_first_name=first_name,
            user_org_context=None,
            user_language_hint=user_language_hint,
            coaching_id=coaching_id,
        )

        # Build the LLM's view of the conversation. The system
        # prompt encodes the protocol; the message history tells
        # the model which step we're on.
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
        ]
        prior = coaching.get("messages") or []
        if isinstance(prior, list):
            for m in prior:
                role = (m.get("role") or "").strip()
                content = (m.get("content") or "").strip()
                # 'trial_audio' rows aren't part of the state-machine
                # exchange — they're recordings dropped into the
                # legacy awareness flow. Filter them out so the LLM
                # doesn't see binary placeholders.
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        # On the very first call (no user_message and no prior
        # messages) we still ask the LLM for STEP 1 — the system
        # prompt instructs it to open without waiting for input.
        if user_message:
            messages.append({"role": "user", "content": user_message})

        from services.openai_service import OpenAIService
        service = OpenAIService()
        if not service.client:
            return jsonify({
                "code": "LLM_UNAVAILABLE",
                "error": "Coach LLM not configured",
            }), 503

        try:
            response = service.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.7,
                max_tokens=600,
                response_format={
                    "type": "json_schema",
                    "json_schema": STATE_MACHINE_RESPONSE_SCHEMA,
                },
            )
            raw = response.choices[0].message.content or ""
        except Exception as llm_err:
            logger.error(
                "coaching/state-machine: LLM call failed: %s",
                llm_err, exc_info=True,
            )
            return jsonify({
                "code": "LLM_ERROR",
                "error": "Coach is unavailable. Please try again.",
            }), 502

        parsed = parse_state_machine_response(raw)
        if parsed is None:
            return jsonify({
                "code": "LLM_PARSE_ERROR",
                "error": (
                    "Coach response was malformed. Please send again."
                ),
            }), 502

        # Persist user side first so the admin transcript reads
        # chronologically even if assistant persist fails downstream.
        if user_message:
            try:
                db.append_coaching_message(
                    coaching_id, "user", user_message,
                )
            except Exception as msg_err:
                logger.warning(
                    "coaching/state-machine: user msg append failed: %s",
                    msg_err,
                )

        try:
            db.append_coaching_message(
                coaching_id,
                "assistant",
                parsed.get("narration") or "",
                extra={
                    "step": parsed.get("step"),
                    "current_question_position": parsed.get(
                        "current_question_position"
                    ),
                    "triggers": parsed.get("triggers") or [],
                    "end": bool(parsed.get("end")),
                    "snippet_player": parsed.get("snippet_player"),
                    "label_buttons": parsed.get("label_buttons"),
                    "acoustic_targets": parsed.get("acoustic_targets"),
                    "raw_llm_output": raw,
                },
            )
        except Exception as msg_err:
            logger.warning(
                "coaching/state-machine: assistant msg append failed: %s",
                msg_err,
            )

        # When the LLM flags end=true on STEP 8, advance the
        # coaching_session to 'complete' so subsequent POSTs return
        # COACHING_COMPLETE. Best-effort; the chat already showed
        # the closing card by this point.
        if parsed.get("end") and coaching.get("current_stage") != "complete":
            try:
                db.update_coaching_stage(coaching_id, "complete")
            except Exception as stage_err:
                logger.warning(
                    "coaching/state-machine: stage advance failed: %s",
                    stage_err,
                )

        return jsonify(parsed), 200

    except Exception as e:
        logger.error(
            "coaching/state-machine/turn failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "State machine turn failed",
        }), 500


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

        # B2 gate (defense-in-depth) — refuse to stack a new session
        # on top of one the coach is still reviewing. Frontend should
        # already disable the mic when /v2/chat/session-state returns
        # PENDING_COACH; this is the backstop for stale UI / multiple
        # tabs / API clients bypassing the frontend.
        prior_pending = db.get_pending_review_session_for_user(str(user_id))
        if prior_pending:
            return jsonify({
                "code": "PRIOR_SESSION_PENDING_REVIEW",
                "error": (
                    "Your coach is still reviewing a prior session. "
                    "Wait for those results to publish before recording "
                    "a new one."
                ),
                "pending_session_id": str(prior_pending.get("id")),
            }), 409

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

        # 6.5. Flip the trial v2_session into the admin review queue.
        # The "infinite loop" model wants admin review on every non-
        # onboarding session — trial recordings included — so the
        # standard publish flow happens once per session (admin
        # clicks Publish, results_published_at gets stamped, user
        # gets the email, charisma_profile gets computed, etc.).
        # Here we just (a) make sure the session has a status that
        # the admin Pending Review surface picks up and (b) notify
        # the admin so they know there's something waiting.
        try:
            from services.session_publish import (
                finalize_session_pending_admin_review,
            )
            fp_result = finalize_session_pending_admin_review(
                session_id=trial_session_id,
                user_id=str(user_id),
            )
            logger.info(
                "coaching trial: pending-review sid=%s result=%s",
                trial_session_id, fp_result,
            )
        except Exception as fp_err:
            logger.warning(
                "coaching trial: pending-review handoff failed "
                "sid=%s err=%s", trial_session_id, fp_err,
            )

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

        # Same acoustic-readback pattern as /v2/user/chat/upload-answer
        # — finalize already computed global_*; we surface them inline
        # for the AcousticMetricsBubble.
        acoustic_metrics: dict | None = None
        try:
            sess_row = db.v2_get_session_by_id(trial_session_id) or {}
            acoustic_metrics = {
                "wpm": sess_row.get("global_wpm"),
                "fillers": sess_row.get("global_fillers"),
                "pause_ms": sess_row.get("global_pause_ms"),
                "dynamic_db": sess_row.get("global_dynamic_db"),
                "pitch_center": sess_row.get("global_pitch_center"),
                "energy": sess_row.get("global_energy"),
                "kpi_score": sess_row.get("kpi_score"),
            }
        except Exception as ar_err:
            logger.warning(
                "coaching trial: acoustic readback failed sid=%s err=%s",
                trial_session_id, ar_err,
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
            "session_status": "processing",
            "acoustic_metrics": acoustic_metrics,
        }), 201

    except Exception as e:
        logger.error("coaching/trial-recording failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Trial recording failed"}), 500


@v2_bp.route("/user/chat/upload-answer", methods=["POST"])
@require_auth
def v2_user_chat_upload_answer():
    """Accept a contextual-chat audio response, finalize the session
    for admin review.

    The "Session 2+" upload entry. Two FE flows land here:

      A) Snippet-CTA contextual chat (original use case)
         User finished onboarding → clicked a CTA on a snippet on
         /results → went through the contextual chat opener (POST
         /v2/user/chat/first-question) → now uploads their audio
         response.

      B) Post-labeling continuation (added Phase Single-Slot-Chat)
         User labeled a published snippet (Yes/No on coach_label)
         → read the follow-up question + the personalized intro
         bubble from /v2/coaching/intro-bubble → now records a
         fresh take with the big mic. ``source_snippet_id`` is
         the snippet they JUST labeled, NOT a clicked CTA.

    Both flows are mechanically identical from this endpoint's
    perspective — same multipart body, same v2_session creation,
    same finalize pipeline.

    The previous path (/v2/public/interview/upload-answer) creates
    a guest session and leaves it orphaned; this endpoint creates
    a proper user-bound v2_session and runs it through the same
    finalize pipeline coaching trials use.

    Multipart body
    --------------
      audio_file         REQUIRED. The recorded response (webm/opus
                         expected; the audio_storage helper handles
                         the actual content-type sniffing).
      source_snippet_id  OPTIONAL UUID. The snippet that triggered
                         this upload — the CTA-clicked snippet
                         (flow A) or the just-labeled snippet
                         (flow B). Stored in
                         recordings.source_metadata so admin
                         tooling can trace the continuation chain.
                         Also accepted as ``sourceSnippetId``
                         (camelCase) for legacy FE callers.
      intent             OPTIONAL free-text label. Logged into
                         source_metadata for analytics; no
                         validation. Conventional values include
                         "stress", "charisma", and (for flow B)
                         "post_labeling_continuation".
      question_text      OPTIONAL. The AI-generated opening
                         question the user was responding to.
                         Logged for traceability.

    Success response (201)
    ----------------------
        {
          "status":            "ok",
          "session_id":        <uuid str>,
          "recording_id":      <uuid str>,
          "session_status":    "processing",
          "acoustic_metrics":  {
            "wpm": float|null, "fillers": int|null,
            "pause_ms": int|null, "dynamic_db": float|null,
            "pitch_center": float|null, "energy": float|null,
            "kpi_score": float|null
          },
          "finalize":          { ... pending_admin_review summary ... }
        }

    The FE renders ``session_status`` directly; "processing" tells
    the user their take is being reviewed. ``acoustic_metrics`` is
    the 30-second readback the dashboard uses while the user waits
    on admin publish.

    Error responses
    ---------------
      400 INVALID_INPUT             missing audio_file
      400 AUDIO_READ_FAILED         couldn't read multipart blob
      400 AUDIO_EMPTY               empty audio payload
      409 PRIOR_SESSION_PENDING_REVIEW   B2 gate — user has another
                                         session the coach hasn't
                                         published yet. Includes
                                         ``pending_session_id`` in
                                         the body so the FE can
                                         link the user back to it.
      500 RECORDING_CREATE_FAILED   DB insert failed
      500 V2_ERROR                  catch-all
      502 STORAGE_ERROR             R2 / audio bucket failure

    Side effects on success
    -----------------------
      - audio uploaded to the audio bucket
        (contextual_chat/<user_id>/<recording_id>.webm)
      - new v2_sessions row bound to request.user_id
      - new recordings row with recording_origin='contextual_chat'
        and source_metadata containing source_snippet_id + intent +
        question_text when provided
      - recording-1 metrics job enqueued
      - extract_recording_snippets runs (snippets land back on
        /results once admin publishes)
      - session handed to finalize_session_pending_admin_review:
        global metrics + B6 KPI, AI draft prefill, status flip to
        'pending_admin_review', admin notification email

    Why no auto-publish
    -------------------
    The "infinite loop" UX is that admin reviews every non-
    onboarding session. The user stays on the waiting screen
    (/user/results/<id> returns status='processing' while
    results_published_at IS NULL) until the admin clicks Publish.
    """
    import uuid as _uuid
    from services.recording_1_job import enqueue_recording_1_job

    try:
        audio = request.files.get("audio_file")
        if not audio:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "audio_file is required",
            }), 400

        user_id = request.user_id
        source_snippet_id = (
            request.form.get("source_snippet_id")
            or request.form.get("sourceSnippetId")
            or ""
        ).strip() or None
        intent = (request.form.get("intent") or "").strip().lower() or None
        question_text = (request.form.get("question_text") or "").strip() or None

        # B2 gate (defense-in-depth) — refuse to stack a new contextual
        # chat session on top of one the coach is still reviewing.
        # Same rule + response code as the coaching/trial-recording
        # endpoint so the frontend can branch on a single code.
        prior_pending = db.get_pending_review_session_for_user(str(user_id))
        if prior_pending:
            return jsonify({
                "code": "PRIOR_SESSION_PENDING_REVIEW",
                "error": (
                    "Your coach is still reviewing a prior session. "
                    "Wait for those results to publish before "
                    "starting a new conversation."
                ),
                "pending_session_id": str(prior_pending.get("id")),
            }), 409

        # 1. Upload audio — same bucket helper trial-recording uses.
        try:
            file_bytes = audio.read()
        except Exception:
            return jsonify({
                "code": "AUDIO_READ_FAILED",
                "error": "Could not read audio",
            }), 400
        if not file_bytes:
            return jsonify({
                "code": "AUDIO_EMPTY",
                "error": "Empty audio payload",
            }), 400

        recording_id = str(_uuid.uuid4())
        # Contextual chat audio lives under its own prefix so the
        # admin queue can tell them apart from baselines and trials
        # at a glance (and so future analytics queries can group by
        # origin without joining recordings).
        storage_path = (
            f"contextual_chat/{user_id}/{recording_id}.webm"
        )
        content_type = (
            audio.mimetype or "audio/webm"
        ).strip() or "audio/webm"
        try:
            from services.audio_storage import put_audio_bytes
            put_audio_bytes(
                storage_path, file_bytes, content_type=content_type,
            )
        except Exception as upload_err:
            logger.error(
                "chat/upload-answer: storage failed: %s",
                upload_err, exc_info=True,
            )
            return jsonify({
                "code": "STORAGE_ERROR",
                "error": "Failed to store audio",
            }), 502

        # 2. Create the v2_session bound to this user.
        chat_session = db.v2_create_session(user_id)
        if not chat_session:
            return jsonify({
                "code": "V2_ERROR",
                "error": "Failed to create session",
            }), 500
        chat_session_id = str(chat_session.get("id"))

        # 3. Create the recordings row. The 'contextual_chat'
        # origin is also a safety filter — the backfill script
        # only acts on coaching_trial, so a half-broken contextual
        # session can't get accidentally auto-published.
        recording_payload = {
            "id": recording_id,
            "user_id": user_id,
            "session_v2_id": chat_session_id,
            "storage_path": storage_path,
            "audio_url": "",
            "duration": 0,
            "recording_origin": "contextual_chat",
        }
        if source_snippet_id:
            # Tucked into the JSONB source_metadata column so admins
            # reviewing the new session can trace which prior snippet
            # the user was responding to.
            recording_payload["source_metadata"] = {
                "source_snippet_id": source_snippet_id,
                "intent": intent,
                "question_text": question_text,
            }
        try:
            db.create_recording(recording_payload)
        except Exception as create_err:
            err_low = str(create_err).lower()
            if (
                "recording_origin" in err_low
                or "source_metadata" in err_low
                or "pgrst204" in err_low
            ):
                fallback = {
                    k: v for k, v in recording_payload.items()
                    if k not in ("recording_origin", "source_metadata")
                }
                db.create_recording(fallback)
            else:
                logger.error(
                    "chat/upload-answer: create_recording failed: %s",
                    create_err, exc_info=True,
                )
                return jsonify({
                    "code": "RECORDING_CREATE_FAILED",
                    "error": "Failed to create recording",
                }), 500

        # 4. Bind the recording to the session + set the lifecycle
        # state recording-1 job uses to drive metrics analysis.
        try:
            db.v2_update_session(chat_session_id, user_id, {
                "recording_1_id": recording_id,
                "status": "completing_from_recording_1",
                "recording_1_processing_status": "pending",
                "self_rating_submitted_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as link_err:
            logger.warning(
                "chat/upload-answer: session link failed (non-fatal): %s",
                link_err,
            )

        # 5. Kick off metrics + snippet extraction. Same pattern as
        # trial-recording: enqueue the metrics job (async) AND run
        # extract synchronously so the snippets exist by the time
        # finalize_session_pending_admin_review runs.
        try:
            enqueue_recording_1_job(
                chat_session_id, recording_id, storage_path, user_id, None,
            )
        except Exception as q_err:
            logger.warning(
                "chat/upload-answer: enqueue failed: %s", q_err, exc_info=True,
            )
        try:
            from services.snippet_extraction import extract_recording_snippets
            extract_recording_snippets(
                session_id=chat_session_id,
                user_id=str(user_id),
                recording_id=recording_id,
                recording_path=storage_path,
                duration_seconds=None,
            )
        except Exception as snippet_err:
            logger.warning(
                "chat/upload-answer: extract failed: %s", snippet_err,
            )

        # 6. Finalize — same helper trial-recording calls. Computes
        # global metrics + B6 KPI, generates AI draft comments,
        # flips status to pending_admin_review, sends the admin
        # notification email.
        finalize_summary: dict | None = None
        try:
            from services.session_publish import (
                finalize_session_pending_admin_review,
            )
            finalize_summary = finalize_session_pending_admin_review(
                session_id=chat_session_id,
                user_id=str(user_id),
            )
        except Exception as fp_err:
            logger.warning(
                "chat/upload-answer: finalize handoff failed sid=%s err=%s",
                chat_session_id, fp_err,
            )

        # Re-read the session row to surface the freshly-computed
        # acoustic metrics inline. finalize_session_pending_admin_review
        # called compute_session_global_metrics in its first step,
        # so the global_* columns are already populated and this is
        # a cheap one-row select. The frontend uses these to render
        # the AcousticMetricsBubble at the 30-second mark while the
        # session sits in admin review.
        acoustic_metrics: dict | None = None
        try:
            session_row = db.v2_get_session_by_id(chat_session_id) or {}
            acoustic_metrics = {
                "wpm": session_row.get("global_wpm"),
                "fillers": session_row.get("global_fillers"),
                "pause_ms": session_row.get("global_pause_ms"),
                "dynamic_db": session_row.get("global_dynamic_db"),
                "pitch_center": session_row.get("global_pitch_center"),
                "energy": session_row.get("global_energy"),
                "kpi_score": session_row.get("kpi_score"),
            }
        except Exception as ar_err:
            logger.warning(
                "chat/upload-answer: acoustic readback failed sid=%s err=%s",
                chat_session_id, ar_err,
            )

        logger.info(
            "chat/upload-answer: ok user_id=%s session_id=%s "
            "source_snippet=%s intent=%s",
            user_id, chat_session_id, source_snippet_id, intent,
        )
        return jsonify({
            "status": "ok",
            "session_id": chat_session_id,
            "recording_id": recording_id,
            "session_status": "processing",
            "acoustic_metrics": acoustic_metrics,
            "finalize": finalize_summary,
        }), 201

    except Exception as e:
        logger.error(
            "chat/upload-answer: failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Contextual chat upload failed",
        }), 500


@v2_bp.route("/user/chat/first-question", methods=["POST"])
@require_auth
def v2_user_chat_first_question():
    """Start a contextual chat by generating the first AI question.

    Query params (any one spelling accepted, see comment below):
      - sourceSnippetId / sourceSnippet / source_snippet_id  (UUID)
      - intent: charisma|stress
    """
    try:
        user_id = request.user_id
        # Defensive param read: the frontend /chat page URL has used
        # `sourceSnippet` while the backend canonical name is
        # `sourceSnippetId`. A mismatch causes the contextual init
        # to silently fall through to the cold-start interview path
        # ("Are you good at math?"). Accept all three spellings so a
        # one-side-only deploy can never reintroduce that bug —
        # whichever key the BFF forwards, we resolve it.
        source_snippet_id = (
            request.args.get("sourceSnippetId")
            or request.args.get("sourceSnippet")
            or request.args.get("source_snippet_id")
            or ""
        ).strip() or None
        intent = (request.args.get("intent") or "").strip().lower() or None

        # ── Admin overrides (priority order) ────────────────────────
        # 1) coaching_directives_queue — new user-level 5-step arc.
        #    Pop the lowest-position un-exhausted row, mark exhausted.
        #    Wins over contextual snippet flow, stored follow-up, and
        #    the dynamic LLM. Phase Directives-Queue (BE).
        #
        # Legacy queued_override_question (single-question override
        # via PUT /v2/admin/user/<id>/context) was removed in the
        # Week-1 cleanup. The directives-queue is the single admin
        # override path now. Old data in user_settings.queued_
        # override_question persists in the DB but is ignored.
        directive = db.pop_next_directive(user_id)
        if directive:
            logger.info(
                "first-question: directives-queue HIT user=%s pos=%s "
                "intent=%s",
                user_id, directive.get("position"),
                directive.get("intent_tag"),
            )
            return jsonify({
                "status": "ok",
                "question": directive.get("question"),
                "source": "directives_queue",
                "directive": {
                    "position": directive.get("position"),
                    "intent_tag": directive.get("intent_tag"),
                },
            }), 200

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

            # No pre-stored question → fall back to dynamic LLM generation.
            #
            # Gate alignment fix: the publish gate
            # (v2_get_results_snippets_for_session) requires only
            # admin_comment NOT NULL — transcript is optional there.
            # If we hard-fail here on missing transcript we break the
            # CTA on snippets that the admin legitimately published
            # (e.g. when Whisper missed a 5s slice). Soften: require
            # only admin_comment. The LLM still has the coach insight
            # to anchor on; transcript is forwarded as empty and the
            # base prompt handles that case.
            transcript = (
                (snippet.get("transcript") or "")
                or (snippet.get("transcription_text") or "")
                or (snippet.get("transcript_text") or "")
                or (snippet.get("transcript_excerpt") or "")
            ).strip()
            admin_comment = (snippet.get("admin_comment") or "").strip()
            if not admin_comment:
                return jsonify({
                    "code": "SNIPPET_CONTEXT_UNAVAILABLE",
                    "error": "Snippet admin_comment is not available yet",
                }), 422
            if not transcript:
                logger.info(
                    "first-question: snippet has no transcript, proceeding "
                    "with admin_comment only snippet=%s user=%s",
                    source_snippet_id, user_id,
                )

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

        # Gate for the self-rating prompt — frontend reads this and
        # decides whether to render the "rate yourself 1-10" UI for
        # this snippet. Rule: ask AT MOST once per attempt. If the
        # most recent attempt already carries a self_rating, the
        # user has answered for this scenario and we silently skip
        # the prompt on subsequent reads.
        #
        # When there are zero attempts yet (the eval daemon hasn't
        # written one) we also return False so the frontend doesn't
        # flash the rating UI before the user has even completed the
        # exchange. The natural moment to ask is *after* the first
        # post-attempt poll returns a row.
        requires_self_score = False
        if attempt_payload:
            latest = max(
                attempt_payload,
                key=lambda a: a.get("attempt_number") or 0,
            )
            requires_self_score = latest.get("self_rating") is None

        return jsonify({
            "snippet_id": snippet_id,
            "attempts": attempt_payload,
            "delta": delta,
            "requires_self_score": requires_self_score,
        }), 200

    except Exception as e:
        logger.error("user/coaching/progress failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to load coaching progress",
        }), 500


# Capture the FIRST 1-10 number in a string, accepting EITHER a
# digit ("8", "10") OR a spelled-out word ("eight", "ten"). Whisper
# sometimes transcribes a spoken "8" as the word "eight" so we have
# to cover both to avoid a brittle UX where the user has to repeat
# themselves. Order in the alternation matters:
#   - "10" first so "8 out of 10" doesn't match "10" inside it
#     (actually word-boundary handles that, but defence-in-depth)
#   - Word numbers after digits so digit-only inputs ("8") parse
#     via the cheap branch
# The capture group is the matched token; resolution to an int
# happens in _parse_self_rating_from_text.
_SELF_RATING_RE = re.compile(
    r"\b(10|[1-9]|one|two|three|four|five|six|seven|eight|nine|ten)\b",
    re.IGNORECASE,
)
_SELF_RATING_WORD_MAP: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
# Phase 8 self-rating: bound the free-text payload so an abusive
# client can't ship megabytes through the endpoint. The frontend
# input is the chat composer (typically <200 chars).
_SELF_RATING_TEXT_MAX = 500


def _parse_self_rating_from_text(text: str) -> int | None:
    """Pull a 1..10 integer out of a free-form user reply.

    Accepts digits ("8", "10") and English number words ("eight",
    "ten") case-insensitively. Returns the FIRST 1-10 number found,
    or None when nothing matches.

    Examples:
      "8"              → 8
      "I'd say 8"      → 8
      "9/10"           → 9
      "eight"          → 8
      "TEN"            → 10
      "8 out of 10"    → 8
      "11"             → None (digit out of range; word_boundary kills it)
      "ten and a half" → 10
      ""               → None
    """
    if not text:
        return None
    m = _SELF_RATING_RE.search(text)
    if not m:
        return None
    token = m.group(1).strip().lower()
    if token in _SELF_RATING_WORD_MAP:
        return _SELF_RATING_WORD_MAP[token]
    try:
        n = int(token)
        return n if 1 <= n <= 10 else None
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


@v2_bp.route("/user/sessions/<session_id>/charisma-profile", methods=["GET"])
@require_auth
def v2_user_session_charisma_profile(session_id):
    """Charisma Awareness Dashboard payload for one session.

    Owner-scoped — only the user the session belongs to can read.
    Pure aggregation over data already on disk (no LLM call), so
    response latency is bounded by Supabase round-trips.

    Response shape (every key always present; nested objects
    shape-complete even when underlying data is sparse)::

        {
          "archetype": "The Visionary",          # str — derived from trinity
          "narrative": "...",                    # str — mirror.narrative or fallback
          "acoustics": {
            "pace": 135.0,                        # WPM (float) or null
            "idealMin": 125,
            "idealMax": 140,
            "peakTopic": "Leadership",            # stickiness_top_topic
            "timeline": [{ "t": "0:00", "wpm": 120.0 }, ...]
          },
          "trinity": {
            "power":    0.85,
            "warmth":   0.40,
            "presence": 0.75,
            "insight":  "Your authoritative profile is heavy on Power..."
          },
          "triggers": {
            "topTheme":         "Leadership",
            "pitchDelta":       "+3.2st",
            "fillerMultiplier": "2.0x",
            "points": [{ "t": 20, "intensity": 0.3 }, ...]
          },
          "recommendation": {
            "title": "Ready for your next stress-test?",
            "body":  "Your visionary profile is strong, but..."
          }
        }

    Responses:
      200 { "session_id": "...", "charisma_profile": {...} }
      400 INVALID_INPUT — bad UUID
      404 SESSION_NOT_FOUND — session doesn't exist or isn't owned
      500 V2_ERROR — unexpected
    """
    try:
        if not _is_valid_uuid(session_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "session_id must be a valid UUID",
            }), 400

        user_id = request.user_id

        # Owner-scoped load. v2_get_session_by_id returns the row
        # regardless of owner so we verify here.
        session = db.v2_get_session_by_id(session_id)
        if not session or str(session.get("user_id") or "") != str(user_id):
            return jsonify({
                "code": "SESSION_NOT_FOUND",
                "error": "Session not found",
            }), 404

        # Pure cache read. The blob was computed and persisted at
        # session-publish + admin compute-metrics — no live compute
        # here so the dashboard load is bounded by a single
        # Supabase select. NULL when the session pre-dates the
        # column or was too sparse to compute; frontend treats
        # NULL as "hide the dashboard".
        profile_payload = session.get("charisma_profile")

        return jsonify({
            "session_id": session_id,
            "charisma_profile": profile_payload,
        }), 200

    except Exception as e:
        logger.error(
            "user/sessions/<id>/charisma-profile failed: %s",
            e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to build charisma profile",
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


@v2_bp.route("/user/mirror", methods=["DELETE"])
@require_auth
def v2_user_mirror_delete():
    """Clear the requesting user's current learner mirror.

    Owner-scoped; the auth-required decorator already binds
    ``request.user_id``. Calls ``db.set_user_current_learner_mirror
    (user_id, None)`` which the helper already supports (passing
    ``None`` clears the column).

    Why: lets the user opt out of a cached reflection they don't
    want lingering on their results page. The next click of
    Regenerate writes a fresh mirror with whatever the current
    prompt + data produce, so this is also the "force re-prompt"
    button when we've shipped prompt changes and want users to see
    the new output without waiting for organic regeneration.

    Response (200)::

        { "status": "ok", "mirror": null }
    """
    try:
        user_id = request.user_id
        db.set_user_current_learner_mirror(user_id, None)
        return jsonify({"status": "ok", "mirror": None}), 200
    except Exception as e:
        logger.error(
            "user/mirror DELETE failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to delete mirror",
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


@v2_bp.route("/chat/session-state", methods=["GET"])
@require_auth
def v2_chat_session_state():
    """Drive the /chat route's UI state for a returning user.

    The frontend killed the /results page; /chat is now the
    single destination after onboarding. This endpoint tells it
    what mode to render in.

    State machine::

        NO_SESSION     — user has no v2_sessions row at all (fresh
                          signup, never recorded). Frontend should
                          route them into the onboarding interview.

        PENDING_COACH  — latest session exists but
                          results_published_at IS NULL (admin
                          hasn't reviewed + published yet).
                          Frontend renders the waiting / FAQ chat;
                          POST /v2/chat/query is fully usable
                          against the Master Document in this
                          state.

        REVIEW_LOOP    — latest session has been published. Payload
                          includes the snippets + admin_comments
                          so the frontend can drop straight into
                          the snippet-review chat without a second
                          round-trip to /v2/user/results/<id>.

    Response (200)::

        {
          "state": "NO_SESSION" | "PENDING_COACH" | "REVIEW_LOOP",
          "session_id": "<uuid>" | null,
          "created_at": "<iso8601>" | null,
          "results_published_at": "<iso8601>" | null,

          // present iff state == "REVIEW_LOOP"
          "snippets":         [ ... full snippet objects, see below ],
          "kpi_score":        number | null,
          "charisma_profile": { ... } | null,
          "ai_summary":       string | null
        }

    Each REVIEW_LOOP snippet matches the shape /user/results/<id>
    returns so the frontend can reuse its existing renderer
    without a second translation layer.

    Why a separate endpoint when /user/sessions/current exists:
    /sessions/current emits the legacy 5-status vocabulary
    (no_session / processing / pending_review / completed /
    error). The frontend's /chat router wants the new
    3-state vocabulary explicitly + the snippet payload inline.
    We could overload /sessions/current, but doing that risks
    breaking the homework + admin routing surfaces that read
    its current shape. A dedicated endpoint is cheaper.
    """
    try:
        user_id = request.user_id
        session = db.v2_get_latest_session_for_user(user_id)

        if not session:
            return jsonify({
                "state": "NO_SESSION",
                "session_id": None,
                "created_at": None,
                "results_published_at": None,
            }), 200

        session_id = str(session.get("id"))
        published_at = session.get("results_published_at")
        base = {
            "session_id": session_id,
            "created_at": session.get("created_at"),
            "results_published_at": published_at,
        }

        if not published_at:
            # Admin hasn't clicked Publish yet. The /v2/chat/query
            # endpoint is the right surface for the user to ask
            # questions while they wait — same Master-Document
            # grounding, no special-casing needed here.
            return jsonify({"state": "PENDING_COACH", **base}), 200

        # REVIEW_LOOP — load published snippets in the same shape
        # /user/results/<id> uses, so the frontend renderer is
        # reusable. We resolve audio URLs the same way too: the
        # admin Files tab, the /results page, and this endpoint all
        # serve the same playable URL.
        try:
            raw_snippets = db.v2_get_results_snippets_for_session(
                session_id, user_id,
            ) or []
        except Exception as snip_err:
            logger.warning(
                "chat/session-state: snippet load failed sid=%s err=%s",
                session_id, snip_err,
            )
            raw_snippets = []

        snippets = [
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
            for s in raw_snippets
        ]

        return jsonify({
            "state": "REVIEW_LOOP",
            **base,
            "snippets": snippets,
            "kpi_score": session.get("kpi_score"),
            "charisma_profile": session.get("charisma_profile"),
            "ai_summary": session.get("ai_task_alignment_comment"),
        }), 200

    except Exception as e:
        logger.error(
            "chat/session-state failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to evaluate session state",
        }), 500


@v2_bp.route("/chat/query", methods=["POST"])
@require_auth
def v2_chat_query():
    """Unified chat orchestrator for the /chat page.

    Powers the post-signup single-thread chat surface. The LLM
    runs under services.master_doc_rag with the verbatim Master
    Document as its only source of truth, plus capability-boundary
    + upload-intent rules. Returns structured output the frontend
    uses to drive UI state (showing/hiding the upload dropzone).

    Body::

        {
          "question": "what is this?",
          "history":  [                          // optional
            { "role": "user",      "content": "..." },
            { "role": "assistant", "content": "..." }
          ]
        }

    Responses::

        200 {
              "answer":         str,    # the chat bubble text
              "show_upload_ui": bool,   # per-turn upload affordance
                                         # toggle (RULE G)
              "show_record_ui": bool,   # per-turn record affordance
                                         # toggle (RULE I) — in-app
                                         # mic, distinct from upload
              "debug":          {...}   # model + history_used / error
            }
        400 INVALID_INPUT — question missing or not a string
        500 V2_ERROR

    show_upload_ui / show_record_ui semantics:
      • show_upload_ui — TRUE on the turn where the user expressed
        intent to upload an existing file ("can I send a file?",
        "I want to upload my recording", etc.). RULE G.
      • show_record_ui — TRUE on the turn where the user expressed
        intent to RECORD in-app via the chat's mic ("can I record
        here?", "let me just record it", etc.). RULE I.
      • Mutually exclusive — at most ONE is TRUE on any turn.
      • Per-turn signals — frontend must NOT cache them across
        turns; each answer carries the current state.

    Why @require_auth: the spec says this is the "after signup"
    surface. Pre-signup users get the on-rails interview flow;
    once they sign up they can ask freeform questions and we want
    the request to carry their identity for future per-user
    analytics on which topics get asked. Anonymous probing of
    the Q&A is out-of-scope for v1.

    ─────────────────────────────────────────────────────────────────
    Phase Stress-Contrast (BE-3) — dual-mode body parsing
    ─────────────────────────────────────────────────────────────────
    This endpoint additively supports a ``multipart/form-data`` body
    when the frontend captures audio alongside the typed/dictated
    question. Path A (text → LLM) is unchanged. Path B (audio → DSP)
    fires asynchronously via ``casual_voice_analytics`` and never
    blocks the HTTP response.

    Multipart fields (all when Path B applies):
      - question:              str (required; same semantics as JSON)
      - history:               JSON-stringified list (optional)
      - audio_file:            webm/opus blob (required for Path B)
      - transcript_source:     "web_speech" | "server_whisper"
                                (default "web_speech")
      - audio_duration_sec:    float hint (optional)

    JSON callers (the existing path) keep the exact same request
    and response shape — no regression.
    """
    try:
        # ── Body parsing — branch on content-type so existing JSON
        # callers keep working unchanged (compatibility contract C1
        # from BE-3 prompt). Multipart adds the audio side without
        # touching the JSON code path.
        content_type = (request.content_type or "").lower()
        is_multipart = "multipart/form-data" in content_type

        audio_bytes: bytes | None = None
        transcript_source = "web_speech"
        audio_duration_sec: float = 0.0

        if is_multipart:
            question = (request.form.get("question") or "").strip()
            history_raw = request.form.get("history")
            history: list | None = None
            if history_raw:
                try:
                    import json as _json
                    parsed = _json.loads(history_raw)
                    if isinstance(parsed, list):
                        history = parsed
                except Exception:
                    # Same leniency as the JSON path — bad history
                    # never breaks the answer.
                    history = None

            audio_file = request.files.get("audio_file")
            if audio_file is not None:
                try:
                    audio_bytes = audio_file.read()
                except Exception as read_err:
                    logger.warning(
                        "chat/query: audio read failed user=%s err=%s "
                        "— continuing text-only",
                        request.user_id, read_err,
                    )
                    audio_bytes = None

                ts_raw = (
                    request.form.get("transcript_source") or ""
                ).strip().lower()
                if ts_raw in ("web_speech", "server_whisper"):
                    transcript_source = ts_raw

                try:
                    audio_duration_sec = float(
                        request.form.get("audio_duration_sec") or "0"
                    )
                except (TypeError, ValueError):
                    audio_duration_sec = 0.0
        else:
            body = request.get_json(silent=True) or {}
            question = body.get("question")
            history = body.get("history")
            if history is not None and not isinstance(history, list):
                history = None

        if not isinstance(question, str) or not question.strip():
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "question must be a non-empty string",
            }), 400

        # ── Path A — LLM answer (the only thing the HTTP response
        # carries back). Unchanged from the pre-BE-3 behavior.
        from services.master_doc_rag import answer_question
        payload, debug = answer_question(question.strip(), history=history)

        # ── Path B — fire-and-forget DSP extraction. Spawned BEFORE
        # the jsonify so the daemon's stack frame exists by the time
        # the request worker recycles, but AFTER Path A so we never
        # delay the LLM. The dispatch itself is a thread.start() —
        # microseconds; safe to do before returning. Failure to
        # dispatch is logged and swallowed; the LLM answer still
        # ships.
        if audio_bytes:
            try:
                from services.casual_voice_analytics import (
                    analyze_casual_audio_async,
                )
                analyze_casual_audio_async(
                    user_id=str(request.user_id),
                    # session_id is None for pure Lounge chat — the
                    # endpoint isn't session-bound. The column on
                    # casual_voice_benchmarks is nullable for this
                    # exact reason; see migration comment.
                    session_id=None,
                    audio_bytes=audio_bytes,
                    transcript=question.strip(),
                    duration_sec=audio_duration_sec,
                    transcript_source=transcript_source,
                )
            except Exception as cv_err:
                # The dispatcher should never raise (it's just a
                # thread.start), but defense-in-depth: a broken
                # casual-voice path MUST NOT take down the chat
                # response. Log and move on.
                logger.warning(
                    "chat/query: casual_voice dispatch failed "
                    "user=%s err=%s (non-fatal — LLM answer still "
                    "returned)",
                    request.user_id, cv_err,
                )

        return jsonify({
            "answer": payload.get("answer", ""),
            "show_upload_ui": bool(payload.get("show_upload_ui", False)),
            "show_record_ui": bool(payload.get("show_record_ui", False)),
            "debug": debug,
        }), 200

    except Exception as e:
        logger.error("chat/query failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Chat query failed",
        }), 500


@v2_bp.route("/user/upload-media", methods=["POST"])
@require_auth
def v2_user_upload_media():
    """Accept a user-uploaded media file (audio OR video), stream
    to Cloudflare R2, persist metadata, hand off to the standard
    admin-review finalize.

    Multipart body:
      - file:        the bytes (required). Field name 'file' is the
                     canonical name; we also accept 'audio_file' /
                     'video_file' / 'media' as aliases so frontend
                     code that came in from the recording endpoints
                     doesn't have to be renamed.
      - session_id:  the v2_sessions row this upload belongs to
                     (optional — null is allowed but means the
                     file won't trigger an admin-review flow).
      - filename:    optional override for the user-facing file
                     name; falls back to the multipart filename.

    Side effects on success:
      - bytes uploaded to R2 (user-media bucket) at
        users/<user_id>/sessions/<session_id>/<filename>
      - user_uploaded_files row written
      - if session_id was passed: session status flipped to
        "pending_admin_review" + admin notification email
        dispatched via the standard finalize helper

    Response (201)::

        {
          "status": "ok",
          "file": {
            "id": "<uuid>",
            "file_name": "<original>",
            "file_type": "audio" | "video",
            "content_type": "video/mp4",
            "size_bytes": 12345678,
            "r2_url": "https://.../users/.../filename.mp4" | null,
            "playback_url": "<public OR signed URL the admin UI can stream>",
            "session_id": "<uuid>" | null,
            "created_at": "<iso8601>"
          },
          "finalize": {...} | null   // present iff session_id was bound
        }

    Why we treat this like a recording-turn finalize: the
    frontend's "video waiting screen" is gated on a session being
    in pending_admin_review status and on the admin email having
    been dispatched. Mirroring the trial-recording handoff means
    files behave the same as live recordings from the user's
    perspective — same flywheel.
    """
    import uuid as _uuid
    from services.user_media_storage import (
        put_user_media_bytes,
        user_media_public_url,
        user_media_bucket_name,
        guess_media_content_type,
        classify_media_kind,
    )

    try:
        upload = (
            request.files.get("file")
            or request.files.get("media")
            or request.files.get("audio_file")
            or request.files.get("video_file")
        )
        if not upload:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "file is required (multipart field 'file')",
            }), 400

        # Read bytes once. We accept memory-based reads because the
        # frontend's MediaRecorder upper bound + the route's
        # MAX_USER_MEDIA_SIZE_MB cap keep us well under any
        # workable streaming threshold.
        try:
            file_bytes = upload.read()
        except Exception:
            return jsonify({
                "code": "FILE_READ_FAILED",
                "error": "Could not read upload",
            }), 400
        if not file_bytes:
            return jsonify({
                "code": "FILE_EMPTY",
                "error": "Empty upload payload",
            }), 400

        size_bytes = len(file_bytes)
        max_mb = int(getattr(config, "MAX_USER_MEDIA_SIZE_MB", 200) or 200)
        if size_bytes > max_mb * 1024 * 1024:
            return jsonify({
                "code": "FILE_TOO_LARGE",
                "error": f"Upload exceeds {max_mb} MB limit",
            }), 413

        # File-name resolution: explicit form override → multipart
        # filename → generic 'upload'. We sanitise via secure_filename
        # so a hostile filename can't escape the R2 prefix.
        raw_name = (
            (request.form.get("filename") or "").strip()
            or (upload.filename or "").strip()
            or "upload"
        )
        safe_name = secure_filename(raw_name) or "upload"

        # Content type — prefer the multipart's, fall back to a
        # guess off the filename so an iOS upload that ships
        # application/octet-stream still gets classified.
        content_type = (upload.mimetype or "").strip().lower()
        if not content_type or content_type == "application/octet-stream":
            content_type = guess_media_content_type(safe_name)
        kind = classify_media_kind(content_type)
        if kind is None:
            return jsonify({
                "code": "UNSUPPORTED_MEDIA_TYPE",
                "error": (
                    "Only audio/* and video/* uploads are supported "
                    f"(got {content_type or 'unknown'})"
                ),
            }), 415

        # Session binding. We accept missing session_id (the chat
        # might upload outside a session context in future), but
        # if one is passed we verify ownership before threading it
        # through — a user must not be able to attach files to
        # someone else's session by guessing UUIDs.
        user_id = request.user_id
        session_id_raw = (
            request.form.get("session_id")
            or request.form.get("sessionId")
            or ""
        ).strip() or None
        session_id: str | None = None
        if session_id_raw:
            if not _is_valid_uuid(session_id_raw):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "session_id must be a valid UUID",
                }), 400
            try:
                session_row = db.v2_get_session_by_id(session_id_raw) or {}
            except Exception:
                session_row = {}
            if not session_row or str(session_row.get("user_id") or "") != str(user_id):
                return jsonify({
                    "code": "SESSION_NOT_FOUND",
                    "error": "Session not found for this user",
                }), 404
            session_id = session_id_raw

        # R2 key shape — exactly the path the spec asked for. The
        # uuid suffix on the filename prevents collisions when a
        # user uploads "video.mp4" three times to the same session.
        path_session = session_id or "no-session"
        r2_key = (
            f"users/{user_id}/sessions/{path_session}/"
            f"{_uuid.uuid4().hex[:8]}_{safe_name}"
        )

        try:
            bucket = put_user_media_bytes(
                key=r2_key, body=file_bytes, content_type=content_type,
            )
        except Exception as up_err:
            logger.error(
                "user/upload-media: R2 upload failed key=%s err=%s",
                r2_key, up_err, exc_info=True,
            )
            sentry_sdk.capture_exception(up_err)
            return jsonify({
                "code": "STORAGE_ERROR",
                "error": "Upload to media bucket failed",
            }), 502

        # Public URL cached when the bucket is public. For private
        # buckets we leave r2_url=NULL and let the admin endpoint
        # mint a signed URL on read.
        public_url = user_media_public_url(r2_key)

        row = db.create_user_uploaded_file(
            user_id=str(user_id),
            session_id=session_id,
            r2_bucket=bucket,
            r2_key=r2_key,
            r2_url=public_url,
            file_name=safe_name,
            file_type=kind,
            content_type=content_type,
            file_size_bytes=size_bytes,
        )
        if not row:
            logger.error(
                "user/upload-media: DB insert returned None "
                "user=%s key=%s", user_id, r2_key,
            )
            return jsonify({
                "code": "DB_ERROR",
                "error": "Upload succeeded but metadata write failed",
            }), 500

        # Treat the file like a completed live recording: flip the
        # session into the admin review queue + dispatch the
        # "New Session Awaiting Review" email. Failure-isolated;
        # the upload still succeeds and the file is queryable in
        # the admin Files tab even if the email send blips.
        finalize_summary: dict | None = None
        if session_id:
            try:
                from services.session_publish import (
                    finalize_session_pending_admin_review,
                )
                finalize_summary = finalize_session_pending_admin_review(
                    session_id=session_id, user_id=str(user_id),
                )
            except Exception as fp_err:
                logger.warning(
                    "user/upload-media: finalize handoff failed "
                    "sid=%s err=%s", session_id, fp_err,
                )

        # The playback_url is what the frontend will actually use
        # to render an <audio>/<video> element right now. Public
        # URL wins; signed URL is the fallback. Always populated
        # on a successful response — if both came back null the
        # admin endpoint will still resolve it later, but we may
        # as well hand the freshest one over now.
        playback_url = public_url
        if not playback_url:
            from services.user_media_storage import presigned_get_user_media
            playback_url = presigned_get_user_media(r2_key)

        return jsonify({
            "status": "ok",
            "file": {
                "id": row.get("id"),
                "file_name": row.get("file_name"),
                "file_type": row.get("file_type"),
                "content_type": row.get("content_type"),
                "size_bytes": row.get("file_size_bytes"),
                "r2_url": row.get("r2_url"),
                "playback_url": playback_url,
                "session_id": row.get("session_id"),
                "created_at": row.get("created_at"),
            },
            "finalize": finalize_summary,
        }), 201

    except Exception as e:
        logger.error("user/upload-media failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Media upload failed",
        }), 500


@v2_bp.route("/user/snippets/<snippet_id>/label", methods=["POST"])
@require_auth
def v2_user_snippet_label(snippet_id):
    """Capture the user's self-confirmation of a snippet's
    charismatic read (the chat state machine's "Would you label
    your voice here as Charismatic? Yes / No" beat).

    RLHF signal. Paired with ``coach_label`` (admin annotation),
    the (admin, user) tuple is the training pair we export later:
    when the user disagrees with the admin, that's the moment the
    classifier most needs to learn from.

    Body::

        { "label": true | false }
        // OR, equivalent alias for symmetry with the sibling
        // /v2/chat/snippet-followup endpoint:
        { "user_label": true | false }
        // If BOTH keys are present, ``label`` wins (canonical).

    Responses::

        200 { "status": "ok", "snippet_id": ..., "user_charisma_label": ... }
        400 INVALID_INPUT — bad UUID / non-bool label / both keys missing
        404 NOT_FOUND     — snippet doesn't exist or isn't owned by
                            this user
        500 V2_ERROR

    Owner-scoped at both the route level (require_auth + the
    db.set_user_snippet_charisma_label filter on user_id) so a
    user can't write to someone else's row even if they guess the
    snippet UUID.
    """
    try:
        if not _is_valid_uuid(snippet_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "snippet_id must be a valid UUID",
            }), 400

        body = request.get_json(silent=True) or {}
        # Canonical field is "label"; "user_label" is an alias kept
        # in sync with the sibling /v2/chat/snippet-followup endpoint
        # so the frontend can use one consistent body shape across
        # both labeling-related calls. If both are present, the
        # canonical name wins.
        label = body.get("label")
        if label is None:
            label = body.get("user_label")
        # Strict bool — accept True/False only. The frontend
        # ActionBubble emits one of those two; anything else (None,
        # int, string "yes" / "charisma") signals a malformed call
        # we want to surface rather than coerce.
        if not isinstance(label, bool):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": (
                    "label (or user_label) must be a boolean "
                    "(true or false)"
                ),
            }), 400

        user_id = request.user_id
        updated = db.set_user_snippet_charisma_label(
            snippet_id=snippet_id,
            user_id=str(user_id),
            label=label,
        )
        if not updated:
            return jsonify({
                "code": "NOT_FOUND",
                "error": "Snippet not found or not owned by user",
            }), 404

        return jsonify({
            "status": "ok",
            "snippet_id": snippet_id,
            "user_charisma_label": updated.get("user_charisma_label"),
            "user_charisma_label_set_at": updated.get(
                "user_charisma_label_set_at"
            ),
        }), 200

    except Exception as e:
        logger.error(
            "user/snippets/<id>/label failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to record snippet label",
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


@v2_bp.route("/public/unsubscribe", methods=["POST"])
def v2_public_unsubscribe():
    """Token-based unsubscribe from publish-results emails.

    Phase 14. No bearer auth required — the signed token IS the
    auth. Validates signature, audience, and expiry; flips
    user_settings.email_pref_publish_results to FALSE; returns 200
    on first success and on subsequent re-clicks (idempotent).

    Body::
        { "token": "<signed unsubscribe JWT>" }

    Responses (per the frontend BFF contract):
      200 {status, email_obscured?, already_unsubscribed?}
      400 INVALID_INPUT — token missing / non-string
      401 INVALID_TOKEN — bad sig / expired / wrong audience
      404 USER_NOT_FOUND — token decoded but the user is gone
      503 SERVICE_UNAVAILABLE — UNSUBSCRIBE_TOKEN_SECRET unset
    """
    try:
        body = request.get_json(silent=True) or {}
        token = body.get("token")
        if not token or not isinstance(token, str):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "token required",
            }), 400

        from services.unsubscribe_tokens import (
            verify_unsubscribe_token,
            UnsubscribeTokenInvalid,
            UnsubscribeTokenExpired,
            UnsubscribeTokenNotConfigured,
        )

        try:
            user_id = verify_unsubscribe_token(token)
        except UnsubscribeTokenNotConfigured as e:
            logger.error("unsubscribe: secret not configured: %s", e)
            return jsonify({
                "code": "SERVICE_UNAVAILABLE",
                "error": "Unsubscribe service is temporarily unavailable.",
            }), 503
        except UnsubscribeTokenExpired as e:
            return jsonify({
                "code": "INVALID_TOKEN",
                "error": f"This unsubscribe link has expired ({e}).",
            }), 401
        except UnsubscribeTokenInvalid as e:
            return jsonify({
                "code": "INVALID_TOKEN",
                "error": f"This unsubscribe link is invalid ({e}).",
            }), 401

        # Make sure the user still exists (token may outlive the
        # account). We resolve the email both for the optional
        # email_obscured response field AND as the existence check
        # — get_user_email_from_auth returns None when the auth
        # row is gone.
        user_email: str | None = None
        try:
            user_email = db.get_user_email_from_auth(user_id)
        except Exception as e:
            logger.warning(
                "unsubscribe: email lookup failed user=%s err=%s",
                user_id, e,
            )
        if not user_email:
            return jsonify({
                "code": "USER_NOT_FOUND",
                "error": "We can't find that account anymore.",
            }), 404

        # Idempotency — second click within the validity window
        # should return 200 with already_unsubscribed=true, not a
        # 4xx. Read the current pref BEFORE writing so we know
        # whether this click changed state.
        was_subscribed = db.get_email_pref_publish_results(user_id)
        if was_subscribed:
            persisted = db.set_email_pref_publish_results(
                user_id=user_id,
                subscribed=False,
                source="email_token",
            )
            if not persisted:
                logger.warning(
                    "unsubscribe: persist failed user=%s — token "
                    "validated but DB write didn't land",
                    user_id,
                )
                return jsonify({
                    "code": "SERVICE_UNAVAILABLE",
                    "error": (
                        "Couldn't save your preference. Please try "
                        "again in a moment."
                    ),
                }), 503

        return jsonify({
            "status": "ok",
            "email_obscured": _obscure_email(user_email),
            "already_unsubscribed": not was_subscribed,
        }), 200

    except Exception as e:
        logger.error("public/unsubscribe failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "SERVICE_UNAVAILABLE",
            "error": "Unsubscribe service is temporarily unavailable.",
        }), 503


def _obscure_email(email: str) -> str | None:
    """Render ``email`` as ``j**@gmail.com``.

    First char + two stars + @ + domain. Returns None on malformed
    input so the response simply omits the field rather than
    leaking the raw address.
    """
    if not email or "@" not in email:
        return None
    local, _, domain = email.partition("@")
    if not local or not domain:
        return None
    head = local[0]
    return f"{head}**@{domain}"


# ── Directed-freestyle baseline (turns 1-4 for new users) ──────────
# Pivot from Phase 18's "frontend owns turns 1-4 as hardcoded strings"
# back to backend-generated dynamic questions, but with per-turn
# psychological OBJECTIVES so the LLM doesn't drift across the
# onboarding arc. Each turn has a single goal; the LLM builds the
# scenario but must satisfy that goal.
#
# Tone arc for the 4 baseline turns: turns 1-2 are warm (charisma —
# icebreaker + empathy), turns 3-4 are pressure (stress — challenge
# + reflex). After baseline (turn 5+), tone alternates per SSoT §4.

_BASELINE_TURN_OBJECTIVES: dict[int, str] = {
    1: (
        "OBJECTIVE: Icebreaker. Give a low-stakes scenario explaining "
        "something basic to a beginner. Do NOT mention math. Goal: "
        "Get them speaking naturally for 15s."
    ),
    2: (
        "OBJECTIVE: Empathy/Frustration. CRITICAL REQUIREMENT: You "
        "MUST explicitly reference a specific detail from the user's "
        "answer in Turn 1 — quote or paraphrase one concrete thing "
        "they said. Pretend the person they were explaining to "
        "completely misunderstood THAT specific detail and is getting "
        "frustrated. Ask the user how they de-escalate and re-explain. "
        "Do not ask a generic empathy question; prove you listened to "
        "their previous audio by anchoring on a phrase or example "
        "from it."
    ),
    3: (
        "OBJECTIVE: Pressure. Pivot to a high-pressure professional "
        "environment where someone aggressively challenges their "
        "authority. Demand a response."
    ),
    4: (
        "OBJECTIVE: Quick Reflex. Give an arbitrary, sudden constraint "
        "(e.g., \"Pitch your idea in exactly 3 sentences\")."
    ),
}


def _baseline_turn_objective(turn_number: int) -> str | None:
    """Return the directed-freestyle objective for turns 1-4, or
    None for turns outside that range. The caller decides whether
    to apply it (typically only when baseline_established=False)."""
    return _BASELINE_TURN_OBJECTIVES.get(turn_number)


def _baseline_turn_tone(turn_number: int) -> str:
    """Tone for baseline turns 1-4. Turns 1-2 charisma (warm arc),
    turns 3-4 stress (pressure arc). Out-of-range falls back to a
    standard alternation."""
    if turn_number == 1 or turn_number == 2:
        return "charisma"
    if turn_number == 3 or turn_number == 4:
        return "stress"
    return "charisma" if turn_number % 2 == 1 else "stress"


@v2_bp.route("/public/interview/next-question", methods=["POST"])
def v2_public_interview_next_question():
    """Return the next interview question — backend owns ALL turns.

    Pivot from Phase 18 (frontend-owned cold-start strings) back to
    backend-generated dynamic questions, with directed-freestyle
    per-turn objectives on turns 1-4 for users who haven't completed
    a baseline yet. See docs/ARCHITECTURE_SINGLE_SOURCE_OF_TRUTH.md
    §1 for the architectural reasoning.

    Behaviour:
      - Turn 1-4 + baseline_established=False (new user):
        LLM generates the question with a strict per-turn
        CURRENT_TURN_OBJECTIVE block in the system prompt + tone
        forced by the objective arc (1-2 charisma, 3-4 stress).
      - Turn 1-4 + baseline_established=True (returning user) OR
        turn 5+ for anyone:
        Standard alternation (charisma on odd, stress on even),
        no objective override. Phase 16 baseline summary +
        Phase 15 longitudinal + Phase 17 metrics blocks still
        apply via _generate_llm_question's existing augmentation.

    Input:  {
        turn_number: int,
        user_id?: str,
        previous_turns?: [{question, transcript?}],
        session_id?: str,                    // Phase A2.1 — optional;
        guest_session_id?: str               // when present, the
                                             // rolling conversation
                                             // summary is loaded and
                                             // spliced into the prompt
                                             // so previous_turns can be
                                             // trimmed to the last 2.
    }
    Output:
      200 {
        question:       str,
        tone:           "charisma" | "stress",
        turn_number:    int,
        source:         "directives_queue" | "admin_override"
                          | "llm_generated",
        directive?:     {position, intent_tag},   // present iff
                                                  // source = directives_queue
        source_detail?: "llm_baseline_directed" | "llm" | "fallback",
                          // present iff source = llm_generated; granular
                          // attribution for backend analytics; FE may
                          // safely ignore.
      }
      400 { code: "INVALID_INPUT" } on malformed input
    """
    try:
        body = request.get_json(silent=True) or {}
        turn_number = int(body.get("turn_number", 1))
        if turn_number < 1:
            turn_number = 1

        user_id = (body.get("user_id") or "").strip() or None
        previous_turns = body.get("previous_turns") or None
        # Phase A2.1 — caller can pass either spelling; whichever
        # the frontend has on hand. Empty/None → summary lookup is
        # skipped and the prompt builder falls back to the legacy
        # full-history replay (preserves turn-1 cold-start behavior
        # byte-for-byte).
        session_id_raw = (
            body.get("session_id")
            or body.get("guest_session_id")
            or ""
        )
        session_id_for_summary = (
            session_id_raw.strip() or None
            if isinstance(session_id_raw, str) else None
        )
        conversation_summary: str | None = None
        if session_id_for_summary and _is_valid_uuid(session_id_for_summary):
            try:
                row = db.get_session_conversation_summary(
                    session_id_for_summary,
                )
                if row:
                    conversation_summary = row.get("summary") or None
            except Exception as cs_err:
                logger.warning(
                    "interview: conversation_summary lookup failed "
                    "sid=%s err=%s (continuing with legacy "
                    "full-history replay)",
                    session_id_for_summary, cs_err,
                )

        # ── Admin override (directives queue) ─────────────────────────
        # coaching_directives_queue — user-level 2-step arc. Pop the
        # lowest-position un-exhausted row, mark exhausted. Wins over
        # directed-freestyle objectives and dynamic LLM generation.
        # Phase Directives-Queue (BE).
        #
        # Legacy queued_override_question (single-question override
        # via PUT /v2/admin/user/<id>/context) was removed in the
        # Week-1 cleanup. The directives-queue is the single admin
        # override path now.
        if user_id:
            directive = db.pop_next_directive(user_id)
            if directive:
                logger.info(
                    "interview: directives-queue HIT user=%s pos=%s "
                    "intent=%s turn=%s",
                    user_id, directive.get("position"),
                    directive.get("intent_tag"), turn_number,
                )
                return jsonify({
                    "question": directive.get("question"),
                    "tone": "charisma",
                    "turn_number": turn_number,
                    "source": "directives_queue",
                    "directive": {
                        "position": directive.get("position"),
                        "intent_tag": directive.get("intent_tag"),
                    },
                }), 200

        # ── Directed-freestyle decision ──────────────────────────────
        # New users (baseline_established=False) on turns 1-4 get the
        # per-turn objective + warm/stress arc. Everyone else uses
        # standard alternation.
        in_baseline_phase = (
            1 <= turn_number <= 4
            and bool(user_id)
            and not db.get_baseline_established(user_id)
        )
        # Guests with no user_id during turns 1-4: also apply the
        # baseline objectives. The flag-flip can't fire (no user_id)
        # but the question quality matters just as much for funnel UX.
        if 1 <= turn_number <= 4 and not user_id:
            in_baseline_phase = True

        if in_baseline_phase:
            tone = _baseline_turn_tone(turn_number)
            objective = _baseline_turn_objective(turn_number)
        else:
            # Turn 5+ for anyone, OR turns 1-4 for a returning user.
            # Standard alternation: odd→charisma, even→stress.
            tone = "charisma" if turn_number % 2 == 1 else "stress"
            objective = None

        question = _generate_llm_question(
            turn_number=turn_number,
            tone=tone,
            previous_turns=previous_turns,
            user_id=user_id,
            baseline_objective=objective,
            conversation_summary=conversation_summary,
        )
        # FE-aligned `source` enum: directives_queue | admin_override |
        # llm_generated. The directives-queue + admin-override branches
        # above already return with the right values; here we always
        # emit "llm_generated" for the LLM/fallback paths so the FE
        # NextQuestionSource enum stays clean.
        #
        # `source_detail` preserves the legacy granularity (baseline-
        # directed vs free-form vs fallback) for backend analytics /
        # admin debugging. FE doesn't consume it; safe to ignore.
        if question and objective:
            source_detail = "llm_baseline_directed"
        elif question:
            source_detail = "llm"
        else:
            source_detail = "fallback"

        if not question:
            pool = _INTERVIEW_QUESTIONS_FALLBACK[tone]
            question_index = (turn_number - 1) % len(pool)
            question = pool[question_index]

        return jsonify({
            "question": question,
            "tone": tone,
            "turn_number": turn_number,
            "source": "llm_generated",
            "source_detail": source_detail,
        }), 200

    except (TypeError, ValueError) as e:
        return jsonify({
            "code": "INVALID_INPUT",
            "error": f"turn_number must be an integer >= 5: {e}",
        }), 400
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

        # ── Phase 18: baseline graduation at turn 4 completion ──────
        # Per docs/ARCHITECTURE_SINGLE_SOURCE_OF_TRUTH.md §2, the
        # baseline_established flip happens here — the moment the
        # user has successfully submitted their answer to the last
        # frontend-owned onboarding turn (M4). Previous behaviour
        # flipped lazily at the first turn-5 next-question request,
        # which moved the side-effect away from the moment it
        # semantically belongs. The Phase 16 baseline summary also
        # bakes here so the digest is ready before the user's first
        # turn-5 prompt is built.
        #
        # Requires an authenticated user — guest sessions skip both
        # the flip (no user_settings row to upsert) and the summary
        # (nothing to attach it to). The auth extract is best-
        # effort: a missing/invalid token just skips this block.
        if turn_number == 4:
            try:
                from auth import verify_supabase_token
                authed_user_id_b = None
                auth_header_b = request.headers.get("Authorization") or ""
                if auth_header_b.startswith("Bearer "):
                    payload_b = verify_supabase_token(
                        auth_header_b[len("Bearer "):].strip()
                    )
                    authed_user_id_b = (payload_b or {}).get("sub")
                if authed_user_id_b:
                    uid = str(authed_user_id_b)
                    # Flip the flag (idempotent — upsert + no-op when
                    # already TRUE).
                    try:
                        db.mark_baseline_established(uid)
                    except Exception as flip_err:
                        logger.warning(
                            "baseline-flip: failed user=%s err=%s",
                            uid, flip_err,
                        )

                    # Phase 16 — compute the EBCP digest now so the
                    # next turn-5 prompt has it ready. Flag-gated;
                    # synchronous so the result is persisted before
                    # the upload response returns (~1-2s additional
                    # latency on this one moment per user).
                    try:
                        from config import Config
                        if Config().BASELINE_SUMMARY_ENABLED:
                            if not db.get_user_baseline_summary(uid):
                                # Build previous_turns from this
                                # session's snippets (turn rows
                                # carry question_text + transcript).
                                turns_for_summary: list[dict] = []
                                try:
                                    rows = db.get_snippets_by_session(
                                        guest_session_id
                                    ) or []
                                except Exception:
                                    rows = []
                                ordered = sorted(
                                    rows,
                                    key=lambda r: r.get("turn_number") or 0,
                                )
                                for r in ordered:
                                    q = (r.get("question_text") or "").strip()
                                    t = (r.get("transcript") or "").strip()
                                    if not t:
                                        continue
                                    turns_for_summary.append({
                                        "question": q,
                                        "transcript": t,
                                    })
                                if turns_for_summary:
                                    from services.baseline_summary import (
                                        compute_baseline_summary,
                                    )
                                    compute_baseline_summary(
                                        user_id=uid,
                                        previous_turns=turns_for_summary,
                                    )
                    except Exception as bs_err:
                        logger.warning(
                            "baseline-summary: compute failed user=%s err=%s",
                            uid, bs_err,
                        )
            except Exception as outer_err:
                logger.warning(
                    "baseline-graduation: outer failure: %s",
                    outer_err,
                )

        # Freemium tease — last onboarding turn returns session-aggregate
        # stats + a hardcoded archetype so the frontend can render the
        # "what we noticed" bubbles BEFORE the user signs up. The session
        # stays anonymous (user_id=NULL); the full charisma_profile +
        # admin email don't fire until /v2/auth/merge-session links it
        # to a real user.
        #
        # Archetype is hardcoded to "The Calm Anchor" per the v1 spec.
        # The real archetype emerges from charisma_profile during the
        # post-claim finalize once we have user_id; pre-claim we
        # surface a stable placeholder rather than computing an
        # unstable one off 4 short turns.
        freemium_tease = None
        if turn_number == 4:
            try:
                from services.session_metrics import (
                    compute_session_global_metrics,
                )
                # Aggregates all 4 turns' snippets into global_* + KPI
                # and persists to the v2_sessions row. Idempotent —
                # the admin "Compute Metrics" click later re-runs the
                # same path.
                agg = compute_session_global_metrics(guest_session_id) or {}
                freemium_tease = {
                    "archetype": "The Calm Anchor",
                    "stats": {
                        "wpm": agg.get("wpm"),
                        "fillers": agg.get("fillers"),
                        "pause_ms": agg.get("pause_ms"),
                        "dynamic_db": agg.get("dynamic_db"),
                        "pitch_center": agg.get("pitch_center"),
                        "energy": agg.get("energy"),
                        "kpi_score": agg.get("kpi_score"),
                        "snippets_analyzed": agg.get("snippets_analyzed"),
                    },
                }
            except Exception as tease_err:
                # Tease is best-effort — failure leaves freemium_tease=None
                # and the frontend renders a "tap to sign up to see
                # your stats" empty state.
                logger.warning(
                    "freemium_tease: aggregation failed sid=%s err=%s",
                    guest_session_id, tease_err,
                )

        # ── Phase A2.1 — fire-and-forget rolling-summary update ─────
        # Folds this turn's (question, transcript) into the session's
        # conversation_summary so the NEXT call to
        # /v2/public/interview/next-question can read a bounded-cost
        # digest instead of replaying the whole history.
        #
        # Async by design: the LLM call adds ~1-2s of wall time and
        # this endpoint already does enough on the hot path
        # (Whisper + acoustic metrics + snippet insert). The runner
        # is a daemon thread that never raises — a failed update
        # leaves the previous summary in place per the spec's "MUST
        # fall back to keep previous summary" rule.
        #
        # Only fires when we have at least one usable side (question
        # OR transcript). Cold-start turn-1 with no question_text +
        # no transcript is a no-op.
        if guest_session_id and (
            (question_text or "").strip()
            or (transcript_text or "").strip()
        ):
            try:
                from services.conversation_summary import (
                    update_summary_async,
                )
                prev = db.get_session_conversation_summary(guest_session_id)
                prev_summary = (prev or {}).get("summary")
                update_summary_async(
                    session_id=guest_session_id,
                    previous_summary=prev_summary,
                    question=(question_text or "").strip(),
                    transcript=(transcript_text or "").strip(),
                )
            except Exception as cs_err:
                logger.warning(
                    "interview: conversation_summary async-fire "
                    "failed sid=%s err=%s (non-fatal — next read "
                    "will see previous summary)",
                    guest_session_id, cs_err,
                )

        return jsonify({
            "status": "ok",
            "guest_session_id": guest_session_id,
            "snippet_id": snippet_dict.get("id") if snippet_dict else None,
            "duration_seconds": duration_seconds,
            "total_session_duration_seconds": round(total_duration, 1),
            "metrics": snippet_metrics,
            "transcript": transcript_text,
            "freemium_tease": freemium_tease,
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

    # Now that the session has a real user_id, run the standard
    # finalize so the admin sees this in the Pending Review queue
    # and gets the notification email. The spec is explicit: the
    # email dispatches ONLY after the claim, never on the
    # anonymous session.
    #
    # finalize_session_pending_admin_review computes global metrics
    # + B6 KPI + AI draft prefill, writes session_kpi_narrative,
    # flips status to "pending_admin_review", and sends the admin
    # notification. Per-step failure-isolated so a flaky email
    # service never unwinds the (already-committed) claim.
    finalize_summary: dict | None = None
    try:
        from services.session_publish import (
            finalize_session_pending_admin_review,
        )
        finalize_summary = finalize_session_pending_admin_review(
            session_id=session_id,
            user_id=str(user_id),
        )
        logger.info(
            "guest_funnel: post-claim finalize sid=%s result=%s",
            session_id, finalize_summary,
        )
    except Exception as fp_err:
        logger.warning(
            "guest_funnel: post-claim finalize failed sid=%s err=%s "
            "(non-fatal — admin can recompute manually)",
            session_id, fp_err,
        )

    logger.info(
        "guest_funnel: claim ok user_id=%s session_id=%s recording_id=%s",
        user_id, session_id, rec_id,
    )
    return ({
        "status": "ok",
        "session_id": str(claimed.get("id")),
        "analysis_status": "queued",
        "finalize": finalize_summary,
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
      - admin_comment    (str, optional)
      - snippet_type     ("charisma"|"stress"|"unlabeled", default "unlabeled")
      - follow_up_question (str, optional) — if omitted AND admin_comment is set,
        the LLM auto-generates one based on snippet_type + transcript + comment.
        Pass null explicitly to clear an existing follow_up_question.
      - acceptance_mode  ("accepted_as_is" | "admin_corrected", optional) — RLHF
        signal classifying how the admin handled the AI's
        ai_draft_admin_comment. "accepted_as_is" = saved the draft raw
        (positive signal). "admin_corrected" = edited before save
        (correction trajectory). Omit to leave the column unchanged;
        the weekly fine-tuning cron filters on this value.

    Returns: { status, snippet, follow_up_question_source, acceptance_mode }
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

        # acceptance_mode — optional RLHF classification. Strict
        # whitelist; reject typos with a 400 so the frontend
        # surfaces the bug instead of silently dropping the signal.
        acceptance_mode_raw = body.get("acceptance_mode")
        acceptance_mode: str | None = None
        if acceptance_mode_raw is not None:
            if not isinstance(acceptance_mode_raw, str):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "acceptance_mode must be a string",
                }), 400
            normalized = acceptance_mode_raw.strip().lower()
            if normalized not in ("accepted_as_is", "admin_corrected"):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": (
                        "acceptance_mode must be 'accepted_as_is' "
                        "or 'admin_corrected'"
                    ),
                }), 400
            acceptance_mode = normalized

        admin_user_id = request.user_id

        updated = db.update_snippet_comment(
            snippet_id=snippet_id,
            admin_comment=admin_comment,
            snippet_type=snippet_type,
            admin_user_id=admin_user_id,
            acceptance_mode=acceptance_mode,
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
                    # Phase 10 — preserve the original AI generation
                    # in ai_draft_follow_up_question so the publish-
                    # time annotation can pair (draft, final) even if
                    # the admin edits follow_up_question afterwards.
                    # Only write the draft once (first generation);
                    # subsequent edits don't overwrite the audit
                    # trail.
                    if not (updated.get("ai_draft_follow_up_question") or "").strip():
                        db.set_charisma_snippet_ai_draft_follow_up(
                            snippet_id, generated,
                        )
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

        # Return the snippet with updated follow_up_question reflected.
        # The row already carries the acceptance_mode + set_at columns
        # if the migration is in place, so the frontend can read them
        # back from final_snippet directly — exposing the canonical
        # acceptance_mode at the top level too for cheap parsing.
        final_snippet = {**updated, "follow_up_question": follow_up_question}
        return jsonify({
            "status": "ok",
            "snippet": final_snippet,
            "follow_up_question_source": follow_up_source,
            "acceptance_mode": (
                final_snippet.get("admin_comment_acceptance_mode")
            ),
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

        # Phase 10 — emit RLHF annotation events for every snippet in
        # this session BEFORE the status flip + email. Each row in
        # admin_annotation_events captures (ai_draft, admin_final) for
        # admin_comment, follow_up_question, and stress coach_label_
        # notes. Approved-as-is gets reason_chip='approved_as_is';
        # edits get the diff. Best-effort — never blocks the publish.
        try:
            events_written = db.record_snippet_publish_annotations(
                session_id=session_id,
                admin_user_id=str(request.user_id),
            )
            logger.info(
                "publish-results: rlhf events emitted session=%s count=%d",
                session_id, events_written,
            )
        except Exception as annot_err:
            logger.warning(
                "publish-results: rlhf emit failed session=%s err=%s "
                "(non-fatal)", session_id, annot_err,
            )

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

        # Flip the session status so /results page shows snippets.
        # Done BEFORE the email send so a failed send never blocks
        # the user from reaching their results via direct link.
        db.v2_publish_session_results(session_id)

        # Charisma Awareness Dashboard — compute once on publish so
        # the user-facing /results page can render the radar/heatmap
        # off a cache read. Failure-isolated: a bad build leaves the
        # column NULL and the frontend hides the section, but the
        # publish still proceeds (snippets + email both ship).
        try:
            from services.charisma_profile import (
                compute_and_persist_charisma_profile,
            )
            compute_and_persist_charisma_profile(
                session_id=session_id,
                user_id=str(user_id),
            )
        except Exception as cp_err:
            logger.warning(
                "publish-results: charisma_profile compute failed "
                "sid=%s err=%s (non-fatal)",
                session_id, cp_err,
            )

        # ── Phase 14 — new PostSessionResultsEmail render pipeline ──
        # Replaces the inline HTML build. The render service handles:
        #   - per-user pref check (skip if unsubscribed)
        #   - server-to-server render call into Next.js
        #   - RFC 8058 List-Unsubscribe headers
        #   - unsubscribe token mint + URL
        # Props for the template:
        first_name: str | None = None
        try:
            details = db.v2_get_student_details(user_id) or {}
            full_name = (details.get("name") or "").strip()
            if full_name:
                first_name = full_name.split()[0]
        except Exception as e:
            logger.warning(
                "publish-results: name lookup failed user=%s err=%s",
                user_id, e,
            )

        snippet_count = 0
        try:
            commented = db.get_snippets_with_comments_by_session(session_id)
            snippet_count = len(commented or [])
        except Exception as e:
            logger.warning(
                "publish-results: snippet count lookup failed "
                "session=%s err=%s", session_id, e,
            )

        top_theme: str | None = None
        try:
            sess_row = db.v2_get_session_by_id(session_id) or {}
            top_theme = (
                (sess_row.get("stickiness_top_topic") or "").strip() or None
            )
        except Exception:
            pass

        from services.post_session_results_email import (
            send_publish_results_email,
        )

        results_url = (
            f"{config.PUBLIC_FRONTEND_URL.rstrip('/')}/results/{session_id}"
        )

        send_result = send_publish_results_email(
            user_id=user_id,
            user_email=user_email,
            user_first_name=first_name,
            snippet_count=snippet_count,
            top_theme=top_theme,
            session_id=session_id,
        )
        status = send_result.get("status")

        if status == "sent":
            logger.info(
                "publish-results: email sent session_id=%s user_id=%s "
                "email=%s", session_id, user_id, user_email,
            )
            return jsonify({
                "status": "ok",
                "email_sent_to": user_email,
                "results_url": results_url,
            }), 200

        if status == "skipped":
            reason = send_result.get("reason") or "unknown"
            logger.info(
                "publish-results: email skipped session_id=%s user_id=%s "
                "reason=%s", session_id, user_id, reason,
            )
            return jsonify({
                "status": "ok",
                "email_sent_to": None,
                "results_url": results_url,
                "email_skipped_reason": reason,
            }), 200

        # render_failed / send_failed — publish itself succeeded
        # (the session is already flipped to completed) so we return
        # 200 with a warning rather than blocking on the email step.
        logger.error(
            "publish-results: email %s session_id=%s user_id=%s err=%s",
            status, session_id, user_id, send_result.get("error"),
        )
        return jsonify({
            "status": "ok",
            "email_sent_to": None,
            "results_url": results_url,
            "warning": (
                "Results published but email delivery failed: "
                f"{send_result.get('error') or status}"
            ),
        }), 200

    except Exception as e:
        logger.error("publish-results: failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to publish results"}), 500


############################################################################
# Admin: AI evaluator rationale review (Phase 14.x — frontend BFF target)
############################################################################

@v2_bp.route(
    "/admin/snippets/<snippet_id>/coaching-rationale",
    methods=["PATCH"],
)
@require_admin
def v2_admin_update_snippet_coaching_rationale(snippet_id):
    """Persist an admin's review of the AI evaluator's rationale.

    Backs the editable-rationale strip on the admin user-detail page.
    The strip pre-fills its textarea with the AI's rationale and lets
    the admin save it as-is (approval signal) or edit it (correction
    signal). At publish time, ``record_snippet_publish_annotations``
    emits one ``admin_annotation_events`` row per reviewed snippet
    (field_name='evaluator_rationale') so the RLHF/DPO export
    captures the (AI draft, admin final) pair the same way it
    already captures admin_comment / follow_up_question.

    Body::

        {
          "rationale":        str,   # text the admin saw on screen
          "edited_by_admin":  bool   # true → store as correction;
                                     # false → store admin_corrected_
                                     #   rationale=null (= approved
                                     #   AI verbatim)
        }

    Responses:
      200 — review saved; returns the updated outcome.evaluator block
      400 INVALID_INPUT       — bad UUID, missing rationale, or
                                edited_by_admin not a bool
      404 NOT_FOUND           — no charisma_snippet with this id
      422 NO_OUTCOME_TO_REVIEW — snippet exists but has no
                                follow_up_outcome / no evaluator
                                (the user hasn't done a coaching
                                attempt for this snippet yet, so
                                there's no AI rationale to review)
      500 V2_ERROR            — unexpected
    """
    if not _is_valid_uuid(snippet_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "snippet_id must be a valid UUID",
        }), 400

    try:
        body = request.get_json(silent=True) or {}
        rationale = body.get("rationale")
        edited_by_admin = body.get("edited_by_admin")

        if not isinstance(rationale, str) or not rationale.strip():
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "rationale must be a non-empty string",
            }), 400
        if not isinstance(edited_by_admin, bool):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "edited_by_admin must be a boolean",
            }), 400

        reviewed_at = datetime.now(timezone.utc).isoformat()
        outcome = db.set_snippet_evaluator_rationale_review(
            snippet_id=snippet_id,
            rationale_text=rationale,
            edited_by_admin=edited_by_admin,
            reviewed_at=reviewed_at,
        )
        if not outcome:
            # Distinguish "snippet doesn't exist" from "snippet has
            # no follow_up_outcome to review" with a quick existence
            # probe — both are 4xx but the codes are different so
            # the frontend can show the right toast.
            try:
                exists_probe = (
                    db.client.table("charisma_snippets")
                    .select("id")
                    .eq("id", snippet_id)
                    .limit(1)
                    .execute()
                )
                snippet_exists = bool(exists_probe.data)
            except Exception:
                snippet_exists = False

            if not snippet_exists:
                return jsonify({
                    "code": "NOT_FOUND",
                    "error": "Snippet not found",
                }), 404
            return jsonify({
                "code": "NO_OUTCOME_TO_REVIEW",
                "error": (
                    "Snippet has no coaching outcome yet — the user "
                    "must complete a coaching attempt before the "
                    "rationale can be reviewed."
                ),
            }), 422

        evaluator = outcome.get("evaluator") or {}
        return jsonify({
            "status": "ok",
            "snippet_id": snippet_id,
            "evaluator": {
                "rationale": evaluator.get("rationale"),
                "admin_corrected_rationale": evaluator.get(
                    "admin_corrected_rationale"
                ),
                "admin_reviewed_at": evaluator.get("admin_reviewed_at"),
            },
        }), 200

    except Exception as e:
        logger.error(
            "admin/snippets/<id>/coaching-rationale failed: %s",
            e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to save rationale review",
        }), 500


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

        # Update boundaries in DB. update_snippet_boundaries
        # converts (start_time, end_time) seconds → (start_offset_ms,
        # duration_ms) and writes those columns — the recompute below
        # then reads the new values straight off the row.
        updated = db.update_snippet_boundaries(snippet_id, start_time, end_time)
        if not updated:
            return jsonify({"code": "NOT_FOUND", "error": "Snippet not found"}), 404

        # Re-slice the parent audio for the new window and re-derive
        # the per-snippet metrics blob + transcript + WPM + fillers
        # in one call. The helper handles audio fetch, PCM decode,
        # PCM slice, Whisper re-transcribe, filler count, and the
        # atomic DB write. Failure is non-fatal so the boundary
        # update still lands.
        recomputed_metrics = None
        try:
            from services.snippet_extraction import (
                recompute_snippet_metrics_for_window,
            )
            recomputed_metrics = recompute_snippet_metrics_for_window(
                snippet_id
            )
        except Exception as metrics_err:
            logger.warning(
                "admin: re-compute metrics after boundary adjust failed: %s",
                metrics_err, exc_info=True,
            )

        # Re-fetch the final state so the response carries the row
        # the admin UI is about to render — includes the fresh
        # metrics JSONB and the new transcript.
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

            # Boundaries changed → the per-snippet metrics blob must
            # be recomputed for the new window. Same helper the
            # dedicated /boundaries endpoint calls, so PATCH and POST
            # produce identical post-conditions. Failure is non-fatal
            # — the boundary update lands either way.
            try:
                from services.snippet_extraction import (
                    recompute_snippet_metrics_for_window,
                )
                recompute_snippet_metrics_for_window(snippet_id)
                # Re-fetch so subsequent partial updates in this same
                # request (label, comment, status) see the new
                # transcript + metric columns.
                refreshed = (
                    db.client.table("charisma_snippets")
                    .select("*")
                    .eq("id", snippet_id)
                    .limit(1)
                    .execute()
                )
                if refreshed.data:
                    snippet = refreshed.data[0]
            except Exception as metrics_err:
                logger.warning(
                    "admin patch: re-compute after boundary change failed: %s",
                    metrics_err, exc_info=True,
                )

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
    """Publish results for a session — flips visibility for the user
    and writes RLHF training rows.

    Mirrors the existing /v2/internal/publish-session-results endpoint
    but takes session_id as a URL path param and ALSO accepts the
    admin's finalized session_comment + Director's Script so we can
    capture the (AI predicted, human final) pairs into
    admin_annotations_log on the same atomic action.

    Body (all fields optional)::

        {
          "final_human_comment":  "...",       // session-level message
          "final_human_next_questions": [      // NEW — 5-question script
            { "position": 1, "text": "...", "intent_tag": "..." },
            ...
          ],
          "final_human_question": "..."        // back-compat single-question;
                                               // ignored if array is present
        }

    Omitted fields fall through to the AI's pre-generated prediction
    (implicit accept). was_corrected is computed per-field/per-
    position by string-comparing predicted vs final.

    RLHF log writes (per Publish click):
      * 1 row for the session-level admin_comment
        (question_position = NULL)
      * up to 5 rows for the Director's Script positions
        (question_position = 1..5, intent_tag carried)
      * 1 row for the legacy single next_question back-compat path
        when the array was NOT provided (question_position = NULL)

    Side effects:
      * Sets results_published_at = NOW() on the session
      * Flips status to 'completed'
      * Saves final_human_next_questions on the session row
      * Sends the "Charisma Snippets Ready" email via Resend
      * Inserts the RLHF rows above

    Responses:
        200 { status, session_id, results_published_at,
              email_sent, rlhf_logged, rlhf_rows_written,
              was_corrected }
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

        body = request.get_json(silent=True) or {}
        final_comment_raw = body.get("final_human_comment")
        final_question_raw = body.get("final_human_question")
        final_comment = (
            final_comment_raw.strip() if isinstance(final_comment_raw, str)
            else None
        )
        final_question = (
            final_question_raw.strip() if isinstance(final_question_raw, str)
            else None
        )

        # NEW — Director's Script array. When present, supersedes
        # the legacy single-question body field for RLHF purposes
        # (we ignore final_human_question for log-write decisions
        # when the array is the authoritative input).
        final_questions_raw = body.get("final_human_next_questions")
        final_questions: list[dict] = []
        if isinstance(final_questions_raw, list):
            for entry in final_questions_raw[:5]:
                if not isinstance(entry, dict):
                    continue
                text = (entry.get("text") or "").strip()
                if not text:
                    continue
                try:
                    pos = int(entry.get("position"))
                except (TypeError, ValueError):
                    continue
                if not (1 <= pos <= 5):
                    continue
                intent = (entry.get("intent_tag") or "").strip() or None
                final_questions.append({
                    "position": pos,
                    "text": text,
                    "intent_tag": intent,
                })

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

        # 3.5. Persist the admin-edited 5-question script on the
        #      session row so the next state-machine turn loads
        #      THIS version (not the AI pre-generated draft).
        if final_questions:
            try:
                db.set_session_final_next_questions(
                    str(session_id), final_questions,
                )
            except Exception as fq_err:
                logger.warning(
                    "publish: final_questions persist failed sid=%s err=%s",
                    session_id, fq_err,
                )

        # 4. RLHF log. Three writes:
        #    a) one row for the session-level admin_comment
        #    b) per-position rows when the Director's Script array
        #       was provided (preferred RLHF granularity)
        #    c) fallback: one row for the legacy single
        #       final_human_question when the array was NOT
        #       provided (back-compat — old admin UI path).
        #    Failure-isolated: publish already succeeded, we don't
        #    unwind for log misses.
        ai_comment = (session.get("ai_predicted_session_comment") or "").strip() or None
        ai_question = (session.get("ai_predicted_next_question") or "").strip() or None
        ai_questions_raw = session.get("ai_predicted_next_questions") or []
        # Position-indexed lookup of the AI prediction so we can
        # diff against admin's per-position edits cheaply.
        ai_questions_by_pos: dict[int, dict] = {}
        if isinstance(ai_questions_raw, list):
            for entry in ai_questions_raw:
                if not isinstance(entry, dict):
                    continue
                try:
                    p = int(entry.get("position"))
                except (TypeError, ValueError):
                    continue
                if 1 <= p <= 5:
                    ai_questions_by_pos[p] = entry

        # Session-level comment fall-through (admin omitted → accepted).
        if final_comment is None:
            final_comment = ai_comment

        # was_corrected (session-level row): per-comment compare.
        # Per-question rows compute their own was_corrected below.
        session_was_corrected = bool(
            (ai_comment != final_comment) and (ai_comment or final_comment)
        )
        # Surface-level "did the admin change ANYTHING" for the
        # response. True if the comment was edited OR any question
        # was edited.
        any_was_corrected = session_was_corrected

        owner_id = session.get("user_id")
        rlhf_rows_written = 0
        if owner_id:
            owner_id_s = str(owner_id)
            session_id_s = str(session_id)
            # a) session-level comment row (question_position = NULL).
            #    We pass the legacy single question into this row
            #    too ONLY when the array path isn't being used,
            #    matching the prior shape exactly for back-compat
            #    consumers of admin_annotations_log.
            try:
                legacy_q_final = (
                    final_question
                    if final_question is not None
                    else ai_question
                )
                row = db.insert_admin_annotation_log(
                    user_id=owner_id_s,
                    session_id=session_id_s,
                    ai_predicted_comment=ai_comment,
                    ai_predicted_question=(
                        None if final_questions else ai_question
                    ),
                    final_human_comment=final_comment,
                    final_human_question=(
                        None if final_questions else legacy_q_final
                    ),
                    was_corrected=session_was_corrected,
                )
                if row is not None:
                    rlhf_rows_written += 1
            except Exception as log_err:
                logger.warning(
                    "publish: session-level rlhf log failed sid=%s err=%s",
                    session_id, log_err,
                )

            # b) per-position rows when admin sent the array.
            if final_questions:
                for entry in final_questions:
                    pos = entry["position"]
                    final_text = entry["text"]
                    final_tag = entry["intent_tag"]
                    ai_entry = ai_questions_by_pos.get(pos) or {}
                    ai_text = (ai_entry.get("text") or "").strip() or None
                    ai_tag = (
                        ai_entry.get("intent_tag") or ""
                    ).strip() or None
                    per_was_corrected = bool(
                        (ai_text != final_text) and (ai_text or final_text)
                    )
                    if per_was_corrected:
                        any_was_corrected = True
                    try:
                        row = db.insert_admin_annotation_log(
                            user_id=owner_id_s,
                            session_id=session_id_s,
                            ai_predicted_comment=None,
                            ai_predicted_question=ai_text,
                            final_human_comment=None,
                            final_human_question=final_text,
                            was_corrected=per_was_corrected,
                            question_position=pos,
                            intent_tag=(final_tag or ai_tag),
                        )
                        if row is not None:
                            rlhf_rows_written += 1
                    except Exception as log_err:
                        logger.warning(
                            "publish: per-position rlhf log failed "
                            "sid=%s pos=%d err=%s",
                            session_id, pos, log_err,
                        )
        else:
            logger.info(
                "publish: skipping rlhf log sid=%s — no owner_id "
                "(anonymous session)", session_id,
            )

        return jsonify({
            "status": "ok",
            "session_id": session_id,
            "results_published_at": published.get("results_published_at"),
            "email_sent": email_sent,
            "rlhf_logged": rlhf_rows_written > 0,
            "rlhf_rows_written": rlhf_rows_written,
            "was_corrected": any_was_corrected,
        }), 200

    except Exception as e:
        logger.error("admin: publish session failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to publish session"}), 500


def _send_results_ready_email(session_id: str, session: dict) -> bool:
    """Send the "Results Ready" email via the Phase 14 render pipeline.

    Returns True iff the email was actually sent. SKIPPED states
    (user unsubscribed, SEND_EMAILS off) return False so the caller
    treats them the same as a delivery miss in its boolean response
    flag, but the underlying outcome is logged.

    Centralised so /admin/sessions/<id>/publish and the legacy
    /internal/publish-session-results don't drift apart.
    """
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
    try:
        resp = httpx.get(user_url, headers=auth_headers, timeout=10)
    except Exception as e:
        logger.warning("publish: auth fetch raised user=%s: %s", user_id, e)
        return False
    if resp.status_code != 200:
        logger.warning("publish: failed to fetch user %s (status %d)", user_id, resp.status_code)
        return False
    user_email = (resp.json() or {}).get("email")
    if not user_email:
        return False

    first_name: str | None = None
    try:
        details = db.v2_get_student_details(user_id) or {}
        full_name = (details.get("name") or "").strip()
        if full_name:
            first_name = full_name.split()[0]
    except Exception as e:
        logger.warning(
            "publish: name lookup failed user=%s err=%s", user_id, e,
        )

    snippet_count = 0
    try:
        commented = db.get_snippets_with_comments_by_session(session_id)
        snippet_count = len(commented or [])
    except Exception as e:
        logger.warning(
            "publish: snippet count lookup failed session=%s err=%s",
            session_id, e,
        )

    top_theme = (session.get("stickiness_top_topic") or "").strip() or None

    from services.post_session_results_email import (
        send_publish_results_email,
    )
    result = send_publish_results_email(
        user_id=user_id,
        user_email=user_email,
        user_first_name=first_name,
        snippet_count=snippet_count,
        top_theme=top_theme,
        session_id=session_id,
    )
    status = result.get("status")
    if status == "sent":
        return True
    logger.info(
        "publish: email %s session=%s user=%s reason=%s",
        status, session_id, user_id,
        result.get("reason") or result.get("error"),
    )
    return False


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


@v2_bp.route("/admin/snippets/<snippet_id>", methods=["DELETE"])
@require_admin
def v2_admin_delete_snippet(snippet_id):
    """Permanently delete a charisma_snippets row.

    Phase 18.1 — admin "delete snippet" flow for garbage /
    misclassified extractions. Distinct from /skip: skip is a soft
    hide reversible from admin UI; this is destructive.

    Cascade behaviour:
      - coaching_attempts rows referencing this snippet → CASCADE
        deleted via the FK from the Phase 2 migration.
      - coaching_attempt_annotations → CASCADE via coaching_attempts.
      - admin_annotation_events → not cascaded (no FK). RLHF training
        signal stays intact.

    Returns:
        200 { status: "ok", deleted_id }
        400 INVALID_INPUT — bad UUID
        404 NOT_FOUND — snippet doesn't exist (or already deleted —
            idempotent for the caller; second click is just a 404)
        500 V2_ERROR — unexpected DB error
    """
    if not _is_valid_uuid(snippet_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "snippet_id must be a valid UUID",
        }), 400

    try:
        deleted = db.hard_delete_charisma_snippet(snippet_id)
        if deleted is None:
            return jsonify({
                "code": "NOT_FOUND",
                "error": "Snippet not found (already deleted or never existed)",
            }), 404

        logger.info(
            "admin: deleted snippet=%s session=%s by admin=%s",
            snippet_id,
            deleted.get("session_id"),
            getattr(request, "user_id", None),
        )
        return jsonify({
            "status": "ok",
            "deleted_id": snippet_id,
        }), 200

    except Exception as e:
        logger.error(
            "admin: delete snippet failed snippet=%s: %s",
            snippet_id, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to delete snippet",
        }), 500


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

@v2_bp.route("/admin/users/<user_id>/files", methods=["GET"])
@require_admin
def v2_admin_get_user_files(user_id):
    """Files uploaded by ``user_id`` (audio + video), newest first.

    Backs the admin user-detail "Files" tab. Each row is decorated
    with a ``playback_url`` so the admin UI can drop straight into
    an ``<audio>`` / ``<video>`` element without a second round-trip:
      - Public bucket → cached ``r2_url`` from the row
      - Private bucket → fresh signed URL minted here (default
        TTL: SIGNED_URL_EXPIRY_SECONDS, configurable via
        ?expires_in=N up to 7 days)

    Auth: admin only (``@require_admin``). The user_id in the path
    is the user whose files we list — distinct from the admin
    making the request.

    Response (200)::

        {
          "user_id": "<uuid>",
          "files": [
            {
              "id": "<uuid>",
              "session_id": "<uuid>" | null,
              "file_name": "<original>",
              "file_type": "audio" | "video",
              "content_type": "video/mp4" | ...,
              "size_bytes": 12345678,
              "r2_url": "https://..." | null,
              "playback_url": "https://...",
              "created_at": "<iso8601>"
            },
            ...
          ],
          "total": N
        }
    """
    try:
        if not _is_valid_uuid(user_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "user_id must be a valid UUID",
            }), 400

        try:
            expires_in = int(
                request.args.get("expires_in")
                or config.SIGNED_URL_EXPIRY_SECONDS
            )
        except (TypeError, ValueError):
            expires_in = config.SIGNED_URL_EXPIRY_SECONDS

        rows = db.list_user_uploaded_files_for_user(user_id) or []

        from services.user_media_storage import presigned_get_user_media

        files: list[dict] = []
        for r in rows:
            # Cached public URL wins when present (zero round-trip
            # on R2 public buckets). Otherwise mint a fresh signed
            # URL per response — TTL is bounded by the helper to
            # 60s..7d so a missing/garbage query param can't
            # produce a URL that lives forever.
            playback_url = (r.get("r2_url") or "").strip() or None
            if not playback_url:
                key = (r.get("r2_key") or "").strip()
                if key:
                    playback_url = presigned_get_user_media(
                        key, expires_in=expires_in,
                    )
            files.append({
                "id": r.get("id"),
                "session_id": r.get("session_id"),
                "file_name": r.get("file_name"),
                "file_type": r.get("file_type"),
                "content_type": r.get("content_type"),
                "size_bytes": r.get("file_size_bytes"),
                "r2_url": r.get("r2_url"),
                "playback_url": playback_url,
                "created_at": r.get("created_at"),
            })

        return jsonify({
            "user_id": user_id,
            "files": files,
            "total": len(files),
        }), 200

    except Exception as e:
        logger.error(
            "admin/users/<id>/files failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to fetch user files",
        }), 500


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
            # Phase 11 — stickiness-topic. Three NULL fields when the
            # admin hasn't yet clicked "Compute Metrics" on this
            # session; the frontend renders "—" in that case. The
            # legacy ai_score / ai_summary block was removed when the
            # panel was redesigned to KPI + Stickiness.
            "stickiness_top_topic": session.get("stickiness_top_topic"),
            "stickiness_score": session.get("stickiness_score"),
            "stickiness_topic_distribution": session.get(
                "stickiness_topic_distribution"
            ),
            "stickiness_computed_at": session.get("stickiness_computed_at"),
            # Phase 17.1 — drift-guard verdict. The admin UI can
            # render a "needs review" banner when this is True and
            # surface drift_diagnostic for the explanation.
            "needs_admin_review": bool(session.get("needs_admin_review")),
            "drift_diagnostic": session.get("drift_diagnostic"),
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
    """Thin shim — the aggregation lives in services.session_metrics so
    other service-layer callers (auto-publish, contextual-chat
    finalize) don't have to reach into routes for it.

    Kept as a private alias here so the existing in-route callers
    (auto-finalize daemon, admin compute-metrics endpoint) need
    zero churn.
    """
    from services.session_metrics import compute_session_global_metrics
    return compute_session_global_metrics(session_id)


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
    """Trigger computation of global session metrics + stickiness-topic.

    1. Aggregates snippet-level metrics into session-level averages
       (delegated to _compute_session_global_metrics; same logic the
       auto-finalize background trigger uses).
    2. Phase 11 — computes the stickiness-topic metric in one batch
       LLM call (services.stickiness.compute_session_stickiness).

    The legacy ai_alignment LLM evaluation has been replaced by the
    KPI + Stickiness panel and no longer runs from this endpoint.
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

        # Phase 11 — stickiness-topic metric. One additional LLM call
        # extracting a 1-2 word topic per snippet; we count the
        # top-recurring topic and the share of snippets it covers.
        # Best-effort: any failure leaves the columns NULL, the AI
        # alignment LLM call below still runs.
        stickiness_top_topic = None
        stickiness_score = None
        stickiness_distribution = None
        try:
            from services.stickiness import compute_session_stickiness
            (
                stickiness_top_topic,
                stickiness_score,
                stickiness_distribution,
            ) = compute_session_stickiness(active_snippets)
            db.update_session_stickiness(
                session_id=session_id,
                top_topic=stickiness_top_topic,
                score=stickiness_score,
                distribution=stickiness_distribution,
            )
        except Exception as stick_err:
            logger.warning(
                "compute-metrics: stickiness failed (non-fatal): %s",
                stick_err,
            )

        # Phase 11 — the legacy ai_alignment LLM evaluation has been
        # replaced by the KPI + Stickiness panel. We no longer call
        # GPT to produce ai_task_alignment_score/comment; the columns
        # remain in the DB for any historical reads but new writes
        # never land here. Cuts one LLM call per "Compute Metrics".

        # Charisma Awareness Dashboard — overwrite the cached profile
        # so the /results page reflects whatever the admin just
        # recomputed (e.g. after re-extracting snippets or re-running
        # KPI). Best-effort; failure leaves the previous blob in
        # place.
        try:
            from services.charisma_profile import (
                compute_and_persist_charisma_profile,
            )
            # We need the owner id to compute. The session row carries
            # it; if it's somehow absent (anonymous pre-claim session)
            # we skip — there's no user-facing dashboard to render
            # for an un-claimed session anyway.
            session_row = db.v2_get_session_by_id(session_id) or {}
            owner_id = session_row.get("user_id")
            if owner_id:
                compute_and_persist_charisma_profile(
                    session_id=session_id, user_id=str(owner_id),
                )
        except Exception as cp_err:
            logger.warning(
                "compute-metrics: charisma_profile rebuild failed "
                "sid=%s err=%s (non-fatal)",
                session_id, cp_err,
            )

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
            # Phase 11 — stickiness-topic. Frontend renders top_topic
            # + score (as percent) and uses distribution for an
            # optional drill-down.
            "stickiness": {
                "top_topic": stickiness_top_topic,
                "score": stickiness_score,
                "distribution": stickiness_distribution,
            },
            # Phase 17.1 — drift-guard verdict. Admin UI shows a
            # "needs review" banner when needs_admin_review is True;
            # drift_diagnostic carries the why (deviation, threshold,
            # the two numbers being compared) for the explainer panel.
            "drift": {
                "needs_admin_review": bool(m.get("needs_admin_review")),
                "diagnostic": m.get("drift_diagnostic"),
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


# ── Snippet follow-up chat (BE Prompt 0) ──────────────────────────────
#
# Frontend contract: docs/PANEL-STATE-MATRIX.md row LI-4 + LI-5.
#
# After the user clicks agree/disagree on a snippet's `coach_label`, the
# panel POSTs `{snippet_id, user_label}` here and we return one short
# follow-up question to seed LI-5 (snippet follow-up chat).
#
# `user_label` semantic — PIN; see matrix preamble. true ⇒ user AGREES
# with the AI/coach's existing `coach_label` on this snippet. false ⇒
# user DISAGREES. The type (charisma vs stress) lives on
# `snippet.coach_label` / `snippet.snippet_type` and is never overloaded
# onto `user_label`. We surface this contract back to the caller via
# `debug.user_label_interpretation = "agreement"` so any silent
# regression to a "type" semantic fails loud in dev.
#
# Model + decoding spec centralized in services/llm_config.py —
# see SPEC_SNIPPET_FOLLOWUP for the canonical values.


@v2_bp.route("/chat/snippet-followup", methods=["POST"])
@require_auth
def v2_chat_snippet_followup():
    """One-shot follow-up question generator after a user labels a snippet.

    Body (JSON):
      - snippet_id (UUID, required)
      - user_label (bool, required) — AGREEMENT semantic; see module-level
        comment above and ``docs/PANEL-STATE-MATRIX.md`` preamble.

    Response 200 (JSON):
      {
        "followup_text": "<≤2-sentence question>",
        "debug": {
          "model": "gpt-4o-mini",
          "user_label_interpretation": "agreement"
        }
      }

    Errors:
      400 INVALID_INPUT                — missing/malformed fields
      404 NOT_FOUND                    — snippet missing OR not owner-scoped
      422 SNIPPET_CONTEXT_UNAVAILABLE  — snippet lacks admin_comment
      500 V2_ERROR                     — LLM/parse/other failure
    """
    try:
        user_id = request.user_id
        body = request.get_json(silent=True) or {}

        # ── Input validation ──
        snippet_id = (body.get("snippet_id") or "").strip()
        if not snippet_id or not _is_valid_uuid(snippet_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "snippet_id must be a valid UUID",
            }), 400

        user_label_raw = body.get("user_label")
        if not isinstance(user_label_raw, bool):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "user_label must be a boolean (agreement semantic)",
            }), 400
        user_label: bool = user_label_raw

        # ── Owner-scoped fetch ──
        # 404 (not 403) on foreign-owner so we don't leak existence.
        snippet = db.get_snippet_by_id(snippet_id, user_id=user_id)
        if not snippet:
            return jsonify({
                "code": "NOT_FOUND",
                "error": "Snippet not found",
            }), 404

        admin_comment = (snippet.get("admin_comment") or "").strip()
        if not admin_comment:
            # Without the coach's insight the follow-up question would
            # be ungrounded ("how did that make you feel?" style filler).
            # Refuse rather than emit something vapid.
            return jsonify({
                "code": "SNIPPET_CONTEXT_UNAVAILABLE",
                "error": "Snippet has no admin_comment yet",
            }), 422

        transcript = (
            (snippet.get("transcript") or "")
            or (snippet.get("transcription_text") or "")
            or (snippet.get("transcript_text") or "")
            or (snippet.get("transcript_excerpt") or "")
        ).strip()
        coach_label = (snippet.get("coach_label") or "").strip().lower() or None
        snippet_type = (snippet.get("snippet_type") or "").strip().lower() or None
        # Display label = whatever the AI/coach asserted about this
        # snippet, in user-facing words. Fall back through coach_label →
        # snippet_type → "this moment" so the prompt never reads
        # "you {None} this".
        display_label = coach_label or snippet_type or "this moment"

        # ── LLM call ──
        from services.llm import chat_complete
        from services.llm_config import SPEC_SNIPPET_FOLLOWUP

        agreement_phrase = (
            "The user AGREES with the coach's label."
            if user_label
            else "The user DISAGREES with the coach's label."
        )
        system = (
            "You are a warm, curious communication coach. After a "
            "user has agreed or disagreed with a coach's label on a "
            "moment from their own speech, you ask ONE short "
            "follow-up question (≤2 sentences) that invites them to "
            "reflect on why. Anchor your question to the specific "
            "coach insight provided; never ask generic 'how did that "
            "feel' filler. Output strict JSON: "
            '{"followup_text": "<question>"}.'
        )
        user_prompt = (
            f"Coach's label on this snippet: {display_label}\n"
            f"Coach's written insight (admin_comment):\n{admin_comment}\n"
            f"User's spoken transcript on this moment:\n"
            f"{transcript or '(no transcript captured)'}\n\n"
            f"User's response: {agreement_phrase}\n\n"
            "Return strict JSON with a single key followup_text."
        )

        result = chat_complete(
            spec=SPEC_SNIPPET_FOLLOWUP,
            system=system,
            user=user_prompt,
            surface="snippet_followup",
            user_id=str(user_id),
        )
        if result is None:
            # chat_complete already logged the failure reason.
            return jsonify({
                "code": "V2_ERROR",
                "error": "Failed to generate follow-up",
            }), 500

        parsed = result.parsed
        if not isinstance(parsed, dict):
            logger.error(
                "snippet-followup: malformed JSON user=%s snippet=%s raw=%r",
                user_id, snippet_id, result.text[:200],
            )
            return jsonify({
                "code": "V2_ERROR",
                "error": "Coach response was malformed",
            }), 500
        followup_text = (parsed.get("followup_text") or "").strip()

        if not followup_text:
            logger.warning(
                "snippet-followup: empty followup_text user=%s snippet=%s",
                user_id, snippet_id,
            )
            return jsonify({
                "code": "V2_ERROR",
                "error": "Coach returned an empty follow-up",
            }), 500

        return jsonify({
            "followup_text": followup_text,
            "debug": {
                "model": result.model,
                # PIN: never change to "type" without coordinated FE
                # update + matrix-doc preamble update. See module-level
                # comment for the full contract.
                "user_label_interpretation": "agreement",
            },
        }), 200

    except Exception as e:
        logger.error("chat/snippet-followup failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to generate follow-up",
        }), 500


# ── Coaching Directives Queue (Phase Directives-Queue / BE) ───────
#
# User-level 5-step coaching arc. Admin authors a sequence of 5
# questions for one user; the chat / interview surface pops them
# one at a time as the AI question for the next turn, marking
# each exhausted as it fires. When the queue is empty, those
# surfaces fall back to _generate_llm_question.
#
# Replaces the per-user single-question
# user_settings.queued_override_question (removed in Week-1
# cleanup) and the conceptually-misplaced snippet-level
# next_question_1..5 columns (which never shipped to this branch).
#
# Audit: every write logs an INFO line with structured fields
# (user, admin, op, row count). We do NOT route to
# admin_annotations_log — that table's schema captures the RLHF
# (predicted, final) training pair, not admin config changes. The
# application log is the audit trail of record for this surface.


# How many directives the admin authors per arc. Tightened from 5
# to 2 — product spec v2 says two questions is the right size.
# DB CHECK constraint allows 1..5 (legacy), so app-level validation
# is the one enforcing the new ceiling for new arcs.
_DIRECTIVES_ARC_LENGTH = 2
_DIRECTIVES_VALID_POSITIONS = set(range(1, _DIRECTIVES_ARC_LENGTH + 1))


def _validate_directives_rows(rows: object) -> tuple[list, str | None]:
    """Returns (normalized_rows, None) on success or
    ([], error_message) on validation failure. Keeps the validation
    logic out of the route body so the rules are easy to spot and
    test."""
    if not isinstance(rows, list):
        return [], "rows must be an array"
    if len(rows) != _DIRECTIVES_ARC_LENGTH:
        return [], (
            f"rows must contain exactly {_DIRECTIVES_ARC_LENGTH} "
            f"entries (positions 1..{_DIRECTIVES_ARC_LENGTH})"
        )

    seen_positions: set[int] = set()
    out: list[dict] = []
    for idx, r in enumerate(rows):
        if not isinstance(r, dict):
            return [], f"rows[{idx}] must be an object"
        try:
            pos = int(r.get("position"))
        except (TypeError, ValueError):
            return [], (
                f"rows[{idx}].position must be an integer "
                f"1..{_DIRECTIVES_ARC_LENGTH}"
            )
        if pos < 1 or pos > _DIRECTIVES_ARC_LENGTH:
            return [], (
                f"rows[{idx}].position must be in "
                f"[1, {_DIRECTIVES_ARC_LENGTH}], got {pos}"
            )
        if pos in seen_positions:
            return [], f"position {pos} appears more than once"
        seen_positions.add(pos)
        intent_tag = (r.get("intent_tag") or "").strip()
        question = (r.get("question") or "").strip()
        if not intent_tag:
            return [], f"rows[{idx}].intent_tag must be non-empty"
        if not question:
            return [], f"rows[{idx}].question must be non-empty"
        out.append({
            "position": pos,
            "intent_tag": intent_tag,
            "question": question,
        })

    # Positions must cover 1..N exactly (no gaps, no dupes — dupes
    # already caught above; this catches gaps).
    if seen_positions != _DIRECTIVES_VALID_POSITIONS:
        return [], (
            f"positions must cover {sorted(_DIRECTIVES_VALID_POSITIONS)} "
            f"exactly; got {sorted(seen_positions)}"
        )

    # Sort by position so persistence + audit log share one order.
    out.sort(key=lambda r: r["position"])
    return out, None


@v2_bp.route(
    "/admin/users/<user_id>/directives-queue",
    methods=["GET"],
)
@require_admin
def v2_admin_get_directives_queue(user_id):
    """Return the user's current 5-step coaching arc.

    Response 200:
        {
          "rows": [
            {"position": 1, "intent_tag": "warm-up", "question": "...",
             "exhausted": false, "id": "...", "created_at": "...",
             "created_by_admin_id": "..."},
            ...
          ]
        }
    Empty list when no queue exists.
    """
    if not _is_valid_uuid(user_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "user_id must be a valid UUID",
        }), 400
    try:
        rows = db.list_directives_queue(user_id)
        return jsonify({"rows": rows}), 200
    except Exception as e:
        logger.error(
            "admin/directives-queue GET failed user=%s: %s",
            user_id, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to read directives queue",
        }), 500


@v2_bp.route(
    "/admin/users/<user_id>/directives-queue",
    methods=["POST"],
)
@require_admin
def v2_admin_post_directives_queue(user_id):
    """Replace the user's coaching arc with the posted 5 rows.

    Body (JSON):
        {
          "rows": [
            {"position": 1, "intent_tag": "...", "question": "..."},
            ... five entries total ...
          ]
        }

    Atomically (at the application layer): DELETE existing rows
    for this user, then INSERT the new 5. The historical record is
    in the application log (logger.info with structured fields).

    Returns the inserted rows as the response so the FE can
    rebuild its view without an extra GET round-trip.
    """
    if not _is_valid_uuid(user_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "user_id must be a valid UUID",
        }), 400
    try:
        body = request.get_json(silent=True) or {}
        rows_raw = body.get("rows")
        normalized, err = _validate_directives_rows(rows_raw)
        if err:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": err,
            }), 400

        admin_user_id = str(request.user_id) if request.user_id else None
        inserted = db.replace_directives_queue(
            user_id=user_id,
            rows=normalized,
            admin_user_id=admin_user_id,
        )
        if not inserted:
            # Either the table is missing (pre-migration) or the
            # INSERT half-failed after the DELETE. Either way the
            # user now has no queue; surface a recoverable error
            # so the admin retries rather than thinking it worked.
            return jsonify({
                "code": "QUEUE_WRITE_FAILED",
                "error": (
                    "Failed to persist directives queue. The "
                    "user's queue may now be empty — please retry."
                ),
            }), 500

        # Structured audit log. One line per POST, parseable by
        # log-ingesting tools downstream.
        logger.info(
            "directives-queue: REPLACE user=%s admin=%s rows=%d "
            "positions=%s",
            user_id, admin_user_id, len(inserted),
            [r.get("position") for r in inserted],
        )
        return jsonify({"rows": inserted}), 200

    except Exception as e:
        logger.error(
            "admin/directives-queue POST failed user=%s: %s",
            user_id, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to write directives queue",
        }), 500


@v2_bp.route(
    "/admin/users/<user_id>/directives-queue",
    methods=["DELETE"],
)
@require_admin
def v2_admin_delete_directives_queue(user_id):
    """Clear the user's coaching arc. Idempotent — calling on an
    empty queue returns 200 with cleared:true."""
    if not _is_valid_uuid(user_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "user_id must be a valid UUID",
        }), 400
    try:
        admin_user_id = str(request.user_id) if request.user_id else None
        ok = db.clear_directives_queue(user_id)
        if not ok:
            return jsonify({
                "code": "QUEUE_WRITE_FAILED",
                "error": "Failed to clear directives queue",
            }), 500
        logger.info(
            "directives-queue: CLEAR user=%s admin=%s",
            user_id, admin_user_id,
        )
        return jsonify({"cleared": True}), 200
    except Exception as e:
        logger.error(
            "admin/directives-queue DELETE failed user=%s: %s",
            user_id, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to clear directives queue",
        }), 500


@v2_bp.route(
    "/admin/users/<user_id>/directives-queue/suggest",
    methods=["POST"],
)
@require_admin
def v2_admin_suggest_directives_queue(user_id):
    """Generate 5 LLM-suggested directives for this user. NEVER
    persists — the admin reviews the suggestions, edits as
    needed, and then POSTs them via the normal endpoint above.

    Body (JSON, optional):
        {"snippet_id_context": "<uuid>"}  // soft anchor for the arc

    Response 200:
        {
          "rows": [
            {"intent_tag": "...", "question": "..."},
            ... up to 5 entries ...
          ]
        }

    May return ``rows: []`` when:
      - LLM is unavailable (OPENAI_API_KEY missing, etc.)
      - The user has no recent transcripts AND no profile signals
        (cold-start — better to let the admin author manually
        than emit generic filler)
      - The model returns malformed JSON
    The admin UI should render an empty form for manual authoring
    in those cases.
    """
    if not _is_valid_uuid(user_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "user_id must be a valid UUID",
        }), 400
    try:
        body = request.get_json(silent=True) or {}
        snippet_id_context = (
            body.get("snippet_id_context") or ""
        ).strip() or None
        if snippet_id_context and not _is_valid_uuid(snippet_id_context):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "snippet_id_context must be a UUID if provided",
            }), 400

        from services.directive_suggestions import suggest_directive_arc
        rows = suggest_directive_arc(
            user_id=user_id,
            snippet_id_context=snippet_id_context,
        )

        admin_user_id = str(request.user_id) if request.user_id else None
        logger.info(
            "directives-queue: SUGGEST user=%s admin=%s anchor=%s "
            "rows=%d",
            user_id, admin_user_id, snippet_id_context or "-",
            len(rows),
        )
        return jsonify({"rows": rows}), 200

    except Exception as e:
        logger.error(
            "admin/directives-queue/suggest failed user=%s: %s",
            user_id, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to generate suggestions",
        }), 500


# ── Chat-surface consent flags (Phase Single-Slot-Chat) ──────────
#
# GET / PUT /v2/user/sharing-consent — four-flag fan-out (Option A
# from the BE prompt). Each flag corresponds to one YesNoPills
# consent moment in the chat funnel:
#   mic_consent    — microphone permission
#   share_consent  — share recorded snippets with the human coach
#   email_consent  — receive weekly progress emails
#   terms_consent  — accept Terms & Privacy
#
# Storage: nullable booleans on user_settings (added by
# migrations/add_consent_flags_to_user_settings.sql). NULL = not
# yet answered → FE shows the prompt for that slot. TRUE/FALSE =
# answered.
#
# Legacy ``opt_in`` alias (response echo + PUT body acceptance)
# was removed in the Week-1 cleanup. The four canonical fields
# above are the only contract now. Stragglers that PUT ``opt_in``
# get a warning log and the field is silently ignored.

_CONSENT_FIELDS_FE = (
    "mic_consent",
    "share_consent",
    "email_consent",
    "terms_consent",
)


def _shape_consent_response(state: dict) -> dict:
    """Compose the GET/PUT response body from a consent state
    dict (as returned by ``db.get_consent_state``).

    has_answered = any of the four is non-null. FE uses it as a
    coarse "has the user been through the funnel at all" check;
    per-moment gating uses the individual fields.
    """
    has_answered = any(
        state.get(field) is not None
        for field in _CONSENT_FIELDS_FE
    )
    out = {
        "has_answered": has_answered,
        "mic_consent": state.get("mic_consent"),
        "share_consent": state.get("share_consent"),
        "email_consent": state.get("email_consent"),
        "terms_consent": state.get("terms_consent"),
    }
    return out


@v2_bp.route("/user/sharing-consent", methods=["GET"])
@require_auth
def v2_user_get_sharing_consent():
    """Return the user's four-flag consent state.

    Response 200::

        {
          "has_answered": bool,
          "mic_consent":   bool | null,
          "share_consent": bool | null,
          "email_consent": bool | null,
          "terms_consent": bool | null
        }
    """
    try:
        state = db.get_consent_state(str(request.user_id))
        return jsonify(_shape_consent_response(state)), 200
    except Exception as e:
        logger.error(
            "user/sharing-consent GET failed user=%s: %s",
            getattr(request, "user_id", None), e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to read consent state",
        }), 500


@v2_bp.route("/user/sharing-consent", methods=["PUT"])
@require_auth
def v2_user_put_sharing_consent():
    """Update any subset of the four consent flags.

    Body (JSON): any subset of mic_consent / share_consent /
    email_consent / terms_consent (each must be bool).

    Note: the legacy ``opt_in`` alias (which previously mapped to
    ``share_consent``) was removed in the Week-1 cleanup. If a
    caller still sends ``opt_in``, we log a warning and silently
    ignore it — use ``share_consent`` directly.

    Response 200: same shape as GET, echoing the post-write state.
    """
    try:
        user_id = str(request.user_id)
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "Body must be a JSON object",
            }), 400

        # Legacy-caller detection — log once so we can spot
        # FE stragglers still sending opt_in. Silently ignored.
        if "opt_in" in body:
            logger.warning(
                "user/sharing-consent PUT: ignoring legacy "
                "opt_in field user=%s — use share_consent",
                user_id,
            )

        patch: dict = {}
        for field in _CONSENT_FIELDS_FE:
            if field in body:
                val = body[field]
                if val is not None and not isinstance(val, bool):
                    return jsonify({
                        "code": "INVALID_INPUT",
                        "error": f"{field} must be a boolean or null",
                    }), 400
                patch[field] = val

        if not patch:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": (
                    "Body must include at least one of: "
                    "mic_consent, share_consent, email_consent, "
                    "terms_consent"
                ),
            }), 400

        new_state = db.upsert_consent_fields(user_id, patch)
        if new_state is None:
            return jsonify({
                "code": "V2_ERROR",
                "error": "Failed to write consent state",
            }), 500

        logger.info(
            "user/sharing-consent PUT user=%s fields=%s",
            user_id, sorted(patch.keys()),
        )
        return jsonify(_shape_consent_response(new_state)), 200

    except Exception as e:
        logger.error(
            "user/sharing-consent PUT failed user=%s: %s",
            getattr(request, "user_id", None), e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to update consent state",
        }), 500


# ── Public interview funnel: end-of-session signal ────────────────
#
# The frontend BFF at /api/session/finalize forwards here when the
# guest interview funnel ends. Three legitimate reasons today:
#   • threshold  — cold-start 30s aggregate audio threshold reached
#   • max_turns  — legacy fallback when the turn cap fires
#   • user_done  — user clicked "Finish & see results"
#
# Historical note: this endpoint did not exist in this repo. The FE
# BFF was built against it on the assumption that the backend
# wanted an explicit end-of-funnel signal. Without it the FE was
# logging a 404 on every session close. We're shipping the stub now
# so the FE stays clean; the actual end-of-funnel bookkeeping
# happens elsewhere (via upload-answer + the results-publish flow),
# so this handler is intentionally minimal:
#
#   - validates inputs
#   - emits a structured log line so funnel-completion analytics
#     can grep on `funnel: ended sid=... reason=...`
#   - returns 200 — the FE treats failure as non-fatal anyway, so
#     200 just keeps the console quiet
#
# When analytics actually wants this data persisted (per-row in
# Postgres, or piped to a warehouse), extend this handler to write
# to v2_sessions or a dedicated `funnel_events` table. For now,
# log-line analytics is enough.


_INTERVIEW_FINALIZE_VALID_REASONS = {"threshold", "max_turns", "user_done"}


@v2_bp.route("/public/interview/finalize", methods=["POST"])
def v2_public_interview_finalize():
    """End-of-funnel signal from the public interview.

    Body (JSON):
      - guest_session_id     (UUID, required)
      - total_duration_seconds (number, optional)
      - reason               ("threshold" | "max_turns" | "user_done",
                              optional — unknown values are accepted
                              with "unknown" attribution; we'd rather
                              capture the signal than reject a malformed
                              field and lose the log line)

    Response 200: {"status": "ok"}

    Failure modes are non-fatal — the FE already treats a non-200
    here as harmless and routes the user to /results regardless. We
    therefore prefer accepting weird payloads and logging them over
    400-ing and losing the analytics signal.
    """
    try:
        body = request.get_json(silent=True) or {}

        gsid = (body.get("guest_session_id") or "").strip()
        if not gsid or not _is_valid_uuid(gsid):
            # No usable session id → still return 200 (non-fatal), but
            # log loudly so we can spot misconfigured callers.
            logger.warning(
                "interview/finalize: missing/invalid guest_session_id "
                "body=%r — accepted (non-fatal)",
                body,
            )
            return jsonify({"status": "ok"}), 200

        try:
            duration_sec = float(body.get("total_duration_seconds") or 0)
        except (TypeError, ValueError):
            duration_sec = 0.0

        reason_raw = (body.get("reason") or "").strip().lower()
        reason = (
            reason_raw
            if reason_raw in _INTERVIEW_FINALIZE_VALID_REASONS
            else "unknown"
        )

        # Structured log — primary analytics signal until/unless we
        # add a dedicated funnel_events table. Greppable prefix
        # "funnel: ended" so downstream log shippers can fan this
        # out to a metrics aggregator without a code change.
        logger.info(
            "funnel: ended sid=%s reason=%s duration_sec=%.1f"
            "%s",
            gsid,
            reason,
            duration_sec,
            f" raw_reason={reason_raw!r}" if reason == "unknown" else "",
        )

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        logger.error(
            "interview/finalize failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        # Still return 200 — non-fatal contract per the BFF
        # comment. We don't want a backend bug to look like a FE
        # bug in the user's console.
        return jsonify({"status": "ok"}), 200


# ── Coaching intro bubble (Phase Single-Slot-Chat) ────────────────
#
# Frontend contract: after the user labels a snippet (Yes/No) and
# reads the follow-up question, the chat transitions into a new
# official recording session. The intro bubble for that new
# session should feel continuous with what the user just labeled
# — referencing the coach's insight, inviting them to record
# now.
#
# 1–2 sentences, ≤180 chars target, generated by gpt-4o-mini
# grounded in the just-labeled snippet. Falls back to a static
# line when the LLM is unavailable or the snippet lacks
# admin_comment.
#
# Endpoint is owner-scoped: foreign snippet → 404, not 403
# (avoids existence leak — same pattern as snippet-followup).


_COACHING_INTRO_STATIC_FALLBACK = (
    "Now let's record a fresh take and see what shifts. "
    "Tap the mic below when you're ready."
)


@v2_bp.route("/coaching/intro-bubble", methods=["POST"])
@require_auth
def v2_coaching_intro_bubble():
    """Generate a personalized intro line for the new official
    recording session that follows snippet labeling.

    Body (JSON):
      - snippet_id (UUID, required) — the snippet the user just
        labeled. Used to ground the intro in real context.

    Response 200 (always — see fallback contract below):
      {
        "intro_text": "<1–2 sentence intro string>",
        "debug": {
          "model": "gpt-4o-mini",
          "prompt_version": "coaching_intro_v1",
          "source": "llm" | "static_fallback"
        }
      }

    Errors:
      400 INVALID_INPUT  — missing / malformed snippet_id
      404 NOT_FOUND      — snippet missing or not owner-scoped

    Fallback contract: when the LLM call fails OR the snippet is
    missing admin_comment, we still return 200 with the static
    fallback string. The FE NEVER has to handle "intro generation
    failed" — it always gets a usable string.
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

        # Owner-scoped fetch. Foreign / nonexistent → 404 (no
        # existence leak).
        snippet = db.get_snippet_by_id(snippet_id, user_id=user_id)
        if not snippet:
            return jsonify({
                "code": "NOT_FOUND",
                "error": "Snippet not found",
            }), 404

        # ── Directives queue takes priority (Item 7 / Phase 2) ──
        # If the admin has authored a directive arc for this user,
        # pop the next un-exhausted entry and use its question as
        # the intro line — this "smoothly introduces" the admin's
        # next question for the fresh recording session. The
        # admin-authored copy wins over the LLM personalization.
        try:
            directive = db.pop_next_directive(str(user_id))
        except Exception as pop_err:
            logger.warning(
                "coaching/intro-bubble: pop_next_directive failed "
                "user=%s err=%s — falling through to LLM path",
                user_id, pop_err,
            )
            directive = None

        if directive and (directive.get("question") or "").strip():
            logger.info(
                "coaching/intro-bubble: directives-queue HIT "
                "user=%s pos=%s intent=%s",
                user_id, directive.get("position"),
                directive.get("intent_tag"),
            )
            return jsonify({
                "intro_text": directive["question"].strip(),
                "debug": {
                    "model": "gpt-4o-mini",
                    "prompt_version": "coaching_intro_v1",
                    "source": "directives_queue",
                    "directive": {
                        "position": directive.get("position"),
                        "intent_tag": directive.get("intent_tag"),
                    },
                },
            }), 200

        # Try the LLM path. ``generate_intro_line`` returns None on
        # any failure mode — we then drop to the static fallback.
        from services.coaching_intro import (
            generate_intro_line,
            PROMPT_VERSION,
        )
        intro = None
        try:
            intro = generate_intro_line(
                user_id=str(user_id),
                snippet=snippet,
            )
        except Exception as gen_err:
            # Defensive: generate_intro_line is supposed to swallow
            # its own errors, but if anything escapes we still want
            # to return 200 with the fallback.
            logger.warning(
                "coaching/intro-bubble: generator raised user=%s "
                "snippet=%s err=%s — using fallback",
                user_id, snippet_id, gen_err,
            )
            intro = None

        if intro:
            return jsonify({
                "intro_text": intro,
                "debug": {
                    "model": "gpt-4o-mini",
                    "prompt_version": PROMPT_VERSION,
                    "source": "llm",
                },
            }), 200

        # Fallback path — still 200. The FE renders this string
        # exactly like the LLM path; ``debug.source`` lets devs
        # spot fallback rates without consulting backend logs.
        return jsonify({
            "intro_text": _COACHING_INTRO_STATIC_FALLBACK,
            "debug": {
                "model": "gpt-4o-mini",
                "prompt_version": PROMPT_VERSION,
                "source": "static_fallback",
            },
        }), 200

    except Exception as e:
        logger.error(
            "coaching/intro-bubble failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        # Last-resort: still return 200 with the static fallback so
        # the FE flow never breaks on a backend bug. Matches the
        # "always usable string" contract above.
        return jsonify({
            "intro_text": _COACHING_INTRO_STATIC_FALLBACK,
            "debug": {
                "model": "gpt-4o-mini",
                "prompt_version": "coaching_intro_v1",
                "source": "static_fallback",
            },
        }), 200
