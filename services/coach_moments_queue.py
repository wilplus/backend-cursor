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
`reached_for_sessions`, which makes the two reach reads, `queue_reads` (and
`queue_for_coach` over it), which makes the queue's reads side by side,
`walk_for_coach`, the walk's reads in three steps, and `close_moments`, the
founder's Delete; every other read is handed in by the route.

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

THE FOUNDER'S DELETE (2026-10-20). The ⋯ on a speaker's row of the queue
closes that speaker's waiting moments: ``close_moments`` keeps them on the
Take as ``intake_context.coach_closed_moments`` ({snippet_id: closed_at}; no
migration, as the corpus archive), and a closed moment leaves every coach's
queue (``closed_by_founder``, logged like the other filters). A Take still
waiting for its text has no moment yet, so it closes whole
(``intake_context.coach_closed_take``): it leaves every coach's queue, and so
do the moments it gets later. The reach is counted before either, so the
reach alarm still hears the Take; the Take, its request and its Ideal Text
are untouched.
"""
from __future__ import annotations

import functools
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable, Iterable, Optional

if TYPE_CHECKING:
    from services.coach_queue import Bookmarks

_log = logging.getLogger(__name__)

STATES = ("judge_it", "answer_it", "answered", "nothing_to_add", "judged",
          "listen_again")
_RATED = ("yes", "in_between", "no", "not_sure")

#: Why a moment is not listed for THIS coach. Logged by name, never served.
NOT_LISTED_AUDIO_RETRY = "audio_unclear_reported"
NOT_LISTED_QUARANTINED = "audio_quarantined"
NOT_LISTED_CLOSED = "rating_closed"
NOT_LISTED_CLOSED_BY_FOUNDER = "closed_by_founder"

#: Where the Take keeps the moments the founder closed: {snippet_id: closed_at}.
CLOSED_KEY = "coach_closed_moments"
#: Where a Take closed whole keeps when (a Take still waiting for its text).
CLOSED_TAKE_KEY = "coach_closed_take"
#: One close is one speaker's row; this bounds a malformed body.
MAX_CLOSE_TAKES = 50

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


def label_reads(database: Any, snippet_ids: Iterable[Any]
                ) -> list[Callable[[], dict]]:
    """The panel's confidence rows on the bookmarked clips, one read per
    chunk of ``_LABEL_CHUNK``, for the queue to run beside its other reads;
    their answers go to ``labels_found``. Each raises when it fails."""
    ids = sorted({str(s) for s in snippet_ids or [] if s})
    return [functools.partial(database.get_confidence_labels_by_snippet_ids,
                              ids[i:i + _LABEL_CHUNK], strict=True)
            for i in range(0, len(ids), _LABEL_CHUNK)]


def labels_found(answers: Iterable[tuple[Any, Optional[Exception]]]
                 ) -> Callable[[str], Optional[list]]:
    """The queue's ``labels_for``, from the label reads' answers, ``(rows,
    failure)`` each: every rater's confidence rows on a clip. A read that
    failed routes on each coach's own row alone (``labels_for`` answers
    None) and says so: an extra listing costs a refused rating, a hidden
    moment an answer."""
    found: dict[str, list] = {}
    for chunk, failure in answers:
        if failure is not None:
            _log.warning("coach queue: label read failed, routing on own rows: %s",
                         failure, exc_info=failure)
            return lambda _sid: None
        for sid, rows in (chunk or {}).items():
            found.setdefault(str(sid), []).extend(rows or [])
    return lambda sid: list(found.get(str(sid)) or [])


#: The newest Takes with moments the alarm looks at, and how long their
#: speakers get to open their feedback first.
REACH_ALARM_TAKES = 3
REACH_ALARM_AFTER = timedelta(hours=6)
_alarmed_on: Optional[str] = None


def _host_chats(takes: list[tuple], chat_of: Callable[[str], Optional[str]]) -> list[str]:
    """The host chats the named Takes were made in, each once."""
    found: list[str] = []
    for take in takes:
        if len(take) < 3 or not take[2]:
            continue
        try:
            chat = chat_of(str(take[2]))
        except Exception:  # noqa: BLE001 — the alarm never waits on this read
            _log.debug("coach queue: host chat not read for %s", take[2], exc_info=True)
            continue
        if chat and chat not in found:
            found.append(chat)
    return found


def reach_alarm(takes: list[tuple], now: Optional[datetime] = None,
                chat_of: Callable[[str], Optional[str]] = lambda _sid: None) -> bool:
    """THE ALARM (founder 2026-10-20). ``takes`` is (sent_at, any moment
    reached[, session id]) for every Take with moments. When the newest few,
    all sent long enough ago, have no moment that reached their speaker,
    something stopped recording the reach (the walk did, 2026-10-12, and no
    coach heard a new speaker): one Sentry warning a day. True when it fired.

    ``chat_of(session id)`` is the host chat a Take was made in (N648 item
    8; services.take_door.made_in). It is read only when the alarm fires, for
    the few Takes it names, so the message says which host chats are not
    reaching a coach; a failed read leaves it out and never costs the alarm."""
    global _alarmed_on
    now = now or datetime.now(timezone.utc)
    cutoff = (now - REACH_ALARM_AFTER).isoformat()
    newest = sorted((t for t in takes if t[0] and t[0] <= cutoff), reverse=True)[:REACH_ALARM_TAKES]
    if len(newest) < REACH_ALARM_TAKES or any(take[1] for take in newest):
        return False
    today = now.date().isoformat()
    if _alarmed_on == today:
        return False
    _alarmed_on = today
    message = (f"coach queue: the {REACH_ALARM_TAKES} newest Takes have no moment "
               "that reached their speaker; no coach can hear them")
    chats = _host_chats(newest, chat_of)
    if chats:
        message += "; made in host chat: " + ", ".join(chats)
    _log.warning(message)
    try:
        import sentry_sdk
        sentry_sdk.capture_message(message, level="warning")
    except Exception:  # noqa: BLE001 — the alarm never costs the queue
        _log.debug("coach queue: alarm not sent", exc_info=True)
    return True


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


def closed_moments(row: Any) -> set[str]:
    """The snippet ids the founder closed on this Take (``close_moments``)."""
    ctx = row.get("intake_context") if isinstance(row, dict) else None
    closed = ctx.get(CLOSED_KEY) if isinstance(ctx, dict) else None
    return {str(s) for s in closed} if isinstance(closed, dict) else set()


def take_closed(row: Any) -> bool:
    """True when the founder closed this Take whole (``close_moments``)."""
    ctx = row.get("intake_context") if isinstance(row, dict) else None
    return isinstance(ctx, dict) and bool(ctx.get(CLOSED_TAKE_KEY))


def _open(session_id: str, listed: list[str], closed: set[str]) -> list[str]:
    """The listed moments the founder has not closed; logged, never silent."""
    kept = [s for s in listed if s not in closed]
    if len(kept) < len(listed):
        _log.info("coach queue: moments withheld sid=%s filter=%s withheld=%d",
                  session_id, NOT_LISTED_CLOSED_BY_FOUNDER, len(listed) - len(kept))
    return kept


#: The states a speaker's row counts as waiting (``moments_queue``).
WAITING_STATES = ("judge_it", "answer_it", "listen_again")


def waiting_moments(queue: list[dict]) -> dict[str, list[str]]:
    """{session_id: [snippet_id]} of the moments a coach's queue counts as
    waiting, exactly as its ``waiting`` numbers count them. Pure."""
    out: dict[str, list[str]] = {}
    for speaker in queue or []:
        for take in speaker.get("takes") or []:
            ids = [str(m["snippet_id"]) for m in take.get("moments") or []
                   if m.get("state") in WAITING_STATES and m.get("snippet_id")]
            if ids:
                out[str(take["session_id"])] = ids
    return out


def waiting_for_text(queue: list[dict]) -> set[str]:
    """The session ids of a coach's queue still waiting for their text: no
    moment yet, so the founder's Delete closes them whole. Pure."""
    return {str(t["session_id"]) for speaker in queue or []
            for t in speaker.get("takes") or [] if t.get("waiting_for_text")}


