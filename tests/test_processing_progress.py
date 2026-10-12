"""The wait bar moves on work that actually happened.

FOUNDER, 2026-09-19: "The loading doesn't show the percentages, it just shows
that it builds and then shows the ideal text — there is no continuity there and
it feels like it's stale."

The run reported five points across its whole length, and the widest gap — 15
to 55 — was `process_lab_recording`, the longest part of it. Forty points of
nothing while the hardest work happened, then a jump.

The fix is NOT interpolation. `lib/willab/waitProgress.ts` already settled
that: elapsed time against a cap reads as "94% done", which is a claim nothing
can make. It named the version worth building — the backend reporting real
boundaries — and these tests hold that line.
"""
from __future__ import annotations

from services.processing_progress import (
    STAGE_MESSAGE,
)

# ── the ladder ─────────────────────────────────────────────────────────────


# ── the lookups refuse to guess ────────────────────────────────────────────


def test_no_message_names_a_score_a_rank_or_a_number():
    """AC-9 lives elsewhere, but these lines are shown to a speaker mid-wait
    and the register has to match the rest: about their take, never about how
    well they did it."""
    import re
    banned = re.compile(
        r"\bscore|\brating|\brank|\bpercent|\bout of\b|\bgrade\b", re.I)
    for line in STAGE_MESSAGE.values():
        assert not banned.search(line), line
        assert line.strip() == line and line.endswith("…")


# ── the bridge from the ledger to the bar ──────────────────────────────────
