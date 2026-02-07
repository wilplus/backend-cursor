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
