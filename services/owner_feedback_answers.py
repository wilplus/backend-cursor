"""The owner's own answers on a Take, for the answered bookmark (contract 16,
founder 2026-09-25, Q19 A).

An answered bookmark opens on one screen: the exercise if there is one, "You
said: <answer>" in one line, what happened to the moment, then the history.
The frontend knows the moment's items and their decided status already; the
one thing it does not have is the answer the owner actually gave — five
values, where the item's status only says approved or dismissed.

Owner-only and self-report only: these are the owner's own answers, never a
coach label, machine prediction or peer rating (L3, BLIND COACH), and never a
score (AC-9).
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional


def owner_answers(database: Any, take_session_id: str,
                  owner_user_id: str) -> Optional[list]:
    """The owner's latest answer per feedback item on their own Take.

    None when the Take is not theirs (the route answers 404). The ownership
    check and the answers are read at once (2026-10-18): the answers read is
    already scoped to this owner, so it shows nothing before the check."""
    from services.parallel import run_in_parallel
    from services.project_ownership import session_actor_id
    if not owner_user_id:
        return None
    session, rows = run_in_parallel(
        lambda: database.v2_session_owner(str(take_session_id)),
        lambda: database.list_take_feedback_self_reports(
            str(take_session_id), str(owner_user_id)))
    if session_actor_id(session or {}) != str(owner_user_id):
        return None
    latest: dict = {}
    for row in rows or []:
        if not isinstance(row, Mapping) or not row.get("feedback_id"):
            continue
        latest[str(row["feedback_id"])] = {
            "feedback_id": str(row["feedback_id"]),
            "feedback_family": row.get("feedback_family"),
            "response": row.get("response"),
            "at": row.get("revised_at") or row.get("created_at"),
        }
    return list(latest.values())
