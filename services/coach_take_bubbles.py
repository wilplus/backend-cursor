"""A student's new Take as a bubble in the coach's Lounge chat (founder
2026-10-01, Phase 0c, A2).

Derived at read, never stored: a bubble is a Take in this coach's queue
(same language gate as the queue) on which this coach has rated no moment
yet. Opening the bubble opens the walk on that Take; judging its first
moment is what makes the bubble go. The bubble carries the pseudonym
(the Students screens stay off, N48.5 Q26 A). Nothing here says anything about the Take's quality (AC-9) or
its moments' kinds (BLIND COACH).
"""
from __future__ import annotations

from typing import Any, Callable


def bubbles(rows: Any, *, moments_for: Callable[[dict], Any],
            ratings_for: Callable[[str], dict],
            pseudonym_for: Callable[[Any], str]) -> list[dict]:
    """The Takes not yet walked by this coach, newest sent first. Pure."""
    out: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        sid = str(row["id"])
        marked = moments_for(row)
        ratings = ratings_for(sid) or {}
        if marked and any(str(m) in {str(k) for k in ratings} for m in marked):
            continue
        user_id = str(row.get("user_id") or "")
        out.append({
            "session_id": sid,
            "take_index": row.get("take_index"),
            "sent_at": str(row.get("review_requested_at") or row.get("created_at") or ""),
            "pseudonym": pseudonym_for(user_id),
            "waiting_for_text": marked is None,
            "first_snippet_id": str(marked[0]) if marked else None,
        })
    out.sort(key=lambda b: b["sent_at"], reverse=True)
    return out


def take_bubbles(database: Any, *, rater_id: str, state_for: Callable[..., dict],
                 matched_rows: Callable[[Any, Any, Any], list],
                 moments_for_snips: Callable[[dict, list], Callable[[dict], Any]],
                 pseudonym_for: Callable[[Any], str]) -> tuple[int, Any]:
    """(status, payload): 428 without the coach's languages; else
    {bubbles: [...]}. The queue's own loaders and gates, handed in."""
    from services.coach_moments_queue import own_ratings_for
    from services.coach_queue import load_review_queue
    proficient = database.get_user_proficient_languages(rater_id)
    if not proficient:
        return 428, {"code": "RATER_LANGUAGES_REQUIRED",
                     "error": "Add the languages you coach in first."}
    rows, snips, _states = load_review_queue(database, state_for)
    matched = matched_rows(rows, snips, proficient)
    return 200, {"bubbles": bubbles(
        matched, moments_for=moments_for_snips(snips, matched),
        ratings_for=own_ratings_for(
            database, [str(r.get("id")) for r in matched if isinstance(r, dict)], rater_id),
        pseudonym_for=pseudonym_for)}
