from supabase import create_client, Client
from config import Config
from typing import List, Optional, Tuple
from datetime import datetime, timedelta, timezone
import sentry_sdk
import json
import time

from services.v2_flow_service import score_and_pick_focus_task

config = Config()

class DatabaseService:
    def __init__(self):
        self.client: Client = create_client(
            config.SUPABASE_URL,
            config.SUPABASE_SERVICE_ROLE_KEY
        )
    
    def get_active_session(self, user_id: str):
        """Get the active (non-completed) session for a user"""
        result = self.client.table("recording_sessions")\
            .select("*")\
            .eq("user_id", user_id)\
            .is_("completed_at", "null")\
            .execute()
        
        if result.data:
            return result.data[0]
        return None
    
    def create_session(self, user_id: str, cursor: float = None, mode: str = None, 
                       mood: str = None, readiness: int = None, inspiration_needed: bool = None,
                       pre_questions_completed: bool = False, status: str = None):
        """Create a new recording session with optional questionnaire data"""
        session_data = {
            "user_id": user_id,
            "pre_questions_completed": pre_questions_completed,  # ✅ Set based on questionnaire
            "recording_completed": False,
            "post_questions_completed": False
        }
        
        # Set status if provided
        if status is not None:
            session_data["status"] = status
        
        # Add questionnaire data if provided
        if cursor is not None:
            session_data["cursor"] = cursor
        if mode is not None:
            session_data["mode"] = mode
        if mood is not None:
            session_data["mood"] = mood
        if readiness is not None:
            session_data["readiness"] = readiness
        if inspiration_needed is not None:
            session_data["inspiration_needed"] = inspiration_needed
        
        result = self.client.table("recording_sessions")\
            .insert(session_data)\
            .execute()
        
        return result.data[0] if result.data else None
    
    def abandon_session(self, session_id: str, user_id: str):
        """Abandon a session (status = abandoned, completed_at set)"""
        result = self.client.table("recording_sessions")\
            .update({
                "status": "abandoned",
                "completed_at": "now()",
                "abandoned_at": "now()"
            })\
            .eq("id", session_id)\
            .eq("user_id", user_id)\
            .execute()
        
        return result.data[0] if result.data else None
    
    def get_pre_questions(self, limit: int = 3):
        """Get pre-recording questions ordered by order_index"""
        result = self.client.table("pre_recording_questions")\
            .select("*")\
            .order("order_index")\
            .limit(limit)\
            .execute()
        
        return result.data
    
    def create_pre_question(self, session_id: str, question_text: str, order_index: int, 
                           command_id: int = None, cursor: float = None, mode: str = None):
        """Create a personalized pre-recording question"""
        question_data = {
            "question_text": question_text,
            "order_index": order_index
        }
        
        # Add optional metadata
        if command_id is not None:
            question_data["command_id"] = command_id
        if cursor is not None:
            question_data["cursor"] = cursor
        if mode is not None:
            question_data["mode"] = mode
        
        result = self.client.table("pre_recording_questions")\
            .insert(question_data)\
            .execute()
        
        return result.data[0] if result.data else None
    
    def save_pre_answers(self, session_id: str, answers: list, user_id: str = None, snapshot_per_answer: list = None):
        """Save pre-recording answers. snapshot_per_answer: optional list of dicts with question_text_snapshot, question_type_snapshot, question_code_snapshot, order_index_snapshot."""
        records = []
        for i, ans in enumerate(answers):
            rec = {
                "recording_session_id": session_id,
                "question_id": ans["question_id"],
                "answer_text": ans["answer_text"]
            }
            if user_id:
                rec["user_id"] = user_id
            if snapshot_per_answer and i < len(snapshot_per_answer):
                snap = snapshot_per_answer[i]
                if snap.get("question_text_snapshot") is not None:
                    rec["question_text_snapshot"] = snap["question_text_snapshot"]
                if snap.get("question_type_snapshot") is not None:
                    rec["question_type_snapshot"] = snap["question_type_snapshot"]
                if snap.get("question_code_snapshot") is not None:
                    rec["question_code_snapshot"] = snap["question_code_snapshot"]
                if snap.get("order_index_snapshot") is not None:
                    rec["order_index_snapshot"] = snap["order_index_snapshot"]
            records.append(rec)
        
        result = self.client.table("pre_recording_answers")\
            .insert(records)\
            .execute()
        
        # Mark session as pre_questions_completed
        self.client.table("recording_sessions")\
            .update({"pre_questions_completed": True})\
            .eq("id", session_id)\
            .execute()
        
        return result.data
    
    def create_recording(self, data: dict):
        """Create a recording record"""
        result = self.client.table("recordings")\
            .insert(data)\
            .execute()
        
        return result.data[0] if result.data else None
    
    def update_recording(self, recording_id: str, data: dict):
        """Update a recording record"""
        try:
            result = self.client.table("recordings")\
                .update(data)\
                .eq("id", recording_id)\
                .execute()
            
            return result.data[0] if result.data else None
        except Exception as e:
            # Log the error but don't fail silently
            # This helps identify missing columns or other schema issues
            sentry_sdk.capture_exception(e)
            error_msg = str(e)
            # If it's a column doesn't exist error, provide helpful message
            if "column" in error_msg.lower() and "does not exist" in error_msg.lower():
                raise Exception(f"Database schema error: {error_msg}. Please ensure all required columns exist in the recordings table.")
            raise
    
    def get_recording(self, recording_id: str, user_id: str = None):
        """Get a recording by ID, optionally verifying ownership"""
        query = self.client.table("recordings").select("*").eq("id", recording_id)
        
        if user_id:
            query = query.eq("user_id", user_id)
        
        result = query.execute()
        
        return result.data[0] if result.data else None
    
    def get_user_recordings(self, user_id: str, limit: int = 10, offset: int = 0):
        """Get recordings for a user with pagination"""
        # Get paginated recordings with count
        # Supabase PostgREST returns count in headers when using count=exact
        result = self.client.table("recordings")\
            .select("*", count="exact")\
            .eq("user_id", user_id)\
            .order("created_at", desc=True)\
            .limit(limit)\
            .offset(offset)\
            .execute()
        
        # Extract total count from response
        # The count is typically in the response metadata or we can get it from the count property
        total = getattr(result, 'count', None)
        if total is None:
            # Fallback: if count not available, we'll need to do a separate count query
            count_result = self.client.table("recordings")\
                .select("id", count="exact")\
                .eq("user_id", user_id)\
                .limit(1)\
                .execute()
            total = getattr(count_result, 'count', len(result.data) if result.data else 0)
        
        return {
            "items": result.data,
            "total": total if total is not None else len(result.data),
            "limit": limit,
            "offset": offset
        }
    
    def get_prior_recordings_for_trend(self, user_id: str, exclude_recording_id: str = None):
        """Get prior recordings for trend computation (need >=2)"""
        query = self.client.table("recordings")\
            .select("id,words_per_minute,filler_words_count,created_at")\
            .eq("user_id", user_id)\
            .not_.is_("words_per_minute", "null")\
            .order("created_at", desc=True)\
            .limit(10)
        
        if exclude_recording_id:
            query = query.neq("id", exclude_recording_id)
        
        result = query.execute()
        return result.data
    
    def get_post_questions(self, user_id: str, classification: str, exclude_question_ids: list = None):
        """Get post-recording questions based on classification"""
        # Determine question type
        if classification == "struggler":
            question_type = "reflective"
        elif classification == "strong":
            question_type = "amplifying"
        else:  # uncertain
            question_type = "reflective"
        
        candidates = []
        
        # 1. User-specific post questions
        user_specific = self.client.table("professional_notes_specific_questions")\
            .select("*")\
            .eq("user_id", user_id)\
            .eq("question_type", "post")\
            .execute()
        
        if user_specific.data:
            candidates.extend(user_specific.data)
        
        # 2. Global post questions
        global_query = self.client.table("post_recording_questions")\
            .select("*")
        
        # Filter by type if the table has a type column
        # (Assuming it does, adjust if schema differs)
        try:
            global_questions = global_query.eq("question_type", question_type).execute()
        except:
            # If no question_type column, get all
            global_questions = global_query.execute()
        
        if global_questions.data:
            candidates.extend(global_questions.data)
        
        # Filter out excluded questions
        if exclude_question_ids:
            candidates = [q for q in candidates if q.get("id") not in exclude_question_ids]
        
        # Return exactly 3 (allow repeats if needed)
        return candidates[:3]
    
    def get_recent_post_question_ids(self, user_id: str, limit: int = 3):
        """Get question IDs from recent sessions to avoid repeats"""
        # Get recent sessions with post answers
        sessions = self.client.table("recording_sessions")\
            .select("id")\
            .eq("user_id", user_id)\
            .not_.is_("completed_at", "null")\
            .order("completed_at", desc=True)\
            .limit(limit)\
            .execute()
        
        if not sessions.data:
            return []
        
        session_ids = [s["id"] for s in sessions.data]
        
        # Get post answers from these sessions
        answers = self.client.table("post_recording_answers")\
            .select("question_id")\
            .in_("session_id", session_ids)\
            .execute()
        
        return list(set([a["question_id"] for a in answers.data]))
    
    def get_recent_question_set_ids(self, user_id: str, limit: int = 5) -> List[int]:
        """Get recently used question set IDs to avoid repetition"""
        # Get recent recordings
        recordings = self.client.table("recordings")\
            .select("id")\
            .eq("user_id", user_id)\
            .order("created_at", desc=True)\
            .limit(limit * 2)\
            .execute()
        
        if not recordings.data:
            return []
        
        recording_ids = [r["id"] for r in recordings.data]
        
        # Get post answers from these recordings
        # Note: We'll need to store question_set_id in post_answers or in a separate table
        # For now, return empty list (will be improved when question_set_id is stored)
        return []
    
    def create_post_question(self, question_text: str, question_type: str, question_set_id: int = None, order_index: int = None):
        """Create a post-recording question record in the database"""
        question_data = {
            "question_text": question_text,
            "question_type": question_type,  # "scale", "binary", "free_text"
        }
        
        # Add optional metadata if columns exist
        if question_set_id is not None:
            question_data["question_set_id"] = question_set_id
        if order_index is not None:
            question_data["order_index"] = order_index
        
        result = self.client.table("post_recording_questions")\
            .insert(question_data)\
            .execute()
        
        return result.data[0] if result.data else None
    
    def save_post_answers(self, session_id: str, recording_id: str, answers: list):
        """Save post-recording answers"""
        # Validate that question_ids are valid UUIDs
        for ans in answers:
            question_id = ans.get("question_id")
            if not question_id:
                raise ValueError(f"Missing question_id in answer: {ans}")
            # Check if it's a valid UUID format (basic check)
            if len(question_id) != 36 or question_id.count('-') != 4:
                raise ValueError(f"Invalid question_id format (must be UUID): {question_id}")
        
        records = [
            {
                "recording_id": recording_id,
                "session_id": session_id,
                "question_id": ans["question_id"],
                "answer_text": ans["answer_text"]
            }
            for ans in answers
        ]
        
        result = self.client.table("post_recording_answers")\
            .insert(records)\
            .execute()
        
        # Mark session as post_questions_completed
        self.client.table("recording_sessions")\
            .update({"post_questions_completed": True})\
            .eq("id", session_id)\
            .execute()
        
        return result.data
    
    def complete_session(self, session_id: str):
        """Mark session as completed (status + completed_at for v1 predicate)"""
        result = self.client.table("recording_sessions")\
            .update({"status": "completed", "completed_at": "now()"})\
            .eq("id", session_id)\
            .execute()
        
        return result.data[0] if result.data else None
    
    def get_previous_performance_score(self, user_id: str, exclude_recording_id: str = None):
        """Get the most recent performance score for a user"""
        # Get user's recordings ordered by date
        query = self.client.table("recordings")\
            .select("id")\
            .eq("user_id", user_id)\
            .order("created_at", desc=True)\
            .limit(10)\
            .execute()
        
        if not query.data:
            return None
        
        # Find the previous recording (exclude current if specified)
        previous_recording_id = None
        for rec in query.data:
            if rec["id"] != exclude_recording_id:
                previous_recording_id = rec["id"]
                break
        
        if not previous_recording_id:
            return None
        
        # Get performance score for that recording
        perf_result = self.client.table("performance_scores")\
            .select("performance")\
            .eq("recording_id", previous_recording_id)\
            .execute()
        
        if perf_result.data:
            return float(perf_result.data[0].get("performance", 0))
        
        return None
    
    def save_performance_score(self, recording_id: str, performance_data: dict):
        """Save performance score to database"""
        score_data = {
            "recording_id": recording_id,
            "performance": performance_data["performance"],
            "final_kpi": performance_data["final_kpi"],
            "resilience_bonus": performance_data.get("bonuses", {}).get("resilience", 0),
            "awareness_bonus": performance_data.get("bonuses", {}).get("awareness", 0),
            "progress_bonus": performance_data.get("bonuses", {}).get("progress", 0),
            "streak_bonus": performance_data.get("bonuses", {}).get("streak", 0),
            "filler_score": performance_data.get("raw_scores", {}).get("filler_score", 0),
            "pacing_score": performance_data.get("raw_scores", {}).get("pacing_score", 0),
            "attitude_score": performance_data.get("raw_scores", {}).get("attitude_score", 0),
            "reflection_score": performance_data.get("raw_scores", {}).get("reflection_score", 0),
        }
        if "self_rating_score" in performance_data:
            score_data["self_rating_score"] = performance_data["self_rating_score"]
        
        result = self.client.table("performance_scores")\
            .insert(score_data)\
            .execute()
        
        return result.data[0] if result.data else None
    
    def get_performance_score(self, recording_id: str):
        """Get performance score for a recording"""
        result = self.client.table("performance_scores")\
            .select("*")\
            .eq("recording_id", recording_id)\
            .execute()
        
        return result.data[0] if result.data else None
    
    def get_user_admin_context(self, user_id: str):
        """Return admin context for report generation. V2: no professional_notes tables; minimal dict."""
        return {
            "general_notes": None,
            "custom_instructions": None,
            "max_words": 120,
            "specific_questions": [],
        }
    
    def get_user_recording_history(self, user_id: str, exclude_recording_id: str = None, limit: int = 10):
        """Get user's recording history for progress tracking (v2: recordings only)."""
        query = (
            self.client.table("recordings")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
        )
        if exclude_recording_id:
            query = query.neq("id", exclude_recording_id)
        result = query.execute()
        return result.data if result.data else []
    
    def get_session(self, session_id: str, user_id: str = None):
        """Get a session by ID"""
        query = self.client.table("recording_sessions").select("*").eq("id", session_id)
        
        if user_id:
            query = query.eq("user_id", user_id)
        
        result = query.execute()
        
        return result.data[0] if result.data else None
    
    def get_pre_answers(self, session_id: str):
        """Get pre-recording answers for a session"""
        result = self.client.table("pre_recording_answers")\
            .select("*,pre_recording_questions(*)")\
            .eq("recording_session_id", session_id)\
            .execute()
        
        return result.data
    
    def get_post_answers(self, session_id: str):
        """Get post-recording answers for a session"""
        result = self.client.table("post_recording_answers")\
            .select("*,post_recording_questions(*)")\
            .eq("session_id", session_id)\
            .execute()
        
        return result.data
    
    def get_user_profile(self, user_id: str):
        """Get user profile with summary stats"""
        # Get recording stats
        recordings = self.get_user_recordings(user_id, limit=1000)
        
        total_recordings = len(recordings)
        latest_recordings = recordings[:5]
        
        return {
            "user_id": user_id,
            "total_recordings": total_recordings,
            "latest_recordings": latest_recordings
        }
    
    def create_signed_url(self, bucket: str, path: str, expires_in: int = 3600):
        """Create a signed URL for a file in Supabase Storage"""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # Supabase Python client create_signed_url returns a response object
            response = self.client.storage.from_(bucket).create_signed_url(
                path, expires_in
            )
            
            # Log the response for debugging
            logger.info(f"Signed URL response type: {type(response)}, response: {response}")
            
            # Supabase Python SDK returns dict with 'signedUrl' key (camelCase)
            # Format: {'signedUrl': 'https://...'}
            signed_url = None
            
            # Try direct dict access first (most common)
            if isinstance(response, dict):
                signed_url = response.get("signedUrl") or response.get("signedURL") or response.get("signed_url") or response.get("url")
            # Try accessing .data attribute if it exists
            elif hasattr(response, 'data'):
                data = response.data
                if isinstance(data, dict):
                    signed_url = data.get("signedUrl") or data.get("signedURL") or data.get("signed_url") or data.get("url")
                elif isinstance(data, str):
                    signed_url = data
            # Try string
            elif isinstance(response, str):
                signed_url = response
            # Try object attributes
            else:
                signed_url = getattr(response, "signedUrl", None) or getattr(response, "signedURL", None) or getattr(response, "signed_url", None) or getattr(response, "url", None)
            
            # If still no URL, try to inspect the response more deeply
            if not signed_url:
                logger.warning(f"Could not extract signed URL, response structure: {dir(response) if hasattr(response, '__dict__') else 'N/A'}")
                # Last resort: try to convert to string and parse
                response_str = str(response)
                if "http" in response_str:
                    # Try to extract URL from string representation
                    import re
                    urls = re.findall(r'https?://[^\s<>"{}|\\^`\[\]]+', response_str)
                    if urls:
                        signed_url = urls[0]
            
            if not signed_url:
                raise Exception(f"Could not extract signed URL from response: {response} (type: {type(response)})")
            
            # Ensure it's a full URL
            if not signed_url.startswith("http"):
                raise Exception(f"Signed URL is not a full URL: {signed_url}")
            
            logger.info(f"Successfully created signed URL for {bucket}/{path}: {signed_url[:80]}...")
            return signed_url
        except Exception as e:
            logger.error(f"Error creating signed URL for {bucket}/{path}: {str(e)}")
            sentry_sdk.capture_exception(e)
            raise Exception(f"Failed to create signed URL: {str(e)}")

    def create_signed_upload_url(self, bucket: str, path: str):
        """Create a signed upload URL for direct PUT upload (recording-upload-url). Returns a single URL string or None if not supported."""
        try:
            bucket_api = self.client.storage.from_(bucket)
            create_upload = getattr(bucket_api, "create_signed_upload_url", None)
            if callable(create_upload):
                result = create_upload(path)
                if isinstance(result, dict):
                    url = result.get("signedUrl") or result.get("signed_url") or result.get("url") or result.get("path")
                    if isinstance(url, str) and url.startswith("http"):
                        return url
                if hasattr(result, "signed_url"):
                    u = getattr(result, "signed_url", None) or getattr(result, "signedUrl", None) or getattr(result, "url", None)
                    if isinstance(u, str) and u.startswith("http"):
                        return u
        except Exception:
            pass
        try:
            import httpx
            base = (config.SUPABASE_URL or "").rstrip("/")
            key = config.SUPABASE_SERVICE_ROLE_KEY or ""
            if not base or not key:
                return None
            url_path = path.lstrip("/")
            resp = httpx.post(
                f"{base}/storage/v1/object/upload/sign/{bucket}",
                json={"path": url_path},
                headers={"Authorization": f"Bearer {key}", "apikey": key, "Content-Type": "application/json"},
                timeout=10.0,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            if isinstance(data, dict):
                signed = data.get("signedUrl") or data.get("signed_url") or data.get("url")
                if isinstance(signed, str) and signed.startswith("http"):
                    return signed
            return None
        except Exception:
            return None

    def upload_audio(self, bucket: str, path: str, file_data: bytes, content_type: str = "audio/webm"):
        """Upload audio file to Supabase Storage"""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # Ensure file_data is bytes
            if not isinstance(file_data, bytes):
                if isinstance(file_data, bool):
                    raise ValueError(f"file_data cannot be a boolean. Got: {type(file_data)}, value: {file_data}")
                file_data = bytes(file_data)
            
            # Ensure path is a string
            if not isinstance(path, str):
                if isinstance(path, bool):
                    raise ValueError(f"path cannot be a boolean. Got: {type(path)}, value: {path}")
                path = str(path)
            
            # Ensure bucket is a string
            if not isinstance(bucket, str):
                if isinstance(bucket, bool):
                    raise ValueError(f"bucket cannot be a boolean. Got: {type(bucket)}, value: {bucket}")
                bucket = str(bucket)
            
            # Ensure content_type is a string
            if not isinstance(content_type, str):
                if isinstance(content_type, bool):
                    raise ValueError(f"content_type cannot be a boolean. Got: {type(content_type)}, value: {content_type}")
                content_type = str(content_type) if content_type else "audio/webm"
            
            # Log parameters for debugging
            logger.info(f"Uploading audio: bucket={bucket} (type: {type(bucket)}), path={path} (type: {type(path)}), content_type={content_type} (type: {type(content_type)}), file_data size={len(file_data)} bytes (type: {type(file_data)})")
            
            # Ensure file_options values are correct types
            # Only include content-type in file_options (upsert might cause encoding issues)
            file_options = {
                "content-type": str(content_type)
            }
            
            logger.info(f"file_options: {file_options}")
            
            # Supabase Python client expects: upload(path, file=file_data, file_options={...})
            # Use keyword argument for 'file' parameter
            # Note: If file already exists, it will be overwritten by default
            result = self.client.storage.from_(bucket).upload(
                path=path,
                file=file_data,
                file_options=file_options
            )
            return result
        except Exception as e:
            logger.error(f"Upload error details: {str(e)}, type: {type(e)}")
            sentry_sdk.capture_exception(e)
            raise Exception(f"Failed to upload audio: {str(e)}")

    def download_audio(self, bucket: str, path: str) -> bytes:
        """Download audio file from Supabase Storage. Used when client uploads by URL (storage_path) and backend fetches for transcription."""
        import logging
        logger = logging.getLogger(__name__)
        try:
            if not isinstance(bucket, str) or not isinstance(path, str):
                raise ValueError("bucket and path must be strings")
            result = self.client.storage.from_(bucket).download(path)
            if isinstance(result, bytes):
                return result
            if hasattr(result, "content"):
                return result.content if isinstance(result.content, bytes) else bytes(result.content)
            if hasattr(result, "read"):
                data = result.read()
                return data if isinstance(data, bytes) else bytes(data)
            raise Exception(f"Unexpected download result type: {type(result)}")
        except Exception as e:
            logger.error(f"Download error for {bucket}/{path}: {str(e)}")
            sentry_sdk.capture_exception(e)
            raise Exception(f"Failed to download audio: {str(e)}")

    def save_admin_notification(self, data: dict):
        """Save admin notification record"""
        result = self.client.table("admin_notifications")\
            .insert(data)\
            .execute()
        
        return result.data[0] if result.data else None
    
    def update_admin_notification(self, notification_id: str, data: dict):
        """Update admin notification status"""
        result = self.client.table("admin_notifications")\
            .update(data)\
            .eq("id", notification_id)\
            .execute()
        
        return result.data[0] if result.data else None

    # --- v1 planned session flow ---
    def get_active_override(self, user_id: str):
        """Get active admin_session_override for user (is_active, not expired, remaining_sessions null or >0)."""
        from datetime import datetime
        now = datetime.utcnow().isoformat() if hasattr(datetime, 'utcnow') else datetime.now().isoformat()
        result = self.client.table("admin_session_overrides")\
            .select("*")\
            .eq("user_id", user_id)\
            .eq("is_active", True)\
            .execute()
        if not result.data:
            return None
        for row in result.data:
            if row.get("expires_at") and str(row["expires_at"]) < now:
                continue
            remaining = row.get("remaining_sessions")
            if remaining is not None and remaining <= 0:
                continue
            return row
        return None

    def consume_admin_override(self, override_id: str):
        """Decrement remaining_sessions if not null. Idempotent: only decrement once per override use."""
        row = self.client.table("admin_session_overrides").select("remaining_sessions").eq("id", override_id).execute()
        if not row.data:
            return
        remaining = row.data[0].get("remaining_sessions")
        if remaining is None:
            return
        self.client.table("admin_session_overrides")\
            .update({"remaining_sessions": max(0, remaining - 1)})\
            .eq("id", override_id)\
            .execute()

    def log_exposure(self, user_id: str, content_type: str, content_code: str, session_id: str = None,
                     recording_id: str = None, content_id: str = None, tier: int = None, was_selected: bool = False):
        """Insert content_exposures row (v1 anti-repetition + analytics)."""
        data = {
            "user_id": user_id,
            "content_type": content_type,
            "content_code": content_code,
            "was_selected": was_selected,
        }
        if session_id:
            data["session_id"] = session_id
        if recording_id:
            data["recording_id"] = recording_id
        if content_id:
            data["content_id"] = content_id
        if tier is not None:
            data["tier"] = tier
        try:
            self.client.table("content_exposures").insert(data).execute()
        except Exception:
            pass  # ignore duplicate / constraint errors for idempotency

    def get_recent_exposures(self, user_id: str, content_type: str, limit: int) -> List[dict]:
        """Recent exposures for user + content_type (for anti-repeat)."""
        result = self.client.table("content_exposures")\
            .select("content_code, session_id, was_selected, exposed_at")\
            .eq("user_id", user_id)\
            .eq("content_type", content_type)\
            .order("exposed_at", desc=True)\
            .limit(limit * 3)\
            .execute()
        return result.data or []

    def get_intent_selection_count(self, user_id: str, intent: str) -> int:
        """Count how many times this user has selected this intent (was_selected=true). Used to detect newly-tested command for post-question."""
        result = self.client.table("content_exposures")\
            .select("id", count="exact")\
            .eq("user_id", user_id)\
            .eq("content_type", "intent")\
            .eq("content_code", intent)\
            .eq("was_selected", True)\
            .execute()
        return getattr(result, "count", None) or len(result.data or [])

    def get_completed_sessions_count(self, user_id: str) -> int:
        """Count sessions with status = 'completed' for user (no_fillers_challenge gating)."""
        result = self.client.table("recording_sessions")\
            .select("id", count="exact")\
            .eq("user_id", user_id)\
            .eq("status", "completed")\
            .execute()
        return getattr(result, "count", None) or len(result.data or [])

    def get_avg_fillers_per_min(self, user_id: str, last_n: int = 5) -> float:
        """Avg fillers/min over last_n recordings. Uses recordings.duration and filler_words_count. If missing data -> return 999 (ineligible)."""
        recs = self.client.table("recordings")\
            .select("id, duration, filler_words_count")\
            .eq("user_id", user_id)\
            .order("created_at", desc=True)\
            .limit(last_n)\
            .execute()
        if not recs.data or len(recs.data) < last_n:
            return 999.0
        total_fillers = 0
        total_min = 0
        for r in recs.data:
            dur = r.get("duration")
            fc = r.get("filler_words_count")
            if dur is None or not isinstance(dur, (int, float)) or dur <= 0:
                return 999.0
            total = None
            if isinstance(fc, dict):
                total = fc.get("total")
            if total is None:
                return 999.0
            total_fillers += int(total)
            total_min += float(dur) / 60.0
        if total_min <= 0:
            return 999.0
        return total_fillers / total_min

    def get_pre_question_templates_for_theme(self, theme_code: str = None, exclude_codes: List[str] = None, limit: int = 1) -> List[dict]:
        """Get active pre_recording_questions for theme (theme_code or theme_code IS NULL). Exclude codes if provided."""
        q = self.client.table("pre_recording_questions")\
            .select("*")\
            .eq("active", True)\
            .order("order_index")
        if theme_code:
            q = q.eq("theme_code", theme_code)
        else:
            q = q.is_("theme_code", "null")
        result = q.limit(limit * 3).execute()
        rows = result.data or []
        if exclude_codes:
            rows = [r for r in rows if r.get("code") not in exclude_codes]
        return rows[:limit]

    def insert_session_command_options(self, session_id: str, options: List[dict]):
        """Insert rows into session_command_options (option_id, intent, tier, mode, prompt_text_snapshot, is_primary, cursor_min, cursor_max)."""
        for o in options:
            row = {
                "session_id": session_id,
                "option_id": o["option_id"],
                "intent": o["intent"],
                "tier": o["tier"],
                "mode": o["mode"],
                "prompt_text_snapshot": o["prompt_text_snapshot"],
                "is_primary": o.get("is_primary", False),
            }
            if o.get("cursor_min") is not None:
                row["cursor_min"] = o["cursor_min"]
            if o.get("cursor_max") is not None:
                row["cursor_max"] = o["cursor_max"]
            try:
                self.client.table("session_command_options").insert(row).execute()
            except Exception:
                pass

    def get_session_command_options(self, session_id: str) -> List[dict]:
        """Get session_command_options for session (A/B/C)."""
        result = self.client.table("session_command_options")\
            .select("*")\
            .eq("session_id", session_id)\
            .order("option_id")\
            .execute()
        return result.data or []

    def update_session_planned_pre_question(self, session_id: str, planned_id: str, text_snapshot: str, type_snapshot: str, code_snapshot: str):
        """Set planned pre-question snapshot on session."""
        self.client.table("recording_sessions")\
            .update({
                "planned_pre_question_id": planned_id,
                "planned_pre_question_text_snapshot": text_snapshot,
                "planned_pre_question_type_snapshot": type_snapshot,
                "planned_pre_question_code_snapshot": code_snapshot,
            })\
            .eq("id", session_id)\
            .execute()

    def update_session_theme(self, session_id: str, recommended_code: str = None, recommended_reason: str = None, chosen_code: str = None, chosen_source: str = None):
        """Set theme decision on session."""
        data = {}
        if recommended_code is not None:
            data["theme_recommended_code"] = recommended_code
        if recommended_reason is not None:
            data["theme_recommended_reason"] = recommended_reason
        if chosen_code is not None:
            data["theme_chosen_code"] = chosen_code
        if chosen_source is not None:
            data["theme_chosen_source"] = chosen_source
        if data:
            self.client.table("recording_sessions").update(data).eq("id", session_id).execute()

    def update_session_selected_command(self, session_id: str, option_id: str, intent: str, tier: int, mode: str, prompt_snapshot: str):
        """Persist selected command snapshot; mirror mode into structure (rollout)."""
        self.client.table("recording_sessions")\
            .update({
                "selected_command_option_id": option_id,
                "selected_intent": intent,
                "selected_tier": tier,
                "selected_mode": mode,
                "selected_prompt_text_snapshot": prompt_snapshot,
                "structure": mode,
            })\
            .eq("id", session_id)\
            .execute()

    def update_session_post_question_set_id(self, session_id: str, set_id: int):
        """Set post_question_set_id on session (chosen at upload)."""
        self.client.table("recording_sessions")\
            .update({"post_question_set_id": set_id})\
            .eq("id", session_id)\
            .execute()

    def update_session_admin_override_consumed(self, session_id: str, override_id: str):
        """Set admin_override_id_applied and admin_override_consumed_at (idempotent guard)."""
        self.client.table("recording_sessions")\
            .update({
                "admin_override_id_applied": override_id,
                "admin_override_consumed_at": "now()",
            })\
            .eq("id", session_id)\
            .execute()

    def get_recent_theme_exposures_by_session(self, user_id: str, limit_sessions: int = 2) -> List[str]:
        """Get theme_chosen_code from last N completed sessions (for anti-repeat)."""
        sessions = self.client.table("recording_sessions")\
            .select("theme_chosen_code")\
            .eq("user_id", user_id)\
            .eq("status", "completed")\
            .not_.is_("theme_chosen_code", "null")\
            .order("completed_at", desc=True)\
            .limit(limit_sessions)\
            .execute()
        return [s["theme_chosen_code"] for s in (sessions.data or []) if s.get("theme_chosen_code")]

    def get_recent_post_set_exposures_by_theme(self, user_id: str, theme_code: str, limit_same_theme: int = 2) -> List[int]:
        """Get post_question_set_id from recent sessions for same theme (for anti-repeat at upload)."""
        sessions = self.client.table("recording_sessions")\
            .select("post_question_set_id")\
            .eq("user_id", user_id)\
            .eq("theme_chosen_code", theme_code)\
            .not_.is_("post_question_set_id", "null")\
            .order("completed_at", desc=True)\
            .limit(limit_same_theme)\
            .execute()
        return [s["post_question_set_id"] for s in (sessions.data or []) if s.get("post_question_set_id") is not None]

    def get_incomplete_sessions_older_than(self, days: float) -> List[dict]:
        """Return recording_sessions that are not completed and created_at is older than days (for cleanup)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        result = self.client.table("recording_sessions")\
            .select("id, created_at, status")\
            .neq("status", "completed")\
            .lt("created_at", cutoff)\
            .execute()
        return result.data or []

    def cleanup_incomplete_sessions(self, days: float = 10, dry_run: bool = False) -> Tuple[int, List[str]]:
        """
        Delete incomplete sessions (and their recordings, pre/post answers, command options, exposures) older than days.
        Incomplete = not concluded with a report (status != 'completed').
        Returns (deleted_count, list of deleted session ids).
        For testing without waiting 10 days: use days=0.04 (≈1 hour) or days=0.001 (≈1.4 min) with dry_run=True first.
        """
        sessions = self.get_incomplete_sessions_older_than(days)
        ids = [s["id"] for s in sessions]
        if dry_run:
            return len(ids), ids
        if not ids:
            return 0, []
        deleted_ids = []
        for session_id in ids:
            try:
                # Delete recordings for this session first (CASCADE will remove performance_scores, post_recording_answers by recording_id)
                self.client.table("recordings").delete().eq("session_id", session_id).execute()
                # Delete session (CASCADE: pre_recording_answers, post_recording_answers, session_command_options, content_exposures)
                self.client.table("recording_sessions").delete().eq("id", session_id).execute()
                deleted_ids.append(session_id)
            except Exception as e:
                sentry_sdk.capture_exception(e)
        return len(deleted_ids), deleted_ids

    # ---------- V2 flow ----------
    def v2_get_universal_questions(self):
        """Get 3 universal questions ordered by position."""
        result = self.client.table("v2_universal_questions").select("*").order("position").execute()
        return result.data or []

    def v2_get_active_exercises(self):
        """All active exercises."""
        result = self.client.table("v2_exercises").select("*").eq("is_active", True).execute()
        return result.data or []

    def v2_get_active_tasks(self):
        """All active tasks."""
        result = self.client.table("v2_tasks").select("*").eq("is_active", True).execute()
        return result.data or []

    def v2_get_post_questions_pool(self):
        """All active post-recording questions (from v2_post_recording_questions table)."""
        result = self.client.table("v2_post_recording_questions").select("*").eq("is_active", True).execute()
        return result.data or []

    def v2_get_metric_definitions(self):
        """All 5 metric definitions (code, left_label, right_label)."""
        result = self.client.table("v2_metric_definitions").select("*").execute()
        return result.data or []

    def v2_get_student_overrides(self, user_id: str):
        """Overrides for user (assigned post Qs, next exercise/task, prompt overrides)."""
        result = self.client.table("v2_student_overrides").select("*").eq("user_id", user_id).execute()
        return result.data[0] if result.data else None

    def v2_get_active_session(self, user_id: str):
        """Active v2 session (status != completed)."""
        result = (
            self.client.table("v2_sessions")
            .select("*")
            .eq("user_id", user_id)
            .neq("status", "completed")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_create_session(self, user_id: str):
        """Create new v2 session (status=universal_questions)."""
        result = self.client.table("v2_sessions").insert({"user_id": user_id, "status": "universal_questions"}).execute()
        return result.data[0] if result.data else None

    def v2_update_session(self, session_id: str, user_id: str, data: dict):
        """Update v2 session; verify user_id."""
        result = self.client.table("v2_sessions").update(data).eq("id", session_id).eq("user_id", user_id).execute()
        return result.data[0] if result.data else None

    def v2_delete_session(self, session_id: str, user_id: str) -> bool:
        """Delete v2 session (owner only). Recordings.session_v2_id set to NULL; v2_reports CASCADE deleted. Returns True when delete executes without error (Supabase delete may return empty body)."""
        result = self.client.table("v2_sessions").delete().eq("id", session_id).eq("user_id", user_id).execute()
        # PostgREST/Supabase delete often returns empty result.data even on success; if we got here without exception, treat as success.
        return True

    def v2_session_expired(self, session: dict, hours: float = 1.0) -> bool:
        """True if session is incomplete and created_at is older than hours. Disabled: always returns False so the app never deletes sessions by age."""
        return False

    def v2_get_incomplete_sessions_older_than(self, hours: float) -> List[dict]:
        """Return v2_sessions that are not completed and created_at is older than hours (for cleanup)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        result = (
            self.client.table("v2_sessions")
            .select("id, user_id, created_at, status")
            .neq("status", "completed")
            .lt("created_at", cutoff)
            .execute()
        )
        return result.data or []

    def v2_cleanup_incomplete_sessions(self, hours: float = 1.0, dry_run: bool = False) -> Tuple[int, List[str]]:
        """
        Delete incomplete v2_sessions (status != 'completed') older than hours.
        Uses v2_delete_session per row so recordings get session_v2_id set to NULL and v2_reports CASCADE.
        Returns (deleted_count, list of deleted session ids). Default 1 hour.
        """
        sessions = self.v2_get_incomplete_sessions_older_than(hours)
        ids = [s["id"] for s in sessions]
        if dry_run:
            return len(ids), ids
        deleted_ids = []
        for s in sessions:
            session_id = s.get("id")
            user_id = s.get("user_id")
            if session_id and user_id:
                try:
                    if self.v2_delete_session(session_id, user_id):
                        deleted_ids.append(session_id)
                except Exception as e:
                    sentry_sdk.capture_exception(e)
        return len(deleted_ids), deleted_ids

    def v2_get_session(self, session_id: str, user_id: str = None):
        """Get v2 session by id, optionally scoped to user."""
        q = self.client.table("v2_sessions").select("*").eq("id", session_id)
        if user_id:
            q = q.eq("user_id", user_id)
        result = q.execute()
        return result.data[0] if result.data else None

    def v2_get_session_by_id(self, session_id: str):
        """Get v2 session by id only (no user filter). For debugging 404: check if session exists and which user_id owns it."""
        return self.v2_get_session(session_id, None)

    def v2_get_last_completed_session(self, user_id: str):
        """Return the most recent completed session for the user (for tutor_feedback_deadline when no active session). Includes tutor_feedback_sent_at so deadline is omitted once feedback is sent."""
        result = (
            self.client.table("v2_sessions")
            .select("id, completed_at, created_at, tutor_feedback_sent_at")
            .eq("user_id", user_id)
            .eq("status", "completed")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_mark_tutor_feedback_sent(self, session_id: str, user_id: str):
        """Set tutor_feedback_sent_at to now for this session (idempotent)."""
        from datetime import datetime, timezone
        self.client.table("v2_sessions").update({
            "tutor_feedback_sent_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", session_id).eq("user_id", user_id).execute()
        return True

    def v2_mark_tutor_feedback_sent_for_user(self, user_id: str):
        """Set tutor_feedback_sent_at on the user's most recent completed session (idempotent). Call when admin sends new homework (POST send-assignment)."""
        last = self.v2_get_last_completed_session(user_id)
        if not last or last.get("tutor_feedback_sent_at"):
            return
        self.v2_mark_tutor_feedback_sent(last["id"], user_id)

    def v2_get_exercise(self, exercise_id: str):
        result = self.client.table("v2_exercises").select("*").eq("id", exercise_id).execute()
        return result.data[0] if result.data else None

    def v2_get_exercise_by_title(self, title: str):
        """First active exercise with this title (case-insensitive), or None. Used for default '0-intro'."""
        if not (title or "").strip():
            return None
        result = (
            self.client.table("v2_exercises")
            .select("*")
            .eq("is_active", True)
            .ilike("title", (title or "").strip())
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def _format_exercise_for_step0(self, ex: dict) -> dict:
        return {
            "id": str(ex["id"]) if ex.get("id") else None,
            "title": (ex.get("title") or "").strip() or "Exercise",
            "video_url": (ex.get("video_url") or "").strip() or None,
            "description": (ex.get("description") or "").strip() or None,
        }

    def v2_get_assigned_exercises_for_user(self, user_id: str):
        """Exercises for step 0 (no active session). Always returns at least one: assigned_next_exercise_id, else last_assigned_exercise_id, else 0-intro by title, else placeholder."""
        overrides = self.v2_get_student_overrides(user_id) or {}
        # Prefer current assignment, then last assigned (so old exercise stays visible until new one is set)
        exercise_id = overrides.get("assigned_next_exercise_id") or overrides.get("last_assigned_exercise_id")
        ex = None
        if exercise_id:
            ex = self.v2_get_exercise(str(exercise_id))
            if ex and ex.get("is_active") is True:
                return [self._format_exercise_for_step0(ex)]
        # No assignment or exercise inactive: fall back to 0-intro (by title)
        ex = self.v2_get_exercise_by_title("0-intro")
        if ex:
            return [self._format_exercise_for_step0(ex)]
        # No 0-intro row: return placeholder (run migrations/seed_intro_0_exercise.sql so admin can set video_url)
        return [{"id": None, "title": "0-intro", "video_url": None, "description": None}]

    def v2_get_task(self, task_id: str):
        result = self.client.table("v2_tasks").select("*").eq("id", task_id).execute()
        return result.data[0] if result.data else None

    def v2_get_focus_task_by_id(self, task_id: str):
        """Single row from v2_focus_tasks by id, or None."""
        result = self.client.table("v2_focus_tasks").select("*").eq("id", task_id).execute()
        return result.data[0] if result.data else None

    def v2_get_last_completed_session_task_ids(self, user_id: str, limit: int = 2):
        """Return selected_task_id from the last N completed sessions (for anti-repeat in focus task selection)."""
        result = (
            self.client.table("v2_sessions")
            .select("selected_task_id")
            .eq("user_id", user_id)
            .eq("status", "completed")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        out = []
        for row in (result.data or []):
            tid = row.get("selected_task_id")
            if tid and str(tid).strip() and str(tid) not in out:
                out.append(str(tid))
        return out

    def v2_get_student_coaching_memory(self, user_id: str):
        """Return the coaching memory row for the user, or None if none exists."""
        result = (
            self.client.table("v2_student_coaching_memory")
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_upsert_student_coaching_memory(self, user_id: str, session_id: str):
        """
        Update per-student coaching memory from the last 5 completed sessions.
        Call after session is marked completed (e.g. after v2_update_session in post-answers).
        Current session is included; when loading the other 4, exclude session_id explicitly for idempotency.
        Derives recurring_issues from last 5 recording_1_performance_profile (e.g. too_fast in >=3 of 5).
        """
        # Fetch only the columns we need for this upsert (faster than full session)
        result = (
            self.client.table("v2_sessions")
            .select("status, performance_score_end, selected_task_id, recording_1_performance_profile")
            .eq("id", session_id)
            .eq("user_id", user_id)
            .execute()
        )
        session = result.data[0] if result.data else None
        if not session or (session.get("status") or "").strip().lower() != "completed":
            return
        current_score = session.get("performance_score_end")
        current_task_id = session.get("selected_task_id")
        current_profile = session.get("recording_1_performance_profile")

        # Last 4 OTHER completed sessions (exclude current session_id); include profile for recurring_issues
        result = (
            self.client.table("v2_sessions")
            .select("performance_score_end, selected_task_id, recording_1_performance_profile")
            .eq("user_id", user_id)
            .eq("status", "completed")
            .neq("id", session_id)
            .order("completed_at", desc=True)
            .limit(4)
            .execute()
        )
        others = list(reversed(result.data or []))  # oldest first

        last_5_scores = []
        recent_focus_task_ids = []
        last_5_profiles = []
        for row in others:
            s = row.get("performance_score_end")
            if s is not None:
                try:
                    last_5_scores.append(float(s))
                except (TypeError, ValueError):
                    pass
            tid = row.get("selected_task_id")
            if tid and str(tid).strip():
                recent_focus_task_ids.append(str(tid))
            prof = row.get("recording_1_performance_profile")
            last_5_profiles.append(prof if isinstance(prof, dict) else None)

        if current_score is not None:
            try:
                last_5_scores.append(float(current_score))
            except (TypeError, ValueError):
                pass
        if current_task_id and str(current_task_id).strip():
            recent_focus_task_ids.append(str(current_task_id))
        last_5_profiles.append(current_profile if isinstance(current_profile, dict) else None)

        last_5_scores = last_5_scores[-5:]
        recent_focus_task_ids = recent_focus_task_ids[-5:]
        last_5_profiles = last_5_profiles[-5:]

        # Recurring issues: if a pattern appears in >=3 of last 5 profiles, add it (cap at 3 issues)
        recurring_issues = []
        too_fast_count = sum(1 for p in last_5_profiles if p and (p.get("pace_level") or "").strip() == "too_fast")
        if too_fast_count >= 3:
            recurring_issues.append("too_fast")
        too_slow_count = sum(1 for p in last_5_profiles if p and (p.get("pace_level") or "").strip() == "too_slow")
        if too_slow_count >= 3:
            recurring_issues.append("too_slow")
        high_fillers_count = sum(1 for p in last_5_profiles if p and (p.get("filler_level") or "").strip() == "high")
        if high_fillers_count >= 3:
            recurring_issues.append("high_fillers")
        recurring_issues = recurring_issues[:3]

        payload = {
            "user_id": user_id,
            "last_5_scores": last_5_scores,
            "recent_focus_task_ids": recent_focus_task_ids,
            "recurring_issues": recurring_issues,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.client.table("v2_student_coaching_memory").upsert(
            payload, on_conflict="user_id"
        ).execute()

    # ---------- Sniper adaptive (user_sniper_profile, session_sniper_metrics) ----------

    def get_sniper_profile(self, user_id: str) -> Optional[dict]:
        """Get user_sniper_profile row or None."""
        result = self.client.table("user_sniper_profile").select("*").eq("user_id", user_id).execute()
        return result.data[0] if result.data else None

    def upsert_sniper_profile(
        self,
        user_id: str,
        session_count: int,
        sessions_with_energy_count: int = 0,
        baseline_wpm: Optional[float] = None,
        baseline_pause_ms: Optional[float] = None,
        baseline_dynamic_db: Optional[float] = None,
        baseline_emphasis_per_min: Optional[float] = None,
        baseline_energy_ratio: Optional[float] = None,
        baseline_fatigue_sec: Optional[float] = None,
    ):
        """Insert or update user_sniper_profile. Pass only fields to set; None leaves existing."""
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "user_id": user_id,
            "session_count": session_count,
            "sessions_with_energy_count": sessions_with_energy_count,
            "updated_at": now,
        }
        if baseline_wpm is not None:
            payload["baseline_wpm"] = baseline_wpm
        if baseline_pause_ms is not None:
            payload["baseline_pause_ms"] = baseline_pause_ms
        if baseline_dynamic_db is not None:
            payload["baseline_dynamic_db"] = baseline_dynamic_db
        if baseline_emphasis_per_min is not None:
            payload["baseline_emphasis_per_min"] = baseline_emphasis_per_min
        if baseline_energy_ratio is not None:
            payload["baseline_energy_ratio"] = baseline_energy_ratio
        if baseline_fatigue_sec is not None:
            payload["baseline_fatigue_sec"] = baseline_fatigue_sec
        self.client.table("user_sniper_profile").upsert(payload, on_conflict="user_id").execute()

    def save_session_sniper_metrics(
        self,
        session_id: str,
        user_id: str,
        wpm: Optional[float] = None,
        pause_ms: Optional[float] = None,
        dynamic_db: Optional[float] = None,
        emphasis_per_min: Optional[float] = None,
        energy_ratio: Optional[float] = None,
        stage_score: Optional[float] = None,
        voiced_duration_sec: Optional[float] = None,
        student_rating_1_10: Optional[int] = None,
    ):
        """Upsert session_sniper_metrics (from client sniper-session-complete)."""
        payload = {"session_id": session_id, "user_id": user_id}
        if wpm is not None:
            payload["wpm"] = wpm
        if pause_ms is not None:
            payload["pause_ms"] = pause_ms
        if dynamic_db is not None:
            payload["dynamic_db"] = dynamic_db
        if emphasis_per_min is not None:
            payload["emphasis_per_min"] = emphasis_per_min
        if energy_ratio is not None:
            payload["energy_ratio"] = energy_ratio
        if stage_score is not None:
            payload["stage_score"] = stage_score
        if voiced_duration_sec is not None:
            payload["voiced_duration_sec"] = voiced_duration_sec
        if student_rating_1_10 is not None:
            payload["student_rating_1_10"] = student_rating_1_10
        self.client.table("session_sniper_metrics").upsert(payload, on_conflict="session_id").execute()

    def get_session_sniper_metrics(self, session_id: str) -> Optional[dict]:
        """Get session_sniper_metrics for session or None."""
        result = self.client.table("session_sniper_metrics").select("*").eq("session_id", session_id).execute()
        return result.data[0] if result.data else None

    def update_or_set_session_sniper_rating(
        self, session_id: str, user_id: str, student_rating_1_10: int
    ) -> bool:
        """Set student_rating_1_10 for a session (owned by user). Updates existing row or inserts one. Returns True if ok."""
        session = self.v2_get_session(session_id, user_id)
        if not session:
            return False
        r = (
            self.client.table("session_sniper_metrics")
            .update({"student_rating_1_10": student_rating_1_10})
            .eq("session_id", session_id)
            .eq("user_id", user_id)
            .execute()
        )
        if r.data and len(r.data) > 0:
            return True
        self.client.table("session_sniper_metrics").insert(
            {"session_id": session_id, "user_id": user_id, "student_rating_1_10": student_rating_1_10}
        ).execute()
        return True

    def update_sniper_baseline_from_payload(
        self,
        user_id: str,
        *,
        session_id: Optional[str] = None,
        wpm: Optional[float] = None,
        pause_ms: Optional[float] = None,
        dynamic_db: Optional[float] = None,
        emphasis_per_min: Optional[float] = None,
        energy_ratio: Optional[float] = None,
        stage_score: Optional[float] = None,
        voiced_duration_sec: Optional[float] = None,
        student_rating_1_10: Optional[int] = None,
    ):
        """
        Update user_sniper_profile from a single POST payload (e.g. sniper-session-complete).
        Only when stage_score >= 60 and voiced_duration_sec >= 60, and only when
        student_rating_1_10 >= 8 or session coach_grade >= 8 (so only “good” sessions update baseline).
        """
        stage_100 = None
        if stage_score is not None:
            stage_100 = float(stage_score) * 100.0 if float(stage_score) <= 1.0 else float(stage_score)
        if stage_100 is None or stage_100 < 60:
            return
        if voiced_duration_sec is not None and voiced_duration_sec < 60:
            return
        if student_rating_1_10 is not None and student_rating_1_10 < 5:
            return
        if session_id:
            session = self.v2_get_session(session_id, user_id)
            if session and session.get("coach_grade") is not None and (session.get("coach_grade") or 0) < 5:
                return
        rating_ok = student_rating_1_10 is not None and student_rating_1_10 >= 8
        if not rating_ok and session_id:
            session = self.v2_get_session(session_id, user_id)
            if session and (session.get("coach_grade") or 0) >= 8:
                rating_ok = True
        if not rating_ok:
            return

        profile = self.get_sniper_profile(user_id)
        session_count = (profile.get("session_count") or 0) + 1
        had_energy = energy_ratio is not None
        sessions_with_energy = (profile.get("sessions_with_energy_count") or 0) + (1 if had_energy else 0)

        def ema(old: Optional[float], new: Optional[float]) -> Optional[float]:
            if new is None:
                return old
            if old is None:
                return new
            return 0.8 * old + 0.2 * new

        new_wpm = ema(profile.get("baseline_wpm"), wpm)
        new_pause = ema(profile.get("baseline_pause_ms"), pause_ms)
        new_dynamic = ema(profile.get("baseline_dynamic_db"), dynamic_db)
        new_emphasis = ema(profile.get("baseline_emphasis_per_min"), emphasis_per_min)
        new_energy_ratio = ema(profile.get("baseline_energy_ratio"), energy_ratio)

        self.upsert_sniper_profile(
            user_id=user_id,
            session_count=session_count,
            sessions_with_energy_count=sessions_with_energy,
            baseline_wpm=new_wpm,
            baseline_pause_ms=new_pause,
            baseline_dynamic_db=new_dynamic,
            baseline_emphasis_per_min=new_emphasis,
            baseline_energy_ratio=new_energy_ratio,
        )

    def update_sniper_baseline_from_session(
        self,
        session_id: str,
        user_id: str,
        recording_wpm: Optional[float] = None,
        recording_duration_sec: Optional[float] = None,
        performance_score_end: Optional[float] = None,
    ):
        """
        After session completes: merge session_sniper_metrics + recording into user_sniper_profile (EMA).
        Only update when stage_score >= 60, voiced_duration >= 60s, and (student_rating_1_10 >= 8 or coach_grade >= 8).
        Skip when either grade < 5 (low-rated session).
        """
        metrics = self.get_session_sniper_metrics(session_id)
        stage_score_100 = None
        if metrics and metrics.get("stage_score") is not None:
            stage_score_100 = float(metrics["stage_score"])
        elif performance_score_end is not None:
            stage_score_100 = float(performance_score_end) * 100.0
        voiced_sec = (metrics or {}).get("voiced_duration_sec")
        duration_sec = voiced_sec if voiced_sec is not None else recording_duration_sec
        if stage_score_100 is None or stage_score_100 < 60:
            return
        if duration_sec is not None and duration_sec < 60:
            return
        student_rating = (metrics or {}).get("student_rating_1_10")
        if student_rating is not None and int(student_rating) < 5:
            return
        session = self.v2_get_session(session_id, user_id)
        if session and session.get("coach_grade") is not None and (session.get("coach_grade") or 0) < 5:
            return
        rating_ok = student_rating is not None and int(student_rating) >= 8
        if not rating_ok and session and (session.get("coach_grade") or 0) >= 8:
            rating_ok = True
        if not rating_ok:
            return

        profile = self.get_sniper_profile(user_id)
        session_count = (profile.get("session_count") or 0) + 1
        had_energy = (metrics or {}).get("energy_ratio") is not None
        sessions_with_energy = (profile.get("sessions_with_energy_count") or 0) + (1 if had_energy else 0)

        def ema(old: Optional[float], new: Optional[float]) -> Optional[float]:
            if new is None:
                return old
            if old is None:
                return new
            return 0.8 * old + 0.2 * new

        wpm = recording_wpm if recording_wpm is not None else (metrics or {}).get("wpm")
        new_wpm = ema(profile.get("baseline_wpm"), wpm)
        new_pause = ema(profile.get("baseline_pause_ms"), (metrics or {}).get("pause_ms"))
        new_dynamic = ema(profile.get("baseline_dynamic_db"), (metrics or {}).get("dynamic_db"))
        new_emphasis = ema(profile.get("baseline_emphasis_per_min"), (metrics or {}).get("emphasis_per_min"))
        new_energy_ratio = ema(profile.get("baseline_energy_ratio"), (metrics or {}).get("energy_ratio"))

        self.upsert_sniper_profile(
            user_id=user_id,
            session_count=session_count,
            sessions_with_energy_count=sessions_with_energy,
            baseline_wpm=new_wpm,
            baseline_pause_ms=new_pause,
            baseline_dynamic_db=new_dynamic,
            baseline_emphasis_per_min=new_emphasis,
            baseline_energy_ratio=new_energy_ratio,
        )

    def v2_select_student_focus_task_for_score(self, user_id: str, performance_score_1: float):
        """
        Per-student focus task for homework flow. Returns one task from v2_focus_tasks where
        max_performance_score >= performance_score_1 (student's score within task range).
        Excludes tasks used in recent completed sessions (anti-repeat): uses coaching memory
        recent_focus_task_ids (up to 5) when available, else last 2 sessions. Order by order_index;
        if multiple eligible, pick first. Returns normalized dict { id, title, prompt_text }, or None.
        """
        rows = self.v2_get_focus_tasks(user_id)
        if not rows:
            return None
        memory = self.v2_get_student_coaching_memory(user_id)
        if memory and isinstance(memory.get("recent_focus_task_ids"), list) and memory["recent_focus_task_ids"]:
            exclude_task_ids = set(str(t) for t in (memory["recent_focus_task_ids"] or [])[:5] if t)
        else:
            exclude_task_ids = set(self.v2_get_last_completed_session_task_ids(user_id, limit=2))
        score = float(performance_score_1)
        eligible = [r for r in rows if float(r.get("max_performance_score", 1.0)) >= score]
        if not eligible:
            eligible = [max(rows, key=lambda r: float(r.get("max_performance_score", 1.0)))]
        # Prefer tasks not used in recent sessions (from memory or last 2)
        not_recent = [r for r in eligible if str(r.get("id")) not in exclude_task_ids]
        if not_recent:
            eligible = not_recent
        # Multi-factor: when we have recurring_issues and any task has targets, score by weakness match
        pick_list = eligible
        if memory and isinstance(memory.get("recurring_issues"), list) and memory["recurring_issues"]:
            has_targets = any((r.get("targets") or []) for r in pick_list)
            if has_targets:
                chosen = score_and_pick_focus_task(
                    pick_list,
                    memory["recurring_issues"],
                    performance_score_1,
                )
                if chosen:
                    row = chosen
                else:
                    row = pick_list[0]
            else:
                row = pick_list[0]
        else:
            row = pick_list[0]
        text = (row.get("text") or "").strip()
        return {
            "id": row["id"],
            "title": text,
            "prompt_text": text,
        }

    def v2_get_task_or_focus_task(self, task_id: str):
        """
        Resolve task from either v2_focus_tasks or v2_tasks (so selected_task_id can
        refer to either). Returns normalized dict { id, title, prompt_text } or None.
        """
        if not task_id:
            return None
        focus = self.v2_get_focus_task_by_id(task_id)
        if focus:
            text = (focus.get("text") or "").strip()
            return {"id": focus["id"], "title": text, "prompt_text": text}
        task = self.v2_get_task(task_id)
        if task:
            return {
                "id": task["id"],
                "title": (task.get("title") or "").strip(),
                "prompt_text": (task.get("prompt_text") or "").strip(),
            }
        return None

    def v2_get_post_questions_by_ids(self, ids: List[str]):
        """Fetch pool questions by id list (for snapshot)."""
        if not ids:
            return []
        result = self.client.table("v2_post_recording_questions").select("*").in_("id", ids).execute()
        order = {str(x): i for i, x in enumerate(ids)}
        rows = result.data or []
        rows.sort(key=lambda r: order.get(str(r["id"]), 999))
        return rows

    def v2_insert_exercise(self, data: dict):
        result = self.client.table("v2_exercises").insert(data).execute()
        return result.data[0] if result.data else None

    def v2_update_exercise(self, exercise_id: str, data: dict):
        result = self.client.table("v2_exercises").update(data).eq("id", exercise_id).execute()
        return result.data[0] if result.data else None

    def v2_delete_exercise(self, exercise_id: str):
        """Soft-delete: set is_active=False. Or hard delete if preferred."""
        self.client.table("v2_exercises").update({"is_active": False}).eq("id", exercise_id).execute()

    def v2_insert_task(self, data: dict):
        result = self.client.table("v2_tasks").insert(data).execute()
        return result.data[0] if result.data else None

    def v2_update_task(self, task_id: str, data: dict):
        result = self.client.table("v2_tasks").update(data).eq("id", task_id).execute()
        return result.data[0] if result.data else None

    def v2_delete_task(self, task_id: str):
        """Soft-delete: set is_active=False so task no longer appears in student flow."""
        self.client.table("v2_tasks").update({"is_active": False}).eq("id", task_id).execute()

    def v2_insert_post_question_pool(self, data: dict):
        result = self.client.table("v2_post_recording_questions").insert(data).execute()
        return result.data[0] if result.data else None

    def v2_update_post_question_pool(self, question_id: str, data: dict):
        result = self.client.table("v2_post_recording_questions").update(data).eq("id", question_id).execute()
        return result.data[0] if result.data else None

    def v2_delete_post_question_pool(self, question_id: str):
        self.client.table("v2_post_recording_questions").delete().eq("id", question_id).execute()

    def v2_get_post_question_pool_by_id(self, question_id: str):
        result = self.client.table("v2_post_recording_questions").select("*").eq("id", question_id).execute()
        return result.data[0] if result.data else None

    # ---------- Per-student post-recording questions (same mechanism as focus_tasks) ----------
    def v2_get_student_post_recording_questions(self, user_id: str):
        result = (
            self.client.table("v2_student_post_recording_questions")
            .select("*")
            .eq("user_id", user_id)
            .order("order_index")
            .order("created_at")
            .execute()
        )
        return result.data or []

    def v2_insert_student_post_recording_question(self, data: dict):
        result = self.client.table("v2_student_post_recording_questions").insert(data).execute()
        return result.data[0] if result.data else None

    def v2_update_student_post_recording_question(self, question_id: str, data: dict):
        payload = {}
        for k in ("text", "order_index", "answer_type", "code"):
            if k in data:
                payload[k] = data[k]
        if not payload:
            result = self.client.table("v2_student_post_recording_questions").select("*").eq("id", question_id).execute()
            return result.data[0] if result.data else None
        result = self.client.table("v2_student_post_recording_questions").update(payload).eq("id", question_id).execute()
        return result.data[0] if result.data else None

    def v2_delete_student_post_recording_question(self, question_id: str):
        self.client.table("v2_student_post_recording_questions").delete().eq("id", question_id).execute()

    def v2_get_student_post_recording_questions_by_ids(self, ids: list):
        """Fetch per-student post-recording questions by row ids (e.g. session post_question_ids)."""
        if not ids:
            return []
        ids = [str(x) for x in ids]
        result = self.client.table("v2_student_post_recording_questions").select("*").in_("id", ids).execute()
        order = {str(x): i for i, x in enumerate(ids)}
        rows = result.data or []
        rows.sort(key=lambda r: order.get(str(r["id"]), 999))
        return rows

    def v2_sync_student_post_recording_questions_from_pool(self, user_id: str, pool_question_ids: list):
        """Replace student's post-recording questions with copies from the pool. Same pattern as focus_tasks sync."""
        self.client.table("v2_student_post_recording_questions").delete().eq("user_id", user_id).execute()
        if not pool_question_ids:
            return []
        inserted = []
        for idx, pool_id in enumerate(pool_question_ids):
            row = self.v2_get_post_question_pool_by_id(pool_id)
            if not row:
                continue
            data = {
                "user_id": user_id,
                "pool_question_id": pool_id,
                "text": row["text"],
                "order_index": idx,
                "answer_type": row.get("answer_type", "text"),
                "code": row.get("code"),
            }
            new_row = self.v2_insert_student_post_recording_question(data)
            if new_row:
                inserted.append(new_row)
        return inserted

    # ---------- Warm-up tasks (per student; homework flow) ----------
    DEFAULT_WARM_UP_TASK_TEXT = "How was your day so far?"
    DEFAULT_FOCUS_TASK_TEXT = "Pay attention to your breathing"

    def v2_ensure_default_warm_up_task(self, user_id: str) -> bool:
        """If user has no warm-up tasks, create the default one. Idempotent. Returns True if ok, False on failure (caller returns 422)."""
        import logging
        log = logging.getLogger(__name__)
        tasks = self.v2_get_warm_up_tasks(user_id)
        if tasks:
            return True
        data = {
            "user_id": user_id,
            "text": self.DEFAULT_WARM_UP_TASK_TEXT,
            "order_index": 0,
            "max_performance_score": 1,
        }
        try:
            self.v2_insert_warm_up_task(data)
            return True
        except Exception as e:
            log.warning("v2_ensure_default_warm_up_task insert failed for user_id=%s: %s", user_id, e)
            return False

    def v2_get_warm_up_tasks(self, user_id: str):
        result = (
            self.client.table("v2_warm_up_tasks")
            .select("*")
            .eq("user_id", user_id)
            .order("order_index")
            .order("created_at")
            .execute()
        )
        return result.data or []

    def v2_insert_warm_up_task(self, data: dict):
        result = self.client.table("v2_warm_up_tasks").insert(data).execute()
        return result.data[0] if result.data else None

    def v2_update_warm_up_task(self, task_id: str, data: dict):
        payload = {}
        if "text" in data:
            payload["text"] = data["text"]
        if "order_index" in data:
            payload["order_index"] = int(data["order_index"])
        if "max_performance_score" in data:
            try:
                payload["max_performance_score"] = float(data["max_performance_score"])
            except (TypeError, ValueError):
                payload["max_performance_score"] = 1.0
        if not payload:
            result = self.client.table("v2_warm_up_tasks").select("*").eq("id", task_id).execute()
            return result.data[0] if result.data else None
        result = self.client.table("v2_warm_up_tasks").update(payload).eq("id", task_id).execute()
        return result.data[0] if result.data else None

    def v2_delete_warm_up_task(self, task_id: str):
        self.client.table("v2_warm_up_tasks").delete().eq("id", task_id).execute()

    # ---------- Warm-up task pool (global pool; assign to students via modal) ----------
    def v2_get_warm_up_task_pool(self):
        result = (
            self.client.table("v2_warm_up_task_pool")
            .select("*")
            .order("order_index")
            .order("created_at")
            .execute()
        )
        return result.data or []

    def v2_get_warm_up_task_pool_by_id(self, pool_id: str):
        result = self.client.table("v2_warm_up_task_pool").select("*").eq("id", pool_id).execute()
        return result.data[0] if result.data else None

    def v2_insert_warm_up_task_pool(self, data: dict):
        data = dict(data)
        data.setdefault("order_index", 0)
        data.setdefault("max_performance_score", 1.0)
        result = self.client.table("v2_warm_up_task_pool").insert(data).execute()
        return result.data[0] if result.data else None

    def v2_update_warm_up_task_pool(self, pool_id: str, data: dict):
        payload = {}
        if "text" in data:
            payload["text"] = data["text"]
        if "order_index" in data:
            payload["order_index"] = int(data["order_index"])
        if "max_performance_score" in data:
            try:
                payload["max_performance_score"] = float(data["max_performance_score"])
            except (TypeError, ValueError):
                payload["max_performance_score"] = 1.0
        if not payload:
            return self.v2_get_warm_up_task_pool_by_id(pool_id)
        result = self.client.table("v2_warm_up_task_pool").update(payload).eq("id", pool_id).execute()
        return result.data[0] if result.data else None

    def v2_delete_warm_up_task_pool(self, pool_id: str):
        self.client.table("v2_warm_up_task_pool").delete().eq("id", pool_id).execute()

    # ---------- Focus tasks (per student; same pattern as warm-up) ----------
    def v2_get_focus_tasks(self, user_id: str):
        result = (
            self.client.table("v2_focus_tasks")
            .select("*")
            .eq("user_id", user_id)
            .order("order_index")
            .order("created_at")
            .execute()
        )
        return result.data or []

    def v2_insert_focus_task(self, data: dict):
        result = self.client.table("v2_focus_tasks").insert(data).execute()
        return result.data[0] if result.data else None

    def v2_update_focus_task(self, task_id: str, data: dict):
        payload = {}
        if "text" in data:
            payload["text"] = data["text"]
        if "order_index" in data:
            payload["order_index"] = int(data["order_index"])
        if "max_performance_score" in data:
            try:
                payload["max_performance_score"] = float(data["max_performance_score"])
            except (TypeError, ValueError):
                payload["max_performance_score"] = 1.0
        if not payload:
            result = self.client.table("v2_focus_tasks").select("*").eq("id", task_id).execute()
            return result.data[0] if result.data else None
        result = self.client.table("v2_focus_tasks").update(payload).eq("id", task_id).execute()
        return result.data[0] if result.data else None

    def v2_delete_focus_task(self, task_id: str):
        self.client.table("v2_focus_tasks").delete().eq("id", task_id).execute()

    def v2_get_focus_task_pool(self):
        result = (
            self.client.table("v2_focus_task_pool")
            .select("*")
            .order("order_index")
            .order("created_at")
            .execute()
        )
        return result.data or []

    def v2_get_focus_task_pool_by_id(self, pool_id: str):
        result = self.client.table("v2_focus_task_pool").select("*").eq("id", pool_id).execute()
        return result.data[0] if result.data else None

    def v2_insert_focus_task_pool(self, data: dict):
        data = dict(data)
        data.setdefault("order_index", 0)
        data.setdefault("max_performance_score", 1.0)
        result = self.client.table("v2_focus_task_pool").insert(data).execute()
        return result.data[0] if result.data else None

    def v2_update_focus_task_pool(self, pool_id: str, data: dict):
        payload = {}
        if "text" in data:
            payload["text"] = data["text"]
        if "order_index" in data:
            payload["order_index"] = int(data["order_index"])
        if "max_performance_score" in data:
            try:
                payload["max_performance_score"] = float(data["max_performance_score"])
            except (TypeError, ValueError):
                payload["max_performance_score"] = 1.0
        if not payload:
            return self.v2_get_focus_task_pool_by_id(pool_id)
        result = self.client.table("v2_focus_task_pool").update(payload).eq("id", pool_id).execute()
        return result.data[0] if result.data else None

    def v2_delete_focus_task_pool(self, pool_id: str):
        self.client.table("v2_focus_task_pool").delete().eq("id", pool_id).execute()

    def v2_sync_student_focus_tasks_from_pool(self, user_id: str, pool_task_ids: list):
        """Replace student's focus tasks with copies from the pool. pool_task_ids = list of v2_focus_task_pool ids in display order."""
        self.client.table("v2_focus_tasks").delete().eq("user_id", user_id).execute()
        if not pool_task_ids:
            return []
        inserted = []
        for idx, pool_id in enumerate(pool_task_ids):
            row = self.v2_get_focus_task_pool_by_id(pool_id)
            if not row:
                continue
            data = {
                "user_id": user_id,
                "pool_task_id": pool_id,
                "text": row["text"],
                "order_index": idx,
                "max_performance_score": float(row.get("max_performance_score", 1.0)),
            }
            new_row = self.v2_insert_focus_task(data)
            if new_row:
                inserted.append(new_row)
        return inserted

    def v2_sync_student_warm_up_tasks_from_pool(self, user_id: str, pool_task_ids: list):
        """Replace student's warm-up tasks with copies from the pool. pool_task_ids = list of v2_warm_up_task_pool ids in display order."""
        # #region agent log
        try:
            import json
            import os
            import time
            _log_path = os.path.join(os.path.dirname(__file__), "..", ".cursor", "debug.log")
            _log_path = os.path.abspath(_log_path)
            with open(_log_path, "a") as _f:
                _f.write(json.dumps({"location": "db.py:v2_sync_student_warm_up_tasks_from_pool", "message": "sync entry before delete", "data": {"user_id": user_id, "pool_task_ids": pool_task_ids}, "timestamp": int(time.time() * 1000), "hypothesisId": "sync_entry"}) + "\n")
        except Exception:
            pass
        # #endregion
        self.client.table("v2_warm_up_tasks").delete().eq("user_id", user_id).execute()
        if not pool_task_ids:
            return []
        inserted = []
        for idx, pool_id in enumerate(pool_task_ids):
            row = self.v2_get_warm_up_task_pool_by_id(pool_id)
            if not row:
                continue
            # order_index must be int; max_performance_score must be numeric (DB: DECIMAL(3,2); if INTEGER, run fix_v2_warm_up_tasks_max_performance_score_type.sql)
            raw_score = row.get("max_performance_score", 1.0)
            try:
                score = round(float(raw_score), 2)
            except (TypeError, ValueError):
                score = 1.0
            data = {
                "user_id": user_id,
                "pool_task_id": pool_id,
                "text": row["text"],
                "order_index": int(idx),
                "max_performance_score": score,
            }
            new_row = self.v2_insert_warm_up_task(data)
            if new_row:
                inserted.append(new_row)
        return inserted

    def v2_get_last_homework_performance_score(self, user_id: str):
        """Last completed homework session's performance_score_end (0-1), or None if no completed session."""
        result = (
            self.client.table("v2_sessions")
            .select("performance_score_end")
            .eq("user_id", user_id)
            .eq("status", "completed")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        score = result.data[0].get("performance_score_end")
        if score is None:
            return None
        return float(score)

    def v2_get_performance_history(self, user_id: str, limit: int = 5) -> List[dict]:
        """Last N completed homework sessions: session_id, created_at, performance_score_end (0-1). Oldest first for chart S1..SN."""
        result = (
            self.client.table("v2_sessions")
            .select("id, created_at, performance_score_end")
            .eq("user_id", user_id)
            .eq("status", "completed")
            .not_.is_("performance_score_end", "null")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        if not result.data:
            return []
        rows = list(reversed(result.data))
        return [
            {
                "session_id": str(r["id"]) if r.get("id") else None,
                "created_at": r.get("created_at"),
                "performance_score_end": float(r.get("performance_score_end") or 0),
            }
            for r in rows
        ]

    def v2_get_assigned_warm_up_task(self, user_id: str):
        """
        Strict taskmaster: no auto-creation of warm-up tasks.
        If user has 0 warm-up tasks => return None (caller returns 422 NO_WARMUP_CONFIGURED).
        Deterministic selection: first by order_index, then created_at.
        """
        result = (
            self.client.table("v2_warm_up_tasks")
            .select("*")
            .eq("user_id", user_id)
            .order("order_index")
            .order("created_at")
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_get_active_homework_session(self, user_id: str):
        """Active homework flow session (status in warm_up, task_block, final_task_ready, post_questions, completing_from_recording_1)."""
        statuses = ("warm_up", "task_block", "final_task_ready", "post_questions", "completing_from_recording_1")
        result = (
            self.client.table("v2_sessions")
            .select("*")
            .eq("user_id", user_id)
            .in_("status", statuses)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_create_homework_session(self, user_id: str):
        """Create new homework flow session (status=warm_up)."""
        result = self.client.table("v2_sessions").insert({"user_id": user_id, "status": "warm_up"}).execute()
        return result.data[0] if result.data else None

    # Context fields: context_short (session summary), context_long (report text), coach_notes (speaker_profile). See docs/CONTEXT-FIELDS.md.

    def v2_append_context_long_entry(self, session_id: str, user_id: str, text: str):
        """Append one report entry to context_long_entries with current UTC timestamp. Returns updated session."""
        from datetime import datetime, timezone
        entry = {"at": datetime.now(timezone.utc).isoformat(), "text": text}
        # Fetch current entries, append, update
        row = self.v2_get_session(session_id, user_id)
        if not row:
            return None
        entries = list(row.get("context_long_entries") or [])
        entries.append(entry)
        self.client.table("v2_sessions").update({
            "context_long_entries": entries,
            "context_long": text,  # keep latest in TEXT for simple reads
        }).eq("id", session_id).eq("user_id", user_id).execute()
        return self.v2_get_session(session_id, user_id)

    def v2_set_context_long_entries(self, session_id: str, user_id: str, entries: list):
        """Admin: set full context_long_entries list. Each entry: { "at": "ISO8601", "text": "..." }. context_long = last entry text or "". Returns updated session or None."""
        row = self.v2_get_session(session_id, user_id)
        if not row:
            return None
        normalized = []
        for e in entries or []:
            if isinstance(e, dict) and e.get("text") is not None:
                normalized.append({"at": e.get("at") or "", "text": str(e["text"])})
        latest = normalized[-1]["text"] if normalized else ""
        self.client.table("v2_sessions").update({
            "context_long_entries": normalized,
            "context_long": latest,
        }).eq("id", session_id).eq("user_id", user_id).execute()
        return self.v2_get_session(session_id, user_id)

    # ---------- Metric questions (2 questions for AI task block; admin Metrics section) ----------
    def v2_get_metric_questions(self):
        """All rows from v2_metric_questions ordered by position (the 3 task-block questions)."""
        result = (
            self.client.table("v2_metric_questions")
            .select("*")
            .order("position")
            .execute()
        )
        return result.data or []

    def v2_get_metric_questions_for_flow(self):
        """First 3 from v2_metric_questions by position (metric_question_1, 2, 3 for task block)."""
        rows = self.v2_get_metric_questions()
        return rows[:3]

    def v2_insert_metric_question(self, data: dict):
        result = self.client.table("v2_metric_questions").insert(data).execute()
        return result.data[0] if result.data else None

    def v2_update_metric_question(self, question_id: str, data: dict):
        result = self.client.table("v2_metric_questions").update(data).eq("id", question_id).execute()
        return result.data[0] if result.data else None

    def v2_update_metric_question_by_position(self, position: int, text: str):
        """Update the single row with this position (1, 2, or 3)."""
        result = self.client.table("v2_metric_questions").update({"text": (text or "").strip()}).eq("position", position).execute()
        return result.data[0] if result.data else None

    def v2_delete_metric_question(self, question_id: str):
        self.client.table("v2_metric_questions").delete().eq("id", question_id).execute()

    def v2_upsert_metric_definition(self, code: str, left_label: str, right_label: str):
        now = datetime.now(timezone.utc).isoformat()
        result = (
            self.client.table("v2_metric_definitions")
            .upsert({"code": code, "left_label": left_label, "right_label": right_label, "updated_at": now}, on_conflict="code")
            .execute()
        )
        return result.data[0] if result.data else None

    _V2_OVERRIDES_COLUMNS = {
        "intended_emotion_prompt", "keywords_prompt", "emotion_check_question_text",
        "assigned_post_question_ids", "assigned_next_exercise_id", "last_assigned_exercise_id", "assigned_next_task_ids",
        "show_exercise_step", "assigned_warm_up_task_id",
        "pitch_variance_ideal", "pending_tutor_video_url", "pending_tutor_video_description",
        "skip_metric_questions", "skip_post_questions",
    }

    def v2_get_user_metric_questions(self, user_id: str):
        """Get the 3 metric questions from v2_metric_questions and pitch_variance_ideal from overrides."""
        rows = self.v2_get_metric_questions()
        by_pos = {r.get("position"): (r.get("text") or "").strip() for r in rows}
        override_result = self.client.table("v2_student_overrides").select("pitch_variance_ideal").eq("user_id", user_id).execute()
        override_row = override_result.data[0] if override_result.data else None
        pitch = override_row.get("pitch_variance_ideal") if override_row else None
        return {
            "metric_question_1": by_pos.get(1, ""),
            "metric_question_2": by_pos.get(2, ""),
            "metric_question_3": by_pos.get(3, ""),
            "pitch_variance_ideal": pitch,
        }

    def v2_update_user_metric_questions(self, user_id: str, data: dict):
        """Update the 3 metric questions in v2_metric_questions (by position) and optionally pitch_variance_ideal in overrides."""
        for pos, key in [(1, "metric_question_1"), (2, "metric_question_2"), (3, "metric_question_3")]:
            if key in data:
                self.v2_update_metric_question_by_position(pos, data.get(key))
        if "pitch_variance_ideal" in data:
            try:
                val = float(data["pitch_variance_ideal"]) if data["pitch_variance_ideal"] is not None else None
            except (TypeError, ValueError):
                val = None
            payload = {"user_id": user_id, "updated_at": datetime.now(timezone.utc).isoformat(), "pitch_variance_ideal": val}
            self.client.table("v2_student_overrides").upsert(payload, on_conflict="user_id").execute()
        return self.v2_get_user_metric_questions(user_id)

    def v2_upsert_student_overrides(self, user_id: str, data: dict):
        """Merge request data with existing overrides so partial PUTs do not clear other fields (e.g. skip_metric_questions, skip_post_questions)."""
        existing = self.v2_get_student_overrides(user_id) or {}
        merged = {}
        for col in self._V2_OVERRIDES_COLUMNS:
            if col in data:
                merged[col] = data[col]
            elif col in existing:
                merged[col] = existing[col]
            else:
                merged[col] = None
        for key in ("skip_metric_questions", "skip_post_questions"):
            if merged.get(key) is None:
                merged[key] = False
        # Empty string for UUID columns: treat as null so clearing "assigned exercise" persists
        if merged.get("assigned_next_exercise_id") == "":
            merged["assigned_next_exercise_id"] = None
        # When admin assigns an exercise, remember it so step 0 can show it until a new one is assigned
        if merged.get("assigned_next_exercise_id"):
            merged["last_assigned_exercise_id"] = merged["assigned_next_exercise_id"]
        payload = {k: v for k, v in merged.items() if v is not None or k in ("skip_metric_questions", "skip_post_questions")}
        payload["user_id"] = user_id
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        # #region agent log
        try:
            open("/Users/arturwillonski/Documents/backend-cursor/.cursor/debug.log", "a").write(json.dumps({"message": "DB upsert overrides", "data": {"data_keys": list(data.keys()), "existing_keys": list(existing.keys()), "merged_skip_metric": merged.get("skip_metric_questions"), "merged_skip_post": merged.get("skip_post_questions"), "payload_has_skip_metric": "skip_metric_questions" in payload, "payload_has_skip_post": "skip_post_questions" in payload, "payload_skip_metric": payload.get("skip_metric_questions"), "payload_skip_post": payload.get("skip_post_questions")}, "hypothesisId": "H2,H5", "location": "db.py:v2_upsert_student_overrides", "timestamp": int(time.time() * 1000)}) + "\n")
        except Exception:
            pass
        # #endregion
        result = self.client.table("v2_student_overrides").upsert(payload, on_conflict="user_id").execute()
        # #region agent log
        try:
            out = result.data[0] if result.data else None
            open("/Users/arturwillonski/Documents/backend-cursor/.cursor/debug.log", "a").write(json.dumps({"message": "DB upsert result", "data": {"result_keys": list(out.keys()) if out else None, "result_skip_metric": out.get("skip_metric_questions") if out else None, "result_skip_post": out.get("skip_post_questions") if out else None}, "hypothesisId": "H2,H4", "location": "db.py:v2_upsert_student_overrides after execute", "timestamp": int(time.time() * 1000)}) + "\n")
        except Exception:
            pass
        # #endregion
        return result.data[0] if result.data else None

    def v2_set_pending_tutor_video(self, user_id: str, video_url: str = None, video_description: str = None):
        """Store coach message and/or video URL for the next session. Call when admin sends assignment. Message is returned as tutor_video_description in GET session/status (homework flow is text-only; no video)."""
        payload = {}
        if video_url is not None:
            payload["pending_tutor_video_url"] = (video_url or "").strip() or None
        if video_description is not None:
            payload["pending_tutor_video_description"] = (video_description or "").strip() or None
        if payload:
            self.v2_upsert_student_overrides(user_id, payload)
        return True

    def v2_get_and_clear_pending_tutor_video(self, user_id: str):
        """Return (url, description) for the pending tutor video and clear both. Used on session/start to attach to the new session."""
        row = self.client.table("v2_student_overrides").select("pending_tutor_video_url, pending_tutor_video_description").eq("user_id", user_id).execute()
        url = None
        description = None
        if row.data:
            r = row.data[0]
            if r.get("pending_tutor_video_url"):
                url = (r["pending_tutor_video_url"] or "").strip() or None
            if r.get("pending_tutor_video_description"):
                description = (r["pending_tutor_video_description"] or "").strip() or None
        if url is not None or description is not None:
            self.client.table("v2_student_overrides").update({
                "pending_tutor_video_url": None,
                "pending_tutor_video_description": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("user_id", user_id).execute()
        return (url, description)

    def v2_create_report(self, session_v2_id: str, recording_id: str, report_text: str):
        result = self.client.table("v2_reports").insert({
            "session_v2_id": session_v2_id,
            "recording_id": recording_id,
            "report_text": report_text,
        }).execute()
        return result.data[0] if result.data else None

    def v2_list_users_with_sessions(self, limit: int = 50, offset: int = 0):
        """List user_ids that have at least one v2_session (for admin students list)."""
        fetch = max((offset + limit) * 2, 100)
        result = (
            self.client.table("v2_sessions")
            .select("user_id")
            .order("created_at", desc=True)
            .limit(fetch)
            .execute()
        )
        seen = set()
        out = []
        for row in (result.data or []):
            uid = row.get("user_id")
            if uid and uid not in seen:
                seen.add(uid)
                out.append(uid)
        return out[offset : offset + limit]

    def v2_list_auth_users(self, limit: int = 50, offset: int = 0):
        """List all auth users (id, email) via Supabase Auth Admin API so new students appear in admin list.
        Returns list of dicts with user_id and email (email may be None if not present)."""
        try:
            import httpx
            base = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users"
            # GoTrue list users: per_page and page (1-based)
            page = (offset // limit) + 1
            resp = httpx.get(
                base,
                params={"per_page": min(limit, 1000), "page": page},
                headers={
                    "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
                    "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
                },
                timeout=10,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            users = data.get("users") or (data.get("data") or {}).get("users") or []
            out = []
            for u in users:
                uid = u.get("id")
                if not uid:
                    continue
                out.append({
                    "user_id": uid,
                    "email": u.get("email") or (u.get("user_metadata") or {}).get("email"),
                })
            return out
        except Exception:
            return None

    def v2_get_student_list_stats(self, user_id: str):
        """Optional stats for admin students list: sessions_count, last_session_at (ISO), avg_performance (0-100)."""
        sessions = (
            self.client.table("v2_sessions")
            .select("id, created_at, recording_1_id, recording_2_id")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(1000)
            .execute()
        )
        rows = sessions.data or []
        if not rows:
            return None
        sessions_count = len(rows)
        last_session_at = max((r.get("created_at") for r in rows if r.get("created_at")), default=None)
        session_ids = [r["id"] for r in rows if r.get("id")]
        avg_performance = None
        if session_ids:
            recs = (
                self.client.table("recordings")
                .select("performance_score_v2")
                .in_("session_v2_id", session_ids)
                .not_.is_("performance_score_v2", "null")
                .execute()
            )
            scores = [r.get("performance_score_v2") for r in (recs.data or []) if r.get("performance_score_v2") is not None]
            if scores:
                avg_performance = round((sum(scores) / len(scores)) * 100)
        return {
            "sessions_count": sessions_count,
            "last_session_at": last_session_at,
            "avg_performance": avg_performance,
        }

    def v2_get_sessions_with_previews(self, user_id: str, limit: int = 50):
        """Get v2 sessions for a user with full report text and recording previews for admin session history."""
        result = (
            self.client.table("v2_sessions")
            .select("id, created_at, status, recording_1_id, recording_2_id, report_id, coach_grade")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        sessions = result.data or []
        # Fetch context_long (and context_long_entries as fallback) so report preview works for completed sessions
        session_ids = [s["id"] for s in sessions]
        context_long_by_id = {}
        if session_ids:
            try:
                ctx = self.client.table("v2_sessions").select("id, context_long, context_long_entries").in_("id", session_ids).execute()
                for row in (ctx.data or []):
                    text = (row.get("context_long") or "").strip()
                    if not text and row.get("context_long_entries"):
                        entries = row["context_long_entries"]
                        if isinstance(entries, list) and entries:
                            last = entries[-1]
                            if isinstance(last, dict) and last.get("text"):
                                text = (last["text"] or "").strip()
                    if text:
                        context_long_by_id[row["id"]] = text
            except Exception:
                pass
        out = []
        for s in sessions:
            rec = {k: v for k, v in s.items() if k in ("id", "created_at", "status", "recording_1_id", "recording_2_id", "report_id", "coach_grade")}
            rec["recording_id"] = s.get("recording_2_id") or s.get("recording_1_id")  # for backward compat in API response
            rec["recording_preview"] = None
            rec["report_preview"] = None
            recording_id = s.get("recording_2_id") or s.get("recording_1_id")
            if recording_id:
                r = self.client.table("recordings").select("performance_score_v2, transcription_text").eq("id", recording_id).execute()
                if r.data:
                    row = r.data[0]
                    rec["recording_preview"] = {
                        "performance_score_v2": row.get("performance_score_v2"),
                        "transcription_preview": (row.get("transcription_text") or "")[:300],
                    }
            report_text = None
            if s.get("report_id"):
                r = self.client.table("v2_reports").select("report_text").eq("id", s["report_id"]).execute()
                if r.data:
                    report_text = r.data[0].get("report_text") or ""
            if report_text is None:
                report_text = context_long_by_id.get(s["id"])
            if report_text:
                # Full report text so admin always sees the full report (no truncation)
                rec["report_preview"] = {"report_text_preview": (report_text or "").strip()}
            out.append(rec)
        return out

    def v2_get_last_report_for_user(self, user_id: str):
        """Get full text of the most recent completed report for admin 'Last Report' section. Only considers sessions with status='completed'. Returns { report_text, report_preview } or None."""
        result = (
            self.client.table("v2_sessions")
            .select("id, report_id")
            .eq("user_id", user_id)
            .eq("status", "completed")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        s = result.data[0]
        report_text = None
        if s.get("report_id"):
            r = self.client.table("v2_reports").select("report_text").eq("id", s["report_id"]).execute()
            if r.data:
                report_text = r.data[0].get("report_text") or ""
        if report_text is None and s.get("id"):
            try:
                ctx = self.client.table("v2_sessions").select("context_long, context_long_entries").eq("id", s["id"]).execute()
                if ctx.data:
                    row = ctx.data[0]
                    report_text = (row.get("context_long") or "").strip()
                    if not report_text and row.get("context_long_entries"):
                        entries = row["context_long_entries"]
                        if isinstance(entries, list) and entries:
                            last = entries[-1]
                            if isinstance(last, dict) and last.get("text"):
                                report_text = (last["text"] or "").strip()
            except Exception:
                pass
        if not report_text:
            return None
        return {"report_text": report_text, "report_preview": (report_text or "")[:500]}

    def v2_get_speaker_profile(self, user_id: str):
        """Get speaker profile for admin panel (main_goal, motivation, coach_notes, etc.)."""
        result = self.client.table("v2_speaker_profiles").select("*").eq("user_id", user_id).execute()
        return result.data[0] if result.data else None

    def v2_upsert_speaker_profile(self, user_id: str, data: dict):
        """Create or update speaker profile. Keys: main_goal, motivation, strong_points, weak_points, charismatic_traits, hobbies_interests, personality_type, coach_notes."""
        allowed = {"main_goal", "motivation", "strong_points", "weak_points", "charismatic_traits", "hobbies_interests", "personality_type", "coach_notes"}
        payload = {k: v for k, v in data.items() if k in allowed}
        payload["user_id"] = user_id
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        result = self.client.table("v2_speaker_profiles").upsert(payload, on_conflict="user_id").execute()
        return result.data[0] if result.data else None

    def get_user_email_from_auth(self, user_id: str) -> str | None:
        """Fetch user email from Supabase Auth (admin API). Returns None if not found or on error."""
        try:
            import httpx
            url = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{user_id}"
            resp = httpx.get(
                url,
                headers={
                    "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
                    "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
                },
                timeout=5,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            return data.get("email") or (data.get("user", {}).get("email"))
        except Exception:
            return None

# Singleton instance
db = DatabaseService()
