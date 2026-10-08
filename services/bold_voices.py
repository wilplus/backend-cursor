"""Bold voices and the once-per-Take after-practice steps: RETIRED
(founder 2026-10-07, Q-B11 A, decisions log N62: "The Album share switch
and Bold voices are retired").

Phase 3 of the after-practice paths (founder 2026-10-01) let a speaker hear
bold voices after the first practice ending: their own landed attempt, a
coach's published readings, then (Phase 4, F4) others' shared clips the
quorum settled Yes and licensed corpus clips a coach labelled Yes; plays
only, a "heard" receipt per play (migration 0409), and each after-practice
step (bridge, Lend your ear, Bold voices) shown once per Take. The walk
lock (N52) has no such screen, and Q-B11 A retires it: the three routes in
``routes/v2/after_practice.py`` answer 404 whatever ``PRAISE_AFTER_PRACTICE_
ENABLED`` says, nothing is served, and nothing is written to
``bold_voices_plays`` or ``after_practice_steps``. The coach's readings
tool (``services/coach_readings.py``) is not this module's and stays as it
is. No row is dropped: a retention operation on the two tables is a
separately authorised, previewed step.

What remains here is the ledger's count of the practices that landed, the
plays and the steps (never a speaker-facing number), so the founder's
weekly line keeps reading what the tables hold.
"""
from __future__ import annotations

from typing import Any


def after_practice_counts(database: Any, *, since: str) -> dict:
    """Counts for the founder's ledger (never a speaker-facing number)."""
    return {"since": since, **(database.count_after_practice(since) or {})}
