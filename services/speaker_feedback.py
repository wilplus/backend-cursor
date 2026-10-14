"""What speakers tell Will about the app or about Will himself (founder
2026-10-14: "I didn't save that feedback by the way, save it somewhere so
you learn also from the conversation with the chat").

The chat's router recognises such a turn (lane ``speaker_feedback``) and
Will replies naturally. The speaker's own message is kept where it already
lives, in their Lounge thread, tagged ``metadata.speaker_feedback``, so an
account's deletion takes it with everything else. The founder reads them
here, newest first, through an admin-only route.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

TAG = "speaker_feedback"
MAX_LIMIT = 200


def recent(database: Any, limit: int = 50) -> list[dict]:
    """The newest tagged speaker messages: {user_id, body, at}."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    res = (database.client.table("lounge_messages")
           .select("user_id, body, client_created_at")
           .eq("role", "user")
           .eq(f"metadata->>{TAG}", "true")
           .order("client_created_at", desc=True)
           .limit(limit).execute())
    return [{"user_id": r.get("user_id"), "body": r.get("body"),
             "at": r.get("client_created_at")} for r in res.data or []]
