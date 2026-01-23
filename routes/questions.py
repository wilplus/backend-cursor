from flask import Blueprint, request, jsonify
from auth import require_auth
from services.db import db
from config import Config
import sentry_sdk

config = Config()

questions_bp = Blueprint("questions", __name__)

@questions_bp.route("/pre-recording", methods=["GET"])
@require_auth
def get_pre_questions():
    """Get pre-recording questions"""
    try:
        questions = db.get_pre_questions(limit=3)
        
        return jsonify({"questions": questions}), 200
        
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "QUESTIONS_ERROR", "error": str(e)}), 500

@questions_bp.route("/pre-recording/answers", methods=["POST"])
@require_auth
def submit_pre_answers():
    """Submit pre-recording answers"""
    try:
        user_id = request.user_id
        data = request.get_json()
        
        session_id = data.get("session_id")
        answers = data.get("answers", [])
        
        if not session_id:
            return jsonify({"code": "INVALID_INPUT", "error": "session_id required"}), 400
        
        if not answers or len(answers) == 0:
            return jsonify({"code": "INVALID_INPUT", "error": "answers required"}), 400
        
        # Verify session belongs to user
        session = db.get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        
        # Save answers
        db.save_pre_answers(session_id, answers)
        
        return jsonify({"message": "Answers saved"}), 200
        
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "ANSWERS_ERROR", "error": str(e)}), 500

@questions_bp.route("/post-recording/answers", methods=["POST"])
@require_auth
def submit_post_answers():
    """Submit post-recording answers and generate final report"""
    try:
        user_id = request.user_id
        data = request.get_json()
        
        recording_id = data.get("recording_id")
        session_id = data.get("session_id")
        answers = data.get("answers", [])
        
        if not recording_id or not session_id:
            return jsonify({"code": "INVALID_INPUT", "error": "recording_id and session_id required"}), 400
        
        if not answers or len(answers) == 0:
            return jsonify({"code": "INVALID_INPUT", "error": "answers required"}), 400
        
        # Verify recording belongs to user
        recording = db.get_recording(recording_id, user_id)
        if not recording:
            return jsonify({"code": "RECORDING_NOT_FOUND", "error": "Recording not found"}), 404
        
        # Verify session belongs to user
        session = db.get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        
        # Save post answers
        db.save_post_answers(session_id, recording_id, answers)
        
        # Get all context for final report
        pre_answers = db.get_pre_answers(session_id)
        post_answers = db.get_post_answers(session_id)
        
        # Get recording data
        transcript = recording.get("transcription_text", "")
        wpm = recording.get("words_per_minute", 0)
        filler_data = recording.get("filler_words_count", {})
        filler_count = filler_data.get("total", 0) if isinstance(filler_data, dict) else 0
        filler_breakdown = filler_data.get("breakdown", {}) if isinstance(filler_data, dict) else {}
        
        # Compute trend if possible
        from utils.metrics import compute_trend_sentence
        prior_recordings = db.get_prior_recordings_for_trend(user_id, exclude_recording_id=recording_id)
        
        trend_sentence = None
        if len(prior_recordings) >= 1:  # Need at least 1 prior (current is excluded, so >=1 means >=2 total)
            previous = prior_recordings[0]
            prev_wpm = previous.get("words_per_minute")
            prev_filler_data = previous.get("filler_words_count", {})
            prev_filler_count = prev_filler_data.get("total", 0) if isinstance(prev_filler_data, dict) else 0
            
            if prev_wpm is not None and prev_filler_count is not None:
                trend_sentence = compute_trend_sentence(wpm, filler_count, prev_wpm, prev_filler_count)
        
        # Generate final report
        from services.openai_service import openai_service
        
        # Format answers for OpenAI
        pre_answers_formatted = [
            {
                "question_text": ans.get("pre_recording_questions", {}).get("question_text", ""),
                "answer_text": ans.get("answer_text", "")
            }
            for ans in pre_answers
        ]
        
        post_answers_formatted = [
            {
                "question_text": ans.get("post_recording_questions", {}).get("question_text", ""),
                "answer_text": ans.get("answer_text", "")
            }
            for ans in post_answers
        ]
        
        final_report = openai_service.generate_final_report(
            transcript=transcript,
            pre_answers=pre_answers_formatted,
            post_answers=post_answers_formatted,
            wpm=wpm,
            filler_count=filler_count,
            filler_breakdown=filler_breakdown,
            trend_sentence=trend_sentence
        )
        
        # Update recording with final report
        db.update_recording(recording_id, {
            "coaching_report": final_report,
            "trend_sentence": trend_sentence
        })
        
        # Mark session as completed
        db.complete_session(session_id)
        
        # Send admin email
        from services.email_service import email_service
        
        transcript_preview = transcript[:200] if transcript else ""
        suggested_questions = openai_service.generate_suggested_questions(
            transcript=transcript,
            pre_answers=pre_answers_formatted,
            post_answers=post_answers_formatted,
            wpm=wpm,
            filler_count=filler_count,
            report=final_report
        )
        
        email_result = email_service.send_admin_notification(
            user_id=user_id,
            session_id=session_id,
            recording_id=recording_id,
            pre_answers=pre_answers_formatted,
            post_answers=post_answers_formatted,
            transcript_preview=transcript_preview,
            final_report=final_report,
            suggested_questions=suggested_questions
        )
        
        # Save admin notification record
        db.save_admin_notification({
            "user_id": user_id,
            "session_id": session_id,
            "recording_id": recording_id,
            "sent_to": config.ADMIN_EMAIL,
            "subject": f"Speech Analysis Session Completed - Session {session_id[:8]}",
            "payload_json": email_result.get("payload", {}),
            "status": email_result.get("status", "pending"),
            "error": email_result.get("error"),
            "sent_at": "now()" if email_result.get("sent") else None
        })
        
        return jsonify({
            "message": "Answers saved and report generated",
            "report": final_report
        }), 200
        
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "ANSWERS_ERROR", "error": str(e)}), 500
