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

import functools
import logging
from typing import Any, Callable, Iterable, Optional

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


def attempt(read: Callable[[], Any]) -> tuple[Any, Optional[Exception]]:
    """``(answer, None)``, or ``(None, the failure)`` for the caller to raise
    or log when its turn comes: the queue reads ahead, side by side, and a
    failure must answer as it did when that read came alone."""
    try:
        return read(), None
    except Exception as e:  # noqa: BLE001 -- handed back; the caller raises or logs it
        return None, e


def _talk_order(row: dict) -> tuple:
    """A snippet's place in its talk, as the batch read ordered it:
    ``start_offset_ms`` with nulls last, then ``id``."""
    offset = row.get("start_offset_ms")
    return (offset is None, offset if offset is not None else 0, str(row.get("id")))


class Bookmarks:
    """The queue's ``moments_for``: a Take's bookmarked snippet ids in talk
    order, or None while its bookmarks are not frozen yet (the Take rides as
    "Waiting for the text", founder 2026-10-01, A1).

    ``bookmarked(row, session_id, feedback_sets)`` is the route's own reading
    of a Take's frozen selection, handed in. Two reads serve every row in
    ``rows``: their frozen sets, and the order of only the bookmarked
    snippets, never every piece of every Take (founder 2026-10-21). Same set
    and order as before: the snippets that exist in that Take, by
    ``start_offset_ms`` then ``id``.

    Both reads happen on the first call, or where a caller puts them beside
    its own reads (founder 2026-11-09, the walk took 1.1 s): ``sets`` handed
    in is the first read already made, ``snippet_ids`` names the bookmarked
    clips once the sets are in, and ``order_reads`` is the second read, one
    per chunk of ``ORDER_CHUNK`` clips, whose answers go to ``take_order``.
    """

    #: Clips per order read, as ``db.get_snippet_order_by_ids`` reads them:
    #: an ``in`` filter rides the URL.
    ORDER_CHUNK = 100

    def __init__(self, database: Any, rows: list,
                 bookmarked: Callable[[dict, str, Any], Optional[set]], *,
                 sets: Optional[dict] = None) -> None:
        self._database = database
        self._rows = rows
        self._bookmarked = bookmarked
        self._sets = sets
        self._marked: Optional[dict[str, Optional[set]]] = None
        self._ordered: Optional[dict[str, list]] = None

    def _marks(self) -> dict[str, Optional[set]]:
        if self._marked is None:
            if self._sets is None:
                self._sets = self._database.get_ideal_text_feedback_sets(
                    [r.get("id") for r in self._rows if r.get("arc_id")])
            self._marked = {
                str(r.get("id")): self._bookmarked(r, str(r.get("id")), self._sets)
                for r in self._rows if isinstance(r, dict)}
        return self._marked

    def snippet_ids(self) -> set[str]:
        """Every bookmarked snippet of every row (the frozen sets are read
        first, unless they were handed in)."""
        return {i for m in self._marks().values() if m for i in m}

    def order_reads(self) -> list[Callable[[], list]]:
        """The second read, one read per chunk of the bookmarked clips, for a
        caller to run beside its own reads. Each raises when it fails."""
        ids = sorted(self.snippet_ids())
        return [functools.partial(self._database.get_snippet_order_by_ids,
                                  ids[i:i + self.ORDER_CHUNK], strict=True)
                for i in range(0, len(ids), self.ORDER_CHUNK)]

    def take_order(self, answers: Iterable[tuple[Any, Optional[Exception]]]) -> None:
        """The order reads' answers, ``(rows, failure)`` each, in any order.
        One failed chunk lists no moments for any Take (the read logged it),
        as the one read did: never a Take with some of its moments."""
        pairs = list(answers)
        failed = any(failure is not None for _rows, failure in pairs)
        snippets = [] if failed else [row for rows, _f in pairs for row in rows or []]
        marked = self._marks()
        ordered: dict[str, list] = {}
        for snip in sorted(snippets, key=_talk_order):
            sid, snip_id = str(snip.get("session_id")), str(snip.get("id"))
            if snip_id in (marked.get(sid) or ()):
                ordered.setdefault(sid, []).append(snip_id)
        self._ordered = ordered

    def read_order(self) -> None:
        """The second read, its chunks one after another, for a caller with
        nothing to read beside it."""
        if self._ordered is None:
            self.take_order(attempt(read) for read in self.order_reads())

    def __call__(self, row: dict) -> Optional[list]:
        self.read_order()
        marked = self._marks()
        sid = str(row.get("id"))
        if sid not in marked:
            marked[sid] = self._bookmarked(row, sid, self._sets)
        if marked[sid] is None:
            logger.info("coach queue: take waiting for the text sid=%s "
                        "filter=bookmarks_not_frozen", sid)
            return None
        return list((self._ordered or {}).get(sid) or [])


def bookmarks_for(
    database: Any, rows: list,
    bookmarked: Callable[[dict, str, Any], Optional[set]], *,
    sets: Optional[dict] = None,
) -> Bookmarks:
    """The queue's ``moments_for`` for ``rows`` (``Bookmarks``); ``sets``
    when the caller has read the rows' frozen sets already."""
    return Bookmarks(database, rows, bookmarked, sets=sets)
