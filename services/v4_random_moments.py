"""A Take's seeded random 20% of moments (V4 Phase 1, B1.2; build plan
D-ML-7; founder V2 A "from all moments", V3 A "round up"; migration 0447).

THE RULE. A moment is one block of the Take's dark frame (about 75 words,
slide-bounded; contract 24a). Of the Take's n blocks, k = ceil(n / 5) are
drawn. Each block is ranked by sha256(``DRAW_VERSION:seed:block_id``) as
lowercase hex, the block id breaking a tie, and the first k are drawn in
that order. The seed is the frame's pick-log seed, the Take's own
(``take_feedback_policy_v3.pick_seed``), so the same Take always draws the
same moments. Every block's chance of being drawn is k / n.

WHERE IT LIVES. The database draws: ``draw_v4_random_moments_v1`` reads the
stored frame, ranks its blocks by this rule and stores the draw in
``v4_random_moments``, apart from the machine's picks (the frame's pick
log). ``draw_moments`` is the same rule in Python, so a reader of either can
check the other (tests pin them equal).

WHAT IT IS FOR. Willfidence for a Take or a speaker is averaged over the
random moments only (W1); testing the picker on past data needs moments the
picker did not choose (M7). Nothing here is scored, served or shown: the
draw never changes what V3 picks or what the speaker sees, and no route
reads it (AC-9). The write is a side write after the frame is stored; it
never raises into the Take pipeline (LIVE LOOP).
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Iterable, Optional

_log = logging.getLogger(__name__)

#: The rule the stored rows carry (migration 0447).
DRAW_VERSION = "v4-random-draw-v1"
#: One moment in five, rounded up (V3 A).
SHARE_DENOMINATOR = 5


def draw_size(moments: int) -> int:
    """k = ceil(n / 5): a Take with one to five moments draws one."""
    n = max(0, int(moments))
    return (n + SHARE_DENOMINATOR - 1) // SHARE_DENOMINATOR


def _rank_key(seed: str, block_id: str) -> tuple[str, str]:
    digest = hashlib.sha256(
        f"{DRAW_VERSION}:{seed}:{block_id}".encode("utf-8")).hexdigest()
    return digest, block_id


def draw_moments(seed: Any, block_ids: Iterable[Any]) -> list[str]:
    """The drawn block ids, in draw order. Pure; mirrors the database.

    Raises ValueError on a block list the database would refuse (an empty
    or duplicated id), so the two can never disagree in silence."""
    seed_text = str(seed or "")
    if not seed_text.isdigit() or len(seed_text) > 16:
        raise ValueError("seed must be a decimal string of at most 16 digits")
    ids = [str(block_id) if isinstance(block_id, str) else "" for block_id in block_ids]
    if not ids or any(not block_id for block_id in ids) or len(set(ids)) != len(ids):
        raise ValueError("every moment needs one non-empty, unique block id")
    ranked = sorted(ids, key=lambda block_id: _rank_key(seed_text, block_id))
    return ranked[:draw_size(len(ids))]


def draw(database: Any, take_session_id: Any) -> Optional[dict]:
    """Ask the database to draw this Take's moments from its stored frame.

    A side write: returns the database's outcome, or None on any failure,
    which is logged and never raised (LIVE LOOP)."""
    take = str(take_session_id or "").strip()
    if not take:
        return None
    try:
        return database.draw_v4_random_moments(take)
    except Exception as error:  # noqa: BLE001 -- logged; the Take stands
        _log.warning("v4 random moments not drawn take=%s: %s", take, error)
        return None
