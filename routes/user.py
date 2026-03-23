from flask import Blueprint, request, jsonify
from auth import require_auth
from services.db import db
import sentry_sdk
import logging

user_bp = Blueprint("user", __name__)
logger = logging.getLogger(__name__)

@user_bp.route("/profile", methods=["GET"])
@require_auth
def get_profile():
    """Get user profile with summary stats"""
    try:
        user_id = request.user_id
        
        profile = db.get_user_profile(user_id)
        
        # Format response
        return jsonify({
            "user": {
                "id": profile.get("user_id", user_id)
            },
            "total_recordings": profile.get("total_recordings", 0),
            "latest_recordings": profile.get("latest_recordings", [])
        }), 200
        
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "PROFILE_ERROR", "error": str(e)}), 500

@user_bp.route("/metric-questions", methods=["GET"])
@require_auth
def get_metric_questions():
    """Get current user's three custom metric questions (and optional pitch_variance config)."""
    try:
        user_id = request.user_id
        data = db.v2_get_user_metric_questions(user_id)
        return jsonify(data), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "METRIC_QUESTIONS_ERROR", "error": str(e)}), 500


@user_bp.route("/metric-questions", methods=["PATCH"])
@require_auth
def update_metric_questions():
    """Update current user's metric_question_1, metric_question_2, metric_question_3 (and optionally pitch_variance_ideal)."""
    try:
        user_id = request.user_id
        data = request.get_json() or {}
        allowed = {"metric_question_1", "metric_question_2", "metric_question_3", "pitch_variance_ideal"}
        payload = {k: data[k] for k in allowed if k in data}
        if not payload:
            out = db.v2_get_user_metric_questions(user_id)
            return jsonify(out), 200
        out = db.v2_update_user_metric_questions(user_id, payload)
        return jsonify(out), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "METRIC_QUESTIONS_ERROR", "error": str(e)}), 500


