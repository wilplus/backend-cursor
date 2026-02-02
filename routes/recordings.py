from flask import Blueprint, request, jsonify
from werkzeug.utils import secure_filename
from auth import require_auth
from services.db import db
from services.openai_service import openai_service
from utils.metrics import count_fillers, compute_wpm
from config import Config
import sentry_sdk
import os
import random
import uuid

recordings_bp = Blueprint("recordings", __name__)
config = Config()

@recordings_bp.route("/upload", methods=["POST"])
@require_auth
def upload_recording():
    """Upload recording and perform initial analysis"""
    try:
        user_id = request.user_id
        
        # Get form data (v1: command_option_id required)
        session_id = request.form.get("session_id")
        command_option_id = request.form.get("command_option_id")
        duration_seconds = request.form.get("duration_seconds")
        audio_file = request.files.get("audio")
        
        if not session_id:
            return jsonify({"code": "INVALID_INPUT", "error": "session_id required"}), 400
        if not command_option_id or command_option_id not in ("A", "B", "C"):
            return jsonify({"code": "INVALID_INPUT", "error": "command_option_id required (A, B, or C)"}), 400
        if not audio_file:
            return jsonify({"code": "INVALID_INPUT", "error": "audio file required"}), 400
        
        # Verify session belongs to user
        session = db.get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        if not session.get("pre_questions_completed"):
            return jsonify({"code": "INVALID_STATE", "error": "Pre-questions must be completed first"}), 400
        
        # v1: Validate command option exists for this session
        opts = db.get_session_command_options(session_id)
        selected_opt = next((o for o in opts if o.get("option_id") == command_option_id), None)
        if not selected_opt:
            return jsonify({"code": "INVALID_INPUT", "error": "command_option_id not found for this session"}), 400
        # Persist selected command snapshot + mirror mode to structure
        db.update_session_selected_command(
            session_id,
            option_id=selected_opt["option_id"],
            intent=selected_opt["intent"],
            tier=selected_opt["tier"],
            mode=selected_opt["mode"],
            prompt_snapshot=selected_opt["prompt_text_snapshot"],
        )
        # Count how many times user has selected this intent (before this upload) for "newly tested" post-question
        intent_selection_count = db.get_intent_selection_count(user_id, selected_opt["intent"])
        # Log exposures: intent was_selected=true, command_option
        db.log_exposure(user_id, "intent", selected_opt["intent"], session_id=session_id, tier=selected_opt["tier"], was_selected=True)
        db.log_exposure(user_id, "command_option", command_option_id, session_id=session_id, was_selected=True)
        
        # Check file size (25MB limit)
        audio_file.seek(0, os.SEEK_END)
        file_size = audio_file.tell()
        audio_file.seek(0)
        
        max_size_bytes = config.MAX_AUDIO_SIZE_MB * 1024 * 1024
        if file_size > max_size_bytes:
            return jsonify({"code": "FILE_TOO_LARGE", "error": f"File exceeds {config.MAX_AUDIO_SIZE_MB}MB limit"}), 400
        
        # Get file extension
        filename = audio_file.filename or "audio.webm"
        ext = os.path.splitext(filename)[1] or ".webm"
        
        # In production: upload to storage, transcribe, validate duration
        # In dev: skip storage and OpenAI, use mock data
        if config.is_production:
            # Upload to Supabase Storage first (unique path per upload to avoid 400 Duplicate on retry)
            storage_path = f"{user_id}/{session_id}/{uuid.uuid4()}{ext}"
            audio_file.seek(0)
            audio_data = audio_file.read()
            
            # Validate audio_data is bytes
            if not isinstance(audio_data, bytes):
                return jsonify({"code": "INVALID_AUDIO", "error": "Audio file data is not in bytes format"}), 400
            
            # Ensure content_type is a string, not None or boolean
            content_type = str(audio_file.content_type) if audio_file.content_type else "audio/webm"
            # Remove any boolean values (convert True/False to string if needed)
            if content_type in ["True", "False"]:
                content_type = "audio/webm"
            
            db.upload_audio(config.AUDIO_BUCKET_NAME, storage_path, audio_data, content_type=content_type)
            
            # Try to create a signed URL (works for both public and private buckets)
            # If bucket is public, we could use public URL, but signed URLs are more reliable
            try:
                audio_url = db.create_signed_url(
                    config.AUDIO_BUCKET_NAME,
                    storage_path,
                    config.SIGNED_URL_EXPIRY_SECONDS
                )
            except Exception as e:
                # Fallback to public URL if signed URL fails
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to create signed URL, using public URL: {str(e)}")
                supabase_url = config.SUPABASE_URL.rstrip('/')
                audio_url = f"{supabase_url}/storage/v1/object/public/{config.AUDIO_BUCKET_NAME}/{storage_path}"
            
            # Transcribe with Whisper
            audio_file.seek(0)
            transcript_result = openai_service.transcribe_audio(audio_file, filename)
            transcript_text = transcript_result["text"]
            whisper_duration = transcript_result["duration"]
            
            # Validate duration from Whisper (must be <= 300 seconds)
            if whisper_duration > config.MAX_RECORDING_DURATION_SECONDS:
                # Don't save recording, return error
                return jsonify({
                    "code": "RECORDING_TOO_LONG",
                    "error": "Recording exceeds 5 minutes"
                }), 400
            
            # Use Whisper duration as source of truth
            actual_duration = whisper_duration
        else:
            # Dev mode: mock data (COMMENTED OUT - using real OpenAI)
            # transcript_text = "This is a mock transcription for development purposes. The user spoke about their presentation and how they felt nervous but prepared."
            # actual_duration = float(duration_seconds) if duration_seconds else 45.0
            # storage_path = None
            # In dev mode, use a placeholder URL or empty string
            # Since audio_url is NOT NULL, we'll use a placeholder
            # audio_url = f"dev-placeholder://{user_id}/{session_id}{ext}"
            
            # Use real OpenAI even in dev mode
            # Upload to Supabase Storage first (unique path per upload to avoid 400 Duplicate on retry)
            storage_path = f"{user_id}/{session_id}/{uuid.uuid4()}{ext}"
            audio_file.seek(0)
            audio_data = audio_file.read()
            
            # Validate audio_data is bytes
            if not isinstance(audio_data, bytes):
                return jsonify({"code": "INVALID_AUDIO", "error": "Audio file data is not in bytes format"}), 400
            
            # Ensure content_type is a string, not None or boolean
            content_type = str(audio_file.content_type) if audio_file.content_type else "audio/webm"
            # Remove any boolean values (convert True/False to string if needed)
            if content_type in ["True", "False"]:
                content_type = "audio/webm"
            
            db.upload_audio(config.AUDIO_BUCKET_NAME, storage_path, audio_data, content_type=content_type)
            
            # Get public URL for the uploaded file
            supabase_url = config.SUPABASE_URL.rstrip('/')
            audio_url = f"{supabase_url}/storage/v1/object/public/{config.AUDIO_BUCKET_NAME}/{storage_path}"
            
            # Transcribe with Whisper
            audio_file.seek(0)
            transcript_result = openai_service.transcribe_audio(audio_file, filename)
            transcript_text = transcript_result["text"]
            whisper_duration = transcript_result["duration"]
            
            # Validate duration from Whisper (must be <= 300 seconds)
            if whisper_duration > config.MAX_RECORDING_DURATION_SECONDS:
                # Don't save recording, return error
                return jsonify({
                    "code": "RECORDING_TOO_LONG",
                    "error": "Recording exceeds 5 minutes"
                }), 400
            
            # Use Whisper duration as source of truth
            actual_duration = whisper_duration
        
        # Compute metrics deterministically
        wpm = compute_wpm(transcript_text, actual_duration)
        filler_data = count_fillers(transcript_text)
        filler_count = filler_data["total"]
        filler_breakdown = filler_data["breakdown"]
        
        # Get pre-answers for classification
        pre_answers = db.get_pre_answers(session_id)
        pre_answers_formatted = [
            {
                "question_text": ans.get("pre_recording_questions", {}).get("question_text", ""),
                "answer_text": ans.get("answer_text", "")
            }
            for ans in pre_answers
        ]
        
        # Classify speech
        classification_result = openai_service.classify_speech(
            transcript=transcript_text,
            pre_answers=pre_answers_formatted,
            wpm=wpm,
            filler_count=filler_count
        )
        
        # Create recording record
        # Convert duration to integer (database expects integer, not float)
        duration_int = int(round(actual_duration))
        
        recording_data = {
            "user_id": user_id,
            "session_id": session_id,
            "command_option_id": command_option_id,
            "transcription_text": transcript_text,
            "duration": duration_int,  # duration column (NOT NULL, INTEGER type)
            "duration_seconds": actual_duration,  # duration_seconds column (if exists, can be float)
            "words_per_minute": wpm,
            "filler_words_count": {
                "breakdown": filler_breakdown,
                "total": filler_count
            },
            "classification": classification_result["classification"],
            "confidence": classification_result["confidence"],
            "audio_url": audio_url,  # Use audio_url instead of storage_path
            "storage_path": storage_path  # Keep storage_path for reference if needed
        }
        
        recording = db.create_recording(recording_data)
        if not recording:
            return jsonify({"code": "RECORDING_CREATE_FAILED", "error": "Failed to create recording"}), 500
        
        recording_id = recording["id"]
        
        # Mark session recording as completed
        db.client.table("recording_sessions")\
            .update({"recording_completed": True, "recording_id": recording_id})\
            .eq("id", session_id)\
            .execute()
        
        # v1: Choose post-set at upload (theme + anti-repeat: last 1 overall, last 2 within theme)
        from services.post_questions_service import POST_QUESTIONS_POOL, generate_post_questions_from_set
        from services.question_service import POST_SETS_BY_THEME
        
        theme_chosen = session.get("theme_chosen_code")
        candidates = POST_SETS_BY_THEME.get(theme_chosen) if theme_chosen else list(range(1, 21))
        if not candidates:
            candidates = list(range(1, 21))
        # Anti-repeat: last 1 overall (from content_exposures or session history), last 2 within theme
        recent_same_theme = db.get_recent_post_set_exposures_by_theme(user_id, theme_chosen or "", limit_same_theme=2)
        recent_overall = db.get_recent_exposures(user_id, "post_set", 1)
        recent_overall_ids = []
        for r in recent_overall:
            try:
                recent_overall_ids.append(int(r.get("content_code", 0)))
            except (ValueError, TypeError):
                pass
        exclude_set_ids = list(set(recent_overall_ids + recent_same_theme))
        available = [s for s in candidates if s not in exclude_set_ids]
        if not available:
            available = candidates
        import random
        set_id = random.choice(available)
        db.update_session_post_question_set_id(session_id, set_id)
        db.log_exposure(user_id, "post_set", str(set_id), session_id=session_id, was_selected=True)
        
        # Get question set by id and instantiate post_recording_questions
        selected_set = next((s for s in POST_QUESTIONS_POOL if s["id"] == set_id), None)
        if not selected_set:
            selected_set = POST_QUESTIONS_POOL[0] if POST_QUESTIONS_POOL else None
        temp_questions = generate_post_questions_from_set(selected_set) if selected_set else []
        
        post_questions = []
        for temp_q in temp_questions:
            question_record = db.create_post_question(
                question_text=temp_q["question_text"],
                question_type=temp_q["question_type"],
                question_set_id=temp_q.get("question_set_id"),
                order_index=temp_q.get("order_index")
            )
            if question_record:
                post_questions.append({
                    "id": question_record["id"],
                    "question_text": question_record["question_text"],
                    "question_type": question_record.get("question_type", temp_q["question_type"]),
                    "question_set_id": temp_q.get("question_set_id"),
                    "order_index": temp_q.get("order_index")
                })
        
        # If command was newly tested (1st or 2nd time this intent), 50% of the time add "was this prompt good?" question
        # order_index must satisfy chk_order_index (e.g. 0-5); cap at 5 so we never exceed DB constraint.
        newly_tested = intent_selection_count < 2
        if newly_tested and random.random() < 0.5:
            next_order = min(len(post_questions), 5)
            prompt_feedback_q = db.create_post_question(
                question_text="Did you find this recording prompt useful?",
                question_type="binary",
                question_set_id=selected_set["id"] if selected_set else None,
                order_index=next_order
            )
            if prompt_feedback_q:
                post_questions.append({
                    "id": prompt_feedback_q["id"],
                    "question_text": prompt_feedback_q["question_text"],
                    "question_type": prompt_feedback_q.get("question_type", "binary"),
                    "question_set_id": prompt_feedback_q.get("question_set_id"),
                    "order_index": next_order,
                })
        
        return jsonify({
            "recording_id": recording_id,
            "status": "recording_uploaded",
            "post_questions": post_questions
        }), 200
        
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "UPLOAD_ERROR", "error": str(e)}), 500

