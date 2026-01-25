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
        
        # Validate question IDs are valid UUIDs before saving
        for ans in answers:
            question_id = ans.get("question_id")
            if not question_id:
                return jsonify({"code": "INVALID_INPUT", "error": "Missing question_id in answers"}), 400
            # Basic UUID format check (36 chars, 4 hyphens)
            if len(question_id) != 36 or question_id.count('-') != 4:
                return jsonify({
                    "code": "INVALID_INPUT", 
                    "error": f"Invalid question_id format (must be UUID): {question_id}. Make sure you're using the question IDs returned from the upload response."
                }), 400
        
        # Save post answers
        try:
            db.save_post_answers(session_id, recording_id, answers)
        except ValueError as e:
            return jsonify({"code": "INVALID_INPUT", "error": str(e)}), 400
        
        # Get all context for final report
        pre_answers = db.get_pre_answers(session_id)
        post_answers = db.get_post_answers(session_id)
        
        # Get recording data
        transcript = recording.get("transcription_text", "")
        wpm = recording.get("words_per_minute", 0)
        filler_data = recording.get("filler_words_count", {})
        filler_count = filler_data.get("total", 0) if isinstance(filler_data, dict) else 0
        filler_breakdown = filler_data.get("breakdown", {}) if isinstance(filler_data, dict) else {}
        
        # Calculate performance score
        from services.scoring_service import (
            normalize_scores, calculate_performance_score, calculate_bonuses,
            calculate_final_kpi, calculate_pacing_score, calculate_attitude_score
        )
        
        # Extract answers (Q1 = scale, Q2 = binary)
        # Sort answers by question_id to ensure consistent ordering
        # For now, we'll use the order they come in (first = scale, second = binary)
        # In production, you might want to query questions to verify types
        q1_answer = None
        q2_answer = None
        
        if len(answers) >= 1:
            q1_answer = answers[0].get("answer_text", "3")
        if len(answers) >= 2:
            q2_answer = answers[1].get("answer_text", "NO")
        
        # Calculate pacing and attitude scores
        pacing_score = calculate_pacing_score(wpm)
        classification = recording.get("classification", "uncertain")
        confidence = recording.get("confidence", "medium")
        attitude_score = calculate_attitude_score(classification, confidence)
        
        # Get pre-recording questionnaire data
        initial_mood = session.get("mood", "positive")
        
        # Get previous performance
        previous_performance = db.get_previous_performance_score(user_id, recording_id)
        
        # Normalize scores
        normalized = normalize_scores(
            filler_word_count=filler_count,
            pacing_score=pacing_score,
            attitude_score=attitude_score,
            q1_answer=q1_answer or "3",
            q2_answer=q2_answer or "NO",
        )
        
        # Calculate performance
        performance = calculate_performance_score(normalized)
        
        # Calculate bonuses
        bonuses = calculate_bonuses(
            performance=performance,
            initial_mood=initial_mood,
            filler_word_count=filler_count,
            awareness_bonus=normalized['awareness_bonus'],
            previous_performance=previous_performance,
            user_streak=0,  # TODO: Implement streak tracking
        )
        
        # Final KPI
        final_kpi = calculate_final_kpi(performance, bonuses)
        
        # Store performance score
        performance_data = {
            "performance": performance,
            "final_kpi": final_kpi,
            "bonuses": bonuses,
            "raw_scores": {
                "filler_score": normalized['filler_score'],
                "pacing_score": normalized['pacing_score'],
                "attitude_score": normalized['attitude_score'],
                "reflection_score": normalized['reflection_score'],
            }
        }
        
        db.save_performance_score(recording_id, performance_data)
        
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
        
        # Get admin context for personalized analysis
        admin_context = db.get_user_admin_context(user_id)
        
        final_report = openai_service.generate_final_report(
            transcript=transcript,
            pre_answers=pre_answers_formatted,
            post_answers=post_answers_formatted,
            wpm=wpm,
            filler_count=filler_count,
            filler_breakdown=filler_breakdown,
            trend_sentence=trend_sentence,
            user_id=user_id,
            admin_context=admin_context,
            recording_id=recording_id
        )
        
        # Update recording with final report
        # Only include fields that exist in the database
        update_data = {}
        if final_report:
            update_data["coaching_report"] = final_report
        if trend_sentence:
            update_data["trend_sentence"] = trend_sentence
        
        if update_data:
            db.update_recording(recording_id, update_data)
        
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
            "report": final_report,
            "recording_id": recording_id,
            "session_id": session_id,
            "post_questions_completed": True,
            "performance_score": {
                "performance": performance,
                "final_kpi": final_kpi,
                "bonuses": bonuses,
                "raw_scores": {
                    "filler_score": normalized['filler_score'],
                    "pacing_score": normalized['pacing_score'],
                    "attitude_score": normalized['attitude_score'],
                    "reflection_score": normalized['reflection_score'],
                }
            }
        }), 200
        
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "ANSWERS_ERROR", "error": str(e)}), 500
