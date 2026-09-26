"""Taking a coach review, and the session row read under it.

The claim and the re-read after it are one step. Review ownership must be
decided on a row read AFTER the claim was taken, so the re-read can never
move before it; and a failure of either means the same thing to the coach —
the review could not be opened safely (503), never a generic 500.

A service, not a route helper, for the reason ``services/coach_queue.py``
gives: the route fence caps every function under ``routes/`` at one database
call, and "claim, then re-read" is two.
"""
from __future__ import annotations

from typing import Any


def claim_review_and_reread(
    database: Any,
    session_id: str,
    actor_user_id: str,
    *,
    actor_is_admin: bool,
    before_claim: dict,
) -> dict:
    """Claim the review for ``actor_user_id``, then re-read its session.

    Returns the row as of the claim, or ``before_claim`` when the re-read
    finds nothing. Any exception from either call reaches the caller as is.
    """
    database.claim_coach_review(
        session_id, actor_user_id, actor_is_admin=actor_is_admin,
    )
    return database.v2_get_session_by_id(session_id) or before_claim
