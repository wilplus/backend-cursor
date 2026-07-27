"""Coach-adjusted surfacing score for power phrases (willab Phase 4, 2026-06-15).

The coach is the GATE — they tag (strong / to_work_on) + surface the acoustic
≤10 AFTER selection. This orders that already-approved set into the user's
"power phrases" by blending the human verdict (DOMINANT) with how the moment
was DELIVERED and how well it covered its topic/slide:

    power_score = w_c·coach_term + w_a·activation + w_s·slide_stickiness
                + w_v·voice_confidence

- coach_term: strong=+1, to_work_on=-1, untagged=0 — DOMINANT, so a coach-strong
  moment always outranks a to-work-on one. SMOOTHING: untagged → 0 → the order
  falls back to the automatic terms (no cold-start cliff before the coach
  reviews).
- activation: ``metrics["overall_score"]`` (~0-1); rank-derived proxy (1/rank)
  when it is absent. NAMING WARNING: despite the name this is NOT acoustic
  activation. services/lab_recording.py computes overall_score as
  ``0.5·topic_stickiness + 0.5·slide_stickiness`` — two LLM reads over the
  transcript TEXT. It is the CONTENT term. (The acoustic salience composite is
  transient and never persisted — services/snippet_salience.py — so it cannot
  reach this function; acoustics gate WHICH pieces are eligible to be ranked,
  which is a different thing.) The key is kept for compatibility.
- slide_stickiness: how well the talk covered the slide (~0-1).
- voice_confidence: the DELIVERY term (services/voice_confidence.py) — a
  speaker-relative confident↔doubtful read in [-1, 1] from the Jiang & Pell
  (2017) cue set. Optional, defaults to no-op. This is what makes the ranking
  BLENDED (L2) rather than content-only: before it, every automatic term above
  was text-derived.

Selection of the ≤10 stays PURELY acoustic (snippet_salience) — this only
reorders what the coach approved.

DIRECTION (Prompt D): ``direction`` (threat/ambiguous/challenge) + ``breakthrough``
are OPTIONAL inputs that DEFAULT to no-op, so the existing /strengths path
(passes neither) is byte-for-byte UNCHANGED. ONLY the best-presentation opts in:
challenge ranks up, threat down, and a threat→challenge breakthrough is the top
AUTO signal — one combined score, modular terms (the challenge-threat lane is
resolved in services/challenge_threat.py). AC-9: the score is internal, never
surfaced; the challenge-only FILTER lives at the caller.
Pure + unit-tested; no DB, no user/coach-as-verdict surface.
"""
from __future__ import annotations

from typing import Any, Optional

_COACH_TERM = {"strong": 1.0, "to_work_on": -1.0}
# challenge ranks up, threat down (Prompt D); ambiguous neutral.
_DIRECTION_TERM = {"challenge": 1.0, "threat": -1.0, "ambiguous": 0.0}
# w_c dominant (human verdict) > w_b breakthrough (top AUTO signal) > the rest.
_W_C, _W_A, _W_S = 2.0, 1.0, 0.6
_W_D, _W_B = 1.0, 2.5
# w_v: the delivery term. Sized so the ORDERING OF AUTHORITY is preserved —
# voice_confidence spans [-1, 1], so its full swing (2.0) cannot cross the
# coach's strong↔to_work_on gap (4.0), and its ceiling (1.0) sits below the
# breakthrough bonus (2.5). Delivery informs the pick; it never overrules a
# human verdict. Comparable in magnitude to the content term (w_a·activation,
# 0-1) by design — founder: "one thing … and another thing … combined".
_W_V = 1.0


def _num(v: Any) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def power_score(
    *,
    activation: Any = None,
    slide_stickiness: Any = None,
    tag: Optional[str] = None,
    rank: Any = None,
    direction: Optional[str] = None,
    breakthrough: bool = False,
    voice_confidence: Any = None,
) -> float:
    """Coach-adjusted surfacing score (higher = better power phrase).

    ``direction``/``breakthrough``/``voice_confidence`` default to no-op (the
    /strengths path passes none of them). When supplied (best-presentation):
    challenge ranks up, threat down, a breakthrough adds the top auto-bonus,
    and voice_confidence leans the pick toward the more confidently DELIVERED
    version of otherwise comparable lines.

    ``voice_confidence`` is None both for pieces recorded before the composite
    existed and whenever the ranking flag is off (services/voice_confidence.py
    ``rank_term`` returns None) — None → 0.0 → the score is byte-for-byte what
    it was, so an unstamped piece is never penalised against a stamped one."""
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
    d = _DIRECTION_TERM.get(direction or "", 0.0)
    b = _W_B if breakthrough else 0.0
    v = _num(voice_confidence)
    return _W_C * coach + _W_A * a + _W_S * s + _W_D * d + b + _W_V * v
