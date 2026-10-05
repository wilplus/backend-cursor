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

THE PANEL ROUTES THE CLIP (decisions K4, K5, K6, K7; W6 2026-10-05). The
coach's blind rating is also the label ledger's vote, so the queue lists a
moment for a coach only where the ledger (services.label_quorum) still wants
THIS coach's ear, read from every rater's rows and used for routing alone
(no other answer travels, BLIND COACH):

    audio_unclear_reported  this coach said Audio unclear: the clip goes to
                            a DIFFERENT rater (AUDIO_RETRY), and a second
                            listen by the same coach is no independent
                            answer (K7), so it leaves this coach's queue
                            instead of saying "Judge it" over a 409
    audio_quarantined       two independent Audio unclear reports: no rater
                            is asked again, and it stays only where this
                            coach already judged it
    rating_closed           two matching answers settled it, or three
                            without a pair left it UNRESOLVED: nobody new is
                            asked (K4); a disagreement or a Not sure asks a
                            third coach

Neither audio report is a label. The owner never counts and the machine
never votes (label_quorum, K6); with the peer lane off, the panel is coaches.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Callable, Iterable, Optional

_log = logging.getLogger(__name__)

STATES = ("judge_it", "answer_it", "answered", "nothing_to_add", "judged")
_RATED = ("yes", "in_between", "no", "not_sure")

#: Why a moment is not listed for THIS coach. Logged by name, never served.
NOT_LISTED_AUDIO_RETRY = "audio_unclear_reported"
NOT_LISTED_QUARANTINED = "audio_quarantined"
NOT_LISTED_CLOSED = "rating_closed"

#: K9 (decisions log K9; W6 2026-10-05): what put a clip in front of the
#: coach, stamped on the coach's rating server-side and never shown before
#: the judgment. The walk lists EVERY bookmark that reached the speaker to
#: every eligible coach: a census of what the Manager chose and the speaker
#: met (probability 1), so it can never estimate production performance on
#: its own. The unbiased random window K9 asks for does not exist for
#: speakers' Takes: any random clip would be one the speaker never met,
#: which N48.2 Q1 A keeps out of the coach's queue; that is the founder's.
#: A clip of the corpus labelling queue keeps the mixed cohort's own record
#: (services.confidence_labels: boundary, balance, random exploration).
WALK_SELECTION_POLICY = "coach-walk-reached-bookmarks-v1"
REASON_REACHED_BOOKMARK = "reached_bookmark"
REASON_OUTSIDE_WALK = "outside_walk"
REASON_UNKNOWN = "unknown"


def selection_stamp(*, cohort_record: Any = None,
                    reached_bookmark: Optional[bool] = None) -> dict:
    """The K9 stamp for one rating: the corpus cohort's own record where the
    clip was drawn into one, else the walk's census (``reached_bookmark``
    True), else a reason with no probability (``False``: the clip was not
    in the walk; ``None``: the read failed)."""
    if isinstance(cohort_record, dict) and cohort_record.get("reason"):
        return {"selection_policy_version": cohort_record.get("policy_version"),
                "selection_reason": cohort_record.get("reason"),
                "sampling_probability": cohort_record.get("sampling_probability")}
    if reached_bookmark:
        return {"selection_policy_version": WALK_SELECTION_POLICY,
                "selection_reason": REASON_REACHED_BOOKMARK,
                "sampling_probability": 1.0}
    return {"selection_policy_version": WALK_SELECTION_POLICY,
            "selection_reason": (REASON_OUTSIDE_WALK if reached_bookmark is False
                                 else REASON_UNKNOWN),
            "sampling_probability": None}


def _rated(rating: Any) -> bool:
    return (isinstance(rating, dict) and rating.get("value") in _RATED
            and not rating.get("unrateable"))


def _reported_audio_unclear(rating: Any) -> bool:
    return isinstance(rating, dict) and (
        rating.get("value") == "audio_unclear" or rating.get("unrateable") is True)


def routing(rating: Any, labels: Optional[list], rater_id: Any) -> Optional[str]:
    """None when the moment is listed for this coach; else why not (the
    ``NOT_LISTED_*`` names). ``rating`` is this coach's own row on the clip;
    ``labels`` every rater's confidence rows on it, or None when they were
    not read (then only the coach's own row decides). Routing only: no
    value is returned, so none can reach a screen (BLIND COACH)."""
    from services.label_quorum import rater_submission_access
    if _reported_audio_unclear(rating):
        return NOT_LISTED_AUDIO_RETRY
    if labels is None:
        return None
    rows = [r for r in labels if isinstance(r, dict)
            and str(r.get("state_id") or "confidence") == "confidence"]
    access = rater_submission_access(rows, rater_id)
    if access["outcome"] == "audio_quarantined" and not _rated(rating):
        return NOT_LISTED_QUARANTINED
    if not access["has_own_rating"] and not access["allowed"]:
        return NOT_LISTED_CLOSED
    return None


