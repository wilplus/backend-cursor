"""The coach's Read screen, one source (founder 2026-09-30, A2; build plan
P2-10).

After the coach's own blind rating, and only then, one read gives the
moment as the coach may now see it: the passage, the speaker's answer,
the coach's own answer, the request that reached the coach (kind, what
fired in words, library status) or None when nothing did, the patterns
the coach has named on it, and the speaker's goal. Everything in words;
no count of anything (AC-9). The route enforces the blind gate before
this runs (BLIND COACH): nothing here checks it again, and nothing here
must be reachable another way.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

_log = logging.getLogger(__name__)

_ANSWERS = ("yes", "in_between", "no", "not_sure", "audio_unclear")


def _passage(database: Any, take_session_id: str, snippet_id: str) -> dict:
    for row in database.get_snippets_by_session(take_session_id) or []:
        if isinstance(row, dict) and str(row.get("id")) == snippet_id:
            return {"passage": str(row.get("transcript") or "").strip(),
                    "slide_index": row.get("slide_index")}
    return {"passage": "", "slide_index": None}


def _speaker_answer(database: Any, snippet_id: str) -> Optional[str]:
    reader = getattr(database, "list_take_feedback_self_reports_by_snippet", None)
    if reader is None:
        return None
    answer = None
    for row in reader(snippet_id) or []:
        if not isinstance(row, dict):
            continue
        if row.get("feedback_family") not in (None, "confident_voice"):
            continue
        value = str(row.get("response") or "")
        if value in _ANSWERS:
            answer = value  # ordered by created_at: the last is current
    return answer


def _coach_answer(database: Any, take_session_id: str, snippet_id: str,
                  rater_id: str) -> Optional[str]:
    ratings = database.get_own_state_ratings_for_session(take_session_id, rater_id) or {}
    own = ratings.get(snippet_id)
    if not isinstance(own, dict):
        return None
    if own.get("unrateable"):
        return "audio_unclear"
    value = own.get("value")
    return str(value) if value in _ANSWERS else None


def _goal(database: Any, owner_user_id: Any) -> Optional[str]:
    if not owner_user_id or not hasattr(database, "get_user_profile"):
        return None
    try:
        profile = database.get_user_profile(str(owner_user_id))
    except Exception as e:  # noqa: BLE001 -- the goal is a courtesy
        _log.info("speaker goal unavailable: %s", e)
        return None
    goal = (profile or {}).get("goal") if isinstance(profile, dict) else None
    return str(goal).strip() or None if goal else None


def moment_read(database: Any, *, take_session_id: str, snippet_id: str,
                rater_id: str, owner_user_id: Any) -> dict:
    """Everything the Read screen shows, after the gate."""
    from services.exercise_coach_requests import coach_request_payload
    take, snip = str(take_session_id), str(snippet_id)
    request = database.get_exercise_coach_request(take, snip)
    # Task 4 (0411): the Read screen is the clip's non-blind side. From
    # here on a rating by this coach on this clip is not blind; the first
    # exposure stands and a repeat read records nothing new.
    from services.coach_exposure import record_exposure
    record_exposure(database, coach_id=str(rater_id), clip_id=snip, via="moment_read")
    return {
        **_passage(database, take, snip),
        "speaker_answer": _speaker_answer(database, snip),
        "coach_answer": _coach_answer(database, take, snip, str(rater_id)),
        "speaker_goal": _goal(database, owner_user_id),
        "request": (coach_request_payload(request, database)
                    if isinstance(request, dict) else None),
    }
