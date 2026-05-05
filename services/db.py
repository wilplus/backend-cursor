from supabase import create_client, Client
from config import Config
from typing import Any, Dict, List, Optional, Tuple, Callable
from datetime import datetime, timedelta, timezone
import json
import logging
import os
import re
import time

import sentry_sdk

config = Config()
logger = logging.getLogger(__name__)


class DatabaseService:
    def __init__(self):
        self.client: Client = self._build_supabase_client()
        # Cache missing optional columns discovered at runtime on older schemas.
        self._v2_sessions_missing_columns: set[str] = set()
        self._student_profile_table = "student_profile"
        self._legacy_student_profile_table = "user_sniper_profile"

    def _build_supabase_client(self) -> Client:
        """Create Supabase client and prefer HTTP/1.1 transport to avoid flaky HTTP/2 disconnects."""
        try:
            import httpx
            ClientOptions = None
            try:
                from supabase.lib.client_options import ClientOptions as _ClientOptions
                ClientOptions = _ClientOptions
            except Exception:
                try:
                    from supabase.client_options import ClientOptions as _ClientOptions
                    ClientOptions = _ClientOptions
                except Exception:
                    try:
                        from supabase import ClientOptions as _ClientOptions
                        ClientOptions = _ClientOptions
                    except Exception:
                        ClientOptions = None

            if ClientOptions is not None:
                http_client = httpx.Client(http2=False, timeout=httpx.Timeout(20.0))
                options = ClientOptions(http_client=http_client)
                try:
                    return create_client(
                        config.SUPABASE_URL,
                        config.SUPABASE_SERVICE_ROLE_KEY,
                        options=options,
                    )
                except TypeError:
                    # Older supabase-py may expect positional options arg.
                    return create_client(
                        config.SUPABASE_URL,
                        config.SUPABASE_SERVICE_ROLE_KEY,
                        options,
                    )
        except Exception as e:
            logger.warning("Supabase HTTP/1.1 transport setup failed; falling back to default client: %s", e)

        return create_client(
            config.SUPABASE_URL,
            config.SUPABASE_SERVICE_ROLE_KEY,
        )

    def _is_transient_postgrest_disconnect(self, err: Exception) -> bool:
        msg = str(err).lower()
        if "remoteprotocolerror" in msg and "server disconnected" in msg:
            return True
        if "server disconnected" in msg:
            return True
        if "connection reset by peer" in msg:
            return True
        if "http2" in msg and "disconnected" in msg:
            return True
        return False

    def _execute_with_retry(self, query_factory: Callable[[], Any], *, label: str, max_attempts: int = 3):
        """Execute a PostgREST query with reconnect + backoff on transient transport drops."""
        attempt = 1
        while True:
            try:
                query = query_factory()
                return query.execute()
            except Exception as e:
                if attempt >= max_attempts or not self._is_transient_postgrest_disconnect(e):
                    raise
                sleep_s = 0.2 * (2 ** (attempt - 1))
                logger.warning(
                    "%s transient DB disconnect (attempt %s/%s): %s; retrying in %.1fs",
                    label,
                    attempt,
                    max_attempts,
                    e,
                    sleep_s,
                )
                # Recreate client to avoid reusing a broken pooled connection/session.
                try:
                    self.client = self._build_supabase_client()
                except Exception:
                    pass
                time.sleep(sleep_s)
                attempt += 1

    def _is_relation_missing_error(self, err: Exception) -> bool:
        msg = str(err).lower()
        return ("42p01" in msg) or ("does not exist" in msg) or ("undefined_table" in msg)

    def _select_student_profile_row(self, user_id: str) -> Optional[dict]:
        """Read profile from new table first; fallback to legacy table during migration."""
        try:
            res = (
                self.client.table(self._student_profile_table)
                .select("*")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if res.data:
                return res.data[0]
        except Exception as e:
            if not self._is_relation_missing_error(e):
                raise
        try:
            res = (
                self.client.table(self._legacy_student_profile_table)
                .select("*")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            return res.data[0] if res.data else None
        except Exception:
            return None
    
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
            err_low = str(e).lower()
            # PostgREST PGRST204: column absent from schema cache / table (e.g. task_id before migration).
            if (
                "task_id" in data
                and (
                    "pgrst204" in err_low
                    or "could not find the 'task_id' column" in err_low
                    or ("task_id" in err_low and "schema" in err_low)
                )
            ):
                retry_payload = {k: v for k, v in data.items() if k != "task_id"}
                try:
                    result = self.client.table("recordings")\
                        .update(retry_payload)\
                        .eq("id", recording_id)\
                        .execute()
                    logger.warning(
                        "update_recording: recordings.task_id not in schema; updated without task_id recording_id=%s",
                        recording_id,
                    )
                    return result.data[0] if result.data else None
                except Exception as e2:
                    sentry_sdk.capture_exception(e2)
                    raise e2

            sentry_sdk.capture_exception(e)
            error_msg = str(e)
            if "column" in error_msg.lower() and "does not exist" in error_msg.lower():
                raise Exception(f"Database schema error: {error_msg}. Please ensure all required columns exist in the recordings table.")
            raise
    
    def get_recording(self, recording_id: str, user_id: str = None):
        """Get a recording by ID, optionally verifying ownership"""
        def _query():
            query = self.client.table("recordings").select("*").eq("id", recording_id)
            if user_id:
                query = query.eq("user_id", user_id)
            return query

        result = self._execute_with_retry(_query, label="get_recording")
        
        return result.data[0] if result.data else None

    def get_recording_for_homework_session(self, recording_id, user_id: str, session: dict):
        """Load recording for report UI: prefer owner match, else id-only if linked from session."""
        if not recording_id or not session:
            return None
        rec = self.get_recording(recording_id, user_id)
        if rec:
            return rec
        rid = str(recording_id)
        allowed = {str(x) for x in (session.get("recording_1_id"),) if x}
        if rid not in allowed:
            return None
        return self.get_recording(recording_id, None)

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
        except Exception:
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
            
            logger.debug("create_signed_url bucket=%s path=%s response_type=%s", bucket, path, type(response).__name__)

            signed_url = None

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
            
            if not signed_url:
                logger.warning("Could not extract signed URL for %s/%s (response_type=%s)", bucket, path, type(response).__name__)
                raise Exception(f"Could not extract signed URL for {bucket}/{path}")

            if not signed_url.startswith("http"):
                raise Exception(f"Signed URL for {bucket}/{path} is not a full URL")

            logger.debug("Signed URL created for %s/%s (expires_in=%s)", bucket, path, expires_in)
            return signed_url
        except Exception as e:
            logger.error("Error creating signed URL for %s/%s: %s", bucket, path, type(e).__name__)
            sentry_sdk.capture_exception(e)
            raise Exception(f"Failed to create signed URL for {bucket}/{path}")

    def _absolute_signed_upload_url(self, raw: str | None) -> str | None:
        """Storage may return a host-relative path; browsers must PUT the full Supabase URL or the app origin gets 404."""
        if not raw or not isinstance(raw, str):
            return None
        s = raw.strip()
        if not s:
            return None
        if s.startswith("http://") or s.startswith("https://"):
            return s
        base = (config.SUPABASE_URL or "").rstrip("/")
        if not base:
            return None
        storage_root = f"{base}/storage/v1"
        if s.startswith("/storage/v1/"):
            return f"{base}{s}"
        if s.startswith("storage/v1/"):
            return f"{base}/{s}"
        if s.startswith("/object/"):
            return f"{storage_root}{s}"
        if s.startswith("object/"):
            return f"{storage_root}/{s}"
        return f"{storage_root}/{s.lstrip('/')}"

    def create_signed_upload_url(self, bucket: str, path: str) -> Optional[Dict[str, str]]:
        """Mint a signed upload URL for browser uploads.

        Returns ``{"signed_url": "<https...>", "token": "<jwt>"}`` or None.
        Supabase Storage expects the upload as **multipart** PUT (same as
        ``@supabase/storage-js`` ``uploadToSignedUrl``). A raw binary PUT
        typically returns **404** (route not matched for that content type).
        """
        from urllib.parse import parse_qs, urlparse

        path_clean = path.lstrip("/")
        sign_segment = f"{bucket}/{path_clean}"

        def _finalize(raw_url: Optional[str], token: Optional[str] = None) -> Optional[Dict[str, str]]:
            signed = self._absolute_signed_upload_url(raw_url) if raw_url else None
            if not signed:
                return None
            if not token:
                vals = parse_qs(urlparse(signed).query).get("token") or []
                token = vals[0] if vals else None
            out: Dict[str, str] = {"signed_url": signed}
            if token:
                out["token"] = token
            return out

        def _from_sdk_result(result: Any) -> Optional[Dict[str, str]]:
            if result is None:
                return None
            if isinstance(result, dict):
                u = (
                    result.get("signedUrl")
                    or result.get("signed_url")
                    or result.get("signedURL")
                    or result.get("url")
                )
                tok = result.get("token")
                tok_s = tok if isinstance(tok, str) else None
                if isinstance(u, str):
                    return _finalize(u, tok_s)
                return None
            for attr in ("signed_url", "signedUrl", "signedURL", "url"):
                u = getattr(result, attr, None)
                if isinstance(u, str):
                    return _finalize(u)
            return None

        try:
            bucket_api = self.client.storage.from_(bucket)
            create_upload = getattr(bucket_api, "create_signed_upload_url", None)
            if callable(create_upload):
                result = create_upload(path_clean)
                normalized = _from_sdk_result(result)
                if normalized:
                    return normalized
        except Exception as e:
            logger.debug("create_signed_upload_url SDK path failed: %s", e)

        try:
            import httpx

            base = (config.SUPABASE_URL or "").rstrip("/")
            key = config.SUPABASE_SERVICE_ROLE_KEY or ""
            if not base or not key:
                return None
            # Match storage-js/storage-py: POST .../object/upload/sign/{bucketId}/{objectPath} (no JSON body).
            resp = httpx.post(
                f"{base}/storage/v1/object/upload/sign/{sign_segment}",
                headers={"Authorization": f"Bearer {key}", "apikey": key},
                timeout=10.0,
            )
            if resp.status_code != 200:
                logger.warning(
                    "create_signed_upload_url POST sign failed status=%s body=%s",
                    resp.status_code,
                    (resp.text or "")[:200],
                )
                return None
            data = resp.json()
            if not isinstance(data, dict):
                return None
            rel = data.get("url") or data.get("signedURL") or data.get("signedUrl") or data.get("signed_url")
            tok = data.get("token")
            tok_s = tok if isinstance(tok, str) else None
            return _finalize(rel if isinstance(rel, str) else None, tok_s)
        except Exception as e:
            logger.warning("create_signed_upload_url httpx path failed: %s", e)
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
            
            logger.debug("upload_audio bucket=%s path=%s size=%d content_type=%s", bucket, path, len(file_data), content_type)

            file_options = {"content-type": str(content_type)}

            result = self.client.storage.from_(bucket).upload(
                path=path,
                file=file_data,
                file_options=file_options
            )
            return result
        except Exception as e:
            logger.error("Upload failed for %s/%s: %s", bucket, path, type(e).__name__)
            sentry_sdk.capture_exception(e)
            raise Exception(f"Failed to upload to {bucket}/{path}: {e}") from e

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
            logger.error("Download failed for %s/%s: %s", bucket, path, type(e).__name__)
            sentry_sdk.capture_exception(e)
            raise Exception(f"Failed to download from {bucket}/{path}: {e}") from e

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
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
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

    def v2_get_metric_definitions(self):
        """All 5 metric definitions (code, left_label, right_label)."""
        result = self.client.table("v2_metric_definitions").select("*").execute()
        return result.data or []

    def v2_get_student_overrides(self, user_id: str):
        """Overrides for user (tasks, prompts, metric/skip flags, pending tutor video)."""
        result = self.client.table("v2_student_overrides").select("*").eq("user_id", user_id).execute()
        rows = result.data or []
        for row in rows:
            if str(row.get("user_id") or "") == str(user_id):
                return row
        return None

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
        """Delete v2 session (owner only). Recordings.session_v2_id set to NULL; v2_reports CASCADE deleted. Returns True when delete executes without error (Supabase delete may return empty body).

        NOTE: The schema has a mutual FK cycle between v2_sessions and v2_reports:
          v2_sessions.report_id → v2_reports(id) ON DELETE SET NULL
          v2_reports.session_v2_id → v2_sessions(id) ON DELETE CASCADE
        PostgreSQL can raise a constraint-cycle error when both fire in the same transaction.
        We break the cycle first by nulling out the FK columns on v2_sessions before deleting.
        Same precaution for recording_1_id (bidirectional with recordings table).
        """
        # Step 1: Break circular FK references to avoid PostgreSQL constraint-cycle errors.
        try:
            self.client.table("v2_sessions").update({
                "recording_1_id": None,
                "report_id": None,
            }).eq("id", session_id).eq("user_id", user_id).execute()
        except Exception:
            pass  # Best-effort; proceed to delete regardless.

        # Step 2: Delete the session row (v2_reports CASCADE, recordings.session_v2_id SET NULL).
        self.client.table("v2_sessions").delete().eq("id", session_id).eq("user_id", user_id).execute()
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

    def v2_delete_stress_snippets_for_recording(self, recording_id: str) -> int:
        """Delete previously generated snippet candidates for one recording."""
        result = (
            self.client.table("stress_snippets")
            .delete()
            .eq("recording_id", recording_id)
            .execute()
        )
        return len(result.data or [])

    def v2_insert_stress_snippets(self, snippets: list[dict]) -> list[dict]:
        """Bulk insert snippet candidates."""
        if not snippets:
            return []
        result = (
            self.client.table("stress_snippets")
            .insert(snippets)
            .execute()
        )
        return result.data or []

    def v2_get_stress_snippet(self, snippet_id: str) -> Optional[dict]:
        """Return one stress snippet row by id."""
        result = (
            self.client.table("stress_snippets")
            .select("*")
            .eq("id", snippet_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_set_stress_snippet_label(
        self,
        snippet_id: str,
        reviewer_id: str,
        label: str,
        notes: Optional[str],
        reviewer_email: Optional[str] = None,
    ) -> Optional[dict]:
        """Set coach binary label (stress/no_stress) for one snippet."""
        payload = {
            "coach_label": label,
            "coach_label_notes": notes,
            "labeled_by": reviewer_id,
            "labeled_by_admin_id": reviewer_id,
            "labeled_by_admin_email": (reviewer_email or "").strip() or None,
            "labeled_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        result = (
            self.client.table("stress_snippets")
            .update(payload)
            .eq("id", snippet_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_clear_stress_snippet_label(self, snippet_id: str) -> Optional[dict]:
        """Remove coach label so the snippet returns to the unlabeled queue."""
        payload = {
            "coach_label": None,
            "coach_label_notes": None,
            "labeled_by": None,
            "labeled_by_admin_id": None,
            "labeled_by_admin_email": None,
            "labeled_at": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        result = (
            self.client.table("stress_snippets")
            .update(payload)
            .eq("id", snippet_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_merge_stress_snippet_features(self, snippet_id: str, patch: dict) -> Optional[dict]:
        """Shallow-merge ``patch`` into ``features`` JSONB."""
        row = self.v2_get_stress_snippet(snippet_id)
        if not row:
            return None
        features = dict(row.get("features") or {})
        for k, v in (patch or {}).items():
            if v is None:
                features.pop(k, None)
            else:
                features[k] = v
        result = (
            self.client.table("stress_snippets")
            .update({
                "features": features,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", snippet_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_list_stress_snippets(
        self,
        *,
        source_type: Optional[str] = None,
        recording_id: Optional[str] = None,
        label_state: str = "all",
        limit: int = 50,
        offset: int = 0,
        sort_created_desc: bool = True,
        exclude_queue_skipped: bool = False,
    ) -> list[dict]:
        """List generated snippets with source-side recording metadata."""
        query = self.client.table("stress_snippets").select("*")
        query = query.order("created_at", desc=sort_created_desc)
        query = query.range(offset, max(offset + limit - 1, offset))
        if source_type:
            query = query.eq("source_type", source_type)
        if recording_id:
            query = query.eq("recording_id", recording_id)
        if label_state == "unlabeled":
            query = query.is_("coach_label", "null")
        result = query.execute()
        rows = result.data or []
        if label_state == "labeled":
            rows = [r for r in rows if r.get("coach_label") is not None]
        if exclude_queue_skipped:
            rows = [
                r
                for r in rows
                if not (isinstance(r.get("features"), dict) and r.get("features", {}).get("queue_skipped") is True)
            ]
        if not rows:
            return []

        recording_ids = [r.get("recording_id") for r in rows if r.get("recording_id")]
        recordings_map: dict[str, dict] = {}
        if recording_ids:
            try:
                recs = (
                    self.client.table("recordings")
                    .select("id, recording_origin, source_metadata, user_id, session_v2_id, created_at, storage_path")
                    .in_("id", recording_ids)
                    .execute()
                )
                recordings_map = {str(r["id"]): r for r in (recs.data or []) if r.get("id")}
            except Exception:
                recordings_map = {}

        out = []
        for row in rows:
            item = dict(row)
            rid = str(item.get("recording_id")) if item.get("recording_id") else None
            item["recording"] = recordings_map.get(rid)
            out.append(item)
        return out

    # ------------------------------------------------------------------
    # Charisma snippets
    # ------------------------------------------------------------------

    def v2_delete_charisma_snippets_for_recording(self, recording_id: str) -> int:
        """Delete all charisma snippet candidates for one recording."""
        result = (
            self.client.table("charisma_snippets")
            .delete()
            .eq("recording_id", recording_id)
            .execute()
        )
        return len(result.data or [])

    def v2_insert_charisma_snippets(self, snippets: list[dict]) -> list[dict]:
        """Bulk insert charisma snippet candidates."""
        if not snippets:
            return []
        result = (
            self.client.table("charisma_snippets")
            .insert(snippets)
            .execute()
        )
        return result.data or []

    def v2_get_charisma_snippet(self, snippet_id: str) -> Optional[dict]:
        """Return one charisma snippet row by id."""
        result = (
            self.client.table("charisma_snippets")
            .select("*")
            .eq("id", snippet_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_set_charisma_snippet_label(
        self,
        snippet_id: str,
        reviewer_id: str,
        label: str,
        notes: Optional[str],
        reviewer_email: Optional[str] = None,
    ) -> Optional[dict]:
        """Set coach_label (charisma/no_charisma) for one snippet."""
        payload = {
            "coach_label": label,
            "coach_label_notes": notes,
            "labeled_by": reviewer_id,
            "labeled_by_admin_id": reviewer_id,
            "labeled_by_admin_email": (reviewer_email or "").strip() or None,
            "labeled_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        result = (
            self.client.table("charisma_snippets")
            .update(payload)
            .eq("id", snippet_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_clear_charisma_snippet_label(self, snippet_id: str) -> Optional[dict]:
        """Remove coach label so the snippet returns to the unlabeled queue."""
        payload = {
            "coach_label": None,
            "coach_label_notes": None,
            "labeled_by": None,
            "labeled_by_admin_id": None,
            "labeled_by_admin_email": None,
            "labeled_at": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        result = (
            self.client.table("charisma_snippets")
            .update(payload)
            .eq("id", snippet_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_merge_charisma_snippet_features(self, snippet_id: str, patch: dict) -> Optional[dict]:
        """Shallow-merge patch into features JSONB."""
        row = self.v2_get_charisma_snippet(snippet_id)
        if not row:
            return None
        features = dict(row.get("features") or {})
        for k, v in (patch or {}).items():
            if v is None:
                features.pop(k, None)
            else:
                features[k] = v
        result = (
            self.client.table("charisma_snippets")
            .update({
                "features": features,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", snippet_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_list_charisma_snippets(
        self,
        *,
        source_type: Optional[str] = None,
        recording_id: Optional[str] = None,
        label_state: str = "all",
        limit: int = 50,
        offset: int = 0,
        sort_created_desc: bool = True,
        exclude_queue_skipped: bool = False,
    ) -> list[dict]:
        """List charisma snippets with optional filtering and recording metadata."""
        query = self.client.table("charisma_snippets").select("*")
        query = query.order("created_at", desc=sort_created_desc)
        query = query.range(offset, max(offset + limit - 1, offset))
        if source_type:
            query = query.eq("source_type", source_type)
        if recording_id:
            query = query.eq("recording_id", recording_id)
        if label_state == "unlabeled":
            query = query.is_("coach_label", "null")
        result = query.execute()
        rows = result.data or []
        if label_state == "labeled":
            rows = [r for r in rows if r.get("coach_label") is not None]
        if exclude_queue_skipped:
            rows = [
                r
                for r in rows
                if not (isinstance(r.get("features"), dict) and r.get("features", {}).get("queue_skipped") is True)
            ]
        if not rows:
            return []
        recording_ids = [r.get("recording_id") for r in rows if r.get("recording_id")]
        recordings_map: dict[str, dict] = {}
        if recording_ids:
            try:
                recs = (
                    self.client.table("recordings")
                    .select("id, recording_origin, source_metadata, user_id, session_v2_id, created_at, storage_path")
                    .in_("id", recording_ids)
                    .execute()
                )
                recordings_map = {str(r["id"]): r for r in (recs.data or []) if r.get("id")}
            except Exception:
                recordings_map = {}
        out = []
        for row in rows:
            item = dict(row)
            rid = str(item.get("recording_id")) if item.get("recording_id") else None
            item["recording"] = recordings_map.get(rid)
            out.append(item)
        return out

    def v2_get_last_completed_session(self, user_id: str):
        """Return the most recent completed session for the user (for tutor_feedback_deadline when no active session). Includes tutor_feedback_sent_at so deadline is omitted once feedback is sent."""
        wide = "id, report_id, completed_at, created_at, tutor_feedback_sent_at, student_completion_email_sent_at, score_for_display"
        base = "id, report_id, completed_at, created_at, tutor_feedback_sent_at, student_completion_email_sent_at"
        try:
            result = (
                self.client.table("v2_sessions")
                .select(wide)
                .eq("user_id", user_id)
                .eq("status", "completed")
                .order("completed_at", desc=True)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            msg = str(e).lower()
            if "score_for_display" in msg or "42703" in msg or "does not exist" in msg:
                result = (
                    self.client.table("v2_sessions")
                    .select(base)
                    .eq("user_id", user_id)
                    .eq("status", "completed")
                    .order("completed_at", desc=True)
                    .limit(1)
                    .execute()
                )
                return result.data[0] if result.data else None
            raise

    def v2_get_latest_session_id_for_user(self, user_id: str) -> Optional[str]:
        """Most recent v2_sessions.id by created_at (any status). For admin UI when no completed row exists."""
        try:
            result = (
                self.client.table("v2_sessions")
                .select("id")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if not result.data:
                return None
            sid = result.data[0].get("id")
            return str(sid) if sid else None
        except Exception as e:
            logger.warning("v2_get_latest_session_id_for_user failed user_id=%s: %s", user_id, e)
            return None

    def v2_mark_tutor_feedback_sent(self, session_id: str, user_id: str):
        """Set tutor_feedback_sent_at to now for this session (idempotent)."""
        from datetime import datetime, timezone
        self.client.table("v2_sessions").update({
            "tutor_feedback_sent_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", session_id).eq("user_id", user_id).execute()
        return True

    def v2_mark_tutor_feedback_sent_for_user(self, user_id: str):
        """Set tutor_feedback_sent_at to now on the user's most recent completed session. Call when admin sends new homework (POST send-assignment)."""
        last = self.v2_get_last_completed_session(user_id)
        if not last:
            return
        self.v2_mark_tutor_feedback_sent(last["id"], user_id)

    def v2_get_student_coaching_memory(self, user_id: str):
        """Return the coaching memory row for the user, or None.

        This field is optional in admin UI. If DB grants are missing temporarily
        (e.g. SQLSTATE 42501 on v2_student_coaching_memory), we avoid failing the
        whole profile endpoint and simply omit coaching memory.
        """
        try:
            result = (
                self.client.table("v2_student_coaching_memory")
                .select("*")
                .eq("user_id", user_id)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            msg = str(e).lower()
            if "v2_student_coaching_memory" in msg and (
                "permission denied" in msg or "42501" in msg
            ):
                logger.warning(
                    "v2_get_student_coaching_memory: missing DB grant, returning None: %s",
                    e,
                )
                return None
            raise

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
            .select("status, score, recording_1_performance_profile")
            .eq("id", session_id)
            .eq("user_id", user_id)
            .execute()
        )
        session = result.data[0] if result.data else None
        if not session or (session.get("status") or "").strip().lower() != "completed":
            return
        current_score = session.get("score")
        current_profile = session.get("recording_1_performance_profile")

        # Last 4 OTHER completed sessions (exclude current session_id); include profile for recurring_issues
        result = (
            self.client.table("v2_sessions")
            .select("score, recording_1_performance_profile")
            .eq("user_id", user_id)
            .eq("status", "completed")
            .neq("id", session_id)
            .order("completed_at", desc=True)
            .limit(4)
            .execute()
        )
        others = list(reversed(result.data or []))  # oldest first

        last_5_scores = []
        last_5_profiles = []
        for row in others:
            s = row.get("score")
            if s is not None:
                try:
                    last_5_scores.append(float(s))
                except (TypeError, ValueError):
                    pass
            prof = row.get("recording_1_performance_profile")
            last_5_profiles.append(prof if isinstance(prof, dict) else None)

        if current_score is not None:
            try:
                last_5_scores.append(float(current_score))
            except (TypeError, ValueError):
                pass
        last_5_profiles.append(current_profile if isinstance(current_profile, dict) else None)

        last_5_scores = last_5_scores[-5:]
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
            "recurring_issues": recurring_issues,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.client.table("v2_student_coaching_memory").upsert(
            payload, on_conflict="user_id"
        ).execute()

    # ---------- Sniper adaptive (user_sniper_profile, session_sniper_metrics) ----------

    def get_sniper_profile(self, user_id: str) -> Optional[dict]:
        """Get student profile row or None (fallback to legacy user_sniper_profile)."""
        return self._select_student_profile_row(user_id)

    def get_sniper_profile_payload(self, user_id: str) -> dict:
        """Return the sniper profile with frontend-safe realtime progression defaults."""
        profile = self.get_sniper_profile(user_id) or {}

        def as_int(value, default: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        out = dict(profile)
        out["user_id"] = str(out.get("user_id") or user_id)
        out["realtime_level"] = max(1, as_int(out.get("realtime_level"), 1))
        out["realtime_step"] = min(10, max(1, as_int(out.get("realtime_step"), 1)))
        out["realtime_pitch_baseline_st"] = out.get("realtime_pitch_baseline_st")
        out["sessions_with_pitch_count"] = max(0, as_int(out.get("sessions_with_pitch_count"), 0))
        return out

    def _session_homework_recording_words_per_minute(self, session_id: str):
        """Words per minute from the recording linked to a v2 session (recording_1)."""
        if not session_id:
            return None
        try:
            sess = (
                self.client.table("v2_sessions")
                .select("recording_1_id")
                .eq("id", session_id)
                .limit(1)
                .execute()
            )
            if not sess.data:
                return None
            s0 = sess.data[0]
            rid = s0.get("recording_1_id")
            if not rid:
                return None
            rec_res = (
                self.client.table("recordings")
                .select("words_per_minute")
                .eq("id", str(rid))
                .limit(1)
                .execute()
            )
            if not rec_res.data:
                return None
            return rec_res.data[0].get("words_per_minute")
        except Exception as e:
            logger.debug("_session_homework_recording_words_per_minute: %s", e)
            return None

    def v2_get_admin_measured_metrics_snapshot(self, user_id: str) -> Dict[str, Any]:
        """Admin UI: latest measured speech metrics (Sniper session) + optional baselines.

        ``latest`` prefers ``session_sniper_metrics`` (realtime/session-complete payload).
        Falls back to ``recordings.words_per_minute`` from the most recent v2 session
        recording when no Sniper row exists (homework-only path).
        """
        baselines: Dict[str, Any] = {}
        try:
            raw_profile = self.get_sniper_profile(user_id) or {}
            for key in (
                "baseline_wpm",
                "baseline_pause_ms",
                "baseline_dynamic_db",
                "baseline_emphasis_per_min",
                "baseline_energy_ratio",
                "baseline_fatigue_sec",
                "realtime_pitch_baseline_st",
            ):
                if key in raw_profile and raw_profile.get(key) is not None:
                    baselines[key] = raw_profile.get(key)
        except Exception:
            pass

        latest: Dict[str, Any] = {
            "source": None,
            "session_id": None,
            "captured_at": None,
            "wpm": None,
            "pause_ms": None,
            "dynamic_db": None,
            "emphasis_per_min": None,
            "energy_ratio": None,
            "voiced_duration_sec": None,
            "pitch_center_st": None,
            "pitch_frame_count": None,
            "stage_score": None,
            "student_rating_1_10": None,
            "recording_id": None,
            "filler_words_count": None,
            "duration_ms": None,
        }

        try:
            sm_res = (
                self.client.table("session_sniper_metrics")
                .select(
                    "session_id, user_id, wpm, pause_ms, dynamic_db, emphasis_per_min, "
                    "energy_ratio, voiced_duration_sec, pitch_center_st, pitch_frame_count, "
                    "stage_score, student_rating_1_10, created_at"
                )
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            row = sm_res.data[0] if sm_res.data else None
            if row and any(
                row.get(k) is not None
                for k in (
                    "wpm",
                    "pause_ms",
                    "dynamic_db",
                    "emphasis_per_min",
                    "energy_ratio",
                    "pitch_center_st",
                    "stage_score",
                    "voiced_duration_sec",
                    "student_rating_1_10",
                )
            ):
                latest["source"] = "session_sniper_metrics"
                latest["session_id"] = row.get("session_id")
                latest["captured_at"] = row.get("created_at")
                for k in (
                    "wpm",
                    "pause_ms",
                    "dynamic_db",
                    "emphasis_per_min",
                    "energy_ratio",
                    "voiced_duration_sec",
                    "pitch_center_st",
                    "pitch_frame_count",
                    "stage_score",
                    "student_rating_1_10",
                ):
                    latest[k] = row.get(k)
                # Sniper row can exist (pause, stage_score, etc.) while wpm stayed null; Whisper WPM is on recordings.
                if latest.get("wpm") is None and row.get("session_id"):
                    wpm_rec = self._session_homework_recording_words_per_minute(str(row["session_id"]))
                    if wpm_rec is not None:
                        latest["wpm"] = wpm_rec
                wpm_val = latest.get("wpm")
                wpm_high = bool(wpm_val is not None and float(wpm_val) > 110)
                return {"latest": latest, "baselines": baselines or None, "wpm_high": wpm_high}
        except Exception as e:
            msg = str(e).lower()
            if "session_sniper_metrics" in msg and (
                "permission denied" in msg or "42501" in msg
            ):
                logger.warning(
                    "v2_get_admin_measured_metrics_snapshot: session_sniper_metrics not readable: %s",
                    e,
                )
            else:
                logger.debug("v2_get_admin_measured_metrics_snapshot: sniper read failed: %s", e)

        try:
            # Include active/in-progress sessions too. Admin should see recording
            # metrics soon after upload, not only after session completion.
            sess_res = (
                self.client.table("v2_sessions")
                .select("id, created_at, completed_at, recording_1_id")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(60)
                .execute()
            )
            for s in sess_res.data or []:
                rid = s.get("recording_1_id")
                if not rid:
                    continue
                rec_res = (
                    self.client.table("recordings")
                    .select("id, words_per_minute, filler_words_count, duration, created_at")
                    .eq("id", rid)
                    .limit(1)
                    .execute()
                )
                if not rec_res.data:
                    continue
                r = rec_res.data[0]
                if (
                    r.get("words_per_minute") is None
                    and r.get("filler_words_count") is None
                    and r.get("duration") is None
                ):
                    continue
                latest["source"] = "recording"
                latest["session_id"] = s.get("id")
                latest["recording_id"] = r.get("id")
                latest["captured_at"] = r.get("created_at") or s.get("completed_at")
                latest["wpm"] = r.get("words_per_minute")
                latest["filler_words_count"] = r.get("filler_words_count")
                latest["duration_ms"] = r.get("duration")
                try:
                    sm_sess = self.get_session_sniper_metrics(str(s.get("id")))
                    if sm_sess and sm_sess.get("student_rating_1_10") is not None:
                        latest["student_rating_1_10"] = sm_sess.get("student_rating_1_10")
                except Exception:
                    pass
                break
        except Exception as e:
            logger.debug("v2_get_admin_measured_metrics_snapshot: recording fallback failed: %s", e)

        if not latest.get("source"):
            latest = {**latest, "source": None}
        # Flag WPM > 110 for frontend highlight
        wpm_val = latest.get("wpm")
        wpm_high = bool(wpm_val is not None and float(wpm_val) > 110)
        return {"latest": latest, "baselines": baselines or None, "wpm_high": wpm_high}

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
        realtime_level: Optional[int] = None,
        realtime_step: Optional[int] = None,
        realtime_pitch_baseline_st: Optional[float] = None,
        sessions_with_pitch_count: Optional[int] = None,
        realtime_last_completed_session_id: Optional[str] = None,
    ):
        """Insert or update student_profile (fallback-compatible with legacy table)."""
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
        if realtime_level is not None:
            payload["realtime_level"] = realtime_level
        if realtime_step is not None:
            payload["realtime_step"] = realtime_step
        if realtime_pitch_baseline_st is not None:
            payload["realtime_pitch_baseline_st"] = realtime_pitch_baseline_st
        if sessions_with_pitch_count is not None:
            payload["sessions_with_pitch_count"] = sessions_with_pitch_count
        if realtime_last_completed_session_id is not None:
            payload["realtime_last_completed_session_id"] = realtime_last_completed_session_id
        wrote_primary = False
        try:
            self.client.table(self._student_profile_table).upsert(payload, on_conflict="user_id").execute()
            wrote_primary = True
        except Exception as e:
            if not self._is_relation_missing_error(e):
                raise
        # Backward compatibility during migration window.
        if not wrote_primary:
            self.client.table(self._legacy_student_profile_table).upsert(payload, on_conflict="user_id").execute()

    def set_sniper_realtime_progression(
        self,
        user_id: str,
        *,
        realtime_level: Optional[int] = None,
        realtime_step: Optional[int] = None,
    ) -> dict:
        """Set the student's unlocked realtime level/step explicitly (coach-controlled progression)."""
        profile = self.get_sniper_profile(user_id) or {}

        def as_int(value, default: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        level = max(1, as_int(realtime_level if realtime_level is not None else profile.get("realtime_level"), 1))
        step = min(10, max(1, as_int(realtime_step if realtime_step is not None else profile.get("realtime_step"), 1)))
        self.upsert_sniper_profile(
            user_id=user_id,
            session_count=as_int(profile.get("session_count"), 0),
            sessions_with_energy_count=as_int(profile.get("sessions_with_energy_count"), 0),
            realtime_level=level,
            realtime_step=step,
        )
        return self.get_sniper_profile_payload(user_id)

    def advance_sniper_realtime_progression(
        self,
        session_id: str,
        user_id: str,
        *,
        max_step: int = 10,
        allow_level_rollover: bool = False,
    ) -> dict:
        """
        Advance the user's realtime training progression once per completed session.
        Default behavior is simple: increment step by 1, capped at step 10 for level 1.
        """
        profile = self.get_sniper_profile(user_id) or {}
        last_session_id = profile.get("realtime_last_completed_session_id")
        if last_session_id and str(last_session_id) == str(session_id):
            return self.get_sniper_profile_payload(user_id)

        def as_int(value, default: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        current_level = max(1, as_int(profile.get("realtime_level"), 1))
        current_step = min(max_step, max(1, as_int(profile.get("realtime_step"), 1)))

        next_level = current_level
        next_step = current_step
        if current_step < max_step:
            next_step = current_step + 1
        elif allow_level_rollover:
            next_level = current_level + 1
            next_step = 1

        self.upsert_sniper_profile(
            user_id=user_id,
            session_count=as_int(profile.get("session_count"), 0),
            sessions_with_energy_count=as_int(profile.get("sessions_with_energy_count"), 0),
            realtime_level=next_level,
            realtime_step=next_step,
            realtime_pitch_baseline_st=profile.get("realtime_pitch_baseline_st"),
            sessions_with_pitch_count=as_int(profile.get("sessions_with_pitch_count"), 0),
            realtime_last_completed_session_id=str(session_id),
        )
        return self.get_sniper_profile_payload(user_id)

    def save_session_step_snapshot(
        self,
        session_id: str,
        user_id: str,
        realtime_level_at_session: int,
        realtime_step_at_session: int,
    ) -> bool:
        """Best-effort save of authoritative backend level/step snapshot on v2_sessions."""
        try:
            self.client.table("v2_sessions").update({
                "realtime_level_at_session": int(realtime_level_at_session),
                "realtime_step_at_session": int(realtime_step_at_session),
            }).eq("id", session_id).eq("user_id", user_id).execute()
            return True
        except Exception:
            return False

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
        recording_id: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        pitch_center_st: Optional[float] = None,
        pitch_frame_count: Optional[int] = None,
        frontend_level: Optional[int] = None,
        frontend_step: Optional[int] = None,
        completed: Optional[bool] = None,
        valid_for_progression: Optional[bool] = None,
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
        if recording_id is not None:
            payload["recording_id"] = recording_id
        if duration_seconds is not None:
            payload["duration_seconds"] = duration_seconds
        if pitch_center_st is not None:
            payload["pitch_center_st"] = pitch_center_st
        if pitch_frame_count is not None:
            payload["pitch_frame_count"] = pitch_frame_count
        if frontend_level is not None:
            payload["frontend_level"] = frontend_level
        if frontend_step is not None:
            payload["frontend_step"] = frontend_step
        if completed is not None:
            payload["completed"] = completed
        if valid_for_progression is not None:
            payload["valid_for_progression"] = valid_for_progression
        # Recording-1 job upserts without student_rating_1_10; some PostgREST/merge paths
        # can clear the column if the student already saved a self-rating while the job was running.
        if "student_rating_1_10" not in payload:
            try:
                existing_sm = self.get_session_sniper_metrics(session_id) or {}
                if existing_sm.get("student_rating_1_10") is not None:
                    payload["student_rating_1_10"] = existing_sm["student_rating_1_10"]
            except Exception:
                pass
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            self.client.table("session_sniper_metrics").upsert(payload, on_conflict="session_id").execute()
        except Exception:
            legacy_payload = {
                k: v for k, v in payload.items()
                if k in {
                    "session_id",
                    "user_id",
                    "wpm",
                    "pause_ms",
                    "dynamic_db",
                    "emphasis_per_min",
                    "energy_ratio",
                    "stage_score",
                    "voiced_duration_sec",
                    "student_rating_1_10",
                }
            }
            self.client.table("session_sniper_metrics").upsert(legacy_payload, on_conflict="session_id").execute()

    def get_session_sniper_metrics(self, session_id: str) -> Optional[dict]:
        """Get session_sniper_metrics for session or None."""
        result = self.client.table("session_sniper_metrics").select("*").eq("session_id", session_id).execute()
        return result.data[0] if result.data else None

    def get_similar_students_by_wpm(self, user_id: str, wpm_threshold: float = 110.0) -> List[dict]:
        """Find other students whose latest session WPM is above wpm_threshold.
        Returns list of {user_id, email, wpm, session_id} sorted by WPM descending.
        Excludes the current user."""
        all_metrics = (
            self.client.table("session_sniper_metrics")
            .select("user_id, wpm, session_id, created_at")
            .not_.is_("wpm", "null")
            .gt("wpm", 0)
            .neq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(500)
            .execute()
        )
        # Keep only the latest per user, filter by threshold
        seen_users = set()
        candidates = []
        for row in all_metrics.data or []:
            uid = row["user_id"]
            if uid in seen_users:
                continue
            seen_users.add(uid)
            row_wpm = float(row["wpm"])
            if row_wpm > wpm_threshold:
                candidates.append({
                    "user_id": uid,
                    "wpm": round(row_wpm, 1),
                    "session_id": row["session_id"],
                })

        # Enrich with emails and names
        for c in candidates:
            try:
                email = self.get_user_email_from_auth(c["user_id"])
                c["email"] = email or ""
            except Exception:
                c["email"] = ""
            try:
                details = self.v2_get_student_details(c["user_id"])
                c["name"] = (details.get("name") or "").strip() if details else ""
            except Exception:
                c["name"] = ""

        # Sort by WPM descending
        candidates.sort(key=lambda c: c["wpm"], reverse=True)
        return candidates

    def update_or_set_session_sniper_rating(
        self, session_id: str, user_id: str, student_rating_1_10: int
    ) -> bool:
        """Persist 1-5 self-rating on session_sniper_metrics.

        PostgREST ``update()`` often returns an empty ``data`` array even when rows were
        updated, so update-then-insert could duplicate-key fail after the recording job
        had already upserted metrics. Always upsert on ``session_id`` instead.

        Merge with any existing row so we never drop ``stage_score`` / ffmpeg fields
        written by the recording-1 job (defense-in-depth vs partial upsert behavior).
        """
        session = self.v2_get_session(session_id, user_id)
        if not session:
            return False
        existing = self.get_session_sniper_metrics(session_id) or {}
        payload = {
            "session_id": session_id,
            "user_id": user_id,
            "student_rating_1_10": int(student_rating_1_10),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        for key in (
            "wpm",
            "pause_ms",
            "dynamic_db",
            "emphasis_per_min",
            "energy_ratio",
            "stage_score",
            "voiced_duration_sec",
            "recording_id",
            "duration_seconds",
            "pitch_center_st",
            "pitch_frame_count",
            "frontend_level",
            "frontend_step",
            "completed",
            "valid_for_progression",
        ):
            if existing.get(key) is not None:
                payload[key] = existing[key]
        self.client.table("session_sniper_metrics").upsert(
            payload, on_conflict="session_id"
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
        the student's 1-5 self-rating is >= 4 or the coach grade is >= 8.
        """
        stage_100 = None
        if stage_score is not None:
            stage_100 = float(stage_score) * 100.0 if float(stage_score) <= 1.0 else float(stage_score)
        if stage_100 is None or stage_100 < 60:
            return
        if voiced_duration_sec is not None and voiced_duration_sec < 60:
            return
        if student_rating_1_10 is not None and student_rating_1_10 < 3:
            return
        if session_id:
            session = self.v2_get_session(session_id, user_id)
            if session and session.get("report_grade") is not None and (session.get("report_grade") or 0) < 5:
                return
        rating_ok = student_rating_1_10 is not None and student_rating_1_10 >= 4
        if not rating_ok and session_id:
            session = self.v2_get_session(session_id, user_id)
            if session and (session.get("report_grade") or 0) >= 8:
                rating_ok = True
        if not rating_ok:
            return

        profile = self.get_sniper_profile(user_id) or {}
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

    def update_sniper_pitch_baseline_from_session_summary(
        self,
        user_id: str,
        *,
        pitch_center_st: Optional[float] = None,
        pitch_frame_count: Optional[int] = None,
        min_pitch_frame_count: int = 10,
    ) -> bool:
        """
        Update the adaptive pitch baseline from a completed session summary.
        Safe to call repeatedly; skips when there is not enough pitch evidence.
        """
        if pitch_center_st is None or pitch_frame_count is None:
            return False
        try:
            pitch_value = float(pitch_center_st)
            frame_count = int(pitch_frame_count)
        except (TypeError, ValueError):
            return False
        if frame_count < min_pitch_frame_count:
            return False

        profile = self.get_sniper_profile(user_id) or {}

        def as_int(value, default: int) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        old_pitch = profile.get("realtime_pitch_baseline_st")
        if old_pitch is None:
            new_pitch = pitch_value
        else:
            try:
                new_pitch = (0.8 * float(old_pitch)) + (0.2 * pitch_value)
            except (TypeError, ValueError):
                new_pitch = pitch_value

        self.upsert_sniper_profile(
            user_id=user_id,
            session_count=as_int(profile.get("session_count"), 0),
            sessions_with_energy_count=as_int(profile.get("sessions_with_energy_count"), 0),
            realtime_level=max(1, as_int(profile.get("realtime_level"), 1)),
            realtime_step=min(10, max(1, as_int(profile.get("realtime_step"), 1))),
            realtime_pitch_baseline_st=new_pitch,
            sessions_with_pitch_count=max(0, as_int(profile.get("sessions_with_pitch_count"), 0)) + 1,
        )
        return True

    def update_sniper_baseline_from_session(
        self,
        session_id: str,
        user_id: str,
        recording_wpm: Optional[float] = None,
        recording_duration_sec: Optional[float] = None,
        score: Optional[float] = None,
    ):
        """
        After session completes: merge session_sniper_metrics + recording into user_sniper_profile (EMA).
        Only update when stage_score >= 60, voiced_duration >= 60s, and (self-rating >= 4 on the 1-5 scale or report_grade >= 8).
        Skip when either rating is clearly low.
        """
        metrics = self.get_session_sniper_metrics(session_id)
        stage_score_100 = None
        if metrics and metrics.get("stage_score") is not None:
            stage_score_100 = float(metrics["stage_score"])
        elif score is not None:
            stage_score_100 = float(score) * 100.0
        voiced_sec = (metrics or {}).get("voiced_duration_sec")
        duration_sec = voiced_sec if voiced_sec is not None else recording_duration_sec
        if stage_score_100 is None or stage_score_100 < 60:
            return
        if duration_sec is not None and duration_sec < 60:
            return
        student_rating = (metrics or {}).get("student_rating_1_10")
        if student_rating is not None and int(student_rating) < 3:
            return
        session = self.v2_get_session(session_id, user_id)
        if session and session.get("report_grade") is not None and (session.get("report_grade") or 0) < 5:
            return
        rating_ok = student_rating is not None and int(student_rating) >= 4
        if not rating_ok and session and (session.get("report_grade") or 0) >= 8:
            rating_ok = True
        if not rating_ok:
            return

        profile = self.get_sniper_profile(user_id) or {}
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

    # ---------- Homework tasks (per-student public.tasks; pool public.tasks_pool) ----------
    DEFAULT_STUDENT_TASK_TEXT = "Do you think you are a good communicator? Why?"
    TASK_TEMPLATE_ALLOWED_PROFILES = {
        "The Overwhelmed",
        "The Stressor",
        "The Drifter",
        "The Master",
    }
    TASK_TEMPLATE_DEFAULT_PROFILE = "The Overwhelmed"
    TASK_TEMPLATE_DEFAULT_LEVEL = 1
    TASK_TEMPLATE_DEFAULT_STEP = 1

    def v2_ensure_default_student_task(self, user_id: str) -> bool:
        """If user has no homework tasks, create the default one. Idempotent."""
        import logging
        log = logging.getLogger(__name__)
        tasks = self.v2_get_student_tasks(user_id)
        if tasks:
            return True
        data = {
            "user_id": user_id,
            "text": self.DEFAULT_STUDENT_TASK_TEXT,
            "order_index": 0,
            "max_performance_score": 1,
        }
        try:
            self.v2_insert_student_task(data)
            return True
        except Exception as e:
            log.warning("v2_ensure_default_student_task insert failed for user_id=%s: %s", user_id, e)
            return False

    def v2_apply_coach_homework_task_text(self, user_id: str, task_text: str | None) -> None:
        """After coach sends assignment, persist task text to public.tasks so session/start sees NO_TASK_CONFIGURED=false.

        Updates the student's first task by order_index; inserts one row if none exist.
        No-op if task_text is empty.
        """
        text = (task_text or "").strip()
        if not text:
            return
        text = text[:8000]
        try:
            rows = self.v2_get_student_tasks(user_id)
            if not rows:
                self.v2_insert_student_task(
                    {
                        "user_id": user_id,
                        "text": text,
                        "order_index": 0,
                        "max_performance_score": 1,
                    }
                )
                return
            first = rows[0]
            tid = first.get("id")
            if tid and (first.get("text") or "").strip() != text:
                self.v2_update_student_task(str(tid), {"text": text})
        except Exception as e:
            logger.warning("v2_apply_coach_homework_task_text failed user_id=%s: %s", user_id, e)

    def v2_get_student_tasks(self, user_id: str):
        result = (
            self.client.table("tasks")
            .select("*")
            .eq("user_id", user_id)
            .order("order_index")
            .order("created_at")
            .execute()
        )
        return result.data or []

    def v2_insert_student_task(self, data: dict):
        result = self.client.table("tasks").insert(data).execute()
        return result.data[0] if result.data else None

    def v2_update_student_task(self, task_id: str, data: dict):
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
            result = self.client.table("tasks").select("*").eq("id", task_id).execute()
            return result.data[0] if result.data else None
        result = self.client.table("tasks").update(payload).eq("id", task_id).execute()
        return result.data[0] if result.data else None

    def v2_delete_student_task(self, task_id: str):
        self.client.table("tasks").delete().eq("id", task_id).execute()

    def _normalize_task_template_fields(self, data: dict, *, partial: bool = False) -> dict:
        payload = {}
        if "target_profile" in data or not partial:
            raw_profile = data.get("target_profile", self.TASK_TEMPLATE_DEFAULT_PROFILE)
            profile = (raw_profile or "").strip()
            if profile not in self.TASK_TEMPLATE_ALLOWED_PROFILES:
                raise ValueError("INVALID_TARGET_PROFILE")
            payload["target_profile"] = profile
        if "level" in data or not partial:
            raw_level = data.get("level", self.TASK_TEMPLATE_DEFAULT_LEVEL)
            try:
                level = int(raw_level)
            except (TypeError, ValueError):
                raise ValueError("INVALID_LEVEL")
            if level < 1:
                raise ValueError("INVALID_LEVEL")
            payload["level"] = level
        if "step_in_level" in data or not partial:
            raw_step = data.get("step_in_level", self.TASK_TEMPLATE_DEFAULT_STEP)
            try:
                step = int(raw_step)
            except (TypeError, ValueError):
                raise ValueError("INVALID_STEP_IN_LEVEL")
            if step < 1 or step > 10:
                raise ValueError("INVALID_STEP_IN_LEVEL")
            payload["step_in_level"] = step
        if "is_active" in data or not partial:
            payload["is_active"] = bool(data.get("is_active", True))
        if "replaces_task_id" in data:
            payload["replaces_task_id"] = data.get("replaces_task_id") or None
        return payload

    def v2_get_task_pool(
        self,
        *,
        include_inactive: bool = False,
        include_behavioral: bool = False,
    ):
        """Return rows from `tasks_pool`.

        `include_behavioral` defaults to False so the legacy admin warm-up
        modal stays uncluttered after the 12 canonical behavioral tasks are
        seeded. The diagnose-and-prescribe engine should opt in via
        `include_behavioral=True` (or use `v2_get_next_active_task_pool_template`
        with `is_behavioral=True`).
        """
        try:
            q = self.client.table("tasks_pool").select("*")
            if not include_inactive:
                q = q.eq("is_active", True)
            if not include_behavioral:
                q = q.eq("is_behavioral", False)
            result = (
                q.order("is_active", desc=True)
                .order("target_profile")
                .order("level")
                .order("step_in_level")
                .order("order_index")
                .order("created_at")
                .execute()
            )
            return result.data or []
        except Exception:
            # Backward compatibility with older schemas that do not yet have new columns.
            result = (
                self.client.table("tasks_pool")
                .select("*")
                .order("order_index")
                .order("created_at")
                .execute()
            )
            return result.data or []

    def v2_get_task_pool_by_id(self, pool_id: str):
        result = self.client.table("tasks_pool").select("*").eq("id", pool_id).execute()
        return result.data[0] if result.data else None

    def v2_insert_task_pool(self, data: dict):
        data = dict(data)
        data.setdefault("order_index", 0)
        data.setdefault("max_performance_score", 1.0)
        data.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
        data.update(self._normalize_task_template_fields(data, partial=False))
        result = self.client.table("tasks_pool").insert(data).execute()
        return result.data[0] if result.data else None

    def v2_update_task_pool(self, pool_id: str, data: dict):
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
        payload.update(self._normalize_task_template_fields(data, partial=True))
        if payload:
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        if not payload:
            return self.v2_get_task_pool_by_id(pool_id)
        result = self.client.table("tasks_pool").update(payload).eq("id", pool_id).execute()
        return result.data[0] if result.data else None

    def v2_delete_task_pool(self, pool_id: str, *, hard_delete: bool = False):
        if hard_delete:
            self.client.table("tasks_pool").delete().eq("id", pool_id).execute()
            return
        try:
            self.client.table("tasks_pool").update(
                {
                    "is_active": False,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            ).eq("id", pool_id).execute()
            return
        except Exception:
            # Backward compatibility for old schema (no is_active).
            self.client.table("tasks_pool").delete().eq("id", pool_id).execute()

    def v2_sync_student_tasks_from_pool(self, user_id: str, pool_task_ids: list):
        """Replace student's tasks from tasks_pool ids (display order)."""
        self.client.table("tasks").delete().eq("user_id", user_id).execute()
        if not pool_task_ids:
            return []
        inserted = []
        for idx, pool_id in enumerate(pool_task_ids):
            row = self.v2_get_task_pool_by_id(pool_id)
            if not row:
                continue
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
            new_row = self.v2_insert_student_task(data)
            if new_row:
                inserted.append(new_row)
        return inserted

    def v2_create_task_pool_entry_and_assign_student(
        self,
        user_id: str,
        text: str,
        order_index: int = 0,
        max_performance_score: float = 1.0,
        insert_at: Any = "end",
        target_profile: str = TASK_TEMPLATE_DEFAULT_PROFILE,
        level: int = TASK_TEMPLATE_DEFAULT_LEVEL,
        step_in_level: int = TASK_TEMPLATE_DEFAULT_STEP,
        is_active: bool = True,
        replaces_task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Insert tasks_pool row, then sync student's tasks from pool selection."""
        text_clean = (text or "").strip()
        if not text_clean:
            raise ValueError("text is required")
        rows = self.v2_get_student_tasks(user_id)
        existing_ids = [str(r["pool_task_id"]) for r in rows if r.get("pool_task_id")]
        dropped_non_pool = sum(1 for r in rows if not r.get("pool_task_id"))
        try:
            mps = float(max_performance_score)
        except (TypeError, ValueError):
            mps = 1.0
        pool_row = self.v2_insert_task_pool(
            {
                "text": text_clean,
                "order_index": int(order_index),
                "max_performance_score": mps,
                "target_profile": target_profile,
                "level": level,
                "step_in_level": step_in_level,
                "is_active": bool(is_active),
                "replaces_task_id": replaces_task_id,
            }
        )
        if not pool_row:
            raise RuntimeError("Failed to insert task pool row")
        new_id = str(pool_row["id"])
        if insert_at == "end" or insert_at is None:
            final_ids = existing_ids + [new_id]
        else:
            try:
                idx = int(insert_at)
            except (TypeError, ValueError):
                idx = len(existing_ids)
            idx = max(0, min(idx, len(existing_ids)))
            final_ids = existing_ids[:idx] + [new_id] + existing_ids[idx:]
        try:
            assigned = self.v2_sync_student_tasks_from_pool(user_id, final_ids)
        except Exception:
            try:
                self.v2_delete_task_pool(new_id, hard_delete=True)
            except Exception:
                pass
            raise
        return {
            "tasks_pool": pool_row,
            "tasks": assigned,
            "dropped_non_pool_tasks": dropped_non_pool,
        }

    def v2_get_next_active_task_pool_template(
        self,
        *,
        target_profile: str,
        level: int,
        exclude_pool_task_ids: Optional[List[str]] = None,
        limit: int = 1,
        is_behavioral: Optional[bool] = None,
    ) -> List[dict]:
        """Deterministic template lookup: active rows ordered by step_in_level then creation.

        `is_behavioral` scopes the lookup to one partition of `tasks_pool`:
          * True  -> only the 12 canonical behavioral recommendation-engine tasks
          * False -> only legacy warm-up tasks
          * None  -> no filter (historical behavior; may return mixed rows)
        """
        q = (
            self.client.table("tasks_pool")
            .select("*")
            .eq("is_active", True)
            .eq("target_profile", target_profile)
            .eq("level", int(level))
        )
        if is_behavioral is not None:
            q = q.eq("is_behavioral", bool(is_behavioral))
        q = (
            q.order("step_in_level")
            .order("created_at")
            .limit(max(1, int(limit)))
        )
        result = q.execute()
        rows = result.data or []
        if exclude_pool_task_ids:
            excluded = {str(x) for x in exclude_pool_task_ids if x}
            rows = [r for r in rows if str(r.get("id")) not in excluded]
        return rows

    def v2_get_last_homework_performance_score(self, user_id: str):
        """Last completed homework session's canonical score (0-1), or None if no completed session."""
        result = (
            self.client.table("v2_sessions")
            .select("score")
            .eq("user_id", user_id)
            .eq("status", "completed")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        row = result.data[0]
        score = row.get("score")
        if score is None:
            return None
        return float(score)

    def v2_get_performance_history(self, user_id: str, limit: int = 5) -> List[dict]:
        """Last N completed homework sessions: session_id, created_at, score (0-1). Oldest first for chart S1..SN."""
        from services.utils import score_01_from_recording_row

        result = (
            self.client.table("v2_sessions")
            .select("id, created_at, score, score_for_display, recording_1_id")
            .eq("user_id", user_id)
            .eq("status", "completed")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        if not result.data:
            return []
        rows = list(reversed(result.data))
        out = []
        for r in rows:
            s01 = None
            if r.get("score_for_display") is not None:
                try:
                    s01 = max(0.0, min(1.0, float(r.get("score_for_display")) / 100.0))
                except (TypeError, ValueError):
                    s01 = None
            if s01 is None:
                s = r.get("score")
                if s is None:
                    continue
                s01 = float(s or 0)
            # Stored score can be 0 while the recording job wrote the real value in scoring_debug only.
            if s01 <= 0 and r.get("recording_1_id"):
                try:
                    rec = self.get_recording(str(r["recording_1_id"]), None)
                    recovered = score_01_from_recording_row(rec or {})
                    if recovered is not None and recovered > 0:
                        s01 = recovered
                except Exception:
                    pass
            out.append(
                {
                    "session_id": str(r["id"]) if r.get("id") else None,
                    "created_at": r.get("created_at"),
                    "score": s01,
                    # Backward compatibility for existing callers.
                    "performance_score_end": s01,
                }
            )
        return out

    def v2_get_assigned_task_for_user(self, user_id: str):
        """First homework task by order_index (no auto-create). None if none configured."""
        result = (
            self.client.table("tasks")
            .select("*")
            .eq("user_id", user_id)
            .order("order_index")
            .order("created_at")
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_get_active_homework_session(self, user_id: str):
        """Active homework flow session.

        `post_questions` stays here only for legacy compatibility with older rows;
        the current web client should not depend on that state.
        """
        statuses = (
            "task",
            "warm_up",  # legacy rows until rename_homework_session_status_warm_up_to_task.sql
            "task_block",
            "final_task_ready",
            "post_questions",
            "completing_from_recording_1",
        )
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
        """Create new homework flow session (status=task: first recording step)."""
        result = self.client.table("v2_sessions").insert({"user_id": user_id, "status": "task"}).execute()
        return result.data[0] if result.data else None

    # ------------------------------------------------------------------
    # Curiosity Gate funnel (anonymous-first acquisition)
    # ------------------------------------------------------------------

    def v2_create_guest_session(
        self,
        guest_session_id: str,
        *,
        recording_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Create an unclaimed funnel session (user_id=NULL) for the Curiosity Gate.

        The row is keyed by `guest_session_id` (UUID handed to the browser via
        an httpOnly cookie). On claim, user_id is bound — see v2_claim_guest_session.

        IMPORTANT ordering: the recordings table has FK
        `recordings.session_v2_id REFERENCES v2_sessions(id)`, so this row must
        be created BEFORE the recording row. recording_id is therefore optional
        on insert and is set later via v2_set_guest_session_recording().
        """
        payload = {
            "id": guest_session_id,
            "user_id": None,
            "status": "guest_pending_claim",
            "session_task_text": "Curiosity Gate: 15-second voice trial.",
        }
        if recording_id:
            payload["recording_1_id"] = recording_id
        result = self.client.table("v2_sessions").insert(payload).execute()
        return result.data[0] if result.data else None

    def v2_set_guest_session_recording(self, guest_session_id: str, recording_id: str) -> Optional[dict]:
        """Set v2_sessions.recording_1_id on an unclaimed funnel row.

        Filtered to user_id IS NULL because at this point the row has not been
        claimed; v2_update_session expects a real user_id and would refuse.
        """
        result = (
            self.client.table("v2_sessions")
            .update({"recording_1_id": recording_id})
            .eq("id", guest_session_id)
            .is_("user_id", "null")
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_claim_guest_session(self, guest_session_id: str, user_id: str) -> Optional[dict]:
        """Bind an unclaimed funnel session to an authenticated user.

        Atomic: the UPDATE is conditional on user_id IS NULL, so two concurrent
        claims (e.g., a double-clicked magic link) cannot both succeed. The
        loser receives None and the caller resolves it as "already claimed".

        Side effect: also writes user_id back to the recordings row so the
        analysis pipeline (which queries recordings by user_id) can find it.

        Returns the updated v2_sessions row on success, or None if the
        session was not found OR was already claimed.
        """
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        update = {
            "user_id": user_id,
            "guest_claimed_at": now_iso,
            "status": "completing_from_recording_1",
            "recording_1_processing_status": "pending",
            # Stamp self_rating so recording_1_job auto-completes after analysis;
            # the funnel UX does not include a self-rating step.
            "self_rating_submitted_at": now_iso,
        }
        result = (
            self.client.table("v2_sessions")
            .update(update)
            .eq("id", guest_session_id)
            .is_("user_id", "null")
            .execute()
        )
        if not result.data:
            return None
        row = result.data[0]
        rec_id = row.get("recording_1_id")
        if rec_id:
            try:
                self.client.table("recordings").update({"user_id": user_id}).eq("id", rec_id).execute()
            except Exception:
                # Don't unwind the claim if the recordings update fails;
                # the pipeline can still find the recording via session_v2_id.
                pass
        return row

    def v2_delete_expired_guest_sessions(self, ttl_hours: int = 24) -> int:
        """Daily cleanup: purge unclaimed funnel rows older than `ttl_hours`.

        Returns the number of rows deleted. Audio blobs in storage are
        unaffected (storage TTL is governed separately to avoid cascading
        failures from a transient storage outage).
        """
        from datetime import datetime, timedelta, timezone
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=ttl_hours)).isoformat()
        result = (
            self.client.table("v2_sessions")
            .delete()
            .is_("user_id", "null")
            .lt("created_at", cutoff)
            .execute()
        )
        return len(result.data or [])

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
        "assigned_task_id",
        "pitch_variance_ideal",
        "pending_tutor_video_url",
        "pending_tutor_video_description",
        "pending_tutor_video_bucket",
        "pending_tutor_video_storage_path",
        "skip_metric_questions",
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
        """Atomic column-specific upsert — only touches columns present in *data*.

        PostgREST ``ON CONFLICT (user_id) DO UPDATE`` only sets the columns
        included in the payload, so untouched columns keep their current
        value.  This removes the old read-merge-write cycle that was
        vulnerable to concurrent-write races.
        """
        payload: dict = {}
        for col in self._V2_OVERRIDES_COLUMNS:
            if col not in data:
                continue
            val = data[col]
            if col == "assigned_task_id" and val == "":
                val = None
            payload[col] = val
        if "skip_metric_questions" in payload and payload["skip_metric_questions"] is None:
            payload["skip_metric_questions"] = False
        if not payload:
            return self.v2_get_student_overrides(user_id)
        payload["user_id"] = user_id
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        result = self.client.table("v2_student_overrides").upsert(payload, on_conflict="user_id").execute()
        rows = result.data or []
        for row in rows:
            if str(row.get("user_id") or "") == str(user_id):
                return row
        return self.v2_get_student_overrides(user_id)

    def v2_set_pending_tutor_video(
        self,
        user_id: str,
        video_url: str = None,
        video_description: str = None,
        video_bucket: str = None,
        video_storage_path: str = None,
    ):
        """Store coach message and/or video URL for the next session. Call when admin sends assignment. Message is returned as tutor_video_description in GET session/status (homework flow is text-only; no video)."""
        payload = {}
        if video_url is not None:
            payload["pending_tutor_video_url"] = (video_url or "").strip() or None
        if video_description is not None:
            payload["pending_tutor_video_description"] = (video_description or "").strip() or None
        if video_bucket is not None:
            payload["pending_tutor_video_bucket"] = (video_bucket or "").strip() or None
        if video_storage_path is not None:
            payload["pending_tutor_video_storage_path"] = (video_storage_path or "").strip() or None
        if payload:
            self.v2_upsert_student_overrides(user_id, payload)
        return True

    def v2_get_and_clear_pending_tutor_video(self, user_id: str):
        """Return (url, description, bucket, storage_path) for the pending tutor video and clear all. Used on session/start to attach to the new session."""
        row = (
            self.client.table("v2_student_overrides")
            .select(
                "pending_tutor_video_url, pending_tutor_video_description, "
                "pending_tutor_video_bucket, pending_tutor_video_storage_path"
            )
            .eq("user_id", user_id)
            .execute()
        )
        url = None
        description = None
        bucket = None
        storage_path = None
        if row.data:
            r = row.data[0]
            if r.get("pending_tutor_video_url"):
                url = (r["pending_tutor_video_url"] or "").strip() or None
            if r.get("pending_tutor_video_description"):
                description = (r["pending_tutor_video_description"] or "").strip() or None
            if r.get("pending_tutor_video_bucket"):
                bucket = (r["pending_tutor_video_bucket"] or "").strip() or None
            if r.get("pending_tutor_video_storage_path"):
                storage_path = (r["pending_tutor_video_storage_path"] or "").strip() or None
        if url is not None or description is not None or bucket is not None or storage_path is not None:
            self.client.table("v2_student_overrides").update(
                {
                    "pending_tutor_video_url": None,
                    "pending_tutor_video_description": None,
                    "pending_tutor_video_bucket": None,
                    "pending_tutor_video_storage_path": None,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            ).eq("user_id", user_id).execute()
        return (url, description, bucket, storage_path)

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
                meta = u.get("user_metadata") or {}
                raw_name = meta.get("name") or meta.get("display_name")
                out.append({
                    "user_id": uid,
                    "email": u.get("email") or (u.get("user_metadata") or {}).get("email"),
                    "name": (str(raw_name).strip() if raw_name is not None and str(raw_name).strip() else None),
                })
            return out
        except Exception:
            return None

    def v2_get_student_details(self, user_id: str):
        """Get student details row (name, price_per_live_lesson, credits, is_archived) or None."""
        result = (
            self.client.table("v2_student_details")
            .select("user_id, name, price_per_live_lesson, credits, is_archived")
            .eq("user_id", user_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_upsert_student_details(self, user_id: str, data: dict):
        """Create/update student details. Allowed keys: name, price_per_live_lesson, credits, is_archived."""
        payload = {"user_id": user_id, "updated_at": datetime.now(timezone.utc).isoformat()}
        if "name" in data:
            name_val = data.get("name")
            if name_val is None:
                payload["name"] = None
            else:
                payload["name"] = str(name_val).strip() or None
        if "price_per_live_lesson" in data:
            payload["price_per_live_lesson"] = data.get("price_per_live_lesson")
        if "credits" in data:
            payload["credits"] = data.get("credits")
        if "is_archived" in data:
            payload["is_archived"] = bool(data.get("is_archived"))
        result = self.client.table("v2_student_details").upsert(payload, on_conflict="user_id").execute()
        return result.data[0] if result.data else None

    def v2_get_archived_user_ids(self) -> set:
        """Return set of user_id strings that have is_archived = true in v2_student_details."""
        try:
            res = (
                self.client.table("v2_student_details")
                .select("user_id")
                .eq("is_archived", True)
                .execute()
            )
            return {str(row["user_id"]) for row in (res.data or [])}
        except Exception:
            return set()

    def v2_deduct_session_credits(self, user_id: str, amount: int = 5) -> int | None:
        """Deduct credits from a student's balance. Returns new credits value or None on failure."""
        try:
            details = self.v2_get_student_details(user_id)
            current = (details or {}).get("credits")
            if current is None:
                current = 15
            new_credits = max(0, int(current) - amount)
            result = (
                self.client.table("v2_student_details")
                .upsert({"user_id": user_id, "credits": new_credits, "updated_at": datetime.now(timezone.utc).isoformat()}, on_conflict="user_id")
                .execute()
            )
            return (result.data[0] or {}).get("credits") if result.data else new_credits
        except Exception:
            return None

    def v2_increment_student_credits(self, user_id: str, delta: int) -> int | None:
        """Add delta to credits (e.g. Stripe payment). Negative delta allowed for corrections; result floors at 0. Returns new balance or None on failure."""
        try:
            d = int(delta)
            details = self.v2_get_student_details(user_id)
            current = (details or {}).get("credits")
            if current is None:
                current = 15
            new_credits = max(0, int(current) + d)
            result = (
                self.client.table("v2_student_details")
                .upsert(
                    {"user_id": user_id, "credits": new_credits, "updated_at": datetime.now(timezone.utc).isoformat()},
                    on_conflict="user_id",
                )
                .execute()
            )
            return (result.data[0] or {}).get("credits") if result.data else new_credits
        except Exception as e:
            logger.warning(
                "v2_increment_student_credits failed user_id=%s delta=%s: %s",
                user_id,
                d,
                e,
                exc_info=True,
            )
            return None

    def stripe_checkout_grant_claim(self, checkout_session_id: str) -> bool:
        """Insert idempotency row for a Stripe Checkout Session. True if newly claimed."""
        sid = (checkout_session_id or "").strip()
        if not sid:
            return False
        try:
            result = self.client.table("stripe_checkout_credit_grants").insert({"checkout_session_id": sid}).execute()
            return bool(result.data)
        except Exception as e:
            msg = str(e).lower()
            if "duplicate" in msg or "unique" in msg or "23505" in msg or "already exists" in msg:
                return False
            logger.warning("stripe_checkout_grant_claim failed session=%s: %s", sid, e)
            raise

    def stripe_checkout_grant_release(self, checkout_session_id: str) -> None:
        sid = (checkout_session_id or "").strip()
        if not sid:
            return
        try:
            self.client.table("stripe_checkout_credit_grants").delete().eq("checkout_session_id", sid).execute()
        except Exception as e:
            logger.warning("stripe_checkout_grant_release failed session=%s: %s", sid, e)

    def v2_charge_homework_completion_credits_once(self, session_id: str, user_id: str, amount: int = 5) -> None:
        """
        Deduct `amount` credits once per session when homework completes with a report.
        Idempotent: sets homework_credits_charged_at only when NULL, then deducts.
        If deduct fails, clears homework_credits_charged_at so a retry can succeed.
        """
        now = datetime.now(timezone.utc).isoformat()
        try:
            result = (
                self.client.table("v2_sessions")
                .update({"homework_credits_charged_at": now})
                .eq("id", session_id)
                .eq("user_id", user_id)
                .eq("status", "completed")
                .is_("homework_credits_charged_at", "null")
                .execute()
            )
            if not result.data:
                return
        except Exception as e:
            sentry_sdk.capture_exception(e)
            logger.warning("v2_charge_homework_completion_credits_once: flag update failed session_id=%s: %s", session_id, e)
            return

        new_bal = self.v2_deduct_session_credits(user_id, amount=amount)
        if new_bal is None:
            logger.warning(
                "v2_charge_homework_completion_credits_once: deduct failed after flag; clearing flag session_id=%s user_id=%s",
                session_id,
                user_id,
            )
            try:
                self.client.table("v2_sessions").update({"homework_credits_charged_at": None}).eq("id", session_id).eq("user_id", user_id).execute()
            except Exception:
                pass

    def v2_get_student_list_stats(self, user_id: str):
        """Optional stats for admin students list: sessions_count, last_session_at (ISO), avg_performance (0-100)."""
        sessions = (
            self.client.table("v2_sessions")
            .select("id, created_at, recording_1_id")
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
        """Get v2 sessions for a user with full report text and all analytics previews for admin session history."""
        all_session_columns = [
            "id", "created_at", "completed_at", "status",
            "recording_1_id", "report_id", "report_grade",
            "student_completion_email_sent_at",
            "self_rating_submitted_at",
            "student_self_rating",
            "score", "task_score",
            "ai_draft_grade", "ai_draft_comment",
            "question_1_score", "question_2_score", "question_3_score",
            "realtime_level_at_session", "realtime_step_at_session",
            "ai_task_score", "ai_scoring_justification", "coach_override_score", "coach_override_justification",
            "session_task_id",
            "session_task_text",
        ]
        result = None
        session_columns = [c for c in all_session_columns if c not in self._v2_sessions_missing_columns]
        session_fields = tuple(session_columns)
        max_attempts = max(1, len(all_session_columns))
        for _ in range(max_attempts):
            if not session_columns:
                raise Exception("v2_get_sessions_with_previews: no selectable v2_sessions columns available")
            select_columns = ", ".join(session_columns)
            session_fields = tuple(session_columns)
            try:
                result = (
                    self.client.table("v2_sessions")
                    .select(select_columns)
                    .eq("user_id", user_id)
                    .order("completed_at", desc=True)
                    .limit(limit)
                    .execute()
                )
                break
            except Exception as e:
                msg = str(e).lower()
                if not ("42703" in msg or "does not exist" in msg or "undefined_column" in msg):
                    raise

                missing_cols = []
                for col in all_session_columns:
                    if f"v2_sessions.{col}" in msg or f"column {col}" in msg:
                        missing_cols.append(col)

                if not missing_cols:
                    # Try to parse: "column v2_sessions.<name> does not exist"
                    m = re.search(r"column\s+v2_sessions\.([a-z0-9_]+)\s+does not exist", msg)
                    if m:
                        missing_cols = [m.group(1)]

                if not missing_cols:
                    raise

                new_missing = [c for c in missing_cols if c not in self._v2_sessions_missing_columns]
                self._v2_sessions_missing_columns.update(missing_cols)
                if new_missing:
                    logger.warning(
                        "v2_get_sessions_with_previews: columns missing %s, retrying without them: %s",
                        new_missing,
                        e,
                    )
                session_columns = [c for c in all_session_columns if c not in self._v2_sessions_missing_columns]
        if result is None:
            raise Exception("v2_get_sessions_with_previews: failed to query sessions after schema fallback retries")
        sessions = result.data or []
        session_ids = [s["id"] for s in sessions]

        # Batch: context_long for report fallback
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

        # Batch: session_sniper_metrics
        sniper_metrics_by_session: dict = {}
        if session_ids:
            try:
                sm = (
                    self.client.table("session_sniper_metrics")
                    .select("session_id, wpm, pause_ms, dynamic_db, emphasis_per_min, energy_ratio, voiced_duration_sec, pitch_center_st, pitch_frame_count, stage_score, student_rating_1_10")
                    .in_("session_id", session_ids)
                    .execute()
                )
                for row in (sm.data or []):
                    sniper_metrics_by_session[row["session_id"]] = row
            except Exception:
                pass

        # Batch: recordings (keyed by recording id)
        recording_ids = list({s.get("recording_1_id") for s in sessions if s.get("recording_1_id")})
        recordings_by_id: dict = {}
        if recording_ids:
            try:
                rec_select = "id, performance_score_v2, transcription_text, words_per_minute, filler_words_count, performance_metrics_v2, duration_ms"
                try:
                    recs = (
                        self.client.table("recordings")
                        .select(rec_select)
                        .in_("id", recording_ids)
                        .execute()
                    )
                except Exception as rec_err:
                    # Legacy schema uses `duration` (seconds) instead of `duration_ms`.
                    rec_msg = str(rec_err).lower()
                    if "duration_ms" in rec_msg and ("does not exist" in rec_msg or "42703" in rec_msg or "undefined_column" in rec_msg):
                        recs = (
                            self.client.table("recordings")
                            .select("id, performance_score_v2, transcription_text, words_per_minute, filler_words_count, performance_metrics_v2, duration")
                            .in_("id", recording_ids)
                            .execute()
                        )
                    else:
                        raise
                for row in (recs.data or []):
                    recordings_by_id[row["id"]] = row
            except Exception:
                pass

        out = []
        for s in sessions:
            rec = {k: v for k, v in s.items() if k in session_fields}
            rec["recording_id"] = s.get("recording_1_id")
            rec["recording_preview"] = None
            rec["report_preview"] = None

            recording_id = s.get("recording_1_id")
            if recording_id and recording_id in recordings_by_id:
                row = recordings_by_id[recording_id]
                raw_duration_ms = row.get("duration_ms")
                if raw_duration_ms is None and row.get("duration") is not None:
                    try:
                        raw_duration_ms = int(float(row.get("duration")) * 1000.0)
                    except (TypeError, ValueError):
                        raw_duration_ms = None
                rec["recording_preview"] = {
                    "performance_score_v2": row.get("performance_score_v2"),
                    "transcription_preview": (row.get("transcription_text") or "")[:300],
                    "words_per_minute": row.get("words_per_minute"),
                    "filler_words_count": row.get("filler_words_count"),
                    "performance_metrics_v2": row.get("performance_metrics_v2"),
                    "duration_ms": raw_duration_ms,
                }

            rec["sniper_metrics"] = sniper_metrics_by_session.get(s["id"])

            # Single field for admin tables: prefer Sniper wpm when set, else Whisper/recording job WPM.
            _rwpm = (rec.get("recording_preview") or {}).get("words_per_minute")
            _swpm = None
            if rec.get("sniper_metrics") and isinstance(rec["sniper_metrics"], dict):
                _swpm = rec["sniper_metrics"].get("wpm")
            _merged_wpm = None
            if _swpm is not None:
                try:
                    _merged_wpm = round(float(_swpm), 1)
                except (TypeError, ValueError):
                    pass
            if _merged_wpm is None and _rwpm is not None:
                try:
                    _merged_wpm = round(float(_rwpm), 1)
                except (TypeError, ValueError):
                    pass
            rec["words_per_minute"] = _merged_wpm
            if isinstance(rec.get("sniper_metrics"), dict) and rec["sniper_metrics"].get("wpm") is None and _merged_wpm is not None:
                rec["sniper_metrics"] = {**rec["sniper_metrics"], "wpm": _merged_wpm}

            # Backward-compat aliases for older admin panels that read flat keys.
            rec["wpm"] = rec.get("words_per_minute")
            filler_total = None
            filler_obj = (rec.get("recording_preview") or {}).get("filler_words_count")
            if isinstance(filler_obj, dict):
                filler_total = filler_obj.get("total")
            elif isinstance(filler_obj, (int, float)):
                filler_total = filler_obj
            rec["filler_words_count"] = filler_total
            rec["duration_seconds"] = None
            duration_ms_val = (rec.get("recording_preview") or {}).get("duration_ms")
            if duration_ms_val is not None:
                try:
                    rec["duration_seconds"] = round(float(duration_ms_val) / 1000.0, 1)
                except (TypeError, ValueError):
                    rec["duration_seconds"] = None
            sm = rec.get("sniper_metrics") if isinstance(rec.get("sniper_metrics"), dict) else {}
            rec["pause_ms"] = sm.get("pause_ms")
            rec["dynamic_db"] = sm.get("dynamic_db")
            rec["pitch_center_st"] = sm.get("pitch_center_st")
            rec["energy_ratio"] = sm.get("energy_ratio")
            _sr = sm.get("student_rating_1_10")
            if _sr is None and s.get("student_self_rating") is not None:
                try:
                    _sr = int(s["student_self_rating"])
                except (TypeError, ValueError):
                    _sr = sm.get("student_rating_1_10")
            rec["student_rating_1_10"] = _sr
            rec["self_rating"] = _sr
            # Skip does not write student_rating_1_10; self_rating_submitted_at is still set on v2_sessions.
            _sub_at = s.get("self_rating_submitted_at")
            rec["self_rating_skipped"] = bool(_sub_at) and _sr is None
            # Single string for tables that only show one cell (optional for admin UI).
            if _sr is not None:
                try:
                    rec["self_rating_label"] = str(int(_sr))
                except (TypeError, ValueError):
                    rec["self_rating_label"] = str(_sr)
            elif rec["self_rating_skipped"]:
                rec["self_rating_label"] = "Skipped"
            else:
                rec["self_rating_label"] = None

            report_text = None
            if s.get("report_id"):
                r = self.client.table("v2_reports").select("report_text").eq("id", s["report_id"]).execute()
                if r.data:
                    report_text = r.data[0].get("report_text") or ""
            if report_text is None and s.get("id"):
                try:
                    r2 = self.client.table("v2_reports").select("report_text").eq("session_v2_id", s["id"]).order("created_at", desc=True).limit(1).execute()
                    if r2.data:
                        report_text = (r2.data[0].get("report_text") or "").strip() or None
                except Exception:
                    pass
            if report_text is None:
                report_text = context_long_by_id.get(s["id"])
            rec["report_delivered"] = bool((report_text or "").strip())
            if report_text:
                rec["report_preview"] = {"report_text_preview": (report_text or "").strip()}
            out.append(rec)
        return out

    def v2_get_last_report_for_user(self, user_id: str):
        """Get full text of the most recent completed report for admin 'Last Report' section. Only considers sessions with status='completed'. Returns { report_text, report_preview } or None."""
        result = (
            self.client.table("v2_sessions")
            .select("id, report_id, completed_at, student_completion_email_sent_at")
            .eq("user_id", user_id)
            .eq("status", "completed")
            .order("completed_at", desc=True)
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
        return {
            "report_text": report_text,
            "report_preview": (report_text or "")[:500],
            "student_completion_email_sent_at": s.get("student_completion_email_sent_at"),
            "report_delivered": True,
        }

    def v2_get_speaker_profile(self, user_id: str):
        """Get speaker profile for admin panel (main_goal, motivation, coach_notes, etc.)."""
        result = self.client.table("v2_speaker_profiles").select("*").eq("user_id", user_id).execute()
        rows = result.data or []
        for row in rows:
            if str(row.get("user_id") or "") == str(user_id):
                return row
        return None

    def v2_upsert_speaker_profile(self, user_id: str, data: dict):
        """Create or update speaker profile. Keys: main_goal, motivation, strong_points, weak_points, charismatic_traits, hobbies_interests, personality_type, coach_notes."""
        allowed = {"main_goal", "motivation", "strong_points", "weak_points", "charismatic_traits", "hobbies_interests", "personality_type", "coach_notes"}
        payload = {k: v for k, v in data.items() if k in allowed}
        payload["user_id"] = user_id
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        result = self.client.table("v2_speaker_profiles").upsert(payload, on_conflict="user_id").execute()
        rows = result.data or []
        for row in rows:
            if str(row.get("user_id") or "") == str(user_id):
                return row
        return self.v2_get_speaker_profile(user_id)

    def get_user_name_from_auth(self, user_id: str) -> str | None:
        """Fetch user display name from Supabase Auth user_metadata. Returns None if not found or on error."""
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
            if resp.status_code == 200:
                data = resp.json()
                meta = data.get("user_metadata") or {}
                raw = (
                    meta.get("full_name")
                    or meta.get("name")
                    or meta.get("display_name")
                    or ""
                )
                cleaned = str(raw).strip()
                return cleaned if cleaned else None
            return None
        except Exception:
            return None

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
            if resp.status_code == 200:
                data = resp.json()
                email = data.get("email") or (data.get("user", {}).get("email"))
                if email and str(email).strip():
                    return str(email).strip()
            # Fallback: some Supabase setups don't expose /admin/users/{id}; use list endpoint and find by id.
            base = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users"
            for page in range(1, 11):
                list_resp = httpx.get(
                    base,
                    params={"per_page": 1000, "page": page},
                    headers={
                        "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
                        "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
                    },
                    timeout=10,
                )
                if list_resp.status_code != 200:
                    break
                payload = list_resp.json()
                users = payload.get("users") or (payload.get("data") or {}).get("users") or []
                if not users:
                    break
                for u in users:
                    if str(u.get("id") or "") == str(user_id):
                        found = (u.get("email") or (u.get("user_metadata") or {}).get("email") or "").strip()
                        return found or None
                if len(users) < 1000:
                    break
            return None
        except Exception:
            return None

    def v2_delete_student(self, user_id: str) -> dict:
        """
        Delete a student and related admin-managed rows.
        Returns a dict with per-step status for observability.
        """
        result = {
            "user_id": user_id,
            "details_deleted": False,
            "overrides_deleted": False,
            "speaker_profile_deleted": False,
            "student_tasks_deleted": False,
            "post_questions_deleted": False,
            "sessions_deleted": False,
            "auth_user_deleted": False,
        }

        # Best-effort cleanup in public schema first.
        self.client.table("v2_student_details").delete().eq("user_id", user_id).execute()
        result["details_deleted"] = True
        self.client.table("v2_student_overrides").delete().eq("user_id", user_id).execute()
        result["overrides_deleted"] = True
        self.client.table("v2_speaker_profiles").delete().eq("user_id", user_id).execute()
        result["speaker_profile_deleted"] = True
        self.client.table("tasks").delete().eq("user_id", user_id).execute()
        result["student_tasks_deleted"] = True
        self.client.table("v2_student_post_recording_questions").delete().eq("user_id", user_id).execute()
        result["post_questions_deleted"] = True
        self.client.table("v2_sessions").delete().eq("user_id", user_id).execute()
        result["sessions_deleted"] = True

        # Remove user from Supabase Auth as final step.
        import httpx
        url = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{user_id}"
        resp = httpx.delete(
            url,
            headers={
                "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
                "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
            },
            timeout=10,
        )
        if resp.status_code in (200, 204):
            result["auth_user_deleted"] = True
            return result
        if resp.status_code == 404:
            # User already absent in auth; treat delete as idempotent success.
            result["auth_user_deleted"] = True
            return result
        raise RuntimeError(f"auth_delete_failed status={resp.status_code} body={resp.text[:300]}")

    # ---------- Coach AI Conversations ----------

    def get_coach_ai_conversation(self, user_id: str) -> dict | None:
        """Get the coach AI conversation history for a student."""
        try:
            result = (
                self.client.table("coach_ai_conversations")
                .select("*")
                .eq("user_id", user_id)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning("get_coach_ai_conversation failed for %s: %s", user_id, e)
            return None

    def upsert_coach_ai_conversation(self, user_id: str, messages: list) -> dict | None:
        """Save/update the coach AI conversation history for a student.
        messages: list of {role, content, timestamp} dicts."""
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "user_id": user_id,
            "messages": json.dumps(messages) if isinstance(messages, list) else messages,
            "updated_at": now,
        }
        try:
            result = (
                self.client.table("coach_ai_conversations")
                .upsert(payload, on_conflict="user_id")
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error("upsert_coach_ai_conversation failed for %s: %s", user_id, e)
            raise

    def clear_coach_ai_conversation(self, user_id: str) -> bool:
        """Clear (delete) the coach AI conversation for a student."""
        try:
            self.client.table("coach_ai_conversations").delete().eq("user_id", user_id).execute()
            return True
        except Exception as e:
            logger.warning("clear_coach_ai_conversation failed for %s: %s", user_id, e)
            return False

    # ---------- Admin Copilot Inbox ----------

    def upsert_student_profile_fields(self, user_id: str, fields: Dict[str, Any]) -> dict:
        payload = {"user_id": user_id, "updated_at": datetime.now(timezone.utc).isoformat()}
        payload.update(fields or {})
        try:
            res = (
                self.client.table(self._student_profile_table)
                .upsert(payload, on_conflict="user_id")
                .execute()
            )
            return res.data[0] if res.data else payload
        except Exception as e:
            if self._is_relation_missing_error(e):
                res = (
                    self.client.table(self._legacy_student_profile_table)
                    .upsert(payload, on_conflict="user_id")
                    .execute()
                )
                return res.data[0] if res.data else payload
            raise

    def list_recent_student_ids(self, limit: int = 500) -> List[str]:
        try:
            rows = (
                self.client.table("v2_sessions")
                .select("user_id, created_at")
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            ids: List[str] = []
            seen = set()
            for row in (rows.data or []):
                uid = str(row.get("user_id") or "").strip()
                if not uid or uid in seen:
                    continue
                seen.add(uid)
                ids.append(uid)
            return ids
        except Exception:
            return []

    def create_admin_annotation_event(
        self,
        *,
        user_id: str,
        session_id: Optional[str],
        section_type: str,
        field_name: str,
        ai_original_text: Optional[str],
        coach_final_text: Optional[str],
        reason_chip: Optional[str],
        custom_reason: Optional[str],
        created_by: str,
        draft_id: Optional[str] = None,
        previous_value_hash: Optional[str] = None,
        new_value_hash: Optional[str] = None,
    ) -> None:
        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "section_type": section_type,
            "field_name": field_name,
            "ai_original_text": ai_original_text,
            "coach_final_text": coach_final_text,
            "reason_chip": reason_chip,
            "custom_reason": custom_reason,
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "draft_id": draft_id,
            "previous_value_hash": previous_value_hash,
            "new_value_hash": new_value_hash,
        }
        try:
            self.client.table("admin_annotation_events").insert(payload).execute()
        except Exception:
            # Backward compatibility for DBs without hash/draft_id columns.
            payload.pop("draft_id", None)
            payload.pop("previous_value_hash", None)
            payload.pop("new_value_hash", None)
            self.client.table("admin_annotation_events").insert(payload).execute()

    def insert_admin_student_send_drafts(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not rows:
            return []
        res = self.client.table("admin_student_send_drafts").insert(rows).execute()
        return res.data or []

    def archive_copilot_queue_row(self, user_id: str, session_id: str, admin_user_id: Optional[str] = None) -> bool:
        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "archived_at": datetime.now(timezone.utc).isoformat(),
            "archived_by": admin_user_id,
        }
        self.client.table("admin_copilot_queue_archives").upsert(
            payload, on_conflict="user_id,session_id"
        ).execute()
        return True

    def unarchive_copilot_queue_row(self, user_id: str, session_id: str) -> bool:
        (
            self.client.table("admin_copilot_queue_archives")
            .delete()
            .eq("user_id", user_id)
            .eq("session_id", session_id)
            .execute()
        )
        return True

    def get_copilot_queue_archived_pairs(self) -> set:
        """Return set of (user_id, session_id) string tuples that are archived."""
        try:
            res = (
                self.client.table("admin_copilot_queue_archives")
                .select("user_id, session_id")
                .execute()
            )
            return {(str(r["user_id"]), str(r["session_id"])) for r in (res.data or [])}
        except Exception:
            return set()

    def list_admin_student_send_drafts(self, *, status: Optional[str] = None) -> List[Dict[str, Any]]:
        q = (
            self.client.table("admin_student_send_drafts")
            .select("*")
            .order("updated_at", desc=True)
            .order("created_at", desc=True)
        )
        if status:
            q = q.eq("status", status)
        res = q.execute()
        return res.data or []

    def get_admin_student_send_draft(self, draft_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        res = (
            self.client.table("admin_student_send_drafts")
            .select("*")
            .eq("id", draft_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None

    def mark_admin_student_send_draft_sent(
        self,
        draft_id: str,
        user_id: str,
        approved_by: str,
        *,
        delivery_email_soft_failed: bool = False,
        draft_payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        payload: Dict[str, Any] = {
            "status": "sent",
            "approved_by": approved_by,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "delivery_lifecycle": "delivered",
            "delivery_email_soft_failed": bool(delivery_email_soft_failed),
            "delivery_failed_step": None,
        }
        if draft_payload is not None:
            payload["draft_payload"] = draft_payload
        res = (
            self.client.table("admin_student_send_drafts")
            .update(payload)
            .eq("id", draft_id)
            .eq("user_id", user_id)
            .execute()
        )
        return res.data[0] if res.data else None

    def queue_admin_student_send_draft_pipeline(
        self,
        *,
        draft_id: str,
        user_id: str,
        pipeline_job_id: str,
        script_mode: str,
        script_manifest: Dict[str, Any],
        created_by: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "pipeline_job_id": pipeline_job_id,
            "pipeline_status": "queued",
            "pipeline_error": None,
            "pipeline_started_at": None,
            "pipeline_finished_at": None,
            "script_mode": script_mode,
            "script_manifest": script_manifest or {},
            "updated_at": now,
            "delivery_lifecycle": "delivering",
            "delivery_started_at": now,
            "delivery_failed_step": None,
            "delivery_email_soft_failed": False,
        }
        if created_by:
            payload["approved_by"] = created_by
        res = (
            self.client.table("admin_student_send_drafts")
            .update(payload)
            .eq("id", draft_id)
            .eq("user_id", user_id)
            .execute()
        )
        return res.data[0] if res.data else None

    def get_admin_student_send_draft_by_pipeline_job(self, pipeline_job_id: str) -> Optional[Dict[str, Any]]:
        res = (
            self.client.table("admin_student_send_drafts")
            .select("*")
            .eq("pipeline_job_id", pipeline_job_id)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None

    def update_admin_student_send_draft_pipeline_status(
        self,
        *,
        draft_id: str,
        user_id: str,
        status: str,
        error: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        payload: Dict[str, Any] = {
            "pipeline_status": status,
            "pipeline_error": (error or None),
            "updated_at": now,
        }
        if status == "failed":
            payload["delivery_lifecycle"] = "failed"
            payload["delivery_failed_step"] = "render"
        elif status in ("queued", "running_tts", "running_video", "uploading"):
            payload["delivery_lifecycle"] = "delivering"
        if status in ("running_tts", "running_video", "uploading"):
            payload["pipeline_started_at"] = now
            payload["pipeline_finished_at"] = None
        elif status in ("sent", "failed"):
            payload["pipeline_finished_at"] = now
        res = (
            self.client.table("admin_student_send_drafts")
            .update(payload)
            .eq("id", draft_id)
            .eq("user_id", user_id)
            .execute()
        )
        return res.data[0] if res.data else None

    def mark_admin_student_send_draft_pipeline_sent(
        self,
        *,
        draft_id: str,
        user_id: str,
        approved_by: str,
        feedback_video_storage_path: str,
        script_manifest: Optional[Dict[str, Any]] = None,
        delivery_email_soft_failed: bool = False,
        draft_payload: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        payload: Dict[str, Any] = {
            "status": "sent",
            "pipeline_status": "sent",
            "pipeline_error": None,
            "feedback_video_storage_path": feedback_video_storage_path,
            "approved_by": approved_by,
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "pipeline_finished_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "delivery_lifecycle": "delivered",
            "delivery_email_soft_failed": bool(delivery_email_soft_failed),
            "delivery_failed_step": None,
        }
        if script_manifest is not None:
            payload["script_manifest"] = script_manifest
        if draft_payload is not None:
            payload["draft_payload"] = draft_payload
        res = (
            self.client.table("admin_student_send_drafts")
            .update(payload)
            .eq("id", draft_id)
            .eq("user_id", user_id)
            .execute()
        )
        return res.data[0] if res.data else None

    def try_claim_admin_send_draft_delivery_in_progress(self, draft_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Atomically move lifecycle idle|failed → delivering. Returns row if claim succeeded."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            res = (
                self.client.table("admin_student_send_drafts")
                .update(
                    {
                        "delivery_lifecycle": "delivering",
                        "delivery_started_at": now,
                        "delivery_failed_step": None,
                        "updated_at": now,
                    }
                )
                .eq("id", draft_id)
                .eq("user_id", user_id)
                .in_("delivery_lifecycle", ["idle", "failed"])
                .execute()
            )
            return res.data[0] if res.data else None
        except Exception as e:
            logger.warning("try_claim_admin_send_draft_delivery_in_progress: %s", e)
            return None

    def reset_admin_send_draft_delivery_idle(self, draft_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        res = (
            self.client.table("admin_student_send_drafts")
            .update(
                {
                    "delivery_lifecycle": "idle",
                    "delivery_started_at": None,
                    "updated_at": now,
                }
            )
            .eq("id", draft_id)
            .eq("user_id", user_id)
            .execute()
        )
        return res.data[0] if res.data else None

    def clear_admin_send_draft_email_soft_failure(self, draft_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        res = (
            self.client.table("admin_student_send_drafts")
            .update(
                {
                    "delivery_email_soft_failed": False,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("id", draft_id)
            .eq("user_id", user_id)
            .execute()
        )
        return res.data[0] if res.data else None

    def create_admin_uploaded_reference_video(
        self,
        *,
        draft_id: Optional[str],
        user_id: str,
        session_id: Optional[str],
        storage_path: str,
        source_video_url: Optional[str],
        transcript_text: Optional[str],
        feature_metadata: Optional[Dict[str, Any]],
        tags: Optional[List[str]],
        is_universal: bool,
        created_by: Optional[str],
        transcription_status: Optional[str] = None,
        transcription_error: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        clean_title = (title or "").strip() or None
        fm = dict(feature_metadata or {})
        # Mirror fields that may be missing at top-level into feature_metadata.
        # Some prod DBs pre-date migrations adding title/transcription_status/transcription_error.
        if clean_title and "title" not in fm:
            fm["title"] = clean_title
        if transcription_status and "transcription_status" not in fm:
            fm["transcription_status"] = transcription_status
        if transcription_error and "transcription_error" not in fm:
            fm["transcription_error"] = transcription_error
        payload = {
            "draft_id": draft_id,
            "user_id": user_id,
            "session_id": session_id,
            "storage_path": storage_path,
            "source_video_url": source_video_url,
            "transcript_text": transcript_text,
            "feature_metadata": fm,
            "tags": tags or [],
            "is_universal": bool(is_universal),
            "created_by": created_by,
            "transcription_status": (transcription_status or "pending"),
            "transcription_error": transcription_error,
            "title": clean_title,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        # Columns that may be absent from older prod schemas. Retry without them
        # when PostgREST reports PGRST204 "could not find column" for any of these.
        _OPTIONAL_COLS = ("title", "transcription_status", "transcription_error", "updated_at")
        import re as _re
        res = None
        for _attempt in range(len(_OPTIONAL_COLS) + 1):
            try:
                res = self.client.table("admin_uploaded_reference_videos").insert(payload).execute()
                break
            except Exception as e:
                msg = str(e)
                if "PGRST204" not in msg and "schema cache" not in msg:
                    raise
                dropped = False
                for col in _OPTIONAL_COLS:
                    if col in payload and f"'{col}'" in msg:
                        payload.pop(col, None)
                        dropped = True
                        break
                if not dropped:
                    m = _re.search(r"'([A-Za-z_][A-Za-z0-9_]*)'", msg)
                    if m and m.group(1) in payload:
                        payload.pop(m.group(1), None)
                        dropped = True
                if not dropped:
                    raise
        return res.data[0] if (res and res.data) else None

    def list_admin_uploaded_reference_videos_for_training(
        self,
        *,
        since_iso: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        q = (
            self.client.table("admin_uploaded_reference_videos")
            .select("*")
            .eq("is_active", True)
            .order("created_at", desc=False)
            .limit(max(1, min(5000, int(limit))))
        )
        if since_iso:
            q = q.gt("created_at", since_iso)
        res = q.execute()
        return res.data or []

    def list_reference_transcripts_for_copilot(
        self,
        *,
        user_id: str,
        limit: int = 6,
    ) -> List[Dict[str, Any]]:
        cap = max(1, min(50, int(limit)))
        out: List[Dict[str, Any]] = []
        seen: set[str] = set()
        try:
            user_rows = (
                self.client.table("admin_uploaded_reference_videos")
                .select("*")
                .eq("is_active", True)
                .eq("user_id", user_id)
                .eq("transcription_status", "done")
                .order("created_at", desc=True)
                .limit(cap)
                .execute()
            ).data or []
        except Exception:
            user_rows = []
        try:
            universal_rows = (
                self.client.table("admin_uploaded_reference_videos")
                .select("*")
                .eq("is_active", True)
                .eq("is_universal", True)
                .eq("transcription_status", "done")
                .order("created_at", desc=True)
                .limit(cap)
                .execute()
            ).data or []
        except Exception:
            universal_rows = []

        for row in (user_rows + universal_rows):
            rid = str(row.get("id") or "").strip()
            if not rid or rid in seen:
                continue
            transcript = (row.get("transcript_text") or "").strip()
            if not transcript:
                continue
            seen.add(rid)
            out.append(row)
            if len(out) >= cap:
                break
        return out

    def list_admin_uploaded_reference_videos(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        is_active: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        q = (
            self.client.table("admin_uploaded_reference_videos")
            .select("*")
            .order("created_at", desc=True)
            .range(max(0, int(offset)), max(0, int(offset)) + max(1, min(500, int(limit))) - 1)
        )
        if is_active is not None:
            q = q.eq("is_active", bool(is_active))
        res = q.execute()
        return res.data or []

    def get_latest_universal_welcome_video(self) -> Optional[Dict[str, Any]]:
        """Return the most recent reference video flagged is_universal=true.

        Used as a fallback "welcome video" on the student's step-0 screen when
        the coach has not yet sent a personal assignment. Admins mark a video
        as universal by checking the "Universal video" box in Training Studio
        on upload (body field `is_universal_video=true`).

        Returns None if no universal video exists or the table is missing.
        """
        try:
            res = (
                self.client.table("admin_uploaded_reference_videos")
                .select("*")
                .eq("is_universal", True)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_latest_universal_welcome_video: %s", e)
            return None

    def find_duplicate_admin_uploaded_reference_video(
        self,
        user_id: str,
        *,
        original_filename: str,
        draft_id: Optional[str] = None,
        session_id: Optional[str] = None,
        within_minutes: int = 60,
    ) -> Optional[Dict[str, Any]]:
        """Return an existing reference video row that looks like a duplicate of
        the one the admin is about to upload. Used to short-circuit re-uploads
        of the same file for the same student/draft within *within_minutes*.

        Match rules (all must hold):
          - same user_id
          - same original_filename (stored in feature_metadata.original_filename
            AND/OR the tail of storage_path)
          - created within the last *within_minutes*
          - same draft_id if provided, else same session_id if provided
        """
        try:
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max(1, within_minutes))).isoformat()
            q = (
                self.client.table("admin_uploaded_reference_videos")
                .select("*")
                .eq("user_id", user_id)
                .gte("created_at", cutoff)
                .order("created_at", desc=True)
                .limit(20)
            )
            if draft_id:
                q = q.eq("draft_id", draft_id)
            elif session_id:
                q = q.eq("session_id", session_id)
            res = q.execute()
            rows = res.data or []
        except Exception as e:
            logger.warning("find_duplicate_admin_uploaded_reference_video: %s", e)
            return None
        needle = (original_filename or "").strip()
        if not needle:
            return None
        for row in rows:
            fm = row.get("feature_metadata") or {}
            fm_name = (fm.get("original_filename") or "").strip() if isinstance(fm, dict) else ""
            sp_tail = os.path.basename((row.get("storage_path") or "").strip())
            # storage_path tail is "{uuid}{ext}", so compare extensions only there.
            if fm_name and fm_name == needle:
                return row
            if sp_tail and os.path.splitext(sp_tail)[1].lower() == os.path.splitext(needle)[1].lower() and fm_name == needle:
                return row
        return None

    def get_latest_admin_uploaded_reference_video_for_user(
        self,
        user_id: str,
        *,
        session_id: Optional[str] = None,
        draft_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Most-recent admin-uploaded reference video for this student.

        Preference order: (draft_id match) → (session_id match) → any row for user.
        Used as a fallback on "Approve & Send" when the draft has no explicit
        video attached — so the Training-Studio upload still surfaces on the
        student's step-0 screen.
        """
        def _query(filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            try:
                q = self.client.table("admin_uploaded_reference_videos").select("*")
                for k, v in filters.items():
                    q = q.eq(k, v)
                q = q.order("created_at", desc=True).limit(1)
                res = q.execute()
                return res.data[0] if res.data else None
            except Exception as e:
                logger.warning("get_latest_admin_uploaded_reference_video_for_user filter=%s: %s", filters, e)
                return None
        if draft_id:
            hit = _query({"user_id": user_id, "draft_id": draft_id})
            if hit:
                return hit
        if session_id:
            hit = _query({"user_id": user_id, "session_id": session_id})
            if hit:
                return hit
        return _query({"user_id": user_id})

    def get_admin_uploaded_reference_video(self, reference_video_id: str) -> Optional[Dict[str, Any]]:
        res = (
            self.client.table("admin_uploaded_reference_videos")
            .select("*")
            .eq("id", reference_video_id)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None

    def update_admin_uploaded_reference_video(
        self,
        reference_video_id: str,
        fields: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        payload = dict(fields or {})
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        res = (
            self.client.table("admin_uploaded_reference_videos")
            .update(payload)
            .eq("id", reference_video_id)
            .execute()
        )
        return res.data[0] if res.data else None

    def create_copilot_reference_upload_job(
        self,
        *,
        created_by: Optional[str],
        student_user_id: str,
    ) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        payload: Dict[str, Any] = {
            "student_user_id": student_user_id,
            "stage": "queued",
            "percent": 0,
            "message": "Queued",
            "updated_at": now,
        }
        if created_by:
            payload["created_by"] = created_by
        res = self.client.table("copilot_reference_upload_jobs").insert(payload).execute()
        return res.data[0] if res.data else None

    def update_copilot_reference_upload_job(
        self,
        job_id: str,
        fields: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        payload = dict(fields or {})
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        res = (
            self.client.table("copilot_reference_upload_jobs")
            .update(payload)
            .eq("id", job_id)
            .execute()
        )
        return res.data[0] if res.data else None

    def get_copilot_reference_upload_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        res = (
            self.client.table("copilot_reference_upload_jobs")
            .select("*")
            .eq("id", job_id)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None

    def mark_stale_upload_jobs_failed(self, stale_minutes: int = 30) -> int:
        """Mark upload jobs stuck in a non-terminal state as failed.

        Should be called on app startup to recover from worker restarts
        that killed in-flight daemon threads.  Returns count of affected rows.
        """
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max(5, stale_minutes))).isoformat()
        try:
            res = (
                self.client.table("copilot_reference_upload_jobs")
                .select("id, stage, updated_at")
                .lt("updated_at", cutoff)
                .neq("stage", "completed")
                .neq("stage", "failed")
                .limit(200)
                .execute()
            )
            stale = res.data or []
            for row in stale:
                self.update_copilot_reference_upload_job(
                    str(row["id"]),
                    {
                        "stage": "failed",
                        "error": "Server restarted while job was in progress",
                        "message": "Interrupted — please retry the upload",
                    },
                )
            return len(stale)
        except Exception as e:
            logger.warning("mark_stale_upload_jobs_failed: %s", e)
            return 0

    def create_model_training_run(
        self,
        *,
        run_type: str,
        status: str,
        input_count: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
        created_by: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "run_type": run_type,
            "status": status,
            "input_count": max(0, int(input_count)),
            "metadata": metadata or {},
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        }
        if status == "running":
            payload["started_at"] = now
        if status in ("completed", "failed", "skipped"):
            payload["finished_at"] = now
        res = self.client.table("model_training_runs").insert(payload).execute()
        return res.data[0] if res.data else None

    def update_model_training_run(
        self,
        run_id: str,
        *,
        status: str,
        input_count: Optional[int] = None,
        output_artifact_ref: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        payload: Dict[str, Any] = {"status": status, "updated_at": now}
        if status == "running":
            payload["started_at"] = now
            payload["finished_at"] = None
        if status in ("completed", "failed", "skipped"):
            payload["finished_at"] = now
        if input_count is not None:
            payload["input_count"] = max(0, int(input_count))
        if output_artifact_ref is not None:
            payload["output_artifact_ref"] = output_artifact_ref
        if metadata is not None:
            payload["metadata"] = metadata
        if error is not None:
            payload["error"] = error
        res = self.client.table("model_training_runs").update(payload).eq("id", run_id).execute()
        return res.data[0] if res.data else None

    def get_latest_model_training_run(self, run_type: str) -> Optional[Dict[str, Any]]:
        res = (
            self.client.table("model_training_runs")
            .select("*")
            .eq("run_type", run_type)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None

    # ---------- Runtime config ----------

    def get_runtime_config(self, key: str) -> Optional[str]:
        try:
            res = (
                self.client.table("runtime_config")
                .select("value")
                .eq("key", key)
                .limit(1)
                .execute()
            )
            if not res.data:
                return None
            value = res.data[0].get("value")
            if value is None:
                return None
            text = str(value).strip()
            return text or None
        except Exception as e:
            if self._is_relation_missing_error(e):
                return None
            logger.warning("get_runtime_config failed for key=%s: %s", key, e)
            return None

    def upsert_runtime_config(
        self,
        *,
        key: str,
        value: str,
        updated_by: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        payload = {
            "key": key,
            "value": value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": updated_by,
            "metadata": metadata or {},
        }
        try:
            res = (
                self.client.table("runtime_config")
                .upsert(payload, on_conflict="key")
                .execute()
            )
            return res.data[0] if res.data else payload
        except Exception as e:
            if self._is_relation_missing_error(e):
                logger.warning("runtime_config table missing; run migrations/add_runtime_model_config.sql")
                return None
            raise

    def v2_get_last_completed_session_full(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Latest completed homework session row (wide select) for copilot / admin seeding."""
        try:
            res = (
                self.client.table("v2_sessions")
                .select("*")
                .eq("user_id", user_id)
                .eq("status", "completed")
                .order("completed_at", desc=True)
                .limit(1)
                .execute()
            )
            return res.data[0] if res.data else None
        except Exception as e:
            logger.warning("v2_get_last_completed_session_full failed for %s: %s", user_id, e)
            return None

    def v2_user_has_pending_copilot_draft(self, user_id: str) -> bool:
        try:
            r = (
                self.client.table("admin_student_send_drafts")
                .select("id")
                .eq("user_id", user_id)
                .eq("status", "pending")
                .limit(1)
                .execute()
            )
            return bool(r.data)
        except Exception:
            return False

    def get_auth_user_id_by_email(self, email: str) -> Optional[str]:
        """Resolve Supabase auth user UUID from email (admin API list). Case-insensitive match."""
        needle = (email or "").strip().lower()
        if not needle or "@" not in needle:
            return None
        try:
            import httpx

            base = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users"
            page = 1
            per_page = 1000
            while page <= 50:
                resp = httpx.get(
                    base,
                    params={"per_page": per_page, "page": page},
                    headers={
                        "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
                        "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
                    },
                    timeout=15,
                )
                if resp.status_code != 200:
                    return None
                data = resp.json()
                users = data.get("users") or (data.get("data") or {}).get("users") or []
                if not users:
                    return None
                for u in users:
                    em = (u.get("email") or "").strip().lower()
                    if em == needle:
                        uid = u.get("id")
                        return str(uid).strip() if uid else None
                if len(users) < per_page:
                    return None
                page += 1
            return None
        except Exception:
            return None

    def v2_list_all_auth_user_ids(self, cap: int = 2000) -> List[str]:
        """Paginate GoTrue admin users; return ids (up to cap). Same pool as admin student list."""
        try:
            import httpx

            base = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users"
            out: List[str] = []
            seen: set[str] = set()
            page = 1
            per_page = min(1000, max(1, cap))
            while len(out) < cap:
                resp = httpx.get(
                    base,
                    params={"per_page": per_page, "page": page},
                    headers={
                        "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
                        "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
                    },
                    timeout=30,
                )
                if resp.status_code != 200:
                    logger.warning(
                        "v2_list_all_auth_user_ids: auth list page %s failed: %s %s",
                        page,
                        resp.status_code,
                        resp.text[:200],
                    )
                    break
                data = resp.json()
                users = data.get("users") or (data.get("data") or {}).get("users") or []
                if not users:
                    break
                for u in users:
                    uid = u.get("id")
                    if not uid or uid in seen:
                        continue
                    seen.add(uid)
                    out.append(str(uid))
                    if len(out) >= cap:
                        break
                if len(users) < per_page:
                    break
                page += 1
            return out
        except Exception as e:
            logger.warning("v2_list_all_auth_user_ids: %s", e)
            return []

    def get_funnel_config(self, key: str) -> dict | None:
        """Get a funnel configuration value by key."""
        try:
            result = (
                self.client.table("funnel_config")
                .select("id, key, value, updated_at")
                .eq("key", key)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.warning(f"get_funnel_config failed: {e}")
            return None

    def set_funnel_config(self, key: str, value: str | None) -> dict:
        """Set or update a funnel configuration value by key (upsert)."""
        try:
            result = (
                self.client.table("funnel_config")
                .upsert({"key": key, "value": value})
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return {"key": key, "value": value}
        except Exception as e:
            logger.error(f"set_funnel_config failed: {e}")
            return {"key": key, "value": value}

    def create_charisma_snippet(
        self,
        session_id: str,
        user_id: str,
        recording_id: str,
        start_offset_ms: int,
        duration_ms: int,
        audio_segment_path: str,
        metrics: dict | None = None,
    ) -> dict | None:
        """Create a new charisma snippet record (unlabeled by default).

        Args:
            metrics: Optional JSONB dict of pre-computed acoustic metrics
                     (wpm, pause_ms, dynamic_db, emphasis_per_min, energy_ratio,
                      pitch_center_st, pitch_frame_count, voiced_duration_sec).
        """
        try:
            payload = {
                "session_id": session_id,
                "user_id": user_id,
                "recording_id": recording_id,
                "start_offset_ms": start_offset_ms,
                "duration_ms": duration_ms,
                "audio_segment_path": audio_segment_path,
                "snippet_type": "unlabeled",
            }
            if metrics:
                payload["metrics"] = metrics
            result = (
                self.client.table("charisma_snippets")
                .insert(payload)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"create_charisma_snippet failed: {e}")
            return None

    def get_snippets_by_session(self, session_id: str) -> List[dict]:
        """Get all snippets for a session, ordered by start time."""
        try:
            result = (
                self.client.table("charisma_snippets")
                .select("*")
                .eq("session_id", session_id)
                .order("start_offset_ms", desc=False)
                .execute()
            )
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"get_snippets_by_session failed: {e}")
            return []

    def get_snippets_by_user(self, user_id: str, limit: int = 100, offset: int = 0) -> List[dict]:
        """Get all snippets for a user, paginated, ordered by creation date (newest first)."""
        try:
            result = (
                self.client.table("charisma_snippets")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(limit)
                .offset(offset)
                .execute()
            )
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"get_snippets_by_user failed: {e}")
            return []

    def get_snippets_with_comments_by_session(self, session_id: str) -> List[dict]:
        """Get only snippets that have admin comments (used for /results page)."""
        try:
            result = (
                self.client.table("charisma_snippets")
                .select("*")
                .eq("session_id", session_id)
                .not_("admin_comment", "is", None)
                .order("start_offset_ms", desc=False)
                .execute()
            )
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"get_snippets_with_comments_by_session failed: {e}")
            return []

    def update_snippet_comment(
        self,
        snippet_id: str,
        admin_comment: str | None,
        snippet_type: str,
        admin_user_id: str | None,
    ) -> dict | None:
        """Update a snippet's comment, type, and admin user."""
        try:
            result = (
                self.client.table("charisma_snippets")
                .update({
                    "admin_comment": admin_comment,
                    "snippet_type": snippet_type,
                    "admin_user_id": admin_user_id,
                })
                .eq("id", snippet_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"update_snippet_comment failed: {e}")
            return None

    def update_snippets_user_id(self, session_id: str, user_id: str) -> int:
        """Update all snippets for a session to have the newly authenticated user_id.

        Called when a guest session is claimed post-signup. Matches rows where
        user_id is NULL or the placeholder UUID used during anonymous interview.
        Returns count of updated rows.
        """
        PLACEHOLDER_UID = "00000000-0000-0000-0000-000000000000"
        total = 0
        try:
            # Match placeholder user_id (from interview flow)
            r1 = (
                self.client.table("charisma_snippets")
                .update({"user_id": user_id})
                .eq("session_id", session_id)
                .eq("user_id", PLACEHOLDER_UID)
                .execute()
            )
            total += len(r1.data) if r1.data else 0
        except Exception as e:
            logger.warning(f"update_snippets_user_id (placeholder): {e}")
        try:
            # Match NULL user_id (from legacy single-upload flow)
            r2 = (
                self.client.table("charisma_snippets")
                .update({"user_id": user_id})
                .eq("session_id", session_id)
                .is_("user_id", None)
                .execute()
            )
            total += len(r2.data) if r2.data else 0
        except Exception:
            pass
        return total

    # ------------------------------------------------------------------
    # Snippet boundary adjustment & per-snippet metrics
    # ------------------------------------------------------------------

    def update_snippet_boundaries(
        self,
        snippet_id: str,
        start_time: float,
        end_time: float,
    ) -> Optional[dict]:
        """Update a snippet's time boundaries (admin +/- 2s adjust).

        Returns the updated snippet row.
        """
        try:
            result = (
                self.client.table("charisma_snippets")
                .update({
                    "start_time": start_time,
                    "end_time": end_time,
                })
                .eq("id", snippet_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"update_snippet_boundaries failed: {e}")
            return None

    def update_snippet_metrics(
        self,
        snippet_id: str,
        wpm: float | None,
        fillers: int | None,
        pause_ms: float | None,
        dynamic_db: float | None,
        pitch_center: float | None,
        energy: float | None,
        metrics_json: dict | None = None,
    ) -> Optional[dict]:
        """Update a snippet's individual acoustic metric columns.

        Also updates the JSONB metrics column for backwards compat.
        """
        try:
            payload: dict = {
                "wpm": wpm,
                "fillers": fillers,
                "pause_ms": pause_ms,
                "dynamic_db": dynamic_db,
                "pitch_center": pitch_center,
                "energy": energy,
            }
            if metrics_json is not None:
                payload["metrics"] = metrics_json
            result = (
                self.client.table("charisma_snippets")
                .update(payload)
                .eq("id", snippet_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"update_snippet_metrics failed: {e}")
            return None

    def skip_snippet(self, snippet_id: str, is_skipped: bool = True) -> Optional[dict]:
        """Mark a snippet as skipped (hidden from user results)."""
        try:
            result = (
                self.client.table("charisma_snippets")
                .update({"is_skipped": is_skipped})
                .eq("id", snippet_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"skip_snippet failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Session-level global metrics & AI alignment
    # ------------------------------------------------------------------

    def update_session_global_metrics(
        self,
        session_id: str,
        global_wpm: float | None,
        global_fillers: int | None,
        global_pause_ms: float | None,
        global_dynamic_db: float | None,
        global_pitch_center: float | None,
        global_energy: float | None,
    ) -> Optional[dict]:
        """Update v2_sessions with aggregated global acoustic metrics."""
        try:
            result = (
                self.client.table("v2_sessions")
                .update({
                    "global_wpm": global_wpm,
                    "global_fillers": global_fillers,
                    "global_pause_ms": global_pause_ms,
                    "global_dynamic_db": global_dynamic_db,
                    "global_pitch_center": global_pitch_center,
                    "global_energy": global_energy,
                })
                .eq("id", session_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"update_session_global_metrics failed: {e}")
            return None

    def update_session_ai_alignment(
        self,
        session_id: str,
        score: float | None,
        comment: str | None,
    ) -> Optional[dict]:
        """Store the LLM's alignment score + comment for a session."""
        try:
            result = (
                self.client.table("v2_sessions")
                .update({
                    "ai_task_alignment_score": score,
                    "ai_task_alignment_comment": comment,
                })
                .eq("id", session_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"update_session_ai_alignment failed: {e}")
            return None

    # ------------------------------------------------------------------
    # User settings (LLM instructions)
    # ------------------------------------------------------------------

    def get_user_settings(self, user_id: str) -> Optional[dict]:
        """Get user_settings row (custom LLM instructions, etc)."""
        try:
            result = (
                self.client.table("user_settings")
                .select("*")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.warning(f"get_user_settings failed: {e}")
            return None

    def upsert_user_settings(self, user_id: str, custom_llm_instructions: str | None) -> Optional[dict]:
        """Create or update user_settings.custom_llm_instructions."""
        try:
            result = (
                self.client.table("user_settings")
                .upsert({
                    "user_id": user_id,
                    "custom_llm_instructions": custom_llm_instructions,
                    "updated_at": "now()",
                })
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"upsert_user_settings failed: {e}")
            return None

    # ------------------------------------------------------------------
    # User timeline (admin: chronological interview view)
    # ------------------------------------------------------------------

    def get_user_interview_timeline(self, user_id: str, session_id: str | None = None) -> List[dict]:
        """Fetch a user's interview snippets in chronological order.

        Returns snippets (with question_text, turn_number, metrics) sorted by
        turn_number. If session_id is provided, filters to that session only.
        """
        try:
            query = (
                self.client.table("charisma_snippets")
                .select("*")
                .eq("user_id", user_id)
            )
            if session_id:
                query = query.eq("session_id", session_id)
            result = query.order("turn_number", desc=False).order("created_at", desc=False).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"get_user_interview_timeline failed: {e}")
            return []

    def get_session_with_global_metrics(self, session_id: str) -> Optional[dict]:
        """Get a session row including global metrics and AI alignment."""
        try:
            result = (
                self.client.table("v2_sessions")
                .select("*")
                .eq("id", session_id)
                .limit(1)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"get_session_with_global_metrics failed: {e}")
            return None

# Singleton instance
db = DatabaseService()
