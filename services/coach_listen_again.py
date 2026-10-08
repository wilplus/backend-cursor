"""A coach is asked to listen to a moment again, blind (founder 2026-10-06,
QG12a A and P26b A, decisions log N53.4; the three signed lines P26c,
N54.1; Q-B8 A, N62; build plan D-CP-10; migration 0444).

THE RULE. When the speaker's one answer disagrees with the machine's read
of the same moment (the follow-up matrix's ambiguity, QG12a A), every coach
who already gave a blind judgment of record on that moment gets the moment
back in their usual work list (P26b A) as a `listen_again` item carrying
exactly one thing: the key of one of the three signed lines (P26c). The
row has no reason, no answer and no read, by its shape (0444), and the
queue row carries no kind. While the ask is open the server treats that
coach as not having rated the moment, so every door the blind gate guards
(the moment read, the drafts, the named errors, the speaker's answer, the
transcript release) is shut again until the coach's new blind answer lands
(BLIND COACH). The new answer is a reconsideration (contract 34, 0427): the
original judgment stands in confidence_labels, the second in
label_revision.

WHAT IT IS NOT. Not a score (AC-9); not a label (L3: the speaker's answer
is read by the matrix and never copied anywhere a coach reads); not in the
speaker's way (the flag is a side write that never raises, LIVE LOOP).

THE WORDS. The three lines live in docs/SIGNED-line-bank-2026-10-06.md
("The coach's work list (P26c A)"); the backend serves their keys, the
panel shows the words. tests/test_coach_listen_again.py holds parity.
"""
from __future__ import annotations

import logging
from typing import Any, Final, Iterable, Optional

_log = logging.getLogger(__name__)

#: The queue state of a moment with an open ask (services.coach_moments_queue).
STATE: Final = "listen_again"

#: The three signed lines, by key (N54.1, P26c A). Byte-identical to the
#: signed markdown; the panel shows them, the server sends the key.
LINES: Final[dict[str, str]] = {
    "P26c-A": "Please listen to this moment once more.",
    "P26c-B": "A second listen, please.",
    "P26c-C": "This moment needs another listen.",
}
LINE_KEYS: Final[tuple[str, ...]] = tuple(LINES)


def flag_disagreement(database: Any, *, take_session_id: Any,
                      snippet_id: Any) -> int:
    """The disagreement flag fired on this moment (QG12a A): ask every coach
    with a judgment of record to listen again. Returns the number of asks
    written, for the log; 0 when none was needed or the write failed. Never
    raises: the speaker's answer is already saved."""
    if not take_session_id or not snippet_id:
        return 0
    writer = getattr(database, "request_coach_listen_again", None)
    if writer is None:
        return 0
    try:
        written = writer(str(take_session_id), str(snippet_id))
    except Exception as e:  # noqa: BLE001 -- a side write, named, never raised
        _log.warning("listen-again ask not written take=%s snip=%s: %s",
                     take_session_id, snippet_id, e, exc_info=True)
        return 0
    try:
        count = int(written or 0)
    except (TypeError, ValueError):
        count = 0
    if count:
        _log.info("listen-again asked take=%s snip=%s coaches=%d",
                  take_session_id, snippet_id, count)
    return count


def mark_heard(database: Any, *, snippet_id: Any, coach_id: Any) -> int:
    """This coach's new blind answer landed on the moment: close their open
    ask. Returns rows closed; never raises (the rating is already saved)."""
    if not snippet_id or not coach_id:
        return 0
    writer = getattr(database, "mark_coach_listen_again_heard", None)
    if writer is None:
        return 0
    try:
        closed = writer(str(snippet_id), str(coach_id))
    except Exception as e:  # noqa: BLE001 -- the rating stands
        _log.warning("listen-again ask not closed snip=%s: %s", snippet_id, e,
                     exc_info=True)
        return 0
    try:
        return int(closed or 0)
    except (TypeError, ValueError):
        return 0


def open_asks(database: Any, *, coach_id: Any,
              session_ids: Iterable[Any]) -> dict[str, dict[str, str]]:
    """{take_session_id: {snippet_id: line_key}} for this coach's open asks
    on these Takes. A failed read is an empty map and a log line: the
    queue then lists the moments as it did before the ask, never with a
    guess."""
    ids = [str(s) for s in session_ids or [] if s]
    if not coach_id or not ids:
        return {}
    reader = getattr(database, "list_open_coach_listen_again", None)
    if reader is None:
        return {}
    try:
        rows = reader(str(coach_id), ids) or []
    except Exception as e:  # noqa: BLE001 -- named, never a guess
        _log.warning("listen-again asks not read coach=%s: %s", coach_id, e,
                     exc_info=True)
        return {}
    out: dict[str, dict[str, str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        take, snip, key = row.get("take_session_id"), row.get("snippet_id"), row.get("line_key")
        if take and snip and key in LINES:
            out.setdefault(str(take), {})[str(snip)] = str(key)
    return out


def masked_state(state: Optional[dict], line_key: str) -> dict:
    """The coach_state of a moment with an open ask: the coach's own earlier
    answer is masked, so every door keyed on it (the blind gate, the
    transcript and owner-answer release, the practice door) is shut again
    until the new blind answer lands. The key rides so the panel can show
    the signed line."""
    out = dict(state or {})
    out["rating_value"] = None
    out["rating_unrateable"] = False
    out["listen_again"] = line_key
    return out


def mask_states(states: dict, asks: dict[str, str]) -> dict:
    """Apply `masked_state` to every snippet in `asks` (snippet -> key),
    adding a row for a snippet the state map did not carry."""
    if not asks:
        return states
    out = dict(states)
    for snippet_id, key in asks.items():
        base = out.get(str(snippet_id)) or {
            "note": "", "tag": None, "surfaced": False,
            "transcript_corrected": None,
            "rating_value": None, "rating_unrateable": False,
        }
        out[str(snippet_id)] = masked_state(base, key)
    return out


def queue_row(snippet_id: str, line_key: str) -> dict:
    """The queue's row for a moment with an open ask: the moment, the state
    and the line key. No kind, no answer, no reason (BLIND COACH)."""
    return {"snippet_id": str(snippet_id), "state": STATE, "line_key": line_key}
