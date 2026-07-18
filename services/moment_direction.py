"""Star-suggestion direction resolution (founder 2026-07-18).

THE surfaced key-moment direction, one rule, pinned:

    coach label if present  →  else the deterministic potentiometer  →  None

* Coach override ALWAYS wins — including 'ambiguous' (the coach looked and
  said neither → no star; their judgment beats the acoustics).
* The fallback is acoustic_read's tone_hint (the FIXED-weight potentiometer,
  ±0.35 band). Deterministic; never learned.
* BLIND-COACH fence: this module must NEVER consult the shadow model
  (services.learning_serve). The shadow keeps learning from coach labels in
  the background; its guess never becomes a surfaced star (pinned by test —
  the import is banned from this module's source).

Suggestion KIND, second rule (founder: "very important to spot the right
moments to replace"):

    REPLACE when ANY of: direction threat · profanity · very low slide
    stickiness — the union, so a charisma lean with a swear word still
    replaces. EMPHASIZE only for a clean charisma lean. Neither → no star.
"""
from __future__ import annotations

from typing import Any, Optional

# Coach training_labels value → the surfaced direction.
_COACH_TO_DIRECTION = {"challenge": "charisma", "threat": "threat"}


def resolve_moment_direction(coach_label: Any,
                             acoustic_read: Any) -> Optional[str]:
    """'charisma' | 'threat' | None. Coach label wins outright (ambiguous →
    None — an explicit coach 'neither'); else the potentiometer's tone_hint;
    else None (neutral band / no read)."""
    if coach_label is not None:
        return _COACH_TO_DIRECTION.get(coach_label)
    from services.acoustic_read import tone_hint
    hint = tone_hint(acoustic_read)
    if hint == "confident":
        return "charisma"
    if hint == "stressed":
        return "threat"
    return None


def resolve_suggestion_kind(direction: Optional[str], transcript: Any, *,
                            slide_stickiness: Any = None,
                            stickiness_max: float = 0.15) -> Optional[str]:
    """'replace' | 'emphasize' | None.

    REPLACE triggers (union — any one suffices): threat direction ·
    profanity in the transcript · slide_stickiness present and ≤ the
    low band. A charisma lean with a replace trigger still REPLACES.
    EMPHASIZE = clean charisma. None otherwise (no star)."""
    from services.text_flags import has_profanity
    _sticky_bad = (
        isinstance(slide_stickiness, (int, float))
        and not isinstance(slide_stickiness, bool)
        and float(slide_stickiness) <= float(stickiness_max)
    )
    if direction == "threat" or has_profanity(transcript) or _sticky_bad:
        return "replace"
    if direction == "charisma":
        return "emphasize"
    return None
