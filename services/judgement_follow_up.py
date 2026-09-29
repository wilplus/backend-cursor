"""What follows the speaker's judgement of a moment: the follow-up matrix
(founder 2026-09-29, contract 24f as amended, 35g-2).

A JUDGEMENT IS ALWAYS ANSWERED. The speaker's answer, crossed with how the
machine read the same clip, decides two things:

  * what shows NOW: praise or a rewrite (the Manager's anchored notes,
    where it found one), the library video matched to the clip, or nothing;
  * under which KIND the bookmark reaches the coach: an error the detectors
    named, praise, a rewrite, or an ambiguity (the speaker and the machine
    disagree). Every answer but Audio unclear goes to the coach. The coach
    records a video for errors by default and may for the rest; a shared
    video rides the moment on the next read.

The matrix, as the founder agreed it:

    answer       read confident     read weak, fired     read weak, not fired
    Yes          praise · praise    nothing · ambiguity  nothing · ambiguity
    In-between   praise · praise    video · error        rewrite · rewrite
    No           praise · ambiguity video · error        rewrite · rewrite
    Not sure     praise · ambiguity video · ambiguity    rewrite · ambiguity
    Audio unclear  nothing, no request

"video" is the library exercise matched to the clip, or the coach request
alone when the library has none (the sentence "Your coach is working on
your exercise", errors only). A read the machine could not make is treated
as weak with nothing fired for what shows, and reaches the coach as an
ambiguity. The read chooses and is never surfaced (AC-9); praise and
rewrites show only where an evidence-backed one exists (L2).

This runs when the answer is SAVED (the feedback-response route), because
the answer decides it. The request row is insert-once per moment.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

_log = logging.getLogger(__name__)

#: The trace lane written on a request raised at judgement time.
JUDGEMENT_LANE = "v3_judgement"

ANSWERS = ("yes", "in_between", "no", "not_sure", "audio_unclear")
KINDS = ("error", "praise", "rewrite", "ambiguity")


def decide(answer: Any, read: str, fired: bool,
           matched: bool) -> tuple[str, Optional[str]]:
    """The cell of the matrix: (what shows now, the kind for the coach).

    `now` is one of "praise", "rewrite", "exercise", "coach_request", "none".
    `kind` is None only for Audio unclear, which raises nothing.
    """
    if answer == "audio_unclear" or answer not in ANSWERS:
        return "none", None
    if read == "confident":
        kind = "praise" if answer in ("yes", "in_between") else "ambiguity"
        return "praise", kind
    if answer == "yes":
        return "none", "ambiguity"
    if read == "weak" and fired:
        now = "exercise" if matched else "coach_request"
        return now, "error" if answer in ("in_between", "no") else "ambiguity"
    if read == "weak":
        return "rewrite", "rewrite" if answer in ("in_between", "no") else "ambiguity"
    # The machine could not read the clip: nothing to show for it, and a
    # human ear settles it.
    return "none", "ambiguity"


def route_owner_answer(database: Any, row: dict, *, arc_id: str,
                       take_session_id: str, owner_user_id: str) -> str:
    """The owner's Confident Voice answer as a routing signal, then what
    follows it. Returns the follow-up for the sheet.

    The route row is the speaker's self-report on the Voice Album lane
    (never a rating; contract 30, 31). The follow-up runs after the route is
    written and never fails the save. Lived in the answer route until
    2026-09-29; here so the route stays within its fence.
    """
    if row.get("feedback_family") != "confident_voice" or not row.get("snippet_id"):
        return "none"
    response = row.get("response")
    routing = (
        "yes" if response == "yes"
        else "no" if response == "no"
        else "unrateable" if response == "audio_unclear"
        else "neutral"
    )
    snip = database.get_snippet_by_id(row["snippet_id"]) or {}
    piece = ((snip.get("metrics") or {}).get("piece")
             if isinstance(snip.get("metrics"), dict) else {})
    database.upsert_owner_voice_album_route(
        snippet_id=row["snippet_id"],
        owner_user_id=owner_user_id,
        arc_id=arc_id,
        response=routing,
        slide_index=(piece.get("slide_index")
                     if isinstance(piece, dict) else None),
    )
    from services.voice_album import refresh_voice_album
    refresh_voice_album(arc_id, database=database)
    return follow_up_for_judgement(
        database, take_session_id=take_session_id,
        snippet_id=str(row["snippet_id"]),
        owner_user_id=owner_user_id, answer=response)


def follow_up_for_judgement(
    database: Any, *, take_session_id: str, snippet_id: str,
    owner_user_id: str, answer: Any,
) -> str:
    """The matrix applied to this moment: what the sheet may show next, and
    the bookmark sent to the coach with its kind.

    Never raises: a failure to record the request is logged, and the answer
    itself was already saved.
    """
    if not take_session_id or not snippet_id:
        return "none"
    if answer == "audio_unclear" or answer not in ANSWERS:
        return "none"
    clip = _clip_read(database, take_session_id, snippet_id)
    if clip is None:
        return "none"
    matched = _exercise_on_moment(database, take_session_id, snippet_id)
    now, kind = decide(answer, clip["read"], bool(clip["observed"]), matched)
    if kind is None:
        return now
    if _request_on_moment(database, take_session_id, snippet_id) is None:
        raised = _raise_request(
            database, take_session_id=take_session_id, snippet_id=snippet_id,
            owner_user_id=owner_user_id, kind=kind, clip=clip, matched=matched)
        # The sentence is a promise: without the request it would be false.
        if now == "coach_request" and not raised:
            return "none"
    return now


def _clip_read(database: Any, take_session_id: str,
               snippet_id: str) -> Optional[dict]:
    """The machine's read of the clip and what fired on it, as the lane
    computes them. None when the clip cannot be read at all."""
    from services.confident_voice_practice import (
        _median_wpm, detected_problem_vocabulary, exercise_eligibility,
        machine_read, observed_problem_tags,
    )
    try:
        snippet = next(iter(
            database.get_confident_voice_practice_candidates([snippet_id])
            or []), None)
        if not isinstance(snippet, dict):
            return None
        verdict = exercise_eligibility(
            snippet, session_median_wpm=_median_wpm(
                database.get_snippets_by_session(take_session_id) or []))
        vocabulary = detected_problem_vocabulary(database)
        return {
            "snippet": snippet, "verdict": verdict, "vocabulary": vocabulary,
            "read": machine_read(verdict),
            "observed": observed_problem_tags(verdict, vocabulary=vocabulary),
        }
    except Exception as e:  # noqa: BLE001 — never lose the answer
        _log.warning("judgement clip read failed take=%s snip=%s: %s",
                     take_session_id, snippet_id, e)
        return None


def _exercise_on_moment(database: Any, take_session_id: str,
                        snippet_id: str) -> bool:
    """A frozen 80/20 draw for this moment: the item already carries one."""
    getter = getattr(database, "get_confident_voice_exercise_assignment", None)
    if getter is None:
        return False
    try:
        return isinstance(getter(take_session_id, snippet_id), dict)
    except Exception as e:  # noqa: BLE001 — a failed read is "no exercise"
        _log.warning("assignment read failed take=%s snip=%s: %s",
                     take_session_id, snippet_id, e)
        return False


def _request_on_moment(database: Any, take_session_id: str,
                       snippet_id: str) -> Any:
    getter = getattr(database, "get_exercise_coach_request", None)
    if getter is None:
        return None
    try:
        request = getter(take_session_id, snippet_id)
    except Exception as e:  # noqa: BLE001
        _log.warning("coach request read failed take=%s snip=%s: %s",
                     take_session_id, snippet_id, e)
        return None
    return request if isinstance(request, dict) else None


def _raise_request(database: Any, *, take_session_id: str, snippet_id: str,
                   owner_user_id: str, kind: str, clip: dict,
                   matched: bool) -> bool:
    """Record the coach request for this moment, with its kind and what the
    detectors found."""
    from services.confident_voice_practice import (
        build_match_trace, offerable_exercises,
    )

    writer = getattr(database, "request_exercise_from_coach", None)
    if writer is None or not owner_user_id:
        return False
    observed = clip["observed"]
    reason = ("library_matched" if matched
              else "nothing_targets_it" if observed
              else "nothing_spotted")
    try:
        writer(
            owner_user_id=str(owner_user_id),
            take_session_id=str(take_session_id), snippet_id=str(snippet_id),
            reason=reason, kind=kind,
            pattern=clip["verdict"].get("pattern"),
            observed_tags=sorted(observed),
            request_trace=build_match_trace(
                lane=JUDGEMENT_LANE, verdict=clip["verdict"],
                vocabulary=clip["vocabulary"],
                exercises=offerable_exercises(database), ranked=[],
                fit=None, snippet=clip["snippet"],
                take_session_id=take_session_id, snippet_id=snippet_id))
        return True
    except Exception as e:  # noqa: BLE001 — never lose the answer
        _log.warning("judgement coach request failed take=%s snip=%s: %s",
                     take_session_id, snippet_id, e)
        return False
