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
judgement is waiting. It is the speaker's side of the request once they
judged (`answer_kind`, 0408; Phase 2, F1), else the kind it rose under. Nothing here is a count of quality (AC-9); the
pseudonym is the queue's own, never a name (L3, §B.4). Pure apart from
`reached_for_sessions`, which makes the two reach reads; every other read
is handed in by the route.

ONLY MOMENTS THAT REACHED THE SPEAKER (founder 2026-10-05, N48.2, Q1 A;
audit D9). The Take's frozen set is chosen BEFORE the window of three
decides what the page shows, so it holds bookmarks no speaker ever met, and
the coach was judging those. A moment now rides the queue only when the
record says it reached the speaker (`reached_moments`):

    opened      the sheet opened on it (0408 `moment_events`, written by
                the page the moment the speaker taps it, under either flow)
    skipped     the speaker moved past it on its open sheet (0408)
    answered    a Confident Voice answer is stored for it
                (`take_feedback_self_report`; covers Takes before 0408)
    requested   its coach request rose, which happens only at the open or
                at the answer (`judgement_follow_up`)

The window's served rows are NOT a signal: the window re-decides on every
read and is never stored, so re-running it now answers "what would show
now", not "what was shown", and a moment the window served but the speaker
never tapped has no record to prove it. Only existence is read, never the
speaker's answer (BLIND COACH): the coach learns that a moment was met,
never what the speaker said about it.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Iterable, Optional

_log = logging.getLogger(__name__)

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
    kind = str(request.get("answer_kind") or request.get("kind") or "error")
    resolution = request.get("resolution")
    if not resolution:
        return {"state": "answer_it", "kind": kind}
    if resolution == "no_safe_match":
        return {"state": "nothing_to_add", "kind": kind}
    return {"state": "answered", "kind": kind}


def reached_moments(
    events: Iterable[Any], answers: Iterable[Any],
    requests: Iterable[Any] = (),
) -> dict[str, set[str]]:
    """{take_session_id: {snippet_id}} for the moments that reached the
    speaker: opened or skipped (0408), answered, or with a coach request
    (which rises only at the open or the answer). Existence only: no answer
    value is read, so none can travel (BLIND COACH)."""
    out: dict[str, set[str]] = {}

    def add(take: Any, snippet: Any) -> None:
        if take and snippet:
            out.setdefault(str(take), set()).add(str(snippet))

    for row in events or []:
        if isinstance(row, dict) and row.get("event") in ("opened", "skipped"):
            add(row.get("take_session_id"), row.get("snippet_id"))
    for row in answers or []:
        if isinstance(row, dict):
            add(row.get("take_session_id"), row.get("snippet_id"))
    for key in requests or []:
        if isinstance(key, tuple) and len(key) == 2:
            add(key[0], key[1])
    return out


def reached_for_sessions(
    database: Any, session_ids: list[str], requests: Any,
) -> Callable[[str], set[str]]:
    """The queue's `reached_for` from two batch reads for the whole queue
    (0408 events, stored answers) and the requests the route already holds.
    A failed read raises, so the queue answers 500 rather than listing
    moments no speaker met."""
    reached = reached_moments(
        database.list_moment_events_for_sessions(session_ids),
        database.list_confident_voice_answered_moments(session_ids),
        (requests or {}).keys())
    return lambda sid: reached.get(str(sid), set())


def _listed(session_id: str, bookmarked: Optional[list],
            reached: set[str]) -> list[str]:
    """The bookmarks that reached the speaker, in the take's order."""
    shown = [str(s) for s in bookmarked or [] if str(s) in reached]
    if bookmarked and len(shown) < len(bookmarked):
        # Never silently absent (founder 2026-10-01, 0a): the log names the
        # filter. Counts and ids only; nothing reaches a user.
        _log.info("coach queue: moments withheld sid=%s "
                  "filter=not_reached_speaker withheld=%d listed=%d",
                  session_id, len(bookmarked) - len(shown), len(shown))
    return shown


def moments_queue(
    rows: Iterable[Any], *,
    moments_for: Callable[[dict], Optional[list[str]]],
    reached_for: Callable[[str], set[str]],
    ratings_for: Callable[[str], dict],
    request_for: Callable[[str, str], Optional[dict]],
    pseudonym_for: Callable[[Any], str],
) -> list[dict]:
    """Speakers oldest first (by the earliest take waiting), takes oldest
    first under each, moments in the order the take lists them.

    `rows` are the review queue's raw rows; `moments_for(row)` the take's
    bookmarked snippet ids in order, or None while the take's bookmarks are
    not frozen yet (the take then rides as `waiting_for_text`, never absent:
    founder 2026-10-01, A1); `reached_for(session_id)` the snippet ids of
    that take that reached the speaker (`reached_moments`): a bookmark
    outside it is not listed (N48.2, Q1 A); `ratings_for(session_id)` THIS
    coach's own ratings by snippet; `request_for(session_id, snippet_id)`
    the moment's request row or None."""
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
        for sid in _listed(session_id, bookmarked, reached_for(session_id)):
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