def _is_valid_uuid(value):
    """Return True if value is a valid UUID string; avoids DB 'invalid input syntax for type uuid'."""
    if not value or not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
        return True
    except (ValueError, TypeError, AttributeError):
        return False


@recordings_bp.route("/<recording_id>", methods=["GET"])
@require_auth
def get_recording(recording_id):
    """Get recording details"""
    try:
        if not _is_valid_uuid(recording_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid recording ID"}), 400
        user_id = request.user_id
        
        # Get recording (verify ownership)
        recording = db.get_recording(recording_id, user_id)
        if not recording:
            return jsonify({"code": "RECORDING_NOT_FOUND", "error": "Recording not found"}), 404
        
        session_id = recording.get("session_id")
        
        # Get answers
        pre_answers = []
        post_answers = []
        
        if session_id:
            pre_answers = db.get_pre_answers(session_id)
            post_answers = db.get_post_answers(session_id)
        
        # Format answers
        pre_answers_formatted = [
            {
                "question_id": ans.get("question_id"),
                "question_text": ans.get("pre_recording_questions", {}).get("question_text", ""),
                "answer_text": ans.get("answer_text", "")
            }
            for ans in pre_answers
        ]
        
        post_answers_formatted = [
            {
                "question_id": ans.get("question_id"),
                "question_text": ans.get("post_recording_questions", {}).get("question_text", ""),
                "answer_text": ans.get("answer_text", "")
            }
            for ans in post_answers
        ]
        
        # Get metrics
        filler_data = recording.get("filler_words_count", {})
        filler_count = filler_data.get("total", 0) if isinstance(filler_data, dict) else 0
        filler_breakdown = filler_data.get("breakdown", {}) if isinstance(filler_data, dict) else {}
        
        # Get audio URL - try signed URL first, fallback to public URL
        import logging
        logger = logging.getLogger(__name__)
        
        audio_url = None
        storage_path = recording.get("storage_path")
        
        # Try to generate signed URL from storage_path (works for both public and private buckets)
        if storage_path:
            try:
                audio_url = db.create_signed_url(
                    config.AUDIO_BUCKET_NAME,
                    storage_path,
                    config.SIGNED_URL_EXPIRY_SECONDS
                )
                logger.info(f"Generated signed URL for recording {recording_id}: {audio_url[:80]}...")
            except Exception as e:
                logger.warning(f"Failed to generate signed URL for recording {recording_id}: {str(e)}")
                # If signed URL generation fails, try public URL as fallback (works if bucket is public)
                supabase_url = config.SUPABASE_URL.rstrip('/')
                audio_url = f"{supabase_url}/storage/v1/object/public/{config.AUDIO_BUCKET_NAME}/{storage_path}"
                logger.info(f"Using public URL fallback: {audio_url}")
        
        # If no storage_path, check if audio_url exists in database
        if not audio_url:
            audio_url = recording.get("audio_url")
            if audio_url:
                # If it's not a full URL, it might be invalid
                if not audio_url.startswith("http"):
                    logger.warning(f"Audio URL in database is not a full URL: {audio_url}")
                    audio_url = None
        
        # Get performance score if it exists
        performance_score = db.get_performance_score(recording_id)
        performance_data = None
        if performance_score:
            performance_data = {
                "performance": float(performance_score.get("performance", 0)),
                "final_kpi": float(performance_score.get("final_kpi", 0)),
                "bonuses": {
                    "resilience": float(performance_score.get("resilience_bonus", 0)),
                    "awareness": float(performance_score.get("awareness_bonus", 0)),
                    "progress": float(performance_score.get("progress_bonus", 0)),
                    "streak": float(performance_score.get("streak_bonus", 0)),
                },
                "raw_scores": {
                    "filler_score": float(performance_score.get("filler_score", 0)),
                    "pacing_score": float(performance_score.get("pacing_score", 0)),
                    "attitude_score": float(performance_score.get("attitude_score", 0)),
                    "reflection_score": float(performance_score.get("reflection_score", 0)),
                }
            }
        
        # Debug logging
        import logging
        logger = logging.getLogger(__name__)
        transcription_text = recording.get("transcription_text", "")
        coaching_report = recording.get("coaching_report")
        
        logger.info(f"Recording {recording_id}: transcription_length={len(transcription_text)}, coaching_report_length={len(coaching_report) if coaching_report else 0}, has_coaching_report={bool(coaching_report)}")
        logger.info(f"Audio URL for recording {recording_id}: {audio_url[:100] if audio_url else 'None'}...")
        
        # Ensure audio_url is valid before returning
        if audio_url and not audio_url.startswith("http"):
            logger.error(f"Invalid audio_url format: {audio_url}")
            audio_url = None
        
        return jsonify({
            "recording_id": recording_id,
            "session_id": session_id,
            "status": "completed" if coaching_report else "pending",
            "transcription_text": transcription_text,
            "audio_url": audio_url,  # Include audio URL for playback (must be full URL or null)
            "metrics": {
                "wpm": recording.get("words_per_minute", 0),
                "filler_count": filler_count,
                "filler_breakdown": filler_breakdown
            },
            "analysis": {
                "report": coaching_report,  # This should be different from transcription
                "trend_sentence": recording.get("trend_sentence")
            },
            "performance_score": performance_data,  # Include performance score if available
            "answers": {
                "pre": pre_answers_formatted,
                "post": post_answers_formatted
            }
        }), 200
        
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "RECORDING_ERROR", "error": str(e)}), 500

