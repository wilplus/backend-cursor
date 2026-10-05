"""The coach's judgement of a practice recording (founder 2026-10-05, Q6;
decisions log N45).

The coach's practice judgement left with the old panel on 1 October (#574)
without a decision to retire it. Since then no practice attempt could enter
the Voice Album, and "did the practice help" recorded nothing. It comes back
on the walk's Read screen as the one instrument (A1): the speaker's chosen
practice recording and the same five answers. This module is the narrow
write behind it: one answer on the selected attempt, the after-practice
record, and the Album reconciliation the old route ran. No exercise, no
share, no decision on the moment: those stay where they are.

BLIND COACH: the route serves this only after the coach's own rating of the
original moment (the moment gate). The machine's read of the attempt is
never shown; the coach sees only their own saved answer.

WRITTEN ONCE (LOCKIN §5c; contract 34; W6 2026-10-05): "the original coach
judgment is never editable". A recording that already carries a coach's
answer keeps it: a second answer is refused (409, with the answer that
stands) and never overwrites the attempt's coach decision.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services.practice_adoption import ANSWERS

_log = logging.getLogger(__name__)


def selected_practice(database: Any, take_session_id: str,
                      snippet_id: str) -> Optional[dict]:
    """The speaker's chosen practice recording on this moment, for the Read
    screen: ``{"attempt_id", "audio_ref", "duration_ms", "coach_answer"}``,
    or None when there is no practice or nothing was chosen."""
    getter = getattr(database, "get_confident_voice_practice_by_moment", None)
    if getter is None:
        return None
    try:
        practice = getter(str(take_session_id), str(snippet_id))
        if not isinstance(practice, dict) or str(practice.get("snippet_id")) != str(snippet_id):
            return None
        selected = str(practice.get("selected_attempt_id") or "")
        if not selected:
            return None
        rows = database.list_confident_voice_practice_attempts(str(practice.get("id"))) or []
    except Exception as e:  # noqa: BLE001 -- the Read screen still draws
        _log.warning("selected practice read failed take=%s snip=%s: %s",
                     take_session_id, snippet_id, e, exc_info=True)
        return None
    row = next((r for r in rows if isinstance(r, dict) and str(r.get("id")) == selected), None)
    if row is None:
        return None
    from services.audio_ref_resolver import resolve_playable_ref
    return {
        "attempt_id": selected,
        "audio_ref": resolve_playable_ref(row.get("audio_ref")),
        "duration_ms": row.get("duration_ms"),
        "coach_answer": row.get("coach_confidence_decision"),
    }


def judge_selected_attempt(database: Any, *, take_session_id: str, snippet_id: str,
                           body: Any, coach_id: str) -> tuple[int, dict]:
    """PUT {answer}: the coach's answer on the selected practice recording."""
    answer = (body or {}).get("answer") if isinstance(body, dict) else None
    if answer not in ANSWERS:
        return 400, {"code": "INVALID_INPUT",
                     "error": "answer must be one of the five answers"}
    practice = database.get_confident_voice_practice_by_moment(
        str(take_session_id), str(snippet_id))
    if not isinstance(practice, dict) or str(practice.get("snippet_id")) != str(snippet_id):
        return 404, {"code": "NOT_FOUND", "error": "No practice on this moment."}
    selected = str(practice.get("selected_attempt_id") or "")
    if not selected:
        return 409, {"code": "NO_SELECTED_ATTEMPT",
                     "error": "The speaker has not chosen a recording yet."}
    written = database.set_confident_voice_practice_attempt_coach_decision(
        str(practice.get("id")), selected, str(answer), str(coach_id))
    if not written:
        return 503, {"code": "V2_ERROR", "error": "Could not save the judgement."}
    if isinstance(written, dict) and written.get("already_decided"):
        # LOCKIN §5c, contract 34 (W6 2026-10-05): the original judgement
        # of this recording stands; this route never writes over it.
        return 409, {"code": "PRACTICE_ALREADY_JUDGED",
                     "error": "This moment already has your answer; it cannot be changed.",
                     "answer": written.get("coach_confidence_decision")}
    from services.practice_more_confident import record_after_coach_decision
    record_after_coach_decision(database, str(practice.get("id")), selected)
    _reconcile_album(database, practice)
    return 200, {"answer": answer}


def _reconcile_album(database: Any, practice: dict) -> None:
    """The practice attempt may now align its three legs (L3)."""
    try:
        fresh = database.get_confident_voice_practice_by_moment(
            str(practice.get("take_session_id")), str(practice.get("snippet_id"))) or practice
        from services.confident_voice_practice import reconcile_practice_voice_album
        if reconcile_practice_voice_album(fresh, database=database):
            from services.arc_notifications import fire_voice_album_ready
            fire_voice_album_ready(
                database, practice.get("owner_user_id"), practice.get("project_id"))
    except Exception as e:  # noqa: BLE001 -- the judgement stands
        _log.warning("practice album reconcile failed practice=%s: %s",
                     practice.get("id"), e, exc_info=True)
