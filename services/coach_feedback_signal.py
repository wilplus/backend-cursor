"""The Lounge bubble's "new": a coach word or answer the walk has not shown
(build plan D-FW-5; founder lock 2026-10-06, the Feedback walk, flow 1 and
"Amendments: Lounge").

"When new feedback from the coach arrives, the Ideal Text bubble in the
Lounge gets the orange outline and a 'new' tag." One yes/no per project,
never a count (AC-9): true while a published coach word (the Take's note)
or a published coach answer on a moment of one of its Takes is newer than
the walk's last show of it; machine-only feedback never makes it true.
The walk clears it by telling the server what it showed (``mark_seen``).
The rule lives in ``new_coach_feedback_by_project_v1`` (0439).

Best-effort on the Lounge's read: a failure there is no flag, never an
error, so the Lounge always mounts (LIVE LOOP).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

_log = logging.getLogger(__name__)

#: The item the walk shows first: the Take's coach note (video and words).
TAKE_WORD = "take_word"


def _uuid(value: Any) -> Optional[str]:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def lounge_flags(database: Any, user_id: Any) -> dict[str, bool]:
    """{project id: bool} for the speaker's projects; {} on any failure."""
    reader = getattr(database, "new_coach_feedback_by_project", None)
    if reader is None or not user_id:
        return {}
    try:
        flags = reader(str(user_id)) or {}
    except Exception as error:  # noqa: BLE001 -- the Lounge still mounts
        _log.warning("new coach feedback read failed: %s", type(error).__name__)
        return {}
    return {str(arc): value is True for arc, value in flags.items()}


def mark_seen(database: Any, user_id: Any, body: Any) -> tuple[int, dict]:
    """The walk showed the Take's coach note (no ``snippet_id``) or one
    moment (``snippet_id``). Returns (status, body); the body says only
    ``{"seen": true}``."""
    body = body if isinstance(body, dict) else {}
    take = _uuid(body.get("take_session_id"))
    snippet = body.get("snippet_id")
    if take is None:
        return 400, {"code": "INVALID_INPUT",
                     "error": "take_session_id must be a valid UUID"}
    if snippet is None:
        item = TAKE_WORD
    else:
        item = _uuid(snippet) or ""
        if not item:
            return 400, {"code": "INVALID_INPUT",
                         "error": "snippet_id must be a valid UUID"}
    try:
        database.mark_coach_feedback_seen(
            user_id=str(user_id), take_session_id=take, item=item)
    except Exception as error:  # noqa: BLE001 -- answered, never swallowed
        if "COACH_FEEDBACK_TAKE_NOT_OWNED" in str(error):
            return 404, {"code": "NOT_FOUND", "error": "take not found"}
        _log.warning("mark coach feedback seen failed take=%s: %s",
                     take, type(error).__name__)
        return 500, {"code": "V2_ERROR", "error": "Could not save."}
    return 200, {"seen": True}
