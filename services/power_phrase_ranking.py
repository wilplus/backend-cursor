"""Coach-adjusted surfacing score for power phrases (willab Phase 4, 2026-06-15).

The coach is the GATE — they tag (strong / to_work_on) + surface the acoustic
≤10 AFTER selection. This orders that already-approved set into the user's
"power phrases" by blending the human verdict (DOMINANT) with acoustic
activation + how well the moment covered its slide:

    power_score = w_c·coach_term + w_a·activation + w_s·slide_stickiness

- coach_term: strong=+1, to_work_on=-1, untagged=0 — DOMINANT, so a coach-strong
  moment always outranks a to-work-on one. SMOOTHING: untagged → 0 → the order
  falls back to pure acoustics (no cold-start cliff before the coach reviews).
- activation: the salience composite (overall_score, ~0-1); rank-derived proxy
  (1/rank) when overall_score is absent.
- slide_stickiness: how well the talk covered the slide (~0-1).

Selection of the ≤10 stays PURELY acoustic (snippet_salience) — this only
reorders what the coach approved. The direction label (threat/ambiguous/
challenge) and the comment text are SEPARATE lanes and are NOT inputs here.
Pure + unit-tested; no DB, no user/coach-as-verdict surface.
"""
from __future__ import annotations

from typing import Any, Optional

_COACH_TERM = {"strong": 1.0, "to_work_on": -1.0}
# w_c dominant so the human verdict orders before any acoustic tie-break.
_W_C, _W_A, _W_S = 2.0, 1.0, 0.6


def _num(v: Any) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def power_score(
    *,
    activation: Any = None,
    slide_stickiness: Any = None,
    tag: Optional[str] = None,
    rank: Any = None,
) -> float:
    """Coach-adjusted surfacing score (higher = better power phrase)."""
    coach = _COACH_TERM.get(tag or "", 0.0)
    a = _num(activation)
    if (
        a == 0.0
        and isinstance(rank, (int, float))
        and not isinstance(rank, bool)
        and rank > 0
    ):
        a = 1.0 / float(rank)  # rank 1 → 1.0, rank 2 → 0.5, …
    s = _num(slide_stickiness)
    return _W_C * coach + _W_A * a + _W_S * s
