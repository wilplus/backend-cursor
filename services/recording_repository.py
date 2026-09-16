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

from services.table_repository import TableRepository

logger = logging.getLogger(__name__)


class RecordingRepository(TableRepository):
    def create_recording(self, data: dict):
        """Create a recording record"""
        result = self.client.table("recordings")\
            .insert(data)\
            .execute()
        
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
