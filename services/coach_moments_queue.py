"""The coach's queue of moments (founder 2026-09-30, A1 to A8; build plan
P2-6).

Speakers oldest first, their takes under them, the moments under each,
and for each moment ONE WORD for where the coach is with it:

    judge_it        no rating from this coach yet
    answer_it       rated; the moment's request is open
    answered        rated; the coach answered with something
    nothing_to_add  rated; the coach said nothing safe fits
    judged          rated; nothing reached the coach from this moment

The kind (error, praise, rewrite, ambiguity) rides ONLY on a moment this
coach has rated (BLIND COACH): before the rating the row says only that a
judgement is waiting. Nothing here is a count of quality (AC-9); the
pseudonym is the queue's own, never a name (L3, §B.4). Pure: every read is
handed in by the route.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Optional

STATES = ("judge_it", "answer_it", "answered", "nothing_to_add", "judged")
_RATED = ("yes", "in_between", "no", "not_sure")


def moment_state(rating: Any, request: Any) -> dict:
    """The one word, and the kind once the rating is saved."""
    rated = (isinstance(rating, dict)
             and rating.get("value") in _RATED
             and not rating.get("unrateable"))
    if not rated:
        return {"state": "judge_it"}
    if not isinstance(request, dict):
        return {"state": "judged"}
    kind = str(request.get("kind") or "error")
    resolution = request.get("resolution")
    if not resolution:
        return {"state": "answer_it", "kind": kind}
    if resolution == "no_safe_match":
        return {"state": "nothing_to_add", "kind": kind}
    return {"state": "answered", "kind": kind}


def moments_queue(
    rows: Iterable[Any], *,
    moments_for: Callable[[dict], list[str]],
    ratings_for: Callable[[str], dict],
    request_for: Callable[[str, str], Optional[dict]],
    pseudonym_for: Callable[[Any], str],
) -> list[dict]:
    """Speakers oldest first (by the earliest take waiting), takes oldest
    first under each, moments in the order the take lists them.

    `rows` are the review queue's raw rows; `moments_for(row)` the take's
    bookmarked snippet ids in order, or None while the take's bookmarks are
    not frozen yet (the take then rides as `waiting_for_text`, never absent:
    founder 2026-10-01, A1); `ratings_for(session_id)` THIS coach's own
    ratings by snippet; `request_for(session_id, snippet_id)` the moment's
    request row or None."""
    speakers: dict[str, dict] = {}
    order: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        session_id = str(row["id"])
        key = str(row.get("user_id") or session_id)
        sent_at = str(row.get("review_requested_at") or row.get("created_at") or "")
        ratings = ratings_for(session_id) or {}
        bookmarked = moments_for(row)
        moments = []
        for snippet_id in bookmarked or []:
            sid = str(snippet_id)
            moments.append({
                "snippet_id": sid,
                **moment_state(ratings.get(sid), request_for(session_id, sid)),
            })
        take = {
            "session_id": session_id,
            "take_index": row.get("take_index"),
            "sent_at": sent_at,
            "moments": moments,
            "waiting": sum(1 for m in moments if m["state"] in ("judge_it", "answer_it")),
            "waiting_for_text": bookmarked is None,
        }
        speaker = speakers.get(key)
        if speaker is None:
            speaker = {"pseudonym": pseudonym_for(row.get("user_id")),
                       "first_sent_at": sent_at, "takes": []}
            speakers[key] = speaker
            order.append(key)
        speaker["takes"].append(take)
        if sent_at and (not speaker["first_sent_at"] or sent_at < speaker["first_sent_at"]):
            speaker["first_sent_at"] = sent_at
    out = []
    for key in sorted(order, key=lambda k: speakers[k]["first_sent_at"]):
        speaker = speakers[key]
        speaker["takes"].sort(key=lambda t: t["sent_at"])
        out.append({
            "pseudonym": speaker["pseudonym"],
            "takes": speaker["takes"],
            "waiting": sum(t["waiting"] for t in speaker["takes"]),
            "waiting_for_text": sum(1 for t in speaker["takes"] if t["waiting_for_text"]),
        })
    return out
