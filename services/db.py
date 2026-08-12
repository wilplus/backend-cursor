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
from services.snippet_tables import SNIPPETS_TABLE

config = Config()
logger = logging.getLogger(__name__)


# Volatile stamps stripped from Say-It-Stronger cards before they are compared
# and serialized as annotation-event text: model/generated_at ride only the
# auto draft, edited_by_coach rides only the final, and version can differ
# between them — none is content, and any one of them would turn a genuinely
# untouched card into false "corrected" signal.
_SIS_VOLATILE_KEYS = ("model", "generated_at", "version", "edited_by_coach")


def _sis_annotation_text(card: Any) -> Optional[str]:
    """A Say-It-Stronger card as canonical annotation-event text.

    Deterministic (sorted keys) so that draft-vs-final equality — and
    therefore the approved_as_is chip — compares CONTENT, not dict ordering
    or the volatile stamps. None for anything that isn't a dict with content.
    """
    if not isinstance(card, dict):
        return None
    slim = {k: v for k, v in card.items() if k not in _SIS_VOLATILE_KEYS}
    if not slim:
        return None
    try:
        return json.dumps(slim, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return None


# Codes that genuinely mean "the object is not there", and nothing else.
#
#   42P01 undefined_table        42703 undefined_column
#   42883 undefined_function     42P10 is NOT here on purpose: an invalid
#                                column reference / bad ON CONFLICT arbiter
#                                means the object EXISTS and the statement is
#                                wrong, which is a different fix entirely.
#   PGRST205 table not found in the schema cache
#   PGRST204 column not found in the schema cache
#   PGRST202 function not found in the schema cache
#
# The three PGRST codes are cache misses, not absences — the object can be
# perfectly present and the API still cannot see it until
# `NOTIFY pgrst, 'reload schema'`. They belong here because the CALLER's next
# move is the same (make the object visible), but the hint must say so.
_MISSING_OBJECT_CODES = frozenset({
    "42P01", "42703", "42883", "PGRST205", "PGRST204", "PGRST202",
})

_PG_CODE_RE = re.compile(r"\b(PGRST\d{3}|[0-9A-Z]{5})\b")


def _pg_error_code(exc: Any) -> str:
    """The Postgres SQLSTATE or PostgREST code on an exception, or "".

    Supabase raises APIError with a `code` attribute; psycopg2 uses `pgcode`;
    everything else has to be read out of the message. Pure, and never raises
    — an error path that can itself fail is worse than no error path.

    WHY THIS EXISTS: a best-effort writer swallows its failures, so the log
    line is the only account of why a table stopped filling. Matching on
    prose ("does not exist", or worse, the table's own name) turns every
    distinct failure into one wrong sentence — see the 2026-08-12 note in
    record_dimension_evaluations.
    """
    for attr in ("code", "pgcode"):
        v = getattr(exc, attr, None)
        if isinstance(v, str) and v.strip():
            return v.strip()
    try:
        m = _PG_CODE_RE.search(str(exc))
    except Exception:      # pragma: no cover - defensive
        return ""
    return m.group(1) if m else ""


def _free_credit_grant() -> int:
    """The upfront free credit grant (config.WILLAB_FREE_CREDIT_GRANT, 25 for
    the testing phase, env-tunable). Single source of truth for both the lazy
    seed AND every "unseeded user" balance fallback, so they can never drift
    apart (a mismatch would wrongly tell a new user 'insufficient')."""
    try:
        from config import Config
        return int(getattr(Config, "WILLAB_FREE_CREDIT_GRANT", 25) or 25)
    except Exception:
        return 25


class DatabaseService:
    def __init__(self):
        self.client: Client = self._build_supabase_client()
        # Cache missing optional columns discovered at runtime on older schemas.
        self._v2_sessions_missing_columns: set[str] = set()
        self._student_profile_table = "student_profile"
        self._legacy_student_profile_table = "user_sniper_profile"

    def reset_connections(self) -> None:
        """Rebuild the client. MUST be called in a freshly forked child.

        `db = DatabaseService()` runs at IMPORT, so the TLS connection to
        Supabase is established in the parent — worker.py's `_warm_analysis_
        stack()` and its boot sweep both touch the DB before forking. A
        `fork` context then hands that one live socket to every slot, and two
        processes writing into a single TLS session produce exactly what the
        worker logs showed:

            [SSL: SSLV3_ALERT_BAD_RECORD_MAC] sslv3 alert bad record mac
            EOF occurred in violation of protocol
            Server disconnected

        Those are caught and logged as warnings, so the reads simply return
        nothing and the sweep quietly does no work — the same silent-failure
        shape as the telemetry writes. `job_queue.reset_connections()` already
        handles this for Redis and says why; the httpx/TLS half was missed.
        """
        self.client = self._build_supabase_client()

    def _build_supabase_client(self) -> Client:
        """Create the Supabase client.

        Earlier this method tried to force HTTP/1.1 transport via a
        custom httpx.Client passed through ClientOptions(http_client=…)
        — supabase-py 2.7.0+ accepts that kwarg, our pin is 2.6.0, so
        every boot raised TypeError and we fell through to the
        default client anyway. The noisy warning ("ClientOptions
        unexpected keyword argument 'http_client'") was the
        fallback firing on each worker boot — not an actual error.

        Application-level retry in ``_execute_with_retry`` /
        ``_is_transient_postgrest_disconnect`` already handles the
        transient HTTP/2 disconnects that motivated the HTTP/1.1
        transport tweak, so we drop the dead code and let the default
        transport do its thing.
        """
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
        """Return admin context for report generation. V2: no professional_notes tables; minimal dict.

        Note: the legacy V1 admin-instructions field (tied to the
        deleted professional_notes_report_tech table) was removed
        from this stub when the FE killed its corresponding surface
        in commit ed9ed70. The downstream prompt branch in
        services.openai_service was always reading None here, so
        the branch was dead code; both ends were dropped together.
        """
        return {
            "general_notes": None,
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

    def v2_update_session_status_unscoped(self, session_id: str, status: str) -> Optional[dict]:
        """Update v2_sessions.status without user_id scoping (admin/internal usage).

        NOTE: v2_sessions has NO ``updated_at`` column (confirmed against the
        live schema — it has created_at/completed_at/coach_approved_at/... but
        no plain updated_at). Writing it made PostgREST reject the ENTIRE
        update (PGRST204 "could not find the 'updated_at' column"), so the
        status flip silently never landed — and callers
        (lab_send.send_lab_recording_to_coach, session_publish finalize) wrap
        this in try/except, masking the failure. Status-only payload here;
        every other v2_sessions update writes its own fields without
        updated_at too.
        """
        result = (
            self.client.table("v2_sessions")
            .update({"status": status})
            .eq("id", session_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_get_session_by_id(self, session_id: str):
        """Get v2 session by id only (no user filter). For debugging 404: check if session exists and which user_id owns it."""
        return self.v2_get_session(session_id, None)

    def v2_get_charisma_snippet_for_user(self, snippet_id: str, user_id: str) -> Optional[dict]:
        """Fetch a charisma_snippets row, scoped to the authenticated owner."""
        result = (
            self.client.table(SNIPPETS_TABLE)
            .select("*")
            .eq("id", snippet_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_get_results_snippets_for_session(self, session_id: str, user_id: str) -> List[dict]:
        """Snippets for the /results page.

        Owner-scoped, non-skipped, AND require admin_comment to be
        populated. The /results page's whole point is delivering coach
        insight to the student — a snippet without a comment has
        nothing meaningful to render, so we hide it here rather than
        having the frontend skip-render it. Matches what
        get_snippets_with_comments_by_session already does for the
        with_admin_comment counter that powers session-state.
        """
        result = (
            self.client.table(SNIPPETS_TABLE)
            .select("*")
            .eq("session_id", session_id)
            .eq("user_id", user_id)
            .eq("is_skipped", False)
            .not_.is_("admin_comment", "null")
            .order("turn_number", desc=False)
            .order("start_offset_ms", desc=False)
            .execute()
        )
        rows = result.data or []
        # Belt-and-suspenders: whitespace-only admin_comment is treated
        # as no comment (PostgREST's NOT NULL filter doesn't catch this).
        return [r for r in rows if (r.get("admin_comment") or "").strip()]

    def v2_publish_session_results(self, session_id: str) -> Optional[dict]:
        """Set results_published_at on a session (admin publish action).

        This flag tells the user-facing /results page that snippets are ready.
        """
        from datetime import datetime, timezone
        result = (
            self.client.table("v2_sessions")
            .update({"results_published_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", session_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_get_latest_published_session_for_user(self, user_id: str) -> Optional[dict]:
        """Return the most recent session with results_published_at set (for /results landing)."""
        try:
            result = (
                self.client.table("v2_sessions")
                .select("*")
                .eq("user_id", user_id)
                .not_.is_("results_published_at", "null")
                .order("results_published_at", desc=True)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning("v2_get_latest_published_session_for_user failed: %s", e)
            return None

    def v2_get_latest_session_for_user(self, user_id: str) -> Optional[dict]:
        """Return the most recent session for a user (any status, including
        unfinished / unpublished). Used by /v2/user/sessions/current to expose
        the full state machine to the frontend so it can route correctly.
        """
        try:
            result = (
                self.client.table("v2_sessions")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning("v2_get_latest_session_for_user failed: %s", e)
            return None

    def v2_count_session_snippets(self, session_id: str) -> dict:
        """Count snippets for a session, split by review state.

        Returns:
            {
                "total": int,             # all non-skipped snippets
                "with_admin_comment": int # admin has reviewed and written feedback
            }

        The "with_admin_comment" count is what powers the pending_review →
        completed transition in the routing-status endpoint: a session has
        snippets ready to show only when at least one has admin_comment set.

        Implementation note: we fetch the rows and count in Python rather
        than using `select("id", count="exact")`. The supabase-py SDK
        version on the deployed runtime treats the count kwarg differently
        from what the docs suggest and threw
        "'SyncSelectRequestBuilder' object is not callable" on .execute().
        Volume here is tiny (snippets-per-session), so the cost of
        materialising the rows is negligible and the code is bulletproof
        across SDK versions.
        """
        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
                .select("id, admin_comment, is_skipped")
                .eq("session_id", session_id)
                .execute()
            )
            rows = result.data or []
            non_skipped = [r for r in rows if not r.get("is_skipped")]
            total = len(non_skipped)
            with_comment = sum(
                1 for r in non_skipped if r.get("admin_comment")
            )
            return {"total": total, "with_admin_comment": with_comment}
        except Exception as e:
            logger.warning("v2_count_session_snippets failed: %s", e)
            return {"total": 0, "with_admin_comment": 0}

    # ------------------------------------------------------------------
    # Coaching sessions — micro-coaching loop on a single snippet
    # ------------------------------------------------------------------

    def create_coaching_session(
        self,
        user_id: str,
        source_snippet_id: str,
        intent: str,
    ) -> Optional[dict]:
        """Insert one coaching_sessions row in the awareness stage.

        Caller must have already validated:
          - the snippet exists and the user owns it
          - the snippet has admin_comment populated (otherwise there is
            nothing to serve as the awareness "first bubble")
          - intent ∈ {'stress', 'charisma'}

        Returns the inserted row dict, or None on failure.
        """
        try:
            row = {
                "user_id": user_id,
                "source_snippet_id": source_snippet_id,
                "intent": intent,
                "current_stage": "awareness",
            }
            result = (
                self.client.table("coaching_sessions")
                .insert(row)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error("create_coaching_session failed: %s", e)
            return None

    def get_coaching_session(self, coaching_id: str, user_id: str) -> Optional[dict]:
        """Owner-scoped fetch of one coaching session."""
        try:
            result = (
                self.client.table("coaching_sessions")
                .select("*")
                .eq("id", coaching_id)
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning("get_coaching_session failed: %s", e)
            return None

    def append_coaching_message(
        self,
        coaching_id: str,
        role: str,
        content: str,
        *,
        extra: Optional[dict] = None,
    ) -> Optional[dict]:
        """Append one entry to coaching_sessions.messages (JSONB).

        The transcript is an ordered array of:
            { "role": "user" | "assistant" | "system" | "trial_audio",
              "content": <string>, "ts": <iso8601>, **extra }

        Read-modify-write rather than a single jsonb_set RPC because
        Supabase REST doesn't expose `jsonb || jsonb` append cleanly,
        and the call cadence (one turn at a time per user) makes the
        race window negligible. If we ever multiplex coaching turns
        per session this should move to a Postgres function.

        Requires the migration to have added the `messages JSONB`
        column. Without it, PGRST204 surfaces and we return None
        cleanly (the caller swallows so the turn response still ships).
        """
        try:
            existing = (
                self.client.table("coaching_sessions")
                .select("messages")
                .eq("id", coaching_id)
                .limit(1)
                .execute()
            )
            current: list = []
            if existing.data and isinstance(existing.data[0].get("messages"), list):
                current = list(existing.data[0]["messages"])

            entry: dict = {
                "role": role,
                "content": content,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            if extra:
                # extra keys win over defaults so callers can override
                # role/content/ts when they need to (e.g. trial_audio
                # entries carry storage_path instead of content).
                entry.update(extra)
            current.append(entry)

            result = (
                self.client.table("coaching_sessions")
                .update({
                    "messages": current,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", coaching_id)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning(
                "append_coaching_message failed (id=%s, role=%s): %s",
                coaching_id, role, e,
            )
            return None

    def set_coaching_trial_recording(
        self,
        coaching_id: str,
        trial_recording_url: str,
    ) -> Optional[dict]:
        """Persist the trial-phase audio URL on a coaching session.

        Called from /v2/coaching/trial-recording after the user uploads
        their re-performance. Lets admin review the full coaching loop
        — bubbles + trial audio — from one row. We also append a
        trial_audio entry to messages so the transcript order stays
        linear.
        """
        try:
            result = (
                self.client.table("coaching_sessions")
                .update({
                    "trial_recording_url": trial_recording_url,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", coaching_id)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning(
                "set_coaching_trial_recording failed (id=%s): %s",
                coaching_id, e,
            )
            return None

    def update_coaching_stage(
        self,
        coaching_id: str,
        new_stage: str,
        trial_session_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Advance a coaching session's stage. Forward-only (never reverses).

        When new_stage == 'complete', also stamps completed_at and binds
        trial_session_id.
        """
        try:
            payload: dict = {
                "current_stage": new_stage,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if new_stage == "complete":
                payload["completed_at"] = datetime.now(timezone.utc).isoformat()
            if trial_session_id:
                payload["trial_session_id"] = trial_session_id

            result = (
                self.client.table("coaching_sessions")
                .update(payload)
                .eq("id", coaching_id)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error("update_coaching_stage failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # End coaching sessions
    # ------------------------------------------------------------------

    def v2_get_published_sessions_for_user(self, user_id: str) -> List[dict]:
        """All published sessions for a user, newest first.

        Powers the /v2/user/results/me Voice-Journey timeline. Returns an
        empty list when the user has nothing published — the endpoint must
        NEVER fall back to mock data.
        """
        try:
            result = (
                self.client.table("v2_sessions")
                .select("*")
                .eq("user_id", user_id)
                .not_.is_("results_published_at", "null")
                .order("results_published_at", desc=True)
                .execute()
            )
            return result.data or []
        except Exception as e:
            logger.warning("v2_get_published_sessions_for_user failed: %s", e)
            return []


    # ------------------------------------------------------------------
    # Charisma snippets
    # ------------------------------------------------------------------

    def v2_delete_lab_snippets_for_recording(self, recording_id: str) -> int:
        """willab re-cut (UX Wave 3 BE-6): delete the auto-cut Lab snippets for
        a recording so process_lab_recording can re-insert a fresh set. willab
        snippets are created via create_charisma_snippet with source_type NULL
        (snippet_type 'unlabeled'), so this targets EXACTLY those.

        THE `source_type IS NULL` FILTER STAYS EVEN THOUGH THE ML GENERATOR IS
        GONE (deleted 2026-08-10 with its paired cleanup,
        v2_delete_charisma_snippets_for_recording). Its rows — source_type
        'student' / 'internet' — are still IN the table; nothing was dropped.
        Widening this delete to "all rows for the recording" would destroy
        them, and would also start eating interview-turn and funnel rows that
        happen to share a recording_id. The filter is what keeps four
        producers' rows in one table from deleting each other.

        Coach authoring lives in the separate training_labels /
        coach_snippet_drafts tables; those rows are left as-is (orphaned by
        snippet_id, invisible to the new cut). Returns the delete count."""
        if not recording_id:
            return 0
        try:
            res = (
                self.client.table(SNIPPETS_TABLE)
                .delete()
                .eq("recording_id", recording_id)
                .is_("source_type", "null")
                .execute()
            )
            return len(res.data or [])
        except Exception as e:
            logger.warning(
                "v2_delete_lab_snippets_for_recording failed rec=%s err=%s",
                recording_id, e,
            )
            return 0

    def v2_insert_charisma_snippets(self, snippets: list[dict]) -> list[dict]:
        """Bulk insert charisma snippet candidates."""
        if not snippets:
            return []
        result = (
            self.client.table(SNIPPETS_TABLE)
            .insert(snippets)
            .execute()
        )
        return result.data or []

    def v2_get_charisma_snippet(self, snippet_id: str) -> Optional[dict]:
        """Return one charisma snippet row by id."""
        result = (
            self.client.table(SNIPPETS_TABLE)
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
            self.client.table(SNIPPETS_TABLE)
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
            self.client.table(SNIPPETS_TABLE)
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
            self.client.table(SNIPPETS_TABLE)
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
        query = self.client.table(SNIPPETS_TABLE).select("*")
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

    def v2_find_session_by_upload_key(self, key: Optional[str]
                                      ) -> Optional[dict]:
        """The retry-collapse lookup (founder 2026-08-10, the double
        recording): same key = same take = the same session. None on
        anything missing — the POST then proceeds as a first attempt."""
        if not key:
            return None
        try:
            res = (
                self.client.table("v2_sessions")
                .select("*")
                .eq("upload_idempotency_key", str(key))
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            logger.warning("v2_find_session_by_upload_key failed: %s", e)
            return None

    def v2_set_session_upload_key(self, session_id: str,
                                  key: Optional[str]) -> bool:
        """Stamp the take's idempotency key on its session. Best-effort —
        a miss just means a retry cannot collapse (today's behavior)."""
        if not session_id or not key:
            return False
        try:
            (self.client.table("v2_sessions")
             .update({"upload_idempotency_key": str(key)})
             .eq("id", str(session_id))
             .execute())
            return True
        except Exception as e:
            logger.warning("v2_set_session_upload_key failed sid=%s: %s",
                           session_id, e)
            return False

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
                current = _free_credit_grant()
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
                current = _free_credit_grant()
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

    def v2_set_student_credits(self, user_id: str, credits: int) -> int | None:
        """Set the credit balance to an ABSOLUTE value (testing admin tool,
        founder 2026-07-13). Floors at 0; marks credits_initialized_at so the
        lazy seed never re-grants over it. Returns the new balance or None."""
        try:
            c = max(0, int(credits))
            now = datetime.now(timezone.utc).isoformat()
            result = (
                self.client.table("v2_student_details")
                .upsert(
                    {"user_id": user_id, "credits": c,
                     "credits_initialized_at": now, "updated_at": now},
                    on_conflict="user_id",
                )
                .execute()
            )
            return (result.data[0] or {}).get("credits") if result.data else c
        except Exception as e:
            logger.warning("v2_set_student_credits failed user_id=%s credits=%s: %s",
                           user_id, credits, e, exc_info=True)
            return None

    def v2_find_user_id_by_email(self, email: str) -> Optional[str]:
        """Resolve a Supabase auth user_id from an email (case-insensitive) —
        for the testing credits-admin page (founder enters an email, not a
        UUID). Scans the Auth Admin user list; fine for the testing user count.
        None when not found / on error."""
        target = (email or "").strip().lower()
        if not target:
            return None
        try:
            offset = 0
            for _ in range(20):  # up to 20 * 50 = 1000 users, then give up
                page = self.v2_list_auth_users(limit=50, offset=offset) or []
                for u in page:
                    if (u.get("email") or "").strip().lower() == target:
                        return u.get("user_id") or u.get("id")
                if len(page) < 50:
                    break
                offset += 50
            return None
        except Exception as e:
            logger.warning("v2_find_user_id_by_email failed: %s", e)
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

    def v2_charge_lab_credits_once(self, session_id: str, user_id: str, amount: int = 1) -> None:
        """Deduct `amount` credits once per willab Lab session at SEND.

        willab "uses credits" — UX Wave v2 relocated the charge from publish
        to send-success (1/session, soft). Idempotent: sets
        lab_credits_charged_at only when NULL (a re-send / re-claim / OAuth
        re-callback never double-charges — all resolve to one session_id),
        then deducts SOFTLY — v2_deduct_session_credits floors at 0, so it
        never hard-blocks. On deduct failure, clears the flag so a retry can
        succeed. Best-effort: never raises into the send path; degrades to a
        no-op if the column is missing.
        """
        if not session_id or not user_id:
            return
        now = datetime.now(timezone.utc).isoformat()
        try:
            result = (
                self.client.table("v2_sessions")
                .update({"lab_credits_charged_at": now})
                .eq("id", session_id)
                .is_("lab_credits_charged_at", "null")
                .execute()
            )
            if not result.data:
                return  # already charged (idempotent no-op), or no such row
        except Exception as e:
            err_low = str(e).lower()
            if "lab_credits_charged_at" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                logger.warning(
                    "v2_charge_lab_credits_once: column missing (run "
                    "migrations/add_lab_credits_charged_at.sql) sid=%s",
                    session_id,
                )
            else:
                logger.warning(
                    "v2_charge_lab_credits_once: flag update failed sid=%s err=%s",
                    session_id, e,
                )
            return
        new_bal = self.v2_deduct_session_credits(user_id, amount=amount)
        if new_bal is None:
            logger.warning(
                "v2_charge_lab_credits_once: deduct failed after flag; "
                "clearing flag sid=%s user=%s", session_id, user_id,
            )
            try:
                self.client.table("v2_sessions").update(
                    {"lab_credits_charged_at": None}
                ).eq("id", session_id).execute()
            except Exception:
                pass
        else:
            logger.info(
                "v2_charge_lab_credits_once: charged %d sid=%s user=%s new_balance=%s",
                amount, session_id, user_id, new_bal,
            )

    def v2_charge_feedback_credits_once(
        self, session_id: str, user_id: str, amount: int = 5,
    ) -> None:
        """Deduct `amount` credits once per session WHEN COACH FEEDBACK IS
        DELIVERED to the user (the publish 'insights ready' moment) — the willab
        monetization trigger (founder re-lock 2026: 15 free credits = 3 free
        coach feedbacks at 5 each). Idempotent: sets feedback_credits_charged_at
        only when NULL, so a re-publish / re-view NEVER re-charges (one charge
        per session's first feedback delivery), then deducts SOFTLY —
        v2_deduct_session_credits floors at 0, so a low balance never withholds
        the coach's work (the gate is on starting the NEXT recording, not on
        receiving feedback). On deduct failure, clears the flag so a retry can
        succeed. Best-effort: never raises into the publish path; no-op if the
        column is missing."""
        if not session_id or not user_id:
            return
        now = datetime.now(timezone.utc).isoformat()
        try:
            result = (
                self.client.table("v2_sessions")
                .update({"feedback_credits_charged_at": now})
                .eq("id", session_id)
                .is_("feedback_credits_charged_at", "null")
                .execute()
            )
            if not result.data:
                return  # already charged (idempotent no-op), or no such row
        except Exception as e:
            err_low = str(e).lower()
            if "feedback_credits_charged_at" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                logger.warning(
                    "v2_charge_feedback_credits_once: column missing (run "
                    "migrations/add_feedback_credits_charged_at.sql) sid=%s",
                    session_id,
                )
            else:
                logger.warning(
                    "v2_charge_feedback_credits_once: flag update failed sid=%s "
                    "err=%s", session_id, e,
                )
            return
        new_bal = self.v2_deduct_session_credits(user_id, amount=amount)
        if new_bal is None:
            logger.warning(
                "v2_charge_feedback_credits_once: deduct failed after flag; "
                "clearing flag sid=%s user=%s", session_id, user_id,
            )
            try:
                self.client.table("v2_sessions").update(
                    {"feedback_credits_charged_at": None}
                ).eq("id", session_id).execute()
            except Exception:
                pass
        else:
            logger.info(
                "v2_charge_feedback_credits_once: charged %d sid=%s user=%s "
                "new_balance=%s", amount, session_id, user_id, new_bal,
            )

    def v2_ensure_credits_initialized(self, user_id: str, grant: Optional[int] = None) -> int:
        """willab credit grant — lazy first-touch seed (UX Wave v2 C1/S.2).

        Grants `grant` credits ONCE per user, the first time we touch their
        ledger (balance read or first send). `grant` defaults to
        config.WILLAB_FREE_CREDIT_GRANT (25 for the testing phase, env-tunable).
        Idempotent via the DEDICATED
        credits_initialized_at flag — never keyed on credits==0/NULL, so a
        user who spends down to 0 is never re-granted. Preserves any existing
        balance (e.g. purchased credits): seeds `grant` only when there is no
        credits value yet; otherwise just stamps the flag. Best-effort —
        returns the resolved balance; degrades to `grant` if the column is
        missing (pre-migration) so the balance endpoint still works.
        """
        if grant is None:
            grant = _free_credit_grant()
        if not user_id:
            return grant
        now = datetime.now(timezone.utc).isoformat()
        try:
            res = (
                self.client.table("v2_student_details")
                .select("credits, credits_initialized_at")
                .eq("user_id", user_id)
                .execute()
            )
            row = res.data[0] if res.data else None
        except Exception as e:
            err_low = str(e).lower()
            if "credits_initialized_at" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                logger.warning(
                    "v2_ensure_credits_initialized: column missing (run "
                    "migrations/add_credits_initialized_at.sql) user=%s", user_id,
                )
            else:
                logger.warning(
                    "v2_ensure_credits_initialized: read failed user=%s err=%s",
                    user_id, e,
                )
            # Fall back to the legacy implicit default so balance still resolves.
            try:
                d = self.v2_get_student_details(user_id)
                cur = (d or {}).get("credits")
                return int(cur) if cur is not None else int(grant)
            except Exception:
                return int(grant)

        # Already initialized → return the current balance (coerced).
        if row and row.get("credits_initialized_at"):
            cur = row.get("credits")
            return int(cur) if cur is not None else 0

        if row is None:
            # No row yet → create with the grant (on_conflict survives a race).
            try:
                self.client.table("v2_student_details").upsert(
                    {"user_id": user_id, "credits": int(grant),
                     "credits_initialized_at": now, "updated_at": now},
                    on_conflict="user_id",
                ).execute()
            except Exception as e:
                logger.warning(
                    "v2_ensure_credits_initialized: seed-insert failed user=%s err=%s",
                    user_id, e,
                )
            logger.info("v2_ensure_credits_initialized: granted %d user=%s", grant, user_id)
            return int(grant)

        # Row exists, flag NULL → seed once. Preserve an existing balance; the
        # `.is_(... null)` guard means a concurrent send that already flagged +
        # decremented this row is NOT clobbered (the update matches nothing).
        existing = row.get("credits")
        seed = int(existing) if existing is not None else int(grant)
        try:
            self.client.table("v2_student_details").update(
                {"credits": seed, "credits_initialized_at": now, "updated_at": now}
            ).eq("user_id", user_id).is_("credits_initialized_at", "null").execute()
        except Exception as e:
            logger.warning(
                "v2_ensure_credits_initialized: seed-update failed user=%s err=%s",
                user_id, e,
            )
        if existing is None:
            logger.info("v2_ensure_credits_initialized: granted %d user=%s", grant, user_id)
        return seed

    def list_coach_students(self, *, limit: int = 100, offset: int = 0) -> list[dict]:
        """willab coach roster (UX Wave v2 E3 / §B.4). Distinct users who have
        a willab Lab session, newest-active first. Returns raw rows
        [{user_id, last_active, session_count}]; the route pseudonymizes +
        attaches the profile domain (NEVER name/email here). session_count =
        the user's total Lab sessions — the read-only coach-load / heavy-user
        signal for the beta "drowning guard" (accurate up to the scan cap
        below). Solo-coach beta: every willab student is in scope (no per-coach
        assignment table yet). Scans up to 2000 recent Lab sessions, dedups in
        Python (PostgREST has no DISTINCT), then pages — fine at beta scale;
        revisit if the roster grows large.
        """
        try:
            res = (
                self.client.table("v2_sessions")
                .select("user_id, created_at, guest_claimed_at")
                .eq("source", "audit_upload")
                .order("created_at", desc=True)
                .limit(2000)
                .execute()
            )
            seen: dict[str, dict] = {}
            for r in (res.data or []):
                uid = r.get("user_id")
                if not uid:
                    continue  # unclaimed guest rows have no user — skip
                ts = r.get("guest_claimed_at") or r.get("created_at") or ""
                key = str(uid)
                entry = seen.get(key)
                if entry is None:
                    seen[key] = {"user_id": key, "last_active": ts, "session_count": 1}
                else:
                    entry["session_count"] += 1
                    if ts > entry["last_active"]:
                        entry["last_active"] = ts
            rows = sorted(seen.values(), key=lambda x: x["last_active"], reverse=True)
            return rows[offset:offset + limit]
        except Exception as e:
            err_low = str(e).lower()
            if "source" in err_low and "pgrst" in err_low:
                logger.warning(
                    "list_coach_students: source column missing (run "
                    "migrations/add_foundation_discriminators.sql)",
                )
                return []
            logger.warning("list_coach_students failed err=%s", e)
            return []

    def v2_list_user_lab_sessions(self, user_id: str, *, limit: int = 200) -> list[dict]:
        """All of a user's willab Lab sessions (source=audit_upload), newest
        first. Powers the coach drill-down (E-1b), the user_audit assembly
        (BE-3), and the cumulative recorded-seconds sum (BE-1). Best-effort:
        [] on missing column / DB hiccup."""
        if not user_id:
            return []
        try:
            res = (
                self.client.table("v2_sessions")
                .select("id, recording_1_id, intake_context, status, "
                        "created_at, guest_claimed_at, results_published_at, "
                        "insights_payload, arc_id, take_index, "
                        "slide_transcripts, coach_feedback_saved_at, "
                        "recording_kind, paired_session_id")
                .eq("user_id", user_id)
                .eq("source", "audit_upload")
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "source" in err_low and "pgrst" in err_low:
                return []
            # arc_id/take_index/slide_transcripts/coach_feedback_saved_at/
            # recording_kind/paired_session_id are later migrations — fall
            # back to the base select if any isn't present yet.
            if any(c in err_low for c in
                   ("arc_id", "take_index", "slide_transcripts",
                    "coach_feedback_saved_at",
                    "recording_kind", "paired_session_id")):
                try:
                    res = (
                        self.client.table("v2_sessions")
                        .select("id, recording_1_id, intake_context, status, "
                                "created_at, guest_claimed_at, "
                                "results_published_at, insights_payload")
                        .eq("user_id", user_id)
                        .eq("source", "audit_upload")
                        .order("created_at", desc=True)
                        .limit(limit)
                        .execute()
                    )
                    return res.data or []
                except Exception:
                    return []
            logger.warning(
                "v2_list_user_lab_sessions failed user=%s err=%s", user_id, e,
            )
            return []

    def v2_get_cumulative_recorded_seconds(self, user_id: str) -> int:
        """Sum of the user's Lab recording durations (seconds) — the
        recording-progress signal (BE-1 / S2). Sums recordings.duration over
        the recordings linked to the user's Lab sessions. Recordings predating
        the duration-persistence fix (UX Wave 3) carry duration=0, so
        historical time undercounts; going forward it is exact. Best-effort:
        0 on hiccup."""
        if not user_id:
            return 0
        try:
            sessions = self.v2_list_user_lab_sessions(user_id)
            rec_ids = [
                s.get("recording_1_id") for s in sessions if s.get("recording_1_id")
            ]
            if not rec_ids:
                return 0
            total = 0
            for i in range(0, len(rec_ids), 100):  # keep the IN() list sane
                chunk = rec_ids[i:i + 100]
                res = (
                    self.client.table("recordings")
                    .select("id, duration")
                    .in_("id", chunk)
                    .execute()
                )
                for r in (res.data or []):
                    try:
                        total += int(round(float(r.get("duration") or 0)))
                    except (TypeError, ValueError):
                        pass
            return total
        except Exception as e:
            logger.warning(
                "v2_get_cumulative_recorded_seconds failed user=%s err=%s",
                user_id, e,
            )
            return 0

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

    # ── processing_jobs — durable state for the async recording pipeline ──
    # (migrations/add_processing_jobs.sql). Postgres is the source of truth;
    # Redis only delivers. All writers here are exact-shape (no phantom
    # columns — the PGRST204 whole-update-rejected lesson from
    # v2_update_session_status_unscoped applies to every method below).

    def create_processing_job(
        self,
        *,
        kind: str,
        user_id: Optional[str],
        session_id: Optional[str],
        dedup_key: Optional[str],
        payload: Dict[str, Any],
        max_attempts: int = 3,
    ) -> Optional[Dict[str, Any]]:
        """Insert a pending job row. Returns the row, or None on failure
        (including a dedup conflict — caller checks for an active twin)."""
        row = {
            "kind": kind,
            "user_id": user_id,
            "session_id": session_id,
            "dedup_key": dedup_key,
            "status": "pending",
            "attempts": 0,
            "max_attempts": max(1, int(max_attempts)),
            "payload": payload or {},
        }
        try:
            res = self.client.table("processing_jobs").insert(row).execute()
            return res.data[0] if res.data else None
        except Exception as e:
            logger.warning("create_processing_job failed kind=%s sid=%s: %s",
                           kind, session_id, e)
            return None

    def get_processing_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        try:
            res = (
                self.client.table("processing_jobs")
                .select("*")
                .eq("id", job_id)
                .limit(1)
                .execute()
            )
            return res.data[0] if res.data else None
        except Exception as e:
            logger.warning("get_processing_job failed job=%s: %s", job_id, e)
            return None

    def get_active_processing_job_by_dedup(
        self, dedup_key: str,
    ) -> Optional[Dict[str, Any]]:
        """The pending/processing job holding this dedup_key, if any."""
        try:
            res = (
                self.client.table("processing_jobs")
                .select("*")
                .eq("dedup_key", dedup_key)
                .in_("status", ["pending", "processing"])
                .limit(1)
                .execute()
            )
            return res.data[0] if res.data else None
        except Exception as e:
            logger.warning("get_active_processing_job_by_dedup failed: %s", e)
            return None

    def claim_processing_job(
        self, job_id: str, expected_attempts: int,
    ) -> Optional[Dict[str, Any]]:
        """Atomically claim a job for one run: pending|processing →
        processing, attempts+1 — guarded by eq(attempts, expected) so of two
        racing claimers (double delivery, sweeper vs live worker) exactly
        one wins. Returns the claimed row or None if the CAS lost."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            res = (
                self.client.table("processing_jobs")
                .update({
                    "status": "processing",
                    "attempts": int(expected_attempts) + 1,
                    "started_at": now,
                    "heartbeat_at": now,
                    "updated_at": now,
                })
                .eq("id", job_id)
                .eq("attempts", int(expected_attempts))
                .in_("status", ["pending", "processing"])
                .execute()
            )
            return res.data[0] if res.data else None
        except Exception as e:
            logger.warning("claim_processing_job failed job=%s: %s", job_id, e)
            return None

    def update_processing_job(
        self, job_id: str, fields: Dict[str, Any],
    ) -> bool:
        """Generic best-effort field update (heartbeat / stage / percent)."""
        try:
            payload = dict(fields)
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.client.table("processing_jobs").update(payload).eq(
                "id", job_id
            ).execute()
            return True
        except Exception as e:
            logger.warning("update_processing_job failed job=%s: %s", job_id, e)
            return False

    def finish_processing_job(
        self,
        job_id: str,
        status: str,
        *,
        error: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Terminal transition → completed | failed."""
        if status not in ("completed", "failed"):
            return False
        now = datetime.now(timezone.utc).isoformat()
        fields: Dict[str, Any] = {
            "status": status,
            "finished_at": now,
            "updated_at": now,
        }
        if status == "completed":
            fields["percent"] = 100
            fields["stage"] = "completed"
            fields["error"] = None
        if error is not None:
            fields["error"] = str(error)[:500]
        if result is not None:
            fields["result"] = result
        try:
            self.client.table("processing_jobs").update(fields).eq(
                "id", job_id
            ).execute()
            return True
        except Exception as e:
            logger.warning("finish_processing_job failed job=%s: %s", job_id, e)
            return False

    def release_processing_job_for_retry(
        self, job_id: str, error: Optional[str] = None,
    ) -> bool:
        """processing → pending (a failed run that still has attempts left,
        or a sweeper-recovered orphan). The attempts counter is NOT reset —
        it is the lifetime run count the cap applies to."""
        now = datetime.now(timezone.utc).isoformat()
        fields: Dict[str, Any] = {
            "status": "pending",
            "heartbeat_at": None,
            "updated_at": now,
        }
        if error is not None:
            fields["error"] = str(error)[:500]
        try:
            res = (
                self.client.table("processing_jobs")
                .update(fields)
                .eq("id", job_id)
                .eq("status", "processing")
                .execute()
            )
            return bool(res.data)
        except Exception as e:
            logger.warning("release_processing_job_for_retry failed job=%s: %s",
                           job_id, e)
            return False

    def list_stale_processing_jobs(
        self, stale_minutes: int = 15, max_rows: int = 100,
    ) -> List[Dict[str, Any]]:
        """Jobs the sweeper should look at: 'processing' rows whose heartbeat
        is older than the cutoff (worker killed mid-job), plus 'pending' rows
        untouched for the same window (enqueue lost — e.g. Redis wiped)."""
        from datetime import timedelta
        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=max(2, stale_minutes))
        ).isoformat()
        out: List[Dict[str, Any]] = []
        try:
            res = (
                self.client.table("processing_jobs")
                .select("*")
                .eq("status", "processing")
                .lt("heartbeat_at", cutoff)
                .limit(max_rows)
                .execute()
            )
            out.extend(res.data or [])
        except Exception as e:
            logger.warning("list_stale_processing_jobs (processing): %s", e)
        try:
            res = (
                self.client.table("processing_jobs")
                .select("*")
                .eq("status", "pending")
                .lt("updated_at", cutoff)
                .limit(max_rows)
                .execute()
            )
            out.extend(res.data or [])
        except Exception as e:
            logger.warning("list_stale_processing_jobs (pending): %s", e)
        return out

    def list_active_processing_jobs(
        self, max_rows: int = 500,
    ) -> List[Dict[str, Any]]:
        """Everything in flight — the queue-depth half of the ops signal."""
        try:
            res = (
                self.client.table("processing_jobs")
                .select("id, status, enqueued_at, started_at")
                .in_("status", ["pending", "processing"])
                .limit(max_rows)
                .execute()
            )
            return res.data or []
        except Exception as e:
            logger.warning("list_active_processing_jobs: %s", e)
            return []

    # The admin panel's projection. NEVER add `payload` or `result` to it.
    #
    # `payload` holds storage paths and upload flags; `result` holds pipeline
    # output. The panel needs neither, and the smallest safe projection is the
    # one that cannot leak a field nobody reviewed. A future `select("*")`
    # here would silently widen an admin surface — test_pipeline_admin asserts
    # on the RETURNED KEYS so that change fails a test rather than shipping.
    _ADMIN_JOB_FIELDS = (
        "id, kind, status, stage, percent, message, error, attempts, "
        "max_attempts, user_id, session_id, enqueued_at, started_at, "
        "finished_at, created_at"
    )

    def list_processing_jobs(
        self, *, status: Optional[str] = None, limit: int = 50,
        before: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Recent jobs for the admin panel, newest first. [] on any failure.

        KEYSET PAGINATION on `enqueued_at`, not OFFSET. The queue mutates
        while you page — jobs finish, new ones arrive — and OFFSET silently
        skips rows when the set shifts underneath it, so page 2 would be
        missing work that page 1 no longer holds. `before` is the previous
        page's oldest `enqueued_at`.

        BOUNDED BY CONSTRUCTION: limit is clamped to 100 here, at the data
        layer, rather than trusted from the caller. An ops surface must never
        be able to table-scan production, and a cap enforced only in the route
        is one refactor away from being absent.
        """
        try:
            capped = max(1, min(int(limit or 50), 100))
        except (TypeError, ValueError):
            capped = 50
        try:
            q = (self.client.table("processing_jobs")
                 .select(self._ADMIN_JOB_FIELDS))
            if status:
                q = q.eq("status", str(status))
            if before:
                q = q.lt("enqueued_at", str(before))
            res = (q.order("enqueued_at", desc=True)
                    .limit(capped).execute())
            return res.data or []
        except Exception as e:
            logger.warning("list_processing_jobs: %s", e)
            return []

    def list_recent_finished_processing_jobs(
        self, max_rows: int = 200,
    ) -> List[Dict[str, Any]]:
        """Recent terminal jobs — the latency half of the ops signal."""
        try:
            res = (
                self.client.table("processing_jobs")
                .select("id, status, enqueued_at, started_at, finished_at, "
                        "error")
                .in_("status", ["completed", "failed"])
                .order("finished_at", desc=True)
                .limit(max_rows)
                .execute()
            )
            return res.data or []
        except Exception as e:
            logger.warning("list_recent_finished_processing_jobs: %s", e)
            return []

    def list_orphaned_processing_sessions(
        self, stale_minutes: int = 30, max_rows: int = 100,
    ) -> List[Dict[str, Any]]:
        """Sessions stuck on analysis_state='processing' with NO active job.

        The gap this closes: the job sweeper only walks processing_jobs, so a
        session flipped to 'processing' that never got a job row is invisible
        to it and shows "Working on your take" forever. Two ways to get one:
        the pre-queue daemon path (ASYNC_ANALYSIS_ENABLED) whose thread died
        with a redeploy, and a crash-looping worker window where the enqueue
        never landed.

        Deliberately generous default cutoff (30 min > the job sweeper's 15):
        a session is only a candidate once it is far past any plausible live
        run, AND has no active job protecting it. Reaping one that IS somehow
        still being worked is self-healing anyway — whoever finishes writes
        'ready' over the 'failed'.

        v2_sessions has no updated_at column (PGRST204 lesson), so created_at
        is the clock. In this flow analysis starts moments after the row is
        created, which makes it a fair proxy.
        """
        from datetime import timedelta
        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=max(5, stale_minutes))
        ).isoformat()
        try:
            res = (
                self.client.table("v2_sessions")
                .select("id, analysis_state, created_at")
                .eq("analysis_state", "processing")
                .lt("created_at", cutoff)
                .limit(max_rows)
                .execute()
            )
            candidates = res.data or []
        except Exception as e:
            logger.warning("list_orphaned_processing_sessions: %s", e)
            return []
        if not candidates:
            return []
        # Subtract anything a live job still owns — that one is not orphaned.
        protected: set = set()
        try:
            ids = [str(r.get("id")) for r in candidates if r.get("id")]
            res = (
                self.client.table("processing_jobs")
                .select("session_id, status")
                .in_("session_id", ids)
                .in_("status", ["pending", "processing"])
                .execute()
            )
            protected = {
                str(r.get("session_id")) for r in (res.data or [])
                if r.get("session_id")
            }
        except Exception as e:
            # Fail CLOSED: if the guard query fails we cannot tell orphaned
            # from live, and failing a running take is worse than a banner
            # that clears one sweep later.
            logger.warning(
                "list_orphaned_processing_sessions: active-job guard failed "
                "(%s) — skipping this pass", e)
            return []
        return [r for r in candidates if str(r.get("id")) not in protected]

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
        user_id: str | None,
        recording_id: str,
        start_offset_ms: int,
        duration_ms: int,
        audio_segment_path: str,
        metrics: dict | None = None,
        transcript: str | None = None,
        words: list | None = None,
    ) -> dict | None:
        """Create a new charisma snippet record (unlabeled by default).

        Args:
            user_id: Real user UUID, or None for anonymous interview turns
                     (updated via update_snippets_user_id on claim).
            metrics: Optional JSONB dict of pre-computed acoustic metrics
                     (wpm, pause_ms, dynamic_db, emphasis_per_min, energy_ratio,
                      pitch_center_st, pitch_frame_count, voiced_duration_sec).
            words: Optional word-level Whisper timestamps [{word, start, end}]
                   (seconds), for #6 per-slide transcript sync. Stored in the
                   `words` JSONB column (migrations/add_snippet_transcripts.sql).
                   If that column isn't applied yet, the insert retries WITHOUT
                   words so a recording is never lost to a pending migration.
        """
        def _insert(payload):
            res = (
                self.client.table(SNIPPETS_TABLE)
                .insert(payload)
                .execute()
            )
            return res.data[0] if res.data and len(res.data) > 0 else None

        try:
            payload = {
                "session_id": session_id,
                "recording_id": recording_id,
                "start_offset_ms": start_offset_ms,
                "duration_ms": duration_ms,
                "audio_segment_path": audio_segment_path,
                "snippet_type": "unlabeled",
            }
            if user_id:
                payload["user_id"] = user_id
            if metrics:
                payload["metrics"] = metrics
            if transcript:
                payload["transcript"] = transcript
            if words:
                payload["words"] = words
            try:
                return _insert(payload)
            except Exception as col_err:
                # The `words` column may not be migrated in this env yet — never
                # let it cost us the snippet. Retry without words (#6 degrades to
                # the legacy whole-snippet per-slide bucketing).
                if "words" in payload:
                    logger.warning(
                        "create_charisma_snippet: retry without words "
                        "(run add_snippet_transcripts.sql?): %s", col_err,
                    )
                    payload.pop("words", None)
                    return _insert(payload)
                raise
        except Exception as e:
            logger.error(f"create_charisma_snippet failed: {e}")
            return None

    def create_charisma_snippets_bulk(self, rows: list | None) -> list:
        """Bulk-insert charisma_snippets in ONE round-trip (pieces-canonical
        2026-07-14 — a long take is ~270 pieces; N sequential inserts would
        add 15-40s to the synchronous upload). Each row dict mirrors
        create_charisma_snippet's payload keys (session_id, user_id?,
        recording_id, start_offset_ms, duration_ms, audio_segment_path,
        metrics?, transcript?, words?).

        Returns the inserted ids in INPUT ORDER (Supabase preserves insert
        order in the returned rows). On a bulk failure it retries the whole
        batch WITHOUT the `words` column (pending migration), then finally
        falls back to per-row create_charisma_snippet so a recording is never
        lost. Missing ids come back as None (aligned by index)."""
        rows = rows or []
        if not rows:
            return []

        def _payload(r, with_words=True):
            p = {
                "session_id": r.get("session_id"),
                "recording_id": r.get("recording_id"),
                "start_offset_ms": r.get("start_offset_ms"),
                "duration_ms": r.get("duration_ms"),
                "audio_segment_path": r.get("audio_segment_path"),
                "snippet_type": "unlabeled",
            }
            if r.get("user_id"):
                p["user_id"] = r["user_id"]
            if r.get("metrics"):
                p["metrics"] = r["metrics"]
            if r.get("transcript"):
                p["transcript"] = r["transcript"]
            if with_words and r.get("words"):
                p["words"] = r["words"]
            return p

        def _bulk(with_words):
            res = (
                self.client.table(SNIPPETS_TABLE)
                .insert([_payload(r, with_words) for r in rows])
                .execute()
            )
            data = res.data or []
            return [d.get("id") for d in data]

        try:
            ids = _bulk(True)
            if len(ids) == len(rows):
                return ids
            # Partial/empty return → fall through to the safe per-row path.
            raise RuntimeError(f"bulk returned {len(ids)} of {len(rows)}")
        except Exception as bulk_err:
            _e = str(bulk_err).lower()
            if "words" in _e:
                try:
                    ids = _bulk(False)
                    if len(ids) == len(rows):
                        logger.warning(
                            "create_charisma_snippets_bulk: inserted without "
                            "words (run add_snippet_transcripts.sql?)")
                        return ids
                except Exception as e2:
                    logger.warning(
                        "create_charisma_snippets_bulk: no-words retry "
                        "failed: %s", e2)
            logger.warning(
                "create_charisma_snippets_bulk: bulk failed (%s) — per-row "
                "fallback", bulk_err)
            out = []
            for r in rows:
                row = self.create_charisma_snippet(
                    session_id=r.get("session_id"), user_id=r.get("user_id"),
                    recording_id=r.get("recording_id"),
                    start_offset_ms=r.get("start_offset_ms"),
                    duration_ms=r.get("duration_ms"),
                    audio_segment_path=r.get("audio_segment_path"),
                    metrics=r.get("metrics"), transcript=r.get("transcript"),
                    words=r.get("words"),
                )
                out.append(row.get("id") if row else None)
            return out

    def insert_candidate_windows(self, rows: list | None) -> int:
        """Persist the FULL candidate-window pool for a recording (automation-
        audit fix #1 — the 'offered vs chosen' selection signal). Append-only,
        training-bound (never read by any user/coach surface; AC-9: storing !=
        surfacing). Idempotent per (recording_id, start_offset_ms) — a re-process
        no-ops via ON CONFLICT DO NOTHING.

        Best-effort: returns the count written; 0 on missing table / bad input /
        error — NEVER raises (live-loop fence: capture must not break the
        recording pipeline). See migrations/add_candidate_windows.sql."""
        if not rows:
            return 0
        clean = [
            r for r in rows
            if isinstance(r, dict) and r.get("start_offset_ms") is not None
        ]
        if not clean:
            return 0
        try:
            res = self.client.table("candidate_windows").upsert(
                clean,
                on_conflict="recording_id,start_offset_ms",
                ignore_duplicates=True,
            ).execute()
            # Report ACTUAL inserted rows when the client returns them (a
            # re-process skips dups via ON CONFLICT DO NOTHING) so the telemetry
            # doesn't overcount; fall back to attempted on older clients.
            data = getattr(res, "data", None)
            return len(data) if isinstance(data, list) else len(clean)
        except Exception as e:
            err_low = str(e).lower()
            if "candidate_windows" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "insert_candidate_windows: table missing (run "
                    "migrations/add_candidate_windows.sql) — pool not captured",
                )
                return 0
            logger.warning("insert_candidate_windows failed: %s", e)
            return 0

    def stamp_review_opened(self, session_id: Optional[str]) -> bool:
        """First-touch stamp of when the coach OPENED a session for review
        (readiness rig #3 — coach-time baseline = results_published_at -
        review_opened_at). Idempotent: set ONLY when NULL, so the first open
        wins. Best-effort → False on missing column / error; NEVER raises into
        the coach review path."""
        if not session_id:
            return False
        now = datetime.now(timezone.utc).isoformat()
        try:
            res = (
                self.client.table("v2_sessions")
                .update({"review_opened_at": now})
                .eq("id", session_id)
                .is_("review_opened_at", "null")
                .execute()
            )
            return bool(res.data)
        except Exception as e:
            err_low = str(e).lower()
            if "review_opened_at" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return False
            logger.warning("stamp_review_opened failed sid=%s: %s", session_id, e)
            return False

    def insert_rejected_take(
        self, *, reason: str | None,
        duration_sec=None, voiced_sec=None, thresholds=None,
        user_id=None, guest_session_id=None, arc_id=None, take_index=None,
    ) -> bool:
        """Log a gate-rejected take's METRICS (automation-audit fix #2c —
        survivorship: gate-failed takes were dropped before any storage, so we
        had no 'bad take' record). Metrics ONLY, never audio. Best-effort,
        append-only, missing-table-safe; NEVER raises (live-loop fence). See
        migrations/add_rejected_takes.sql."""
        row: dict = {"reason": reason}
        if user_id:
            row["user_id"] = user_id
        if guest_session_id:
            row["guest_session_id"] = str(guest_session_id)
        if arc_id:
            row["arc_id"] = str(arc_id)
        if take_index is not None:
            try:
                row["take_index"] = int(take_index)
            except (TypeError, ValueError):
                pass
        for k, v in (("duration_sec", duration_sec), ("voiced_sec", voiced_sec)):
            if v is not None:
                try:
                    row[k] = float(v)
                except (TypeError, ValueError):
                    pass
        if isinstance(thresholds, dict):
            row["thresholds"] = thresholds
        try:
            self.client.table("rejected_takes").insert(row).execute()
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "rejected_takes" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "insert_rejected_take: table missing (run "
                    "migrations/add_rejected_takes.sql) — reject not captured",
                )
                return False
            logger.warning("insert_rejected_take failed: %s", e)
            return False

    # ── willab — coach-video corpus (Subsystem V) ─────────────────────────
    #
    # Private/training-bound lane (RLS service-role only). Capture only; never
    # read by a user surface. See migrations/add_coach_video_assets.sql +
    # services/coach_video_capture.py. All best-effort: NEVER raise into the
    # video-upload path (live-loop fence).

    def get_coach_video_asset_by_idempotency_key(
        self, key: Optional[str],
    ) -> Optional[dict]:
        """The asset for a client record-action key (retry dedupe). None on
        missing table / unknown key / error."""
        if not key:
            return None
        try:
            res = (
                self.client.table("coach_video_assets")
                .select("*")
                .eq("upload_idempotency_key", str(key))
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            err_low = str(e).lower()
            if "coach_video_assets" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                return None
            logger.warning("get_coach_video_asset_by_idempotency_key failed: %s", e)
            return None

    def get_current_coach_video_asset(
        self, session_id: str, content_type: str,
        snippet_id: Optional[str] = None,
    ) -> Optional[dict]:
        """The CURRENT (is_current) take for a session/content (+snippet for
        breakthrough). None on missing table / none / error."""
        if not session_id or not content_type:
            return None
        try:
            q = (
                self.client.table("coach_video_assets")
                .select("*")
                .eq("session_id", session_id)
                .eq("content_type", content_type)
                .eq("is_current", True)
            )
            if snippet_id:
                q = q.eq("snippet_id", snippet_id)
            else:
                q = q.is_("snippet_id", "null")
            res = q.limit(1).execute()
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            err_low = str(e).lower()
            if "coach_video_assets" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                return None
            logger.warning("get_current_coach_video_asset failed: %s", e)
            return None

    def insert_coach_video_asset(self, row: dict) -> Optional[dict]:
        """Append a coach-video TAKE. Returns the created row (with id) or None on
        missing table / error. Best-effort — never raises."""
        if not isinstance(row, dict) or not row.get("session_id"):
            return None
        try:
            res = self.client.table("coach_video_assets").insert(row).execute()
            return (res.data or [None])[0]
        except Exception as e:
            err_low = str(e).lower()
            if "coach_video_assets" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "insert_coach_video_asset: table missing (run "
                    "migrations/add_coach_video_assets.sql) — not captured",
                )
                return None
            logger.warning("insert_coach_video_asset failed: %s", e)
            return None

    def supersede_coach_video_asset(
        self, prev_id: str, new_id: str,
    ) -> bool:
        """Mark a prior take as superseded by a new one (is_current=false +
        superseded_by). Best-effort → False on error."""
        if not prev_id or not new_id:
            return False
        try:
            self.client.table("coach_video_assets").update(
                {"is_current": False, "superseded_by": str(new_id)}
            ).eq("id", str(prev_id)).execute()
            return True
        except Exception as e:
            logger.warning("supersede_coach_video_asset failed prev=%s: %s", prev_id, e)
            return False

    def update_coach_video_transcript(
        self, asset_id: str, transcript: Optional[str], status: str,
    ) -> bool:
        """Backfill the async transcript + status. Best-effort → False on error."""
        if not asset_id:
            return False
        try:
            self.client.table("coach_video_assets").update(
                {"transcript": transcript, "transcription_status": status}
            ).eq("id", str(asset_id)).execute()
            return True
        except Exception as e:
            logger.warning("update_coach_video_transcript failed asset=%s: %s", asset_id, e)
            return False

    def get_current_coach_video_assets_for_session(
        self, session_id: str,
    ) -> list[dict]:
        """All CURRENT takes for a session (publish snapshot). [] on missing
        table / none / error."""
        if not session_id:
            return []
        try:
            res = (
                self.client.table("coach_video_assets")
                .select("id, content_type, snippet_id, comment_text_at_publish")
                .eq("session_id", session_id)
                .eq("is_current", True)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "coach_video_assets" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                return []
            logger.warning("get_current_coach_video_assets_for_session failed: %s", e)
            return []

    def set_coach_video_comment_at_publish(
        self, asset_id: str, text: Optional[str],
    ) -> bool:
        """Write-once the FINAL delivered comment at publish (only when currently
        NULL, so a re-publish never clobbers the first delivered text).
        Best-effort → False on error/no-op."""
        if not asset_id or not text:
            return False
        try:
            res = (
                self.client.table("coach_video_assets")
                .update({"comment_text_at_publish": text})
                .eq("id", str(asset_id))
                .is_("comment_text_at_publish", "null")
                .execute()
            )
            return bool(res.data)
        except Exception as e:
            logger.warning("set_coach_video_comment_at_publish failed asset=%s: %s", asset_id, e)
            return False

    def get_snippets_by_session(self, session_id: str) -> List[dict]:
        """Get all snippets for a session, ordered by start time."""
        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
                .select("*")
                .eq("session_id", session_id)
                .order("start_offset_ms", desc=False)
                .execute()
            )
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"get_snippets_by_session failed: {e}")
            return []

    def get_snippets_by_sessions(
        self, session_ids, *, include_words: bool = False,
    ) -> dict:
        """Batch read — ALL snippets for many sessions in ONE query per 100 ids
        (kills the N+1 on /v2/user/strengths). Returns
        {session_id: [snippets ordered by start_offset_ms]}.

        Excludes the heavy `words` JSONB by default — the Trainings list reads
        the precomputed slide_transcripts (#A), so per-snippet words aren't
        needed there. Pass include_words=True where the per-snippet split is
        used. Best-effort: {} on hiccup; falls back to select(*) if the slim
        projection trips a missing column."""
        ids = [str(s) for s in (session_ids or []) if s]
        if not ids:
            return {}
        slim = ("id, session_id, start_offset_ms, duration_ms, transcript, "
                "audio_segment_path, metrics, snippet_type")
        cols = "*" if include_words else slim
        # Pieces-canonical (2026-07-14): a session can carry ~15-270 piece
        # rows (was ≤10 windows), so 100 sessions per query can exceed
        # PostgREST's server-side max-rows (default 1000) — which TRUNCATES
        # SILENTLY, and because rows are ordered by start_offset_ms the
        # dropped rows are systematically the ENDS of talks. Two guards:
        # smaller id chunks + explicit .range() pagination until a short page.
        _page = 1000
        out: dict = {}
        try:
            for i in range(0, len(ids), 20):
                chunk = ids[i:i + 20]
                offset = 0
                while True:
                    try:
                        res = (
                            self.client.table(SNIPPETS_TABLE)
                            .select(cols)
                            .in_("session_id", chunk)
                            .order("start_offset_ms", desc=False)
                            .order("id", desc=False)  # total order for paging
                            .range(offset, offset + _page - 1)
                            .execute()
                        )
                    except Exception:
                        # Slim projection hit a missing column → fall back to *
                        # for the rest of the batch (still paged).
                        cols = "*"
                        res = (
                            self.client.table(SNIPPETS_TABLE)
                            .select("*")
                            .in_("session_id", chunk)
                            .order("start_offset_ms", desc=False)
                            .order("id", desc=False)
                            .range(offset, offset + _page - 1)
                            .execute()
                        )
                    rows = res.data or []
                    for r in rows:
                        out.setdefault(str(r.get("session_id")), []).append(r)
                    if len(rows) < _page:
                        break
                    offset += _page
            return out
        except Exception as e:
            logger.warning(
                "get_snippets_by_sessions failed (%d ids): %s", len(ids), e,
            )
            return {}

    def get_snippets_by_user(self, user_id: str, limit: int = 100, offset: int = 0) -> List[dict]:
        """Get all snippets for a user, paginated, ordered by creation date (newest first)."""
        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
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
        """Get only snippets that have admin comments (used for /results page).

        Per docs/ARCHITECTURE_SINGLE_SOURCE_OF_TRUTH.md §6: whitespace-
        only admin_comment is treated as "no comment". PostgREST's
        NOT NULL filter can't express TRIM(...) <> '' so we apply the
        strip-filter in Python after the DB query.
        """
        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
                .select("*")
                .eq("session_id", session_id)
                .not_.is_("admin_comment", "null")
                .order("start_offset_ms", desc=False)
                .execute()
            )
            rows = result.data or []
            return [r for r in rows if (r.get("admin_comment") or "").strip()]
        except Exception as e:
            logger.error(f"get_snippets_with_comments_by_session failed: {e}")
            return []

    def get_snippet_by_id(
        self,
        snippet_id: str,
        user_id: str | None = None,
    ) -> dict | None:
        """Owner-scoped fetch of one charisma_snippets row by id.

        When user_id is provided we filter on it for ownership; pass None
        from admin contexts that need to read any snippet.
        """
        try:
            q = self.client.table(SNIPPETS_TABLE).select("*").eq("id", snippet_id)
            if user_id:
                q = q.eq("user_id", user_id)
            result = q.limit(1).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning(f"get_snippet_by_id failed: {e}")
            return None

    def update_snippet_comment(
        self,
        snippet_id: str,
        admin_comment: str | None,
        snippet_type: str,
        admin_user_id: str | None,
        acceptance_mode: str | None = None,
    ) -> dict | None:
        """Update a snippet's comment, type, admin user, and
        optional RLHF acceptance_mode.

        ``acceptance_mode``:
          'accepted_as_is'  — admin saved the AI draft without
                              changing it (positive RLHF signal).
          'admin_corrected' — admin edited the draft before saving
                              (correction trajectory; paired with
                              ai_draft_admin_comment as the
                              training (predicted, final) row).
          None              — caller didn't classify; column stays
                              unchanged (or NULL on first write).
                              Used by legacy callers + the
                              auto-promote-drafts path that
                              doesn't have admin intent to
                              record.

        ``admin_comment_acceptance_set_at`` is stamped iff
        acceptance_mode is not None.
        """
        try:
            patch: dict = {
                "admin_comment": admin_comment,
                "snippet_type": snippet_type,
                "admin_user_id": admin_user_id,
            }
            if acceptance_mode is not None:
                patch["admin_comment_acceptance_mode"] = acceptance_mode
                patch["admin_comment_acceptance_set_at"] = (
                    datetime.now(timezone.utc).isoformat()
                )
            result = (
                self.client.table(SNIPPETS_TABLE)
                .update(patch)
                .eq("id", snippet_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            err_low = str(e).lower()
            if (
                "admin_comment_acceptance_mode" in err_low
                or "admin_comment_acceptance_set_at" in err_low
                or "pgrst204" in err_low
            ):
                # Migration not yet run in this environment — retry
                # without the new columns so existing admin tooling
                # keeps working. The acceptance signal is lost for
                # this row, which is the expected pre-migration
                # behaviour.
                logger.warning(
                    "update_snippet_comment: acceptance columns "
                    "missing (migration pending?), retrying "
                    "without — sid=%s",
                    snippet_id,
                )
                try:
                    fallback = {
                        "admin_comment": admin_comment,
                        "snippet_type": snippet_type,
                        "admin_user_id": admin_user_id,
                    }
                    result = (
                        self.client.table(SNIPPETS_TABLE)
                        .update(fallback)
                        .eq("id", snippet_id)
                        .execute()
                    )
                    if result.data and len(result.data) > 0:
                        return result.data[0]
                    return None
                except Exception as e2:
                    logger.error(
                        f"update_snippet_comment fallback failed: {e2}"
                    )
                    return None
            logger.error(f"update_snippet_comment failed: {e}")
            return None

    def update_snippet_follow_up_question(
        self,
        snippet_id: str,
        follow_up_question: str | None,
    ) -> dict | None:
        """Store (or clear) the pre-generated follow-up question on a snippet.

        Called automatically after labeling, or manually from the admin panel.
        Returns the updated row, or None on failure.
        """
        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
                .update({
                    "follow_up_question": follow_up_question,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", snippet_id)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error("update_snippet_follow_up_question failed for %s: %s", snippet_id, e)
            return None

    # ── Phase 10: AI-draft + implicit-approval helpers ────────────────

    def create_user_uploaded_file(
        self,
        *,
        user_id: str,
        session_id: str | None,
        r2_bucket: str,
        r2_key: str,
        r2_url: str | None,
        file_name: str,
        file_type: str,
        content_type: str | None,
        file_size_bytes: int | None,
    ) -> Optional[dict]:
        """Insert a user_uploaded_files row.

        Owner-scoping is enforced at the row level via ``user_id``;
        the caller (route handler) is responsible for taking
        ``user_id`` from the authenticated request, not from the
        request body.

        Returns the inserted row on success, ``None`` on failure
        (logs the error so the upload endpoint can surface a
        generic 500 without leaking schema details).
        """
        try:
            payload = {
                "user_id": user_id,
                "session_id": session_id,
                "r2_bucket": r2_bucket,
                "r2_key": r2_key,
                "r2_url": r2_url,
                "file_name": file_name,
                "file_type": file_type,
                "content_type": content_type,
                "file_size_bytes": file_size_bytes,
            }
            result = (
                self.client.table("user_uploaded_files")
                .insert(payload)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.error("create_user_uploaded_file failed: %s", e)
            return None

    def list_user_uploaded_files_for_user(
        self,
        user_id: str,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        """Return user_uploaded_files rows for ``user_id``, newest first.

        Backs the admin Files tab. Soft-deleted rows (deleted_at
        not null, per Task 9's DELETE endpoint) are excluded so the
        admin never sees them in the list.

        Task 9 pagination — caller passes the FE's ``limit`` AND we
        fetch ``limit + 1`` so the route handler can compute
        ``has_more`` without a second count query. Caller is
        responsible for truncating the response slice to ``limit``
        before serialising. Default limit of 200 matches the
        pre-pagination behaviour for callers that don't paginate.
        """
        try:
            lim = max(1, int(limit))
            off = max(0, int(offset))
            # Fetch one extra so the caller can compute has_more
            # without a separate count() — saves one round-trip.
            fetch_count = lim + 1
            result = (
                self.client.table("user_uploaded_files")
                .select("*")
                .eq("user_id", user_id)
                .is_("deleted_at", "null")
                .order("created_at", desc=True)
                .range(off, off + fetch_count - 1)
                .execute()
            )
            rows = result.data or []
            # The deleted_at column may not exist yet during the
            # rollout window. Re-issue the query without the
            # filter so the page keeps working pre-migration.
            return rows
        except Exception as e:
            # Detect the "column doesn't exist" case (migration
            # pending) and retry without the soft-delete filter.
            err_low = str(e).lower()
            if "deleted_at" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "list_user_uploaded_files_for_user: deleted_at "
                    "column missing (run migrations/add_deleted_"
                    "at_to_user_uploaded_files.sql) — falling back "
                    "to unfiltered list user=%s",
                    user_id,
                )
                try:
                    lim = max(1, int(limit))
                    off = max(0, int(offset))
                    fetch_count = lim + 1
                    result = (
                        self.client.table("user_uploaded_files")
                        .select("*")
                        .eq("user_id", user_id)
                        .order("created_at", desc=True)
                        .range(off, off + fetch_count - 1)
                        .execute()
                    )
                    return result.data or []
                except Exception as fallback_err:
                    logger.warning(
                        "list_user_uploaded_files_for_user fallback "
                        "failed user=%s err=%s",
                        user_id, fallback_err,
                    )
                    return []
            logger.warning(
                "list_user_uploaded_files_for_user failed user=%s err=%s",
                user_id, e,
            )
            return []

    def soft_delete_user_uploaded_file(
        self,
        file_id: str,
        user_id: str,
    ) -> Optional[dict]:
        """Owner-scoped soft delete on user_uploaded_files.

        Marks the row with ``deleted_at = NOW()`` instead of
        DELETE'ing — the weekly hard-delete cron sweeps soft-
        deleted rows + their R2 bytes. Two-phase delete:

          (1) admin clicks → row.deleted_at set; the API filters
              it out of the Files list immediately, user-facing
              surfaces stop linking to it.
          (2) ~weekly cron → object removed from R2, row removed
              from DB.

        Owner scope is enforced inline (user_id eq) so a request
        body that targets a different user's file_id with the
        wrong user_id quietly no-ops. Caller must verify the
        admin-context user_id matches the path user_id BEFORE
        calling this — admins delete other users' files, but only
        through the admin-scoped route, which provides the
        authoritative user_id.

        Returns the updated row on success, None on failure or no-
        match. None is sufficient information for the route to
        return 404 — admin doesn't need to distinguish "not yours"
        from "doesn't exist" (existence leak protection).
        """
        if not file_id or not user_id:
            return None
        try:
            from datetime import timezone, datetime
            now_utc = datetime.now(timezone.utc).isoformat()
            result = (
                self.client.table("user_uploaded_files")
                .update({"deleted_at": now_utc})
                .eq("id", file_id)
                .eq("user_id", user_id)
                .is_("deleted_at", "null")
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            err_low = str(e).lower()
            if "deleted_at" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "soft_delete_user_uploaded_file: deleted_at "
                    "column missing (run migrations/add_deleted_"
                    "at_to_user_uploaded_files.sql) file=%s user=%s",
                    file_id, user_id,
                )
                return None
            logger.error(
                "soft_delete_user_uploaded_file failed file=%s "
                "user=%s err=%s",
                file_id, user_id, e,
            )
            return None

    def get_pending_review_session_for_user(
        self,
        user_id: str,
    ) -> Optional[dict]:
        """Return the user's existing pending-admin-review session,
        if any.

        Pending = bound to this user_id AND results_published_at IS
        NULL AND has at least one non-skipped snippet (so a freshly-
        aborted upload that never made it to snippet extraction
        doesn't block new attempts indefinitely).

        Used by upload endpoints (chat/upload-answer + coaching/
        trial-recording) to prevent the user from stacking a
        second session on top of the first while the coach is
        still reviewing. The frontend's PENDING_COACH state should
        already gate the mic, but the backend check is the
        defence-in-depth layer for cases where the frontend is
        stale, the user has two tabs open, or a third-party
        client bypasses the UI.

        Returns the most-recent qualifying session row or None.
        Failure logs + returns None — the caller treats None as
        "no block, proceed with upload" so a transient query
        failure doesn't lock the user out.
        """
        try:
            sessions = (
                self.client.table("v2_sessions")
                .select("id, created_at, status, results_published_at")
                .eq("user_id", user_id)
                .is_("results_published_at", "null")
                .order("created_at", desc=True)
                .limit(10)
                .execute()
                .data
            ) or []
        except Exception as e:
            logger.warning(
                "get_pending_review_session_for_user query failed "
                "uid=%s err=%s — allowing upload to proceed", user_id, e,
            )
            return None

        if not sessions:
            return None

        # Confirm at least one of those sessions has actual snippet
        # content. A session row with zero snippets is either a
        # freshly-aborted upload OR a placeholder created by the
        # endpoint just before snippet extraction failed — neither
        # should block a clean retry.
        session_ids = [s["id"] for s in sessions]
        try:
            snip_rows = (
                self.client.table(SNIPPETS_TABLE)
                .select("session_id")
                .in_("session_id", session_ids)
                .eq("is_skipped", False)
                .limit(50)
                .execute()
                .data
            ) or []
        except Exception as e:
            logger.warning(
                "get_pending_review_session_for_user snippet probe "
                "failed uid=%s err=%s — allowing upload", user_id, e,
            )
            return None

        sessions_with_snippets = {r.get("session_id") for r in snip_rows if r.get("session_id")}
        for s in sessions:
            if s["id"] in sessions_with_snippets:
                return s
        return None

    def set_session_conversation_summary(
        self,
        session_id: str,
        summary: Optional[str],
    ) -> Optional[dict]:
        """Phase A2.1 — persist the rolling interview digest.

        Called by services/conversation_summary.py after each turn.
        Stamps conversation_summary_updated_at so the prompt builder
        can detect staleness.

        Passing ``summary=None`` clears the column — useful for
        admin resets or when graduation invalidates the digest.

        Failure logs + returns None; the caller (the async
        updater) treats a failed persist as "leave previous
        summary in place" rather than blocking the next turn.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            result = (
                self.client.table("v2_sessions")
                .update({
                    "conversation_summary": summary,
                    "conversation_summary_updated_at": (
                        now if summary is not None else None
                    ),
                })
                .eq("id", session_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            err_low = str(e).lower()
            if (
                "conversation_summary" in err_low
                or "pgrst204" in err_low
            ):
                logger.warning(
                    "set_session_conversation_summary: column missing "
                    "(migration pending?) sid=%s", session_id,
                )
                return None
            logger.warning(
                "set_session_conversation_summary failed sid=%s err=%s",
                session_id, e,
            )
            return None

    def get_session_conversation_summary(
        self,
        session_id: str,
    ) -> Optional[dict]:
        """Read the current digest + its updated_at without pulling
        the full session row. Returns ``{summary, updated_at}`` or
        None when the session doesn't exist OR the digest hasn't
        been generated yet (cold-start)."""
        try:
            result = (
                self.client.table("v2_sessions")
                .select("conversation_summary, conversation_summary_updated_at")
                .eq("id", session_id)
                .limit(1)
                .execute()
            )
            data = result.data or []
            if not data:
                return None
            row = data[0]
            summary = (row.get("conversation_summary") or "").strip() or None
            if summary is None:
                return None
            return {
                "summary": summary,
                "updated_at": row.get("conversation_summary_updated_at"),
            }
        except Exception as e:
            logger.warning(
                "get_session_conversation_summary failed sid=%s err=%s",
                session_id, e,
            )
            return None

    # ── Casual Voice Benchmarks (Phase Stress-Contrast / BE-3) ──────
    #
    # Silent acoustic snapshots of the user speaking casually during
    # /v2/chat/query (multipart path). Paired with
    # services.casual_voice_analytics.analyze_casual_audio_async (the
    # daemon-thread writer) and surfaced by compute_stress_contrast
    # below.

    def insert_casual_voice_benchmark(
        self,
        *,
        user_id: str,
        session_id: Optional[str],
        metrics: dict,
        transcript_source: str,
        audio_duration_ms: Optional[int],
        audio_storage_path: Optional[str] = None,
    ) -> Optional[dict]:
        """Persist one casual-voice metrics row. Returns the inserted
        row, or None on any failure (caller is the fire-and-forget
        daemon thread — losing one row is non-fatal).
        """
        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "metrics": metrics,
            "transcript_source": transcript_source,
            "audio_duration_ms": audio_duration_ms,
            "audio_storage_path": audio_storage_path,
        }
        try:
            result = (
                self.client.table("casual_voice_benchmarks")
                .insert(payload)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            err_low = str(e).lower()
            if (
                "casual_voice_benchmarks" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                # Migration not yet applied in this environment —
                # silently no-op so /v2/chat/query keeps working
                # while the table catches up. Production has it; dev
                # branches that pulled the code before running the
                # SQL would otherwise spam Sentry on every chat send.
                logger.warning(
                    "insert_casual_voice_benchmark: table missing "
                    "(migration pending?) user=%s — skipping",
                    user_id,
                )
                return None
            logger.warning(
                "insert_casual_voice_benchmark failed user=%s err=%s",
                user_id, e,
            )
            return None

    def get_recent_casual_voice_metrics(
        self,
        user_id: str,
        limit: int = 5,
    ) -> List[dict]:
        """Last N casual-voice metric blobs for this user, newest
        first. Returns a list of the ``metrics`` JSONB dicts (just
        the metrics, not the wrapping row). Empty list on no rows or
        on failure (caller is the contrast aggregator, which already
        handles the empty case as "not enough samples").
        """
        try:
            result = (
                self.client.table("casual_voice_benchmarks")
                .select("metrics")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(int(limit))
                .execute()
            )
            return [
                r["metrics"]
                for r in (result.data or [])
                if isinstance(r.get("metrics"), dict)
            ]
        except Exception as e:
            logger.warning(
                "get_recent_casual_voice_metrics failed user=%s err=%s",
                user_id, e,
            )
            return []

    def get_recent_published_snippet_metrics(
        self,
        user_id: str,
        limit: int = 5,
    ) -> List[dict]:
        """Last N PUBLISHED charisma_snippets metric blobs for this
        user. "Published" = coach_label IS NOT NULL (admin has
        reviewed and labeled the snippet). This is the "official /
        high-stakes" side of the stress contrast.

        Returns dicts with the same keys
        /v2/user/results/<session_id> exposes:
        {wpm, fillers, pause_ms, dynamic_db, pitch_center, energy}.
        Empty list on failure or no rows.
        """
        try:
            # PM-9: this selected ONLY the six denormalized columns, which are
            # dead on the live path (services/snippet_values) — so every row
            # came back all-NULL and the caller's shared-key check below found
            # nothing, quietly reporting the contrast as underpowered forever.
            # `metrics`, `transcript` and `duration_ms` are what actually hold
            # the values, so they have to be selected for the resolver to work.
            from services.snippet_values import resolve_all
            result = (
                self.client.table(SNIPPETS_TABLE)
                # The six denormalized metric columns are NOT selected: they
                # are always NULL (nothing writes them) and migration 0254
                # drops them, at which point naming one here would make this
                # query error. resolve_all reads the blob; its column lookups
                # simply miss, before and after the drop.
                .select("metrics, transcript, duration_ms, created_at")
                .eq("user_id", user_id)
                .not_.is_("coach_label", "null")
                .order("created_at", desc=True)
                .limit(int(limit))
                .execute()
            )
            return [resolve_all(r) for r in result.data or []]
        except Exception as e:
            logger.warning(
                "get_recent_published_snippet_metrics failed "
                "user=%s err=%s",
                user_id, e,
            )
            return []

    def compute_stress_contrast(
        self,
        user_id: str,
    ) -> Optional[dict]:
        """median(last 5 published snippet metrics) − median(last 5
        casual voice metrics) for the keys that exist on both
        sides.

        Sign convention (PIN; documented in
        docs/PANEL-STATE-MATRIX.md): positive delta means OFFICIAL >
        CASUAL. So +wpm_delta = user speaks faster under pressure
        than when casual = likely a stress tell. Frontend renders
        accordingly.

        Returns None when EITHER side has fewer than 3 samples
        (insufficient signal for a meaningful median). Frontend uses
        None to omit the Stress Contrast section entirely — no
        "not enough data" placeholder.

        Pitch is intentionally OMITTED from the delta in v1:
        ``charisma_snippets.pitch_center`` is in Hz, while
        ``analyze_audio.pitch_center_st`` is in semitones. Comparing
        them directly produces nonsense. A future revision can
        unit-harmonize and add ``pitch_delta_st``.
        """
        import statistics

        official = self.get_recent_published_snippet_metrics(user_id, limit=5)
        casual = self.get_recent_casual_voice_metrics(user_id, limit=5)

        if len(official) < 3 or len(casual) < 3:
            return None

        def _median(rows: List[dict], key: str) -> Optional[float]:
            vals = [
                r.get(key)
                for r in rows
                if isinstance(r.get(key), (int, float))
            ]
            return float(statistics.median(vals)) if vals else None

        deltas: dict = {}
        # Keys that exist on BOTH sides with compatible units.
        # See docstring re: pitch omission.
        for key in ("wpm", "pause_ms", "dynamic_db"):
            o = _median(official, key)
            c = _median(casual, key)
            if o is not None and c is not None:
                deltas[f"{key}_delta"] = round(o - c, 3)

        if not deltas:
            # Samples on both sides but no shared metric keys had
            # numeric values — happens on legacy rows with NULL
            # metric columns. Treat as underpowered.
            return None

        return {
            "samples": {
                "official": len(official),
                "casual": len(casual),
            },
            "deltas": deltas,
            "sign_convention": "positive_delta_means_official_greater_than_casual",
        }

    # ── Coaching Directives Queue (Phase Directives-Queue / BE) ────
    #
    # User-level 5-step coaching arc. Admins POST an ordered list of
    # 5 questions via /v2/admin/users/<id>/directives-queue; the
    # chat / interview surface pops them one at a time via
    # pop_next_directive() and marks each exhausted. When the queue
    # is empty, those surfaces fall back to _generate_llm_question.
    #
    # Replaces the per-user single-question
    # user_settings.queued_override_question (removed in Week-1
    # cleanup) and the conceptually-misplaced snippet-level
    # next_question_1..5 columns (which never shipped to this
    # branch).

    def list_directives_queue(
        self,
        user_id: str,
    ) -> List[dict]:
        """Return the user's current arc, ordered by position ASC.
        Returns empty list when no queue exists OR the table is
        missing (pre-migration env).
        """
        try:
            result = (
                self.client.table("coaching_directives_queue")
                .select(
                    "id, position, intent_tag, question, "
                    "exhausted, created_at, created_by_admin_id"
                )
                .eq("user_id", user_id)
                .order("position", desc=False)
                .execute()
            )
            return list(result.data or [])
        except Exception as e:
            err_low = str(e).lower()
            if (
                "coaching_directives_queue" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                logger.warning(
                    "list_directives_queue: table missing "
                    "(migration pending?) user=%s — returning []",
                    user_id,
                )
                return []
            logger.warning(
                "list_directives_queue failed user=%s err=%s",
                user_id, e,
            )
            return []

    def replace_directives_queue(
        self,
        *,
        user_id: str,
        rows: List[dict],
        admin_user_id: Optional[str],
    ) -> List[dict]:
        """Atomic-ish replace: DELETE existing rows for user_id,
        then INSERT the new arc. Returns the inserted rows on
        success; empty list on failure.

        ``rows`` must each carry ``position`` (1..5), ``intent_tag``
        (non-empty str), ``question`` (non-empty str). The caller
        is responsible for validation; this method just persists
        what it's given.

        Atomicity caveat: Supabase python-postgrest doesn't expose
        BEGIN/COMMIT, so DELETE and INSERT are two HTTP round-trips.
        If the INSERT fails after the DELETE succeeded, the user
        ends up with NO queue — admin will see an empty list on
        the next GET and can re-POST. We log the half-state at
        WARNING so support can spot it. Acceptable for an
        admin-driven workflow (no concurrent writers).
        """
        try:
            (
                self.client.table("coaching_directives_queue")
                .delete()
                .eq("user_id", user_id)
                .execute()
            )
        except Exception as del_err:
            err_low = str(del_err).lower()
            if (
                "coaching_directives_queue" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                logger.warning(
                    "replace_directives_queue: table missing "
                    "(migration pending?) user=%s — skipping",
                    user_id,
                )
                return []
            logger.warning(
                "replace_directives_queue: DELETE failed user=%s err=%s",
                user_id, del_err,
            )
            return []

        if not rows:
            # POST with empty rows == effectively DELETE. Honor
            # silently so the admin UI can implement "clear" via
            # POST [] as an alternative to DELETE.
            return []

        payload = [
            {
                "user_id": user_id,
                "position": int(r["position"]),
                "intent_tag": (r.get("intent_tag") or "").strip(),
                "question": (r.get("question") or "").strip(),
                "exhausted": False,
                "created_by_admin_id": admin_user_id,
            }
            for r in rows
        ]
        try:
            result = (
                self.client.table("coaching_directives_queue")
                .insert(payload)
                .execute()
            )
            return list(result.data or [])
        except Exception as ins_err:
            logger.error(
                "replace_directives_queue: INSERT failed AFTER "
                "successful DELETE user=%s err=%s — user now has "
                "EMPTY queue; admin should re-POST",
                user_id, ins_err,
            )
            return []

    def clear_directives_queue(self, user_id: str) -> bool:
        """Delete the user's current arc. Returns True on success
        (including the "nothing to delete" case), False on real
        failure. Idempotent — calling on an empty queue is a no-op
        success.
        """
        try:
            (
                self.client.table("coaching_directives_queue")
                .delete()
                .eq("user_id", user_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if (
                "coaching_directives_queue" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                logger.warning(
                    "clear_directives_queue: table missing "
                    "(migration pending?) user=%s — treating as "
                    "no-op success",
                    user_id,
                )
                return True
            logger.warning(
                "clear_directives_queue failed user=%s err=%s",
                user_id, e,
            )
            return False

    def pop_next_directive(
        self,
        user_id: str,
    ) -> Optional[dict]:
        """Atomic-ish: find the lowest-position un-exhausted row
        for ``user_id``, mark it exhausted, return its
        ``{id, position, intent_tag, question}``. Returns None when
        the queue is empty OR fully exhausted OR the table is
        missing.

        Atomicity caveat: SELECT then UPDATE on two HTTP calls.
        Race window between them = "if two next-question requests
        for the same user fire in parallel, both might consume the
        same row." Acceptable today because: (a) chat & interview
        surfaces are user-driven and serial per session; (b) an
        admin watching this in production can re-POST if the queue
        gets weirdly out of order. If we ever need stricter
        guarantees, promote to an RPC stored function with
        SELECT ... FOR UPDATE SKIP LOCKED.

        Called from the next-question splice in /v2/user/chat/
        first-question and /v2/public/interview/next-question
        BEFORE the LLM fallback. (The legacy queued_override_question
        consumer was removed in the Week-1 cleanup.)
        """
        try:
            picked = (
                self.client.table("coaching_directives_queue")
                .select("id, position, intent_tag, question")
                .eq("user_id", user_id)
                .eq("exhausted", False)
                .order("position", desc=False)
                .limit(1)
                .execute()
            )
            rows = picked.data or []
            if not rows:
                return None
            row = rows[0]
        except Exception as sel_err:
            err_low = str(sel_err).lower()
            if (
                "coaching_directives_queue" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                # Table not yet present — silently fall through to
                # legacy / LLM path so the next-question handler
                # doesn't 500 just because the migration is
                # pending.
                return None
            logger.warning(
                "pop_next_directive: select failed user=%s err=%s "
                "— falling through",
                user_id, sel_err,
            )
            return None

        try:
            (
                self.client.table("coaching_directives_queue")
                .update({"exhausted": True})
                .eq("id", row["id"])
                .execute()
            )
        except Exception as upd_err:
            # The UPDATE failed but we already have the row in
            # memory. Returning it means the chat surface will use
            # this question — but the row is still flagged
            # un-exhausted in the DB, so the NEXT turn will also
            # pick the same row. Worse than dropping the row.
            # Safer: log + return None, let the LLM fallback fire.
            logger.warning(
                "pop_next_directive: mark-exhausted failed "
                "user=%s row=%s err=%s — falling through to LLM "
                "to avoid double-firing the same directive",
                user_id, row.get("id"), upd_err,
            )
            return None

        return {
            "id": row.get("id"),
            "position": row.get("position"),
            "intent_tag": row.get("intent_tag"),
            "question": row.get("question"),
        }

    def set_session_predictions(
        self,
        session_id: str,
        *,
        ai_predicted_session_comment: Optional[str],
        ai_predicted_next_question: Optional[str] = None,
        ai_predicted_next_questions: Optional[list] = None,
    ) -> Optional[dict]:
        """Persist pre-generated AI predictions on the session row.

        Called by services.session_predictions during finalize so
        the admin opens the user-detail page to a pre-filled
        comment + next-question(s) they can accept or edit. Stamps
        ai_predictions_generated_at so the UI can surface "this is
        N hours old, regenerate?" when metrics drift.

        ``ai_predicted_next_questions`` is the NEW 5-position
        ordered script — list of {position, text, intent_tag}.
        ``ai_predicted_next_question`` is kept for back-compat
        with the old single-question admin UI; if the array is
        provided but the single field isn't, we derive the single
        field from position-1 so legacy callers keep working.

        Gracefully degrades if the new JSONB column doesn't exist
        yet (migration pending) — retries the update without it
        and logs a warning, so existing admin tooling still saves
        the comment + single question.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            # Derive single-question back-compat value when only
            # the array was passed.
            single_q = ai_predicted_next_question
            if single_q is None and ai_predicted_next_questions:
                try:
                    first = ai_predicted_next_questions[0]
                    if isinstance(first, dict):
                        single_q = (first.get("text") or "").strip() or None
                except (IndexError, AttributeError, TypeError):
                    single_q = None

            patch: dict = {
                "ai_predicted_session_comment": ai_predicted_session_comment,
                "ai_predicted_next_question": single_q,
                "ai_predictions_generated_at": now,
            }
            if ai_predicted_next_questions is not None:
                patch["ai_predicted_next_questions"] = ai_predicted_next_questions

            result = (
                self.client.table("v2_sessions")
                .update(patch)
                .eq("id", session_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            err_low = str(e).lower()
            if (
                "ai_predicted_next_questions" in err_low
                or "pgrst204" in err_low
            ):
                # New JSONB column missing in this environment —
                # retry without it so the comment + single-question
                # back-compat path still saves.
                logger.warning(
                    "set_session_predictions: array column missing "
                    "(migration pending?), retrying without — sid=%s",
                    session_id,
                )
                try:
                    fallback = {
                        "ai_predicted_session_comment": ai_predicted_session_comment,
                        "ai_predicted_next_question": single_q,
                        "ai_predictions_generated_at": now,
                    }
                    result = (
                        self.client.table("v2_sessions")
                        .update(fallback)
                        .eq("id", session_id)
                        .execute()
                    )
                    if result.data and len(result.data) > 0:
                        return result.data[0]
                    return None
                except Exception as e2:
                    logger.warning(
                        "set_session_predictions fallback failed sid=%s err=%s",
                        session_id, e2,
                    )
                    return None
            logger.warning(
                "set_session_predictions failed sid=%s err=%s",
                session_id, e,
            )
            return None

    def set_session_final_next_questions(
        self,
        session_id: str,
        questions: Optional[list],
    ) -> Optional[dict]:
        """Save the admin-edited 5-question script on Publish.

        ``questions`` is a list of {position, text, intent_tag?}
        dicts (length ≤ 5) or None to clear. Idempotent — same
        list saved twice is a no-op. Failure logs + returns None
        so the publish itself isn't blocked.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            result = (
                self.client.table("v2_sessions")
                .update({
                    "final_human_next_questions": questions,
                    "updated_at": now,
                })
                .eq("id", session_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            err_low = str(e).lower()
            if (
                "final_human_next_questions" in err_low
                or "pgrst204" in err_low
            ):
                logger.warning(
                    "set_session_final_next_questions: column missing "
                    "(migration pending?) sid=%s",
                    session_id,
                )
                return None
            logger.warning(
                "set_session_final_next_questions failed sid=%s err=%s",
                session_id, e,
            )
            return None

    def get_session_predictions(self, session_id: str) -> Optional[dict]:
        """Read the (predicted_comment, predicted_question,
        generated_at) trio without pulling the full session row.

        Returns ``None`` when the session doesn't exist or has
        never had predictions generated. The publish handler uses
        this to recover the AI prediction it needs to log
        alongside the human's final.
        """
        try:
            result = (
                self.client.table("v2_sessions")
                .select(
                    "id, ai_predicted_session_comment, "
                    "ai_predicted_next_question, "
                    "ai_predictions_generated_at"
                )
                .eq("id", session_id)
                .limit(1)
                .execute()
            )
            data = result.data or []
            return data[0] if data else None
        except Exception as e:
            logger.warning(
                "get_session_predictions failed sid=%s err=%s",
                session_id, e,
            )
            return None

    def insert_admin_annotation_log(
        self,
        *,
        user_id: str,
        session_id: str,
        ai_predicted_comment: Optional[str],
        ai_predicted_question: Optional[str],
        final_human_comment: Optional[str],
        final_human_question: Optional[str],
        was_corrected: bool,
        question_position: Optional[int] = None,
        intent_tag: Optional[str] = None,
        surface: Optional[str] = None,
    ) -> Optional[dict]:
        """Write one RLHF training row to admin_annotations_log.

        Called from the admin Publish handler and the session-
        level KPI narrative PATCH handler. Returns the inserted
        row or None on failure — failure logs but does NOT raise
        to the route, because the publish / save itself has
        already succeeded by the time we write the log and we
        won't undo it for a training-pipeline side-effect.

        ``question_position`` (1..5) + ``intent_tag`` are set
        for the per-position rows that capture each Director's
        Script question's (predicted, final) pair. Left NULL for
        the session-level admin_comment row and for legacy
        single-question rows.

        ``surface`` tags the write path so downstream RLHF
        analytics can filter by edit type. Values currently
        emitted:
          "session_kpi_narrative"  — PATCH /kpi-narrative
          "publish_session_comment" — publish's session-level row
          "publish_question_p1".."p5" — publish's per-position rows
        None when the column is missing (graceful fallback below)
        or when an unmigrated caller doesn't set it.

        Graceful fallback when per-position / surface columns
        aren't in the schema yet (migration pending): retries the
        insert without them. The session-level signal still
        lands; the missing-column granularity just isn't
        available until the matching migration runs.
        """
        try:
            payload: dict = {
                "user_id": user_id,
                "session_id": session_id,
                "ai_predicted_comment": ai_predicted_comment,
                "ai_predicted_question": ai_predicted_question,
                "final_human_comment": final_human_comment,
                "final_human_question": final_human_question,
                "was_corrected": bool(was_corrected),
            }
            if question_position is not None:
                payload["question_position"] = int(question_position)
            if intent_tag is not None:
                payload["intent_tag"] = intent_tag
            if surface is not None:
                payload["surface"] = surface

            result = (
                self.client.table("admin_annotations_log")
                .insert(payload)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            err_low = str(e).lower()
            if (
                "question_position" in err_low
                or "intent_tag" in err_low
                or "surface" in err_low
                or "pgrst204" in err_low
            ):
                logger.warning(
                    "insert_admin_annotation_log: optional column(s) "
                    "missing (migration pending?), retrying without — "
                    "sid=%s pos=%s surface=%s",
                    session_id, question_position, surface,
                )
                try:
                    fallback = {
                        k: v for k, v in payload.items()
                        if k not in (
                            "question_position",
                            "intent_tag",
                            "surface",
                        )
                    }
                    result = (
                        self.client.table("admin_annotations_log")
                        .insert(fallback)
                        .execute()
                    )
                    if result.data and len(result.data) > 0:
                        return result.data[0]
                    return None
                except Exception as e2:
                    logger.warning(
                        "insert_admin_annotation_log fallback failed sid=%s err=%s",
                        session_id, e2,
                    )
                    return None
            logger.warning(
                "insert_admin_annotation_log failed sid=%s uid=%s err=%s",
                session_id, user_id, e,
            )
            return None

    def promote_ai_drafts_to_admin_comments(self, session_id: str) -> int:
        """Copy ai_draft_admin_comment → admin_comment for every snippet
        in ``session_id`` that has a draft but no human comment yet.

        Used by the auto-publish flow for coaching trial recordings —
        there's no admin in the loop to review drafts, so we ship the
        AI's first take as the comment. Existing admin_comment rows
        are NOT overwritten (idempotent: a manual review later wins
        over a previous auto-promotion if the admin edits the row).

        Returns the number of rows promoted. Zero is a valid outcome:
        snippets without drafts, or already-commented rows, both fall
        outside the filter.
        """
        try:
            # PostgREST has no UPDATE … FROM, so we read first then
            # write per-row. The N here is bounded by snippets-per-
            # session (typically 1-5 for a trial recording) so the
            # extra round-trip cost is fine.
            sel = (
                self.client.table(SNIPPETS_TABLE)
                .select("id, ai_draft_admin_comment, admin_comment")
                .eq("session_id", session_id)
                .execute()
            )
            candidates = sel.data or []
            promoted = 0
            now = datetime.now(timezone.utc).isoformat()
            for row in candidates:
                existing = (row.get("admin_comment") or "").strip()
                if existing:
                    continue
                draft = (row.get("ai_draft_admin_comment") or "").strip()
                if not draft:
                    continue
                try:
                    (
                        self.client.table(SNIPPETS_TABLE)
                        .update({
                            "admin_comment": draft,
                            "updated_at": now,
                        })
                        .eq("id", row["id"])
                        .execute()
                    )
                    promoted += 1
                except Exception as upd_err:
                    logger.warning(
                        "promote_ai_drafts: row update failed sid=%s sn=%s err=%s",
                        session_id, row["id"], upd_err,
                    )
            return promoted
        except Exception as e:
            logger.warning(
                "promote_ai_drafts_to_admin_comments failed sid=%s: %s",
                session_id, e,
            )
            return 0

    def set_charisma_snippet_ai_draft_comment(
        self,
        snippet_id: str,
        draft: str | None,
    ) -> bool:
        """Persist an AI-suggested admin_comment draft on a charisma snippet.

        Phase 10. Written once when the snippet is first extracted; the
        admin then keeps it, edits it, or replaces it via the normal
        admin_comment save path. The draft column is intentionally
        immutable from the admin UI — at publish time we compare
        admin_comment vs this column to emit the RLHF pair.

        Returns True on success. Failure logs + returns False so the
        snippet pipeline that triggered this can keep running.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            (
                self.client.table(SNIPPETS_TABLE)
                .update({
                    "ai_draft_admin_comment": draft,
                    "ai_draft_admin_comment_generated_at": now,
                    "updated_at": now,
                })
                .eq("id", snippet_id)
                .execute()
            )
            return True
        except Exception as e:
            logger.warning(
                "set_charisma_snippet_ai_draft_comment failed %s: %s",
                snippet_id, e,
            )
            return False

    def set_charisma_snippet_ai_draft_coach_note(
        self,
        snippet_id: str,
        draft: str | None,
    ) -> bool:
        """Persist the AI-Commentator coach-note draft on a charisma snippet,
        FROZEN: written only when ai_draft_coach_note is currently NULL, so a
        re-process never overwrites a draft the coach is already editing
        against (preserves the (draft, coach-final) diff). willab Phase 4 /
        Prompt 2. Returns True on a write, False on skip/failure (best-effort;
        the drafting pipeline keeps running)."""
        try:
            existing = (
                self.client.table(SNIPPETS_TABLE)
                .select("ai_draft_coach_note")
                .eq("id", snippet_id)
                .limit(1)
                .execute()
            )
            rows = existing.data or []
            if rows and (rows[0].get("ai_draft_coach_note") or "").strip():
                return False  # frozen — already has a draft
            now = datetime.now(timezone.utc).isoformat()
            (
                self.client.table(SNIPPETS_TABLE)
                .update({
                    "ai_draft_coach_note": draft,
                    "ai_draft_coach_note_generated_at": now,
                    "updated_at": now,
                })
                .eq("id", snippet_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "ai_draft_coach_note" in err_low and (
                "does not exist" in err_low or "pgrst204" in err_low
            ):
                logger.warning(
                    "set_charisma_snippet_ai_draft_coach_note: column missing "
                    "(run migrations/add_ai_draft_coach_note.sql)",
                )
                return False
            logger.warning(
                "set_charisma_snippet_ai_draft_coach_note failed %s: %s",
                snippet_id, e,
            )
            return False

    def set_charisma_snippet_say_it_stronger(
        self,
        snippet_id: str,
        payload: Optional[dict],
    ) -> bool:
        """Persist the 'Say It Stronger' suggestion on a charisma snippet,
        write-once (only when say_it_stronger is currently NULL) so duplicate
        daemon runs are idempotent. Best-effort — missing column (run
        migrations/add_say_it_stronger.sql) or any error returns False and
        never breaks the generation loop."""
        if not snippet_id or not isinstance(payload, dict):
            return False
        try:
            existing = (
                self.client.table(SNIPPETS_TABLE)
                .select("say_it_stronger")
                .eq("id", snippet_id)
                .limit(1)
                .execute()
            )
            rows = existing.data or []
            if rows and rows[0].get("say_it_stronger"):
                return False  # write-once — already generated
            (
                self.client.table(SNIPPETS_TABLE)
                .update({"say_it_stronger": payload})
                .eq("id", snippet_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "say_it_stronger" in err_low and (
                "does not exist" in err_low or "pgrst204" in err_low
            ):
                logger.warning(
                    "set_charisma_snippet_say_it_stronger: column missing "
                    "(run migrations/add_say_it_stronger.sql)",
                )
                return False
            logger.warning(
                "set_charisma_snippet_say_it_stronger failed %s: %s",
                snippet_id, e,
            )
            return False

    def set_charisma_snippet_say_it_stronger_final(
        self,
        snippet_id: str,
        payload: Optional[dict],
    ) -> bool:
        """Persist the COACH-corrected 'Say It Stronger' card (Engine 1,
        founder 2026-07-11). Plain update — RE-editable (unlike the write-once
        auto draft; the coach may revise until publish). Best-effort — missing
        column (run migrations/add_say_it_stronger_final.sql) → False."""
        if not snippet_id or not isinstance(payload, dict):
            return False
        try:
            (
                self.client.table(SNIPPETS_TABLE)
                .update({"say_it_stronger_final": payload})
                .eq("id", snippet_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "say_it_stronger_final" in err_low and (
                "does not exist" in err_low or "pgrst204" in err_low
            ):
                logger.warning(
                    "set_charisma_snippet_say_it_stronger_final: column "
                    "missing (run migrations/add_say_it_stronger_final.sql)",
                )
                return False
            logger.warning(
                "set_charisma_snippet_say_it_stronger_final failed %s: %s",
                snippet_id, e,
            )
            return False

    def get_ai_draft_coach_notes_by_session(self, session_id: str) -> dict:
        """{snippet_id: ai_draft_coach_note} for a session — the AI-Commentator
        pre-fills the coach read serves. Coach-only. {} on missing column/table
        (pre-migration → coach sees blank fields, same as today)."""
        if not session_id:
            return {}
        try:
            res = (
                self.client.table(SNIPPETS_TABLE)
                .select("id, ai_draft_coach_note")
                .eq("session_id", session_id)
                .execute()
            )
            return {
                str(r.get("id")): r.get("ai_draft_coach_note")
                for r in (res.data or [])
                if r.get("ai_draft_coach_note")
            }
        except Exception as e:
            if "ai_draft_coach_note" in str(e).lower():
                return {}
            logger.warning(
                "get_ai_draft_coach_notes_by_session failed sid=%s: %s",
                session_id, e,
            )
            return {}

    def set_charisma_snippet_ai_draft_follow_up(
        self,
        snippet_id: str,
        draft: str | None,
    ) -> bool:
        """Persist the original AI-generated follow_up_question, frozen.

        Phase 10. follow_up_question itself may be edited by the admin
        — this column preserves the pre-edit version so the publish-
        time annotation can pair the two.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            (
                self.client.table(SNIPPETS_TABLE)
                .update({
                    "ai_draft_follow_up_question": draft,
                    "ai_draft_follow_up_question_generated_at": now,
                    "updated_at": now,
                })
                .eq("id", snippet_id)
                .execute()
            )
            return True
        except Exception as e:
            logger.warning(
                "set_charisma_snippet_ai_draft_follow_up failed %s: %s",
                snippet_id, e,
            )
            return False

    def record_snippet_publish_annotations(
        self,
        *,
        session_id: str,
        admin_user_id: str,
    ) -> int:
        """Emit RLHF annotation events for every snippet in a session.

        Phase 10 — fires once per session at publish time. For each
        snippet that has an ai_draft_* column populated, write one
        admin_annotation_events row comparing the draft to the final
        admin-typed value:

          - draft == final  → reason_chip='approved_as_is', both
            ai_original_text and coach_final_text = the draft. Signal:
            this AI suggestion was good enough to ship unedited.
          - draft != final  → ai_original_text=draft,
            coach_final_text=final, no reason_chip. Signal: admin
            corrected the AI; the diff is the lesson.

        Field_names that emit: 'admin_comment', 'follow_up_question',
        'evaluator_rationale', 'say_it_stronger' (charisma_snippets),
        'coach_note' (charisma draft vs coach_snippet_drafts.note), and
        'coach_label_notes' (stress_snippets).

        'say_it_stronger' (founder 2026-07-27, learning-pipeline item 2):
        the draft is the auto card (charisma_snippets.say_it_stronger),
        the final is the coach's corrected card (say_it_stronger_final) —
        both serialized as canonical JSON with the volatile stamps
        (model / generated_at / version / edited_by_coach) stripped, so
        "approved as-is" means the CONTENT matched, not the metadata.

        Idempotency (review finding 2026-07-28 — mattered the moment the
        dead emitter was repaired, see _emit_publish_event_if_signal): the
        table has no unique constraint, and re-publish IS a real flow on the
        publish route, so this now probes for existing publish-path rows and
        SKIPS the whole capture when the session was already captured — the
        same never-double-write-on-uncertainty rule as
        scripts/backfill_few_shot_annotations.py. Trade-off, accepted there
        and here: a correction made between publish and re-publish is not
        re-captured; a corrupted corpus (approved_as_is AND a correction for
        the same field) is worse than a missed pair.

        Returns total events written.
        """
        events_written = 0

        if self._publish_annotations_already_captured(session_id):
            logger.info(
                "record_snippet_publish_annotations: session %s already "
                "captured — skipping (idempotency probe)", session_id,
            )
            return 0

        # The student the session belongs to — admin_annotation_events.user_id
        # is NOT NULL (the corpus is per-student), so without an owner nothing
        # can be written and every emit below will skip with a warning.
        owner_user_id: Optional[str] = None
        try:
            _sess = self.v2_get_session_by_id(str(session_id)) or {}
            if _sess.get("user_id"):
                owner_user_id = str(_sess["user_id"])
        except Exception as e:
            logger.warning(
                "record_snippet_publish_annotations: owner lookup failed "
                "session=%s: %s", session_id, e,
            )

        # ── Charisma side ──────────────────────────────────────────
        # Column tiers degrade gracefully pre-migration, ONE migration's
        # columns per step (review finding: a coarser ladder silently dropped
        # the whole say-it-stronger capture when only the *_final migration
        # was unrun): full → minus say_it_stronger_final → minus both SiS
        # columns → legacy minus ai_draft_coach_note. EVERY tier failure is
        # logged (a transient error that falls through must be visible —
        # publish-time capture fires once per session, so a silent drop loses
        # those pairs permanently).
        _CHARISMA_TIERS = (
            "id, admin_comment, ai_draft_admin_comment, "
            "follow_up_question, ai_draft_follow_up_question, "
            "follow_up_outcome, ai_draft_coach_note, "
            "say_it_stronger, say_it_stronger_final",
            "id, admin_comment, ai_draft_admin_comment, "
            "follow_up_question, ai_draft_follow_up_question, "
            "follow_up_outcome, ai_draft_coach_note, say_it_stronger",
            "id, admin_comment, ai_draft_admin_comment, "
            "follow_up_question, ai_draft_follow_up_question, "
            "follow_up_outcome, ai_draft_coach_note",
            "id, admin_comment, ai_draft_admin_comment, "
            "follow_up_question, ai_draft_follow_up_question, "
            "follow_up_outcome",
        )
        charisma_rows: list = []
        for _tier, _cols in enumerate(_CHARISMA_TIERS):
            try:
                charisma_rows = (
                    self.client.table(SNIPPETS_TABLE)
                    .select(_cols)
                    .eq("session_id", session_id)
                    .execute()
                    .data
                ) or []
                break
            except Exception as e:
                logger.warning(
                    "record_snippet_publish_annotations: charisma select "
                    "tier %d failed session=%s: %s%s",
                    _tier, session_id, e,
                    "" if _tier == len(_CHARISMA_TIERS) - 1
                    else " — trying the next tier",
                )
                charisma_rows = []

        # willab Phase 4 / Prompt 2 — coach-note comment-clone pair. The draft
        # lives on charisma_snippets.ai_draft_coach_note; the coach's FINAL note
        # lives in coach_snippet_drafts.note (a different table). Capture only
        # when a draft existed (that's the (draft, coach-final) training pair).
        try:
            coach_notes_map = {
                str(d.get("snippet_id")): d.get("note")
                for d in (self.get_coach_snippet_drafts(session_id) or [])
                if d.get("snippet_id")
            }
        except Exception:
            coach_notes_map = {}

        for row in charisma_rows:
            snippet_id = row.get("id")
            if not snippet_id:
                continue
            events_written += self._emit_publish_event_if_signal(
                session_id=session_id,
                admin_user_id=admin_user_id,
                section_type="charisma_snippet",
                field_name="admin_comment",
                draft=row.get("ai_draft_admin_comment"),
                final=row.get("admin_comment"),
                draft_id=str(snippet_id),
                owner_user_id=owner_user_id,
            )
            events_written += self._emit_publish_event_if_signal(
                session_id=session_id,
                admin_user_id=admin_user_id,
                section_type="charisma_snippet",
                field_name="follow_up_question",
                draft=row.get("ai_draft_follow_up_question"),
                final=row.get("follow_up_question"),
                draft_id=str(snippet_id),
                owner_user_id=owner_user_id,
            )

            # coach-note (draft, coach-final) pair — only when an AI draft
            # existed for this snippet (the comment-clone corpus).
            if (row.get("ai_draft_coach_note") or "").strip():
                events_written += self._emit_publish_event_if_signal(
                    session_id=session_id,
                    admin_user_id=admin_user_id,
                    section_type="coach_note",
                    field_name="coach_note",
                    draft=row.get("ai_draft_coach_note"),
                    final=coach_notes_map.get(str(snippet_id)),
                    draft_id=str(snippet_id),
                    owner_user_id=owner_user_id,
                )

            # Say-It-Stronger (draft, coach-final) pair (founder 2026-07-27,
            # learning-pipeline item 2). The auto card and the coach's
            # corrected card already sit side-by-side on the row ("the future
            # correction corpus", add_say_it_stronger_final.sql) — this makes
            # them an actual training pair. Serialized as canonical JSON with
            # volatile stamps stripped. Three shapes (review finding: the
            # final-only case was originally dropped):
            #   draft only        → rode to the student unedited →
            #                       approved_as_is (publish implies review,
            #                       same convention as admin_comment)
            #   draft + final     → the correction pair
            #   final only        → coach wrote the card from scratch (the
            #                       draft never generated) → empty-draft pair
            _sis_draft = _sis_annotation_text(row.get("say_it_stronger"))
            _sis_final = _sis_annotation_text(row.get("say_it_stronger_final"))
            if _sis_draft or _sis_final:
                events_written += self._emit_publish_event_if_signal(
                    session_id=session_id,
                    admin_user_id=admin_user_id,
                    section_type="charisma_snippet",
                    field_name="say_it_stronger",
                    draft=_sis_draft,
                    final=_sis_final or _sis_draft,
                    draft_id=str(snippet_id),
                    owner_user_id=owner_user_id,
                )

            # Phase 14.x — evaluator rationale review. Gated on
            # admin_reviewed_at so we don't fire spurious "approved
            # as-is" signal for rationales the admin never looked at.
            # When admin reviewed: draft = AI's rationale, final =
            # admin_corrected_rationale OR (fall back to AI rationale
            # when admin approved verbatim). _emit_publish_event_if_
            # signal then assigns reason_chip="approved_as_is" or
            # null exactly like the other two fields.
            outcome = row.get("follow_up_outcome")
            evaluator = (
                outcome.get("evaluator")
                if isinstance(outcome, dict) else None
            )
            if isinstance(evaluator, dict) and evaluator.get(
                "admin_reviewed_at"
            ):
                ai_rationale = (evaluator.get("rationale") or "").strip()
                admin_correction = (
                    (evaluator.get("admin_corrected_rationale") or "")
                    .strip()
                    or None
                )
                events_written += self._emit_publish_event_if_signal(
                    session_id=session_id,
                    admin_user_id=admin_user_id,
                    section_type="charisma_snippet",
                    field_name="evaluator_rationale",
                    draft=ai_rationale,
                    final=admin_correction or ai_rationale,
                    draft_id=str(snippet_id),
                    owner_user_id=owner_user_id,
                )

        # ── Stress side: REMOVED 2026-08-10 ───────────────────────
        # This walked the session's recordings to find stress_snippets
        # and emit a publish event per (ai_draft_coach_notes ->
        # coach_label_notes) pair. stress_snippets is now retired-in-
        # place: nothing writes it (the label writer went in #368, the
        # draft writer with this change), so the block could only ever
        # re-read frozen historical rows and cost two queries on every
        # publish to find nothing new.
        #
        # "coach_label_notes" STAYS in _PUBLISH_CAPTURE_FIELDS below on
        # purpose: events written before today carry that field name, and
        # the idempotency probe keys on the tuple. Dropping it would make
        # the backfill unable to recognise its own prior writes.

        return events_written

    # The field_names the publish-time capture emits — the idempotency probe
    # keys on these. KEEP IN SYNC with scripts/backfill_few_shot_annotations
    # (_PUBLISH_PATH_FIELDS): a field emitted here but missing there lets the
    # backfill double-write it.
    _PUBLISH_CAPTURE_FIELDS = (
        "admin_comment", "follow_up_question", "coach_note",
        "evaluator_rationale", "coach_label_notes", "say_it_stronger",
    )

    def _publish_annotations_already_captured(self, session_id: str) -> bool:
        """Has this session already emitted publish-path annotation rows?

        The never-double-write-on-uncertainty rule (mirrors the backfill's
        probe): a probe FAILURE reads as "already captured", because writing
        blind risks the corpus (approved_as_is + a correction for the same
        field), while skipping only loses one session's pairs."""
        try:
            rows = (
                self.client.table("admin_annotation_events")
                .select("id")
                .eq("session_id", str(session_id))
                .in_("field_name", list(self._PUBLISH_CAPTURE_FIELDS))
                .limit(1)
                .execute()
                .data
            ) or []
            return bool(rows)
        except Exception as e:
            logger.warning(
                "record_snippet_publish_annotations: idempotency probe "
                "failed session=%s: %s — treating as captured (never "
                "double-write on uncertainty)", session_id, e,
            )
            return True

    def has_ideal_text_annotations(self, arc_uuid: Optional[str]) -> bool:
        """Any ideal-text annotation rows for this arc yet?

        The idempotency probe for the APPROVE-route capture hook: the shipped
        FE's Verify button posts /ideal-text/approve (never /verify), and
        approve has no re-approve guard — so its capture fires only when this
        probe finds nothing. First approve captures; re-approves skip. The
        /verify route keeps its own per-VERSION exactly-once and does not use
        this probe. Probe failure → True (never double-write on
        uncertainty)."""
        if not arc_uuid:
            return True
        try:
            rows = (
                self.client.table("admin_annotation_events")
                .select("id")
                .eq("draft_id", str(arc_uuid))
                .in_("field_name", ["ideal_text_sentence", "ideal_text_block"])
                .limit(1)
                .execute()
                .data
            ) or []
            return bool(rows)
        except Exception as e:
            logger.warning(
                "has_ideal_text_annotations: probe failed arc=%s: %s — "
                "treating as captured", arc_uuid, e,
            )
            return True

    def _emit_publish_event_if_signal(
        self,
        *,
        session_id: str,
        admin_user_id: str,
        section_type: str,
        field_name: str,
        draft: str | None,
        final: str | None,
        draft_id: str | None,
        owner_user_id: str | None = None,
    ) -> int:
        """Fire one admin_annotation_events row if there's signal to capture.

        Returns 1 when an event was written, 0 when both draft and
        final were empty (no signal) or the insert raised.

        REPAIR 2026-07-27: this called ``self.insert_admin_annotation_event``
        — a method that has never existed in any commit (the real helper is
        ``create_admin_annotation_event``) — with ``user_id=None`` against the
        table's ``user_id UUID NOT NULL``. The AttributeError was swallowed by
        the except below, so EVERY publish-time RLHF capture silently wrote
        zero rows since it shipped. The tests never caught it because they
        patch ``record_snippet_publish_annotations`` wholesale. Hence
        ``owner_user_id`` (the student the session belongs to) is now required
        for a write: without it the insert would 23502 anyway, so we skip
        loudly instead of pretending.
        """
        d = (draft or "").strip()
        f = (final or "").strip()
        if not d and not f:
            return 0
        if not owner_user_id:
            logger.warning(
                "record_snippet_publish_annotations: no owner user_id — "
                "skipping emit session=%s field=%s", session_id, field_name,
            )
            return 0
        # Detect "approved as-is" vs "edited" with case-insensitive
        # whitespace-collapsed comparison so trivial differences don't
        # generate false correction signal.
        norm_d = " ".join(d.split()).lower()
        norm_f = " ".join(f.split()).lower()
        if d and norm_d == norm_f:
            reason_chip = "approved_as_is"
        else:
            reason_chip = None
        try:
            self.create_admin_annotation_event(
                user_id=str(owner_user_id),
                session_id=session_id,
                section_type=section_type,
                field_name=field_name,
                ai_original_text=(d or None),
                coach_final_text=(f or None),
                reason_chip=reason_chip,
                custom_reason=None,
                created_by=admin_user_id,
                draft_id=draft_id,
            )
            return 1
        except Exception as e:
            logger.warning(
                "record_snippet_publish_annotations: emit failed "
                "session=%s field=%s: %s",
                session_id, field_name, e,
            )
            return 0

    def get_user_company_id(self, user_id: str) -> Optional[str]:
        """Lookup the user's company_id from user_settings.

        Returns None when:
          - the row doesn't exist (user never edited any setting), OR
          - the column isn't migrated yet (PGRST204), OR
          - the value is genuinely NULL (user in personal sandbox).
        Callers must treat all three uniformly — no company == personal
        sandbox, snippet retrieval scoped to viewer only.
        """
        try:
            result = (
                self.client.table("user_settings")
                .select("company_id")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return (result.data[0].get("company_id") or None)
            return None
        except Exception as e:
            logger.warning("get_user_company_id failed for %s: %s", user_id, e)
            return None

    def log_few_shot_retrieval(
        self,
        *,
        user_id: str,
        requesting_snippet_id: Optional[str],
        exemplar_snippet_ids: List[str],
        intent: str,
        scope_mode: str,
        company_id: Optional[str],
    ) -> None:
        """Fire-and-forget audit log entry for a few-shot retrieval.

        Compliance + telemetry. ``scope_mode`` documents the rollout
        path:
          - 'cross_tenant_legacy' — flag off, pre-Phase-1 behaviour
          - 'tenant_scoped'      — flag on, viewer has a company_id
          - 'canonical_topup'    — flag on, no company / cold start;
                                     limited to canonical rows
        Failures swallow — the retrieval already happened in memory
        and we don't want an audit-log write to delay the LLM call.
        """
        try:
            self.client.table("few_shot_retrievals").insert({
                "user_id": user_id,
                "requesting_snippet_id": requesting_snippet_id,
                "exemplar_snippet_ids": list(exemplar_snippet_ids),
                "intent": intent,
                "scope_mode": scope_mode,
                "company_id": company_id,
            }).execute()
        except Exception as e:
            logger.warning("log_few_shot_retrieval failed: %s", e)

    def insert_coaching_attempt(
        self,
        *,
        snippet_id: str,
        user_id: str,
        source: str,
        score: float | None,
        components: dict | None,
        question_text: str | None,
        user_answer_text: str | None,
        user_answer_duration_ms: int | None,
        user_answer_word_count: int | None,
        rationale: str | None,
        is_eligible_for_few_shot: bool = True,
        fact_check: dict | None = None,
        evaluator_model: str | None = None,
        acoustic_features: dict | None = None,
        entities: dict | None = None,
        skill_id: str | None = None,
        raw_outcome: dict | None = None,
    ) -> Optional[dict]:
        """Append a new row to coaching_attempts for ``snippet_id``.

        Phase 2 of the snippet-CTA learning loop. Every contextual
        turn-1 evaluation produces ONE row here — so a snippet that's
        been re-attempted N times has N rows, ordered by
        ``attempt_number``.

        ``attempt_number`` is derived via read-then-insert: we read
        ``COALESCE(MAX(attempt_number), 0) + 1`` and write that value.
        The UNIQUE(snippet_id, attempt_number) constraint is the race
        safety net — if two daemon threads pick the same number
        simultaneously, the second write raises and we retry once
        with MAX+1 recomputed. Beyond one retry we give up (extreme
        write contention isn't expected: outcome capture is spawned
        from the upload endpoint per user-action).

        Failure modes (returns None):
          - the migration hasn't run yet (PGRST204 on the table)
          - extreme write contention (≥2 conflicts in a row)
          - any other Supabase error
        Caller is the daemon thread in coaching_outcomes — it must
        NOT propagate failures up to the user's upload response.
        """
        next_number = self._next_coaching_attempt_number(snippet_id)
        if next_number is None:
            return None

        payload = {
            "snippet_id": snippet_id,
            "user_id": user_id,
            "attempt_number": next_number,
            "source": source,
            "score": score,
            "components": components,
            "acoustic_features": acoustic_features,
            "entities": entities,
            "skill_id": skill_id,
            "question_text": question_text,
            "user_answer_text": user_answer_text,
            "user_answer_duration_ms": user_answer_duration_ms,
            "user_answer_word_count": user_answer_word_count,
            "rationale": rationale,
            "is_eligible_for_few_shot": bool(is_eligible_for_few_shot),
            "fact_check": fact_check,
            "evaluator_model": evaluator_model,
            "raw_outcome": raw_outcome,
        }

        for attempt in range(2):
            try:
                result = (
                    self.client.table("coaching_attempts")
                    .insert(payload)
                    .execute()
                )
                return result.data[0] if result.data else None
            except Exception as e:
                msg = str(e).lower()
                # Unique-violation race — recompute MAX and retry once.
                if attempt == 0 and ("duplicate key" in msg or "23505" in msg):
                    retry_number = self._next_coaching_attempt_number(snippet_id)
                    if retry_number is None:
                        return None
                    payload["attempt_number"] = retry_number
                    continue
                logger.warning(
                    "insert_coaching_attempt failed snippet=%s err=%s",
                    snippet_id, e,
                )
                return None
        return None

    def _next_coaching_attempt_number(self, snippet_id: str) -> Optional[int]:
        """Compute the next attempt_number for a snippet. ``None`` on error."""
        try:
            row = (
                self.client.table("coaching_attempts")
                .select("attempt_number")
                .eq("snippet_id", snippet_id)
                .order("attempt_number", desc=True)
                .limit(1)
                .execute()
            )
            if row.data:
                return int(row.data[0].get("attempt_number") or 0) + 1
            return 1
        except Exception as e:
            logger.warning(
                "_next_coaching_attempt_number failed snippet=%s err=%s",
                snippet_id, e,
            )
            return None

    def list_coaching_attempts_for_snippet(
        self,
        snippet_id: str,
        user_id: Optional[str] = None,
    ) -> List[dict]:
        """All coaching_attempts for ``snippet_id`` in chronological order.

        When ``user_id`` is provided the query is owner-scoped — the
        public /coaching/progress endpoint passes it so a user can
        only see their own attempts. Admin callers pass None to see
        every attempt regardless of owner.

        Returns [] on any error (missing table, etc.) so the caller
        can render an empty progress view without 500-ing.
        """
        try:
            query = (
                self.client.table("coaching_attempts")
                .select("*")
                .eq("snippet_id", snippet_id)
                .order("attempt_number", desc=False)
            )
            if user_id:
                query = query.eq("user_id", user_id)
            return (query.execute().data) or []
        except Exception as e:
            logger.warning(
                "list_coaching_attempts_for_snippet failed snippet=%s err=%s",
                snippet_id, e,
            )
            return []

    def update_coaching_attempt_self_rating(
        self,
        *,
        snippet_id: str,
        user_id: str,
        rating: int,
        rating_text: Optional[str] = None,
        attempt_number: Optional[int] = None,
    ) -> Optional[dict]:
        """Stamp a 1..10 self-rating onto a coaching_attempts row.

        Phase 8 — in-chat self-rating. The frontend asks "how do you
        feel about that response on a scale of 1-10?" right after the
        evaluation lands, and POSTs the user's reply to /v2/user/
        coaching/self-rating, which calls this.

        Targeting rules:
          - When ``attempt_number`` is provided, update that exact
            row (owner-scoped so a user can't backfill someone else's
            attempt).
          - When ``attempt_number`` is None, target the MOST RECENT
            attempt for this (snippet, user). This is the common
            path — the rating ask sits right after the latest
            evaluation, so the user is rating the attempt they just
            saw scored.

        Returns the updated row, or None when:
          - no attempt exists yet for that snippet+user (race with
            the eval daemon — caller should 425 the client),
          - the targeted attempt isn't owned by ``user_id``,
          - any Supabase error.
        """
        try:
            r = int(rating)
        except (TypeError, ValueError):
            return None
        if not (1 <= r <= 10):
            return None

        # Resolve the target row id. We always do this lookup (rather
        # than UPDATE … WHERE attempt_number = …) so the owner-scope
        # check is explicit and we can distinguish "missing" from
        # "wrong owner" in the response.
        try:
            query = (
                self.client.table("coaching_attempts")
                .select("id, attempt_number, user_id")
                .eq("snippet_id", snippet_id)
                .eq("user_id", user_id)
            )
            if attempt_number is not None:
                query = query.eq("attempt_number", int(attempt_number))
            else:
                query = query.order("attempt_number", desc=True).limit(1)
            existing = (query.execute().data) or []
        except Exception as e:
            logger.warning(
                "update_coaching_attempt_self_rating lookup failed "
                "snippet=%s user=%s err=%s",
                snippet_id, user_id, e,
            )
            return None

        if not existing:
            return None
        row_id = existing[0].get("id")
        if not row_id:
            return None

        payload = {
            "self_rating": r,
            "self_rating_text": (rating_text or None),
            "self_rating_submitted_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            result = (
                self.client.table("coaching_attempts")
                .update(payload)
                .eq("id", row_id)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning(
                "update_coaching_attempt_self_rating update failed "
                "id=%s err=%s",
                row_id, e,
            )
            return None

    def list_recent_coaching_attempts_for_user(
        self,
        user_id: str,
        *,
        limit: int = 10,
    ) -> List[dict]:
        """Most recent coaching_attempts for ``user_id``, newest first.

        Phase 3 — feeds the learner-profile aggregator. We select only
        the columns the aggregator needs so the query stays cheap on
        users with long histories. ``limit`` matches
        services.learner_profile.ATTEMPTS_WINDOW.

        Returns [] on any error so the recompute path can degrade
        gracefully (leaving the profile column unchanged) rather than
        breaking the outcome-persist flow that triggered it.
        """
        try:
            return (
                self.client.table("coaching_attempts")
                .select(
                    "attempt_number, score, components, self_rating, "
                    "entities, created_at, snippet_id"
                )
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(max(1, limit))
                .execute()
                .data
            ) or []
        except Exception as e:
            logger.warning(
                "list_recent_coaching_attempts_for_user failed "
                "user=%s err=%s", user_id, e,
            )
            return []

    def set_user_current_learner_mirror(
        self,
        user_id: str,
        mirror: Optional[dict],
    ) -> Optional[dict]:
        """Upsert the current learner mirror JSONB for ``user_id``.

        Phase 6 — replaces (does not append) the prior mirror so the
        user always sees the most recent reflection. Passing
        ``mirror=None`` clears the column, which is useful if we
        ever want a "discard my reflection" button.

        Upsert because the row may not exist yet — same reasoning as
        set_user_inferred_learner_profile. Failure returns None;
        the caller (services.learner_mirror) maps that to a
        PERSIST_FAILED error code so the user sees a clear retry
        signal rather than a silent no-op.
        """
        try:
            result = (
                self.client.table("user_settings")
                .upsert({
                    "user_id": user_id,
                    "current_learner_mirror": mirror,
                    "current_learner_mirror_generated_at": (
                        datetime.now(timezone.utc).isoformat()
                    ),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.warning(
                "set_user_current_learner_mirror failed user=%s err=%s",
                user_id, e,
            )
            return None

    # ── Phase 9: admin RLHF on coaching attempts ──────────────────────

    def insert_coaching_attempt_annotation(
        self,
        *,
        coaching_attempt_id: str,
        admin_user_id: str,
        admin_action: str,
        admin_score: float | None = None,
        admin_components: dict | None = None,
        admin_note: str | None = None,
        ai_score_was_correct: bool | None = None,
        reason_chip: str | None = None,
    ) -> Optional[dict]:
        """Append an admin annotation onto a coaching_attempts row.

        Phase 9 — one row per review action so multi-admin review
        stays cleanly queryable. The caller (the admin route) is
        responsible for verifying the requester is actually an
        admin; this helper does not re-check.

        Returns the inserted row on success, None when:
          - the migration hasn't run yet,
          - the coaching_attempt_id doesn't exist (FK violation),
          - any Supabase error.
        """
        payload = {
            "coaching_attempt_id": coaching_attempt_id,
            "admin_user_id": admin_user_id,
            "admin_action": admin_action,
            "admin_score": admin_score,
            "admin_components": admin_components,
            "admin_note": admin_note,
            "ai_score_was_correct": ai_score_was_correct,
            "reason_chip": reason_chip,
        }
        try:
            result = (
                self.client.table("coaching_attempt_annotations")
                .insert(payload)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning(
                "insert_coaching_attempt_annotation failed attempt=%s "
                "admin=%s err=%s",
                coaching_attempt_id, admin_user_id, e,
            )
            return None

    def list_annotations_for_coaching_attempt(
        self,
        coaching_attempt_id: str,
    ) -> List[dict]:
        """All annotations on one attempt, newest first.

        Returns [] on any error so the review UI can render the
        attempt page even if the annotations table is missing.
        """
        try:
            return (
                self.client.table("coaching_attempt_annotations")
                .select("*")
                .eq("coaching_attempt_id", coaching_attempt_id)
                .order("created_at", desc=True)
                .execute()
                .data
            ) or []
        except Exception as e:
            logger.warning(
                "list_annotations_for_coaching_attempt failed "
                "attempt=%s err=%s", coaching_attempt_id, e,
            )
            return []

    def count_annotations_by_admin(self, admin_user_id: str) -> int:
        """How many coaching-attempt annotations has this admin written?

        Phase 9 — the bulk-approve threshold (default: unlock at
        100 reviews per admin) is read off this number by the
        admin UI. We use count='exact' so the response carries the
        total without fetching rows.

        Returns 0 on any error — failure mode is "feature stays
        locked", which is safe.
        """
        try:
            result = (
                self.client.table("coaching_attempt_annotations")
                .select("id", count="exact")
                .eq("admin_user_id", admin_user_id)
                .limit(1)
                .execute()
            )
            return int(result.count or 0)
        except Exception as e:
            logger.warning(
                "count_annotations_by_admin failed admin=%s err=%s",
                admin_user_id, e,
            )
            return 0

    def set_user_admin_profile_override(
        self,
        *,
        user_id: str,
        override: Optional[dict],
        set_by: Optional[str],
    ) -> Optional[dict]:
        """Upsert the admin override of the learner profile.

        Pass ``override=None`` to clear (admin "reset to inferred"
        action). ``set_by`` is the admin's user id — recorded for
        audit; can be None when the system itself clears the
        override (e.g. via a future cron job).

        Returns the upserted row, or None on failure.
        """
        try:
            payload: dict[str, Any] = {
                "user_id": user_id,
                "admin_profile_override": override,
                "admin_profile_override_set_at": (
                    datetime.now(timezone.utc).isoformat() if override is not None
                    else None
                ),
                "admin_profile_override_set_by": set_by,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            result = (
                self.client.table("user_settings")
                .upsert(payload)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.warning(
                "set_user_admin_profile_override failed user=%s err=%s",
                user_id, e,
            )
            return None

    def get_top_followup_examples(
        self,
        intent: str,
        *,
        limit: int = 3,
        min_score: float = 0.65,
        exclude_snippet_id: str | None = None,
        viewer_user_id: str | None = None,
    ) -> List[dict]:
        """Highest-scoring past contextual exchanges for a given intent.

        Powers the few-shot retrieval layer of the coaching-effectiveness
        loop: when the user clicks a CTA, the LLM that generates the
        first question receives the TOP-N past exchanges where the same
        intent produced a high-quality answer. That nudges the model
        toward wording patterns that have already worked, instead of
        generating from scratch every time.

        Phase 2 rewrite: reads from ``coaching_attempts`` (1:N) rather
        than the latest-wins ``charisma_snippets.follow_up_outcome``
        JSONB. The retrieval picks the BEST attempt per snippet (group
        by snippet_id, keep MAX score) and then joins the snippet
        context. The downstream consumer (``_build_few_shot_block``)
        still expects a ``follow_up_outcome``-shaped dict on each row,
        so we synthesize one from the chosen attempt — that keeps the
        prompt-builder unchanged through the migration.

        Filters applied (all must hold):
          - charisma_snippets.snippet_type = intent ("charisma"/"stress")
          - admin_comment non-null (need the coach's framing)
          - transcript non-null
          - attempt.score >= ``min_score``
          - attempt.is_eligible_for_few_shot = TRUE (Phase 5 guard)
          - snippet_id != exclude_snippet_id

        Falls back to [] on any error (e.g. coaching_attempts table not
        yet migrated) so the LLM prompt builder degrades gracefully to
        context-free generation.
        """
        try:
            normalised = (intent or "").strip().lower()
            if normalised not in ("charisma", "stress"):
                return []

            # ── Phase 1 tenant-scoping setup ───────────────────────
            # Resolved BEFORE the query so the audit log captures the
            # company_id that was actually used.
            from config import Config
            tenant_scoping_on = bool(Config().FEW_SHOT_TENANT_SCOPED)
            viewer_company_id: str | None = None
            scope_mode = "cross_tenant_legacy"
            if tenant_scoping_on and viewer_user_id:
                viewer_company_id = self.get_user_company_id(viewer_user_id)

            # ── Step 1: pull top-scoring attempts ──────────────────
            # Fetch a generous pool — same snippet may have many
            # attempts so we need headroom to dedupe to the best-per-
            # snippet without losing the requested limit.
            try:
                attempts = (
                    self.client.table("coaching_attempts")
                    .select(
                        "snippet_id, user_id, attempt_number, score, "
                        "components, question_text, user_answer_text, "
                        "user_answer_duration_ms, user_answer_word_count, "
                        "rationale, is_eligible_for_few_shot, "
                        "evaluator_model, fact_check, created_at"
                    )
                    .eq("is_eligible_for_few_shot", True)
                    .gte("score", min_score)
                    .order("score", desc=True)
                    .limit(max(limit * 10, 40))
                    .execute()
                    .data
                ) or []
            except Exception as e:
                # Table missing / not migrated — degrade to empty pool
                # rather than crash the first-question endpoint.
                logger.warning(
                    "get_top_followup_examples: coaching_attempts query "
                    "failed (table missing?): %s", e
                )
                return []

            # Best attempt per snippet. attempts is already score-DESC,
            # so the first occurrence of each snippet_id is the best.
            best_by_snippet: dict[str, dict] = {}
            for a in attempts:
                sid = a.get("snippet_id")
                if not sid or sid == exclude_snippet_id:
                    continue
                if sid in best_by_snippet:
                    continue
                best_by_snippet[sid] = a
            if not best_by_snippet:
                if viewer_user_id:
                    self.log_few_shot_retrieval(
                        user_id=viewer_user_id,
                        requesting_snippet_id=exclude_snippet_id,
                        exemplar_snippet_ids=[],
                        intent=normalised,
                        scope_mode=scope_mode,
                        company_id=viewer_company_id,
                    )
                return []

            # ── Step 2: join snippet context ───────────────────────
            snippet_ids = list(best_by_snippet.keys())
            try:
                snippet_rows = (
                    self.client.table(SNIPPETS_TABLE)
                    .select(
                        "id, snippet_type, transcript, admin_comment, "
                        "follow_up_question, sharing_scope, user_id, "
                        "created_at"
                    )
                    .in_("id", snippet_ids)
                    .eq("snippet_type", normalised)
                    .not_.is_("admin_comment", "null")
                    .not_.is_("transcript", "null")
                    .execute()
                    .data
                ) or []
            except Exception as e:
                logger.warning(
                    "get_top_followup_examples: snippet join failed: %s", e
                )
                return []

            # Merge attempt + snippet; synthesize a follow_up_outcome
            # dict so _build_few_shot_block doesn't need to change.
            merged: list[dict] = []
            for s in snippet_rows:
                if not (s.get("admin_comment") or "").strip():
                    continue
                if not (s.get("transcript") or "").strip():
                    continue
                attempt = best_by_snippet.get(s.get("id"))
                if not attempt:
                    continue
                answer_text = (attempt.get("user_answer_text") or "").strip()
                if not answer_text:
                    continue
                merged_row = dict(s)
                merged_row["follow_up_outcome"] = {
                    "score": attempt.get("score"),
                    "evaluator": {
                        "components": attempt.get("components") or {},
                        "rationale": attempt.get("rationale"),
                        "model": attempt.get("evaluator_model"),
                    },
                    "user_answer": {
                        "text": answer_text,
                        "duration_ms": attempt.get("user_answer_duration_ms"),
                        "word_count": attempt.get("user_answer_word_count"),
                    },
                    "question_text": attempt.get("question_text"),
                    "eligible_for_few_shot": bool(
                        attempt.get("is_eligible_for_few_shot")
                    ),
                    "fact_check": attempt.get("fact_check"),
                    "attempt_number": attempt.get("attempt_number"),
                }
                merged.append(merged_row)

            # Re-sort by the attempt score (descending). Snippet-IN
            # order isn't guaranteed by PostgREST.
            merged.sort(
                key=lambda r: float(
                    (r.get("follow_up_outcome") or {}).get("score") or 0
                ),
                reverse=True,
            )

            # ── Step 3: Phase 1 tenant filter ──────────────────────
            if tenant_scoping_on:
                if viewer_company_id:
                    scope_mode = "tenant_scoped"
                    merged = self._filter_by_tenant_or_canonical(
                        merged, viewer_company_id
                    )
                else:
                    scope_mode = "canonical_topup"
                    merged = [
                        r for r in merged
                        if (r.get("sharing_scope") or "tenant_only") == "canonical"
                    ]
            else:
                merged = [
                    r for r in merged
                    if (r.get("sharing_scope") or "tenant_only") != "private"
                ]

            kept = merged[:limit]

            # Fire-and-forget audit log.
            if viewer_user_id:
                self.log_few_shot_retrieval(
                    user_id=viewer_user_id,
                    requesting_snippet_id=exclude_snippet_id,
                    exemplar_snippet_ids=[str(r.get("id")) for r in kept if r.get("id")],
                    intent=normalised,
                    scope_mode=scope_mode,
                    company_id=viewer_company_id,
                )
            return kept
        except Exception as e:
            logger.warning("get_top_followup_examples failed: %s", e)
            return []

    def _filter_by_tenant_or_canonical(
        self,
        rows: list[dict],
        viewer_company_id: str,
    ) -> list[dict]:
        """Keep rows whose author is in the viewer's company OR whose
        sharing_scope is 'canonical'. Drop everything else.

        Single batched user_settings lookup for the candidate authors —
        we do NOT issue per-row queries. For typical pool sizes
        (limit * 4 == 12 candidates) the IN-list query is fast.
        """
        canonical_rows: list[dict] = []
        author_ids: set[str] = set()
        for r in rows:
            scope = (r.get("sharing_scope") or "tenant_only").lower()
            if scope == "private":
                continue
            if scope == "canonical":
                canonical_rows.append(r)
                continue
            uid = r.get("user_id")
            if uid:
                author_ids.add(str(uid))

        if not author_ids:
            return canonical_rows

        # Batch lookup: which of these authors share viewer_company_id?
        try:
            settings = (
                self.client.table("user_settings")
                .select("user_id, company_id")
                .in_("user_id", list(author_ids))
                .execute()
                .data
            ) or []
        except Exception as e:
            logger.warning(
                "_filter_by_tenant_or_canonical: settings lookup failed: %s", e
            )
            settings = []

        same_company = {
            str(s.get("user_id"))
            for s in settings
            if s.get("company_id") and str(s.get("company_id")) == str(viewer_company_id)
        }

        tenant_rows = [
            r for r in rows
            if (r.get("sharing_scope") or "tenant_only").lower() == "tenant_only"
            and str(r.get("user_id") or "") in same_company
        ]

        # Preserve order from the score-sorted source query, with
        # canonical rows interleaved naturally (they were already in
        # `rows` and we kept their original positions).
        return [r for r in rows if r in tenant_rows or r in canonical_rows]

    def set_snippet_evaluator_rationale_review(
        self,
        snippet_id: str,
        *,
        rationale_text: str,
        edited_by_admin: bool,
        reviewed_at: str,
        is_trivial_edit: bool = False,
    ) -> dict | None:
        """Persist an admin's review of the AI evaluator's rationale.

        Lives inside the existing ``follow_up_outcome.evaluator`` JSONB
        block (Phase 14.x — frontend's contract) rather than as a
        separate column, so we read the current outcome, mutate the
        review fields, and write the whole JSONB back.

        Semantics::

          edited_by_admin=True, is_trivial_edit=False
            → admin_corrected_rationale = rationale_text
              was_trivial_edit (cleared / not set)
              "Real correction; train on this."

          edited_by_admin=True, is_trivial_edit=True
            → admin_corrected_rationale = rationale_text
              was_trivial_edit = True
              "Admin's edit preserved as user-facing copy, but the
               diff was sub-threshold — publish-time annotation
               consumers MUST check the flag and treat as approval
               rather than correction. Set by the word-token diff
               gate (services.utils.changed_word_tokens) when the
               admin overrode a 422 with the 'trivial edit'
               checkbox."

          edited_by_admin=False (is_trivial_edit ignored)
            → admin_corrected_rationale = None
              "Admin approved the AI rationale verbatim; stored as
               null so the publish-time annotation logic falls back
               to the AI rationale and detects approved_as_is."

        ``admin_reviewed_at`` is always stamped — its presence is what
        distinguishes "admin reviewed and approved" from "admin never
        looked at this", and it's the gate the publish-time annotation
        loop uses to decide whether to emit a signal.

        Returns the updated outcome dict on success, or None when the
        snippet has no follow_up_outcome / no evaluator block (caller
        should respond 422 — there's no rationale to review yet).

        Race window: if a new coaching attempt overwrites
        follow_up_outcome between our read and write, we lose the
        attempt. Admin reviews are infrequent and coaching attempts
        are user-initiated, so the window is small in practice; if
        this becomes a problem we'll move admin review to a separate
        column or add a JSONB-merge SQL function.
        """
        if not snippet_id:
            return None
        try:
            existing = (
                self.client.table(SNIPPETS_TABLE)
                .select("follow_up_outcome")
                .eq("id", snippet_id)
                .limit(1)
                .execute()
            )
        except Exception as e:
            logger.error(
                "set_snippet_evaluator_rationale_review: select failed "
                "snippet=%s err=%s", snippet_id, e,
            )
            return None

        if not existing.data:
            return None
        outcome = (existing.data[0].get("follow_up_outcome") or None)
        if not isinstance(outcome, dict):
            # No coaching attempt has been recorded for this snippet yet —
            # nothing to review.
            return None
        evaluator = outcome.get("evaluator")
        if not isinstance(evaluator, dict):
            return None

        # Mutate in place — outcome is a fresh dict from the DB read.
        evaluator["admin_corrected_rationale"] = (
            (rationale_text or "").strip() if edited_by_admin else None
        )
        evaluator["admin_reviewed_at"] = reviewed_at
        # was_trivial_edit only carries meaning when edited_by_admin
        # is True (we actually saved corrected text). Set the flag
        # in both directions so explicit True/False is recoverable;
        # publish-time consumers default to False on absent key.
        if edited_by_admin:
            evaluator["was_trivial_edit"] = bool(is_trivial_edit)
        else:
            # Approval path discards corrected text — the trivial-
            # edit concept doesn't apply. Clear any stale flag from
            # a previous save so a re-review doesn't carry it over.
            evaluator.pop("was_trivial_edit", None)
        outcome["evaluator"] = evaluator

        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
                .update({
                    "follow_up_outcome": outcome,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", snippet_id)
                .execute()
            )
            if result.data:
                return result.data[0].get("follow_up_outcome") or outcome
            return outcome
        except Exception as e:
            logger.error(
                "set_snippet_evaluator_rationale_review: update failed "
                "snippet=%s err=%s", snippet_id, e,
            )
            return None

    def set_snippet_follow_up_outcome(
        self,
        snippet_id: str,
        outcome: dict | None,
    ) -> dict | None:
        """Persist the post-turn-1 evaluation JSONB onto a source snippet.

        Powers the first piece of the coaching-effectiveness learning
        loop: every contextual chat the user starts via a CTA produces
        one of these blobs (score + components + rationale + the user's
        actual answer). See services/coaching_outcomes.py for the
        evaluation logic.

        Latest-wins overwrite (the user may re-record turn 1).
        Requires the `follow_up_outcome JSONB` column on
        charisma_snippets. If the migration hasn't run yet the call
        fails cleanly (PGRST204) and the caller silently swallows.
        """
        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
                .update({
                    "follow_up_outcome": outcome,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", snippet_id)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(
                "set_snippet_follow_up_outcome failed for %s: %s",
                snippet_id, e,
            )
            return None

    def update_coach_ai_message(
        self,
        user_id: str,
        message_index: int,
        new_content: str,
    ) -> dict | None:
        """Edit the `content` of one message in the coach AI conversation history.

        The messages array is stored as JSONB. We update the element at
        `message_index` in-place and persist the full array back.

        Returns the updated conversation row, or None on failure / out-of-range.
        """
        try:
            conv = self.get_coach_ai_conversation(user_id)
            if not conv:
                return None
            raw = conv.get("messages") or "[]"
            messages = json.loads(raw) if isinstance(raw, str) else list(raw)
            if not (0 <= message_index < len(messages)):
                return None  # index out of range — caller should 404/422
            messages[message_index] = {
                **messages[message_index],
                "content": new_content,
                "edited_by_admin": True,
                "edited_at": datetime.now(timezone.utc).isoformat(),
            }
            return self.upsert_coach_ai_conversation(user_id, messages)
        except Exception as e:
            logger.error("update_coach_ai_message failed for %s idx=%s: %s", user_id, message_index, e)
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
                self.client.table(SNIPPETS_TABLE)
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
                self.client.table(SNIPPETS_TABLE)
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

        Schema reality check (2026-05-11):
            Production logs after df9def4 surfaced PGRST204:
              "Could not find the 'end_time' column of
               'charisma_snippets' in the schema cache"

            So contrary to the Expand-Contract assumption that there
            were two semantically-paired column representations of the
            same boundary, only ONE pair actually exists in this DB:

                start_offset_ms, duration_ms   (milliseconds, int)

            The `start_time` / `end_time` references in the codebase
            (this helper's prior version, the upload-answer INSERT
            payload at routes/v2_routes.py:8777-8778, the
            v2_admin_get_session response shape at L10384, the route
            handler at L9404+) are write-only artefacts of an aborted
            schema migration that landed in the code but never in the
            database. PostgREST silently drops them on INSERT (which
            is why fresh sessions still create snippet rows fine) but
            errors atomically on UPDATE (which is why ±2s adjusts
            started failing 404 after df9def4).

            The fix is just to write the columns that actually exist.
            The route handler keeps accepting (start_time, end_time)
            as its public contract — we convert at this single
            chokepoint. If a future migration adds the seconds-pair as
            real columns (or restores them), this is the one place to
            re-introduce the dual write.
        """
        try:
            start_offset_ms = max(0, int(round(start_time * 1000)))
            duration_ms = max(0, int(round((end_time - start_time) * 1000)))
            result = (
                self.client.table(SNIPPETS_TABLE)
                .update({
                    "start_offset_ms": start_offset_ms,
                    "duration_ms": duration_ms,
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

    def update_snippet_metrics_blob(
        self, snippet_id: str, metrics_json: dict,
    ) -> bool:
        """Replace ONLY the ``metrics`` JSONB on a snippet.

        Deliberately narrow, and deliberately not update_snippet_metrics: that
        one also writes the six denormalized acoustic columns, so a caller who
        merely wants to re-stamp a derived field inside the blob would have to
        echo wpm/fillers/pause_ms/dynamic_db/pitch_center/energy back and would
        silently null any it got wrong. This is for re-stamping derived reads
        (scripts/backfill_voice_confidence.py); the measured columns are the
        recorder's to write, not a backfill's.

        Best-effort: returns False on any failure rather than raising."""
        if not snippet_id or not isinstance(metrics_json, dict):
            return False
        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
                .update({"metrics": metrics_json})
                .eq("id", snippet_id)
                .execute()
            )
            return bool(getattr(result, "data", None))
        except Exception as e:
            logger.warning("update_snippet_metrics_blob failed sid=%s: %s",
                           snippet_id, e)
            return False

    def set_snippet_arousal(self, snippet_id: str, arousal_z: float) -> bool:
        """Capture the baseline-relative AROUSAL read on a snippet (founder
        2026-07-24, capture-first). A learning-loop signal only — it is never
        surfaced to a user and never fed into ranking. Best-effort: a missing
        ``arousal_z`` column (migration pending) or any other error just
        returns False and never raises into the analysis path."""
        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
                .update({"arousal_z": arousal_z})
                .eq("id", snippet_id)
                .execute()
            )
            return bool(getattr(result, "data", None))
        except Exception as e:
            logger.warning("set_snippet_arousal failed sid=%s: %s",
                           snippet_id, e)
            return False

    def upsert_arc_context_document(self, arc_id, text, pages, chars, *,
                                    filename=None, truncated=False) -> bool:
        """Store the extracted context document for an arc (X-1, founder
        2026-07-24; one row per arc). Best-effort — a missing table (migration
        pending) or any error returns False, never raises into the upload."""
        try:
            self.client.table("arc_context_documents").upsert({
                "arc_id": str(arc_id),
                "text": text or "",
                "pages": int(pages or 0),
                "chars": int(chars or 0),
                "filename": filename,
                "truncated": bool(truncated),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="arc_id").execute()
            return True
        except Exception as e:
            logger.error("upsert_arc_context_document failed arc=%s: %s",
                         arc_id, e)
            return False

    def get_arc_context_document(self, arc_id) -> Optional[dict]:
        """The stored context document for an arc — {text, pages, chars,
        filename, truncated} or None. Best-effort (missing table → None)."""
        try:
            res = (
                self.client.table("arc_context_documents")
                .select("text, pages, chars, filename, truncated")
                .eq("arc_id", str(arc_id))
                .limit(1)
                .execute()
            )
            rows = getattr(res, "data", None) or []
            return rows[0] if rows else None
        except Exception as e:
            logger.warning("get_arc_context_document failed arc=%s: %s",
                           arc_id, e)
            return None

    # ── Journal (blog) content + CMS (founder 2026-07-25) ─────────────────
    # A self-contained marketing surface: nothing in the record → transcribe
    # → coach → read loop reads or writes journal_post. Every helper is
    # best-effort so a missing table (migration pending) degrades to "no
    # posts" instead of 500ing a public page.
    #
    # UNIQUE-slug note: the table has a UNIQUE constraint on `slug`, so the
    # create/update helpers surface a collision as the sentinel string
    # "DUPLICATE_SLUG" and the route maps it to 409 (never a 500).

    _JOURNAL_COLUMNS = (
        "id, slug, title, excerpt, category, read_time_min, cover_kind, "
        "cover_image_url, cover_alt, media_url, media_duration_sec, body, "
        "author_name, author_avatar_url, status, published_at, sort_order, "
        "meta_title, meta_description, og_image_url, created_at, updated_at"
    )

    @staticmethod
    def journal_search_filter(search: Optional[str]) -> Optional[str]:
        """The PostgREST `or=(...)` filter for a title/excerpt search, or None.

        SINGLE source of truth for the needle sanitization (used by both the
        list and the count query, which must agree or paging goes wrong).

        `,` `(` `)` are the condition/group separators in PostgREST's filter
        grammar, so they are stripped — without them an injected value stays
        inside the single ilike pattern and cannot add a condition. Note the
        real guarantee against draft exposure is structural, not this: the
        public queries also apply `status=eq.published` as a SEPARATE filter,
        and PostgREST ANDs separate params, so no or-injection can widen the
        result set past published rows.
        """
        if not search:
            return None
        safe = str(search)
        for ch in (",", "(", ")"):
            safe = safe.replace(ch, " ")
        safe = safe.strip()
        if not safe:
            return None
        return f"title.ilike.%{safe}%,excerpt.ilike.%{safe}%"

    @staticmethod
    def _is_duplicate_slug(err: Exception) -> bool:
        """True when the error is the UNIQUE(slug) violation (Postgres 23505
        / PostgREST duplicate-key text), so the route can answer 409."""
        msg = str(err).lower()
        return (
            "23505" in msg
            or "duplicate key" in msg
            or ("unique" in msg and "slug" in msg)
        )

    def list_journal_posts(self, *, published_only: bool = True,
                           category: Optional[str] = None,
                           search: Optional[str] = None,
                           order_column: str = "published_at",
                           descending: bool = True,
                           tiebreak_column: str = "published_at",
                           limit: int = 50,
                           offset: int = 0) -> list:
        """Journal posts for the public index (published_only) or the CMS
        list (published_only=False). Best-effort → [] on any failure.

        `search` is a case-insensitive substring over title OR excerpt.
        The `curated` ordering passes order_column='sort_order'; a secondary
        order breaks ties within one sort_order.

        ``tiebreak_column`` picks that secondary order (FE amendment
        2026-07-25). The PUBLIC index keeps 'published_at' — every public row
        is published, so the date is non-NULL and is the meaningful order. The
        CMS list passes 'created_at' instead, because it INCLUDES DRAFTS: a
        draft's published_at is NULL, Postgres orders DESC as NULLS FIRST, and
        every new post starts at sort_order=0 — so a published_at tiebreak
        would float undated drafts above dated posts and shuffle the CMS list
        as dates get set. created_at is never NULL, so the CMS order is stable.
        """
        try:
            q = self.client.table("journal_post").select(self._JOURNAL_COLUMNS)
            if published_only:
                q = q.eq("status", "published")
            if category:
                q = q.eq("category", str(category))
            or_filter = self.journal_search_filter(search)
            if or_filter:
                q = q.or_(or_filter)
            # NOTE on NULL display dates: Postgres orders DESC as NULLS FIRST,
            # and this client cannot emit `nullslast` (order(nullsfirst=False)
            # emits no modifier at all, so the Postgres default stands). A
            # published row with published_at = NULL would therefore pin itself
            # to the top of the public index. That is prevented at the two
            # points where it can be enforced instead: validate_post_body
            # stamps a date whenever status becomes published, and the
            # migration backfills any row written directly via SQL.
            q = q.order(order_column, desc=bool(descending))
            if order_column != tiebreak_column:
                q = q.order(tiebreak_column, desc=True)
            res = q.range(int(offset), int(offset) + int(limit) - 1).execute()
            return getattr(res, "data", None) or []
        except Exception as e:
            logger.warning("list_journal_posts failed: %s", e)
            return []

    def count_journal_posts(self, *, published_only: bool = True,
                            category: Optional[str] = None,
                            search: Optional[str] = None) -> int:
        """Total matching posts, for the index's `total`. Best-effort → 0."""
        try:
            q = self.client.table("journal_post").select(
                "id", count="exact")
            if published_only:
                q = q.eq("status", "published")
            if category:
                q = q.eq("category", str(category))
            or_filter = self.journal_search_filter(search)
            if or_filter:
                q = q.or_(or_filter)
            res = q.execute()
            cnt = getattr(res, "count", None)
            if cnt is not None:
                return int(cnt)
            return len(getattr(res, "data", None) or [])
        except Exception as e:
            logger.warning("count_journal_posts failed: %s", e)
            return 0

    def get_journal_post_by_slug(self, slug: str, *,
                                 published_only: bool = True,
                                 strict: bool = False) -> Optional[dict]:
        """One post by slug, or None. `published_only` keeps a draft
        invisible on the public route (404, no existence leak).

        `strict=True` RE-RAISES an infrastructure error instead of returning
        None. The public by-slug route uses it: swallowing a Supabase blip
        into a None would render a live post as 404 "post not found", and the
        FE's ISR would then cache that 404 — a transient DB hiccup would take
        a real post off the site until the window expired. Missing row → None
        either way; only the error path differs.
        """
        if not slug:
            return None
        try:
            q = (
                self.client.table("journal_post")
                .select(self._JOURNAL_COLUMNS)
                .eq("slug", str(slug))
            )
            if published_only:
                q = q.eq("status", "published")
            res = q.limit(1).execute()
            rows = getattr(res, "data", None) or []
            return rows[0] if rows else None
        except Exception as e:
            logger.warning("get_journal_post_by_slug failed slug=%s: %s",
                           slug, e)
            if strict:
                raise
            return None

    def get_journal_post_by_id(self, post_id: str) -> Optional[dict]:
        """One post by id for the CMS editor (any status), or None."""
        if not post_id:
            return None
        try:
            res = (
                self.client.table("journal_post")
                .select(self._JOURNAL_COLUMNS)
                .eq("id", str(post_id))
                .limit(1)
                .execute()
            )
            rows = getattr(res, "data", None) or []
            return rows[0] if rows else None
        except Exception as e:
            logger.warning("get_journal_post_by_id failed id=%s: %s",
                           post_id, e)
            return None

    def create_journal_post(self, fields: dict):
        """Insert a post. Returns the created row, "DUPLICATE_SLUG" on a slug
        collision, or None on any other failure."""
        try:
            res = (
                self.client.table("journal_post")
                .insert(dict(fields or {}))
                .execute()
            )
            rows = getattr(res, "data", None) or []
            return rows[0] if rows else None
        except Exception as e:
            if self._is_duplicate_slug(e):
                return "DUPLICATE_SLUG"
            logger.error("create_journal_post failed: %s", e)
            return None

    def update_journal_post(self, post_id: str, fields: dict):
        """Patch a post. Returns the updated row, "DUPLICATE_SLUG" on a slug
        collision, or None when the row is missing / on any other failure."""
        if not post_id:
            return None
        payload = dict(fields or {})
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            res = (
                self.client.table("journal_post")
                .update(payload)
                .eq("id", str(post_id))
                .execute()
            )
            rows = getattr(res, "data", None) or []
            return rows[0] if rows else None
        except Exception as e:
            if self._is_duplicate_slug(e):
                return "DUPLICATE_SLUG"
            logger.error("update_journal_post failed id=%s: %s", post_id, e)
            return None

    def delete_journal_post(self, post_id: str) -> bool:
        """Delete a post. True on success. Best-effort."""
        if not post_id:
            return False
        try:
            self.client.table("journal_post").delete() \
                .eq("id", str(post_id)).execute()
            return True
        except Exception as e:
            logger.error("delete_journal_post failed id=%s: %s", post_id, e)
            return False

    def reorder_journal_posts(self, ids: list) -> int:
        """Assign sort_order by position in `ids` (the CMS's manual order).

        Returns how many updates were ACCEPTED without error — not how many
        rows matched, since PostgREST does not error on an update that hits
        zero rows. Best-effort per row, so one bad id cannot abort the rest.
        """
        written = 0
        for index, post_id in enumerate(ids or []):
            if not post_id:
                continue
            try:
                self.client.table("journal_post").update({
                    "sort_order": index,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", str(post_id)).execute()
                written += 1
            except Exception as e:
                logger.warning("reorder_journal_posts failed id=%s: %s",
                               post_id, e)
        return written

    def journal_category_counts(self) -> dict:
        """{category: published_count} for the optional categories endpoint.
        Counted in Python over the published slugs — the table is small and
        this avoids depending on a PostgREST group-by. Best-effort → {}."""
        try:
            res = (
                self.client.table("journal_post")
                .select("category")
                .eq("status", "published")
                .execute()
            )
            out: dict = {}
            for row in (getattr(res, "data", None) or []):
                key = (row or {}).get("category")
                if key:
                    out[key] = out.get(key, 0) + 1
            return out
        except Exception as e:
            logger.warning("journal_category_counts failed: %s", e)
            return {}

    # ── Community Content Studio (founder 2026-07-26) ─────────────────────
    # The three derived community posts hanging off a journal post. Same
    # best-effort discipline as the journal helpers above: a missing table
    # (migration pending) degrades to "no items" instead of 500ing the CMS.
    #
    # These rows are NEVER served by a public route — they carry no slug and
    # no status because they can never be published to the site.

    _COMMUNITY_COLUMNS = (
        "id, journal_post_id, kind, title, body, flags, pillar_id, "
        "pillar_name, theme, soft_cta_line, app_proof_line, model, "
        "generated_at, created_at, updated_at"
    )

    @staticmethod
    def _is_missing_community_table(error: Exception) -> bool:
        text = str(error).lower()
        return "journal_community_post" in text and (
            "does not exist" in text or "pgrst" in text
            or "could not find the table" in text
        )

    def upsert_journal_community_posts(self, journal_post_id: str,
                                       rows: list) -> list:
        """Write 1..3 derived posts, keyed on (journal_post_id, kind).

        Upsert rather than insert: regenerating a format REPLACES it instead
        of stacking duplicates, and a single-format reroll leaves its siblings
        alone. Returns the written rows, [] on failure.
        """
        if not journal_post_id or not rows:
            return []
        try:
            res = (
                self.client.table("journal_community_post")
                .upsert([dict(r) for r in rows],
                        on_conflict="journal_post_id,kind")
                .execute()
            )
            return getattr(res, "data", None) or []
        except Exception as e:
            if self._is_missing_community_table(e):
                logger.warning(
                    "upsert_journal_community_posts: table missing (run "
                    "migrations/add_journal_community_posts.sql) post=%s",
                    journal_post_id)
                return []
            logger.error("upsert_journal_community_posts failed post=%s: %s",
                         journal_post_id, e)
            return []

    def list_journal_community_posts(self,
                                     journal_post_id: Optional[str] = None
                                     ) -> list:
        """Derived posts for one parent, or ALL of them when the id is None —
        the CMS loads every item once and groups them client-side. []."""
        try:
            q = (
                self.client.table("journal_community_post")
                .select(self._COMMUNITY_COLUMNS)
            )
            if journal_post_id:
                q = q.eq("journal_post_id", str(journal_post_id))
            res = q.order("journal_post_id").order("kind").execute()
            return getattr(res, "data", None) or []
        except Exception as e:
            if self._is_missing_community_table(e):
                logger.warning(
                    "list_journal_community_posts: table missing (run "
                    "migrations/add_journal_community_posts.sql)")
                return []
            logger.warning("list_journal_community_posts failed: %s", e)
            return []

    def get_journal_community_post(self, item_id: str) -> Optional[dict]:
        """One derived post by id, or None."""
        if not item_id:
            return None
        try:
            res = (
                self.client.table("journal_community_post")
                .select(self._COMMUNITY_COLUMNS)
                .eq("id", str(item_id))
                .limit(1)
                .execute()
            )
            rows = getattr(res, "data", None) or []
            return rows[0] if rows else None
        except Exception as e:
            logger.warning("get_journal_community_post failed id=%s: %s",
                           item_id, e)
            return None

    def update_journal_community_post(self, item_id: str,
                                      changes: dict) -> Optional[dict]:
        """Patch the founder's manual edit (title/body). None on failure."""
        if not item_id or not changes:
            return None
        payload = dict(changes)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            res = (
                self.client.table("journal_community_post")
                .update(payload)
                .eq("id", str(item_id))
                .execute()
            )
            rows = getattr(res, "data", None) or []
            return rows[0] if rows else None
        except Exception as e:
            logger.error("update_journal_community_post failed id=%s: %s",
                         item_id, e)
            return None

    def delete_journal_community_post(self, item_id: str) -> bool:
        """Delete one derived post. True on success. Best-effort."""
        if not item_id:
            return False
        try:
            self.client.table("journal_community_post").delete() \
                .eq("id", str(item_id)).execute()
            return True
        except Exception as e:
            logger.error("delete_journal_community_post failed id=%s: %s",
                         item_id, e)
            return False

    # ── Generated journal covers (founder 2026-07-28) ─────────────────────
    # Candidate cover images for a journal post. Same best-effort discipline
    # as the helpers above: a missing table (migration pending) degrades to
    # "no history" — the draw still works and still sets cover_image_url, the
    # founder just loses the strip of previous attempts.
    #
    # CMS-only rows. No public route reads this table; the site sees only the
    # promoted cover_image_url on journal_post.

    _POST_IMAGE_COLUMNS = (
        "id, journal_post_id, image_url, storage_key, alt_text, prompt, "
        "revised_prompt, notes, parent_image_id, flags, model, size, "
        "quality, created_at"
    )

    @staticmethod
    def _is_missing_post_image_table(error: Exception) -> bool:
        text = str(error).lower()
        return "journal_post_image" in text and (
            "does not exist" in text or "pgrst" in text
            or "could not find the table" in text
        )

    def insert_journal_post_image(self, row: dict) -> Optional[dict]:
        """Record one generated cover attempt. None on failure.

        Insert, never upsert: every attempt is kept so "Regenerate" is
        non-destructive and the founder can walk back to an earlier one.
        """
        if not row:
            return None
        try:
            res = (
                self.client.table("journal_post_image")
                .insert(dict(row))
                .execute()
            )
            rows = getattr(res, "data", None) or []
            return rows[0] if rows else None
        except Exception as e:
            if self._is_missing_post_image_table(e):
                logger.warning(
                    "insert_journal_post_image: table missing (run "
                    "migrations/add_journal_post_image.sql) post=%s",
                    row.get("journal_post_id"))
                return None
            logger.error("insert_journal_post_image failed post=%s: %s",
                         row.get("journal_post_id"), e)
            return None

    def list_journal_post_images(self, journal_post_id: str,
                                 limit: int = 24) -> list:
        """This post's cover attempts, newest first. []."""
        if not journal_post_id:
            return []
        try:
            res = (
                self.client.table("journal_post_image")
                .select(self._POST_IMAGE_COLUMNS)
                .eq("journal_post_id", str(journal_post_id))
                .order("created_at", desc=True)
                .limit(max(1, int(limit or 24)))
                .execute()
            )
            return getattr(res, "data", None) or []
        except Exception as e:
            if self._is_missing_post_image_table(e):
                logger.warning(
                    "list_journal_post_images: table missing (run "
                    "migrations/add_journal_post_image.sql)")
                return []
            logger.warning("list_journal_post_images failed post=%s: %s",
                           journal_post_id, e)
            return []

    def get_journal_post_image(self, image_id: str) -> Optional[dict]:
        """One cover attempt by id, or None."""
        if not image_id:
            return None
        try:
            res = (
                self.client.table("journal_post_image")
                .select(self._POST_IMAGE_COLUMNS)
                .eq("id", str(image_id))
                .limit(1)
                .execute()
            )
            rows = getattr(res, "data", None) or []
            return rows[0] if rows else None
        except Exception as e:
            if self._is_missing_post_image_table(e):
                logger.warning(
                    "get_journal_post_image: table missing (run "
                    "migrations/add_journal_post_image.sql)")
                return None
            logger.warning("get_journal_post_image failed id=%s: %s",
                           image_id, e)
            return None

    def delete_journal_post_image(self, image_id: str) -> bool:
        """Delete one cover attempt. True on success. Best-effort.

        The R2 object is intentionally left in place: the post may still point
        at this url (or a CDN may still be serving it), and an orphaned image
        is cheaper than a broken cover.
        """
        if not image_id:
            return False
        try:
            self.client.table("journal_post_image").delete() \
                .eq("id", str(image_id)).execute()
            return True
        except Exception as e:
            logger.error("delete_journal_post_image failed id=%s: %s",
                         image_id, e)
            return False

    def skip_snippet(self, snippet_id: str, is_skipped: bool = True) -> Optional[dict]:
        """Mark a snippet as skipped (hidden from user results)."""
        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
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

    def hard_delete_charisma_snippet(self, snippet_id: str) -> Optional[dict]:
        """Permanently remove a charisma_snippets row.

        Phase 18.1 — admin "delete snippet" flow for garbage /
        misclassified extractions. Distinct from skip_snippet:
          - skip_snippet: soft-hide (is_skipped=TRUE), row remains
            in admin view + DB. Reversible.
          - hard_delete_charisma_snippet: row is GONE. coaching_
            attempts referencing it CASCADE-delete (per the FK
            in the Phase 2 migration); admin_annotation_events
            keyed on snippet_id stay in place (no FK) so the
            RLHF training signal isn't lost.

        Returns the deleted row dict on success (lets the caller
        log what was destroyed), None when nothing matched the
        id, or raises only on Supabase transport errors — the
        caller maps those to 500.

        Idempotent: deleting an already-gone row returns None
        cleanly, no exception, so the route layer can map to
        404 without retry.
        """
        try:
            # Read-before-delete so we can return the row in the
            # response AND tell "already gone" (None data) from
            # "Supabase rejected the delete" (exception).
            existing = (
                self.client.table(SNIPPETS_TABLE)
                .select("*")
                .eq("id", snippet_id)
                .limit(1)
                .execute()
            )
            if not (existing.data or []):
                return None
            self.client.table(SNIPPETS_TABLE).delete().eq(
                "id", snippet_id
            ).execute()
            return existing.data[0]
        except Exception as e:
            logger.error(
                "hard_delete_charisma_snippet failed snippet=%s err=%s",
                snippet_id, e,
            )
            raise

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
        kpi_score: float | None = None,
    ) -> Optional[dict]:
        """Update v2_sessions with aggregated global acoustic metrics + KPI."""
        try:
            payload = {
                "global_wpm": global_wpm,
                "global_fillers": global_fillers,
                "global_pause_ms": global_pause_ms,
                "global_dynamic_db": global_dynamic_db,
                "global_pitch_center": global_pitch_center,
                "global_energy": global_energy,
            }
            if kpi_score is not None:
                payload["kpi_score"] = kpi_score
            result = (
                self.client.table("v2_sessions")
                .update(payload)
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

    def get_next_session_icebreaker_row(
        self,
        session_id: str,
    ) -> Optional[dict]:
        """Read the six icebreaker columns + session metadata for
        the admin GET endpoint.

        Returns a dict with the raw columns; the route layer derives
        the public 5-state ``queue_status`` enum via
        ``services.next_session_icebreaker.derive_queue_status``.

        Returns None when the row doesn't exist OR when the columns
        are missing (migration pending). Empty-row vs missing-column
        is logged so we can tell them apart in audits.
        """
        if not session_id:
            return None
        try:
            result = (
                self.client.table("v2_sessions")
                .select(
                    "id, user_id, "
                    "next_session_icebreaker_ai_draft, "
                    "next_session_icebreaker_ai_draft_generated_at, "
                    "next_session_icebreaker, "
                    "next_session_icebreaker_edited_at, "
                    "next_session_icebreaker_status, "
                    "next_session_icebreaker_generation_error"
                )
                .eq("id", session_id)
                .limit(1)
                .execute()
            )
            if not result.data:
                return None
            return result.data[0]
        except Exception as e:
            err_low = str(e).lower()
            if (
                "next_session_icebreaker" in err_low
                or "pgrst204" in err_low
            ):
                logger.warning(
                    "get_next_session_icebreaker_row: columns missing "
                    "(run migrations/add_next_session_icebreaker_"
                    "columns.sql) sid=%s",
                    session_id,
                )
                return None
            logger.warning(
                "get_next_session_icebreaker_row failed sid=%s err=%s",
                session_id, e,
            )
            return None

    def set_next_session_icebreaker_ai_draft(
        self,
        session_id: str,
        *,
        ai_draft: str,
        generated_at: str,
        reset_editable: bool,
    ) -> bool:
        """Persist the immutable AI baseline of the icebreaker.

        Called from services.next_session_icebreaker.generate_next_
        session_icebreaker — the only writer of the ai_draft column.

        Writes:
          - next_session_icebreaker_ai_draft = ai_draft
          - next_session_icebreaker_ai_draft_generated_at = generated_at
          - next_session_icebreaker_generation_error = NULL (success
            clears any prior failure tag)

        When ``reset_editable=True`` (default for first generation
        AND regenerate), ALSO writes:
          - next_session_icebreaker = ai_draft (current starts
            equal to draft)
          - next_session_icebreaker_edited_at = NULL
          - next_session_icebreaker_status = 'pending'

        ``reset_editable=False`` would preserve admin edits across a
        re-generation — we don't expose that today (regenerate is
        destructive by FE-approved design) but the kwarg leaves the
        door open.

        Returns True on success. Logs + returns False on:
          - missing column (migration pending)
          - generic DB failure
        """
        if not session_id or not ai_draft:
            return False
        payload: dict[str, Any] = {
            "next_session_icebreaker_ai_draft": ai_draft,
            "next_session_icebreaker_ai_draft_generated_at": generated_at,
            "next_session_icebreaker_generation_error": None,
        }
        if reset_editable:
            payload.update({
                "next_session_icebreaker": ai_draft,
                "next_session_icebreaker_edited_at": None,
                "next_session_icebreaker_status": "pending",
            })
        try:
            (
                self.client.table("v2_sessions")
                .update(payload)
                .eq("id", session_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if (
                "next_session_icebreaker" in err_low
                or "pgrst204" in err_low
            ):
                logger.warning(
                    "set_next_session_icebreaker_ai_draft: column "
                    "missing (run migrations/add_next_session_"
                    "icebreaker_columns.sql) sid=%s",
                    session_id,
                )
                return False
            logger.error(
                "set_next_session_icebreaker_ai_draft failed sid=%s: %s",
                session_id, e,
            )
            return False

    def update_next_session_icebreaker_editable(
        self,
        session_id: str,
        *,
        current: Optional[str],
        edited_at: str,
        status: str,
    ) -> bool:
        """Admin-edit write path for the icebreaker.

        Updates ONLY the editable columns:
          - next_session_icebreaker = current
          - next_session_icebreaker_edited_at = edited_at
          - next_session_icebreaker_status = status

        The immutable ai_draft column is intentionally NOT touched —
        admin edits leave the LLM baseline pinned for diff tracking.

        ``current=None`` + ``status='skipped'`` is the "admin cleared"
        case: n+1 will fall through to the default first-question
        path.

        Caller is responsible for the status enum value matching the
        CHECK constraint ('pending', 'skipped', 'delivered'). Routes
        pass 'pending' or 'skipped' only; 'delivered' is owned by
        ``mark_next_session_icebreaker_delivered``.
        """
        if not session_id:
            return False
        try:
            (
                self.client.table("v2_sessions")
                .update({
                    "next_session_icebreaker": current,
                    "next_session_icebreaker_edited_at": edited_at,
                    "next_session_icebreaker_status": status,
                })
                .eq("id", session_id)
                .execute()
            )
            return True
        except Exception as e:
            logger.error(
                "update_next_session_icebreaker_editable failed "
                "sid=%s: %s", session_id, e,
            )
            return False

    def set_next_session_icebreaker_generation_error(
        self,
        session_id: str,
        error_tag: str,
    ) -> bool:
        """Tag a failed generation attempt.

        Writes next_session_icebreaker_generation_error = error_tag
        and leaves ai_draft NULL. FE consumes the tag to render the
        "Generation failed — Regenerate" red banner state.

        Common tags (no DB-level enum; informational):
          'transcript_too_short' | 'llm_unavailable' | 'llm_empty'
        """
        if not session_id:
            return False
        try:
            (
                self.client.table("v2_sessions")
                .update({
                    "next_session_icebreaker_generation_error": error_tag,
                })
                .eq("id", session_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if (
                "next_session_icebreaker" in err_low
                or "pgrst204" in err_low
            ):
                # Migration pending; nothing to log loudly.
                return False
            logger.warning(
                "set_next_session_icebreaker_generation_error "
                "failed sid=%s: %s", session_id, e,
            )
            return False

    def clear_next_session_icebreaker_generation_error(
        self,
        session_id: str,
    ) -> bool:
        """Clear the error tag before a fresh generation attempt.

        Called from generate_next_session_icebreaker(overwrite=True)
        so the FE sees the new attempt's outcome rather than a stale
        failure tag bleeding through.
        """
        if not session_id:
            return False
        try:
            (
                self.client.table("v2_sessions")
                .update({
                    "next_session_icebreaker_generation_error": None,
                })
                .eq("id", session_id)
                .execute()
            )
            return True
        except Exception:
            return False  # best-effort; not load-bearing

    def pop_pending_icebreaker_for_user(
        self,
        user_id: str,
    ) -> Optional[dict]:
        """Atomic-ish: find the user's most-recent session whose
        icebreaker is pending+non-null, mark it delivered, return
        ``{question, source_session_id}``.

        Returns None when:
          - no pending icebreaker exists for this user
          - the columns are missing (migration pending)
          - the read OR the mark-delivered failed

        Atomicity caveat: SELECT then UPDATE on two HTTP calls.
        Race window between them = "if two first-question requests
        for the same user fire in parallel, both might consume the
        same row." Mirrors pop_next_directive's caveat exactly —
        acceptable because chat surfaces are user-driven and serial
        per session. If we ever need stricter guarantees, promote
        to a stored function with SELECT ... FOR UPDATE SKIP LOCKED.

        Called from /v2/user/chat/first-question AFTER the directives-
        queue check (admin overrides still win) but BEFORE the
        contextual-init flow — see the route comment for the full
        priority order.
        """
        if not user_id:
            return None
        try:
            picked = (
                self.client.table("v2_sessions")
                .select(
                    "id, next_session_icebreaker"
                )
                .eq("user_id", user_id)
                .eq("next_session_icebreaker_status", "pending")
                .not_.is_("next_session_icebreaker", None)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = picked.data or []
            if not rows:
                return None
            row = rows[0]
        except Exception as sel_err:
            err_low = str(sel_err).lower()
            if (
                "next_session_icebreaker" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                # Columns not yet present — silently fall through to
                # legacy path. Mirrors pop_next_directive.
                return None
            logger.warning(
                "pop_pending_icebreaker: select failed user=%s err=%s "
                "— falling through",
                user_id, sel_err,
            )
            return None

        question = (row.get("next_session_icebreaker") or "").strip()
        if not question:
            # Status was 'pending' but the value was empty/whitespace —
            # treat as if no icebreaker exists. Don't flip it to
            # 'delivered' (nothing was delivered).
            return None

        # Mark delivered. If this UPDATE fails we abort delivery — same
        # rationale as pop_next_directive: better to let the LLM
        # fallback fire than to re-serve the same icebreaker twice.
        try:
            (
                self.client.table("v2_sessions")
                .update({
                    "next_session_icebreaker_status": "delivered",
                })
                .eq("id", row["id"])
                .execute()
            )
        except Exception as upd_err:
            logger.warning(
                "pop_pending_icebreaker: mark-delivered failed "
                "user=%s sid=%s err=%s — falling through to LLM "
                "to avoid double-firing the same icebreaker",
                user_id, row.get("id"), upd_err,
            )
            return None

        return {
            "question": question,
            "source_session_id": row.get("id"),
        }

    def get_next_session_id_for(
        self,
        user_id: str,
        after_session_id: str,
    ) -> Optional[str]:
        """For the GET endpoint's queue_status derivation: does the
        user have a session that was created AFTER ``after_session_id``?
        If so, return its id; the FE renders the card as 'queued'.

        Returns None when:
          - no later session exists
          - the after_session row isn't found (can't compare created_at)
          - DB hiccup

        Light query — single index seek on (user_id, created_at).
        """
        if not user_id or not after_session_id:
            return None
        try:
            # First fetch after_session's created_at — we don't have
            # it in the GET row payload context and don't want to
            # require the caller to thread it through.
            anchor = (
                self.client.table("v2_sessions")
                .select("created_at")
                .eq("id", after_session_id)
                .limit(1)
                .execute()
            )
            if not anchor.data:
                return None
            anchor_ts = anchor.data[0].get("created_at")
            if not anchor_ts:
                return None
            later = (
                self.client.table("v2_sessions")
                .select("id")
                .eq("user_id", user_id)
                .gt("created_at", anchor_ts)
                .order("created_at", desc=False)
                .limit(1)
                .execute()
            )
            rows = later.data or []
            if not rows:
                return None
            return rows[0].get("id")
        except Exception as e:
            logger.warning(
                "get_next_session_id_for failed user=%s sid=%s err=%s",
                user_id, after_session_id, e,
            )
            return None

    # ── Ticket 2 — Dad-joke onboarding opener ───────────────────────
    #
    # Two reads: one random pick (for /start), one by-id lookup (for
    # /next when FE returns the joke_id it was given). No writes —
    # admin curation endpoints (deactivate / edit / add) are out of
    # scope for v1.

    def get_random_dad_joke(self, locale: str = "en") -> Optional[dict]:
        """Pick one random active joke in the requested locale.

        Returns ``{id, setup, punchline, emoji}`` or None when:
          - dad_jokes table is missing (migration pending)
          - no active jokes in the locale
          - DB hiccup

        Approach: SELECT all active rows in the locale (small set,
        ≤ a few dozen at any plausible scale), pick one in Python
        with random.choice. Avoids the supabase-py limitation that
        ORDER BY random() isn't exposed cleanly, AND lets us seed
        the random in tests deterministically if we ever need to.
        """
        if not locale:
            locale = "en"
        try:
            res = (
                self.client.table("dad_jokes")
                .select("id, setup, punchline, emoji")
                .eq("locale", locale)
                .eq("active", True)
                .execute()
            )
            rows = res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if (
                "dad_jokes" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                # Migration not yet run — caller falls back to no
                # opener (silent), which is the right UX: the joke
                # is decoration, never blocking.
                return None
            logger.warning(
                "get_random_dad_joke failed locale=%s err=%s",
                locale, e,
            )
            return None
        if not rows:
            return None

        import random
        return random.choice(rows)

    def dad_jokes_health(self) -> dict:
        """FIX.3 — Health probe for the dad_jokes table.

        Returns ``{table_exists, joke_count, sample_joke}`` so admin
        + FE can confirm the migration ran on Supabase. Catches the
        common deploy failure mode where the BE ships endpoints
        but the migration was forgotten — the opener silently
        skips (204) and nobody knows why.

        ``sample_joke`` is one active row (for visual confirmation
        the seed took), or None on empty table.
        """
        try:
            res = (
                self.client.table("dad_jokes")
                .select("id, setup, punchline, emoji, active")
                .eq("active", True)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            # Re-query just the count without limit so the health
            # endpoint reflects actual seed size, not the limit-1.
            try:
                count_res = (
                    self.client.table("dad_jokes")
                    .select("id", count="exact")
                    .eq("active", True)
                    .execute()
                )
                total = count_res.count or len(rows)
            except Exception:
                total = len(rows)
            return {
                "table_exists": True,
                "joke_count": int(total),
                "sample_joke": rows[0] if rows else None,
            }
        except Exception as e:
            err_low = str(e).lower()
            if (
                "dad_jokes" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                return {
                    "table_exists": False,
                    "joke_count": 0,
                    "sample_joke": None,
                }
            logger.warning("dad_jokes_health failed err=%s", e)
            return {
                "table_exists": False,
                "joke_count": 0,
                "sample_joke": None,
                "error": str(e),
            }

    def get_dad_joke_by_id(self, joke_id: str) -> Optional[dict]:
        """Lookup a joke by id for the /next endpoint.

        The FE round-trips the joke_id from /start back to /next so
        the punchline endpoint can deliver the matching content
        without re-rolling random. Returns None when the id is
        unknown or the table is missing (caller falls back to
        skipping the punchline gracefully).
        """
        if not joke_id:
            return None
        try:
            res = (
                self.client.table("dad_jokes")
                .select("id, setup, punchline, emoji")
                .eq("id", joke_id)
                .limit(1)
                .execute()
            )
            rows = res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "dad_jokes" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return None
            logger.warning(
                "get_dad_joke_by_id failed jid=%s err=%s",
                joke_id, e,
            )
            return None
        if not rows:
            return None
        return rows[0]

    # ── tester-soft-v1 — KPI timeline + question pool ────────────────
    #
    # Two thin readers + one write path for the admin pool CRUD.
    # No business logic in db.py — services/kpi_timeline.py and
    # routes/v2_routes.py own the shaping.

    def get_user_kpi_timeline_rows(
        self,
        user_id: str,
        *,
        limit: int = 200,
    ) -> list[dict]:
        """Return per-session KPI scoring rows for a user, newest
        first, capped at ``limit``.

        Returns ``{id, created_at, kpi_score, global_wpm,
        global_fillers, stickiness_score, source}`` per session.
        ``source`` is the discriminator added by the foundation
        migration; pre-migration rows return NULL and the consumer
        treats them as ``'interview'``.

        Empty list when the user has no finalized sessions OR the
        DB hiccups — same fail-closed pattern as the rest of
        v2_sessions helpers.
        """
        if not user_id:
            return []
        try:
            res = (
                self.client.table("v2_sessions")
                .select(
                    "id, created_at, kpi_score, global_wpm, "
                    "global_fillers, stickiness_score, source"
                )
                .eq("user_id", user_id)
                .not_.is_("kpi_score", None)
                .order("created_at", desc=False)
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "source" in err_low and "pgrst" in err_low:
                # Foundation migration not yet run — retry without
                # the source column so the chart still renders for
                # whichever rows have kpi_score populated.
                try:
                    res = (
                        self.client.table("v2_sessions")
                        .select(
                            "id, created_at, kpi_score, global_wpm, "
                            "global_fillers, stickiness_score"
                        )
                        .eq("user_id", user_id)
                        .not_.is_("kpi_score", None)
                        .order("created_at", desc=False)
                        .limit(limit)
                        .execute()
                    )
                    return res.data or []
                except Exception as fallback_err:
                    logger.warning(
                        "get_user_kpi_timeline_rows fallback "
                        "failed user=%s err=%s",
                        user_id, fallback_err,
                    )
                    return []
            logger.warning(
                "get_user_kpi_timeline_rows failed user=%s err=%s",
                user_id, e,
            )
            return []

    def list_chat_question_pool(
        self,
        *,
        intent: Optional[str] = None,
        locale: str = "en",
        active_only: bool = True,
    ) -> list[dict]:
        """Admin-facing read of the question pool.

        Filters: ``intent`` ('charisma' | 'stress' | 'trust' |
        'post_official'), ``locale``, ``active_only``. Returns
        ordered by ``created_at`` ascending so the admin sees the
        oldest entries first (matches insertion order for a
        sequentially-seeded pool).

        Returns [] on missing table — the foundation migration
        creates it but a stale env might miss the run.
        """
        try:
            query = (
                self.client.table("chat_question_pool")
                .select("*")
                .eq("locale", locale)
            )
            if intent is not None:
                query = query.eq("intent", intent)
            if active_only:
                query = query.eq("active", True)
            res = query.order("created_at", desc=False).execute()
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if (
                "chat_question_pool" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                return []
            logger.warning(
                "list_chat_question_pool failed err=%s", e,
            )
            return []

    def insert_chat_question(
        self,
        *,
        intent: str,
        text: str,
        weight: int = 100,
        locale: str = "en",
        position_hint: Optional[str] = None,
        created_by: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[dict]:
        """Admin write: insert one question into the pool.

        Validation (intent / position_hint) is handled by the route
        layer's input validator; the DB-level CHECK constraint is
        the final gate and rejects bad enum values with a Postgres
        error that the route catches as 422.
        """
        payload: dict[str, Any] = {
            "intent": intent,
            "text": text,
            "weight": int(weight),
            "locale": locale,
            "active": True,
        }
        if position_hint is not None:
            payload["position_hint"] = position_hint
        if created_by:
            payload["created_by"] = created_by
        if notes:
            payload["notes"] = notes
        try:
            res = (
                self.client.table("chat_question_pool")
                .insert(payload)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            logger.warning(
                "insert_chat_question failed intent=%s err=%s",
                intent, e,
            )
            return None

    def update_chat_question(
        self,
        question_id: str,
        *,
        text: Optional[str] = None,
        weight: Optional[int] = None,
        active: Optional[bool] = None,
        position_hint: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[dict]:
        """Admin write: partial update of one question.

        Only fields explicitly passed are updated. intent + locale
        are intentionally NOT mutable here — those identify the
        question's pool slot; changing them is functionally a
        delete + re-insert and should be modeled that way to keep
        audit history honest.
        """
        payload: dict[str, Any] = {}
        if text is not None:
            payload["text"] = text
        if weight is not None:
            payload["weight"] = int(weight)
        if active is not None:
            payload["active"] = bool(active)
        if position_hint is not None:
            payload["position_hint"] = position_hint
        if notes is not None:
            payload["notes"] = notes
        if not payload:
            # No-op update; return current row.
            try:
                res = (
                    self.client.table("chat_question_pool")
                    .select("*")
                    .eq("id", question_id)
                    .limit(1)
                    .execute()
                )
                rows = res.data or []
                return rows[0] if rows else None
            except Exception:
                return None
        try:
            res = (
                self.client.table("chat_question_pool")
                .update(payload)
                .eq("id", question_id)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            logger.warning(
                "update_chat_question failed qid=%s err=%s",
                question_id, e,
            )
            return None

    def soft_delete_chat_question(self, question_id: str) -> bool:
        """Admin write: flip ``active=False`` on one question.

        Soft-delete rather than hard-delete so the audit trail of
        "this question was previously asked of N users" stays
        intact. Reactivation is an update with active=True.
        """
        try:
            (
                self.client.table("chat_question_pool")
                .update({"active": False})
                .eq("id", question_id)
                .execute()
            )
            return True
        except Exception as e:
            logger.warning(
                "soft_delete_chat_question failed qid=%s err=%s",
                question_id, e,
            )
            return False

    # ── willab beta — Lab session source + history ──────────────────

    def set_session_user_id(self, session_id: str, user_id: str) -> bool:
        """Attribute a session to a user (Prompt D — authed lab takes are owned
        at record time so the explore arc + best-presentation work without
        waiting for the guest→signed claim flow). Best-effort; non-fatal."""
        if not session_id or not user_id:
            return False
        try:
            self.client.table("v2_sessions").update(
                {"user_id": user_id}
            ).eq("id", session_id).execute()
            return True
        except Exception as e:
            logger.warning("set_session_user_id failed sid=%s: %s", session_id, e)
            return False

    def set_session_arc(
        self, session_id: str, arc_id: Optional[str], take_index: Optional[int],
    ) -> bool:
        """Link a session into an explore-session arc (Prompt A §3). Best-effort;
        missing column (migration pending) → False, non-fatal."""
        if not session_id or not arc_id:
            return False
        try:
            self.client.table("v2_sessions").update({
                "arc_id": arc_id, "take_index": take_index,
            }).eq("id", session_id).execute()
            return True
        except Exception as e:
            if "arc_id" in str(e).lower() or "take_index" in str(e).lower():
                logger.warning(
                    "set_session_arc: column missing (run "
                    "migrations/add_explore_arc.sql)",
                )
                return False
            logger.warning("set_session_arc failed sid=%s: %s", session_id, e)
            return False

    def set_session_recording_kind(
        self, session_id: str, kind: str,
        paired_session_id: Optional[str] = None,
    ) -> bool:
        """Tag a session as the SPOKEN take or its READ variant (founder
        2026-07-14). ``paired_session_id`` links a read back to the spoken
        take it corrects. Best-effort: missing column (migration pending) →
        False, non-fatal (the recording still processes; it just reads as
        'spoken' by default downstream)."""
        if not session_id or kind not in ("spoken", "read"):
            return False
        payload: dict = {"recording_kind": kind}
        if paired_session_id:
            payload["paired_session_id"] = str(paired_session_id)
        try:
            self.client.table("v2_sessions").update(payload).eq(
                "id", session_id).execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "recording_kind" in _e or "paired_session_id" in _e:
                logger.warning(
                    "set_session_recording_kind: column missing (run "
                    "migrations/add_recording_kind.sql) sid=%s", session_id,
                )
                return False
            logger.warning("set_session_recording_kind failed sid=%s: %s",
                           session_id, e)
            return False

    # ── willab — delivery layer (founder 2026-07-15) ────────────────────
    # Async analysis state · per-take coach Save · the one-block ideal text
    # · the user's notebook copy. See migrations/add_analysis_state.sql,
    # add_coach_feedback_saved.sql, add_coach_arc_ideal_text.sql,
    # add_user_arc_ideal_notes.sql.

    def set_session_analysis_state(
        self, session_id: str, state: str, error: Optional[str] = None,
    ) -> bool:
        """Flip the async-analysis job state on the session row
        (processing | ready | failed). Best-effort; missing column
        (migration pending) → False (the sync path never reads it)."""
        if not session_id or state not in ("processing", "ready", "failed"):
            return False
        payload: dict = {"analysis_state": state}
        if state == "failed":
            payload["analysis_error"] = (str(error) if error else "unknown")[:500]
        try:
            self.client.table("v2_sessions").update(payload).eq(
                "id", session_id).execute()
        except Exception as e:
            if "analysis_state" in str(e).lower():
                logger.warning(
                    "set_session_analysis_state: column missing (run "
                    "migrations/add_analysis_state.sql) sid=%s", session_id,
                )
                return False
            logger.warning("set_session_analysis_state failed sid=%s: %s",
                           session_id, e)
            return False
        # Push half (docs/BE-HANDOFF-analysis-state-push.md): announce the
        # flip AFTER the write lands, never before — the FE's poll fallback
        # must always agree with what push said. Guarded here too so a broken
        # notifier can never turn a landed write into a reported failure.
        try:
            from services.realtime_notify import broadcast_analysis_state
            broadcast_analysis_state(str(session_id), state)
        except Exception:
            logger.debug(
                "analysis-state broadcast wrapper failed sid=%s", session_id)
        return True

    def set_session_feedback_saved(self, session_id: str) -> bool:
        """Stamp the per-take coach 'Save' checkpoint (nothing delivered —
        the publish requires all 3 takes saved). Best-effort."""
        if not session_id:
            return False
        try:
            self.client.table("v2_sessions").update({
                "coach_feedback_saved_at":
                    datetime.now(timezone.utc).isoformat(),
            }).eq("id", session_id).execute()
            return True
        except Exception as e:
            if "coach_feedback_saved_at" in str(e).lower():
                logger.warning(
                    "set_session_feedback_saved: column missing (run "
                    "migrations/add_coach_feedback_saved.sql) sid=%s",
                    session_id,
                )
                return False
            logger.warning("set_session_feedback_saved failed sid=%s: %s",
                           session_id, e)
            return False

    def get_coach_arc_ideal_text(self, arc_id: Optional[str]) -> Optional[dict]:
        """The coach's one-block ideal text row for an arc, or None (no row /
        missing table / error → the caller falls back to the auto draft)."""
        if not arc_id:
            return None
        try:
            res = (
                self.client.table("coach_arc_ideal_text")
                .select("*")
                .eq("arc_id", str(arc_id))
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            _e = str(e).lower()
            if "coach_arc_ideal_text" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return None
            logger.warning("get_coach_arc_ideal_text failed arc=%s: %s",
                           arc_id, e)
            return None

    def upsert_coach_arc_ideal_text(
        self, arc_id: str, text: str, updated_by: Optional[str],
        *, approve: bool = False,
    ) -> bool:
        """Save (and optionally approve) the coach's one-block ideal text.
        approve=True stamps approved_at — the gate the student GET requires.
        Re-saving after approval keeps approved_at (edits post-approval stay
        approved; the coach explicitly owns the content either way)."""
        if not arc_id or not isinstance(text, str) or not text.strip():
            return False
        payload: dict = {
            "arc_id": str(arc_id),
            "text": text,
            "updated_by": str(updated_by) if updated_by else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if approve:
            payload["approved_at"] = datetime.now(timezone.utc).isoformat()
        try:
            self.client.table("coach_arc_ideal_text").upsert(
                payload, on_conflict="arc_id").execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "coach_arc_ideal_text" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "upsert_coach_arc_ideal_text: table missing (run "
                    "migrations/add_coach_arc_ideal_text.sql) arc=%s", arc_id,
                )
                return False
            logger.warning("upsert_coach_arc_ideal_text failed arc=%s: %s",
                           arc_id, e)
            return False

    def persist_auto_ideal_text(self, arc_id: str, text: str,
                                *, take_count: Optional[int] = None) -> bool:
        """Persist the MACHINE-assembled ideal-text draft (eager assembly at
        take 3, founder 2026-07-15; instant lane 2026-07-17).

        TWO copies since the instant lane:
          * ``auto_text`` — the frozen machine copy: ALWAYS refreshed (a
            re-record improves the free instant surface even after the coach
            starts editing). Never carries coach content.
          * ``text`` — the working/perfected copy: written only while the
            machine still owns it (updated_by IS NULL, unapproved). A coach's
            edit or approval is NEVER overwritten.
        updated_by stays NULL on machine writes (the machine's signature).
        Migration-pending fallback (auto_text column missing): the legacy
        single-column write with the legacy guard. Best-effort; False on
        guard-refuse / missing table / error.

        ``take_count`` — the arc's SPOKEN take count, which since founder
        2026-08-05 IS the version. See the versioning note below."""
        if not arc_id or not isinstance(text, str) or not text.strip():
            return False
        try:
            row = self.get_coach_arc_ideal_text(arc_id)
            coach_owned = bool(
                row and (row.get("updated_by") or row.get("approved_at")))
            _now = datetime.now(timezone.utc).isoformat()
            payload = {
                "arc_id": str(arc_id),
                "auto_text": text,
                "auto_updated_at": _now,
            }
            # ── Versioning: THE VERSION IS THE TAKE COUNT (founder
            # 2026-08-05, "each take is different and each should be
            # verified"). Take 1 → 1.0, take 2 → 2.0, always. A bump
            # implicitly resets verification (verified_version < version
            # reads as unverified), which is the point: each take earns
            # its own coach pass.
            #
            # Pinning to the count rather than incrementing is what makes
            # this SAFE to call repeatedly. The old rule bumped whenever
            # the assembled text differed, so it had two failure modes at
            # once: a take that barely moved the text left the badge
            # frozen (the founder's "take 2 still says 1.0"), while an
            # idle re-open that did shift a character bumped the version
            # and silently un-verified a text nobody re-recorded. An
            # absolute count has neither — recompute it as often as you
            # like and it lands on the same number.
            #
            # take_count=None → the caller could not count (a failed read).
            # Fail CLOSED to the OLD change-detect rule rather than write a
            # wrong absolute: a stale number here would un-verify real
            # coach work. Pre-migration rows: the version key rides the
            # same upsert and the missing-column fallback below drops it.
            _old_auto = (row or {}).get("auto_text") or (
                (row or {}).get("text") if row and not coach_owned else None)
            if isinstance(take_count, int) and take_count >= 1:
                payload["version"] = take_count
            elif row is None:
                payload["version"] = 1
            elif (_old_auto or "").strip() != text.strip():
                _v = row.get("version")
                payload["version"] = (int(_v) + 1) if isinstance(_v, int) else 2
            if not coach_owned:
                payload.update({
                    "text": text,
                    "updated_by": None,
                    "updated_at": _now,
                })
            try:
                self.client.table("coach_arc_ideal_text").upsert(
                    payload, on_conflict="arc_id").execute()
                return True
            except Exception as _e_auto:
                _low = str(_e_auto).lower()
                if "version" in _low and "version" in payload:
                    # Versioning columns not migrated yet (run
                    # migrations/add_ideal_text_versioning.sql) — write the
                    # copies without the version bump.
                    payload.pop("version", None)
                    self.client.table("coach_arc_ideal_text").upsert(
                        payload, on_conflict="arc_id").execute()
                    return True
                if "auto_text" not in _low and "auto_updated_at" not in _low:
                    raise
                # auto columns not migrated yet → the legacy behavior
                # (run migrations/add_ideal_text_auto_copy.sql).
                logger.warning(
                    "persist_auto_ideal_text: auto columns missing (run "
                    "migrations/add_ideal_text_auto_copy.sql) arc=%s", arc_id,
                )
                if coach_owned:
                    return False  # legacy guard: never clobber the coach
                self.client.table("coach_arc_ideal_text").upsert({
                    "arc_id": str(arc_id),
                    "text": text,
                    "updated_by": None,
                    "updated_at": _now,
                }, on_conflict="arc_id").execute()
                return True
        except Exception as e:
            _e = str(e).lower()
            if "coach_arc_ideal_text" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "persist_auto_ideal_text: table missing (run "
                    "migrations/add_coach_arc_ideal_text.sql) arc=%s", arc_id,
                )
                return False
            logger.warning("persist_auto_ideal_text failed arc=%s: %s",
                           arc_id, e)
            return False

    def verify_ideal_text(self, arc_id: str, coach_id: Optional[str]) -> Optional[str]:
        """Coach VERIFY (single deliverable, founder 2026-07-17): snapshot the
        current best text as the VERIFIED copy of the CURRENT version — the
        coach's working copy when a human owns the row, else the machine copy.
        The snapshot keeps the served "verified" text stable even while the
        coach keeps editing afterwards; a later reassembly bumps `version`,
        which implicitly resets status to unverified.

        Returns 'verified' | 'already' (current version already verified) |
        None (nothing to verify / error)."""
        if not arc_id:
            return None
        try:
            row = self.get_coach_arc_ideal_text(arc_id)
            if not row:
                return None
            coach_owned = bool(row.get("updated_by") or row.get("approved_at"))
            best = ((row.get("text") or "") if coach_owned
                    else (row.get("auto_text") or row.get("text") or ""))
            best = best.strip()
            if not best:
                return None
            _v = row.get("version")
            version = int(_v) if isinstance(_v, int) else 1
            _vv = row.get("verified_version")
            if isinstance(_vv, int) and _vv == version:
                return "already"
            self.client.table("coach_arc_ideal_text").upsert({
                "arc_id": str(arc_id),
                "verified_version": version,
                "verified_text": best,
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "verified_by": str(coach_id) if coach_id else None,
            }, on_conflict="arc_id").execute()
            return "verified"
        except Exception as e:
            logger.warning("verify_ideal_text failed arc=%s: %s", arc_id, e)
            return None

    def get_moment_unlock(self, arc_id: Optional[str]) -> Optional[dict]:
        """The presentation's key-moment unlock row (single deliverable,
        founder 2026-07-17 — the ONLY paid item: 5 credits, one-time per
        presentation, covers all current AND future moments). Deliberately a
        SEPARATE table from the retired $25 arc_purchases — no grandfathering
        (founder-explicit). None on missing table / no row / error."""
        if not arc_id:
            return None
        try:
            res = (
                self.client.table("moment_unlocks")
                .select("*")
                .eq("arc_id", str(arc_id))
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            _e = str(e).lower()
            if "moment_unlocks" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return None  # migration pending → locked (never open)
            logger.warning("get_moment_unlock failed arc=%s: %s", arc_id, e)
            return None

    def insert_moment_unlock(
        self, arc_id: str, user_id: str, credits_spent: int,
    ) -> Optional[dict]:
        """Exclusive claim of the moments unlock — unique(arc_id) is the
        atomic double-charge guard (mirrors arc_purchases). Returns the row,
        or None on ANY conflict/error (the caller refunds)."""
        if not arc_id or not user_id:
            return None
        try:
            res = (
                self.client.table("moment_unlocks")
                .insert({
                    "arc_id": str(arc_id),
                    "user_id": str(user_id),
                    "credits_spent": int(credits_spent),
                })
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            logger.warning("insert_moment_unlock conflict/failure arc=%s: %s",
                           arc_id, e)
            return None

    def get_user_arc_ideal_notes(
        self, arc_id: Optional[str], user_id: Optional[str],
    ) -> Optional[str]:
        """The user's personal notebook copy of the ideal text (or None)."""
        if not arc_id or not user_id:
            return None
        try:
            res = (
                self.client.table("user_arc_ideal_notes")
                .select("text")
                .eq("arc_id", str(arc_id))
                .eq("user_id", str(user_id))
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0].get("text") if rows else None
        except Exception as e:
            _e = str(e).lower()
            if "user_arc_ideal_notes" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return None
            logger.warning("get_user_arc_ideal_notes failed arc=%s: %s",
                           arc_id, e)
            return None

    def upsert_user_arc_ideal_notes(
        self, arc_id: str, user_id: str, text: str,
    ) -> bool:
        """Save the user's personal notebook copy. NEVER touches the coach
        canonical (L1 — the deliverable stays the coach-approved select)."""
        if not arc_id or not user_id or not isinstance(text, str):
            return False
        try:
            self.client.table("user_arc_ideal_notes").upsert({
                "arc_id": str(arc_id),
                "user_id": str(user_id),
                "text": text,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="arc_id,user_id").execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "user_arc_ideal_notes" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "upsert_user_arc_ideal_notes: table missing (run "
                    "migrations/add_user_arc_ideal_notes.sql) arc=%s", arc_id,
                )
                return False
            logger.warning("upsert_user_arc_ideal_notes failed arc=%s: %s",
                           arc_id, e)
            return False

    def get_user_ideal_edit(
        self, arc_id: Optional[str], user_id: Optional[str],
    ) -> Optional[dict]:
        """The student's in-place SD edit of the ideal text (founder
        2026-07-17): {text, version, updated_at} or None. Sibling columns on
        user_arc_ideal_notes — never the legacy `text` notebook copy. Missing
        column (migration pending) / no row / error → None."""
        if not arc_id or not user_id:
            return None
        try:
            res = (
                self.client.table("user_arc_ideal_notes")
                .select("user_text, user_text_version, updated_at")
                .eq("arc_id", str(arc_id))
                .eq("user_id", str(user_id))
                .limit(1)
                .execute()
            )
            rows = res.data or []
            if not rows:
                return None
            r = rows[0]
            _text = r.get("user_text")
            if not isinstance(_text, str) or not _text.strip():
                return None
            return {
                "text": _text,
                "version": r.get("user_text_version"),
                "updated_at": r.get("updated_at"),
            }
        except Exception as e:
            _e = str(e).lower()
            if any(c in _e for c in (
                "user_text", "user_arc_ideal_notes",
            )) and ("does not exist" in _e or "pgrst" in _e):
                return None
            logger.warning("get_user_ideal_edit failed arc=%s: %s", arc_id, e)
            return None

    def upsert_user_ideal_edit(
        self, arc_id: str, user_id: str, text: str, version: Optional[int],
    ) -> bool:
        """Persist the student's in-place SD edit + the version it was made
        against (sibling columns; NEVER touches the coach canonical or the
        legacy `text` notebook — L1). Best-effort; False on missing column
        (migration pending) / error."""
        if not arc_id or not user_id or not isinstance(text, str):
            return False
        try:
            self.client.table("user_arc_ideal_notes").upsert({
                "arc_id": str(arc_id),
                "user_id": str(user_id),
                # user_arc_ideal_notes.text is NOT NULL — keep the row valid
                # without disturbing a real notebook copy: only default it to
                # "" when creating a fresh row (the coalesce keeps any existing
                # notebook text on a pure edit-update via on_conflict).
                "user_text": text,
                "user_text_version": (
                    int(version) if isinstance(version, int) else None),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="arc_id,user_id").execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if any(c in _e for c in (
                "user_text", "user_arc_ideal_notes",
            )) and ("does not exist" in _e or "pgrst" in _e):
                logger.warning(
                    "upsert_user_ideal_edit: column/table missing (run "
                    "migrations/add_user_ideal_edit.sql) arc=%s", arc_id)
                return False
            logger.warning("upsert_user_ideal_edit failed arc=%s: %s",
                           arc_id, e)
            return False

    # ── ideal_text_part — the document as an ordered list with stable ids ──
    # SPEC-parts-locking-and-layers §3.1, Step 0. Identity only; PR 3 adds the
    # lock. Both of these are best-effort in the same sense as the edit lane
    # above: a missing table (migration 0255 not applied) degrades to "this
    # document has no parts", which is exactly the pre-migration behaviour.

    def get_ideal_text_parts(
        self, arc_id: Optional[str], user_id: Optional[str],
        *, with_lock: bool = False,
    ) -> list:
        """One document's parts, in `ord` order. [] on anything missing.

        Keyed (arc_id, user_id) to match `user_arc_ideal_notes` — the served
        document is derived per request, so arc_id alone does not name one.

        `with_lock` adds `locked_at` (migration 0256). OPT-IN rather than
        always selected: the student payload must never carry it (AC-9 is not
        the issue — a lock is not a score — but the parts block is a wire
        contract, and a field nobody asked for is a field someone renders).
        The layer filter asks for it; the serve path does not.
        """
        if not arc_id or not user_id:
            return []
        try:
            res = (
                self.client.table("ideal_text_part")
                .select("id, ord, text, locked_at" if with_lock
                        else "id, ord, text")
                .eq("arc_id", str(arc_id))
                .eq("user_id", str(user_id))
                .order("ord")
                .execute()
            )
            return res.data or []
        except Exception as e:
            _e = str(e).lower()
            if ("ideal_text_part" in _e or "locked_at" in _e) and (
                    "does not exist" in _e or "pgrst" in _e):
                # Two different pre-migration states, one degrade. Missing
                # TABLE (0255) → no identity; missing COLUMN (0256) → identity
                # without locks. Both mean "no locks to enforce", and the layer
                # filter treats an empty list as "everything is allowed" —
                # which is the safe direction, because R1 SUPPRESSES
                # interventions and a bad read must never silence the surface.
                logger.warning(
                    "get_ideal_text_parts: table/column missing (run "
                    "migrations/add_ideal_text_parts.sql, "
                    "add_ideal_text_part_lock.sql) arc=%s", arc_id)
                return []
            logger.warning("get_ideal_text_parts failed arc=%s: %s", arc_id, e)
            return []

    def set_ideal_text_part_lock(
        self, arc_id: str, user_id: str, part_id: str, locked: bool,
    ) -> bool:
        """Lock or unlock ONE part (SPEC §4, R5). True on success.

        Scoped to (arc_id, user_id) as well as the part id, so a caller cannot
        reach another document's part by guessing an id — the id alone is the
        primary key, and a route that trusted it would be an IDOR.

        UNLOCK CLEARS THE COLUMN rather than writing a history row (R5). The
        lock is live UI state, not an audit trail; what §6 needs recorded is
        the DECISION on each intervention, which lives on its own row and is
        never rewritten by a lock or an unlock.
        """
        if not arc_id or not user_id or not part_id:
            return False
        try:
            update: dict = {
                "locked_at": (datetime.now(timezone.utc).isoformat()
                              if locked else None),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if locked:
                # The MATURITY counter (slice 2, founder 2026-08-11): +1 on
                # every lock-in, never on unlock. Read-then-write — this is
                # a single-student tap path, not a contended counter — and
                # best-effort: pre-migration the lock still lands, the
                # counter simply holds at nothing.
                try:
                    cur = (
                        self.client.table("ideal_text_part")
                        .select("iteration")
                        .eq("id", str(part_id))
                        .eq("arc_id", str(arc_id))
                        .eq("user_id", str(user_id))
                        .limit(1)
                        .execute()
                    )
                    row0 = (cur.data or [{}])[0] or {}
                    update["iteration"] = int(row0.get("iteration") or 0) + 1
                except Exception:
                    pass
            def _do(payload: dict):
                return (
                    self.client.table("ideal_text_part")
                    .update(payload)
                    .eq("id", str(part_id))
                    .eq("arc_id", str(arc_id))
                    .eq("user_id", str(user_id))
                    .execute()
                )
            try:
                res = _do(update)
            except Exception as inner:
                # Pre-migration column miss: the LOCK must land even when
                # the counter cannot — retry without it, never fail the tap
                # on a column that is not there yet.
                if "iteration" in update and (
                        "iteration" in str(inner).lower()
                        or "pgrst204" in str(inner).lower()):
                    update.pop("iteration", None)
                    res = _do(update)
                else:
                    raise
            # An update that matched NOTHING is not a success. Postgres has no
            # complaint to make about it, so without this a lock on a part that
            # does not belong to this document returns 200 and does nothing —
            # and the FE would draw a locked paragraph that is not locked.
            return bool(res.data)
        except Exception as e:
            _e = str(e).lower()
            if ("ideal_text_part" in _e or "locked_at" in _e) and (
                    "does not exist" in _e or "pgrst" in _e):
                logger.warning(
                    "set_ideal_text_part_lock: table/column missing (run "
                    "migrations/add_ideal_text_part_lock.sql) arc=%s", arc_id)
                return False
            logger.warning("set_ideal_text_part_lock failed arc=%s: %s",
                           arc_id, e)
            return False

    def replace_ideal_text_parts(
        self, arc_id: str, user_id: str, parts: list,
    ) -> bool:
        """Replace a document's parts wholesale. True on success.

        WHOLESALE, NOT PER-ROW UPSERT, and the unique index is why. A reorder
        changes many rows' `ord` at once; upserting them one at a time walks
        through states where two rows claim one slot, and
        `uq_ideal_text_part_slot` would reject whichever came second — leaving
        the document half-reordered. Delete-then-insert has no intermediate
        state to violate.

        The delete is the RISK in that trade: if the insert fails, the parts
        are gone. That is survivable and deliberately so — parts are pure
        identity, the canonical `text` is written separately and is untouched,
        and a document with no parts is a valid state the client re-mints from.
        Losing identity costs the ids; losing the words would cost the words.
        """
        if not arc_id or not user_id or not isinstance(parts, list):
            return False
        try:
            # ITERATION SURVIVES THE REPLACE (bug, found 2026-08-12).
            #
            # The insert below names the columns it writes, so EVERY column it
            # omits silently returns to its DEFAULT — and `iteration` (0265)
            # defaults to 0. Lock a chunk (iteration → 1), record another take,
            # open the readout: `compose_locked` reports `changed`, the parts
            # are replaced, and the founder's "Locked in · N iterations" kicker
            # is back to zero with nothing in the logs to say so.
            #
            # All three call sites carefully read `locked_at` back and thread
            # it through, and not one of them mentions `iteration` — which is
            # the shape of the hazard: preserving a column is opt-in and
            # forgetting is the default. So the preservation lives HERE, once,
            # where it cannot be forgotten by a fourth caller.
            #
            # Read before the delete: afterwards there is nothing to read.
            prev_iter: dict = {}
            try:
                _res = (self.client.table("ideal_text_part")
                        .select("id, iteration")
                        .eq("arc_id", str(arc_id))
                        .eq("user_id", str(user_id))
                        .execute())
                prev_iter = {str(r.get("id")): int(r.get("iteration") or 0)
                             for r in (_res.data or []) if isinstance(r, dict)}
            except Exception as _it_err:
                # A pre-0265 database has no such column. Degrade to "no
                # maturity counters", never to a failed document write.
                logger.warning(
                    "replace_ideal_text_parts: iteration unreadable arc=%s: "
                    "%s (counters reset)", arc_id, _it_err)
            (self.client.table("ideal_text_part")
                .delete()
                .eq("arc_id", str(arc_id))
                .eq("user_id", str(user_id))
                .execute())
            if not parts:
                return True     # the student cleared the document
            self.client.table("ideal_text_part").insert([
                {
                    "id": str(p["id"]),
                    "arc_id": str(arc_id),
                    "user_id": str(user_id),
                    "ord": int(p["ord"]),
                    "text": str(p["text"]),
                    # The lock rides the replace so auto-lock and compose can
                    # persist in ONE write. Absent/None = open; a caller that
                    # wants to preserve an existing lock passes the original
                    # timestamp through (never re-stamped — a decision made
                    # before a lock and one after mean different things, §6).
                    "locked_at": p.get("locked_at"),
                    # An EXPLICIT caller value wins (a fresh part carries
                    # none); otherwise the stored counter is carried across.
                    "iteration": (p.get("iteration")
                                  if isinstance(p.get("iteration"), int)
                                  else prev_iter.get(str(p["id"]), 0)),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                for p in parts
            ]).execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "ideal_text_part" in _e and (
                    "does not exist" in _e or "pgrst" in _e):
                logger.warning(
                    "replace_ideal_text_parts: table missing (run "
                    "migrations/add_ideal_text_parts.sql) arc=%s", arc_id)
                return False
            logger.warning("replace_ideal_text_parts failed arc=%s: %s",
                           arc_id, e)
            return False

    # ── the acoustic KPI (founder 2026-08-12) ──────────────────────────────
    # The speaker's own baseline, and the per-part moving average that is
    # measured against it. Best-effort in the same sense as everything above:
    # a missing table (migrations 0268/0269 not applied) degrades to "no
    # baseline / no history", which is the cold-start state the readers are
    # already written for and is exactly the pre-migration behaviour.

    def insert_user_acoustic_baseline(
        self, user_id: str, features: dict, *,
        n_sessions: int = 0, n_samples: int = 0,
        detector_version: str = "",
    ) -> Optional[str]:
        """Append a baseline snapshot; return its id, or None.

        APPEND-ONLY (founder immutability rule). The insert lands FIRST and
        the previous row is superseded after — interrupted between the two
        leaves two current rows, and the reader takes the newest, which is
        degraded but correct. The reverse order leaves a window with NO
        current baseline, which reads as cold start and would drop the user
        out of single-point focus for no reason at all.

        The supersede is best-effort ON TOP of a successful insert: failing to
        mark the old row must not lose the new one.
        """
        if not user_id or not isinstance(features, dict) or not features:
            return None
        try:
            res = (self.client.table("user_acoustic_baseline")
                   .insert({
                       "user_id": str(user_id),
                       "features": features,
                       "n_sessions": int(n_sessions),
                       "n_samples": int(n_samples),
                       "detector_version": str(detector_version),
                   })
                   .execute())
            rows = res.data or []
            new_id = str(rows[0].get("id")) if rows else None
        except Exception as e:
            _e = str(e).lower()
            if "user_acoustic_baseline" in _e and (
                    "does not exist" in _e or "pgrst" in _e):
                logger.warning(
                    "insert_user_acoustic_baseline: table missing (run "
                    "migrations/add_user_acoustic_baseline.sql) user=%s",
                    user_id)
                return None
            logger.warning("insert_user_acoustic_baseline failed user=%s: %s",
                           user_id, e)
            return None
        if not new_id:
            return None
        try:
            (self.client.table("user_acoustic_baseline")
                .update({"superseded_at": datetime.now(timezone.utc)
                         .isoformat()})
                .eq("user_id", str(user_id))
                .eq("detector_version", str(detector_version))
                .is_("superseded_at", "null")
                .neq("id", new_id)
                .execute())
        except Exception as e:
            logger.warning(
                "insert_user_acoustic_baseline: supersede failed user=%s: %s "
                "(new row %s stands)", user_id, e, new_id)
        return new_id

    def get_current_user_acoustic_baseline(
        self, user_id: str, *, detector_version: str = "",
    ) -> Optional[dict]:
        """This user's current baseline row for one regime, or None.

        Ordered newest-first and limited to one rather than assuming a single
        current row: the append-then-supersede order above can legitimately
        leave two, and "the newest wins" is the rule that makes that state
        correct instead of ambiguous.
        """
        if not user_id:
            return None
        try:
            res = (self.client.table("user_acoustic_baseline")
                   .select("id, features, n_sessions, n_samples, computed_at")
                   .eq("user_id", str(user_id))
                   .eq("detector_version", str(detector_version))
                   .is_("superseded_at", "null")
                   .order("computed_at", desc=True)
                   .limit(1)
                   .execute())
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            _e = str(e).lower()
            if "user_acoustic_baseline" in _e and (
                    "does not exist" in _e or "pgrst" in _e):
                logger.warning(
                    "get_current_user_acoustic_baseline: table missing (run "
                    "migrations/add_user_acoustic_baseline.sql) user=%s",
                    user_id)
                return None
            logger.warning(
                "get_current_user_acoustic_baseline failed user=%s: %s",
                user_id, e)
            return None

    def get_arc_part_acoustics(
        self, arc_id: Optional[str], user_id: Optional[str],
    ) -> list:
        """One document's per-part acoustic rows. [] on anything missing.

        [] is the cold-start answer and the failure answer alike, and both are
        safe in the same direction: `focus_part_id([])` is None, and None
        means "no focus established — behave exactly as before". A bad read
        can therefore never SUPPRESS feedback, only decline to concentrate it.
        """
        if not arc_id or not user_id:
            return []
        try:
            res = (self.client.table("arc_part_acoustics")
                   .select("part_id, ema_z, n_takes, came_onboard_at, "
                           "baseline_id, last_take_session_id")
                   .eq("arc_id", str(arc_id))
                   .eq("user_id", str(user_id))
                   .order("ema_z")
                   .execute())
            return res.data or []
        except Exception as e:
            _e = str(e).lower()
            if "arc_part_acoustics" in _e and (
                    "does not exist" in _e or "pgrst" in _e):
                logger.warning(
                    "get_arc_part_acoustics: table missing (run "
                    "migrations/add_arc_part_acoustics.sql) arc=%s", arc_id)
                return []
            logger.warning("get_arc_part_acoustics failed arc=%s: %s",
                           arc_id, e)
            return []

    def upsert_arc_part_acoustics(self, rows: list) -> bool:
        """Write per-part acoustic rows. True on success.

        Per-row upsert on the PRIMARY KEY, NOT the wholesale delete-then-
        insert `replace_ideal_text_parts` uses. The two are different problems:
        parts are replaced together because a reorder moves many `ord` values
        at once and the slot index cannot survive the intermediate state.
        These rows have no ordering constraint between them, and a delete here
        would throw away the take history of every part the current take did
        not happen to cover — which is the exact hazard that put this table
        beside `ideal_text_part` instead of on it.

        `came_onboard_at` is stamped only on the TRANSITION. An already-onboard
        row keeps its original timestamp: the ratchet records when a part came
        onboard, and re-stamping it every take would erase that.
        """
        if not rows:
            return False
        try:
            now = datetime.now(timezone.utc).isoformat()
            prev = {}
            first = rows[0] if isinstance(rows[0], dict) else {}
            if first.get("arc_id") and first.get("user_id"):
                prev = {
                    str(r.get("part_id")): r.get("came_onboard_at")
                    for r in (self.get_arc_part_acoustics(
                        first["arc_id"], first["user_id"]) or [])
                    if isinstance(r, dict) and r.get("came_onboard_at")
                }
            payload = []
            for r in rows:
                if not isinstance(r, dict) or not r.get("part_id"):
                    continue
                pid = str(r["part_id"])
                onboard_at = prev.get(pid)
                if not onboard_at and r.get("came_onboard"):
                    onboard_at = now
                payload.append({
                    "part_id": pid,
                    "arc_id": str(r.get("arc_id") or ""),
                    "user_id": str(r.get("user_id") or ""),
                    "ema_z": float(r.get("ema_z") or 0.0),
                    "n_takes": int(r.get("n_takes") or 0),
                    "last_take_session_id": r.get("last_take_session_id"),
                    "came_onboard_at": onboard_at,
                    "baseline_id": r.get("baseline_id"),
                    "detector_version": str(r.get("detector_version") or ""),
                    "updated_at": now,
                })
            if not payload:
                return False
            (self.client.table("arc_part_acoustics")
                .upsert(payload, on_conflict="part_id")
                .execute())
            return True
        except Exception as e:
            _e = str(e).lower()
            if "arc_part_acoustics" in _e and (
                    "does not exist" in _e or "pgrst" in _e):
                logger.warning(
                    "upsert_arc_part_acoustics: table missing (run "
                    "migrations/add_arc_part_acoustics.sql)")
                return False
            logger.warning("upsert_arc_part_acoustics failed: %s", e)
            return False

    # The star-suggestion kinds. MUST mirror the moment_suggestions kind
    # CHECK (alter_moment_suggestions_kind_delivery.sql) — the 2026-07-20
    # lesson: #221 widened the DB CHECK but not this guard, so 'delivery'
    # rows were rejected HERE and the feature ran silently inert in prod.
    # Pinned by test_delivery_stars.
    SUGGESTION_KINDS = ("emphasize", "replace", "structure", "delivery")

    def upsert_moment_suggestion(
        self, snippet_id: str, arc_id: str, kind: str,
        replacement_text: Optional[str], why: Optional[str],
        trigger: Optional[str],
    ) -> bool:
        """One star suggestion per snippet (founder 2026-07-18). Idempotent
        on snippet_id (a reassembly regenerates in place). Best-effort."""
        if not snippet_id or not arc_id \
                or kind not in self.SUGGESTION_KINDS:
            return False
        try:
            self.client.table("moment_suggestions").upsert({
                "snippet_id": str(snippet_id),
                "arc_id": str(arc_id),
                "kind": kind,
                "replacement_text": replacement_text,
                "why": why,
                "trigger": trigger,
            }, on_conflict="snippet_id").execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "moment_suggestions" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "upsert_moment_suggestion: table missing (run "
                    "migrations/add_moment_suggestions.sql)")
                return False
            logger.warning("upsert_moment_suggestion failed snip=%s: %s",
                           snippet_id, e)
            return False

    def get_moment_suggestions_by_arc(self, arc_id: Optional[str]) -> dict:
        """{snippet_id: suggestion row} for one presentation. Best-effort:
        {} on missing table / error (no stars, never a break).

        FOLD (founder 2026-07-28, coach star-text corrections): the returned
        ``why`` / ``replacement_text`` are the coach's final WHEN one exists,
        else the machine draft — done HERE, at the one reader, so every
        consumer (the ideal-text serve, the decision ledger's phrase keying,
        the snapshot, tracked changes) shows the corrected wording without
        any of them knowing the twin columns exist. The raw drafts ride along
        as ``why_draft`` / ``replacement_text_draft`` for the two consumers
        that need the pair (the coach stars review + the corpus emission).
        Pre-migration rows simply have no *_final keys → the fold no-ops."""
        if not arc_id:
            return {}
        try:
            res = (
                self.client.table("moment_suggestions")
                .select("*")
                .eq("arc_id", str(arc_id))
                .execute()
            )
            out: dict = {}
            for r in (res.data or []):
                if not r.get("snippet_id"):
                    continue
                r = dict(r)
                r["why_draft"] = r.get("why")
                r["replacement_text_draft"] = r.get("replacement_text")
                if r.get("why_final"):
                    r["why"] = r["why_final"]
                if r.get("replacement_text_final"):
                    r["replacement_text"] = r["replacement_text_final"]
                out[str(r["snippet_id"])] = r
            return out
        except Exception as e:
            _e = str(e).lower()
            if "moment_suggestions" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return {}
            logger.warning("get_moment_suggestions_by_arc failed arc=%s: %s",
                           arc_id, e)
            return {}

    # Sentinel for set_moment_suggestion_final: "this field was not sent —
    # leave the stored value alone". Distinct from None, which CLEARS.
    _FINAL_UNSET = object()

    def set_moment_suggestion_final(
        self, snippet_id: str, *, why_final: Any = _FINAL_UNSET,
        replacement_text_final: Any = _FINAL_UNSET,
        edited_by: Optional[str] = None,
    ) -> bool:
        """The coach's corrected star wording (founder 2026-07-28) — plain
        update, re-editable until they're done (mirrors
        set_charisma_snippet_say_it_stronger_final). The machine's draft
        columns are NEVER touched: the (draft, final) pair is the correction
        corpus.

        Three values per field: a string SETS the correction, an explicit
        None CLEARS it (revert to the draft — the full-state star-text PUT),
        and omitting the argument PRESERVES whatever is stored (the §4b
        verdict piggyback, whose wire only carries fields the coach actually
        changed). Both omitted → no-op, True. Best-effort,
        missing-column-safe; never raises."""
        if not snippet_id:
            return False
        payload: dict = {}
        if why_final is not self._FINAL_UNSET:
            payload["why_final"] = why_final
        if replacement_text_final is not self._FINAL_UNSET:
            payload["replacement_text_final"] = replacement_text_final
        if not payload:
            return True
        payload["text_final_updated_at"] = \
            datetime.now(timezone.utc).isoformat()
        if edited_by:
            payload["text_final_by"] = str(edited_by)
        try:
            (self.client.table("moment_suggestions")
                 .update(payload)
                 .eq("snippet_id", str(snippet_id)).execute())
            return True
        except Exception as e:
            _e = str(e).lower()
            if ("why_final" in _e or "replacement_text_final" in _e
                    or "text_final" in _e):
                logger.warning(
                    "set_moment_suggestion_final: columns missing (run "
                    "migrations/add_moment_suggestion_final.sql)",
                )
                return False
            logger.warning("set_moment_suggestion_final failed snip=%s: %s",
                           snippet_id, e)
            return False

    # ── ideal-text decision ledger (founder 2026-07-20) ──────────────
    # Phrase-keyed memory of approved/dismissed suggestions; see
    # services/ideal_decision_ledger.py + add_ideal_decision_ledger.sql.
    # All best-effort with the table-missing degradation (LIVE LOOP).

    def upsert_ideal_decision(self, *, arc_id: str, kind: str,
                              target_phrase: str,
                              display_phrase: Optional[str],
                              replacement_text: Optional[str],
                              decision: str, source: Optional[str],
                              snippet_id: Optional[str],
                              version: Optional[int]) -> bool:
        """One decision per (arc, kind, phrase) — last write wins (an
        applied→dismissed flip updates in place). Best-effort."""
        if not arc_id or not target_phrase \
                or kind not in ("polish", "replace", "emphasize") \
                or decision not in ("approved", "dismissed"):
            return False
        try:
            self.client.table("ideal_decision_ledger").upsert({
                "arc_id": str(arc_id),
                "kind": kind,
                "target_phrase": target_phrase,
                "display_phrase": display_phrase,
                "replacement_text": replacement_text,
                "decision": decision,
                "source": source,
                "snippet_id": snippet_id,
                "version": version,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="arc_id,kind,target_phrase").execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "ideal_decision_ledger" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "upsert_ideal_decision: table missing (run "
                    "migrations/add_ideal_decision_ledger.sql)")
                return False
            logger.warning("upsert_ideal_decision failed arc=%s: %s",
                           arc_id, e)
            return False

    def delete_moment_suggestion(self, snippet_id: Optional[str]) -> bool:
        """Drop one star row — a DISMISSED star must not survive to the
        next serve/anchor pass (founder 2026-07-20 rule 2; the ledger
        remembers the decision, this removes the offer). Best-effort."""
        if not snippet_id:
            return False
        try:
            (self.client.table("moment_suggestions")
             .delete()
             .eq("snippet_id", str(snippet_id))
             .execute())
            return True
        except Exception as e:
            logger.warning("delete_moment_suggestion failed snip=%s: %s",
                           snippet_id, e)
            return False

    def delete_ideal_decision(self, arc_id: str, kind: str,
                              target_phrase: str) -> bool:
        """A reverted approval wipes the row — the phrase becomes
        suggestible again. Best-effort."""
        if not arc_id or not kind or not target_phrase:
            return False
        try:
            (self.client.table("ideal_decision_ledger")
             .delete()
             .eq("arc_id", str(arc_id))
             .eq("kind", kind)
             .eq("target_phrase", target_phrase)
             .execute())
            return True
        except Exception as e:
            logger.warning("delete_ideal_decision failed arc=%s: %s",
                           arc_id, e)
            return False

    def list_intervention_decision_history(self, arc_id: Optional[str],
                                           limit: int = 50) -> list:
        """The arc's decided proposals THAT STILL CARRY THEIR TEXT — the
        deck editor's "proposals from earlier iterations" (slice 2,
        founder 2026-08-11). Rows written before the texts migration have
        no quote and are unlistable — filtered here, never invented.
        Newest first. [] pre-migration / on hiccup."""
        if not arc_id:
            return []
        try:
            res = (
                self.client.table("intervention_decisions")
                .select("change_key,decision,lane,intervention_type,"
                        "quote,proposed_text,why_key,updated_at")
                .eq("arc_id", str(arc_id))
                .order("updated_at", desc=True)
                .limit(max(1, int(limit)))
                .execute()
            )
            return [r for r in (res.data or [])
                    if isinstance(r, dict) and (r.get("quote")
                                                or r.get("proposed_text"))]
        except Exception as e:
            logger.warning(
                "list_intervention_decision_history failed arc=%s: %s",
                arc_id, e)
            return []

    def record_intervention_decision(self, *, arc_id: str,
                                     take_session_id: str,
                                     change_key: str,
                                     decision: str,
                                     lane: Optional[str] = None,
                                     intervention_type: Optional[str] = None,
                                     quote: Optional[str] = None,
                                     proposed_text: Optional[str] = None,
                                     why_key: Optional[str] = None,
                                     ) -> bool:
        """One decided intervention — SPEC §3.3's ground-truth row AND one
        spent budget slot (founder 2026-08-10: the ≤3 is PER TAKE, and a
        decided offer never frees its slot). Vocabulary is the SPEC's:
        approved / disregarded; absence of a row means UNDECIDED (R4).
        Upsert on the offer's identity so a re-tap updates in place rather
        than double-spending. lane/intervention_type ride along when the
        caller knows them — they are the §6 join to intervention_arms.
        Best-effort."""
        if not arc_id or not change_key \
                or decision not in ("approved", "disregarded"):
            return False
        try:
            row: dict = {
                "arc_id": str(arc_id),
                "take_session_id": str(take_session_id or ""),
                "change_key": str(change_key),
                "decision": decision,
                "lane": lane,
                "intervention_type": intervention_type,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            # The proposal texts (slice 2 history) ride only when the caller
            # HAS them: a re-tap without them must not null what an earlier
            # write stored. Pre-migration these keys would 400 the upsert, so
            # a schema-cache miss retries without them — the decision (the
            # spend) must never be lost to the history columns.
            texts = {k: v for k, v in (("quote", quote),
                                       ("proposed_text", proposed_text),
                                       ("why_key", why_key)) if v}
            try:
                self.client.table("intervention_decisions").upsert(
                    {**row, **texts},
                    on_conflict="arc_id,take_session_id,change_key").execute()
            except Exception as inner:
                if not texts:
                    raise
                _ie = str(inner).lower()
                if "quote" in _ie or "proposed_text" in _ie \
                        or "why_key" in _ie or "pgrst204" in _ie:
                    self.client.table("intervention_decisions").upsert(
                        row,
                        on_conflict="arc_id,take_session_id,change_key"
                    ).execute()
                else:
                    raise
            return True
        except Exception as e:
            _e = str(e).lower()
            if "intervention_decisions" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "record_intervention_decision: table missing (run "
                    "migrations/add_intervention_decisions.sql)")
                return False
            logger.warning("record_intervention_decision failed arc=%s: %s",
                           arc_id, e)
            return False

    def delete_intervention_decision(self, *, arc_id: str,
                                     take_session_id: str,
                                     change_key: str) -> bool:
        """A reverted decision returns its slot — the offer is undecided
        again and the take's budget grows back by one. Best-effort."""
        if not arc_id or not change_key:
            return False
        try:
            (self.client.table("intervention_decisions")
             .delete()
             .eq("arc_id", str(arc_id))
             .eq("take_session_id", str(take_session_id or ""))
             .eq("change_key", str(change_key))
             .execute())
            return True
        except Exception as e:
            logger.warning("delete_intervention_decision failed arc=%s: %s",
                           arc_id, e)
            return False

    # ── BLINDED A/B SLIDE VERDICTS (founder 2026-08-11) ──────────────────
    #
    # The corpus that unblocks piece (b) — see
    # migrations/add_slide_ab_verdicts.sql for what a row means and why the
    # sides are stored AS SHOWN rather than as winner/loser.

    def record_slide_ab_verdict(self, *, arc_id: str, slide_index: int,
                                session_left: str, session_right: str,
                                verdict: str,
                                winner_session_id: Optional[str] = None,
                                left_text: Optional[str] = None,
                                right_text: Optional[str] = None,
                                rated_by: Optional[str] = None) -> bool:
        """One blinded comparison. Append-only — a re-rating is a new row, so
        intra-rater reliability stays computable. Best-effort: a labelling
        write must never break the review it rides with."""
        if not arc_id or verdict not in ("left", "right", "tie"):
            return False
        try:
            self.client.table("slide_ab_verdicts").insert({
                "arc_id": str(arc_id),
                "slide_index": int(slide_index),
                "session_left": str(session_left),
                "session_right": str(session_right),
                "verdict": verdict,
                "winner_session_id": (
                    str(winner_session_id) if winner_session_id else None
                ),
                "left_text": left_text,
                "right_text": right_text,
                "rated_by": str(rated_by) if rated_by else None,
            }).execute()
            return True
        except Exception as e:
            logger.warning("record_slide_ab_verdict failed arc=%s: %s",
                           arc_id, e)
            return False

    def list_slide_ab_verdicts(self, arc_id: str) -> list:
        """Every verdict for an arc, newest first — the corpus AND the
        already-rated set the serve subtracts. [] pre-migration."""
        if not arc_id:
            return []
        try:
            res = (
                self.client.table("slide_ab_verdicts")
                .select("*")
                .eq("arc_id", str(arc_id))
                .order("created_at", desc=True)
                .execute()
            )
            return list(res.data or [])
        except Exception as e:
            _e = str(e).lower()
            if "slide_ab_verdicts" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return []
            logger.warning("list_slide_ab_verdicts failed arc=%s: %s",
                           arc_id, e)
            return []

    # ── THE COACH'S WORD→SLIDE GROUND TRUTH (founder 2026-08-11) ─────────
    #
    # Append-only by design (migrations/add_snippet_slide_corrections.sql):
    # the latest row per snippet wins and the earlier ones stay as the audit
    # trail. Never an upsert — a silently overwritten label is a corpus
    # nobody can compare across time.

    def record_snippet_slide_correction(self, *, session_id: str,
                                        snippet_id: str,
                                        slide_index: Optional[int],
                                        was_slide_index: Optional[int] = None,
                                        corrected_by: Optional[str] = None,
                                        ) -> bool:
        """One human judgment: the slide ON SCREEN while this snippet was
        spoken was `slide_index`. None = the coach withdrew a correction and
        the pipeline's own answer stands (stored, not deleted — "a human
        checked and the pipeline was right" is a label too).

        Best-effort: a labelling write must never break the coach's save."""
        if not session_id or not snippet_id:
            return False
        try:
            self.client.table("snippet_slide_corrections").insert({
                "session_id": str(session_id),
                "snippet_id": str(snippet_id),
                "slide_index": slide_index,
                "was_slide_index": was_slide_index,
                "corrected_by": str(corrected_by) if corrected_by else None,
            }).execute()
            return True
        except Exception as e:
            logger.warning("record_snippet_slide_correction failed sid=%s "
                           "snippet=%s: %s", session_id, snippet_id, e)
            return False

    def get_snippet_slide_corrections(self, session_id: str) -> dict:
        """{snippet_id: slide_index} for one session — the LATEST correction
        per snippet, reverts included as an explicit None.

        Returns {} pre-migration / on hiccup: the pipeline's own bucketing is
        the floor, so a missing table degrades to today's behaviour and never
        darkens a take. Ordered newest-first and taken first-seen, which is
        the append-only table's "latest wins" in one pass."""
        if not session_id:
            return {}
        try:
            res = (
                self.client.table("snippet_slide_corrections")
                .select("snippet_id,slide_index")
                .eq("session_id", str(session_id))
                .order("created_at", desc=True)
                .order("id", desc=True)
                .execute()
            )
            out: dict = {}
            for r in (res.data or []):
                sid = str((r or {}).get("snippet_id") or "")
                if sid and sid not in out:
                    out[sid] = (r or {}).get("slide_index")
            return out
        except Exception as e:
            _e = str(e).lower()
            if "snippet_slide_corrections" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return {}
            logger.warning("get_snippet_slide_corrections failed sid=%s: %s",
                           session_id, e)
            return {}

    def list_snippet_slide_corrections(self, session_id: str) -> list:
        """Every row for a session, newest first — the audit trail + the
        training corpus (each row is one (speech window, slide) pair with
        what the pipeline said beside it). [] pre-migration."""
        if not session_id:
            return []
        try:
            res = (
                self.client.table("snippet_slide_corrections")
                .select("*")
                .eq("session_id", str(session_id))
                .order("created_at", desc=True)
                .execute()
            )
            return list(res.data or [])
        except Exception as e:
            _e = str(e).lower()
            if "snippet_slide_corrections" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return []
            logger.warning("list_snippet_slide_corrections failed sid=%s: %s",
                           session_id, e)
            return []

    def count_intervention_decisions(self, arc_id: Optional[str],
                                     take_session_id: Optional[str]) -> int:
        """Spent slots for one take. 0 pre-migration / on hiccup — the
        serve degrades to the per-arbitration budget, never to silence.

        STYLE-LANE rows (lane == "lane:style") do NOT count: the post-lock
        style lane rides OUTSIDE the ≤3 budget (founder 2026-08-11, ruling
        4). Counted in Python rather than with .neq — PostgREST's neq
        drops NULL lanes too, and the star lane's rows carry lane NULL, so
        a server-side filter would silently free slots that were spent."""
        if not arc_id:
            return 0
        try:
            res = (
                self.client.table("intervention_decisions")
                .select("lane")
                .eq("arc_id", str(arc_id))
                .eq("take_session_id", str(take_session_id or ""))
                .execute()
            )
            return sum(1 for r in (res.data or [])
                       if (r or {}).get("lane") != "lane:style")
        except Exception as e:
            _e = str(e).lower()
            if "intervention_decisions" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return 0
            logger.warning("count_intervention_decisions failed arc=%s: %s",
                           arc_id, e)
            return 0

    def list_spent_intervention_decisions(self, arc_id: Optional[str],
                                          take_session_id: Optional[str]
                                          ) -> list:
        """The take's spent slots WITH THE WORDS THEY WERE SPENT ON —
        [{quote}], style-lane rows excluded by the same rule
        `count_intervention_decisions` applies.

        The budget is counted per SLIDE now (founder 2026-08-11), and this
        table has no slide column: the quote is what places a spent slot in
        the document, which needs no migration and no backfill. A row whose
        quote predates the texts migration cannot be placed and is simply not
        counted against any slide — history is never invented, and the error
        runs toward offering MORE feedback rather than silently withholding
        it. [] pre-migration / on hiccup."""
        if not arc_id:
            return []
        try:
            res = (
                self.client.table("intervention_decisions")
                .select("lane,quote")
                .eq("arc_id", str(arc_id))
                .eq("take_session_id", str(take_session_id or ""))
                .execute()
            )
            return [r for r in (res.data or [])
                    if isinstance(r, dict)
                    and r.get("lane") != "lane:style"
                    and (r.get("quote") or "").strip()]
        except Exception as e:
            _e = str(e).lower()
            if "intervention_decisions" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return []
            logger.warning(
                "list_spent_intervention_decisions failed arc=%s: %s",
                arc_id, e)
            return []

    def list_style_intervention_decisions(self, arc_id: Optional[str],
                                          take_session_id: Optional[str]
                                          ) -> list:
        """The take's spent STYLE slots — [{quote}], the exact rows the two
        methods above throw away.

        The style lane got its own ≤3-per-take / ≤2-per-slide budget
        (founder 2026-08-12) and needs its own ledger read, because
        `count_intervention_decisions` and `list_spent_intervention_decisions`
        both exclude `lane:style` on purpose: style rides OUTSIDE the ≤3
        (ruling 4). Two budgets, two reads, neither charging the other.

        Rows are kept even with a blank quote — the CALLER places what it can
        and counts everything, since a slot spent on words that have since
        been baked away is still spent against the take. Filtered in Python
        for the same reason its siblings are: PostgREST's `.eq` on `lane`
        would be fine here, but keeping all three on one code path means a
        future change to what "style" means cannot update two of them and
        miss the third. [] pre-migration / on hiccup — a ledger miss degrades
        to the per-serve cap, never to silence."""
        if not arc_id:
            return []
        try:
            res = (
                self.client.table("intervention_decisions")
                .select("lane,quote")
                .eq("arc_id", str(arc_id))
                .eq("take_session_id", str(take_session_id or ""))
                .execute()
            )
            return [r for r in (res.data or [])
                    if isinstance(r, dict) and r.get("lane") == "lane:style"]
        except Exception as e:
            _e = str(e).lower()
            if "intervention_decisions" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return []
            logger.warning(
                "list_style_intervention_decisions failed arc=%s: %s",
                arc_id, e)
            return []

    def list_ideal_decisions(self, arc_id: Optional[str]) -> list:
        """All ledger rows of an arc. [] pre-migration / on hiccup —
        callers degrade to no-memory behavior."""
        if not arc_id:
            return []
        try:
            res = (
                self.client.table("ideal_decision_ledger")
                .select("*")
                .eq("arc_id", str(arc_id))
                .execute()
            )
            return res.data or []
        except Exception as e:
            _e = str(e).lower()
            if "ideal_decision_ledger" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return []
            logger.warning("list_ideal_decisions failed arc=%s: %s",
                           arc_id, e)
            return []

    def upsert_ideal_text_version(self, arc_id: str, version: int,
                                  text: str, moments: Any) -> bool:
        """Append-only per-VERSION snapshot (founder 2026-07-20) — the text
        as this version assembled it + that step's sanitized reasoning.
        Idempotent per (arc, version). Best-effort."""
        if not arc_id or not isinstance(version, int) or version < 1 \
                or not (text or "").strip():
            return False
        try:
            self.client.table("ideal_text_versions").upsert({
                "arc_id": str(arc_id),
                "version": version,
                "text": text,
                "moments": moments,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="arc_id,version").execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "ideal_text_versions" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "upsert_ideal_text_version: table missing (run "
                    "migrations/add_ideal_text_versions.sql)")
                return False
            logger.warning("upsert_ideal_text_version failed arc=%s: %s",
                           arc_id, e)
            return False

    def get_ideal_text_version(self, arc_id: Optional[str],
                               version: Any) -> Optional[dict]:
        """One historical snapshot, or None (pre-migration / never
        snapshotted / hiccup — callers fall back to the live view)."""
        if not arc_id or not isinstance(version, int):
            return None
        try:
            res = (
                self.client.table("ideal_text_versions")
                .select("*")
                .eq("arc_id", str(arc_id))
                .eq("version", version)
                .limit(1)
                .execute()
            )
            return (res.data or [None])[0]
        except Exception as e:
            _e = str(e).lower()
            if "ideal_text_versions" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return None
            logger.warning("get_ideal_text_version failed arc=%s: %s",
                           arc_id, e)
            return None

    # ── master-document blocks + saves (founder 2026-07-22) ──────────
    # See services/master_document.py + add_ideal_text_blocks.sql.
    # All best-effort; list returns None on FAILURE ([] only on a real
    # empty read) — the read-fail ≠ empty lesson.

    def list_ideal_text_blocks(self,
                               arc_id: Optional[str]) -> Optional[list]:
        if not arc_id:
            return None
        try:
            res = (
                self.client.table("ideal_text_blocks")
                .select("*")
                .eq("arc_id", str(arc_id))
                .order("block_key", desc=False)
                .execute()
            )
            return res.data or []
        except Exception as e:
            _e = str(e).lower()
            if not ("ideal_text_blocks" in _e and (
                    "does not exist" in _e or "pgrst" in _e)):
                logger.warning("list_ideal_text_blocks failed arc=%s: %s",
                               arc_id, e)
            return None

    def get_ideal_text_block(self, arc_id: Optional[str],
                             block_key: Any) -> Optional[dict]:
        if not arc_id or not isinstance(block_key, int):
            return None
        try:
            res = (
                self.client.table("ideal_text_blocks")
                .select("*")
                .eq("arc_id", str(arc_id))
                .eq("block_key", block_key)
                .limit(1)
                .execute()
            )
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_ideal_text_block failed arc=%s: %s",
                           arc_id, e)
            return None

    def upsert_ideal_text_block(self, arc_id: str, block_key: int,
                                fields: dict) -> bool:
        """Partial upsert of one block row. Every column in the table has
        a default or is nullable except the key pair (enforced here), so
        partial writes are INSERT-safe — no #221-class NOT NULL trap."""
        if not arc_id or not isinstance(block_key, int) \
                or not isinstance(fields, dict):
            return False
        try:
            payload = dict(fields)
            payload["arc_id"] = str(arc_id)
            payload["block_key"] = block_key
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.client.table("ideal_text_blocks").upsert(
                payload, on_conflict="arc_id,block_key").execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "ideal_text_blocks" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "upsert_ideal_text_block: table missing (run "
                    "migrations/add_ideal_text_blocks.sql)")
                return False
            logger.warning("upsert_ideal_text_block failed arc=%s: %s",
                           arc_id, e)
            return False

    def delete_ideal_text_block(self, arc_id: str,
                                block_key: int) -> bool:
        """Remove one block row — a kept candidate is deleted outright
        (a parked settled-inactive row became an invisible ghost that
        swallowed later takes' material; review 2026-07-22)."""
        if not arc_id or not isinstance(block_key, int):
            return False
        try:
            (self.client.table("ideal_text_blocks")
             .delete()
             .eq("arc_id", str(arc_id))
             .eq("block_key", block_key)
             .execute())
            return True
        except Exception as e:
            logger.warning("delete_ideal_text_block failed arc=%s: %s",
                           arc_id, e)
            return False

    def get_snippets_by_ids(self, snippet_ids: Any) -> list:
        """Bulk snippet read — ONE query instead of a round trip per
        piece (review 2026-07-22 perf finding). Carries `metrics` (the
        block-ranking judge) and `say_it_stronger` (the T3 emphasis
        key-phrase signal, 2026-07-23). Best-effort: on the
        column-missing case (say_it_stronger not migrated) it retries
        without it; [] on any other failure."""
        ids = [str(x) for x in (snippet_ids or []) if x]
        if not ids:
            return []
        try:
            try:
                res = (
                    self.client.table(SNIPPETS_TABLE)
                    .select("id, metrics, say_it_stronger")
                    .in_("id", ids)
                    .execute()
                )
                return res.data or []
            except Exception as _e_full:
                if "say_it_stronger" not in str(_e_full).lower():
                    raise
            res = (
                self.client.table(SNIPPETS_TABLE)
                .select("id, metrics")
                .in_("id", ids)
                .execute()
            )
            return res.data or []
        except Exception as e:
            logger.warning("get_snippets_by_ids failed (%d ids): %s",
                           len(ids), e)
            return []

    def insert_ideal_text_save(self, arc_id: str, version: int) -> bool:
        """One save row per (arc, version) — idempotent (a double-tap on
        Save re-stamps the same version harmlessly)."""
        if not arc_id or not isinstance(version, int) or version < 1:
            return False
        try:
            self.client.table("ideal_text_saves").upsert({
                "arc_id": str(arc_id),
                "version": version,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="arc_id,version").execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "ideal_text_saves" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "insert_ideal_text_save: table missing (run "
                    "migrations/add_ideal_text_blocks.sql)")
                return False
            logger.warning("insert_ideal_text_save failed arc=%s: %s",
                           arc_id, e)
            return False

    def get_latest_ideal_text_save(self,
                                   arc_id: Optional[str]) -> Optional[dict]:
        if not arc_id:
            return None
        try:
            res = (
                self.client.table("ideal_text_saves")
                .select("*")
                .eq("arc_id", str(arc_id))
                .order("version", desc=True)
                .limit(1)
                .execute()
            )
            return (res.data or [None])[0]
        except Exception:
            return None

    # ── variant pool + compositions (founder 2026-08-03) ─────────────
    # See services/ideal_text_variants.py + add_ideal_text_variant_pool
    # .sql. Append-only lanes; all best-effort; list reads return None
    # on FAILURE ([] only on a real empty read).

    def insert_ideal_text_block_variant(self, arc_id: str, block_key: int,
                                        fields: dict) -> Optional[dict]:
        """One APPEND-ONLY variant row; returns the inserted row (the
        caller needs its id for composition pointers) or None. A take-
        sourced duplicate (same arc/block/take — the partial unique
        index) returns None quietly: the pool already has it."""
        if not arc_id or not isinstance(block_key, int) \
                or not isinstance(fields, dict):
            return None
        try:
            payload = dict(fields)
            payload["arc_id"] = str(arc_id)
            payload["block_key"] = block_key
            res = (self.client.table("ideal_text_block_variants")
                   .insert(payload).execute())
            return (res.data or [None])[0]
        except Exception as e:
            _e = str(e).lower()
            if "duplicate" in _e or "unique" in _e or "23505" in _e:
                return None
            if "ideal_text_block_variants" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "insert_ideal_text_block_variant: table missing (run "
                    "migrations/add_ideal_text_variant_pool.sql)")
                return None
            logger.warning("insert_ideal_text_block_variant failed "
                           "arc=%s: %s", arc_id, e)
            return None

    def list_ideal_text_block_variants(
            self, arc_id: Optional[str]) -> Optional[list]:
        if not arc_id:
            return None
        try:
            res = (
                self.client.table("ideal_text_block_variants")
                .select("*")
                .eq("arc_id", str(arc_id))
                .order("created_at", desc=False)
                .execute()
            )
            return res.data or []
        except Exception as e:
            _e = str(e).lower()
            if not ("ideal_text_block_variants" in _e and (
                    "does not exist" in _e or "pgrst" in _e)):
                logger.warning("list_ideal_text_block_variants failed "
                               "arc=%s: %s", arc_id, e)
            return None

    def get_ideal_text_block_variant(self, arc_id: Optional[str],
                                     variant_id: Any) -> Optional[dict]:
        """One variant by id, ARC-SCOPED — the select route must never
        resolve another arc's variant id."""
        if not arc_id or not variant_id:
            return None
        try:
            res = (
                self.client.table("ideal_text_block_variants")
                .select("*")
                .eq("arc_id", str(arc_id))
                .eq("id", str(variant_id))
                .limit(1)
                .execute()
            )
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_ideal_text_block_variant failed arc=%s: %s",
                           arc_id, e)
            return None

    def insert_ideal_text_composition(self, arc_id: str, revision: int,
                                      selections: Any, reason: Any,
                                      created_by: Any) -> bool:
        """One APPEND-ONLY composition revision. A (arc, revision)
        conflict returns False — the caller retries with the next
        number; existing history is never overwritten."""
        if not arc_id or not isinstance(revision, int) or revision < 1:
            return False
        try:
            (self.client.table("ideal_text_compositions").insert({
                "arc_id": str(arc_id),
                "revision": revision,
                "selections": selections or [],
                "reason": reason,
                "created_by": (str(created_by) if created_by else None),
            }).execute())
            return True
        except Exception as e:
            _e = str(e).lower()
            if "ideal_text_compositions" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "insert_ideal_text_composition: table missing (run "
                    "migrations/add_ideal_text_variant_pool.sql)")
                return False
            if not ("duplicate" in _e or "unique" in _e or "23505" in _e):
                logger.warning("insert_ideal_text_composition failed "
                               "arc=%s: %s", arc_id, e)
            return False

    def get_ideal_text_composition(self, arc_id: Optional[str],
                                   revision: Any) -> Optional[dict]:
        if not arc_id or not isinstance(revision, int):
            return None
        try:
            res = (
                self.client.table("ideal_text_compositions")
                .select("*")
                .eq("arc_id", str(arc_id))
                .eq("revision", revision)
                .limit(1)
                .execute()
            )
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_ideal_text_composition failed arc=%s: %s",
                           arc_id, e)
            return None

    def list_ideal_text_compositions(self, arc_id: Optional[str],
                                     limit: int = 50) -> Optional[list]:
        """Newest first, bounded — the revisions timeline read."""
        if not arc_id:
            return None
        try:
            res = (
                self.client.table("ideal_text_compositions")
                .select("*")
                .eq("arc_id", str(arc_id))
                .order("revision", desc=True)
                .limit(max(1, int(limit)))
                .execute()
            )
            return res.data or []
        except Exception as e:
            _e = str(e).lower()
            if not ("ideal_text_compositions" in _e and (
                    "does not exist" in _e or "pgrst" in _e)):
                logger.warning("list_ideal_text_compositions failed "
                               "arc=%s: %s", arc_id, e)
            return None

    def get_ideal_text_composition_head(
            self, arc_id: Optional[str]) -> Optional[dict]:
        if not arc_id:
            return None
        try:
            res = (
                self.client.table("ideal_text_composition_head")
                .select("*")
                .eq("arc_id", str(arc_id))
                .limit(1)
                .execute()
            )
            return (res.data or [None])[0]
        except Exception:
            return None

    def set_ideal_text_composition_head(self, arc_id: str,
                                        revision: int) -> bool:
        """Repoint the one live pointer — undo/restore IS this write."""
        if not arc_id or not isinstance(revision, int) or revision < 1:
            return False
        try:
            self.client.table("ideal_text_composition_head").upsert({
                "arc_id": str(arc_id),
                "head_revision": revision,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="arc_id").execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "ideal_text_composition_head" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "set_ideal_text_composition_head: table missing (run "
                    "migrations/add_ideal_text_variant_pool.sql)")
                return False
            logger.warning("set_ideal_text_composition_head failed "
                           "arc=%s: %s", arc_id, e)
            return False

    def set_session_priming(
        self, session_id: str,
        condition: Optional[str], phrase: Optional[str],
    ) -> bool:
        """Persist the pre-take priming manipulation (founder 2026-07-13) on the
        take's session row — the framing the student saw before this live take.
        PRIVATE research-correlation signal (see services/priming.py); the route
        pre-validates the condition enum. Best-effort: missing column (migration
        pending) → False, non-fatal (the take is still recorded). A separate
        write from the feeling capture, so a pre-migration failure here can
        never regress feeling."""
        if not session_id or not (condition or phrase):
            return False
        try:
            self.client.table("v2_sessions").update({
                "priming_condition": condition,
                "priming_phrase": phrase,
            }).eq("id", session_id).execute()
            return True
        except Exception as e:
            if "priming_condition" in str(e).lower() or \
                    "priming_phrase" in str(e).lower():
                logger.warning(
                    "set_session_priming: column missing (run "
                    "migrations/add_session_priming.sql) sid=%s", session_id,
                )
                return False
            logger.warning("set_session_priming failed sid=%s: %s",
                           session_id, e)
            return False

    def deduct_credits_strict(
        self, user_id: Optional[str], amount: int,
    ) -> Optional[int]:
        """HARD atomic deduct for the $25/25-credit arc unlock (2026-07-06) —
        unlike v2_deduct_session_credits (soft, floors at 0, read-then-write),
        this NEVER oversells: it fails (returns None) when the balance is
        insufficient, using a compare-and-swap so a concurrent write can never
        race it into a negative or double-spent balance.

        Returns the NEW balance on success, or None on insufficient funds / a
        db hiccup / exhausted CAS retries (the caller must treat None as
        "did not charge" and roll back whatever it reserved)."""
        if not user_id or not isinstance(amount, int) or amount <= 0:
            return None
        from datetime import datetime, timezone
        for _ in range(3):
            details = self.v2_get_student_details(str(user_id)) or {}
            current = details.get("credits")
            if current is None:
                # Unseeded user. Taking _free_credit_grant() as the balance here
                # is NOT enough: the CAS below is an UPDATE ... eq(credits, N),
                # and an UPDATE never creates a row, so it would match nothing
                # and the caller would report INSUFFICIENT_CREDITS to a user who
                # actually holds the grant. Write the row first (idempotent,
                # guarded by credits_initialized_at — a user who spent down to 0
                # is never re-granted), then CAS against the seeded value.
                current = self.v2_ensure_credits_initialized(str(user_id))
            current = int(current)
            if current < amount:
                return None  # genuinely insufficient — no point retrying
            new_val = current - amount
            try:
                res = (
                    self.client.table("v2_student_details")
                    .update({
                        "credits": new_val,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    })
                    .eq("user_id", str(user_id))
                    .eq("credits", current)  # CAS guard on the value we read
                    .execute()
                )
            except Exception as e:
                logger.warning("deduct_credits_strict failed user=%s: %s",
                               user_id, e)
                return None
            if res.data:
                return new_val
            # Someone else changed the balance between our read and write —
            # benign race, not insufficiency. Retry with a fresh read.
        logger.warning(
            "deduct_credits_strict: CAS retries exhausted user=%s amount=%s",
            user_id, amount,
        )
        return None

    def get_coach_best_presentation_edits(self, arc_id: Optional[str]) -> dict:
        """Per-slide COACH corrections to an arc's ideal text (founder
        2026-07-06 — the coach-owned counterpart to the user's pencil-edit).
        Returns {slide_index: text}. {} on missing table / none / error."""
        if not arc_id:
            return {}
        try:
            res = (
                self.client.table("coach_best_presentation_edits")
                .select("slide_index, text")
                .eq("arc_id", arc_id)
                .execute()
            )
            return {
                r.get("slide_index"): r.get("text")
                for r in (res.data or [])
                if isinstance(r.get("slide_index"), int)
            }
        except Exception as e:
            err_low = str(e).lower()
            if "coach_best_presentation_edits" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return {}
            logger.warning("get_coach_best_presentation_edits failed arc=%s: %s",
                           arc_id, e)
            return {}

    def get_coach_best_presentation_key_phrases(self, arc_id) -> dict:
        """{slide_index: [phrases]} — the coach-corrected key phrases (Engine
        2, 2026-07-11). {} on missing table/column / none / error (the auto-
        derived set serves)."""
        if not arc_id:
            return {}
        try:
            res = (
                self.client.table("coach_best_presentation_edits")
                .select("slide_index, key_phrases")
                .eq("arc_id", arc_id)
                .execute()
            )
            out = {}
            for r in (res.data or []):
                kp = r.get("key_phrases")
                if isinstance(r.get("slide_index"), int) and isinstance(kp, list):
                    phrases = [str(x).strip() for x in kp
                               if isinstance(x, str) and str(x).strip()]
                    if phrases:
                        out[r["slide_index"]] = phrases
            return out
        except Exception:
            return {}

    # (upsert_coach_best_presentation_edit DELETED 2026-07-15 — the per-
    #  slide coach editor was replaced by the ONE-block ideal text
    #  (coach_arc_ideal_text); the readers below stay: compose still
    #  folds edits saved before the switch.)

    def count_arc_sessions(
        self, arc_id: Optional[str], exclude_session_id: Optional[str] = None,
    ) -> Optional[int]:
        """STRICT arc-session count for take numbering: returns None on ANY
        error (so the caller can fail CLOSED and keep the FE-sent index instead
        of mislabeling a real take-2/3 as take-1), and can EXCLUDE the current
        session (an upload retry already arc-linked must not double-count
        itself).

        Counts SPOKEN takes only (founder 2026-07-14): a read is a paired
        variant of its take (paired_session_id set), not a take of its own —
        so `paired_session_id IS NULL` isolates the real takes. Falls back to
        the unfiltered count when the column is not migrated."""
        if not arc_id:
            return None

        def _q(with_paired_filter):
            q = (
                self.client.table("v2_sessions")
                .select("id", count="exact")
                .eq("arc_id", arc_id)
            )
            if with_paired_filter:
                q = q.is_("paired_session_id", "null")
            if exclude_session_id:
                q = q.neq("id", str(exclude_session_id))
            return q.limit(1).execute()

        try:
            res = _q(True)
            cnt = getattr(res, "count", None)
            return int(cnt) if cnt is not None else 0
        except Exception as e:
            if "paired_session_id" in str(e).lower():
                try:  # pre-migration → count all arc sessions
                    res = _q(False)
                    cnt = getattr(res, "count", None)
                    return int(cnt) if cnt is not None else 0
                except Exception:
                    return None
            logger.warning("count_arc_sessions failed arc=%s: %s", arc_id, e)
            return None

    def get_arc_take_count(self, arc_id: Optional[str]) -> int:
        """How many takes are in an arc (Prompt A §3 take_count). 0 on missing
        column / no arc."""
        if not arc_id:
            return 0
        try:
            res = (
                self.client.table("v2_sessions")
                .select("id", count="exact")
                .eq("arc_id", arc_id)
                .limit(1)
                .execute()
            )
            return int(getattr(res, "count", None) or 0)
        except Exception as e:
            if "arc_id" in str(e).lower():
                return 0
            logger.warning("get_arc_take_count failed arc=%s: %s", arc_id, e)
            return 0

    def insert_recording_feeling(
        self, *, session_id: str, feeling: str,
        user_id: Optional[str] = None, recording_id: Optional[str] = None,
        arc_id: Optional[str] = None, take_index: Optional[int] = None,
    ) -> bool:
        """Persist a pre-recording feeling (U10 — split-sink, audit-stage
        correlation input). Best-effort + non-fatal: a missing table or a bad
        value never breaks the recording. The route pre-validates the enum."""
        if not session_id or not feeling:
            return False
        row = {"session_id": session_id, "feeling": feeling}
        if user_id:
            row["user_id"] = user_id
        if recording_id:
            row["recording_id"] = recording_id
        if arc_id:
            row["arc_id"] = arc_id
        if take_index is not None:
            row["take_index"] = take_index
        try:
            self.client.table("recording_feelings").insert(row).execute()
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "recording_feelings" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                logger.warning(
                    "insert_recording_feeling: table missing (run "
                    "migrations/add_recording_feelings.sql) session=%s",
                    session_id,
                )
                return False
            logger.warning(
                "insert_recording_feeling failed session=%s: %s", session_id, e,
            )
            return False

    def get_feelings_by_session(self, session_id: str) -> list[dict]:
        """The pre-recording feeling(s) the student named for a session (U10 —
        coach review read). Usually one row; [] on missing table / none /
        error. Coach-only — never serialised to the user."""
        if not session_id:
            return []
        try:
            res = (
                self.client.table("recording_feelings")
                .select("feeling, take_index, recording_id, created_at")
                .eq("session_id", session_id)
                .order("created_at", desc=False)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "recording_feelings" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return []
            logger.warning("get_feelings_by_session failed sid=%s: %s",
                           session_id, e)
            return []

    def get_best_presentation_edits(self, arc_id: Optional[str]) -> dict:
        """Per-slide text overrides for an arc's best-presentation (Prompt D —
        the user's pencil-edits). Returns {slide_index: text}. {} on missing
        table / none / error."""
        if not arc_id:
            return {}
        try:
            res = (
                self.client.table("best_presentation_edits")
                .select("slide_index, text")
                .eq("arc_id", arc_id)
                .execute()
            )
            return {
                r.get("slide_index"): r.get("text")
                for r in (res.data or [])
                if isinstance(r.get("slide_index"), int)
            }
        except Exception as e:
            err_low = str(e).lower()
            if "best_presentation_edits" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return {}
            logger.warning("get_best_presentation_edits failed arc=%s: %s",
                           arc_id, e)
            return {}

    def upsert_best_presentation_edit(
        self, arc_id: str, slide_index: int, text: str,
        user_id: Optional[str] = None,
    ) -> bool:
        """Save the user's edited text for one best-presentation slide (Prompt
        D). Upserts on (arc_id, slide_index). Best-effort; missing table →
        False, non-fatal."""
        if not arc_id or not isinstance(slide_index, int) or not text:
            return False
        from datetime import datetime, timezone
        row = {
            "arc_id": arc_id, "slide_index": slide_index, "text": text,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if user_id:
            row["user_id"] = user_id
        try:
            self.client.table("best_presentation_edits").upsert(
                row, on_conflict="arc_id,slide_index",
            ).execute()
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "best_presentation_edits" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                logger.warning(
                    "upsert_best_presentation_edit: table missing (run "
                    "migrations/add_best_presentation_edits.sql) arc=%s", arc_id,
                )
                return False
            logger.error("upsert_best_presentation_edit failed arc=%s: %s",
                         arc_id, e)
            return False

    def get_user_transcript_edits(self, session_id: Optional[str]) -> list:
        """The user's own transcript corrections for a session (founder
        2026-07-07) — display layer only, the coach keeps the original.
        Returns [{snippet_id, chunk_index, text}]; [] on missing table /
        none / error."""
        if not session_id:
            return []
        try:
            res = (
                self.client.table("user_transcript_edits")
                .select("snippet_id, chunk_index, text")
                .eq("session_id", session_id)
                .execute()
            )
            return [r for r in (res.data or []) if isinstance(r, dict)]
        except Exception as e:
            err_low = str(e).lower()
            if "user_transcript_edits" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return []
            logger.warning("get_user_transcript_edits failed sid=%s: %s",
                           session_id, e)
            return []

    def upsert_user_transcript_edit(
        self,
        session_id: str,
        *,
        snippet_id: Optional[str] = None,
        chunk_index: Optional[int] = None,
        text: str,
    ) -> bool:
        """Save the user's corrected transcript text for ONE target — a
        snippet (snippet_id) or a deckless full-transcript chunk
        (chunk_index). Exactly one target must be set.

        Manual select→update-or-insert rather than a single on_conflict
        upsert: the table serves TWO row kinds against two different
        unique pairs — (session_id, snippet_id) and (session_id,
        chunk_index) — and PostgREST's upsert takes one on_conflict target,
        so one call shape can't serve both kinds. The unique constraints DO
        enforce per-kind dedupe (the target column is non-NULL for its own
        kind), which means a concurrent first-save race surfaces as a
        unique-violation on our insert — caught below and retried as the
        update it really is. Best-effort; missing table → False."""
        has_snip = bool(snippet_id)
        has_chunk = isinstance(chunk_index, int) and chunk_index >= 0
        if not session_id or not text or has_snip == has_chunk:
            return False
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        def _select_existing():
            q = (
                self.client.table("user_transcript_edits")
                .select("id")
                .eq("session_id", session_id)
            )
            q = q.eq("snippet_id", snippet_id) if has_snip \
                else q.eq("chunk_index", chunk_index)
            return (q.limit(1).execute()).data or []

        def _update(row_id):
            (
                self.client.table("user_transcript_edits")
                .update({"text": text, "updated_at": now})
                .eq("id", row_id)
                .execute()
            )

        try:
            rows = _select_existing()
            if rows:
                _update(rows[0]["id"])
                return True
            row = {"session_id": session_id, "text": text, "updated_at": now}
            if has_snip:
                row["snippet_id"] = snippet_id
            else:
                row["chunk_index"] = chunk_index
            try:
                self.client.table("user_transcript_edits").insert(row).execute()
                return True
            except Exception as ins_err:
                ins_low = str(ins_err).lower()
                if "23505" in ins_low or "duplicate key" in ins_low \
                        or "unique" in ins_low:
                    # Lost a concurrent first-save race — the row exists now;
                    # this request becomes the update it really is.
                    rows = _select_existing()
                    if rows:
                        _update(rows[0]["id"])
                        return True
                raise
        except Exception as e:
            err_low = str(e).lower()
            if "user_transcript_edits" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                logger.warning(
                    "upsert_user_transcript_edit: table missing (run "
                    "migrations/add_user_transcript_edits.sql) sid=%s",
                    session_id,
                )
                return False
            logger.error("upsert_user_transcript_edit failed sid=%s: %s",
                         session_id, e)
            return False

    def get_best_presentation_cache(self, arc_id: Optional[str]) -> Optional[dict]:
        """The cached composed best-presentation for an arc (Part B — skip the
        ~2-4s LLM compose when nothing changed). Returns {signature, payload} or
        None on miss / missing table / error (caller recomputes)."""
        if not arc_id:
            return None
        try:
            res = (
                self.client.table("best_presentation_cache")
                .select("signature, payload")
                .eq("arc_id", arc_id)
                .limit(1)
                .execute()
            )
            return (res.data or [None])[0]
        except Exception as e:
            err_low = str(e).lower()
            if "best_presentation_cache" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return None
            logger.warning("get_best_presentation_cache failed arc=%s: %s",
                           arc_id, e)
            return None

    def upsert_best_presentation_cache(
        self, arc_id: str, signature: str, payload: dict,
    ) -> bool:
        """Store the composed best-presentation keyed by arc + content signature
        (Part B). Upserts on arc_id. Best-effort; missing table → False (the
        feature simply doesn't cache, never errors the GET)."""
        if not arc_id or not signature:
            return False
        from datetime import datetime, timezone
        row = {
            "arc_id": arc_id, "signature": signature, "payload": payload,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.client.table("best_presentation_cache").upsert(
                row, on_conflict="arc_id",
            ).execute()
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "best_presentation_cache" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                logger.warning(
                    "upsert_best_presentation_cache: table missing (run "
                    "migrations/add_best_presentation_cache.sql) arc=%s", arc_id,
                )
                return False
            logger.error("upsert_best_presentation_cache failed arc=%s: %s",
                         arc_id, e)
            return False

    def get_feelings_by_sessions(self, session_ids: list) -> list[dict]:
        """Pre-recording feelings for a BATCH of sessions (U10 — the coach
        roster rollup). One query, mapped by the caller. [] on missing table /
        empty input / error."""
        if not session_ids:
            return []
        try:
            res = (
                self.client.table("recording_feelings")
                .select("session_id, feeling, take_index, created_at")
                .in_("session_id", list(session_ids))
                .order("created_at", desc=False)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "recording_feelings" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return []
            logger.warning("get_feelings_by_sessions failed: %s", e)
            return []

    def get_read_sessions_for(self, spoken_session_id) -> list[dict]:
        """The paired mid-take RE-READ sessions of a spoken take
        (recording_kind='read', paired_session_id=<take>), oldest first —
        the fold order the coach packet appends them in (founder 2026-07-16:
        "re-reads are part of the take, never separate items"). Uses
        idx_v2_sessions_paired. Best-effort: [] pre-migration / on hiccup
        (the packet degrades to the parent take alone)."""
        if not spoken_session_id:
            return []
        try:
            res = (
                self.client.table("v2_sessions")
                .select("id, user_id, arc_id, take_index, status, "
                        "created_at, results_published_at, "
                        "recording_kind, paired_session_id, intake_context")
                .eq("paired_session_id", str(spoken_session_id))
                .order("created_at", desc=False)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "paired_session_id" in err_low:
                return []  # pre-migration — no read rows can exist either
            logger.warning(
                "get_read_sessions_for failed sid=%s err=%s",
                spoken_session_id, e,
            )
            return []

    def get_arc_sessions(self, arc_id: Optional[str]) -> list[dict]:
        """The takes of an explore arc, ORDERED by take_index (Prompt A §3/§5).
        Powers cross-take selection + the delivery layer (spoken/read split,
        per-take Save state). Best-effort: [] on missing column / no arc /
        DB hiccup; the delivery-layer columns degrade to absent pre-migration
        (older rows read as spoken/unsaved)."""
        if not arc_id:
            return []
        _full_cols = ("id, user_id, arc_id, take_index, status, "
                      "created_at, intake_context, results_published_at, "
                      "recording_kind, paired_session_id, "
                      "coach_feedback_saved_at, analysis_state")
        try:
            try:
                res = (
                    self.client.table("v2_sessions")
                    .select(_full_cols)
                    .eq("arc_id", arc_id)
                    .order("take_index", desc=False)
                    .execute()
                )
                return res.data or []
            except Exception as _e_full:
                _low = str(_e_full).lower()
                # Delivery-layer columns not migrated yet → the legacy list.
                # analysis_state joined the select 2026-07-22 (the re-read
                # completion gate); it degrades the same way.
                if not any(c in _low for c in (
                        "recording_kind", "paired_session_id",
                        "coach_feedback_saved_at", "analysis_state")):
                    raise
            res = (
                self.client.table("v2_sessions")
                .select("id, user_id, arc_id, take_index, status, "
                        "created_at, intake_context, results_published_at")
                .eq("arc_id", arc_id)
                .order("take_index", desc=False)
                .execute()
            )
            return res.data or []
        except Exception as e:
            _e = str(e).lower()
            # results_published_at is a base column, but be defensive: if the
            # explicit select trips any missing column, retry without the
            # optional one (keeps coach_reviewed/cache-signature best-effort).
            if "results_published_at" in _e:
                try:
                    res = (
                        self.client.table("v2_sessions")
                        .select("id, user_id, arc_id, take_index, status, "
                                "created_at, intake_context")
                        .eq("arc_id", arc_id)
                        .order("take_index", desc=False)
                        .execute()
                    )
                    return res.data or []
                except Exception:
                    return []
            if "arc_id" in _e or "take_index" in _e:
                logger.warning(
                    "get_arc_sessions: column missing (run "
                    "migrations/add_explore_arc.sql) arc=%s", arc_id,
                )
                return []
            logger.warning("get_arc_sessions failed arc=%s: %s", arc_id, e)
            return []

    def list_user_arc_sessions(self, user_id: Optional[str]) -> list[dict]:
        """Every arc-linked session the user owns — the /user/trainings source
        (the route groups per arc). Arc-keyed on purpose, so DECKLESS trainings
        appear too (the deck-hash grouping in /user/strengths drops them into
        the flat general bucket). Best-effort: [] on missing column / hiccup."""
        if not user_id:
            return []
        _legacy_cols = ("id, arc_id, take_index, status, created_at, "
                        "intake_context, results_published_at")
        _full_cols = _legacy_cols + ", recording_kind, paired_session_id"
        try:
            try:
                res = (
                    self.client.table("v2_sessions")
                    .select(_full_cols)
                    .eq("user_id", str(user_id))
                    .not_.is_("arc_id", "null")
                    .order("created_at", desc=False)
                    .execute()
                )
                return res.data or []
            except Exception as _ef:
                _lowf = str(_ef).lower()
                if not ("recording_kind" in _lowf
                        or "paired_session_id" in _lowf):
                    raise
            res = (
                self.client.table("v2_sessions")
                .select(_legacy_cols)
                .eq("user_id", str(user_id))
                .not_.is_("arc_id", "null")
                .order("created_at", desc=False)
                .execute()
            )
            return res.data or []
        except Exception as e:
            _e = str(e).lower()
            if "arc_id" in _e or "take_index" in _e:
                logger.warning(
                    "list_user_arc_sessions: column missing (run "
                    "migrations/add_explore_arc.sql) user=%s", user_id,
                )
                return []
            logger.warning("list_user_arc_sessions failed user=%s: %s",
                           user_id, e)
            return []

    # ── willab — arc batch delivery (founder 2026-07-13) ────────────────
    #
    # arc_batch_deliveries: one row per arc, stamped by the coach's explicit
    # "Publish arc" action — the WHOLE training (all takes' labelled snippets
    # + the finalized ideal text) delivered to the student as ONE batch.
    # Coexists with the per-take publish. See
    # migrations/add_arc_batch_deliveries.sql.

    def mark_arc_batch_delivered(
        self, arc_id: str, user_id: Optional[str], coach_id: Optional[str],
    ) -> bool:
        """Upsert the one-row-per-arc batch-delivery marker. Idempotent — a
        re-publish refreshes published_at (the batch simply went out again)."""
        if not arc_id:
            return False
        try:
            self.client.table("arc_batch_deliveries").upsert({
                "arc_id": str(arc_id),
                "user_id": str(user_id) if user_id else None,
                "coach_id": str(coach_id) if coach_id else None,
                "published_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="arc_id").execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "arc_batch_deliveries" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "mark_arc_batch_delivered: table missing (run "
                    "migrations/add_arc_batch_deliveries.sql) arc=%s", arc_id,
                )
                return False
            logger.warning("mark_arc_batch_delivered failed arc=%s: %s",
                           arc_id, e)
            return False

    def get_arc_batch_delivery(self, arc_id: Optional[str]) -> Optional[dict]:
        """The batch-delivery row for an arc, or None. None on missing table /
        error — the batch defaults to NOT delivered (the student view shows
        'waiting for your coach', never a phantom delivery)."""
        if not arc_id:
            return None
        try:
            res = (
                self.client.table("arc_batch_deliveries")
                .select("*")
                .eq("arc_id", str(arc_id))
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            _e = str(e).lower()
            if "arc_batch_deliveries" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return None  # pre-migration → never delivered
            logger.warning("get_arc_batch_delivery failed arc=%s: %s",
                           arc_id, e)
            return None

    def list_arc_batch_deliveries(self, arc_ids: list) -> dict:
        """{arc_id: row} for the given arcs — ONE read for the trainings
        list (no per-arc N+1). {} on missing table / error (not delivered)."""
        ids = [str(a) for a in (arc_ids or []) if a]
        if not ids:
            return {}
        try:
            res = (
                self.client.table("arc_batch_deliveries")
                .select("*")
                .in_("arc_id", ids)
                .execute()
            )
            return {str(r.get("arc_id")): r for r in (res.data or [])
                    if r.get("arc_id")}
        except Exception as e:
            _e = str(e).lower()
            if "arc_batch_deliveries" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return {}
            logger.warning("list_arc_batch_deliveries failed: %s", e)
            return {}

    # ── willab — Paid Audits / arc entitlement (BE chunk A1/A4/A5) ──────
    #
    # arc_purchases: one row per PAID/passed arc ("audit"). The row IS the
    # entitlement — take-1 is always free; a purchase unlocks take-2 feedback,
    # take-3, and the ideal-text report. Distinct from credits + user_audits.
    # See migrations/add_arc_purchases.sql.

    def get_arc_purchase(self, arc_id: Optional[str]) -> Optional[dict]:
        """The purchase row for an arc, or None. None on missing table /
        no purchase / error — never raises (entitlement defaults to NOT
        entitled, so a hiccup keeps the paywall up, never opens it)."""
        if not arc_id:
            return None
        try:
            res = (
                self.client.table("arc_purchases")
                .select("*")
                .eq("arc_id", str(arc_id))
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            err_low = str(e).lower()
            if "arc_purchases" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "get_arc_purchase: table missing (run "
                    "migrations/add_arc_purchases.sql) arc=%s", arc_id,
                )
                return None
            logger.warning("get_arc_purchase failed arc=%s: %s", arc_id, e)
            return None

    def create_arc_purchase(
        self, arc_id: str, user_id: str, *,
        kind: str = "paid", source: str = "stripe",
        currency: Optional[str] = None, amount_minor: Optional[int] = None,
        stripe_session_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Record a paid/passed arc. IDEMPOTENT: unique(arc_id) means a second
        purchase for the same arc (or a replayed stripe webhook on the same
        stripe_session_id) no-ops — on conflict we return the EXISTING row, so
        the caller treats a duplicate exactly like a fresh grant. Returns the
        row or None on real failure."""
        if not arc_id or not user_id:
            return None
        row = {
            "arc_id": str(arc_id), "user_id": str(user_id),
            "kind": kind, "source": source,
        }
        if currency:
            row["currency"] = str(currency).lower()
        if amount_minor is not None:
            try:
                row["amount_minor"] = int(amount_minor)
            except (TypeError, ValueError):
                pass
        if stripe_session_id:
            row["stripe_session_id"] = str(stripe_session_id)
        try:
            res = self.client.table("arc_purchases").insert(row).execute()
            created = (res.data or [None])[0]
            if created:
                return created
            return self.get_arc_purchase(arc_id)
        except Exception as e:
            err_low = str(e).lower()
            # Unique conflict (arc already purchased / replayed webhook) →
            # return the existing row; that's the idempotent success path.
            if (
                "duplicate" in err_low or "unique" in err_low
                or "23505" in err_low or "conflict" in err_low
            ):
                existing = self.get_arc_purchase(arc_id)
                if existing:
                    return existing
                # conflict was on stripe_session_id for a different arc — fall
                # through to a best-effort lookup by that session id.
                if stripe_session_id:
                    return self.get_arc_purchase_by_stripe_session(
                        stripe_session_id,
                    )
                return None
            if "arc_purchases" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "create_arc_purchase: table missing (run "
                    "migrations/add_arc_purchases.sql) arc=%s", arc_id,
                )
                return None
            logger.warning("create_arc_purchase failed arc=%s: %s", arc_id, e)
            return None

    def create_arc_purchase_exclusive(
        self, arc_id: str, user_id: str, *,
        kind: str = "paid", source: str = "credits",
        credits_charged: Optional[int] = None,
    ) -> Optional[dict]:
        """Purpose-built for the credits unlock (2026-07-06): unlike
        ``create_arc_purchase`` (which returns the EXISTING row on a unique
        conflict — the right idempotent behavior for a replayed Stripe
        webhook), this returns None on ANY conflict, so the caller can tell
        "I just created the entitlement" from "someone else already has it" —
        the caller MUST NOT deduct credits unless this returns a fresh row
        (else a race could charge twice for one arc)."""
        if not arc_id or not user_id:
            return None
        row = {
            "arc_id": str(arc_id), "user_id": str(user_id),
            "kind": kind, "source": source,
        }
        if credits_charged is not None:
            try:
                row["credits_charged"] = int(credits_charged)
            except (TypeError, ValueError):
                pass
        try:
            res = self.client.table("arc_purchases").insert(row).execute()
            return (res.data or [None])[0]
        except Exception as e:
            err_low = str(e).lower()
            if "arc_purchases" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "create_arc_purchase_exclusive: table missing (run "
                    "migrations/add_arc_purchases.sql) arc=%s", arc_id,
                )
            # Any conflict (unique(arc_id)) or other error → None, deliberately
            # (never the existing row) so the caller never double-charges.
            return None

    def get_arc_purchase_by_stripe_session(
        self, stripe_session_id: Optional[str],
    ) -> Optional[dict]:
        """Purchase row keyed by Stripe Checkout Session id (webhook
        idempotency lookup). None on missing/none/error."""
        if not stripe_session_id:
            return None
        try:
            res = (
                self.client.table("arc_purchases")
                .select("*")
                .eq("stripe_session_id", str(stripe_session_id))
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            logger.warning(
                "get_arc_purchase_by_stripe_session failed sid=%s: %s",
                stripe_session_id, e,
            )
            return None

    def mark_arc_delivered(self, arc_id: Optional[str]) -> bool:
        """Stamp delivered_at when the coach has delivered the arc's audit.
        Idempotent (sets only when NULL). Best-effort → False on any hiccup."""
        if not arc_id:
            return False
        now = datetime.now(timezone.utc).isoformat()
        try:
            res = (
                self.client.table("arc_purchases")
                .update({"delivered_at": now})
                .eq("arc_id", str(arc_id))
                .is_("delivered_at", "null")
                .execute()
            )
            return bool(res.data)
        except Exception as e:
            logger.warning("mark_arc_delivered failed arc=%s: %s", arc_id, e)
            return False

    # arc_invite_codes — founding free-pass codes (A4).

    def get_arc_invite_code(self, code: Optional[str]) -> Optional[dict]:
        """An invite code row, or None. None on missing table / unknown
        code / error."""
        if not code:
            return None
        try:
            res = (
                self.client.table("arc_invite_codes")
                .select("*")
                .eq("code", str(code).strip())
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            err_low = str(e).lower()
            if "arc_invite_codes" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "get_arc_invite_code: table missing (run "
                    "migrations/add_arc_invite_codes.sql) code=%s", code,
                )
                return None
            logger.warning("get_arc_invite_code failed code=%s: %s", code, e)
            return None

    def consume_arc_invite_code(self, code: Optional[str]) -> bool:
        """Atomically claim ONE use of an active code with uses < max_uses.
        Guards on uses (conditional update) so two concurrent redeems can't
        over-spend a code. Returns True iff a use was claimed. Caller mints the
        purchase only on True."""
        if not code:
            return False
        row = self.get_arc_invite_code(code)
        if not row or not row.get("active"):
            return False
        try:
            uses = int(row.get("uses") or 0)
            max_uses = int(row.get("max_uses") or 0)
        except (TypeError, ValueError):
            return False
        if uses >= max_uses:
            return False
        try:
            # Conditional update: only bump when uses still equals what we read
            # (optimistic lock). A racing redeem changed uses → 0 rows → retry
            # is the caller's choice; here we just report no-claim.
            res = (
                self.client.table("arc_invite_codes")
                .update({"uses": uses + 1})
                .eq("code", str(code).strip())
                .eq("uses", uses)
                .eq("active", True)
                .execute()
            )
            return bool(res.data)
        except Exception as e:
            logger.warning("consume_arc_invite_code failed code=%s: %s", code, e)
            return False

    def create_arc_invite_code(
        self, code: str, *, max_uses: int = 1, note: Optional[str] = None,
    ) -> Optional[dict]:
        """Mint an invite code (admin/seed, A4). Idempotent: a re-run of the
        same code returns the existing row. None on real failure."""
        if not code:
            return None
        row = {"code": str(code).strip(), "max_uses": int(max_uses)}
        if note:
            row["note"] = str(note)
        try:
            res = self.client.table("arc_invite_codes").insert(row).execute()
            created = (res.data or [None])[0]
            return created or self.get_arc_invite_code(code)
        except Exception as e:
            err_low = str(e).lower()
            if (
                "duplicate" in err_low or "unique" in err_low
                or "23505" in err_low or "conflict" in err_low
            ):
                return self.get_arc_invite_code(code)
            logger.warning("create_arc_invite_code failed code=%s: %s", code, e)
            return None

    def set_session_presentation_duration(
        self, session_id: Optional[str], seconds: Optional[int],
    ) -> bool:
        """Persist the gate's measured duration onto the session (A5 — the
        length→audits read). Best-effort: no-op (False) on missing column /
        bad value / error; the recording row keeps the authoritative copy."""
        if not session_id or seconds is None:
            return False
        try:
            secs = int(round(float(seconds)))
        except (TypeError, ValueError):
            return False
        try:
            self.client.table("v2_sessions").update(
                {"presentation_duration_seconds": secs}
            ).eq("id", session_id).execute()
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "presentation_duration_seconds" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                logger.warning(
                    "set_session_presentation_duration: column missing (run "
                    "migrations/add_session_duration.sql) sid=%s", session_id,
                )
                return False
            logger.warning(
                "set_session_presentation_duration failed sid=%s: %s",
                session_id, e,
            )
            return False

    # ── willab — Audit Delivery (Prompt C §2/§3) ───────────────────────
    #
    # Coach-curated PDF audits, one row per uploaded PDF. Distinct from the
    # lab Readout ('audit_upload' sessions) — see migrations/add_user_audits.sql.

    def insert_user_audit(
        self, user_id: str, name: str, storage_path: str,
        audit_date: Optional[str] = None,
    ) -> Optional[dict]:
        """Record an uploaded audit PDF for a user. Returns the row (with id)
        or None on failure. audit_date defaults to now() server-side."""
        if not user_id or not name or not storage_path:
            return None
        row = {
            "user_id": user_id, "name": name, "storage_path": storage_path,
        }
        if audit_date:
            row["audit_date"] = audit_date
        try:
            res = self.client.table("user_audits").insert(row).execute()
            return (res.data or [None])[0]
        except Exception as e:
            err_low = str(e).lower()
            if "user_audits" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                logger.warning(
                    "insert_user_audit: table missing (run "
                    "migrations/add_user_audits.sql) user=%s", user_id,
                )
                return None
            logger.error("insert_user_audit failed user=%s: %s", user_id, e)
            return None

    def list_user_audits(self, user_id: str) -> list[dict]:
        """A user's audits, newest first. [] on missing table / none / error."""
        if not user_id:
            return []
        try:
            res = (
                self.client.table("user_audits")
                .select("id, name, audit_date, storage_path, created_at")
                .eq("user_id", user_id)
                .order("audit_date", desc=True)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "user_audits" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return []
            logger.warning("list_user_audits failed user=%s: %s", user_id, e)
            return []

    def get_user_audit(self, audit_id: str, user_id: str) -> Optional[dict]:
        """One audit row, OWNERSHIP-scoped to user_id (None if not theirs)."""
        if not audit_id or not user_id:
            return None
        try:
            res = (
                self.client.table("user_audits")
                .select("id, name, audit_date, storage_path, created_at")
                .eq("id", audit_id)
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_user_audit failed id=%s: %s", audit_id, e)
            return None

    # ── Confidence labels (founder 2026-07-28) ─────────────────────────
    # The corpus for the app's core function. SEPARATE from training_labels
    # (challenge/threat is a different construct feeding a different model)
    # and keyed per RATER so the future agreement aggregator has something to
    # aggregate. See services/confidence_labels.py + add_confidence_labels.sql.

    def upsert_confidence_label(
        self, *, snippet_id: str, row: dict, rater_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> bool:
        """Store (or replace) one rater's confidence call on one snippet.
        ``row`` is the validated shape from validate_confidence_label — this
        method does no validation of its own. Best-effort, missing-table-safe;
        NEVER raises."""
        if not snippet_id or not isinstance(row, dict):
            return False
        # FULL-STATE upsert: an omitted intensity CLEARS the stored one.
        # The FE saves yes/no first and the grade second, so a coach who
        # flips their answer sends {confident} alone — carrying the previous
        # answer's intensity forward would leave a 5 attached to a "no"
        # nobody graded. Stale training data is worse than absent training
        # data, so absence wins.
        payload: dict = {
            "snippet_id": str(snippet_id),
            "confident": bool(row.get("confident")),
            "source": row.get("source") or "coach",
            "intensity": row.get("intensity"),
            "note": row.get("note"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if rater_id:
            payload["rater_id"] = str(rater_id)
        if session_id:
            payload["session_id"] = str(session_id)
        try:
            (self.client.table("confidence_labels")
                 .upsert(payload,
                         on_conflict="snippet_id,rater_id").execute())
            return True
        except Exception as e:
            err_low = str(e).lower()
            # 42P10: ON CONFLICT (snippet_id, rater_id) found no matching
            # unique constraint. The arbiter cannot match an expression
            # index, so a database still carrying the original
            # COALESCE-index shape of the migration fails every save here.
            if "42p10" in err_low or "on conflict" in err_low:
                logger.warning(
                    "upsert_confidence_label: unique constraint shape does "
                    "not match ON CONFLICT — re-run the current "
                    "migrations/add_confidence_labels.sql (it swaps the "
                    "expression index for a plain composite constraint)",
                )
                return False
            if "confidence_labels" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "upsert_confidence_label: table missing (run "
                    "migrations/add_confidence_labels.sql)",
                )
                return False
            logger.warning("upsert_confidence_label failed snip=%s: %s",
                           snippet_id, e)
            return False

    def upsert_state_rating(
        self, *, snippet_id: str, row: dict, rater_id: Optional[str] = None,
        session_id: Optional[str] = None, lane: str = "coach",
        intensity: Optional[int] = None,
        model_version_at_time: Optional[str] = None,
        probe_score_at_time: Optional[float] = None,
    ) -> bool:
        """Store (or replace) one rater's TERNARY rating on one snippet
        (SPEC.md v3 §3.2). ``row`` is the validated shape from
        services.state_ratings.validate_rating — no validation happens here.

        Writes the SAME physical table as upsert_confidence_label
        (confidence_labels, extended by add_state_generic_ratings.sql), so the
        two instruments share the per-rater uniqueness and a coach who
        re-rates replaces their own row rather than doubling it.

        The legacy ``confident`` boolean is written alongside for continuity —
        yes/no map onto it, and NEUTRAL WRITES NULL. Neutral is the one answer
        the binary instrument could never express, so a null is the honest
        record; coercing it to false would fabricate a negative label, and
        every reader of that column already tolerates a null row.

        ``intensity`` is written ONLY when the caller passes it explicitly in
        the same request that carried the answer — i.e. a legacy body where
        both came from one judgment. It is never carried forward from a
        previous row: a stale 1-5 grade attached to an answer nobody graded is
        the failure the FULL-STATE upsert above exists to prevent, and absent
        training data beats wrong training data.

        Best-effort, missing-column-safe; NEVER raises."""
        if not snippet_id or not isinstance(row, dict):
            return False
        value = row.get("value")
        payload: dict = {
            "snippet_id": str(snippet_id),
            "state_id": row.get("state_id") or "confidence",
            "value": value,
            "unrateable": bool(row.get("unrateable")),
            "question_id": row.get("question_id"),
            "question_version": row.get("question_version"),
            "saw_model_output": bool(row.get("saw_model_output")),
            "latency_ms": row.get("latency_ms"),
            "note": row.get("note"),
            "lane": lane,
            # `source` predates `lane` and several readers still filter on it.
            # Both bootstrap and coach lanes ARE the coach rating; the lane
            # column is what separates them.
            "source": "coach" if lane in ("bootstrap", "coach") else "game",
            "confident": (True if value == "yes"
                          else False if value == "no" else None),
            # FULL-STATE, like the binary upsert: an omitted intensity CLEARS
            # the stored one rather than carrying the previous answer's grade
            # onto a new answer.
            "intensity": intensity,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if rater_id:
            payload["rater_id"] = str(rater_id)
        if session_id:
            payload["session_id"] = str(session_id)
        if model_version_at_time:
            payload["model_version_at_time"] = str(model_version_at_time)
        if probe_score_at_time is not None:
            payload["probe_score_at_time"] = float(probe_score_at_time)
        try:
            (self.client.table("confidence_labels")
                 .upsert(payload,
                         on_conflict="snippet_id,rater_id").execute())
            # The append-only shadow (SPEC-immutable-provenance §3.2). AFTER
            # the upsert succeeds, never instead of it and never gating it:
            # confidence_labels remains the current-answer read, this is the
            # history the upsert destroys.
            self._append_label_revision(payload)
            return True
        except Exception as e:
            err_low = str(e).lower()
            if ("column" in err_low and (
                    "state_id" in err_low or "unrateable" in err_low
                    or "question_version" in err_low or "lane" in err_low)):
                logger.warning(
                    "upsert_state_rating: ternary columns missing (run "
                    "migrations/add_state_generic_ratings.sql)",
                )
                return False
            if "42p10" in err_low or "on conflict" in err_low:
                logger.warning(
                    "upsert_state_rating: unique constraint shape does not "
                    "match ON CONFLICT — re-run "
                    "migrations/add_confidence_labels.sql",
                )
                return False
            logger.warning("upsert_state_rating failed snip=%s: %s",
                           snippet_id, e)
            return False

    def _append_label_revision(self, payload: dict) -> None:
        """Append ONE revision row shadowing a rating write (§3.2).

        Coach labels are overwritten in place by design (the corpus wants the
        rater's CURRENT answer); this is the only record of what the upsert
        replaced. Nothing here is ever updated or deleted.

        `supersedes_id` is best-effort: the newest prior revision for the
        same (snippet, rater, state), NULL when the lookup fails or nothing
        precedes it. A missing pointer degrades to "order by id" — the chain
        is a convenience, the append is the guarantee.

        NEVER raises, and a failure never un-succeeds the rating write it
        shadows — the table may simply not be migrated yet (0258).
        """
        try:
            state_id = payload.get("state_id") or "confidence"
            rater_id = payload.get("rater_id")
            prev_id = None
            try:
                q = (self.client.table("label_revision").select("id")
                     .eq("snippet_id", payload["snippet_id"])
                     .eq("state_id", state_id))
                q = (q.eq("rater_id", rater_id) if rater_id
                     else q.is_("rater_id", "null"))
                res = q.order("id", desc=True).limit(1).execute()
                if res.data:
                    prev_id = res.data[0].get("id")
            except Exception:
                pass
            row = {
                "snippet_id": payload["snippet_id"],
                "rater_id": rater_id,
                "state_id": state_id,
                "value": payload.get("value"),
                "unrateable": bool(payload.get("unrateable")),
                "confident": payload.get("confident"),
                "intensity": payload.get("intensity"),
                "note": payload.get("note"),
                "lane": payload.get("lane"),
                "source": payload.get("source"),
                "question_id": payload.get("question_id"),
                "question_version": payload.get("question_version"),
                "saw_model_output": bool(payload.get("saw_model_output")),
                "latency_ms": payload.get("latency_ms"),
                "session_id": payload.get("session_id"),
                "model_version_at_time": payload.get("model_version_at_time"),
                "probe_score_at_time": payload.get("probe_score_at_time"),
                "origin": "live",
                "supersedes_id": prev_id,
                # The judgment's own timestamp — created_at is the INSERT's.
                "rated_at": payload.get("updated_at"),
            }
            self.client.table("label_revision").insert(row).execute()
        except Exception as e:
            err_low = str(e).lower()
            if "label_revision" in err_low and (
                    "does not exist" in err_low or "42p01" in err_low
                    or "pgrst" in err_low):
                logger.warning(
                    "label_revision: table missing (run "
                    "migrations/add_label_revision.sql) — rating saved, "
                    "revision NOT recorded")
                return
            logger.warning("_append_label_revision failed snip=%s: %s",
                           payload.get("snippet_id"), e)

    def record_dimension_evaluations(self, rows: list) -> int:
        """Store drift-monitoring evaluations (SPEC D26/D30, Appendix G).

        One row per (snippet, dimension, benchmark_version). Returns the
        number written; 0 on any failure.

        AC-9: nothing written here is user-facing. It feeds PSI and the
        p-chart, which are an INTERNAL audit surface.

        THREE STATES, and conflating any two of them corrupts the monitor:

            computed AND benchmarked   fired=True/False  insufficient=False
            computed, NO benchmark     fired=None        insufficient=False
            not computable             fired=None        insufficient=True

        The middle state is most of what exists today — wpm, pause_ms,
        dynamic_db, pitch_center and energy are measured on every snippet and
        none has a fire threshold in code yet. Those rows are still worth
        storing: PSI reads `decile`, not `fired`.

        So `fired` is passed through as None unless a real decision was made,
        and is forced to None whenever `insufficient_data` is set. Writing
        False for either of the other two states would book a decision nobody
        made, deflating every fire rate and leaving the monitor calm exactly
        when data goes missing.

        Best-effort, missing-column-safe; NEVER raises. Drift telemetry must
        never be able to break the scoring path it observes.
        """
        if not rows:
            return 0
        payload = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not row.get("dimension_id"):
                continue
            if not (row.get("snippet_id") or row.get("recording_id")
                    or row.get("session_id")):
                continue          # ck_dimension_evaluations_has_anchor
            insufficient = bool(row.get("insufficient_data"))
            fired = row.get("fired")
            # None stays None: "no benchmark defined" is a real state, not a
            # negative decision. Only an explicit bool becomes a decision.
            decision = None if (insufficient or fired is None) else bool(fired)
            # A SNIPPET-GRAIN ROW DOES NOT ALSO CLAIM THE RECORDING GRAIN
            # (23505, found in production 2026-08-12 the moment the error
            # handler above started printing real codes):
            #
            #   Key (recording_id, dimension_id, benchmark_version)
            #     = (97d982ea…, wpm, measure-v1) already exists.
            #   violates unique constraint "uq_dimension_evaluations_rec_dim_ver"
            #
            # `_windowed_rate_rows` sets snippet_id AND recording_id, so seven
            # windows of one recording produce seven rows sharing a
            # (recording_id, dimension_id, benchmark_version). The upsert's
            # arbiter names the SNIPPET index, so Postgres never treats the
            # recording-grain violation as a conflict to resolve — it raises,
            # and a best-effort writer swallows it. That is why this table
            # kept staying empty.
            #
            # 0249 already designed the way out: storage is SNIPPET grain
            # ("ANALYSIS must aggregate to session grain first"), and the
            # recording-grain index is PARTIAL — `WHERE recording_id IS NOT
            # NULL`. That partiality only does its job if snippet-grain rows
            # leave the column NULL, which is what this does. The row keeps
            # its anchor (ck_dimension_evaluations_has_anchor is satisfied by
            # snippet_id) and its session_id, which is the grain every reader
            # actually uses: `get_dimension_evaluations_since` does not select
            # recording_id at all, and the drift job aggregates to session
            # before it computes anything.
            #
            # Rows already written keep their recording_id. Backfilling would
            # rewrite historical calculations to fit a later understanding —
            # the one thing the founder's immutability rule forbids — and no
            # reader needs it.
            _snip = row.get("snippet_id")
            entry = {
                "snippet_id": _snip,
                "recording_id": None if _snip else row.get("recording_id"),
                "session_id": row.get("session_id"),
                "user_id": row.get("user_id"),
                "dimension_id": str(row["dimension_id"]),
                "raw_value": row.get("raw_value"),
                "decile": row.get("decile"),
                "fired": decision,
                "insufficient_data": insufficient,
                "benchmark_tier": row.get("benchmark_tier") or "CORPUS_REL",
                "benchmark_version": str(row.get("benchmark_version") or "v0"),
                "window_class": row.get("window_class"),
                "n_units": row.get("n_units"),
            }
            # The provenance stamp (SPEC-immutable-provenance §3.1): which
            # detector definition produced this number, and whether the live
            # code still hashed to it at write time. {} for dimensions with
            # no registered detector, or while detector_version is absent —
            # an unstamped row is the honest pre-provenance NULL.
            try:
                from services.provenance_check import stamp
                entry.update(stamp(entry["dimension_id"]))
            except Exception:
                pass          # the stamp must never break the write it rides
            payload.append(entry)
        if not payload:
            return 0
        # PostgREST upserts are all-or-nothing per batch: since every row in
        # a batch is built the same way, a payload either uniformly carries
        # the stamp keys or uniformly does not.
        stamped = any("provenance" in p for p in payload)
        try:
            (self.client.table("dimension_evaluations")
                 .upsert(payload,
                         on_conflict="snippet_id,dimension_id,benchmark_version")
                 .execute())
            return len(payload)
        except Exception as e:
            err_low = str(e).lower()
            # 0257 not applied yet but detector_version somehow readable (or
            # a schema cache lag): retry WITHOUT the stamp rather than losing
            # the measurements. Losing telemetry to the stamp would invert
            # the priority — provenance exists to protect the data, not to
            # gate it.
            if stamped and "column" in err_low and (
                    "provenance" in err_low or "detector_version" in err_low):
                logger.warning(
                    "record_dimension_evaluations: provenance columns missing "
                    "(run migrations/add_detector_version.sql) — writing "
                    "unstamped")
                for p in payload:
                    p.pop("provenance", None)
                    p.pop("detector_version", None)
                try:
                    (self.client.table("dimension_evaluations")
                         .upsert(payload,
                                 on_conflict=("snippet_id,dimension_id,"
                                              "benchmark_version"))
                         .execute())
                    return len(payload)
                except Exception as e2:
                    logger.warning(
                        "record_dimension_evaluations failed: %s", e2)
                    return 0
            # THE ERROR IS THE ERROR (2026-08-12). This branch used to read
            #
            #     if "does not exist" in err_low or "dimension_evaluations" in err_low
            #
            # — a substring match on the TABLE'S OWN NAME, which every
            # PostgREST error about this table contains. So a stale schema
            # cache (PGRST204, "could not find the 'snippet_id' column … in
            # the schema cache"), a bad arbiter (42P10) and a genuinely absent
            # table all printed the same sentence: "table/columns missing (run
            # …)". It sent a full afternoon after two migrations that had been
            # applied the whole time, on a table holding 145 rows.
            #
            # A best-effort writer swallows its failures by design (see the
            # docstring), so this log line is the ONLY thing that will ever
            # say why the table stopped filling. It has to say the true thing.
            # The migration hint survives, narrowed to the codes that actually
            # mean the object is absent.
            code = _pg_error_code(e)
            missing = code in _MISSING_OBJECT_CODES or (
                not code and "does not exist" in err_low)
            if missing:
                logger.warning(
                    "record_dimension_evaluations: %s — object missing (run "
                    "migrations/add_dimension_evaluations.sql then "
                    "add_dimension_evaluations_snippet_grain.sql; if those are "
                    "applied, the PostgREST schema cache is stale — "
                    "NOTIFY pgrst, 'reload schema')", code or "no code")
                return 0
            logger.warning("record_dimension_evaluations failed [%s]: %s",
                           code or "no code", e)
            return 0

    def record_intervention_arms(self, rows: list) -> int:
        """Store the manager engine's experiment arms (PM-8, Appendix H.12).

        One row per (session, dimension) CONSIDERED. Returns the number
        written; 0 on any failure. Best-effort and NEVER raises — the same
        rule as the drift telemetry: a recorder must not break the thing it
        records.

        THAT SWALLOW IS WHY THE CONTRACT IS TESTED STATICALLY. Twice on
        2026-08-06 a schema/code mismatch made every write fail silently and
        the table simply stayed empty — a partial index used as an ON CONFLICT
        arbiter (42P10), then an INTEGER column handed a fraction (22P02).
        `test_upsert_arbiters` and `test_schema_column_types` cover both
        shapes for this table too; nothing at runtime will ever complain.

        AC-9: internal only. Arm assignments and priority values are
        arbitration inputs and must never reach a client-facing schema.
        """
        if not rows:
            return 0
        payload = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not row.get("session_id") or not row.get("dimension_id"):
                continue
            arm = str(row.get("arm") or "")
            if arm not in ("CONTROL", "WITHHELD", "EXPLORE",
                           "TREATED", "NOT_SELECTED"):
                continue          # ck_intervention_arms_arm
            surfaced = bool(row.get("surfaced"))
            # Keep the CHECK satisfied here rather than letting Postgres
            # reject the whole batch: a caller bug must cost one row, not the
            # entire session's record.
            if surfaced != (arm in ("TREATED", "EXPLORE")):
                continue          # ck_intervention_arms_surfaced_agrees
            payload.append({
                "session_id": str(row["session_id"]),
                "user_id": row.get("user_id"),
                "dimension_id": str(row["dimension_id"]),
                "arm": arm,
                "priority": row.get("priority"),
                "would_have_surfaced": row.get("would_have_surfaced"),
                "surfaced": surfaced,
                "form": row.get("form"),
                "control_salt": row.get("control_salt"),
                "withhold_salt": row.get("withhold_salt"),
                "gamma": row.get("gamma"),
                "withhold_rate": row.get("withhold_rate"),
                "exploration_rate": row.get("exploration_rate"),
            })
        if not payload:
            return 0
        try:
            (self.client.table("intervention_arms")
                 .upsert(payload, on_conflict="session_id,dimension_id")
                 .execute())
            return len(payload)
        except Exception as e:
            err_low = str(e).lower()
            if "does not exist" in err_low or "intervention_arms" in err_low:
                logger.warning(
                    "record_intervention_arms: table/columns missing (run "
                    "migrations/add_intervention_arms.sql)",
                )
                return 0
            logger.warning("record_intervention_arms failed: %s", e)
            return 0

    def get_dimension_evaluations_since(self, *, weeks: int = 4,
                                        limit: int = 50000) -> list:
        """Evaluation rows for the drift job. [] on anything missing.

        Returns raw rows; SESSION-GRAIN AGGREGATION IS THE CALLER'S JOB and is
        not optional — snippets inside a session are not independent, and
        counting thirty of them as thirty observations narrows the p-chart's
        control limits by ~sqrt(30) and makes the monitor fire on its own
        sampling. services.drift_job does it.
        """
        try:
            from datetime import timedelta
            since = (datetime.now(timezone.utc)
                     - timedelta(weeks=int(weeks))).isoformat()
            res = (self.client.table("dimension_evaluations")
                   .select("session_id, dimension_id, raw_value, fired, "
                           "benchmark_tier, benchmark_version, "
                           "insufficient_data, evaluated_at")
                   .gte("evaluated_at", since)
                   .limit(int(limit)).execute())
            return res.data or []
        except Exception as e:
            logger.warning("get_dimension_evaluations_since failed: %s", e)
            return []

    def get_reference_distribution(self, version: str = "frozen_v1") -> list:
        """The frozen PSI baseline. [] when it has not been minted yet, which
        is a normal early state, not an error."""
        try:
            res = (self.client.table("reference_distribution")
                   .select("dimension_id, decile, pct, upper_bound, n_at_freeze")
                   .eq("version", str(version)).execute())
            return res.data or []
        except Exception as e:
            logger.warning("get_reference_distribution failed: %s", e)
            return []

    def insert_reference_distribution(self, rows: list) -> int:
        """Mint a frozen reference. Returns rows written; 0 on failure.

        NEVER UPDATES. reference_distribution blocks UPDATE by trigger — a
        reference recomputed on a rolling window tracks the drift it exists to
        detect, PSI reads ~0 forever, and the monitor becomes decorative WHILE
        APPEARING TO WORK. A refit inserts a new `version`.
        """
        if not rows:
            return 0
        try:
            (self.client.table("reference_distribution")
                 .insert(rows).execute())
            return len(rows)
        except Exception as e:
            err = str(e).lower()
            if "duplicate" in err or "unique" in err or "23505" in err:
                logger.info("insert_reference_distribution: version already "
                            "minted — refusing to overwrite a frozen "
                            "reference (this is the trigger doing its job)")
                return 0
            logger.warning("insert_reference_distribution failed: %s", e)
            return 0

    def get_confidence_labels_by_snippet_ids(self, snippet_ids: list) -> dict:
        """{snippet_id: [label rows]} for the given snippets. {} on anything
        missing — the queue then renders every piece as unlabelled."""
        ids = [str(s) for s in (snippet_ids or []) if s]
        if not ids:
            return {}
        try:
            rows = (self.client.table("confidence_labels")
                    .select("*").in_("snippet_id", ids).execute().data) or []
            out: dict = {}
            for r in rows:
                out.setdefault(str(r.get("snippet_id")), []).append(r)
            return out
        except Exception as e:
            logger.warning("get_confidence_labels_by_snippet_ids failed: %s", e)
            return {}

    def get_own_state_ratings_for_session(self, session_id: str,
                                          rater_id: str) -> dict:
        """{snippet_id: {value, unrateable}} — THIS rater's own ratings only.

        SCOPED TO ONE RATER ON PURPOSE, and that scope is the whole safety
        argument. Showing a coach their OWN prior answer is just resuming
        their work. Showing them ANOTHER rater's would anchor the next label
        and quietly destroy the independence that makes multi-rater agreement
        mean anything — the same reason the labeler card shows no machine
        read. A future "what did the panel say" surface is a different
        endpoint with a different audience, never this one.

        {} on anything missing, so the card renders every snippet as
        unanswered rather than failing the whole review read.
        """
        if not session_id or not rater_id:
            return {}
        try:
            rows = (self.client.table("confidence_labels")
                    .select("snippet_id, value, unrateable")
                    .eq("session_id", str(session_id))
                    .eq("rater_id", str(rater_id))
                    .execute().data) or []
            out: dict = {}
            for r in rows:
                snippet_id = r.get("snippet_id")
                if not snippet_id:
                    continue
                out[str(snippet_id)] = {
                    "value": r.get("value"),
                    "unrateable": bool(r.get("unrateable")),
                }
            return out
        except Exception as e:
            logger.warning(
                "get_own_state_ratings_for_session failed session=%s: %s",
                session_id, e)
            return {}

    def count_labelled_snippets_by_session_ids(self, session_ids: list) -> dict:
        """{session_id: how many DISTINCT snippets carry a confidence label}.

        The corpus index's "how much is labelled" badge (FE 2026-07-30) —
        one batched query for the whole list, where the FE's fallback costs
        one queue request per row. DISTINCT snippets, not label rows: two
        raters on one piece is still one labelled piece. {} on anything
        missing — the badge then falls back to the FE's queue read."""
        ids = [str(s) for s in (session_ids or []) if s]
        if not ids:
            return {}
        try:
            rows = (self.client.table("confidence_labels")
                    .select("session_id, snippet_id")
                    .in_("session_id", ids).execute().data) or []
            seen: dict = {}
            for r in rows:
                sid, snip = r.get("session_id"), r.get("snippet_id")
                if sid and snip:
                    seen.setdefault(str(sid), set()).add(str(snip))
            return {sid: len(snips) for sid, snips in seen.items()}
        except Exception as e:
            logger.warning(
                "count_labelled_snippets_by_session_ids failed: %s", e)
            return {}

    def get_confidence_label_corpus(self, *, source: Optional[str] = None,
                                    limit: int = 5000) -> list:
        """The training-side pull, newest first. [] on anything missing."""
        try:
            q = self.client.table("confidence_labels").select("*")
            if source:
                q = q.eq("source", str(source))
            return (q.order("created_at", desc=True)
                     .limit(int(limit)).execute().data) or []
        except Exception as e:
            logger.warning("get_confidence_label_corpus failed: %s", e)
            return []

    # ── Peer-review validation loop (founder 2026-08-03) ───────────────
    # A user/peer flags whether the AI's confidence choice was right. SEPARATE
    # table from confidence_labels on purpose: these are NON-BLIND (the
    # reviewer saw the AI's call first), and blending them indistinguishably
    # with the blind coach corpus would let the model grade its own homework.
    # See services/confidence_reviews.py + add_snippet_confidence_reviews.sql.

    def upsert_snippet_confidence_review(
        self, *, snippet_id: str, reviewer_user_id: str, ai_correct: bool,
        model_version: Optional[str] = None,
    ) -> bool:
        """Store (or REPLACE) one reviewer's flag on one snippet.

        Replace-on-reflag: (snippet_id, reviewer_user_id) is unique, so a
        reviewer who changes their mind updates their row rather than stacking
        a second one — duplicate rows from one rater are junk labels (the same
        N3 rule the voice game follows). Other reviewers' rows are untouched,
        so peer agreement stays computable.

        ``ai_correct`` is already a validated real boolean by the time it gets
        here (services/confidence_reviews.validate_confidence_review); this
        method does no validation of its own. Best-effort, missing-table-safe;
        NEVER raises."""
        if not snippet_id or not reviewer_user_id:
            return False
        payload: dict = {
            "snippet_id": str(snippet_id),
            "reviewer_user_id": str(reviewer_user_id),
            "ai_correct": bool(ai_correct),
            "model_version": model_version,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            (self.client.table("snippet_confidence_reviews")
                 .upsert(payload,
                         on_conflict="snippet_id,reviewer_user_id").execute())
            return True
        except Exception as e:
            err_low = str(e).lower()
            # 42P10: ON CONFLICT found no matching unique constraint — the
            # composite UNIQUE in the migration has not been applied.
            if "42p10" in err_low or "on conflict" in err_low:
                logger.warning(
                    "upsert_snippet_confidence_review: unique constraint does "
                    "not match ON CONFLICT — run "
                    "migrations/add_snippet_confidence_reviews.sql",
                )
                return False
            if "snippet_confidence_reviews" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "upsert_snippet_confidence_review: table missing (run "
                    "migrations/add_snippet_confidence_reviews.sql)",
                )
                return False
            logger.warning("upsert_snippet_confidence_review failed snip=%s: %s",
                           snippet_id, e)
            return False

    def get_snippet_confidence_reviews(self, *, limit: int = 5000) -> list:
        """The peer-review corpus pull, newest first. [] on anything missing —
        the trace then reports zero peer_review rows rather than erroring."""
        try:
            return (self.client.table("snippet_confidence_reviews")
                    .select("snippet_id, reviewer_user_id, ai_correct, "
                            "model_version, created_at")
                    .order("created_at", desc=True)
                    .limit(int(limit)).execute().data) or []
        except Exception as e:
            err_low = str(e).lower()
            if "snippet_confidence_reviews" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                return []
            logger.warning("get_snippet_confidence_reviews failed: %s", e)
            return []

    def find_training_import_by_key(self, key: str) -> Optional[dict]:
        """The SUCCESSFUL import already created under this idempotency key,
        or None.

        The retry-safety half of the timeout problem (FE 2026-07-28): the
        proxy can time out on a request whose BE work then SUCCEEDS, so a
        re-send must return the ORIGINAL import rather than mint a second —
        a talk imported twice is labelled twice and trained on twice, and
        nothing on screen would say so.

        A FAILED import releases its key (FE §7, 2026-07-29). Deduping a
        retry-after-failure would make the key a permanent lock: a
        NO_CANDIDATES import is a tuning problem on MY side, the coach
        changes nothing about the file, and once I retune they could never
        get a fresh run — the key would keep handing back the failure. The
        duplicate worth preventing is the retry after a SUCCESS the coach
        could not see; a retry after a visible failure is exactly the retry
        that should be allowed through.

        Best-effort; None on any error (the caller then proceeds, which risks
        the duplicate but never blocks a legitimate first import)."""
        if not key:
            return None
        try:
            rows = (
                self.client.table("v2_sessions")
                .select("id, arc_id, intake_context, analysis_state")
                .eq("source", "training_import")
                .eq("intake_context->>import_key", str(key))
                .order("created_at", desc=True)
                .limit(5)
                .execute()
                .data
            ) or []
            for r in rows:
                if (r.get("analysis_state") or "ready") != "failed":
                    return r
            return None
        except Exception as e:
            logger.warning("find_training_import_by_key failed: %s", e)
            return None

    def list_training_import_sessions(self, *, user_id: Optional[str] = None,
                                      limit: int = 200) -> list[dict]:
        """The imported training takes, newest first (founder 2026-07-28).

        Deliberately NOT v2_list_user_lab_sessions with a different filter:
        that method is the per-speaker BASELINE reader, and imports must stay
        out of it (a corpus of many voices would corrupt one speaker's norm —
        see services/training_import.py). This is the coach's separate
        window onto the corpus. Best-effort: [] on anything missing.

        analysis_state comes from an older migration, so the select degrades
        rather than betting the whole list on it: a DB without that column
        would otherwise return an EMPTY corpus index, which reads exactly
        like "nothing imported" — the failure this list exists to rule out."""
        _cols_full = ("id, arc_id, take_index, intake_context, created_at, "
                      "status, user_id, recording_1_id, analysis_state")
        _cols_base = ("id, arc_id, take_index, intake_context, created_at, "
                      "status, user_id, recording_1_id")
        for _cols in (_cols_full, _cols_base):
            try:
                q = (
                    self.client.table("v2_sessions")
                    .select(_cols)
                    .eq("source", "training_import")
                )
                if user_id:
                    q = q.eq("user_id", str(user_id))
                return (q.order("created_at", desc=True)
                         .limit(int(limit)).execute().data) or []
            except Exception as e:
                if _cols is _cols_base:
                    logger.warning(
                        "list_training_import_sessions failed: %s", e)
                    return []
                logger.warning(
                    "list_training_import_sessions: analysis_state missing "
                    "(run migrations/add_analysis_state.sql) — retrying "
                    "without it: %s", e)
        return []

    def set_session_source(self, session_id: str, source: str) -> bool:
        """Stamp v2_sessions.source (foundation discriminator). The Lab
        handler marks its sessions 'audit_upload' so the history list +
        future audit features can find willab Lab sessions. Best-effort;
        missing column (migration pending) → False, non-fatal."""
        if not session_id:
            return False
        try:
            (
                self.client.table("v2_sessions")
                .update({"source": source})
                .eq("id", session_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            # An enum CHECK rejection is a DEPLOYMENT error, not a data one,
            # and it cost a day of silent orphaned imports: 'training_import'
            # was not in v2_sessions_source_check, every UPDATE 23514'd, and
            # this method's quiet False was mistaken for "nothing to do".
            # Name the fix in the log rather than making the next person
            # reverse-engineer a missing row.
            if "23514" in err_low or "check constraint" in err_low:
                logger.error(
                    "set_session_source: '%s' is not an allowed source value "
                    "— the v2_sessions_source_check CHECK rejected it (run "
                    "migrations/add_training_import_source.sql if this is a "
                    "training import) sid=%s", source, session_id,
                )
                return False
            if "source" in err_low and "pgrst" in err_low:
                return False
            logger.warning(
                "set_session_source failed sid=%s err=%s", session_id, e,
            )
            return False

    def list_user_lab_sessions(
        self,
        user_id: str,
        *,
        limit: int = 50,
    ) -> list[dict]:
        """List a user's willab Lab sessions, newest first, for the
        history / scroll-back view. Filters source='audit_upload' so
        old-funnel/homework sessions don't appear. Returns lightweight
        rows; the FE fetches the full readout per session on tap.
        """
        if not user_id:
            return []
        try:
            res = (
                self.client.table("v2_sessions")
                .select(
                    "id, created_at, status, results_published_at, "
                    "intake_context"
                )
                .eq("user_id", user_id)
                .eq("source", "audit_upload")
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "source" in err_low and "pgrst" in err_low:
                logger.warning(
                    "list_user_lab_sessions: source column missing (run "
                    "migrations/add_foundation_discriminators.sql) user=%s",
                    user_id,
                )
                return []
            logger.warning(
                "list_user_lab_sessions failed user=%s err=%s", user_id, e,
            )
            return []

    # ── willab beta — training labels (design §14, PRIVATE lane) ────

    def upsert_training_labels(
        self,
        session_id: str,
        labeled_by: Optional[str],
        rows: list[dict],
    ) -> int:
        """Persist the per-snippet direction labels captured at publish.

        Idempotent on (session_id, snippet_id) — re-publish updates the
        current label. Stamps session_id + labeled_by + labeled_at on
        each row (the validator supplied snippet_id/value/flags/
        schema_version). Returns rows written; 0 on missing table.

        PRIVATE lane (split-sink §2): written here, never read into any
        user-facing path.
        """
        if not session_id or not rows:
            return 0
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = [
            {
                "session_id": session_id,
                "snippet_id": r["snippet_id"],
                "schema_version": r.get("schema_version", "direction-v1"),
                "value": r["value"],
                "labeled_by": labeled_by,
                "labeled_at": now_iso,
                "was_pre_filled": bool(r.get("was_pre_filled", False)),
                "was_overridden": bool(r.get("was_overridden", False)),
                "updated_at": now_iso,
            }
            for r in rows
        ]
        try:
            res = (
                self.client.table("training_labels")
                .upsert(payload, on_conflict="session_id,snippet_id")
                .execute()
            )
            return len(res.data or [])
        except Exception as e:
            err_low = str(e).lower()
            if (
                "training_labels" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                logger.warning(
                    "upsert_training_labels: table missing (run "
                    "migrations/add_training_labels_table.sql) sid=%s",
                    session_id,
                )
                return 0
            logger.error(
                "upsert_training_labels failed sid=%s err=%s", session_id, e,
            )
            return 0

    def get_training_labels(self, session_id: str) -> list[dict]:
        """Read the per-snippet direction labels for a session.

        PRIVATE training lane (split-sink §2/§14): exposed ONLY to the
        coach-authoring readout (`GET /v2/admin/sessions/<id>/readout`),
        NEVER folded into a user-facing path. Returns [] if none / table
        missing (cold start has no labels → coach labels from scratch).
        """
        if not session_id:
            return []
        try:
            res = (
                self.client.table("training_labels")
                .select(
                    "snippet_id, schema_version, value, was_pre_filled, "
                    "was_overridden, labeled_by, labeled_at"
                )
                .eq("session_id", session_id)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "training_labels" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return []
            logger.warning(
                "get_training_labels failed sid=%s err=%s", session_id, e,
            )
            return []

    def get_training_labels_by_sessions(self, session_ids) -> dict:
        """Batch read of per-snippet direction labels for MANY sessions in ONE
        query per 100 ids (kills the N+1 in build_best_presentation /
        build_arc_breakthroughs over a long arc). Returns
        {session_id: [labels]}. Same PRIVATE training lane as
        get_training_labels. {} on missing table / empty input / error."""
        ids = [str(s) for s in (session_ids or []) if s]
        if not ids:
            return {}
        out: dict = {}
        try:
            for i in range(0, len(ids), 100):
                chunk = ids[i:i + 100]
                res = (
                    self.client.table("training_labels")
                    .select(
                        "session_id, snippet_id, schema_version, value, "
                        "was_pre_filled, was_overridden, labeled_by, labeled_at"
                    )
                    .in_("session_id", chunk)
                    .execute()
                )
                for r in (res.data or []):
                    out.setdefault(str(r.get("session_id")), []).append(r)
            return out
        except Exception as e:
            err_low = str(e).lower()
            if "training_labels" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return {}
            logger.warning(
                "get_training_labels_by_sessions failed (%d ids): %s",
                len(ids), e,
            )
            return {}

    def get_all_training_labels(self, *, limit: int = 50000) -> list[dict]:
        """Read ALL direction labels across sessions — the corpus the shadow
        learner trains on (Phase 4 / Prompt 1, B1 export). PRIVATE training
        lane; service-role only. Returns [] on missing table (cold start)."""
        try:
            res = (
                self.client.table("training_labels")
                .select(
                    "session_id, snippet_id, schema_version, value, "
                    "was_pre_filled, was_overridden, selection_source, "
                    "heuristic_version, labeled_at"
                )
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "training_labels" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return []
            # selection_source / heuristic_version missing (migration unrun) →
            # retry without them so export still works pre-migration.
            if "selection_source" in err_low or "heuristic_version" in err_low:
                try:
                    res = (
                        self.client.table("training_labels")
                        .select(
                            "session_id, snippet_id, schema_version, value, "
                            "was_pre_filled, was_overridden, labeled_at"
                        )
                        .limit(limit)
                        .execute()
                    )
                    return res.data or []
                except Exception:
                    return []
            logger.warning("get_all_training_labels failed err=%s", e)
            return []

    def get_snippet_metrics_by_ids(self, snippet_ids: list[str]) -> dict:
        """{snippet_id: metrics} for the given charisma snippets — the 11-feature
        side of the export join. Best-effort; missing rows just absent."""
        out: dict = {}
        ids = [s for s in (snippet_ids or []) if s]
        if not ids:
            return out
        try:
            # chunk to keep the IN() list sane
            for i in range(0, len(ids), 200):
                chunk = ids[i:i + 200]
                res = (
                    self.client.table(SNIPPETS_TABLE)
                    .select("id, metrics")
                    .in_("id", chunk)
                    .execute()
                )
                for row in (res.data or []):
                    out[str(row.get("id"))] = row.get("metrics") or {}
        except Exception as e:
            logger.warning("get_snippet_metrics_by_ids failed err=%s", e)
        return out

    def get_snippet_data_origin_by_ids(self, snippet_ids: list[str]) -> dict:
        """{snippet_id: data_origin} for the given charisma snippets (Subsystem-S
        wall — lets the export hard-exclude synthetic from the truth corpus).
        Best-effort: a missing column (pre-migration) returns {} so EVERYTHING is
        treated as real — safe, since no synthetic data exists pre-migration."""
        out: dict = {}
        ids = [s for s in (snippet_ids or []) if s]
        if not ids:
            return out
        try:
            for i in range(0, len(ids), 200):
                chunk = ids[i:i + 200]
                res = (
                    self.client.table(SNIPPETS_TABLE)
                    .select("id, data_origin")
                    .in_("id", chunk)
                    .execute()
                )
                for row in (res.data or []):
                    out[str(row.get("id"))] = row.get("data_origin")
        except Exception as e:
            err_low = str(e).lower()
            if "data_origin" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                logger.warning(
                    "get_snippet_data_origin_by_ids: column missing (run "
                    "migrations/add_synthetic_provenance_walls.sql) — treating "
                    "all as real",
                )
                return {}
            logger.warning("get_snippet_data_origin_by_ids failed err=%s", e)
        return out

    def insert_game_save(self, user_id: str, arc_id: str) -> bool:
        """Save a game session under TODAY's date (Engine 5 daily practice).
        Idempotent per (user, arc, date) — a re-save the same day no-ops.
        Best-effort; missing table (run migrations/add_game_saves.sql) →
        False."""
        if not user_id or not arc_id:
            return False
        from datetime import datetime, timezone
        row = {
            "user_id": str(user_id), "arc_id": str(arc_id),
            "saved_date": datetime.now(timezone.utc).date().isoformat(),
        }
        try:
            self.client.table("game_saves").upsert(
                row, on_conflict="user_id,arc_id,saved_date",
            ).execute()
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "game_saves" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                logger.warning(
                    "insert_game_save: table missing (run "
                    "migrations/add_game_saves.sql)",
                )
                return False
            logger.warning("insert_game_save failed user=%s arc=%s: %s",
                           user_id, arc_id, e)
            return False

    def list_game_saves(self, user_id: str) -> list:
        """The user's saved game sessions, newest first (the Game tab's
        key-moments archive). [] on missing table / none / error."""
        if not user_id:
            return []
        try:
            res = (
                self.client.table("game_saves")
                .select("id, arc_id, saved_date, created_at")
                .eq("user_id", str(user_id))
                .order("saved_date", desc=True)
                .execute()
            )
            # saved_at alias = the DATE it was filed under (the FE reads
            # saved_at first; created_at is the row timestamp fallback).
            out = []
            for r in (res.data or []):
                if isinstance(r, dict):
                    out.append({**r, "saved_at": r.get("saved_date")})
            return out
        except Exception as e:
            err_low = str(e).lower()
            if "game_saves" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return []
            logger.warning("list_game_saves failed user=%s: %s", user_id, e)
            return []

    # ── Coach star verdicts (founder 2026-07-27) ───────────────────────
    # The DECISION-layer correction corpus for the voice-text analytics: did
    # this star deserve to fire, and as this kind? Separate from
    # training_labels (the blind confidence-labeling lane) by fence — see
    # services/star_verdicts.py. Never surfaced to a student (AC-9).

    def upsert_star_verdict(
        self, *, snippet_id: str, row: dict, session_id: Optional[str] = None,
        arc_id: Optional[str] = None, coach_user_id: Optional[str] = None,
    ) -> bool:
        """Store (or replace) the coach's judgment of ONE fired star.

        ``row`` is the validated shape from star_verdicts.validate_verdict —
        this method does no validation of its own so there is exactly one
        place that decides what a legal verdict is. Upsert on snippet_id: a
        re-judgment replaces, because the corpus wants the coach's current
        view, not their deliberation history.

        Best-effort, missing-table-safe; NEVER raises."""
        if not snippet_id or not isinstance(row, dict) or not row.get("verdict"):
            return False
        payload: dict = {"snippet_id": str(snippet_id)}
        for k in ("star_kind", "star_device", "verdict", "corrected_device",
                  "note", "star_version"):
            if row.get(k) is not None:
                payload[k] = row[k]
        if session_id:
            payload["session_id"] = str(session_id)
        if arc_id:
            payload["arc_id"] = str(arc_id)
        if coach_user_id:
            payload["coach_user_id"] = str(coach_user_id)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            (self.client.table("star_verdicts")
                 .upsert(payload, on_conflict="snippet_id").execute())
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "star_verdicts" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "upsert_star_verdict: table missing (run "
                    "migrations/add_star_verdicts.sql)",
                )
                return False
            logger.warning("upsert_star_verdict failed: %s", e)
            return False

    def get_star_verdict(self, snippet_id: str) -> tuple:
        """One star's verdict row, error-distinguishing: ``(row_or_None, ok)``.

        The keep-flip emission guard needs "no verdict exists" and "the read
        FAILED" to be different answers (review finding): the by-ids reader
        returns {} for both, and treating an errored read as "no prior"
        re-emits the approved_as_is row on a re-keep — the exact double-write
        the guard exists to prevent. ok=False → the caller fails CLOSED
        (no emission)."""
        if not snippet_id:
            return None, False
        try:
            rows = (self.client.table("star_verdicts")
                    .select("*").eq("snippet_id", str(snippet_id))
                    .limit(1).execute().data) or []
            return (rows[0] if rows else None), True
        except Exception as e:
            err_low = str(e).lower()
            if "star_verdicts" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                # Missing table = genuinely no verdict can exist yet — that
                # is a real "no prior", not an unknown.
                return None, True
            logger.warning("get_star_verdict failed snip=%s: %s",
                           snippet_id, e)
            return None, False

    def get_star_verdicts_by_snippet_ids(self, snippet_ids: list) -> dict:
        """{snippet_id: verdict_row} for the given snippets. {} on anything
        missing — the coach review simply renders every star as unjudged."""
        ids = [str(s) for s in (snippet_ids or []) if s]
        if not ids:
            return {}
        try:
            rows = (self.client.table("star_verdicts")
                    .select("*").in_("snippet_id", ids).execute().data) or []
            return {str(r.get("snippet_id")): r for r in rows
                    if r.get("snippet_id")}
        except Exception as e:
            err_low = str(e).lower()
            if "star_verdicts" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "get_star_verdicts_by_snippet_ids: table missing (run "
                    "migrations/add_star_verdicts.sql)",
                )
                return {}
            logger.warning("get_star_verdicts_by_snippet_ids failed: %s", e)
            return {}

    def get_star_verdicts_for_corpus(self, *, star_kind: Optional[str] = None,
                                     limit: int = 5000) -> list:
        """The training-side pull: judged stars, newest first, optionally one
        family. [] on anything missing; NEVER raises."""
        try:
            q = self.client.table("star_verdicts").select("*")
            if star_kind:
                q = q.eq("star_kind", str(star_kind))
            return (q.order("created_at", desc=True)
                     .limit(int(limit)).execute().data) or []
        except Exception as e:
            logger.warning("get_star_verdicts_for_corpus failed: %s", e)
            return []

    def insert_snippet_peer_label(
        self, *, snippet_id: str, rater_id: Optional[str], label: Optional[str],
        source: Optional[str] = None, is_second_order: bool = True,
        weight: float = 1.0, shown_origin: Optional[str] = None,
    ) -> bool:
        """Record a SECOND-ORDER (non-coach) peer/self-verification label
        (Subsystem-S multi-rater lane). Separate from training_labels (the
        coach-truth corpus) — a future model blends this BELOW coach truth.
        Best-effort, append-only, missing-table-safe; NEVER raises."""
        if not snippet_id:
            return False
        row: dict = {
            "snippet_id": str(snippet_id),
            "is_second_order": bool(is_second_order),
            "weight": float(weight),
        }
        if rater_id:
            row["rater_id"] = str(rater_id)
        if label is not None:
            row["label"] = str(label)
        if source:
            row["source"] = str(source)
        if shown_origin:
            row["shown_origin"] = str(shown_origin)
        try:
            self.client.table("snippet_peer_labels").insert(row).execute()
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "snippet_peer_labels" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "insert_snippet_peer_label: table missing (run "
                    "migrations/add_synthetic_provenance_walls.sql)",
                )
                return False
            logger.warning("insert_snippet_peer_label failed: %s", e)
            return False

    def insert_user_suggestion_feedback(
        self, *, snippet_id: str, session_id: Optional[str],
        user_id: Optional[str], target: str, action: str,
        upgrade_index: Optional[int] = None,
        suggestion_version: Optional[str] = None,
    ) -> bool:
        """Record one Apply / ✓-prefer tap on a suggestion row (founder
        2026-07-14) — a SECOND-ORDER preference signal strictly below coach
        truth (mirrors insert_snippet_peer_label). Never joined into
        training_labels; never surfaced back as a score (AC-9 — capture
        only). Best-effort, append-only, missing-table-safe; NEVER raises."""
        if not snippet_id or not target or not action:
            return False
        row: dict = {
            "snippet_id": str(snippet_id),
            "target": str(target),
            "action": str(action),
        }
        if session_id:
            row["session_id"] = str(session_id)
        if user_id:
            row["user_id"] = str(user_id)
        if isinstance(upgrade_index, int) and not isinstance(upgrade_index, bool):
            row["upgrade_index"] = upgrade_index
        if suggestion_version is not None:
            row["suggestion_version"] = str(suggestion_version)
        try:
            self.client.table("user_suggestion_feedback").insert(row).execute()
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "user_suggestion_feedback" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "insert_user_suggestion_feedback: table missing (run "
                    "migrations/add_user_suggestion_feedback.sql)",
                )
                return False
            logger.warning("insert_user_suggestion_feedback failed: %s", e)
            return False

    def get_suggestion_feedback_by_session(self, session_id: str) -> list[dict]:
        """All Apply/✓/revert taps for a session, CHRONOLOGICAL — the readout
        replays them into per-snippet applied_upgrade_indexes so the FE's
        Approve state (and its reversibility) survives reload (founder
        2026-07-15). [] on missing table / none / error."""
        if not session_id:
            return []
        try:
            res = (
                self.client.table("user_suggestion_feedback")
                .select("snippet_id, target, upgrade_index, action, created_at")
                .eq("session_id", str(session_id))
                .order("created_at", desc=False)
                .execute()
            )
            return res.data or []
        except Exception as e:
            _e = str(e).lower()
            if "user_suggestion_feedback" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return []
            logger.warning("get_suggestion_feedback_by_session failed sid=%s: %s",
                           session_id, e)
            return []

    def count_training_labels(self) -> int:
        """Total direction labels across all sessions — corpus size for the
        learning status + the auto-retrain threshold. 0 on missing table."""
        try:
            res = (
                self.client.table("training_labels")
                .select("snippet_id", count="exact")
                .limit(1)
                .execute()
            )
            return int(getattr(res, "count", None) or 0)
        except Exception as e:
            if "training_labels" in str(e).lower():
                return 0
            logger.warning("count_training_labels failed err=%s", e)
            return 0

    # ── willab Phase 4 / Prompt 1 — shadow model registry ────────────────
    def insert_model_version(
        self, *, version: str, status: str = "shadow",
        schema_version: Optional[str] = None, corpus_size: Optional[int] = None,
        metrics: Optional[dict] = None, artifact_ref: Optional[str] = None,
    ) -> bool:
        """Register a trained (SHADOW) model. Best-effort; missing-table-safe."""
        try:
            self.client.table("model_versions").insert({
                "version": version,
                "status": status,
                "schema_version": schema_version,
                "corpus_size": corpus_size,
                "metrics": metrics,
                "artifact_ref": artifact_ref,
            }).execute()
            return True
        except Exception as e:
            if "model_versions" in str(e).lower():
                logger.warning(
                    "insert_model_version: table missing (run "
                    "migrations/add_learning_subsystem.sql)",
                )
                return False
            logger.warning("insert_model_version failed v=%s err=%s", version, e)
            return False

    def get_latest_model_version(self) -> Optional[dict]:
        """Newest registered model (any status), or None. Missing-table-safe."""
        try:
            res = (
                self.client.table("model_versions")
                .select("version, created_at, status, schema_version, "
                        "corpus_size, metrics, artifact_ref")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            if "model_versions" in str(e).lower():
                return None
            logger.warning("get_latest_model_version failed err=%s", e)
            return None

    def list_model_versions(self, *, limit: int = 50) -> list[dict]:
        """All registered models, newest first. [] on missing table."""
        try:
            res = (
                self.client.table("model_versions")
                .select("version, created_at, status, schema_version, "
                        "corpus_size, metrics")
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception as e:
            if "model_versions" in str(e).lower():
                return []
            logger.warning("list_model_versions failed err=%s", e)
            return []

    # ── willab Phase 4 / Prompt 1 — shadow prediction log (B3) ───────────
    def upsert_shadow_prediction(
        self, *, session_id: str, snippet_id: str, model_version: str,
        predicted_label: str, confidence: Optional[float] = None,
    ) -> bool:
        """Log one SHADOW prediction, deduped on (snippet_id, model_version).
        Never user/coach-facing. Best-effort; missing-table-safe."""
        try:
            existing = (
                self.client.table("shadow_predictions")
                .select("id")
                .eq("snippet_id", snippet_id)
                .eq("model_version", model_version)
                .limit(1)
                .execute()
            )
            if existing.data:
                return False
            self.client.table("shadow_predictions").insert({
                "session_id": session_id,
                "snippet_id": snippet_id,
                "model_version": model_version,
                "predicted_label": predicted_label,
                "confidence": confidence,
            }).execute()
            return True
        except Exception as e:
            if "shadow_predictions" in str(e).lower():
                return False
            logger.warning("upsert_shadow_prediction failed snip=%s: %s", snippet_id, e)
            return False

    def backfill_shadow_coach_actual(self, snippet_id: str, coach_actual_label: str) -> bool:
        """When the coach labels a snippet, fill coach_actual_label on its shadow
        rows (predicted-vs-actual closes the agreement loop). Best-effort."""
        try:
            (
                self.client.table("shadow_predictions")
                .update({"coach_actual_label": coach_actual_label})
                .eq("snippet_id", snippet_id)
                .is_("coach_actual_label", "null")
                .execute()
            )
            return True
        except Exception as e:
            if "shadow_predictions" in str(e).lower():
                return False
            logger.warning("backfill_shadow_coach_actual failed snip=%s: %s", snippet_id, e)
            return False

    def get_shadow_agreement(self) -> Optional[dict]:
        """{agreement_overall, by_class, sample_n} of predicted vs coach_actual.
        None when no labeled predictions yet. In-distribution (heuristic-selected,
        range-restricted) — the dashboard must label it as such."""
        try:
            res = (
                self.client.table("shadow_predictions")
                .select("predicted_label, coach_actual_label")
                .not_.is_("coach_actual_label", "null")
                .limit(5000)
                .execute()
            )
            rows = res.data or []
            if not rows:
                return None
            n = len(rows)
            agree = sum(1 for r in rows if r.get("predicted_label") == r.get("coach_actual_label"))
            by_class: dict = {}
            for r in rows:
                actual = r.get("coach_actual_label")
                hit, tot = by_class.get(actual, (0, 0))
                by_class[actual] = (hit + (1 if r.get("predicted_label") == actual else 0), tot + 1)
            return {
                "agreement_overall": round(agree / n, 4),
                "by_class": {k: round(h / t, 4) for k, (h, t) in by_class.items() if t},
                "sample_n": n,
                "note": "in-distribution (heuristic-selected); not a held-out estimate",
            }
        except Exception as e:
            if "shadow_predictions" in str(e).lower():
                return None
            logger.warning("get_shadow_agreement failed: %s", e)
            return None

    def delete_training_label(self, session_id: str, snippet_id: str) -> bool:
        """Clear one snippet's direction label (the coach unset it — the FE
        sends direction_label: null). Best-effort; missing table → False."""
        if not session_id or not snippet_id:
            return False
        try:
            (
                self.client.table("training_labels")
                .delete()
                .eq("session_id", session_id)
                .eq("snippet_id", snippet_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "training_labels" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return False
            logger.warning(
                "delete_training_label failed sid=%s snip=%s err=%s",
                session_id, snippet_id, e,
            )
            return False

    def delete_training_labels_for_session(self, session_id: str) -> int:
        """Delete ALL training labels for a session. Used by force re-cut
        (UX Wave 3 BE-6) — re-cut mints new snippet ids, so the old labels
        would be orphaned; on an explicit force we delete them rather than
        leave dead-snippet rows polluting the private-lane training signal.
        Returns the delete count; best-effort."""
        if not session_id:
            return 0
        try:
            res = (
                self.client.table("training_labels")
                .delete()
                .eq("session_id", session_id)
                .execute()
            )
            return len(res.data or [])
        except Exception as e:
            logger.warning(
                "delete_training_labels_for_session failed sid=%s err=%s",
                session_id, e,
            )
            return 0

    def delete_coach_snippet_drafts_for_session(self, session_id: str) -> int:
        """Delete ALL coach snippet drafts (note/tag/surfaced/when/examples)
        for a session. Companion to delete_training_labels_for_session for
        force re-cut. Returns the delete count; best-effort."""
        if not session_id:
            return 0
        try:
            res = (
                self.client.table("coach_snippet_drafts")
                .delete()
                .eq("session_id", session_id)
                .execute()
            )
            return len(res.data or [])
        except Exception as e:
            logger.warning(
                "delete_coach_snippet_drafts_for_session failed sid=%s err=%s",
                session_id, e,
            )
            return 0

    @staticmethod
    def fold_reads_out_of_queue(rows: list[dict]) -> list[dict]:
        """Founder 2026-07-16: a mid-take RE-READ is part of its parent take,
        never its own queue item — the coach packet folds its snippets in.
        Drops read rows (recording_kind='read' / paired_session_id set) and
        stamps has_reread=True on parents present in the same page. Pure
        (unit-tested directly); legacy rows without the columns pass through
        untouched."""
        parents_with_reads = {
            str(r.get("paired_session_id")) for r in rows
            if r.get("paired_session_id")
        }
        out = []
        for r in rows:
            if r.get("recording_kind") == "read" or r.get("paired_session_id"):
                continue
            if str(r.get("id")) in parents_with_reads:
                r = dict(r)
                r["has_reread"] = True
            out.append(r)
        return out

    def list_review_queue(self, *, limit: int = 100) -> list[dict]:
        """willab coach review queue (§3.8/§14): willab Lab sessions sent
        to the coach (status pending_admin_review, source audit_upload)
        and not yet published, newest-sent first. Returns raw rows; the
        route pseudonymizes user_id (§14 red-line 6 — never the real id in
        the list) + shapes the response. (results_published_at filtered in
        Python to avoid PostgREST is-null quirks.) Read rows are folded out
        (fold_reads_out_of_queue) — a re-read reviews INSIDE its parent
        take's packet, never as its own row.
        """
        _full_cols = (
            "id, user_id, intake_context, guest_claimed_at, "
            "created_at, results_published_at, "
            "recording_kind, paired_session_id, arc_id, take_index"
        )
        _base_cols = (
            "id, user_id, intake_context, guest_claimed_at, "
            "created_at, results_published_at"
        )
        try:
            try:
                res = (
                    self.client.table("v2_sessions")
                    .select(_full_cols)
                    .eq("status", "pending_admin_review")
                    .eq("source", "audit_upload")
                    .order("guest_claimed_at", desc=True)
                    .limit(limit)
                    .execute()
                )
                rows = res.data or []
            except Exception as _e_full:
                _low = str(_e_full).lower()
                # Fold/arc columns not migrated yet → the legacy select
                # (no read rows can exist without the columns either).
                if not any(c in _low for c in (
                        "recording_kind", "paired_session_id",
                        "arc_id", "take_index")):
                    raise
                res = (
                    self.client.table("v2_sessions")
                    .select(_base_cols)
                    .eq("status", "pending_admin_review")
                    .eq("source", "audit_upload")
                    .order("guest_claimed_at", desc=True)
                    .limit(limit)
                    .execute()
                )
                rows = res.data or []
            rows = [r for r in rows if not r.get("results_published_at")]
            return self.fold_reads_out_of_queue(rows)
        except Exception as e:
            err_low = str(e).lower()
            if "source" in err_low and "pgrst" in err_low:
                logger.warning(
                    "list_review_queue: source column missing (run "
                    "migrations/add_foundation_discriminators.sql)",
                )
                return []
            logger.warning("list_review_queue failed err=%s", e)
            return []

    # ── willab beta — strong-sides library (design §7, contract §3.11) ─

    def upsert_strong_sides_library(self, rows: list[dict]) -> int:
        """Idempotent batch upsert of library rows on (user_id,
        snippet_id). Returns the number of rows written. Best-effort:
        missing table (migration pending) → 0.

        Rows: {user_id, session_id, snippet_id, note, tag, snippet_ref}.
        """
        if not rows:
            return 0
        try:
            res = (
                self.client.table("strong_sides_library")
                .upsert(rows, on_conflict="user_id,snippet_id")
                .execute()
            )
            return len(res.data or [])
        except Exception as e:
            err_low = str(e).lower()
            if (
                "strong_sides_library" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                logger.warning(
                    "upsert_strong_sides_library: table missing (run "
                    "migrations/add_strong_sides_library_table.sql)",
                )
                return 0
            logger.error("upsert_strong_sides_library failed err=%s", e)
            return 0

    def get_strong_sides_library(
        self,
        user_id: str,
        *,
        tag: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        """Read a user's library (newest first), optionally filtered by
        tag. Used by the Lounge bot (retrieval) + the FE library view.
        Empty list on missing table / DB hiccup.
        """
        if not user_id:
            return []
        try:
            query = (
                self.client.table("strong_sides_library")
                .select("id, session_id, snippet_id, note, tag, "
                        "snippet_ref, created_at")
                .eq("user_id", user_id)
            )
            if tag is not None:
                query = query.eq("tag", tag)
            res = (
                query.order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if (
                "strong_sides_library" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                return []
            logger.warning(
                "get_strong_sides_library failed user=%s err=%s",
                user_id, e,
            )
            return []

    def delete_strong_sides_library_for_session(
        self, user_id: str, session_id: str
    ) -> int:
        """Delete all strong_sides_library rows for (user_id, session_id).
        Owner-scoped. Best-effort; returns rows deleted (0 on miss / missing
        table). Used by the user-facing presentation/take delete."""
        if not user_id or not session_id:
            return 0
        try:
            res = (
                self.client.table("strong_sides_library")
                .delete()
                .eq("user_id", user_id)
                .eq("session_id", session_id)
                .execute()
            )
            return len(res.data or [])
        except Exception as e:
            err_low = str(e).lower()
            if "strong_sides_library" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return 0
            logger.warning(
                "delete_strong_sides_library_for_session failed "
                "user=%s session=%s err=%s", user_id, session_id, e,
            )
            return 0

    # ── willab beta — insights_payload (design §6b/§14, contract §3.9) ─

    def set_session_insights_payload(
        self,
        session_id: str,
        payload: Optional[dict],
    ) -> bool:
        """Persist the coach user-facing lane on v2_sessions.insights_
        payload (JSONB). Called from the publish endpoint after the
        publish-contract validation (library floor) passes.

        USER lane only (split-sink §2) — never the private labels.
        Returns True on success; False (logged) on missing column
        (migration pending) or DB failure so the route can decide
        whether to hard-fail the publish.
        """
        if not session_id:
            return False
        try:
            (
                self.client.table("v2_sessions")
                .update({"insights_payload": payload})
                .eq("id", session_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "insights_payload" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "set_session_insights_payload: column missing (run "
                    "migrations/add_insights_payload_to_v2_sessions.sql) "
                    "sid=%s", session_id,
                )
                return False
            logger.error(
                "set_session_insights_payload failed sid=%s err=%s",
                session_id, e,
            )
            return False

    # ── willab beta — coach per-snippet DRAFT store (E1 / §B.3, USER lane) ─

    def upsert_coach_snippet_draft(
        self,
        session_id: str,
        snippet_id: str,
        fields: dict,
        updated_by: Optional[str] = None,
    ) -> Optional[dict]:
        """MERGE-upsert one coach per-snippet draft (note/tag/surfaced/
        when_context/examples) on (session_id, snippet_id).

        Only the keys present in ``fields`` change; the rest of the row is
        preserved (read-modify-write, so partial per-field saves accumulate —
        coach edits note now, tag later). E1 immediate-persist + resume.

        USER lane (split-sink §2): this is a DRAFT — the published artifact is
        assembled into v2_sessions.insights_payload at publish. Never the
        private label lane. Best-effort: missing table → None.
        """
        if not session_id or not snippet_id:
            return None
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            existing = (
                self.client.table("coach_snippet_drafts")
                .select("*")
                .eq("session_id", session_id)
                .eq("snippet_id", snippet_id)
                .limit(1)
                .execute()
            )
            base = (existing.data or [{}])[0] if getattr(existing, "data", None) else {}
            row = {
                "session_id": session_id,
                "snippet_id": snippet_id,
                "note": base.get("note"),
                "tag": base.get("tag"),
                # Default TRUE on first write (§1.A opt-out-surface, FE handoff
                # 2026-06-19): a snippet reaches the user by default; the coach
                # UN-surfaces the ones to hide (explicit surfaced=false persists
                # and is respected). Reverses the old opt-in-surface default.
                "surfaced": base.get("surfaced", True),
                "when_context": base.get("when_context"),
                "examples": base.get("examples") or [],
                "updated_by": updated_by,
                "updated_at": now_iso,
            }
            # breakthrough_video_ref / transcript_corrected are NOT re-asserted
            # from base — each is only written when the coach actually sets it
            # (merge loop below). A normal note/tag save never references either
            # column, and ON CONFLICT preserves whatever was already there —
            # keeps coach saves working even before their migrations run.
            # reference_post_slug (ticket 6, 2026-07-26) joins the same
            # write-only-when-set group: a blog post the COACH manually attaches
            # to this verified moment. Never re-asserted from base, so a normal
            # note/tag save leaves it alone and coach saves keep working before
            # its migration runs.
            for k in (
                "note", "tag", "surfaced", "when_context", "examples",
                "breakthrough_video_ref", "transcript_corrected",
                "reference_post_slug",
            ):
                if k in fields:
                    row[k] = fields[k]
            res = (
                self.client.table("coach_snippet_drafts")
                .upsert(row, on_conflict="session_id,snippet_id")
                .execute()
            )
            return (res.data or [None])[0] if getattr(res, "data", None) else row
        except Exception as e:
            err_low = str(e).lower()
            if "coach_snippet_drafts" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                logger.warning(
                    "upsert_coach_snippet_draft: table missing (run "
                    "migrations/add_coach_snippet_drafts_table.sql) sid=%s",
                    session_id,
                )
                return None
            logger.error(
                "upsert_coach_snippet_draft failed sid=%s snip=%s err=%s",
                session_id, snippet_id, e,
            )
            return None

    def get_coach_snippet_drafts(self, session_id: str) -> list[dict]:
        """All USER-lane per-snippet drafts for a session (resume read +
        publish assembly). Empty on missing table / DB hiccup."""
        if not session_id:
            return []
        try:
            # select(*) (not an explicit column list) so a not-yet-migrated
            # breakthrough_video_ref column never makes this read fail and wipe
            # the drafts (which would break resume + publish assembly). Consumers
            # read named keys via .get(), so extra columns are harmless.
            res = (
                self.client.table("coach_snippet_drafts")
                .select("*")
                .eq("session_id", session_id)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "coach_snippet_drafts" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return []
            logger.warning(
                "get_coach_snippet_drafts failed sid=%s err=%s", session_id, e,
            )
            return []

    def set_session_coach_video_ref(
        self,
        session_id: str,
        video_ref: Optional[str],
    ) -> bool:
        """Persist the coach feedback video URL on the session (B.3). Folded
        into insights_payload at publish so it ships to the user. Best-effort:
        missing column (migration pending) → False."""
        if not session_id:
            return False
        try:
            (
                self.client.table("v2_sessions")
                .update({"coach_video_ref": video_ref})
                .eq("id", session_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "coach_video_ref" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "set_session_coach_video_ref: column missing (run "
                    "migrations/add_coach_video_ref_to_v2_sessions.sql) sid=%s",
                    session_id,
                )
                return False
            logger.error(
                "set_session_coach_video_ref failed sid=%s err=%s",
                session_id, e,
            )
            return False

    def set_session_boundary_metrics(
        self,
        session_id: str,
        metrics: Optional[dict],
    ) -> bool:
        """Persist the F1 word→slide boundary measurement for a take
        (services.slide_boundary_metrics). INTERNAL/coach-side — exposure and
        impact of the pause-snap compensation, never surfaced to a user (AC-9).

        Best-effort: missing column (migration pending) → False, and the
        recording is unaffected. A measurement never blocks the live loop."""
        if not session_id:
            return False
        try:
            (
                self.client.table("v2_sessions")
                .update({"boundary_metrics": metrics})
                .eq("id", session_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "boundary_metrics" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "set_session_boundary_metrics: column missing "
                    "(run migrations/add_boundary_metrics.sql)")
            else:
                logger.warning(
                    "set_session_boundary_metrics failed sid=%s: %s",
                    session_id, e)
            return False

    def set_session_slide_transcripts(
        self,
        session_id: str,
        slide_transcripts: Optional[list],
    ) -> bool:
        """Persist the COMPLETE per-slide 1:1 transcript on the session (#A —
        bucketed from the whole-recording word list by the slide-click timeline).
        The take viewer reads this directly (complete + fast). Best-effort:
        missing column (migration pending) → False, recording unaffected."""
        if not session_id:
            return False
        try:
            (
                self.client.table("v2_sessions")
                .update({"slide_transcripts": slide_transcripts})
                .eq("id", session_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "slide_transcripts" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "set_session_slide_transcripts: column missing (run "
                    "migrations/add_slide_transcripts.sql) sid=%s", session_id,
                )
                return False
            logger.error(
                "set_session_slide_transcripts failed sid=%s err=%s",
                session_id, e,
            )
            return False

    def get_session_slide_transcripts(self, session_id: str) -> Optional[list]:
        """Read the persisted COMPLETE per-slide 1:1 transcript for a session
        (#A). Returns the list [{index, transcript, start_offset_ms,
        duration_ms}] or None when absent / missing column / error — the readout
        then falls back to its per-snippet rendering."""
        if not session_id:
            return None
        try:
            res = (
                self.client.table("v2_sessions")
                .select("slide_transcripts")
                .eq("id", session_id)
                .limit(1)
                .execute()
            )
            row = (res.data or [None])[0]
            st = row.get("slide_transcripts") if isinstance(row, dict) else None
            return st if isinstance(st, list) else None
        except Exception as e:
            err_low = str(e).lower()
            if "slide_transcripts" in err_low or "pgrst" in err_low:
                return None
            logger.warning("get_session_slide_transcripts failed sid=%s: %s",
                           session_id, e)
            return None

    # ── willab beta — user profile (design §2 / contract §3.1) ──────
    #
    # One-time self-declared {domain, goal} on user_settings (co-located
    # with the derived inferred_learner_profile / baseline_summary it
    # feeds). Distinct from v2_speaker_profiles (admin coach-notes).

    def get_user_profile(self, user_id: str) -> Optional[dict]:
        """Read the user's intake profile: {domain, goal, previous_goal,
        goal_changed_at}.

        Returns all-None pre-intake. ``previous_goal`` / ``goal_changed_at``
        carry the LAST goal change (Prompt A §6 C4 follow-up) so the coach
        surface can show "goal: NEW (was PREVIOUS)". None (the whole return)
        only on a hard DB failure, which the route treats as "no profile yet".
        """
        if not user_id:
            return None
        # Goal-change columns are a later migration; select them separately so
        # a pre-migration env still returns {domain, goal} (graceful degrade).
        try:
            res = (
                self.client.table("user_settings")
                .select("profile_domain, profile_goal, profile_goal_previous, "
                        "profile_goal_changed_at")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if not res.data:
                return {"domain": None, "goal": None,
                        "previous_goal": None, "goal_changed_at": None}
            row = res.data[0]
            return {
                "domain": row.get("profile_domain"),
                "goal": row.get("profile_goal"),
                "previous_goal": row.get("profile_goal_previous"),
                "goal_changed_at": row.get("profile_goal_changed_at"),
            }
        except Exception as e:
            err_low = str(e).lower()
            if "profile_goal_previous" in err_low or "profile_goal_changed_at" in err_low:
                # Change-tracking migration not yet run — fall back to the
                # base profile so the goal still surfaces.
                return self._get_user_profile_base(user_id)
            if "profile_domain" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "get_user_profile: column missing (run migrations/"
                    "add_profile_to_user_settings.sql) user=%s", user_id,
                )
                return {"domain": None, "goal": None,
                        "previous_goal": None, "goal_changed_at": None}
            logger.warning(
                "get_user_profile failed user=%s err=%s", user_id, e,
            )
            return None

    def _get_user_profile_base(self, user_id: str) -> Optional[dict]:
        """Pre-migration fallback — {domain, goal} only, change fields None."""
        try:
            res = (
                self.client.table("user_settings")
                .select("profile_domain, profile_goal")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            row = (res.data or [{}])[0]
            return {
                "domain": row.get("profile_domain"),
                "goal": row.get("profile_goal"),
                "previous_goal": None, "goal_changed_at": None,
            }
        except Exception as e:
            logger.warning("get_user_profile base read failed user=%s: %s",
                           user_id, e)
            return None

    def update_user_goal(
        self, user_id: str, new_goal: str, previous_goal: Optional[str],
    ) -> bool:
        """Goal-ONLY update from the chat intercept (Prompt A §6 C4). Records
        the prior goal + change time so the coach sees old→new. Partial upsert:
        preserves profile_domain (not in the payload). Best-effort; missing
        change-columns → falls back to a plain goal write (still succeeds)."""
        if not user_id or not new_goal:
            return False
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            "user_id": user_id,
            "profile_goal": new_goal,
            "profile_goal_previous": previous_goal,
            "profile_goal_changed_at": now_iso,
            "updated_at": now_iso,
        }
        try:
            self.client.table("user_settings").upsert(payload).execute()
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "profile_goal_previous" in err_low or "profile_goal_changed_at" in err_low:
                # Change-tracking migration not yet run — still persist the
                # goal so the update isn't lost (history just isn't tracked).
                try:
                    self.client.table("user_settings").upsert({
                        "user_id": user_id, "profile_goal": new_goal,
                        "updated_at": now_iso,
                    }).execute()
                    logger.warning(
                        "update_user_goal: change-cols missing (run migrations/"
                        "add_goal_change_tracking.sql) user=%s", user_id,
                    )
                    return True
                except Exception as e2:
                    logger.error("update_user_goal fallback failed user=%s: %s",
                                 user_id, e2)
                    return False
            logger.error("update_user_goal failed user=%s: %s", user_id, e)
            return False

    def set_user_profile(
        self,
        user_id: str,
        *,
        domain: Optional[str],
        goal: Optional[str],
    ) -> bool:
        """Upsert the user's intake profile on user_settings.

        Intake submits both fields together (design §2 — two-turn
        bounded), so this is a full set, not a partial patch. ``domain``
        is validated against the enum by the route layer; the DB CHECK
        constraint is the final gate. Returns True on success, False on
        any DB failure (route maps to 500).
        """
        if not user_id:
            return False
        from datetime import datetime, timezone
        payload = {
            "user_id": user_id,
            "profile_domain": domain,
            "profile_goal": goal,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            (
                self.client.table("user_settings")
                .upsert(payload)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "profile_domain" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "set_user_profile: column missing (run migrations/"
                    "add_profile_to_user_settings.sql) user=%s", user_id,
                )
                return False
            logger.error(
                "set_user_profile failed user=%s err=%s", user_id, e,
            )
            return False

    # ── speaker sex — the voice-confidence weight router ────────────
    #
    # user_settings.profile_sex (migrations/add_speaker_sex.sql). Read and
    # written on their OWN narrow queries rather than folded into
    # get/set_user_profile, for two reasons: the record path wants this one
    # value and nothing else on a hot code path, and a sex-only write must
    # never clobber profile_domain / profile_goal.
    #
    # Both degrade to "no answer on file" (None / False) when the migration
    # hasn't run — the composite then uses sex-blind weights, which is its
    # shipped v1 behaviour, so a pre-migration env is merely un-improved,
    # never broken.

    def get_user_speaker_sex(self, user_id: str) -> Optional[str]:
        """The user's self-declared sex: 'female' | 'male' |
        'prefer_not_to_say' | None (never asked). None on any failure —
        callers must not distinguish "no answer" from "lookup broke" by
        guessing; services/voice_confidence.py handles that explicitly."""
        if not user_id:
            return None
        try:
            res = (
                self.client.table("user_settings")
                .select("profile_sex")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if not res.data:
                return None
            return res.data[0].get("profile_sex")
        except Exception as e:
            err_low = str(e).lower()
            if "profile_sex" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "get_user_speaker_sex: column missing (run migrations/"
                    "add_speaker_sex.sql) user=%s", user_id,
                )
                return None
            logger.warning(
                "get_user_speaker_sex failed user=%s err=%s", user_id, e,
            )
            return None

    def set_user_speaker_sex(self, user_id: str, sex: Optional[str]) -> bool:
        """PARTIAL upsert of user_settings.profile_sex — deliberately does not
        carry profile_domain / profile_goal, so answering this question at
        signup cannot wipe an intake that was filled in later (or earlier).
        The route layer validates the enum; the DB CHECK is the final gate.
        Returns False on any DB failure."""
        if not user_id:
            return False
        from datetime import datetime, timezone
        payload = {
            "user_id": user_id,
            "profile_sex": sex,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.client.table("user_settings").upsert(payload).execute()
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "profile_sex" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "set_user_speaker_sex: column missing (run migrations/"
                    "add_speaker_sex.sql) user=%s", user_id,
                )
                return False
            logger.error(
                "set_user_speaker_sex failed user=%s err=%s", user_id, e,
            )
            return False

    # ── willab beta — lounge_messages (BE contract §3.15) ───────────
    #
    # Per-user Lounge chat thread. Text only, never audio, never in the
    # coach packet, never profiled. FE-append (incl. bot turns);
    # idempotent on (user_id, client_id); client_created_at is the
    # ordering key surviving the unsigned→signed merge.
    # See services/lounge_messages.py for validation + page shaping.

    def get_lounge_messages_page(
        self,
        user_id: str,
        *,
        limit: int,
        before: Optional[str] = None,
    ) -> list[dict]:
        """Fetch newest-first (DESC) rows for the thread, up to
        ``limit + 1`` so the caller can detect older pages.

        Returns the raw row list in DESC order; the route layer calls
        services.lounge_messages.shape_lounge_page to reverse to ASC +
        compute has_more + oldest_cursor.

        ``before`` (ISO-8601) pages older: rows strictly older than the
        cursor. Absent → the latest page (bottom of thread).

        Empty list on missing table (migration pending) / DB hiccup —
        the Lounge degrades to an empty thread rather than erroring.
        """
        if not user_id:
            return []
        try:
            query = (
                self.client.table("lounge_messages")
                .select(
                    "id, client_id, role, kind, body, metadata, "
                    "client_created_at"
                )
                .eq("user_id", user_id)
            )
            if before:
                query = query.lt("client_created_at", before)
            # +1 to detect whether an older page exists.
            res = (
                query.order("client_created_at", desc=True)
                .limit(limit + 1)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if (
                "lounge_messages" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                logger.warning(
                    "get_lounge_messages_page: table missing (run "
                    "migrations/add_lounge_messages_table.sql) user=%s",
                    user_id,
                )
                return []
            logger.warning(
                "get_lounge_messages_page failed user=%s err=%s",
                user_id, e,
            )
            return []

    def insert_lounge_messages(
        self,
        user_id: str,
        messages: list[dict],
    ) -> list[dict]:
        """Idempotent batch append/merge of Lounge messages.

        Upserts on the (user_id, client_id) unique key — re-sending a
        stored client_id is a no-op, not a duplicate (covers append
        retry, double-tap, and double-merge-on-resignup). The same
        path serves both per-turn appends and the merge-on-signup
        replay (BE contract §3.5/§3.15, §7.8 — no separate /merge
        alias).

        ``messages`` are pre-validated rows from
        services.lounge_messages.validate_lounge_batch (each carries
        client_id, role, kind, body, metadata, client_created_at).
        BE stamps user_id here — the FE never sets it.

        Returns the persisted rows (with server id) or [] on failure.
        """
        if not user_id or not messages:
            return []
        rows = [
            {
                "user_id":           user_id,
                "client_id":         m["client_id"],
                "role":              m["role"],
                "kind":              m["kind"],
                "body":              m.get("body") or "",
                "metadata":          m.get("metadata"),
                "client_created_at": m["client_created_at"],
            }
            for m in messages
        ]
        try:
            res = (
                self.client.table("lounge_messages")
                .upsert(rows, on_conflict="user_id,client_id")
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if (
                "lounge_messages" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                logger.warning(
                    "insert_lounge_messages: table missing (run "
                    "migrations/add_lounge_messages_table.sql) user=%s",
                    user_id,
                )
                return []
            logger.error(
                "insert_lounge_messages failed user=%s count=%d err=%s",
                user_id, len(rows), e,
            )
            return []

    def delete_lounge_messages_for_user(self, user_id: str) -> bool:
        """Delete the entire Lounge thread for a user (BE contract
        §3.14 — user-deletable privacy commitment). Account deletion
        is covered separately by the ON DELETE CASCADE FK; this is the
        explicit user-initiated 'clear my Lounge' path.
        """
        if not user_id:
            return False
        try:
            (
                self.client.table("lounge_messages")
                .delete()
                .eq("user_id", user_id)
                .execute()
            )
            return True
        except Exception as e:
            logger.warning(
                "delete_lounge_messages_for_user failed user=%s err=%s",
                user_id, e,
            )
            return False

    def set_session_drift_flag(
        self,
        *,
        session_id: str,
        needs_review: bool,
        diagnostic: Optional[dict],
    ) -> Optional[dict]:
        """Phase 17.1 — persist the Phase 17 drift-guard verdict.

        Writes both columns atomically so admin surfaces never see a
        flag without the explanation, or vice versa. ``diagnostic``
        is the dict returned by detect_classifier_drift.

        Idempotent — when drift resolves on a re-run (admin re-
        extracted a snippet with better metrics, say) pass
        ``needs_review=False`` and the new diagnostic; the row flips
        back. Failure logs + returns None so the metrics compute
        path can keep going.
        """
        try:
            result = (
                self.client.table("v2_sessions")
                .update({
                    "needs_admin_review": bool(needs_review),
                    "drift_diagnostic": diagnostic,
                })
                .eq("id", session_id)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning(
                "set_session_drift_flag failed session=%s err=%s",
                session_id, e,
            )
            return None

    def update_session_stickiness(
        self,
        *,
        session_id: str,
        top_topic: Optional[str],
        score: Optional[float],
        distribution: Optional[dict],
    ) -> Optional[dict]:
        """Persist the Phase 11 stickiness-topic metric onto v2_sessions.

        Pass all three values as None to clear (e.g. after a re-extract
        produced no topics). The ``computed_at`` timestamp is always
        written so admins can see "ran but found nothing" vs "never ran".
        """
        try:
            result = (
                self.client.table("v2_sessions")
                .update({
                    "stickiness_top_topic": top_topic,
                    "stickiness_score": score,
                    "stickiness_topic_distribution": distribution,
                    "stickiness_computed_at": (
                        datetime.now(timezone.utc).isoformat()
                    ),
                })
                .eq("id", session_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.warning(
                "update_session_stickiness failed session=%s err=%s",
                session_id, e,
            )
            return None

    # ------------------------------------------------------------------
    # User settings (LLM instructions)
    # ------------------------------------------------------------------

    def get_session_intake_context(
        self,
        session_id: str,
    ) -> Optional[dict]:
        """Read v2_sessions.intake_context JSONB for a session.

        Task 9 — per-session speech-context intake block:
            { topic, audience, target_length_seconds }

        Returns the parsed dict (may contain nulls inside), or None
        when the column is unset / row not found / DB hiccup.
        ``None`` means "use defaults" downstream — same pre-task-9
        behavior. Owner-scope is enforced by the caller (route
        handler), not here.
        """
        if not session_id:
            return None
        try:
            result = (
                self.client.table("v2_sessions")
                .select("intake_context")
                .eq("id", session_id)
                .limit(1)
                .execute()
            )
            if not result.data:
                return None
            ctx = result.data[0].get("intake_context")
            return ctx if isinstance(ctx, dict) else None
        except Exception as e:
            err_low = str(e).lower()
            if "intake_context" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "get_session_intake_context: column missing "
                    "(run migrations/add_intake_context_to_v2_"
                    "sessions.sql) sid=%s", session_id,
                )
                return None
            logger.warning(
                "get_session_intake_context failed sid=%s err=%s",
                session_id, e,
            )
            return None

    def set_session_intake_context(
        self,
        session_id: str,
        intake_context: Optional[dict],
    ) -> bool:
        """Full-replace write of v2_sessions.intake_context.

        Task 9 — FE owns the draft and PUTs the whole 3-field form
        on submit; partial updates are out of scope. Pass None to
        clear the column back to NULL (rare, but supported so an
        admin tool can wipe stale intake data without a SQL hop).

        Returns True on success, False on any failure path
        (caller maps to 500). Best-effort logging matches the
        rest of the v2_sessions helpers.
        """
        if not session_id:
            return False
        try:
            (
                self.client.table("v2_sessions")
                .update({"intake_context": intake_context})
                .eq("id", session_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "intake_context" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "set_session_intake_context: column missing "
                    "(run migrations/add_intake_context_to_v2_"
                    "sessions.sql) sid=%s", session_id,
                )
                return False
            logger.error(
                "set_session_intake_context failed sid=%s err=%s",
                session_id, e,
            )
            return False

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

    # ── Chat-surface consent flags (Phase Single-Slot-Chat) ────────
    #
    # Four nullable boolean columns on user_settings powering
    # GET / PUT /v2/user/sharing-consent. NULL = not yet answered
    # (FE shows the prompt for that slot). TRUE/FALSE = answered.
    # Distinct from the user_consents GDPR audit ledger; that one
    # is immutable and written once at signup.

    _CONSENT_FIELDS = (
        "mic_consent",
        "share_consent",
        "email_consent",
        "terms_consent",
    )

    def get_consent_state(self, user_id: str) -> dict:
        """Returns the four-flag consent state for ``user_id``.

        Shape::
            {
              "mic_consent":   bool | None,
              "share_consent": bool | None,
              "email_consent": bool | None,
              "terms_consent": bool | None,
            }

        Returns all-None when the user has no user_settings row yet
        OR the consent columns haven't been migrated yet (silent
        degradation so pre-migration deploys don't 500). The route
        handler computes ``has_answered`` from these.
        """
        settings = self.get_user_settings(user_id) or {}
        out: dict = {}
        for field in self._CONSENT_FIELDS:
            val = settings.get(field)
            # Defensive: anything other than True/False/None is treated
            # as "not answered". Supabase JSON decode can occasionally
            # surface odd types; we'd rather show the prompt than
            # block on a malformed cell.
            if isinstance(val, bool):
                out[field] = val
            else:
                out[field] = None
        return out

    def upsert_consent_fields(
        self,
        user_id: str,
        patch: dict,
    ) -> Optional[dict]:
        """Partial upsert of the four consent flags. ``patch`` may
        contain any subset of mic_consent / share_consent /
        email_consent / terms_consent; missing keys are NOT touched.

        Returns the post-write consent state (same shape as
        ``get_consent_state``) on success, None on failure.

        Silently no-ops + warns when the columns are missing
        (pre-migration env). Matches the pattern used by
        ``insert_casual_voice_benchmark`` and others.
        """
        payload: dict = {
            "user_id": user_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        for field in self._CONSENT_FIELDS:
            if field in patch:
                val = patch[field]
                if val is not None and not isinstance(val, bool):
                    # Caller passed a non-bool / non-None — reject
                    # at this layer rather than silently coercing.
                    logger.warning(
                        "upsert_consent_fields: %s must be bool or "
                        "None, got %r — skipping that field",
                        field, type(val).__name__,
                    )
                    continue
                payload[field] = val
        if len(payload) <= 2:
            # Caller asked to update nothing — return current state.
            return self.get_consent_state(user_id)

        try:
            (
                self.client.table("user_settings")
                .upsert(payload)
                .execute()
            )
        except Exception as e:
            err_low = str(e).lower()
            if any(
                f in err_low for f in self._CONSENT_FIELDS
            ) and ("does not exist" in err_low or "pgrst204" in err_low):
                logger.warning(
                    "upsert_consent_fields: consent columns missing "
                    "(migration pending?) user=%s — skipping write",
                    user_id,
                )
                return self.get_consent_state(user_id)
            logger.warning(
                "upsert_consent_fields failed user=%s err=%s",
                user_id, e,
            )
            return None

        return self.get_consent_state(user_id)

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

    def upsert_admin_user_context_fields(
        self,
        *,
        user_id: str,
        custom_llm_instructions: Optional[str] = None,
        private_admin_notes: Optional[str] = None,
        coach_override_profile: Optional[str] = None,
        update_instructions: bool = False,
        update_notes: bool = False,
        update_override_profile: bool = False,
    ) -> Optional[dict]:
        """Partial upsert of admin-editable user context fields.

        Phase 12 — backs the PUT /v2/admin/user/<id>/context endpoint.
        Each ``update_*`` flag controls whether the matching value is
        included in the upsert payload, so the caller can update one
        card on the admin view without overwriting the others.

        Note: ``coach_override_profile`` lives on user_sniper_profile
        (the Phase 9 admin learner-type override), not user_settings.
        We persist it via the existing student-profile path so the
        precedence rule in _augment_coaching_system_prompt keeps
        working unchanged.

        Legacy ``queued_override_question`` parameter was removed in
        the Week-1 cleanup. The admin override path is now
        coaching_directives_queue (POST /v2/admin/users/<id>/
        directives-queue). Old data in the user_settings column
        persists in the DB but is no longer read or written here.

        Returns the updated user_settings row, or None on failure.
        """
        # ── user_settings side ────────────────────────────────────
        payload: dict[str, Any] = {
            "user_id": user_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if update_instructions:
            payload["custom_llm_instructions"] = custom_llm_instructions
        if update_notes:
            payload["private_admin_notes"] = private_admin_notes

        updated_row = None
        if len(payload) > 2:  # more than just user_id + updated_at
            try:
                result = (
                    self.client.table("user_settings")
                    .upsert(payload)
                    .execute()
                )
                if result.data:
                    updated_row = result.data[0]
            except Exception as e:
                logger.warning(
                    "upsert_admin_user_context_fields settings failed "
                    "user=%s err=%s", user_id, e,
                )
                return None
        else:
            # Caller didn't ask to update anything on user_settings;
            # we still want to return the current row.
            updated_row = self.get_user_settings(user_id)

        # ── user_sniper_profile side (coach_override_profile) ─────
        if update_override_profile:
            try:
                # The override column lives on user_sniper_profile (per
                # the precedence rule in routes/v2_routes.py::
                # _augment_coaching_system_prompt). Upsert keyed on
                # user_id; we only touch the override column so the
                # rest of the profile (behavioral_profile, etc.) stays
                # intact.
                self.client.table("user_sniper_profile").upsert({
                    "user_id": user_id,
                    "coach_override_profile": coach_override_profile,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).execute()
            except Exception as e:
                logger.warning(
                    "upsert_admin_user_context_fields override failed "
                    "user=%s err=%s", user_id, e,
                )

        return updated_row

    def get_email_pref_publish_results(self, user_id: str) -> bool:
        """Phase 14 — is this user subscribed to the publish-results
        email? Defaults to TRUE on any error or missing row so a DB
        hiccup never accidentally drops emails to subscribed users.
        """
        if not user_id:
            return True
        try:
            result = (
                self.client.table("user_settings")
                .select("email_pref_publish_results")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if result.data:
                val = result.data[0].get("email_pref_publish_results")
                # Treat NULL as TRUE — schema default is TRUE; only an
                # explicit FALSE skips the send.
                return False if val is False else True
            return True
        except Exception as e:
            logger.warning(
                "get_email_pref_publish_results failed user=%s err=%s",
                user_id, e,
            )
            return True

    def set_email_pref_publish_results(
        self,
        *,
        user_id: str,
        subscribed: bool,
        source: str | None = None,
    ) -> bool:
        """Phase 14 — flip the publish-results email preference.

        When ``subscribed`` is False we also stamp ``unsubscribed_at``
        + ``unsubscribed_source`` for audit. Going back to True
        clears those fields so the audit trail reflects only the
        current opt-out state.

        Upsert so users without a settings row still record their
        opt-out (the row defaults the other settings columns to
        their schema defaults).

        Returns True on success.
        """
        if not user_id:
            return False
        try:
            now = datetime.now(timezone.utc).isoformat()
            payload: dict[str, Any] = {
                "user_id": user_id,
                "email_pref_publish_results": bool(subscribed),
                "updated_at": now,
            }
            if subscribed:
                payload["unsubscribed_at"] = None
                payload["unsubscribed_source"] = None
            else:
                payload["unsubscribed_at"] = now
                payload["unsubscribed_source"] = source or "unknown"
            (
                self.client.table("user_settings")
                .upsert(payload)
                .execute()
            )
            return True
        except Exception as e:
            logger.warning(
                "set_email_pref_publish_results failed user=%s err=%s",
                user_id, e,
            )
            return False

    def get_baseline_established(self, user_id: str) -> bool:
        """Phase 13 — has this user completed the EBCP baseline once?

        Defaults to False on any error or missing row so an
        infrastructure hiccup never accidentally bypasses the
        scripted opener.
        """
        if not user_id:
            return False
        try:
            result = (
                self.client.table("user_settings")
                .select("baseline_established")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if result.data:
                return bool(result.data[0].get("baseline_established"))
            return False
        except Exception as e:
            logger.warning(
                "get_baseline_established failed user=%s err=%s",
                user_id, e,
            )
            return False

    def mark_baseline_established(self, user_id: str) -> bool:
        """Phase 13 — flip the flag TRUE the first time a user
        graduates from the scripted EBCP turns (1-4) into the LLM
        regime. Upsert so the row exists even for users who never
        edited any other setting. Returns True on success.
        """
        if not user_id:
            return False
        try:
            (
                self.client.table("user_settings")
                .upsert({
                    "user_id": user_id,
                    "baseline_established": True,
                    "baseline_established_at": (
                        datetime.now(timezone.utc).isoformat()
                    ),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .execute()
            )
            return True
        except Exception as e:
            logger.warning(
                "mark_baseline_established failed user=%s err=%s",
                user_id, e,
            )
            return False

    def reset_baseline_established(self, user_id: str) -> bool:
        """Phase 13 — admin reset path. Flips ``baseline_established``
        back to FALSE so the user runs the scripted EBCP opener again
        on their next session. Clears ``baseline_established_at`` too
        for audit clarity ("when was the most recent graduation?").

        Phase 16: also clears any cached ``baseline_summary`` so the
        re-run produces a fresh digest. Otherwise an admin-triggered
        re-baseline would silently use the OLD summary on the new
        EBCP graduation — masking exactly the freshness an admin
        wanted.

        Upsert (not update) so this works on users who don't have a
        user_settings row yet — they just get a fresh row with FALSE,
        which is the schema default anyway.

        Returns True on success. Failure logs + returns False so the
        admin route can surface a proper error.
        """
        if not user_id:
            return False
        try:
            (
                self.client.table("user_settings")
                .upsert({
                    "user_id": user_id,
                    "baseline_established": False,
                    "baseline_established_at": None,
                    "baseline_summary": None,
                    "baseline_summary_computed_at": None,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .execute()
            )
            return True
        except Exception as e:
            logger.warning(
                "reset_baseline_established failed user=%s err=%s",
                user_id, e,
            )
            return False

    def get_user_baseline_summary(self, user_id: str) -> Optional[dict]:
        """Phase 16 — read the cached baseline_summary blob.

        Returns None when:
          - user_id missing,
          - no user_settings row yet,
          - column is NULL (user hasn't reached turn 5 yet),
          - any Supabase error.
        Caller falls through to raw previous_turns in those cases.
        """
        if not user_id:
            return None
        try:
            result = (
                self.client.table("user_settings")
                .select("baseline_summary")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0].get("baseline_summary") or None
            return None
        except Exception as e:
            logger.warning(
                "get_user_baseline_summary failed user=%s err=%s",
                user_id, e,
            )
            return None

    def set_user_baseline_summary(
        self,
        user_id: str,
        summary: Optional[dict],
    ) -> bool:
        """Phase 16 — persist the LLM-generated baseline digest.

        Upserts user_settings row + stamps baseline_summary_
        computed_at. Pass summary=None to clear (admin reset path
        uses reset_baseline_established, not this).

        Returns True on success.
        """
        if not user_id:
            return False
        try:
            now = datetime.now(timezone.utc).isoformat()
            (
                self.client.table("user_settings")
                .upsert({
                    "user_id": user_id,
                    "baseline_summary": summary,
                    "baseline_summary_computed_at": now if summary else None,
                    "updated_at": now,
                })
                .execute()
            )
            return True
        except Exception as e:
            logger.warning(
                "set_user_baseline_summary failed user=%s err=%s",
                user_id, e,
            )
            return False

    def list_sessions_for_user_admin(self, user_id: str) -> List[dict]:
        """All v2_sessions rows for ``user_id``, newest first.

        Phase 12 — backs the multi-session admin user view. No limit
        — the admin needs the full longitudinal history. Returns []
        on any error so the endpoint still renders.
        """
        try:
            return (
                self.client.table("v2_sessions")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .execute()
                .data
            ) or []
        except Exception as e:
            logger.warning(
                "list_sessions_for_user_admin failed user=%s err=%s",
                user_id, e,
            )
            return []

    def list_snippets_for_sessions(
        self,
        session_ids: List[str],
    ) -> dict[str, List[dict]]:
        """Bulk load charisma_snippets grouped by session_id.

        Phase 12 — replaces N per-session queries with one IN-list
        query. Returns ``{session_id: [snippet, ...]}``. Sessions
        with no snippets are NOT included as empty entries; callers
        should default to [] when looking up a missing key.
        """
        if not session_ids:
            return {}
        try:
            rows = (
                self.client.table(SNIPPETS_TABLE)
                .select("*")
                .in_("session_id", session_ids)
                .order("turn_number", desc=False)
                .order("start_offset_ms", desc=False)
                .execute()
                .data
            ) or []
        except Exception as e:
            logger.warning(
                "list_snippets_for_sessions failed err=%s", e,
            )
            return {}

        grouped: dict[str, List[dict]] = {}
        for r in rows:
            sid = r.get("session_id")
            if not sid:
                continue
            grouped.setdefault(str(sid), []).append(r)
        return grouped

    # ``consume_queued_override_question`` was removed in the Week-1
    # cleanup. The admin override path is now
    # coaching_directives_queue (see db.pop_next_directive). The
    # legacy ``user_settings.queued_override_question`` column
    # persists in the DB for forensic safety but is neither read
    # nor written by application code.

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
                self.client.table(SNIPPETS_TABLE)
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

    def update_turn_question_text(self, turn_id: str, text: str) -> Optional[dict]:
        """Update the question_text on a charisma_snippets row (admin HITL edit).

        A "turn" is a charisma_snippet row — each interview answer audio chunk
        stores the question asked in that turn as `question_text`.

        Returns the updated row, or None if not found.
        """
        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
                .update({
                    "question_text": text,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", turn_id)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error("update_turn_question_text failed for turn_id=%s: %s", turn_id, e)
            return None

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

    # ------------------------------------------------------------------
    # Legal + runtime consent
    # ------------------------------------------------------------------

    def get_user_consent_state(
        self,
        user_id: str,
        *,
        current_terms_version: str,
    ) -> dict:
        """Compose the unified consent payload for /v2/user/consent.

        Reads three runtime preferences off user_settings (mic, share,
        email) AND the immutable user_consents ledger to derive a
        terms_consent flag against ``current_terms_version``.

        Returns a shape-complete dict — every field is always present
        so the route handler doesn't need to special-case missing
        rows. NULL preferences mean "user has never been asked"; the
        frontend uses NULL to decide whether to surface the prompt.

        Response shape::

            {
              "has_answered":            bool,
              "mic_consent":             True | False | None,
              "mic_consent_set_at":      "ISO8601" | None,
              "share_consent":           True | False | None,
              "share_consent_set_at":    "ISO8601" | None,
              "email_consent":           True | False | None,
              "email_consent_set_at":    "ISO8601" | None,
              "terms_consent":           True | False,
              "terms_version_current":   "1.0",
              "terms_version_accepted":  "1.0" | None,
              "terms_accepted_at":       "ISO8601" | None,
            }

        has_answered is True iff ANY of (mic / share / email is non-
        NULL) OR the user has a user_consents row at the current
        terms_version. Frontend reads this to skip the "ask anything"
        moment for users who have already engaged with consent.
        """
        settings = self.get_user_settings(user_id) or {}

        # Resolve the terms ledger lookup. Cheap (indexed on user_id +
        # terms_version, unique pair). On any error: default to
        # terms_consent=False so we under-claim acceptance rather than
        # over-claim — the frontend simply re-prompts.
        terms_row: Optional[dict] = None
        try:
            result = (
                self.client.table("user_consents")
                .select("terms_version, terms_accepted_at")
                .eq("user_id", user_id)
                .eq("terms_version", current_terms_version)
                .limit(1)
                .execute()
            )
            if result.data:
                terms_row = result.data[0]
        except Exception as e:
            logger.warning(
                "get_user_consent_state: terms lookup failed "
                "user=%s err=%s — defaulting terms_consent=False",
                user_id, e,
            )

        mic = settings.get("mic_consent_preference")
        share = settings.get("share_consent_preference")
        email = settings.get("email_consent_preference")
        terms_consent = bool(terms_row)

        has_answered = (
            mic is not None
            or share is not None
            or email is not None
            or terms_consent
        )

        return {
            "has_answered": has_answered,
            "mic_consent": mic,
            "mic_consent_set_at": settings.get("mic_consent_set_at"),
            "share_consent": share,
            "share_consent_set_at": settings.get("share_consent_set_at"),
            "email_consent": email,
            "email_consent_set_at": settings.get("email_consent_set_at"),
            "terms_consent": terms_consent,
            "terms_version_current": current_terms_version,
            "terms_version_accepted": (
                terms_row.get("terms_version") if terms_row else None
            ),
            "terms_accepted_at": (
                terms_row.get("terms_accepted_at") if terms_row else None
            ),
        }

    def set_user_consent_preferences(
        self,
        user_id: str,
        *,
        mic: Optional[bool] = None,
        share: Optional[bool] = None,
        email: Optional[bool] = None,
        update_mic: bool = False,
        update_share: bool = False,
        update_email: bool = False,
    ) -> bool:
        """Upsert the runtime consent preferences on user_settings.

        Only the flags whose ``update_*`` companion is True are
        written. This matches the existing partial-update convention
        used by upsert_admin_user_context_fields and lets the route
        send PATCH-style payloads (only included keys are written).

        Each ``update_*=True`` write also stamps the corresponding
        *_set_at column to NOW so the UI can show "you opted in on
        <date>". Setting a preference to None when update_*=True is
        a valid "clear" (the column goes back to NULL, set_at also
        cleared, the frontend re-prompts).

        Returns True on success, False on any DB error. The route
        handler maps False to 500 so the user retries rather than
        seeing a misleading 200.
        """
        if not (update_mic or update_share or update_email):
            # Nothing to write — caller sent an empty payload.
            return True

        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()

        payload: dict[str, Any] = {
            "user_id": user_id,
            "updated_at": now_iso,
        }
        if update_mic:
            payload["mic_consent_preference"] = mic
            payload["mic_consent_set_at"] = now_iso if mic is not None else None
        if update_share:
            payload["share_consent_preference"] = share
            payload["share_consent_set_at"] = now_iso if share is not None else None
        if update_email:
            payload["email_consent_preference"] = email
            payload["email_consent_set_at"] = now_iso if email is not None else None

        try:
            (
                self.client.table("user_settings")
                .upsert(payload)
                .execute()
            )
            return True
        except Exception as e:
            logger.error(
                "set_user_consent_preferences failed user=%s err=%s",
                user_id, e,
            )
            return False

    def record_user_consent(
        self,
        user_id: str,
        terms_version: str = "1.0",
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> dict | None:
        """Insert a consent record into user_consents.

        Uses upsert with on-conflict-do-nothing so that calling this twice
        for the same (user_id, terms_version) pair is safe and idempotent —
        the original timestamp is preserved.

        Returns the stored row dict, or None on failure (non-fatal: the
        Supabase user has already been created by the time this is called,
        so a logging failure must not block registration).
        """
        try:
            from datetime import timezone, datetime
            now_utc = datetime.now(timezone.utc).isoformat()
            row = {
                "user_id": user_id,
                "terms_version": terms_version,
                "terms_accepted_at": now_utc,
                "ip_address": ip_address,
                "user_agent": user_agent,
            }
            result = (
                self.client.table("user_consents")
                .upsert(row, on_conflict="user_id,terms_version", ignore_duplicates=True)
                .execute()
            )
            return result.data[0] if result.data else row
        except Exception as e:
            logger.error(f"record_user_consent failed for user_id={user_id}: {e}")
            return None

    def insert_user_consent_event(
        self,
        *,
        user_id: str,
        consent_type: str,
        consent_value: Optional[bool],
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Optional[dict]:
        """Append a row to the per-flip consent audit ledger.

        Companion to ``record_user_consent`` — that one is the
        single-row-per-(user, terms_version) TOS acceptance record;
        this one is the append-only event log of every per-toggle
        consent change (mic_consent / share_consent / email_consent
        / terms_consent).

        Called from POST /v2/user/sharing-consent for EACH field
        that the body actually patched. Migration:
        migrations/add_user_consent_events_table.sql.

        Failure-tolerant — a ledger-write failure does NOT unwind
        the user-facing PUT (the preference column is already
        updated and we don't want the admin to retry a successful
        consent change). Logs the failure so we can spot it in
        Sentry; returns None.

        Graceful fallback when the table doesn't exist yet
        (migration pending): the post-rollout PGRST204 is
        downgraded to a warning so the consent PUT keeps working
        during the deploy window.
        """
        if not user_id or not consent_type:
            return None
        try:
            from datetime import timezone, datetime
            now_utc = datetime.now(timezone.utc).isoformat()
            row = {
                "user_id": user_id,
                "consent_type": consent_type,
                "consent_value": consent_value,
                "set_at": now_utc,
                "ip_address": ip_address,
                "user_agent": user_agent,
            }
            result = (
                self.client.table("user_consent_events")
                .insert(row)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            err_low = str(e).lower()
            if (
                "user_consent_events" in err_low
                or "pgrst204" in err_low
            ):
                logger.warning(
                    "insert_user_consent_event: table missing "
                    "(run migrations/add_user_consent_events_"
                    "table.sql) user=%s type=%s",
                    user_id, consent_type,
                )
                return None
            logger.error(
                "insert_user_consent_event failed user=%s type=%s "
                "err=%s",
                user_id, consent_type, e,
            )
            return None

    # ── Read alignment (F1 handoff §3, 2026-08-03) ────────────────────
    def upsert_read_alignment(self, session_id: str, fields: dict) -> bool:
        """Persist one read's force-alignment result (aligned transcript,
        per-word timings, script deviations). One row per read session."""
        if not session_id or not isinstance(fields, dict):
            return False
        try:
            self.client.table("read_alignments").upsert({
                "session_id": str(session_id),
                **fields,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="session_id").execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "read_alignments" in _e and ("does not exist" in _e
                                            or "pgrst" in _e):
                logger.warning(
                    "upsert_read_alignment: table missing (run "
                    "migrations/add_read_alignments.sql)")
                return False
            logger.warning("upsert_read_alignment failed sid=%s: %s",
                           session_id, e)
            return False

    def get_read_alignment(self, session_id: Optional[str]) -> Optional[dict]:
        if not session_id:
            return None
        try:
            res = (self.client.table("read_alignments").select("*")
                   .eq("session_id", str(session_id)).limit(1).execute())
            return (res.data or [None])[0]
        except Exception:
            return None

    # ── Reflection Game (F2 handoff §1, 2026-08-03) ───────────────────
    def get_shadow_challenge_snippet_ids(self, snippet_ids) -> set:
        """Snippet ids the SHADOW model flagged 'challenge' — the game's
        clip source. Internal only: never serialize this membership."""
        ids = [str(x) for x in (snippet_ids or []) if x]
        if not ids:
            return set()
        try:
            res = (self.client.table("shadow_predictions")
                   .select("snippet_id")
                   .in_("snippet_id", ids)
                   .eq("predicted_label", "challenge").execute())
            return {str(r.get("snippet_id")) for r in (res.data or [])
                    if r.get("snippet_id")}
        except Exception as e:
            logger.warning("get_shadow_challenge_snippet_ids failed: %s", e)
            return set()

    def list_reflection_clips(self, user_id: Optional[str]) -> list:
        """Every clip of one user, oldest first — the stable all-time
        order the 1-in-4 decoy cadence is positioned against."""
        if not user_id:
            return []
        try:
            res = (self.client.table("reflection_clips").select("*")
                   .eq("user_id", str(user_id))
                   .order("created_at", desc=False).execute())
            return res.data or []
        except Exception as e:
            _e = str(e).lower()
            if "reflection_clips" in _e and ("does not exist" in _e
                                             or "pgrst" in _e):
                logger.warning(
                    "list_reflection_clips: table missing (run "
                    "migrations/add_reflection_clips.sql)")
                return []
            logger.warning("list_reflection_clips failed user=%s: %s",
                           user_id, e)
            return []

    def insert_reflection_clip(self, user_id: str, fields: dict) -> bool:
        if not user_id or not isinstance(fields, dict) \
                or not fields.get("snippet_id"):
            return False
        try:
            self.client.table("reflection_clips").insert({
                "user_id": str(user_id), **fields,
            }).execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "duplicate" in _e or "unique" in _e:
                return False    # snippet already clipped — idempotent
            if "reflection_clips" in _e and ("does not exist" in _e
                                             or "pgrst" in _e):
                logger.warning(
                    "insert_reflection_clip: table missing (run "
                    "migrations/add_reflection_clips.sql)")
                return False
            logger.warning("insert_reflection_clip failed user=%s: %s",
                           user_id, e)
            return False

    def mark_reflection_clips_served(self, clip_ids) -> bool:
        ids = [str(x) for x in (clip_ids or []) if x]
        if not ids:
            return True
        try:
            (self.client.table("reflection_clips")
             .update({"served_at": datetime.now(timezone.utc).isoformat()})
             .in_("id", ids).is_("served_at", "null").execute())
            return True
        except Exception as e:
            logger.warning("mark_reflection_clips_served failed: %s", e)
            return False

    def count_reflection_clips_served_today(
            self, user_id: Optional[str]) -> int:
        """Clips FIRST served since UTC midnight — the cadence counter."""
        if not user_id:
            return 0
        try:
            day_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0).isoformat()
            res = (self.client.table("reflection_clips").select("id")
                   .eq("user_id", str(user_id))
                   .gte("served_at", day_start).execute())
            return len(res.data or [])
        except Exception:
            return 0

    def get_reflection_clip(self, clip_id: Optional[str]) -> Optional[dict]:
        if not clip_id:
            return None
        try:
            res = (self.client.table("reflection_clips").select("*")
                   .eq("id", str(clip_id)).limit(1).execute())
            return (res.data or [None])[0]
        except Exception:
            return None

    def set_reflection_vote(self, clip_id: str, user_id: str,
                            vote: str) -> Optional[dict]:
        """Store the user's vote (owner-scoped; a re-vote overwrites).
        Returns the updated row, or None when the clip isn't theirs."""
        if not clip_id or not user_id or vote not in ("best", "not_this"):
            return None
        try:
            res = (self.client.table("reflection_clips")
                   .update({"user_vote": vote,
                            "voted_at": datetime.now(
                                timezone.utc).isoformat()})
                   .eq("id", str(clip_id)).eq("user_id", str(user_id))
                   .execute())
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("set_reflection_vote failed clip=%s: %s",
                           clip_id, e)
            return None

    def list_reflection_clips_for_coach(self, limit: int = 20) -> list:
        """Voted, verdict-pending clips, oldest vote first. The caller
        (route) shapes the BLIND payload — audio + transcript only."""
        try:
            res = (self.client.table("reflection_clips").select("*")
                   .not_.is_("user_vote", "null")
                   .is_("coach_verdict", "null")
                   .order("voted_at", desc=False)
                   .limit(max(1, int(limit))).execute())
            return res.data or []
        except Exception as e:
            logger.warning("list_reflection_clips_for_coach failed: %s", e)
            return []

    def set_reflection_verdict(self, clip_id: str,
                               verdict: str) -> Optional[dict]:
        if not clip_id or verdict not in ("confident", "not_confident"):
            return None
        try:
            res = (self.client.table("reflection_clips")
                   .update({"coach_verdict": verdict,
                            "verified_at": datetime.now(
                                timezone.utc).isoformat()})
                   .eq("id", str(clip_id)).execute())
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("set_reflection_verdict failed clip=%s: %s",
                           clip_id, e)
            return None

    def list_confident_voices(self, user_id: Optional[str]) -> list:
        """The user's cross-project Confident Voices library: coach-
        verified moments only (decoys eligible — a coach-verified decoy
        is a confident moment), newest verdict first. A list is a list:
        no aggregates ride anywhere near this (AC-9)."""
        if not user_id:
            return []
        try:
            res = (self.client.table("reflection_clips").select("*")
                   .eq("user_id", str(user_id))
                   .eq("coach_verdict", "confident")
                   .order("verified_at", desc=True).execute())
            return res.data or []
        except Exception as e:
            logger.warning("list_confident_voices failed user=%s: %s",
                           user_id, e)
            return []


# Singleton instance
db = DatabaseService()