@recordings_bp.route("/<recording_id>/audio-url", methods=["GET"])
@require_auth
def get_audio_url(recording_id):
    """Get signed URL for audio file (or return existing public URL)"""
    try:
        if not _is_valid_uuid(recording_id):
            return jsonify({"code": "INVALID_INPUT", "error": "Invalid recording ID"}), 400
        user_id = request.user_id
        
        # Get recording (verify ownership)
        recording = db.get_recording(recording_id, user_id)
        if not recording:
            return jsonify({"code": "RECORDING_NOT_FOUND", "error": "Recording not found"}), 404
        
        # First, check if audio_url already exists (public URL or dev placeholder)
        audio_url = recording.get("audio_url")
        if audio_url:
            # If it's a dev placeholder, return it as-is
            if audio_url.startswith("dev-placeholder://"):
                return jsonify({
                    "signed_url": audio_url,
                    "expires_in": None,
                    "note": "Development mode - placeholder URL"
                }), 200
            # If it's a public URL, return it
            if audio_url.startswith("http://") or audio_url.startswith("https://"):
                return jsonify({
                    "signed_url": audio_url,
                    "expires_in": None,
                    "note": "Public URL"
                }), 200
        
        # If no audio_url, try to generate signed URL from storage_path
        storage_path = recording.get("storage_path")
        if storage_path:
            signed_url = db.create_signed_url(
                config.AUDIO_BUCKET_NAME,
                storage_path,
                config.SIGNED_URL_EXPIRY_SECONDS
            )
            return jsonify({
                "signed_url": signed_url,
                "expires_in": config.SIGNED_URL_EXPIRY_SECONDS
            }), 200
        
        # No audio available
        return jsonify({"code": "NO_AUDIO", "error": "Audio file not available"}), 404
        
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "URL_ERROR", "error": str(e)}), 500
