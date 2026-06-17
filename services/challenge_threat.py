"""Challenge-threat lane (willab Prompt D) — the direction component of the ONE
combined ranking, kept MODULAR (separate from the acoustic/coach terms it feeds
in services/power_phrase_ranking.power_score).

Three pure pieces:
  • resolve_direction — the COACH's blind label wins; else the SHADOW model's
    prediction (Phase 4 / Prompt 1). The shadow label is NEVER shown to the
    coach — the coach labels independently and the system learns from the diff.
  • detect_breakthroughs — the threat→challenge transition: walking a take in
    time order, a challenge moment that follows a threat one is a "breakthrough"
    (paralyzing stress → motivating). That's the KEY moment.
  • is_challenge — the SURFACING filter: the user sees ONLY challenge moments;
    threat informs ranking + marks where the breakthrough started, but is never
    shown (Prompt D §0/§7).
"""
from __future__ import annotations

from typing import Any, Optional

VALID_DIRECTIONS = ("threat", "ambiguous", "challenge")


def resolve_direction(
    coach_label: Any, shadow_label: Any = None,
) -> Optional[str]:
    """The snippet's direction: the COACH's label (training_labels, blind) when
    valid, else the SHADOW prediction, else None. Pure — the caller fetches both
    (the coach label from training_labels, the shadow label from
    learning_serve.predict_direction(features)["label"])."""
    if coach_label in VALID_DIRECTIONS:
        return coach_label
    if shadow_label in VALID_DIRECTIONS:
        return shadow_label
    return None


def is_challenge(direction: Any) -> bool:
    """Surfacing filter — only challenge reaches the user."""
    return direction == "challenge"


def detect_breakthroughs(snippets: Any) -> set:
    """Return the set of snippet ids that are threat→challenge BREAKTHROUGHS.

    ``snippets`` = list of dicts with ``id``, ``start_offset_ms``, ``direction``.
    Walking each take in TIME order: a ``challenge`` moment is a breakthrough iff
    the most recent prior direction was ``threat`` (the user broke through).
    Reaching challenge resets the latch — later challenges aren't breakthroughs
    until another threat. ``ambiguous`` doesn't change the latch.

    Pass ONE take's snippets at a time (or tag them with take so transitions
    don't cross takes); the caller groups by take_index.
    """
    if not isinstance(snippets, list):
        return set()
    ordered = sorted(
        (s for s in snippets if isinstance(s, dict)),
        key=lambda s: (s.get("start_offset_ms")
                       if isinstance(s.get("start_offset_ms"), (int, float))
                       and not isinstance(s.get("start_offset_ms"), bool)
                       else 0),
    )
    out = set()
    prev_threat = False
    for s in ordered:
        d = s.get("direction")
        if d == "challenge":
            if prev_threat:
                out.add(s.get("id"))
            prev_threat = False
        elif d == "threat":
            prev_threat = True
        # ambiguous / None: leave the latch as-is
    return out