def moment_state(rating: Any, request: Any) -> dict:
    """The one word, and the kind once the rating is saved. A moment this
    coach reported as Audio unclear never reaches here (``routing``)."""
    if not _rated(rating):
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


#: Clips per label read: an `in` filter rides the URL, so it is chunked.
_LABEL_CHUNK = 150


def remembered(moments_for: Callable[[dict], Optional[list[str]]]
               ) -> Callable[[dict], Optional[list[str]]]:
    """``moments_for`` asked once per take: the route reads the bookmarks
    to fetch the labels, and the queue reads them again to list them."""
    seen: dict[str, Optional[list[str]]] = {}

    def once(row: dict) -> Optional[list[str]]:
        key = str(row.get("id"))
        if key not in seen:
            seen[key] = moments_for(row)
        return seen[key]
    return once


def labels_for_snippets(database: Any, snippet_ids: Iterable[Any]
                        ) -> Callable[[str], Optional[list]]:
    """The queue's ``labels_for``: every rater's confidence rows on the
    listed clips, from batched reads. A read that fails routes on each
    coach's own row alone (``labels_for`` answers None) and says so: an
    extra listing costs a refused rating, a hidden moment an answer."""
    ids = sorted({str(s) for s in snippet_ids or [] if s})
    found: dict[str, list] = {}
    try:
        for i in range(0, len(ids), _LABEL_CHUNK):
            chunk = database.get_confidence_labels_by_snippet_ids(
                ids[i:i + _LABEL_CHUNK], strict=True) or {}
            for sid, rows in chunk.items():
                found.setdefault(str(sid), []).extend(rows or [])
    except Exception as e:  # noqa: BLE001 -- routed on own rows, named
        _log.warning("coach queue: label read failed, routing on own rows: %s",
                     e, exc_info=True)
        return lambda _sid: None
    return lambda sid: list(found.get(str(sid)) or [])


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


def _routed(session_id: str, listed: list[str], ratings: dict,
            labels_for: Optional[Callable[[str], Optional[list]]],
            rater_id: Any) -> list[str]:
    """The listed moments the ledger still wants THIS coach on (``routing``).
    Never silently absent: the log names each filter with its count."""
    kept: list[str] = []
    withheld: Counter = Counter()
    for sid in listed:
        why = routing(ratings.get(sid), labels_for(sid) if labels_for else None,
                      rater_id)
        if why:
            withheld[why] += 1
        else:
            kept.append(sid)
    for why, count in sorted(withheld.items()):
        _log.info("coach queue: moments withheld sid=%s filter=%s withheld=%d",
                  session_id, why, count)
    return kept


def moments_queue(
    rows: Iterable[Any], *,
    moments_for: Callable[[dict], Optional[list[str]]],
    reached_for: Callable[[str], set[str]],
    ratings_for: Callable[[str], dict],
    request_for: Callable[[str, str], Optional[dict]],
    pseudonym_for: Callable[[Any], str],
    labels_for: Optional[Callable[[str], Optional[list]]] = None,
    rater_id: Any = None,
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
    the moment's request row or None; `labels_for(snippet_id)` every
    rater's rows on the clip, for routing only (``routing``; K4, K5), and
    `rater_id` this coach."""
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
        listed = _listed(session_id, bookmarked, reached_for(session_id))
        for sid in _routed(session_id, listed, ratings, labels_for, rater_id):
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


def queue_for_coach(
    database: Any, rows: list, *, rater_id: Any,
    moments_for: Callable[[dict], Optional[list[str]]],
    pseudonym_for: Callable[[Any], str],
) -> list[dict]:
    """The walk's queue for one coach, every read batched: the moments'
    requests, the reach (N48.2 Q1 A), this coach's own ratings and the
    panel's rows on the listed clips (routing only, K4, K5). ``rows`` are
    the review queue's rows this coach may see (the language gate)."""
    ids = [str(r.get("id")) for r in rows if isinstance(r, dict)]
    requests = database.list_exercise_coach_requests_for_sessions(ids)
    once = remembered(moments_for)
    return moments_queue(
        rows, moments_for=once,
        reached_for=reached_for_sessions(database, ids, requests),
        ratings_for=lambda sid: database.get_own_state_ratings_for_session(sid, rater_id),
        request_for=lambda sid, snip: requests.get((sid, snip)),
        pseudonym_for=pseudonym_for,
        labels_for=labels_for_snippets(
            database, [s for r in rows if isinstance(r, dict) for s in (once(r) or [])]),
        rater_id=rater_id)
