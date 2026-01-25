from flask import Blueprint, request, jsonify
from auth import require_auth
from services.db import db
from services.question_service import (
    calculate_cursor, determine_mode, select_commands, generate_question_from_command
)
import sentry_sdk
import logging

logger = logging.getLogger(__name__)
session_bp = Blueprint("session", __name__)

@session_bp.route("/start", methods=["POST"])
@require_auth
def start_session():
    """Start a new recording session with optional questionnaire"""
    try:
        user_id = request.user_id
        data = request.get_json() or {}
        questionnaire = data.get("questionnaire")
        
        # Check for active session
        active_session = db.get_active_session(user_id)
        
        if active_session:
            # Return existing active session
            session_id = active_session["id"]
            cursor = active_session.get("cursor")
            mode = active_session.get("mode")
            
            # Get existing pre-questions for this session (if stored)
            # For now, we'll generate new ones based on stored cursor/mode
            if cursor is not None and mode is not None:
                selected_commands = select_commands(cursor, mode, num_questions=3)
                pre_questions = []
                for idx, command in enumerate(selected_commands):
                    question_text = generate_question_from_command(command, cursor, mode)
                    pre_questions.append({
                        "id": f"generated-{idx}",
                        "question_text": question_text,
                        "order_index": idx
                    })
            else:
                # Fallback to default questions
                pre_questions = db.get_pre_questions(limit=3)
            
            return jsonify({
                "session_id": session_id,
                "pre_questions": pre_questions,
                "cursor": cursor,
                "mode": mode
            }), 200
        
        # Calculate cursor and mode from questionnaire
        if questionnaire:
            mood = questionnaire.get("mood", "positive")
            readiness = questionnaire.get("readiness", 5)
            inspiration_needed = questionnaire.get("inspiration_needed", False)
            
            # Validate inputs
            if mood not in ["positive", "negative"]:
                mood = "positive"
            if not isinstance(readiness, int) or readiness < 1 or readiness > 10:
                readiness = 5
            if not isinstance(inspiration_needed, bool):
                inspiration_needed = False
            
            cursor = calculate_cursor(mood, readiness)
            mode = determine_mode(inspiration_needed)
        else:
            # Default values if no questionnaire
            cursor = 0.5
            mode = "open"
            mood = None
            readiness = None
            inspiration_needed = None
        
        # Select commands based on cursor and mode
        selected_commands = select_commands(cursor, mode, num_questions=3)
        
        # Generate personalized questions
        pre_questions = []
        for idx, command in enumerate(selected_commands):
            question_text = generate_question_from_command(command, cursor, mode)
            
            pre_questions.append({
                "id": f"generated-{idx}",  # Temporary ID, could be stored in DB
                "question_text": question_text,
                "order_index": idx
            })
        
        # Create new session with questionnaire data
        session = db.create_session(
            user_id=user_id,
            cursor=cursor,
            mode=mode,
            mood=mood,
            readiness=readiness,
            inspiration_needed=inspiration_needed
        )
        
        if not session:
            return jsonify({"code": "SESSION_CREATE_FAILED", "error": "Failed to create session"}), 500
        
        session_id = session["id"]
        
        return jsonify({
            "session_id": session_id,
            "pre_questions": pre_questions,
            "cursor": cursor,
            "mode": mode
        }), 200
        
    except Exception as e:
        logger.error(f"Session start error: {str(e)}")
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
