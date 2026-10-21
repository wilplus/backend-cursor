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

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


_QUEUE_SNIPPET_COLUMNS = "id, session_id, start_offset_ms"


def load_review_queue(
    database: Any, state_for: Optional[Callable[..., dict]] = None, *,
    snippets: bool = True,
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

    ``snippets=False`` skips the read of every piece of every queued Take
    and returns no snippets: the walk, the speakers, the bubbles and the
    founder's close order only the bookmarked moments, from
    ``bookmarks_for`` (founder 2026-10-21, the queue took 6.7 s). Their
    language gate loses nothing: this projection carries no language.

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
    pieces = (database.get_snippets_by_sessions(
        ids, columns=_QUEUE_SNIPPET_COLUMNS) or {}) if snippets else {}
    if state_for is None:
        return rows, pieces, {}
    drafts = database.get_coach_snippet_drafts_by_sessions(ids) or {}
    states = {
        str(i): state_for(i, draft_rows=drafts.get(str(i)) or [])
        for i in ids
    }
    return rows, pieces, states


def _talk_order(row: dict) -> tuple:
    """A snippet's place in its talk, as the batch read ordered it:
    ``start_offset_ms`` with nulls last, then ``id``."""
    offset = row.get("start_offset_ms")
    return (offset is None, offset if offset is not None else 0, str(row.get("id")))


def bookmarks_for(
    database: Any, rows: list,
    bookmarked: Callable[[dict, str, Any], Optional[set]],
) -> Callable[[dict], Optional[list]]:
    """The queue's ``moments_for``: a Take's bookmarked snippet ids in talk
    order, or None while its bookmarks are not frozen yet (the Take rides as
    "Waiting for the text", founder 2026-10-01, A1).

    ``bookmarked(row, session_id, feedback_sets)`` is the route's own reading
    of a Take's frozen selection, handed in. On the first call, two reads
    serve every row in ``rows``: their frozen sets, and the order of only
    the bookmarked snippets, never every piece of every Take (founder
    2026-10-21). Same set and order as before: the snippets that exist in
    that Take, by ``start_offset_ms`` then ``id``."""
    loaded: dict[str, Any] = {}

    def load() -> None:
        sets = database.get_ideal_text_feedback_sets(
            [r.get("id") for r in rows if r.get("arc_id")])
        marked = {str(r.get("id")): bookmarked(r, str(r.get("id")), sets)
                  for r in rows if isinstance(r, dict)}
        wanted = {i for m in marked.values() if m for i in m}
        ordered: dict[str, list] = {}
        for snip in sorted(database.get_snippet_order_by_ids(wanted) or [],
                           key=_talk_order):
            sid, snip_id = str(snip.get("session_id")), str(snip.get("id"))
            if snip_id in (marked.get(sid) or ()):
                ordered.setdefault(sid, []).append(snip_id)
        loaded.update(sets=sets, marked=marked, ordered=ordered)

    def moments_for(row: dict) -> Optional[list]:
        if not loaded:
            load()
        sid = str(row.get("id"))
        if sid not in loaded["marked"]:
            loaded["marked"][sid] = bookmarked(row, sid, loaded["sets"])
        if loaded["marked"][sid] is None:
            logger.info("coach queue: take waiting for the text sid=%s "
                        "filter=bookmarks_not_frozen", sid)
            return None
        return list(loaded["ordered"].get(sid) or [])
    return moments_for