def close_moments(database: Any, rows: list, waiting: dict[str, list[str]], *,
                  whole: Iterable[str] = (),
                  now: Optional[datetime] = None) -> int:
    """The founder's Delete on a speaker's row: keep ``waiting`` closed on the
    Takes' review-queue ``rows`` (which carry ``intake_context``), merged into
    what each Take already holds, and close the Takes in ``whole`` entirely.
    How many moments and Takes were newly closed; raises RuntimeError when a
    write fails."""
    whole = {str(w) for w in whole}
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    closed = 0
    for row in rows or []:
        sid = str(row.get("id") or "") if isinstance(row, dict) else ""
        ctx = dict(row.get("intake_context") or {}) if isinstance(
            row.get("intake_context"), dict) else {}
        held = ctx.get(CLOSED_KEY)
        before: dict = held if isinstance(held, dict) else {}
        added = {s: stamp for s in waiting.get(sid) or [] if s not in before}
        closes_take = sid in whole and not ctx.get(CLOSED_TAKE_KEY)
        if not added and not closes_take:
            continue
        if added:
            ctx[CLOSED_KEY] = {**before, **added}
        if closes_take:
            ctx[CLOSED_TAKE_KEY] = stamp
        if not database.takes.set_session_intake_context(sid, ctx):
            raise RuntimeError(f"could not close moments on {sid}")
        closed += len(added) + int(closes_take)
    _log.info("coach queue: founder closed %d moment(s) or Take(s)", closed)
    return closed


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


