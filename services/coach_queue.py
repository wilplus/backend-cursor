"""Loading the coach's review queue — in three reads, not two per take.

FOUNDER 2026-09-25: "shorten the loading times on the coach panel."

The route used to call `get_snippets_by_session` and `_coach_state_map` once
per queued take. Forty takes meant eighty round trips before a coach saw a
list, and each read served one small thing: a language match plus a count,
and a lifecycle pill. Neither is worth a round trip of its own.

WHY THIS IS A SERVICE AND NOT A ROUTE HELPER. The route fence measures every
function under ``routes/``, not only the decorated ones, and caps them at one
database call: "a route validates, authorises, calls one service function,
serialises." A loop making raw reads was never one of those four, and neither
is a three-read prefetch sitting beside it. The fence caught exactly that and
said to move it here.
"""
from __future__ import annotations

from typing import Any, Callable, Optional


def load_review_queue(
    database: Any, state_for: Callable[..., dict],
) -> tuple[list, dict, dict]:
    """The queue's rows, their snippets, and their coach state.

    Returns ``(rows, snippets_by_session, coach_state_by_session)``, both maps
    keyed by session id as a string.

    ``state_for`` is the caller's own state builder, handed in rather than
    imported: the shape of a coach state belongs to the surface that renders
    it, and this function's job is only to make sure it is built from rows
    that were already fetched instead of from a fresh read per take. It is
    called as ``state_for(session_id, draft_rows=rows)``.

    Best-effort in the same way every read on this path is: a batch that
    returns nothing yields empty companions rather than raising, and the
    queue still draws with a blank pill instead of failing to load at all.
    """
    rows = database.list_review_queue() or []
    ids = [r.get("id") for r in rows if r.get("id")]
    if not ids:
        return rows, {}, {}
    snippets = database.get_snippets_by_sessions(ids) or {}
    drafts = database.get_coach_snippet_drafts_by_sessions(ids) or {}
    states = {
        str(i): state_for(i, draft_rows=drafts.get(str(i)) or [])
        for i in ids
    }
    return rows, snippets, states


def frozen_feedback_sets(database: Any, rows: list) -> Optional[dict]:
    """{take_session_id: [frozen selection rows]} for the queue's Takes in
    one read, or None when the batch cannot be had: each Take is then read
    alone, exactly as before (founder 2026-10-18: "I want the speakers to
    open faster"; one read per Take was most of the queue's wait)."""
    reader = getattr(database, "get_ideal_text_feedback_sets_for_takes", None)
    ids = [str(r.get("id")) for r in rows or [] if isinstance(r, dict) and r.get("id")]
    if reader is None or not ids:
        return None
    return reader(ids)
