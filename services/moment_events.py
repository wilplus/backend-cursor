"""The speaker opened or skipped a bookmark (founder 2026-10-01, F1; Phase 2
of the after-practice paths; migration 0408).

"Opening a bookmark never asks for a judgment first. The machine's read
chooses the feedback. The speaker judges themselves after it." So the
moment's coach request rises when the moment OPENS
(``services.judgement_follow_up.follow_up_for_open``), tagged with the
machine's kind, and the open and the skip are recorded once each: the coach
sees them on a requested moment after their own blind rating, and the
coach-load report counts requests per opened moment before and after the
switch.

The event is recorded under either flow (a receipt, like the exercise
render, so the "before" of that report exists); only the request at open
waits for ``Config.JUDGEMENT_AFTER_FEEDBACK_ENABLED``. Nothing here reaches
the speaker beyond "recorded" and what the sheet may show next: no read, no
kind (AC-9, BLIND COACH). The settled read at the bottom is the one rule
that decides, without a Path 1 answer, that a moment is no longer waiting on
the speaker (the practice landed, the practice was dismissed, or the
bookmark was skipped), so the page's bar and the lock gate agree.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

_log = logging.getLogger(__name__)

EVENTS = ("opened", "skipped")
#: What the sheet may say was on screen when the moment opened: the kinds a
#: bookmark can carry. Anything else is dropped, never stored.
CO_EXPOSED = ("question", "praise", "rewrite", "exercise", "coach_request",
              "coach_answer")


def co_exposed_from(body: Any) -> dict:
    """The sheet's own report of what it showed, kept to the known kinds."""
    shown = body.get("shown") if isinstance(body, dict) else None
    kept = ([s for s in shown if isinstance(s, str) and s in CO_EXPOSED]
            if isinstance(shown, list) else [])
    return {"shown": sorted(set(kept))}


def record_moment_event(database: Any, *, user_id: str, snippet_id: str,
                        body: Any) -> tuple[int, dict]:
    """(status, payload) for one open or skip of a bookmark."""
    from services.judgement_follow_up import (
        follow_up_for_open, judgement_after_feedback_enabled,
    )
    fields: dict = body if isinstance(body, dict) else {}
    event = fields.get("event")
    if event not in EVENTS:
        return 400, {"code": "INVALID_INPUT",
                     "error": "event must be opened or skipped"}
    snippet = database.get_snippet_by_id(str(snippet_id))
    session = (database.v2_get_session_by_id(
        str(snippet.get("session_id") or "")) if snippet else None)
    if (not snippet or not session
            or str(session.get("user_id")) != str(user_id)):
        return 404, {"code": "NOT_FOUND", "error": "snippet not found"}
    take_id = str(session.get("id"))
    recorded = database.record_moment_event(
        owner_user_id=str(user_id), take_session_id=take_id,
        snippet_id=str(snippet_id), event=str(event),
        co_exposed=co_exposed_from(fields))
    if recorded and session.get("arc_id"):
        # An open or a skip retires the stored bookmarks too (0429); one
        # debounced rebake per document puts them back (F3). Never raises.
        from services.ideal_text_feedback_bake import (
            request_rebake_after_answer,
        )
        request_rebake_after_answer(session.get("arc_id"), str(user_id))
    follow_up = "none"
    if event == "opened" and judgement_after_feedback_enabled():
        follow_up = follow_up_for_open(
            database, take_session_id=take_id, snippet_id=str(snippet_id),
            owner_user_id=str(user_id))
    return 200, {"recorded": bool(recorded), "follow_up": follow_up}


def settled_status_by_moment(database: Any, *, take_session_id: str,
                             owner_user_id: Optional[str]) -> dict[str, str]:
    """{snippet_id: "approved" | "dismissed"} for the moments of this Take
    the speaker settled WITHOUT a Path 1 answer (F1): a practice that landed
    (Yes or In-between on an attempt, 29a) is approved; a practice dismissed,
    or a bookmark skipped, is dismissed. A practice outranks a skip. Empty on
    any failure: the page then keeps its bar, which is the safe side."""
    from services.practice_adoption import DONE_ANSWERS
    from services.practice_check import machine_closed

    out: dict[str, str] = {}
    try:
        for row in database.list_moment_events_for_take(str(take_session_id)) or []:
            if isinstance(row, dict) and row.get("event") == "skipped" and row.get("snippet_id"):
                out[str(row["snippet_id"])] = "dismissed"
        for row in database.list_confident_voice_practice_for_take(
                str(take_session_id), owner_user_id) or []:
            if not isinstance(row, dict) or not row.get("snippet_id"):
                continue
            status = row.get("status")
            if status == "completed" and (row.get("final_user_answer") in DONE_ANSWERS
                                          or machine_closed(row)):
                out[str(row["snippet_id"])] = "approved"
            elif status in ("completed", "dismissed"):
                out[str(row["snippet_id"])] = "dismissed"
    except Exception as e:  # noqa: BLE001 — the page keeps its bar
        _log.warning("settled read failed take=%s: %s", take_session_id, e,
                     exc_info=True)
        return {}
    return out
