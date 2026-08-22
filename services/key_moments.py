"""Select coach-confirmed confidence moments for live product surfaces.

Peer quorum belongs exclusively to internal training and evaluation. A live
key moment therefore requires the latest explicit professional-coach Yes.
Owner routes, peer ratings, bootstrap labels, and machine proposals cannot
satisfy this selector.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

# The settled value that makes a moment KEY. `no` and the ambiguous class are
# settled too — they are simply not this.
KEY_VALUE = "yes"


def confidence_verdicts(database, snippet_ids: Iterable[Any]) -> dict:
    """``{snippet_id: yes|no}`` from professional coaches only."""
    from services.professional_confidence import professional_verdicts
    return professional_verdicts(database, snippet_ids)


def key_snippet_ids(database, snippet_ids: Iterable[Any]) -> set:
    """The subset whose latest professional confidence verdict is Yes."""
    return {
        sid for sid, value in
        confidence_verdicts(database, snippet_ids).items()
        if value == KEY_VALUE
    }


def is_key_moment(database, snippet_id: Optional[Any]) -> bool:
    """Single-snippet convenience. Prefer the batched selector for a set."""
    if not snippet_id:
        return False
    return str(snippet_id) in key_snippet_ids(database, [snippet_id])
