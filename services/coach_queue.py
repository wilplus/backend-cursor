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


_QUEUE_SNIPPET_COLUMNS = "id, session_id, start_offset_ms"


def load_review_queue(
    database: Any, state_for: Optional[Callable[..., dict]] = None,
) -> tuple[list, dict, dict]:
    """The queue's rows, their snippets, and their coach state.

    Returns ``(rows, snippets_by_session, coach_state_by_session)``, both maps
    keyed by session id as a string.

    ``state_for`` is the caller's own state builder, handed in rather than
    imported: the shape of a coach state belongs to the surface that renders
    it, and this function's job is only to make sure it is built from rows
    that were already fetched instead of from a fresh read per take. It is
    called as ``state_for(session_id, draft_rows=rows)``. None skips the
    drafts read and returns no states: the walk, the speakers and the
    bubbles never read a pill, and every draft of the queue was a wide read
    for nothing on them (founder 2026-10-18, the coach panel's load time).

    Best-effort in the same way every read on this path is: a batch that
    returns nothing yields empty companions rather than raising, and the
    queue still draws with a blank pill instead of failing to load at all.
    """
    rows = database.list_review_queue() or []
    ids = [r.get("id") for r in rows if r.get("id")]
    if not ids:
        return rows, {}, {}
    # Ids and order are all the queues read from a snippet (the moments,
    # the count); transcripts and metrics were most of the bytes.
    snippets = database.get_snippets_by_sessions(
        ids, columns=_QUEUE_SNIPPET_COLUMNS) or {}
    if state_for is None:
        return rows, snippets, {}
    drafts = database.get_coach_snippet_drafts_by_sessions(ids) or {}
    states = {
        str(i): state_for(i, draft_rows=drafts.get(str(i)) or [])
        for i in ids
    }
    return rows, snippets, states