def _json_safe_profile(obj):
    """Convert profile dict to JSON-serializable types (Supabase may return UUID, datetime)."""
    if obj is None:
        return None
    if hasattr(obj, "isoformat"):  # datetime
        return obj.isoformat()
    if hasattr(obj, "hex"):  # UUID
        return str(obj)
    if isinstance(obj, dict):
        return {k: _json_safe_profile(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe_profile(v) for v in obj]
    return obj


def _empty_sniper_profile(user_id: str):
    return {
        "user_id": user_id,
        "realtime_level": 1,
        "realtime_step": 1,
        "realtime_pitch_baseline_st": None,
        "sessions_with_pitch_count": 0,
    }


def _first_present(data: dict, keys: tuple[str, ...]):
    for key in keys:
        if key in data:
            return data.get(key)
    return None


def _as_float(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError("must be a number")


def _as_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError("must be an integer")


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes"):
            return True
        if lowered in ("false", "0", "no"):
            return False
    raise ValueError("must be a boolean")


def _extract_sniper_completion_payload(data: dict):
    session_means = data.get("session_means") if isinstance(data.get("session_means"), dict) else {}
    payload = {
        "session_id": data.get("session_id"),
        "recording_id": data.get("recording_id"),
        "duration_seconds": _as_float(_first_present(data, ("duration_seconds",))),
        "wpm": _as_float(_first_present(data, ("wpm",))),
        "pause_ms": _as_float(_first_present(data, ("avg_pause_ms", "avgPauseMs"))),
        "dynamic_db": _as_float(_first_present(data, ("dynamic_range_db", "dynamicRangeDb"))),
        "emphasis_per_min": _as_float(_first_present(data, ("emphasis_per_min", "emphasisPerMin"))),
        "energy_ratio": _as_float(_first_present(data, ("energy_ratio", "energyRatio"))),
        "stage_score": _as_float(_first_present(data, ("stage_score",))),
        "voiced_duration_sec": _as_float(_first_present(data, ("voiced_duration_sec",))),
        "pitch_center_st": _as_float(_first_present(data, ("measured_pitch_center_st", "pitch_center_st"))),
        "pitch_frame_count": _as_int(_first_present(data, ("pitch_frame_count",))),
        "frontend_level": _as_int(_first_present(data, ("frontend_level",))),
        "frontend_step": _as_int(_first_present(data, ("frontend_step",))),
        "completed": _as_bool(_first_present(data, ("completed",))),
        "valid_for_progression": _as_bool(_first_present(data, ("valid_for_progression",))),
    }
    if payload["wpm"] is None:
        payload["wpm"] = _as_float(_first_present(session_means, ("paceWpm", "wpm")))
    if payload["pause_ms"] is None:
        payload["pause_ms"] = _as_float(_first_present(session_means, ("avgPauseMs", "avg_pause_ms", "pause_ms")))
    if payload["dynamic_db"] is None:
        payload["dynamic_db"] = _as_float(_first_present(session_means, ("dynamicRangeDb", "dynamic_range_db", "dynamic_db")))
    if payload["emphasis_per_min"] is None:
        payload["emphasis_per_min"] = _as_float(_first_present(session_means, ("emphasisPerMin", "emphasis_per_min")))
    if payload["energy_ratio"] is None:
        payload["energy_ratio"] = _as_float(_first_present(session_means, ("energyRatio", "energy_ratio")))
    if payload["voiced_duration_sec"] is None:
        payload["voiced_duration_sec"] = _as_float(_first_present(session_means, ("voicedDurationSec", "voiced_duration_sec")))
    if payload["pitch_center_st"] is None:
        payload["pitch_center_st"] = _as_float(_first_present(session_means, ("pitchCenterSt", "measured_pitch_center_st", "pitch_center_st")))
    if payload["pitch_frame_count"] is None:
        payload["pitch_frame_count"] = _as_int(_first_present(session_means, ("pitchFrameCount", "pitch_frame_count")))
    return payload


@user_bp.route("/sniper-profile", methods=["GET", "POST"])
@require_auth
def get_sniper_profile():
    """GET current sniper profile; POST completed session summary for adaptive persistence."""
    try:
        user_id = request.user_id
        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            try:
                payload = _extract_sniper_completion_payload(data)
            except ValueError as ve:
                return jsonify({"code": "INVALID_INPUT", "error": str(ve)}), 400

            session_id = payload.get("session_id")
            if not session_id:
                return jsonify({"code": "MISSING_SESSION_ID", "error": "session_id required"}), 400

            session = db.v2_get_session(session_id, user_id)
            if not session:
                return jsonify({"code": "SESSION_NOT_FOUND", "error": "session not found or not yours"}), 404

            recording_id = str(payload["recording_id"]).strip() if payload.get("recording_id") else None
            allowed_recording_ids = {
                str(session.get("recording_1_id")) for _ in [0] if session.get("recording_1_id")
            } | {
                str(session.get("recording_2_id")) for _ in [0] if session.get("recording_2_id")
            }
            if recording_id and allowed_recording_ids and recording_id not in allowed_recording_ids:
                return jsonify({"code": "INVALID_INPUT", "error": "recording_id must belong to this session"}), 400

            profile_before = db.get_sniper_profile_payload(user_id)
            level_before = int(profile_before.get("realtime_level") or 1)
            step_before = int(profile_before.get("realtime_step") or 1)

            db.save_session_sniper_metrics(
                session_id=session_id,
                user_id=user_id,
                wpm=payload.get("wpm"),
                pause_ms=payload.get("pause_ms"),
                dynamic_db=payload.get("dynamic_db"),
                emphasis_per_min=payload.get("emphasis_per_min"),
                energy_ratio=payload.get("energy_ratio"),
                stage_score=payload.get("stage_score"),
                voiced_duration_sec=payload.get("voiced_duration_sec"),
                recording_id=recording_id,
                duration_seconds=payload.get("duration_seconds"),
                pitch_center_st=payload.get("pitch_center_st"),
                pitch_frame_count=payload.get("pitch_frame_count"),
                frontend_level=payload.get("frontend_level"),
                frontend_step=payload.get("frontend_step"),
                completed=payload.get("completed"),
                valid_for_progression=payload.get("valid_for_progression"),
            )

            db.save_session_step_snapshot(
                session_id=session_id,
                user_id=user_id,
                realtime_level_at_session=level_before,
                realtime_step_at_session=step_before,
            )

            completed = payload.get("completed") is True
            valid_for_progression = payload.get("valid_for_progression") is True
            if completed and valid_for_progression:
                if payload.get("pitch_center_st") is not None and payload.get("pitch_frame_count") is not None:
                    db.update_sniper_pitch_baseline_from_session_summary(
                        user_id,
                        pitch_center_st=payload.get("pitch_center_st"),
                        pitch_frame_count=payload.get("pitch_frame_count"),
                    )
            else:
                logger.info(
                    "sniper-profile POST skipped progression-triggerable payload session_id=%s completed=%s valid_for_progression=%s",
                    session_id,
                    payload.get("completed"),
                    payload.get("valid_for_progression"),
                )

            profile = db.get_sniper_profile_payload(user_id)
            metrics = db.get_session_sniper_metrics(session_id)
            return jsonify({
                "status": "ok",
                "profile": _json_safe_profile(profile),
                "session_sniper_metrics": _json_safe_profile(metrics),
            }), 200

        profile = db.get_sniper_profile_payload(user_id)
        out = _json_safe_profile(profile)
        return jsonify(out), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        # Return 200 with defaults so recorder UI can still render Level/Step.
        return jsonify(_empty_sniper_profile(request.user_id)), 200


@user_bp.route("/sniper-profile/session-rating", methods=["PATCH"])
@require_auth
def patch_sniper_session_rating():
    """Set student self-rating (1-5) for a session. Body: { session_id, rating } or legacy { session_id, student_rating_1_10 }."""
    try:
        user_id = request.user_id
        data = request.get_json() or {}
        session_id = data.get("session_id")
        rating = data.get("student_rating_1_10") if data.get("student_rating_1_10") is not None else data.get("rating")
        if not session_id:
            return jsonify({"code": "MISSING_SESSION_ID", "error": "session_id required"}), 400
        if rating is None:
            return jsonify({"code": "MISSING_RATING", "error": "student_rating_1_10 or rating (1-5) required"}), 400
        try:
            r = int(rating)
        except (TypeError, ValueError):
            return jsonify({"code": "INVALID_RATING", "error": "rating must be 1-5"}), 422
        if not (1 <= r <= 5):
            return jsonify({"code": "INVALID_RATING", "error": "rating must be 1-5"}), 422
        ok = db.update_or_set_session_sniper_rating(session_id, user_id, r)
        if not ok:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "session not found or not yours"}), 404
        return jsonify({"status": "ok", "rating": r, "student_rating_1_10": r}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "SESSION_RATING_ERROR", "error": str(e)}), 500


@user_bp.route("/recordings", methods=["GET"])
@require_auth
def get_recordings():
    """Get user recordings with pagination"""
    try:
        user_id = request.user_id
        
        limit = request.args.get("limit", default=10, type=int)
        offset = request.args.get("offset", default=0, type=int)
        
        # Get recordings with pagination info
        result = db.get_user_recordings(user_id, limit=limit, offset=offset)
        
        # Return in format expected by frontend
        return jsonify({
            "recordings": result.get("items", []),
            "total": result.get("total", 0),
            "limit": result.get("limit", limit),
            "offset": result.get("offset", offset),
            "itemsCount": len(result.get("items", []))
        }), 200
        
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "RECORDINGS_ERROR", "error": str(e)}), 500
