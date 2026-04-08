"""
V2: admin CRUD only. Student flow is homework only (routes/homework.py).
All /v2/admin/* require auth + admin.
"""
from flask import Blueprint, request, jsonify
from config import Config
from auth import require_auth
from routes.admin import require_admin, is_admin
from services.db import db
from services.email_service import email_service
from services.video_url_validation import validate_video_url
import logging
import sentry_sdk
import json
import time
import mimetypes
import os
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)
v2_bp = Blueprint("v2", __name__, url_prefix="/v2")
config = Config()

_IMPORT_ALLOWED_SOURCE_KINDS = {"internet", "coach_upload", "manual_import"}
_IMPORT_ALLOWED_OVERALL_QUALITY = {"good", "bad", "unclear"}
_IMPORT_ALLOWED_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".webm", ".mp4", ".mpeg", ".mpga", ".ogg", ".oga", ".aac", ".flac"
}


def _coerce_review_score(name: str, value):
    if value is None:
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number")
    if score != score or score in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be a finite number")
    return score


def _is_valid_uuid(val):
    import re
    return bool(re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', str(val or ''), re.I))


def _coerce_review_overall_quality(value):
    if value is None:
        return None
    if isinstance(value, str):
        quality = value.strip()
        if not quality:
            return None
        return quality
    score = _coerce_review_score("overall_quality", value)
    return str(int(score)) if float(score).is_integer() else str(score)


def _coerce_bounded_int(name: str, value, *, min_value: int, max_value: int):
    if value is None:
        raise ValueError(f"{name} is required")
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer between {min_value} and {max_value}")
    if parsed < min_value or parsed > max_value:
        raise ValueError(f"{name} must be between {min_value} and {max_value}")
    return parsed


def _clean_optional_text(value, *, max_len: int | None = None):
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Expected a string value")
    cleaned = value.strip()
    if not cleaned:
        return None
    if max_len is not None and len(cleaned) > max_len:
        raise ValueError(f"Value must be at most {max_len} characters")
    return cleaned


def _validate_import_source_kind(value):
    source_kind = _clean_optional_text(value)
    if not source_kind:
        raise ValueError("source_kind is required")
    if source_kind not in _IMPORT_ALLOWED_SOURCE_KINDS:
        allowed = ", ".join(sorted(_IMPORT_ALLOWED_SOURCE_KINDS))
        raise ValueError(f"source_kind must be one of {allowed}")
    return source_kind


def _validate_import_overall_quality(value):
    overall_quality = _clean_optional_text(value)
    if not overall_quality:
        raise ValueError("overall_quality is required")
    if overall_quality not in _IMPORT_ALLOWED_OVERALL_QUALITY:
        allowed = ", ".join(sorted(_IMPORT_ALLOWED_OVERALL_QUALITY))
        raise ValueError(f"overall_quality must be one of {allowed}")
    return overall_quality


def _validate_import_source_url(value):
    source_url = _clean_optional_text(value, max_len=2048)
    if not source_url:
        return None
    parsed = urlparse(source_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("source_url must be a valid http/https URL")
    return source_url


def _validate_import_audio_file(file_storage):
    if file_storage is None or not (getattr(file_storage, "filename", "") or "").strip():
        raise ValueError("audio_file is required")
    original_name = secure_filename(file_storage.filename or "")
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in _IMPORT_ALLOWED_EXTENSIONS:
        raise ValueError("unsupported audio format")
    return original_name, ext


def _build_admin_import_storage_path(recording_id: str, original_filename: str):
    safe_name = secure_filename(original_filename or "") or "audio"
    ext = os.path.splitext(safe_name)[1].lower() or ".bin"
    now = datetime.now(timezone.utc)
    return f"admin_imports/{now:%Y/%m}/{recording_id}/{uuid.uuid4().hex}{ext}"


def _public_storage_url(bucket: str, path: str):
    supabase_url = (getattr(config, "SUPABASE_URL", "") or "").rstrip("/")
    if not supabase_url or not bucket or not path:
        return ""
    return f"{supabase_url}/storage/v1/object/public/{bucket}/{path}"


def _build_admin_import_source_metadata(*, source_kind: str, source_url, source_title, speaker_label, language_code, transcript_text, import_notes, reviewer_id: str):
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


def _try_queue_admin_import_processing(recording_id: str) -> bool:
    """Hook for a future standalone recording-processing pipeline."""
    return False


def _parse_admin_import_review_patch(data: dict):
    payload = {}
    if "overall_quality" in data:
        payload["overall_quality"] = _validate_import_overall_quality(data.get("overall_quality")) if data.get("overall_quality") is not None else None
    if "confidence_score" in data:
        payload["confidence_score"] = _coerce_bounded_int("confidence_score", data.get("confidence_score"), min_value=1, max_value=10)
    if "coach_style_score" in data:
        payload["coach_style_score"] = _coerce_bounded_int("coach_style_score", data.get("coach_style_score"), min_value=1, max_value=10)
    if "review_notes" in data:
        payload["notes"] = _clean_optional_text(data.get("review_notes"), max_len=5000)
    elif "notes" in data:
        payload["notes"] = _clean_optional_text(data.get("notes"), max_len=5000)
    if "rubric_version" in data:
        rubric_version = _clean_optional_text(data.get("rubric_version"), max_len=255)
        if not rubric_version:
            raise ValueError("rubric_version is required")
        payload["rubric_version"] = rubric_version
    return payload


def _allowed_session_recording_ids(session: dict) -> set[str]:
    ids = set()
    for key in ("recording_1_id",):
        value = session.get(key)
        if value:
            ids.add(str(value))
    return ids


def _validate_session_recording_id(session: dict, recording_id: str | None):
    if recording_id is None:
        return
    allowed_ids = _allowed_session_recording_ids(session)
    if not allowed_ids:
        raise ValueError("This session has no recording to attach")
    if str(recording_id) not in allowed_ids:
        raise ValueError("recording_id must belong to this session")


def _parse_review_payload(data: dict):
    payload = {}
    if "recording_id" in data:
        payload["recording_id"] = str(data.get("recording_id")).strip() if data.get("recording_id") else None
    if "overall_quality" in data:
        payload["overall_quality"] = _coerce_review_overall_quality(data.get("overall_quality"))
    if "confidence_score" in data:
        payload["confidence_score"] = _coerce_review_score("confidence_score", data.get("confidence_score"))
    if "coach_style_score" in data:
        payload["coach_style_score"] = _coerce_review_score("coach_style_score", data.get("coach_style_score"))
    if "notes" in data:
        notes = data.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise ValueError("notes must be a string or null")
        payload["notes"] = notes.strip() if isinstance(notes, str) else None
    if "rubric_version" in data:
        rubric_version = data.get("rubric_version")
        if rubric_version is None or not isinstance(rubric_version, str) or not rubric_version.strip():
            raise ValueError("rubric_version must be a non-empty string")
        payload["rubric_version"] = rubric_version.strip()
    return payload


def _parse_review_annotation_payload(data: dict, *, partial: bool = False):
    payload = {}
    required = () if partial else ("recording_id", "start_ms", "end_ms", "label", "rubric_version")
    for field in required:
        if field not in data:
            raise ValueError(f"{field} is required")
    if "recording_id" in data:
        recording_id = data.get("recording_id")
        if recording_id is None or not str(recording_id).strip():
            raise ValueError("recording_id is required")
        payload["recording_id"] = str(recording_id).strip()
    if "start_ms" in data:
        try:
            payload["start_ms"] = int(data.get("start_ms"))
        except (TypeError, ValueError):
            raise ValueError("start_ms must be an integer")
    if "end_ms" in data:
        try:
            payload["end_ms"] = int(data.get("end_ms"))
        except (TypeError, ValueError):
            raise ValueError("end_ms must be an integer")
    if "label" in data:
        label = data.get("label")
        if label is None or not isinstance(label, str) or not label.strip():
            raise ValueError("label must be a non-empty string")
        payload["label"] = label.strip()
    if "notes" in data:
        notes = data.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise ValueError("notes must be a string or null")
        payload["notes"] = notes.strip() if isinstance(notes, str) else None
    if "rubric_version" in data:
        rubric_version = data.get("rubric_version")
        if rubric_version is None or not isinstance(rubric_version, str) or not rubric_version.strip():
            raise ValueError("rubric_version must be a non-empty string")
        payload["rubric_version"] = rubric_version.strip()
    return payload


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
            if not payload:
                return jsonify({"code": "INVALID_INPUT", "error": "No updatable fields provided"}), 400
            row = db.v2_upsert_student_details(user_id, payload)
            return jsonify({
                "status": "ok",
                "user_id": user_id,
                "name": row.get("name") if row else payload.get("name"),
                "price_per_live_lesson": row.get("price_per_live_lesson") if row else payload.get("price_per_live_lesson"),
                "credits": row.get("credits") if row else payload.get("credits"),
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
        coaching_memory = db.v2_get_student_coaching_memory(user_id)
        tasks = db.v2_get_student_tasks(user_id)
        last_report = db.v2_get_last_report_for_user(user_id)
        sessions = db.v2_get_sessions_with_previews(user_id, limit=50)
        delivered_sessions = [s for s in sessions if s.get("report_delivered")]
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
            "coaching_memory": coaching_memory,
            "realtime_level": sniper_profile.get("realtime_level"),
            "realtime_step": sniper_profile.get("realtime_step"),
            "measured_metrics": measured_metrics,
            "tasks": tasks,
            "last_report": last_report.get("report_text") if last_report else None,
            "last_report_preview": last_report.get("report_preview") if last_report else None,
            "last_report_delivered": bool(last_report.get("report_delivered")) if last_report else False,
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
        # #region agent log
        _log_path = "/Users/arturwillonski/Documents/backend-cursor/.cursor/debug.log"
        try:
            with open(_log_path, "a") as _f:
                _f.write(json.dumps({"message": "PUT overrides request body", "data": {"body_keys": list(data.keys()), "skip_metric_questions": data.get("skip_metric_questions")}, "hypothesisId": "H1", "location": "v2_routes.py:PUT overrides", "timestamp": int(time.time() * 1000)}) + "\n")
        except Exception as _e:
            try:
                with open("/Users/arturwillonski/Documents/backend-cursor/debug_override.log", "a") as _f:
                    _f.write(json.dumps({"message": "PUT overrides request body", "data": {"body_keys": list(data.keys()), "skip_metric_questions": data.get("skip_metric_questions")}, "hypothesisId": "H1", "location": "v2_routes.py:PUT overrides", "timestamp": int(time.time() * 1000), "primary_log_error": str(_e)}) + "\n")
            except Exception:
                pass
        # #endregion
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
        additional_user_ids = body.get("additional_user_ids") or []
        if not isinstance(additional_user_ids, list):
            additional_user_ids = []
        # Deduplicate and exclude the primary user
        additional_user_ids = [uid for uid in additional_user_ids if isinstance(uid, str) and uid != user_id]

        student_email = db.get_user_email_from_auth(user_id)
        if not student_email or not student_email.strip():
            return jsonify({"code": "NO_EMAIL", "error": "Student has no email in auth"}), 400
        # Store coach message (and optional video URL) so GET session/status can return tutor_video_description
        if video_url is not None or video_description is not None:
            db.v2_set_pending_tutor_video(user_id, video_url, video_description)
        result = email_service.send_assignment_to_student(
            to_email=student_email.strip(),
            frontend_url=config.FRONTEND_URL,
            video_url=video_url,
            video_description=video_description,
            student_name=student_email.strip(),
        )
        if result.get("status") == "failed":
            return jsonify({"code": "EMAIL_FAILED", "error": result.get("error", "Failed to send email")}), 500
        sniper_profile = db.get_sniper_profile_payload(user_id)
        # Treat successful coach action as the unlock trigger for the student UI,
        # even if email delivery is pending/disabled in this environment.
        db.v2_mark_tutor_feedback_sent_for_user(user_id)

        # Send to additional (similar) students
        additional_results = []
        for extra_uid in additional_user_ids:
            try:
                extra_email = db.get_user_email_from_auth(extra_uid)
                if not extra_email or not extra_email.strip():
                    additional_results.append({"user_id": extra_uid, "status": "skipped", "reason": "no_email"})
                    continue
                if video_url is not None or video_description is not None:
                    db.v2_set_pending_tutor_video(extra_uid, video_url, video_description)
                extra_result = email_service.send_assignment_to_student(
                    to_email=extra_email.strip(),
                    frontend_url=config.FRONTEND_URL,
                    video_url=video_url,
                    video_description=video_description,
                    student_name=extra_email.strip(),
                )
                db.v2_mark_tutor_feedback_sent_for_user(extra_uid)
                additional_results.append({"user_id": extra_uid, "status": extra_result.get("status", "unknown"), "email": extra_email.strip()})
            except Exception as extra_err:
                logger.warning("send-assignment: additional user %s failed: %s", extra_uid, extra_err)
                additional_results.append({"user_id": extra_uid, "status": "failed", "reason": str(extra_err)})

        return jsonify({
            "status": "ok",
            "message": "Assignment sent",
            "sent": result.get("sent", False),
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
            session["recording_review"] = db.v2_get_recording_review(session_id)
            session["review_annotations_count"] = len(db.v2_list_recording_review_annotations(session_id))
            return jsonify({"session": session}), 200
        # PATCH: report_grade / report_comment / coach_override_score
        data = request.get_json() or {}
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


@v2_bp.route("/admin/students/<user_id>/sessions/<session_id>/review", methods=["GET", "PUT", "PATCH"])
@require_admin
def v2_admin_student_session_review(user_id, session_id):
    """Admin-only ML review labels for a completed session."""
    try:
        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404

        if request.method == "GET":
            return jsonify({
                "review": db.v2_get_recording_review(session_id),
                "allowed_recording_ids": sorted(_allowed_session_recording_ids(session)),
            }), 200

        existing = db.v2_get_recording_review(session_id)
        data = request.get_json(silent=True) or {}
        try:
            payload = _parse_review_payload(data)
            if "recording_id" in payload:
                _validate_session_recording_id(session, payload.get("recording_id"))
            if not payload:
                return jsonify({"code": "INVALID_INPUT", "error": "No review fields provided"}), 400
            if not existing and "rubric_version" not in payload:
                return jsonify({"code": "INVALID_INPUT", "error": "rubric_version is required when creating a review"}), 400
        except ValueError as ve:
            return jsonify({"code": "INVALID_INPUT", "error": str(ve)}), 400

        review = db.v2_upsert_recording_review(session_id, request.user_id, payload)
        return jsonify({"status": "ok", "review": review}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/sessions/<session_id>/review-annotations", methods=["GET", "POST"])
@require_admin
def v2_admin_student_session_review_annotations(user_id, session_id):
    """Admin-only time-span review labels for a session recording."""
    try:
        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404

        if request.method == "GET":
            return jsonify({"annotations": db.v2_list_recording_review_annotations(session_id)}), 200

        data = request.get_json(silent=True) or {}
        try:
            payload = _parse_review_annotation_payload(data, partial=False)
            _validate_session_recording_id(session, payload.get("recording_id"))
            if payload["start_ms"] < 0:
                return jsonify({"code": "INVALID_INPUT", "error": "start_ms must be >= 0"}), 400
            if payload["end_ms"] <= payload["start_ms"]:
                return jsonify({"code": "INVALID_INPUT", "error": "end_ms must be greater than start_ms"}), 400
        except ValueError as ve:
            return jsonify({"code": "INVALID_INPUT", "error": str(ve)}), 400

        annotation = db.v2_create_recording_review_annotation(session_id, request.user_id, payload)
        return jsonify({"status": "ok", "annotation": annotation}), 201
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/sessions/<session_id>/review-annotations/<annotation_id>", methods=["PATCH", "DELETE"])
@require_admin
def v2_admin_student_session_review_annotation_detail(user_id, session_id, annotation_id):
    """Admin-only update/delete for one time-span review annotation."""
    try:
        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404

        annotation = db.v2_get_recording_review_annotation(annotation_id)
        if not annotation or str(annotation.get("session_id")) != str(session_id):
            return jsonify({"code": "ANNOTATION_NOT_FOUND", "error": "Annotation not found"}), 404

        if request.method == "DELETE":
            db.v2_delete_recording_review_annotation(annotation_id)
            return jsonify({"status": "ok", "deleted": True}), 200

        data = request.get_json(silent=True) or {}
        try:
            payload = _parse_review_annotation_payload(data, partial=True)
            if not payload:
                return jsonify({"code": "INVALID_INPUT", "error": "No annotation fields provided"}), 400
            if "recording_id" in payload:
                _validate_session_recording_id(session, payload.get("recording_id"))
            next_start = payload.get("start_ms", int(annotation.get("start_ms") or 0))
            next_end = payload.get("end_ms", int(annotation.get("end_ms") or 0))
            if next_start < 0:
                return jsonify({"code": "INVALID_INPUT", "error": "start_ms must be >= 0"}), 400
            if next_end <= next_start:
                return jsonify({"code": "INVALID_INPUT", "error": "end_ms must be greater than start_ms"}), 400
        except ValueError as ve:
            return jsonify({"code": "INVALID_INPUT", "error": str(ve)}), 400

        updated = db.v2_update_recording_review_annotation(annotation_id, request.user_id, payload)
        if not updated:
            return jsonify({"code": "ANNOTATION_NOT_FOUND", "error": "Annotation not found"}), 404
        return jsonify({"status": "ok", "annotation": updated}), 200
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


@v2_bp.route("/admin/recordings/imports", methods=["GET"])
@require_admin
def v2_admin_recordings_imports():
    """List imported recordings for the admin ML page."""
    try:
        try:
            limit = int(request.args.get("limit", 50))
        except (TypeError, ValueError):
            return jsonify({"code": "INVALID_INPUT", "error": "limit must be an integer"}), 400
        try:
            offset = int(request.args.get("offset", 0))
        except (TypeError, ValueError):
            return jsonify({"code": "INVALID_INPUT", "error": "offset must be an integer"}), 400
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        rows = db.v2_list_admin_import_recordings(limit=limit, offset=offset)
        recordings = []
        for row in rows:
            playback_url = None
            storage_path = (row.get("storage_path") or "").strip()
            if storage_path:
                try:
                    playback_url = db.create_signed_url(config.AUDIO_BUCKET_NAME, storage_path, config.SIGNED_URL_EXPIRY_SECONDS)
                except Exception:
                    playback_url = _public_storage_url(config.AUDIO_BUCKET_NAME, storage_path) or None
            recordings.append({
                "id": row.get("id"),
                "recording_id": row.get("id"),
                "created_at": row.get("created_at"),
                "duration": row.get("duration"),
                "duration_seconds": row.get("duration_seconds"),
                "audio_url": playback_url,
                "transcription_text": row.get("transcription_text"),
                "recording_origin": row.get("recording_origin"),
                "source_metadata": row.get("source_metadata") or {},
                "review": row.get("review"),
            })
        return jsonify({
            "recordings": recordings,
            "limit": limit,
            "offset": offset,
            "count": len(recordings),
        }), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/recordings/import", methods=["POST"])
@require_admin
def v2_admin_recordings_import():
    """Admin-only multipart recording ingestion for ML labeling."""
    try:
        if "audio_file" not in request.files:
            return jsonify({"code": "AUDIO_FILE_REQUIRED", "error": "audio_file is required"}), 400

        audio_file = request.files.get("audio_file")
        try:
            original_name, _ = _validate_import_audio_file(audio_file)
        except ValueError as ve:
            message = str(ve)
            if message == "unsupported audio format":
                return jsonify({"code": "UNSUPPORTED_AUDIO_FORMAT", "error": "unsupported audio format"}), 415
            return jsonify({"code": "AUDIO_FILE_REQUIRED", "error": message}), 400

        max_bytes = int((getattr(config, "MAX_AUDIO_SIZE_MB", 25) or 25) * 1024 * 1024)
        content_length = request.content_length or 0
        if content_length and content_length > max_bytes:
            return jsonify({"code": "FILE_TOO_LARGE", "error": f"audio_file exceeds {config.MAX_AUDIO_SIZE_MB}MB limit"}), 413

        form = request.form
        try:
            source_kind = _validate_import_source_kind(form.get("source_kind"))
            overall_quality = _validate_import_overall_quality(form.get("overall_quality"))
            confidence_score = _coerce_bounded_int("confidence_score", form.get("confidence_score"), min_value=1, max_value=10)
            coach_style_score = _coerce_bounded_int("coach_style_score", form.get("coach_style_score"), min_value=1, max_value=10)
            rubric_version = _clean_optional_text(form.get("rubric_version"), max_len=255)
            if not rubric_version:
                raise ValueError("rubric_version is required")
            source_url = _validate_import_source_url(form.get("source_url"))
            source_title = _clean_optional_text(form.get("source_title"), max_len=500)
            speaker_label = _clean_optional_text(form.get("speaker_label"), max_len=255)
            language_code = _clean_optional_text(form.get("language_code"), max_len=32)
            transcript_text = _clean_optional_text(form.get("transcript_text"), max_len=50000)
            import_notes = _clean_optional_text(form.get("import_notes"), max_len=5000)
            review_notes = _clean_optional_text(form.get("review_notes"), max_len=5000)
        except ValueError as ve:
            msg = str(ve)
            code = "INVALID_IMPORT_PAYLOAD"
            if msg.startswith("source_kind"):
                code = "INVALID_SOURCE_KIND"
            elif msg.startswith("overall_quality"):
                code = "INVALID_OVERALL_QUALITY"
            elif msg.startswith("confidence_score"):
                code = "INVALID_CONFIDENCE_SCORE"
            elif msg.startswith("coach_style_score"):
                code = "INVALID_COACH_STYLE_SCORE"
            elif msg.startswith("rubric_version"):
                code = "MISSING_RUBRIC_VERSION"
            elif msg.startswith("source_url"):
                code = "INVALID_SOURCE_URL"
            return jsonify({"code": code, "error": msg}), 422

        file_bytes = audio_file.read()
        if not file_bytes:
            return jsonify({"code": "INVALID_MULTIPART", "error": "audio_file is empty"}), 400
        if len(file_bytes) > max_bytes:
            return jsonify({"code": "FILE_TOO_LARGE", "error": f"audio_file exceeds {config.MAX_AUDIO_SIZE_MB}MB limit"}), 413

        recording_id = str(uuid.uuid4())
        storage_path = _build_admin_import_storage_path(recording_id, original_name)
        content_type = (audio_file.mimetype or mimetypes.guess_type(original_name)[0] or "application/octet-stream").strip()

        try:
            db.upload_audio(config.AUDIO_BUCKET_NAME, storage_path, file_bytes, content_type=content_type)
        except Exception as upload_err:
            logger.warning("Admin recording import upload failed: %s", upload_err, exc_info=True)
            return jsonify({"code": "IMPORT_UPLOAD_FAILED", "error": "Failed to store uploaded audio"}), 500

        source_metadata = _build_admin_import_source_metadata(
            source_kind=source_kind,
            source_url=source_url,
            source_title=source_title,
            speaker_label=speaker_label,
            language_code=language_code,
            transcript_text=transcript_text,
            import_notes=import_notes,
            reviewer_id=str(request.user_id),
        )
        public_audio_url = _public_storage_url(config.AUDIO_BUCKET_NAME, storage_path)

        try:
            recording = db.create_recording({
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
            })
        except Exception as create_err:
            logger.warning("Admin recording import create_recording failed: %s", create_err, exc_info=True)
            return jsonify({"code": "IMPORT_RECORDING_CREATE_FAILED", "error": str(create_err)}), 500

        if not recording:
            return jsonify({"code": "IMPORT_RECORDING_CREATE_FAILED", "error": "Failed to create recording row"}), 500

        try:
            review = db.v2_create_recording_review_for_recording(
                recording_id,
                str(request.user_id),
                {
                    "overall_quality": overall_quality,
                    "confidence_score": confidence_score,
                    "coach_style_score": coach_style_score,
                    "notes": review_notes,
                    "rubric_version": rubric_version,
                },
            )
        except Exception as review_err:
            logger.warning("Admin recording import review creation failed: %s", review_err, exc_info=True)
            return jsonify({"code": "IMPORT_REVIEW_CREATE_FAILED", "error": str(review_err)}), 500

        playback_url = None
        try:
            playback_url = db.create_signed_url(config.AUDIO_BUCKET_NAME, storage_path, config.SIGNED_URL_EXPIRY_SECONDS)
        except Exception as playback_err:
            logger.warning("Admin recording import signed URL failed: %s", playback_err)
            playback_url = public_audio_url or None

        queued = False
        try:
            queued = _try_queue_admin_import_processing(recording_id)
        except Exception as queue_err:
            logger.warning("Admin recording import queue failed: %s", queue_err, exc_info=True)

        message = (
            "Recording imported and queued for processing."
            if queued else
            "Recording imported and labeled."
        )
        return jsonify({
            "status": "ok",
            "recording_id": recording_id,
            "review_id": review.get("id") if isinstance(review, dict) else None,
            "playback_url": playback_url,
            "message": message,
        }), 201
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "IMPORT_FAILED", "error": str(e)}), 500


@v2_bp.route("/admin/recordings/<recording_id>", methods=["GET"])
@require_admin
def v2_admin_recording_detail(recording_id):
    """Return one imported/admin recording with metadata and latest review."""
    try:
        if not _is_valid_uuid(recording_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid recording ID"}), 400
        recording = db.get_recording(recording_id, None)
        if not recording:
            return jsonify({"code": "RECORDING_NOT_FOUND", "error": "Recording not found"}), 404
        review = db.v2_get_recording_review_by_recording(recording_id)
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
            "review": review,
            "playback_url": playback_url,
        }), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/recordings/<recording_id>/review", methods=["PATCH"])
@require_admin
def v2_admin_recording_review_patch(recording_id):
    """Create or update the latest ML review for an imported/admin recording."""
    try:
        if not _is_valid_uuid(recording_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid recording ID"}), 400
        recording = db.get_recording(recording_id, None)
        if not recording:
            return jsonify({"code": "RECORDING_NOT_FOUND", "error": "Recording not found"}), 404
        data = request.get_json(silent=True) or {}
        try:
            payload = _parse_admin_import_review_patch(data)
        except ValueError as ve:
            msg = str(ve)
            code = "INVALID_INPUT"
            if msg.startswith("overall_quality"):
                code = "INVALID_OVERALL_QUALITY"
            elif msg.startswith("confidence_score"):
                code = "INVALID_CONFIDENCE_SCORE"
            elif msg.startswith("coach_style_score"):
                code = "INVALID_COACH_STYLE_SCORE"
            elif msg.startswith("rubric_version"):
                code = "MISSING_RUBRIC_VERSION"
            return jsonify({"code": code, "error": msg}), 422
        if not payload:
            return jsonify({"code": "INVALID_INPUT", "error": "No review fields provided"}), 400
        existing = db.v2_get_recording_review_by_recording(recording_id)
        if not existing and "rubric_version" not in payload:
            return jsonify({"code": "MISSING_RUBRIC_VERSION", "error": "rubric_version is required when creating a review"}), 422
        review = db.v2_upsert_recording_review_for_recording(recording_id, str(request.user_id), payload)
        return jsonify({
            "status": "ok",
            "recording_id": recording_id,
            "review": review,
        }), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


# ---------- Admin: tasks_pool (global pool) + tasks (per student) ----------


def _admin_tasks_pool_list_payload(data: list):
    return {"tasks_pool": data}


def _admin_tasks_pool_row_payload(row):
    if row is None:
        return {"tasks_pool": None}
    return {"tasks_pool": row}


@v2_bp.route("/admin/tasks-pool", methods=["GET"])
@v2_bp.route("/admin/task-pool", methods=["GET"])
@v2_bp.route("/admin/task-warm-up-pool", methods=["GET"])
@require_admin
def v2_admin_tasks_pool_list():
    try:
        data = db.v2_get_task_pool()
    except Exception:
        data = []
    return jsonify(_admin_tasks_pool_list_payload(data)), 200


@v2_bp.route("/admin/tasks-pool", methods=["POST"])
@v2_bp.route("/admin/task-pool", methods=["POST"])
@v2_bp.route("/admin/task-warm-up-pool", methods=["POST"])
@require_admin
def v2_admin_tasks_pool_create():
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
        row = db.v2_insert_task_pool(payload)
        return jsonify(_admin_tasks_pool_row_payload(row)), 201
    except Exception as e:
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
    payload = {k: data[k] for k in ("text", "order_index", "max_performance_score") if k in data}
    if "max_performance_score" in payload:
        try:
            payload["max_performance_score"] = float(payload["max_performance_score"])
        except (TypeError, ValueError):
            payload["max_performance_score"] = 1.0
    if not payload:
        row = db.v2_get_task_pool_by_id(pool_id)
    else:
        row = db.v2_update_task_pool(pool_id, payload)
    if not row:
        return jsonify({"error": "Pool task not found"}), 404
    return jsonify(_admin_tasks_pool_row_payload(row)), 200


@v2_bp.route("/admin/tasks-pool/<pool_id>", methods=["DELETE"])
@v2_bp.route("/admin/task-pool/<pool_id>", methods=["DELETE"])
@v2_bp.route("/admin/task-warm-up-pool/<pool_id>", methods=["DELETE"])
@require_admin
def v2_admin_tasks_pool_delete(pool_id):
    try:
        db.v2_delete_task_pool(pool_id)
    except Exception:
        pass
    return jsonify({"status": "ok"}), 200


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
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400
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
        )
        return jsonify(result), 201
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as err:
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
                or s.get("warm_up_task_text")  # legacy preview column name on old rows
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
        override_profile = (body.get("coach_override_profile") or "").strip() or None
        justification = (body.get("profile_override_justification") or "").strip() or None
        reason_chip = (body.get("reason_chip") or "").strip() or None
        refresh_student_profile_state(user_id)
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
        display_profile = (updated.get("coach_override_profile") or "").strip() or (updated.get("behavioral_profile") or "").strip() or "Unclassified"
        return jsonify({"status": "ok", "display_profile": display_profile, "profile": updated}), 200
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


def _serialize_copilot_draft(row):
    payload = _draft_payload(row)
    return {
        "id": str(row.get("id") or ""),
        "student_id": str(row.get("user_id") or ""),
        "session_id": row.get("session_id"),
        "status": _draft_state_ui(row),
        "ai_insight": payload.get("ai_insight"),
        "corrected_insight": payload.get("corrected_insight"),
        "good_as_is": payload.get("good_as_is"),
        "grade_draft": payload.get("grade_draft"),
        "comment_draft": payload.get("comment_draft"),
        "task_draft": payload.get("task_draft") or payload.get("task_text") or row.get("master_task_text"),
        "email_draft": payload.get("email_draft") or payload.get("email_message") or payload.get("homework_comment"),
        "script_draft": payload.get("script_draft") or payload.get("video_script"),
        "reason_chip_required": bool(payload.get("reason_chip_required", False)),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
    }


def _pick_student_draft(user_id: str, *, session_id: str | None = None, draft_id: str | None = None, include_sent: bool = False):
    if draft_id:
        row = db.get_admin_student_send_draft(draft_id, user_id)
        if row and (include_sent or str(row.get("status") or "").lower() != "sent"):
            return row
        if row and include_sent:
            return row
    q = db.client.table("admin_student_send_drafts").select("*").eq("user_id", user_id).order("updated_at", desc=True).order("created_at", desc=True)
    if session_id:
        q = q.eq("session_id", session_id)
    rows = q.limit(20).execute().data or []
    if include_sent and rows:
        return rows[0]
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
    if sess:
        coach_insight = (sess.get("coach_insight") or "").strip()
        report_comment = (sess.get("report_comment") or "").strip()
        report_grade = sess.get("report_grade")
        score_for_display = sess.get("score_for_display")

    task_text = ""
    if sess:
        task_text = (sess.get("session_task_text") or sess.get("warm_up_task_text") or "").strip()
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

    meta = {
        "backfilled_at": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
    }
    if score_for_display is not None:
        try:
            meta["score_for_display"] = float(score_for_display)
        except (TypeError, ValueError):
            meta["score_for_display"] = score_for_display

    payload = {
        "state": "Draft",
        "ai_insight": coach_insight or None,
        "grade_draft": report_grade,
        "comment_draft": report_comment or None,
        "task_draft": master_task_text,
        "metadata": meta,
    }

    return {
        "user_id": user_id,
        "session_id": session_id,
        "cohort_profile": profile,
        "cohort_stage": stage,
        "master_task_text": master_task_text,
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
            items.append(
                {
                    "id": row.get("id"),
                    "draft_id": row.get("id"),
                    "user_id": uid,
                    "email": db.get_user_email_from_auth(uid) if uid else None,
                    "session_id": row.get("session_id"),
                    "cohort_profile": row.get("cohort_profile"),
                    "cohort_stage": row.get("cohort_stage"),
                    "master_task_text": row.get("master_task_text"),
                    "status": row.get("status"),
                    "updated_at": row.get("updated_at"),
                    "created_at": row.get("created_at"),
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
        baseline_uids = db.v2_list_all_auth_user_ids(cap=cap_ms)
        if not baseline_uids:
            baseline_uids = db.list_recent_student_ids(limit=cap_ms)
        for uid in baseline_uids:
            if not uid:
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
            if not uid:
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

        rows = db.list_admin_student_send_drafts(status=None)
        profile_cache = {}
        filtered = []
        for row in rows:
            uid = str(row.get("user_id") or "")
            if not uid:
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
                    "session_id": row.get("session_id"),
                    "queue_position": i,
                    "state": _draft_state_ui(row),
                    "draft_count": int((counts.get(uid) or {}).get("Draft", 0)),
                    "ready_count": int((counts.get(uid) or {}).get("Ready", 0)),
                    "sent_count": int((counts.get(uid) or {}).get("Sent", 0)),
                    "profile": {
                        "name": details.get("name"),
                        "email": email,
                        "stage": str(stage),
                        "justification": profile_row.get("behavioral_profile_justification"),
                        "canonical_score_for_display": latest_session.get("score_for_display"),
                    },
                }
            )

        uids_in_queue = {str(it["student_id"]) for it in items}
        extra_uids = db.v2_list_all_auth_user_ids(cap=cap_ms)
        if not extra_uids:
            extra_uids = db.list_recent_student_ids(limit=cap_ms)
        for uid in extra_uids:
            if not uid or uid in uids_in_queue:
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
                    "session_id": None,
                    "queue_position": len(items),
                    "state": "Draft",
                    "draft_count": 0,
                    "ready_count": 0,
                    "sent_count": 0,
                    "profile": {
                        "name": details.get("name"),
                        "email": email,
                        "stage": str(stage),
                        "justification": profile_row.get("behavioral_profile_justification"),
                        "canonical_score_for_display": latest_session.get("score_for_display"),
                    },
                }
            )
            uids_in_queue.add(uid)

        return jsonify({"students": items, "count": len(items)}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/copilot/students/<user_id>/drafts", methods=["GET", "PUT"])
@require_admin
def v2_admin_copilot_student_drafts(user_id):
    try:
        if request.method == "GET":
            session_id = (request.args.get("session_id") or "").strip() or None
            q = db.client.table("admin_student_send_drafts").select("*").eq("user_id", user_id).order("updated_at", desc=True).order("created_at", desc=True)
            if session_id:
                q = q.eq("session_id", session_id)
            rows = q.limit(50).execute().data or []
            return jsonify({"drafts": [_serialize_copilot_draft(r) for r in rows]}), 200

        body = request.get_json(silent=True) or {}
        session_id = (body.get("session_id") or "").strip() or None
        draft_id = (body.get("draft_id") or "").strip() or None
        row = _pick_student_draft(user_id, session_id=session_id, draft_id=draft_id, include_sent=False)
        if not row:
            return jsonify({"code": "DRAFT_NOT_FOUND", "error": "No editable draft found for student"}), 404
        payload = _draft_payload(row)
        for k in ("grade_draft", "comment_draft", "task_draft", "email_draft", "script_draft", "metadata"):
            if k in body:
                payload[k] = body.get(k)
        if "reason_chips" in body:
            payload["reason_chips"] = body.get("reason_chips")
        if "reason_chip_custom" in body:
            payload["reason_chip_custom"] = body.get("reason_chip_custom")
        updated = (
            db.client.table("admin_student_send_drafts")
            .update({"draft_payload": payload, "updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", row.get("id"))
            .eq("user_id", user_id)
            .execute()
        )
        out = updated.data[0] if updated.data else row
        return jsonify({"status": "ok", "draft": _serialize_copilot_draft(out)}), 200
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
            return jsonify({"code": "DRAFT_NOT_FOUND", "error": "Draft not found"}), 404
        payload = _draft_payload(row)
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
            return jsonify({"code": "DRAFT_NOT_FOUND", "error": "Draft not found"}), 404
        if str(row.get("status") or "").lower() == "sent":
            return jsonify({"status": "ok", "state": "Sent", "sent_at": row.get("sent_at")}), 200
        payload = _draft_payload(row)
        student_email = (db.get_user_email_from_auth(user_id) or "").strip()
        if not student_email:
            return jsonify({"code": "NO_EMAIL", "error": "Student has no email in auth"}), 400
        send_result = email_service.send_assignment_to_student(
            to_email=student_email,
            frontend_url=config.FRONTEND_URL,
            video_description=(payload.get("email_draft") or payload.get("email_message") or payload.get("homework_comment") or ""),
            student_name=student_email,
        )
        if send_result.get("status") == "failed":
            return jsonify({"code": "EMAIL_FAILED", "error": send_result.get("error", "send failed")}), 500
        updated = db.mark_admin_student_send_draft_sent(str(row.get("id")), user_id, request.user_id) or row
        return jsonify({"status": "ok", "state": "Sent", "sent_at": updated.get("sent_at"), "draft": _serialize_copilot_draft(updated)}), 200
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
        target_ids = body.get("user_ids")
        if target_ids is not None and not isinstance(target_ids, list):
            return jsonify({"code": "INVALID_INPUT", "error": "user_ids must be an array"}), 400
        target_ids = {str(x) for x in (target_ids or []) if str(x).strip()}

        rows = []
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
            rows.append(
                {
                    "user_id": uid,
                    "session_id": latest_session.get("id"),
                    "cohort_profile": profile,
                    "cohort_stage": int(stage),
                    "master_task_text": master_task_text,
                    "draft_payload": {
                        "task_text": master_task_text,
                        "email_message": (body.get("email_message") or "").strip() or None,
                        "video_script": (body.get("video_script") or "").strip() or None,
                        "homework_comment": (body.get("homework_comment") or "").strip() or None,
                    },
                    "status": "pending",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )

        inserted = db.insert_admin_student_send_drafts(rows)
        return jsonify({"status": "ok", "inserted_count": len(inserted), "drafts": inserted}), 201
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500


@v2_bp.route("/admin/students/<user_id>/drafts/<draft_id>/approve-send", methods=["POST"])
@require_admin
def v2_admin_student_draft_approve_send(user_id, draft_id):
    try:
        row = db.get_admin_student_send_draft(draft_id, user_id)
        if not row:
            return jsonify({"code": "DRAFT_NOT_FOUND", "error": "Draft not found"}), 404
        if row.get("status") == "sent":
            return jsonify({"status": "ok", "already_sent": True, "draft_id": draft_id}), 200
        payload = row.get("draft_payload") if isinstance(row.get("draft_payload"), dict) else {}
        student_email = (db.get_user_email_from_auth(user_id) or "").strip()
        if not student_email:
            return jsonify({"code": "NO_EMAIL", "error": "Student has no email in auth"}), 400
        send_result = email_service.send_assignment_to_student(
            to_email=student_email,
            frontend_url=config.FRONTEND_URL,
            video_description=(payload.get("email_message") or payload.get("homework_comment") or ""),
            student_name=student_email,
        )
        if send_result.get("status") == "failed":
            return jsonify({"code": "EMAIL_FAILED", "error": send_result.get("error", "send failed")}), 500
        updated = db.mark_admin_student_send_draft_sent(draft_id, user_id, request.user_id)
        return jsonify({"status": "ok", "draft": updated, "email": send_result}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": str(e)}), 500
