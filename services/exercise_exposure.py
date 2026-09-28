"""The speaker's client confirms an assigned exercise rendered (0387).

Label specification exercise-adequacy-label-v1 (founder 2026-09-28,
docs/MLC3-EXERCISE-ADEQUACY-DESIGN.md §3.5, item 5): an exposure exists only
once the client confirms the exercise was actually on screen. The 80/20
assignment is made when the feedback is built, whether or not anyone saw it,
so it cannot stand in for this.

Recorded once per assignment in the database; a card rendered on every poll
is still one exposure. A moment with no draw — nothing fitted, or an exercise
a coach shared — has nothing to expose, and the call says so without error,
so the client can send it for every exercise card without knowing which kind
it is.

Nothing here reaches the speaker beyond "recorded": no count, no time.
"""
from __future__ import annotations

from typing import Any

#: The database's refusals, and what the client is told.
_REFUSALS = {
    "EXERCISE_RENDERED_NOT_OWNER": (404, "NOT_FOUND", "snippet not found"),
    "EXERCISE_RENDERED_WRONG_EXERCISE": (
        409, "EXERCISE_OFFER_STALE",
        "That is not the exercise offered for this moment."),
    "EXERCISE_RENDERED_INPUT_INVALID": (400, "INVALID_INPUT",
                                        "exercise_id is required"),
}


def record_rendered(database: Any, *, user_id: str, snippet_id: str,
                    body: Any) -> tuple[int, dict]:
    """(status, payload) for one render confirmation."""
    fields: dict = body if isinstance(body, dict) else {}
    exercise_id = fields.get("exercise_id")
    if not isinstance(exercise_id, str) or not exercise_id.strip():
        return 400, {"code": "INVALID_INPUT",
                     "error": "exercise_id is required"}
    snippet = database.get_snippet_by_id(str(snippet_id))
    session = (database.v2_get_session_by_id(
        str(snippet.get("session_id") or "")) if snippet else None)
    if (not snippet or not session
            or str(session.get("user_id")) != str(user_id)):
        return 404, {"code": "NOT_FOUND", "error": "snippet not found"}
    try:
        seen = database.record_exercise_rendered(
            owner_user_id=str(user_id),
            take_session_id=str(session.get("id")),
            snippet_id=str(snippet_id), exercise_id=exercise_id.strip())
    except Exception as e:  # the database's refusal, named
        text = str(e)
        if "EXERCISE_RENDERED_NOT_DRAWN" in text:
            # Nothing fitted, or a coach shared it: no draw, no exposure.
            return 200, {"recorded": False}
        for code, (status, public, message) in _REFUSALS.items():
            if code in text:
                return status, {"code": public, "error": message}
        raise
    return 200, {"recorded": isinstance(seen, dict)}
