"""What follows the speaker's judgement of a moment (founder 2026-09-29).

A JUDGEMENT IS ALWAYS ANSWERED. Until today a No on a bookmark that was not
the Take's single exercise item led nowhere: no helper words (24e), no
exercise (24f gave the Take one, on the weakest item), no word to the
coach, and the sheet ended. The founder's rule: the bookmark goes to the
coach when nothing in the library matched the moment, and the speaker is
told so. "So at the beginning it will be going to the coach fairly often."

This runs when the answer is SAVED (the feedback-response route), not when
the document is read, because the answer decides it: Audio unclear raises
nothing, and a No raises a request whether or not a problem was recognised,
since the speaker has named one the detectors missed. The request row is
insert-once per moment (migration 0385), so a repeated answer is harmless.

The next read of the Ideal Text serves what the request came to
(``confident_voice_practice._annotate_coach_answers``): the open request as
`coach_request`, or the coach's shared exercise as the item's practice.
"""
from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)

#: Judgements that send the bookmark to the coach when nothing matched.
#: A No does so unconditionally. (Yes, In-between and Not sure follow in the
#: budget change, where the lane opens on every bookmark, and only when a
#: problem was recognised.)
ALWAYS_RAISING = frozenset({"no"})

#: The trace lane written on a request raised at judgement time.
JUDGEMENT_LANE = "v3_judgement"


def route_owner_answer(database: Any, row: dict, *, arc_id: str,
                       take_session_id: str, owner_user_id: str) -> str:
    """The owner's Confident Voice answer as a routing signal, then what
    follows it. Returns the follow-up for the sheet: "exercise",
    "coach_request" or "none".

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
    """What the sheet may show next: "exercise", "coach_request" or "none".

    Never raises: a failure to record the request is logged and reads as
    "none", because the answer itself was already saved and the feedback is
    never lost over its follow-up.
    """
    if not take_session_id or not snippet_id or answer == "audio_unclear":
        return "none"
    if _exercise_on_moment(database, take_session_id, snippet_id):
        return "exercise"
    existing = _request_on_moment(database, take_session_id, snippet_id)
    if existing is not None:
        return "coach_request"
    if answer not in ALWAYS_RAISING:
        return "none"
    return "coach_request" if _raise_request(
        database, take_session_id=take_session_id, snippet_id=snippet_id,
        owner_user_id=owner_user_id) else "none"


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
                   owner_user_id: str) -> bool:
    """Record the coach request for this moment, with what was spotted."""
    from services.confident_voice_practice import (
        _median_wpm, build_match_trace, detected_problem_vocabulary,
        exercise_eligibility, observed_problem_tags, offerable_exercises,
    )

    writer = getattr(database, "request_exercise_from_coach", None)
    if writer is None or not owner_user_id:
        return False
    try:
        snippet = next(iter(
            database.get_confident_voice_practice_candidates([snippet_id])
            or []), None)
        if not isinstance(snippet, dict):
            return False
        verdict = exercise_eligibility(
            snippet, session_median_wpm=_median_wpm(
                database.get_snippets_by_session(take_session_id) or []))
        vocabulary = detected_problem_vocabulary(database)
        observed = observed_problem_tags(verdict, vocabulary=vocabulary)
        writer(
            owner_user_id=str(owner_user_id),
            take_session_id=str(take_session_id), snippet_id=str(snippet_id),
            reason="nothing_targets_it" if observed else "nothing_spotted",
            pattern=verdict.get("pattern"), observed_tags=sorted(observed),
            request_trace=build_match_trace(
                lane=JUDGEMENT_LANE, verdict=verdict, vocabulary=vocabulary,
                exercises=offerable_exercises(database), ranked=[],
                fit=None, snippet=snippet, take_session_id=take_session_id,
                snippet_id=snippet_id))
        return True
    except Exception as e:  # noqa: BLE001 — never lose the answer
        _log.warning("judgement coach request failed take=%s snip=%s: %s",
                     take_session_id, snippet_id, e)
        return False