def answered_at(moments: list[dict], ratings: dict,
                request_for: Callable[[str, str], Optional[dict]],
                session_id: str) -> Optional[str]:
    """When THIS coach last answered on the Take: the latest of their own
    ratings and the answers resolved on its listed moments, or None. Orders
    the coach's answered Takes, most recent first; a time, never a value
    (BLIND COACH holds: it says when, not what)."""
    times = []
    for m in moments:
        sid = str(m.get("snippet_id") or "")
        rating = ratings.get(sid)
        if isinstance(rating, dict) and rating.get("updated_at"):
            times.append(str(rating["updated_at"]))
        request = request_for(session_id, sid)
        if isinstance(request, dict) and request.get("resolved_at"):
            times.append(str(request["resolved_at"]))
    return max(times) if times else None


def _no_goal(_user_id: Any) -> Optional[str]:
    return None


def talk_setup(row: Any) -> tuple[Optional[str], Optional[str]]:
    """Who the Take's talk is for and what the speaker wants the audience to
    do, in the speaker's own words: the setup's ``audience`` and its
    "Desired call to action:" line, filled by Will's questions (N82).
    Founder 2026-10-20 (N87): the coach sees both under the speaker's goal,
    from the newest Take that has them. Never a name; None when the speaker
    has not said. Pure."""
    ctx = row.get("intake_context") if isinstance(row, dict) else None
    ctx = ctx if isinstance(ctx, dict) else {}
    from services.will_question import call_to_action
    audience = str(ctx.get("audience") or "").strip() or None
    ask = call_to_action(ctx.get("strategic_context")) or None
    return audience, ask


def _goal_text(profile: Any) -> Optional[str]:
    goal = profile.get("goal") if isinstance(profile, dict) else None
    if not isinstance(goal, str):
        return None
    return goal.strip() or None


