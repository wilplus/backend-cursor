"""Challenge-threat lane (willab Prompt D) — the direction component of the ONE
combined ranking, kept MODULAR (separate from the acoustic/coach terms it feeds
in services/power_phrase_ranking.power_score).

Three pure pieces:
  • resolve_direction — the COACH's blind label wins; else the SHADOW model's
    prediction (Phase 4 / Prompt 1). The shadow label is NEVER shown to the
    coach — the coach labels independently and the system learns from the diff.
  • detect_breakthroughs — the coach-confirmed breakthrough moments. A
    breakthrough = a coach ``challenge`` mark (founder 2026-06-26: the coach's
    challenge mark in the panel IS the breakthrough mark). The earlier
    threat→challenge-transition rule is RETIRED — see the function.
  • is_challenge — the SURFACING filter: the user sees ONLY challenge moments;
    threat informs ranking but is never shown (Prompt D §0/§7).
"""
from __future__ import annotations

from typing import Any, Optional

VALID_DIRECTIONS = ("threat", "ambiguous", "challenge")


def resolve_direction(
    coach_label: Any, shadow_label: Any = None,
    *, shadow_confidence: Any = None, min_confidence: Any = None,
) -> Optional[str]:
    """The snippet's direction: the COACH's label (training_labels, blind) when
    valid, else the SHADOW prediction, else None. Pure — the caller fetches both
    (the coach label from training_labels, the shadow label from
    learning_serve.predict_direction(features)["label"]).

    GRADUATED AUTONOMY (readiness rig #3, default-OFF): when ``min_confidence`` is
    set, the shadow fallback is used ONLY if ``shadow_confidence >=
    min_confidence`` — below the floor the snippet gets NO direction (None)
    rather than a low-confidence guess. That routes low-confidence cases to the
    human (no machine direction term) and high-confidence to the machine.
    ``min_confidence=None`` (the default) → no gating, identical to before. The
    COACH label is never gated — it always wins."""
    if coach_label in VALID_DIRECTIONS:
        return coach_label
    if shadow_label in VALID_DIRECTIONS:
        if min_confidence is not None:
            try:
                if (shadow_confidence is None
                        or float(shadow_confidence) < float(min_confidence)):
                    return None
            except (TypeError, ValueError):
                return None
        return shadow_label
    return None


def is_challenge(direction: Any) -> bool:
    """Surfacing filter — only challenge reaches the user."""
    return direction == "challenge"


def detect_breakthroughs(snippets: Any) -> set:
    """Return the set of snippet ids that are coach-confirmed BREAKTHROUGHS.

    BREAKTHROUGH = a coach ``challenge`` mark (founder 2026-06-26). The coach's
    challenge mark in the panel IS the breakthrough mark — so every snippet the
    coach labelled ``challenge`` is a breakthrough.

    The earlier threat→challenge-TRANSITION rule is RETIRED: it required a coach
    ``threat`` immediately before the ``challenge`` in the same take, so a coach
    who marked a single ``challenge`` (no preceding threat) saw NO breakthrough
    surface anywhere — the reported "I chose one and it wasn't shown" bug.

    ``snippets`` = list of dicts with ``id`` and ``direction`` (callers still
    pass ``start_offset_ms``; it's accepted and ignored — order no longer
    matters without the latch). The coach-only gate lives at the call sites
    (``coach_direction``), so no model guess ever reaches this set.
    """
    if not isinstance(snippets, list):
        return set()
    return {
        s.get("id")
        for s in snippets
        if isinstance(s, dict) and s.get("direction") == "challenge"
    }
