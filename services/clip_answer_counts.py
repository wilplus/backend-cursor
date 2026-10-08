"""Answer counts per clip as soft-label data (V4 brief 1.7, founder-signed
2026-10-05/06; decision rows Q1, Q2, Q3; V17 A; build plan D-ML-11;
migration 0442).

THE RULE. Each clip keeps how many blind human raters said Yes, In-between,
No and Not sure, and the share who said Yes with In-between counting half
(Q1: Yes 1, In-between 1/2, No 0; V17 A). The counts live in their own table
(``clip_answer_counts``), rebuilt from the label ledger by the database
function ``refresh_clip_answer_counts_v1``, and are read by nothing that
decides anything today: the quorum (``services.label_quorum``) keeps its
humans-only rule, MACHINE_VOTES = 0 and its two lanes (Q3), and nothing
trains on the counts until the founder opens the training door (M10, P-b).

WHO IS COUNTED. Exactly the rows the quorum would count as a human vote:
state 'confidence', lane 'coach' or 'game_peer', not a self-report, not an
Audio-unclear abstention, blind (0411: a rating made after the rater saw the
clip's non-blind side is not a label), with a rater. Historical v1
``neutral`` is the old spelling of Not sure and is counted with it
(``label_quorum.IDK_VALUES``). ``counted_answer`` is the same rule on one
ledger row, so a reader of either can check the other. Speaker taps are never labels (L3;
M8): the speaker's answers never enter the ledger as a vote, and a rating
the speaker gives on their own clip is excluded as a self-report. The
machine has no lane and no count.

WHEN. After a blind human rating lands (the coach's judgment of record, a
peer's label under the quorum's access rule). A side write: it never raises
and never blocks the rating it follows (LIVE LOOP). Never in any user
payload (AC-9).
"""
from __future__ import annotations

import logging
from fractions import Fraction
from typing import Any, Optional

_log = logging.getLogger(__name__)

#: The rule the stored row carries (migration 0442).
RULE_VERSION = "soft-label-v1"
#: The lanes counted: the quorum's human lanes, and only those (Q3).
LANES_COUNTED = ("coach", "game_peer")
#: Q1 / V17 A: the weight of each perceptual answer in the soft label.
VOTE_WEIGHTS = {"yes": Fraction(1), "in_between": Fraction(1, 2), "no": Fraction(0)}
#: Rater uncertainty, kept as its own count; ``neutral`` is the v1 spelling.
NOT_SURE_VALUES = ("not_sure", "neutral")


def counted_answer(row: dict) -> Optional[str]:
    """Which count one ledger row adds to: 'yes', 'in_between', 'no',
    'not_sure', or None when the row is not a blind human vote. Pure; the
    same filter as refresh_clip_answer_counts_v1."""
    if (row.get("state_id") or "confidence") != "confidence":
        return None
    if row.get("lane") not in LANES_COUNTED:
        return None
    if row.get("self_report") or row.get("unrateable"):
        return None
    if row.get("blind") is False:
        return None
    if not row.get("rater_id"):
        return None
    value = row.get("value")
    if value in VOTE_WEIGHTS:
        return str(value)
    if value in NOT_SURE_VALUES:
        return "not_sure"
    return None


def soft_label(yes: int, in_between: int, no: int) -> Optional[Fraction]:
    """The share who said Yes, In-between counting half, over the
    perceptual answers; None while nobody has answered. Pure; mirrors the
    database function so a reader of either can check the other."""
    total = int(yes) + int(in_between) + int(no)
    if total <= 0:
        return None
    weighted = (VOTE_WEIGHTS["yes"] * int(yes)
                + VOTE_WEIGHTS["in_between"] * int(in_between)
                + VOTE_WEIGHTS["no"] * int(no))
    return weighted / total


def refresh(database: Any, snippet_id: Any) -> Optional[dict]:
    """Rebuild one clip's counts from the ledger, best-effort. The row, or
    None when the write was not made (a missing migration, a failed call);
    the rating it follows is already saved either way."""
    if not snippet_id:
        return None
    writer = getattr(database, "refresh_clip_answer_counts", None)
    if writer is None:
        return None
    try:
        row = writer(str(snippet_id))
    except Exception as e:  # noqa: BLE001 -- a side write, named, never raised
        _log.warning("clip answer counts not refreshed snip=%s: %s",
                     snippet_id, e, exc_info=True)
        return None
    return row if isinstance(row, dict) else None