def speaker_goals(database: Any, rows: Iterable[Any]
                  ) -> Callable[[Any], Optional[str]]:
    """The queue's ``goal_for``: every speaker's goal, a courtesy on the
    queue, from one batched read (one read per speaker was a round trip
    each, founder 2026-10-18). Never a name. A failed read shows no goal."""
    ids = sorted({str(r.get("user_id")) for r in rows or []
                  if isinstance(r, dict) and r.get("user_id")})
    try:
        profiles = (database.get_user_profiles(ids) or {}) if ids else {}
    except Exception as e:  # noqa: BLE001 -- the goal is a courtesy
        _log.info("speaker goals unavailable: %s", e)
        profiles = {}
    return lambda uid: _goal_text(profiles.get(str(uid))) if uid else None


def moments_queue(
    rows: Iterable[Any], *,
    moments_for: Callable[[dict], Optional[list[str]]],
    reached_for: Callable[[str], set[str]],
    ratings_for: Callable[[str], dict],
    request_for: Callable[[str, str], Optional[dict]],
    pseudonym_for: Callable[[Any], str],
    labels_for: Optional[Callable[[str], Optional[list]]] = None,
    rater_id: Any = None,
    goal_for: Callable[[Any], Optional[str]] = _no_goal,
    listen_again_for: Callable[[str], dict[str, str]] = lambda _sid: {},
    alarm: bool = True,
    chat_of: Callable[[str], Optional[str]] = lambda _sid: None,
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
    `rater_id` this coach. The speaker's goal is read once per speaker
    via `goal_for`; never a name. `listen_again_for(session_id)` is
    {snippet_id: line_key} for THIS coach's open asks to listen again
    (0444, QG12a A, P26b A): such a moment rides as `listen_again` with the
    signed line's key and nothing else, not even the kind, and counts as
    waiting (BLIND COACH)."""
    speakers: dict[str, dict] = {}
    order: list[str] = []
    reach: list[tuple[str, bool, str]] = []
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
        if bookmarked:
            reach.append((sent_at, bool(listed), session_id))
        if take_closed(row):
            _log.info("coach queue: take withheld sid=%s filter=%s",
                      session_id, NOT_LISTED_CLOSED_BY_FOUNDER)
            continue
        asks = listen_again_for(session_id) or {}
        open_listed = _open(session_id, listed, closed_moments(row))
        for sid in _routed(session_id, open_listed, ratings, labels_for, rater_id):
            if sid in asks:
                from services.coach_listen_again import queue_row
                moments.append(queue_row(sid, asks[sid]))
                continue
            moments.append({
                "snippet_id": sid,
                **moment_state(ratings.get(sid), request_for(session_id, sid)),
            })
        take = {
            "session_id": session_id,
            "take_index": row.get("take_index"),
            "sent_at": sent_at,
            "moments": moments,
            "waiting": sum(1 for m in moments
                           if m["state"] in ("judge_it", "answer_it", "listen_again")),
            "waiting_for_text": bookmarked is None,
            "answered_at": answered_at(moments, ratings, request_for, session_id),
        }
        take["audience"], take["call_to_action"] = talk_setup(row)
        speaker = speakers.get(key)
        if speaker is None:
            speaker = {"pseudonym": pseudonym_for(row.get("user_id")),
                       "goal": goal_for(row.get("user_id")),
                       "first_sent_at": sent_at, "takes": []}
            speakers[key] = speaker
            order.append(key)
        speaker["takes"].append(take)
        if sent_at and (not speaker["first_sent_at"] or sent_at < speaker["first_sent_at"]):
            speaker["first_sent_at"] = sent_at
    if alarm:  # off for a part of the queue (the founder's Delete)
        reach_alarm(reach, chat_of=chat_of)
    out = []
    for key in sorted(order, key=lambda k: speakers[k]["first_sent_at"]):
        speaker = speakers[key]
        speaker["takes"].sort(key=lambda t: t["sent_at"])
        out.append({
            "pseudonym": speaker["pseudonym"],
            "goal": speaker["goal"],
            "takes": speaker["takes"],
            "waiting": sum(t["waiting"] for t in speaker["takes"]),
            "waiting_for_text": sum(1 for t in speaker["takes"] if t["waiting_for_text"]),
        })
    return out


def queue_reads(
    database: Any, rows: list, *, rater_id: Any, bookmarks: Bookmarks,
    goal_rows: Iterable[Any] = (),
) -> dict[str, Any]:
    """Every read the queue makes, side by side, as ``moments_queue``'s own
    keyword arguments: the moments' requests, the reach (N48.2 Q1 A), this
    coach's own ratings, the open asks to listen again, the speakers' goals,
    the panel's rows on the bookmarked clips (routing only, K4, K5) and the
    bookmarks' talk order. ``rows`` are the review queue's rows this coach
    may see (the language gate); ``goal_rows`` more speakers whose goals
    ride the same read (the walk's plans).

    No read below needs another's answer, so they run side by side; the
    results come back in this order and a failed read still raises here
    (founder 2026-10-21: one after another, the queue took 6.7 s). Only the
    frozen sets go first, unless the caller read them already: the labels
    read needs to know which clips are bookmarked (founder 2026-11-09)."""
    from services.coach_listen_again import open_asks
    from services.coach_queue import attempt
    from services.parallel import run_in_parallel
    ids = [str(r.get("id")) for r in rows if isinstance(r, dict)]
    clips = bookmarks.snippet_ids()
    # The clips' two reads go out a chunk per read: one after another, each
    # hundred clips was one more round trip (founder 2026-11-09).
    order, labels = bookmarks.order_reads(), label_reads(database, clips)
    answers = run_in_parallel(
        lambda: database.list_exercise_coach_requests_for_sessions(ids),
        lambda: open_asks(database, coach_id=rater_id, session_ids=ids),
        lambda: database.get_own_state_ratings_for_sessions(ids, rater_id) or {},
        lambda: database.list_moment_events_for_sessions(ids),
        lambda: database.list_confident_voice_answered_moments(ids),
        lambda: speaker_goals(database, [*rows, *goal_rows]),
        *(functools.partial(attempt, read) for read in [*order, *labels]))
    requests, asks, ratings, events, answered, goal_for = answers[:6]
    bookmarks.take_order(answers[6:6 + len(order)])
    labels_for = labels_found(answers[6 + len(order):])
    reached = reached_moments(events, answered, (requests or {}).keys())
    return {
        "reached_for": lambda sid: reached.get(str(sid), set()),
        "ratings_for": lambda sid: ratings.get(str(sid)) or {},
        "request_for": lambda sid, snip: requests.get((sid, snip)),
        "labels_for": labels_for,
        "goal_for": goal_for,
        "listen_again_for": lambda sid: asks.get(str(sid), {}),
    }


def host_chat_of(database: Any) -> Callable[[str], Optional[str]]:
    """``chat_of`` for the reach alarm: the host chat a Take was made in
    (services.take_door.made_in), read only when the alarm fires."""
    from services import take_door
    return lambda take_id: take_door.made_in(database, take_id)


def queue_for_coach(
    database: Any, rows: list, *, rater_id: Any,
    moments_for: Bookmarks,
    pseudonym_for: Callable[[Any], str],
    alarm: bool = True,
) -> list[dict]:
    """The walk's queue for one coach, every read batched (``queue_reads``).
    ``rows`` are the review queue's rows this coach may see (the language
    gate); ``moments_for`` their bookmarks (services.coach_queue)."""
    return moments_queue(
        rows, moments_for=moments_for, pseudonym_for=pseudonym_for,
        rater_id=rater_id, alarm=alarm, chat_of=host_chat_of(database),
        **queue_reads(database, rows, rater_id=rater_id, bookmarks=moments_for))


def _plan_items(database: Any, plans: tuple, events: tuple, *, rater_id: str,
                proficient: list, matched: list, rows: list) -> list[dict]:
    """The plans waiting on this coach (``plan_coach.queue_items``), from
    the reads the walk already made. Best-effort, as before: a failed read
    or step draws the queue without them."""
    from services import plan_coach
    try:
        for _answer, failed in (plans, events):
            if failed is not None:
                raise failed
        return plan_coach.queue_items(
            database, rater_id=rater_id, proficient=proficient,
            matched_users={str(r.get("user_id")) for r in matched},
            queued_users={str(r.get("user_id")) for r in rows},
            plans=plans[0], events=events[0])
    except Exception as e:  # noqa: BLE001 -- the moments are drawn either way
        _log.warning("coach queue: the plans not read: %s", e, exc_info=True)
        return []


def _with_plans(queue: list[dict], items: list[dict], *,
                pseudonym_for: Callable[[Any], str],
                goal_for: Callable[[Any], Optional[str]]) -> list[dict]:
    """The queue with each plan waiting on this coach on its speaker's card
    (N213; routes.v2.coach_plans opens it). A failure draws the queue as it
    was."""
    if not items:
        return queue
    from services import plan_coach
    try:
        return plan_coach.with_plans(queue, items, pseudonym_for=pseudonym_for,
                                     goal_for=goal_for)
    except Exception as e:  # noqa: BLE001 -- the moments are drawn either way
        _log.warning("coach queue: the plans not read: %s", e, exc_info=True)
        return queue


def walk_for_coach(
    database: Any, *, rater_id: str,
    matched_rows: Callable[[list, dict, list], list],
    bookmarked: Callable[[dict, str, Any], Optional[set]],
    pseudonym_for: Callable[[Any], str],
) -> Optional[list[dict]]:
    """The coach's walk (GET /v2/coach/queue/moments): the queue of the
    Takes this coach may hear, with each plan waiting on them on its
    speaker's card (N213). None when the coach has not said which languages
    they understand (the route answers 428).

    Every read goes out as soon as what it needs is known, side by side
    (founder 2026-11-09: the walk took 1.1 s, its reads one after another),
    in three steps, each a named lap in Server-Timing:

      queue_read     the coach's languages, the review queue, the plans;
      language_gate  the language gate (the recordings' languages, when a
                     Take declares none), the plans' events, and every
                     queued Take's frozen set;
      moment_reads   ``queue_reads``, the plans' speakers' goals in the
                     queue's goals read;

    then ``queue_build`` draws it. ``matched_rows(rows, snippets,
    proficient)`` is the route's language gate and ``bookmarked`` its
    reading of a frozen set, handed in. What is listed, and for whom, is
    what the reads one after another gave (BLIND COACH; the reach alarm)."""
    from services import plan_coach
    from services.coach_queue import attempt, bookmarks_for, load_review_queue
    from services.parallel import run_in_parallel
    from services.request_context import timed

    with timed("queue_read"):
        proficient, queued, plans = run_in_parallel(
            lambda: database.get_user_proficient_languages(rater_id),
            lambda: attempt(lambda: load_review_queue(database, snippets=False)),
            lambda: attempt(lambda: database.list_waiting_plans() or []))
    if not proficient:
        return None
    if queued[1] is not None:
        raise queued[1]
    rows, snips, _states = queued[0]
    with timed("language_gate"):
        matched, events, sets = run_in_parallel(
            lambda: matched_rows(rows, snips, proficient),
            lambda: (attempt(lambda: plan_coach.level_events(database, plans[0]))
                     if plans[1] is None else (None, None)),
            lambda: database.get_ideal_text_feedback_sets(
                [r.get("id") for r in rows if r.get("arc_id")]))
    items = _plan_items(database, plans, events, rater_id=rater_id,
                        proficient=proficient, matched=matched, rows=rows)
    bookmarks = bookmarks_for(database, matched, bookmarked, sets=sets)
    with timed("moment_reads"):
        reads = queue_reads(database, matched, rater_id=rater_id, bookmarks=bookmarks,
                            goal_rows=[item["plan"] for item in items])
    with timed("queue_build"):
        queue = moments_queue(matched, moments_for=bookmarks, pseudonym_for=pseudonym_for,
                              rater_id=rater_id, chat_of=host_chat_of(database), **reads)
        return _with_plans(queue, items, pseudonym_for=pseudonym_for,
                           goal_for=reads["goal_for"])
