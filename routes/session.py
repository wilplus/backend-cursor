from flask import Blueprint, request, jsonify
from auth import require_auth
from services.db import db
import sentry_sdk

session_bp = Blueprint("session", __name__)

@session_bp.route("/start", methods=["POST"])
@require_auth
def start_session():
    """Start a new recording session"""
    try:
        user_id = request.user_id
        
        # Check for active session
        active_session = db.get_active_session(user_id)
        
        if active_session:
            # Return existing active session
            session_id = active_session["id"]
        else:
            # Create new session
            session = db.create_session(user_id)
            if not session:
                return jsonify({"code": "SESSION_CREATE_FAILED", "error": "Failed to create session"}), 500
            session_id = session["id"]
        
        # Get pre-questions
        pre_questions = db.get_pre_questions(limit=3)
        
        return jsonify({
            "session_id": session_id,
            "pre_questions": pre_questions
        }), 200
        
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "SESSION_ERROR", "error": str(e)}), 500

@session_bp.route("/abandon", methods=["POST"])
@require_auth
def abandon_session():
    """Abandon the current active session"""
    try:
        user_id = request.user_id
        
        active_session = db.get_active_session(user_id)
        if not active_session:
            return jsonify({"code": "NO_ACTIVE_SESSION", "error": "No active session found"}), 404
        
        session_id = active_session["id"]
        db.abandon_session(session_id, user_id)
        
        return jsonify({"message": "Session abandoned"}), 200
        
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "ABANDON_ERROR", "error": str(e)}), 500

@session_bp.route("/status", methods=["GET"])
@require_auth
def get_session_status():
    """Get current session status"""
    try:
        user_id = request.user_id
        
        active_session = db.get_active_session(user_id)
        
        if not active_session:
            return jsonify({
                "active": False
            }), 200
        
        return jsonify({
            "active": True,
            "session_id": active_session["id"],
            "pre_completed": active_session.get("pre_questions_completed", False),
            "recording_completed": active_session.get("recording_completed", False),
            "post_completed": active_session.get("post_questions_completed", False),
            "recording_id": active_session.get("recording_id")  # If exists
        }), 200
        
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "STATUS_ERROR", "error": str(e)}), 500
