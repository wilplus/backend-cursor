"""Did a practice attempt sound more confident than the original? (0388)

Rule exercise-more-confident-v1 (founder 2026-09-28, option A; contract
35g-3). Internal only: nothing here reaches a speaker or a coach (AC-9), and
it is never a label — exercise-adequacy-label-v1 (design §3.5) stays the one
label specification, unchanged.

Two legs, kept apart (L3), and both must say yes:

* machine — the attempt's voice-confidence composite is higher than the
  original clip's; any increase counts;
* coach — the coach answered "Do you find it more confident?" Yes about that
  attempt, after their own blind rating. The speaker's answer is not a leg.

The database computes the result (``record_practice_more_confident_v1``) from
the stored snapshots and the coach's stored answer, so no caller can hand it a
number. ``outcome`` below is the same rule in Python, for tests and readers;
the migration's CASE is the one that writes.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

RULE_VERSION = "exercise-more-confident-v1"


def machine_leg(original: Optional[float], attempt: Optional[float]) -> str:
    """'higher', 'not_higher', or 'unmeasurable' when either score is missing."""
    if not _is_number(original) or not _is_number(attempt):
        return "unmeasurable"
    return "higher" if float(attempt) > float(original) else "not_higher"  # type: ignore[arg-type]


def outcome(machine: str, coach: Optional[str]) -> str:
    """'helped' only when both legs say yes; 'pending' while either is missing."""
    if machine == "unmeasurable" or coach not in ("yes", "no"):
        return "pending"
    if machine == "higher" and coach == "yes":
        return "helped"
    return "not_helped"


def record_after_coach_decision(database: Any, practice_id: str,
                                attempt_id: str) -> Optional[dict]:
    """Recompute the result once the coach has answered about an attempt.

    Best-effort: this is bookkeeping behind the coach's save, so a failure is
    logged and never fails the save or the live loop."""
    try:
        return database.record_practice_more_confident(
            practice_id=str(practice_id), attempt_id=str(attempt_id))
    except Exception as e:
        logger.warning("practice more-confident record failed practice=%s: %s",
                       practice_id, e)
        return None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
