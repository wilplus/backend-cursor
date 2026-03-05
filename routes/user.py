from flask import Blueprint, request, jsonify
from auth import require_auth
from services.db import db
import sentry_sdk

user_bp = Blueprint("user", __name__)

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


@user_bp.route("/sniper-profile", methods=["GET"])
@require_auth
def get_sniper_profile():
    """Get current user's sniper profile (user_sniper_profile). Returns {} if none or on error (avoids 500 so frontend flow continues)."""
    try:
        user_id = request.user_id
        profile = db.get_sniper_profile(user_id)
        out = _json_safe_profile(profile) if profile else {}
        return jsonify(out), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        # Return 200 with empty profile so recording flow is not blocked (e.g. table missing, serialization)
        return jsonify({}), 200


@user_bp.route("/sniper-profile/session-rating", methods=["PATCH"])
@require_auth
def patch_sniper_session_rating():
    """Set student self-rating (1–10) for a session. Body: { session_id, student_rating_1_10 } or { session_id, rating }."""
    try:
        user_id = request.user_id
        data = request.get_json() or {}
        session_id = data.get("session_id")
        rating = data.get("student_rating_1_10") if data.get("student_rating_1_10") is not None else data.get("rating")
        if not session_id:
            return jsonify({"code": "MISSING_SESSION_ID", "error": "session_id required"}), 400
        if rating is None:
            return jsonify({"code": "MISSING_RATING", "error": "student_rating_1_10 or rating (1–10) required"}), 400
        try:
            r = int(rating)
        except (TypeError, ValueError):
            return jsonify({"code": "INVALID_RATING", "error": "rating must be 1–10"}), 422
        if not (1 <= r <= 10):
            return jsonify({"code": "INVALID_RATING", "error": "rating must be 1–10"}), 422
        ok = db.update_or_set_session_sniper_rating(session_id, user_id, r)
        if not ok:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "session not found or not yours"}), 404
        return jsonify({"status": "ok", "student_rating_1_10": r}), 200
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
