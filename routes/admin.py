from flask import Blueprint, request, jsonify
from auth import require_auth
from services.db import db
from config import Config
import sentry_sdk
import logging

logger = logging.getLogger(__name__)
admin_bp = Blueprint("admin", __name__)
config = Config()


def is_admin(user_id: str) -> bool:
    """Check if user is an admin by email from token payload"""
    try:
        # Get email from token payload (set by require_auth decorator)
        token_payload = getattr(request, 'token_payload', None)
        if not token_payload:
            return False
        
        user_email = token_payload.get("email")
        if not user_email:
            return False
        
        # Check if email is in admin_users table
        admin_result = db.client.table("admin_users")\
            .select("id")\
            .eq("email", user_email)\
            .eq("is_active", True)\
            .execute()
        
        return len(admin_result.data) > 0
    except Exception as e:
        logger.error(f"Error checking admin status: {str(e)}")
        return False


def require_admin(f):
    """Decorator to require admin authentication"""
    from functools import wraps
    from auth import require_auth as base_require_auth
    
    @wraps(f)
    @base_require_auth
    def decorated_function(*args, **kwargs):
        user_id = request.user_id
        
        if not is_admin(user_id):
            return jsonify({"code": "FORBIDDEN", "error": "Admin access required"}), 403
        
        return f(*args, **kwargs)
    
    return decorated_function


@admin_bp.route("/feedback", methods=["POST"])
@require_admin
def save_admin_feedback():
    """Save admin feedback for a user"""
    try:
        data = request.get_json()
        user_id = data.get("user_id")
        
        if not user_id:
            return jsonify({"code": "INVALID_INPUT", "error": "user_id required"}), 400
        
        # Update or create professional_notes
        notes_result = db.client.table("professional_notes")\
            .select("*")\
            .eq("user_id", user_id)\
            .execute()
        
        if notes_result.data:
            # Update existing
            notes = db.client.table("professional_notes")\
                .update({
                    "notes": data.get("general_notes", notes_result.data[0].get("notes", "")),
                    "updated_at": "now()"
                })\
                .eq("user_id", user_id)\
                .execute()
        else:
            # Create new
            notes = db.client.table("professional_notes")\
                .insert({
                    "user_id": user_id,
                    "notes": data.get("general_notes", "")
                })\
                .execute()
        
        # Update or create custom_instructions
        tech_result = db.client.table("professional_notes_report_tech")\
            .select("*")\
            .eq("user_id", user_id)\
            .execute()
        
        if tech_result.data:
            # Update existing
            tech_notes = db.client.table("professional_notes_report_tech")\
                .update({
                    "custom_instructions": data.get("custom_instructions", tech_result.data[0].get("custom_instructions", "")),
                    "max_words": data.get("max_words", tech_result.data[0].get("max_words", 120)),
                    "updated_at": "now()"
                })\
                .eq("user_id", user_id)\
                .execute()
        else:
            # Create new
            tech_notes = db.client.table("professional_notes_report_tech")\
                .insert({
                    "user_id": user_id,
                    "custom_instructions": data.get("custom_instructions", ""),
                    "max_words": data.get("max_words", 120)
                })\
                .execute()
        
        # Add specific questions if provided
        if data.get("specific_questions"):
            for q in data["specific_questions"]:
                db.client.table("professional_notes_specific_questions")\
                    .insert({
                        "user_id": user_id,
                        "question_text": q.get("question_text"),
                        "question_type": q.get("question_type", "post")
                    })\
                    .execute()
        
        return jsonify({
            "status": "success",
            "message": "Admin feedback saved successfully"
        }), 200
        
    except Exception as e:
        logger.error(f"Error saving admin feedback: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "FEEDBACK_ERROR", "error": str(e)}), 500


@admin_bp.route("/user/<user_id>/context", methods=["GET"])
@require_admin
def get_user_admin_context(user_id):
    """Get admin notes and context for a user"""
    try:
        # Get professional notes
        notes_result = db.client.table("professional_notes")\
            .select("*")\
            .eq("user_id", user_id)\
            .execute()
        
        # Get custom instructions
        tech_result = db.client.table("professional_notes_report_tech")\
            .select("*")\
            .eq("user_id", user_id)\
            .execute()
        
        # Get specific questions
        questions_result = db.client.table("professional_notes_specific_questions")\
            .select("*")\
            .eq("user_id", user_id)\
            .execute()
        
        return jsonify({
            "user_id": user_id,
            "general_notes": notes_result.data[0].get("notes") if notes_result.data else None,
            "custom_instructions": tech_result.data[0].get("custom_instructions") if tech_result.data else None,
            "max_words": tech_result.data[0].get("max_words", 120) if tech_result.data else 120,
            "specific_questions": [
                {
                    "id": q.get("id"),
                    "question_text": q.get("question_text"),
                    "question_type": q.get("question_type")
                }
                for q in questions_result.data
            ] if questions_result.data else []
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting admin context: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "CONTEXT_ERROR", "error": str(e)}), 500


@admin_bp.route("/recordings", methods=["GET"])
@require_admin
def get_admin_recordings():
    """Get recordings for admin review"""
    try:
        limit = request.args.get("limit", default=20, type=int)
        offset = request.args.get("offset", default=0, type=int)
        needs_feedback = request.args.get("needs_feedback", default="false").lower() == "true"
        
        # Get recordings
        query = db.client.table("recordings")\
            .select("*, user_id")\
            .order("created_at", desc=True)\
            .limit(limit)\
            .offset(offset)
        
        result = query.execute()
        
        recordings = result.data
        
        # Filter by needs_feedback if requested
        if needs_feedback:
            # Get recordings without admin notes
            recordings_with_notes = set()
            notes_result = db.client.table("professional_notes")\
                .select("user_id")\
                .execute()
            
            if notes_result.data:
                recordings_with_notes = set(n.get("user_id") for n in notes_result.data)
            
            # Filter recordings where user doesn't have admin notes
            recordings = [r for r in recordings if r.get("user_id") not in recordings_with_notes]
        
        return jsonify({
            "recordings": recordings,
            "limit": limit,
            "offset": offset,
            "count": len(recordings)
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting admin recordings: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "RECORDINGS_ERROR", "error": str(e)}), 500
