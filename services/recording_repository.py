"""Recording repository — the F1 recordings and recording_attempts table access carved out of services/db.py
(audit Q-A1 step 2 / Q-A2, Phase 4, 2026-09-14).

Every method here is the verbatim body it had on DatabaseService; db.py keeps
a one-line delegate under the same name, so the ~360 test sites that patch
``db.<method>`` and every caller keep working unchanged. The repository takes
the injected database service (the feedback_repository idiom) and reads the
Supabase client THROUGH it on every call (``self.client`` is a property), so
``DatabaseService.reset_connections()`` — the post-fork rebuild — is seen here
too. Nothing in this module constructs a client; only services/db.py does.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone  # noqa: F401 — used by the moved bodies
from typing import Any, Dict, List, Optional  # noqa: F401

import sentry_sdk  # noqa: F401

logger = logging.getLogger(__name__)


class RecordingRepository:
    def __init__(self, database: Any) -> None:
        self.database = database

    @property
    def client(self) -> Any:
        return self.database.client

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

    def get_user_recording_history(self, user_id: str, exclude_recording_id: Optional[str] = None, limit: int = 10):
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

    def get_recording_attempt(self, attempt_id: str) -> Optional[dict]:
        """Read the canonical Attempt coordinates for parity-gated workers."""
        if not attempt_id:
            return None
        try:
            result = (
                self.client.table("recording_attempts")
                .select(
                    "id, owner_principal_id, project_id, recording_kind, "
                    "status, attempt_count"
                )
                .eq("id", str(attempt_id))
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as error:
            logger.warning(
                "recording attempt lookup failed attempt=%s: %s",
                attempt_id, error,
            )
            return None
