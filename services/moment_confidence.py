"""Star-suggestion routing on the defined CONFIDENCE construct.

Confidence means how assured the speaker sounds in the delivery of this exact
moment. It is a property of the voice, not the content. This module does not
infer or retain a broader psychological state.

``confidence`` (``conf-q-v1``) is single-barrelled and defined as "how assured
the speaker SOUNDS in their delivery of this moment — a property of the voice,
not of the content". This live suggestion router uses only the stored machine
read. Blind peer judgments remain internal training/evaluation data.

SPEC §7.3 scopes ``VOICE_CONFIDENCE_RANKING_ENABLED`` to RANKING — "is the
machine fallback trusted yet" for the blend. This is not the blend. Gating the
star lane on it would take EMPHASIZE dark entirely until validation passes,
which is a regression dressed as caution: the lane routes off an unvalidated
machine read TODAY (``tone_hint``), so moving it to a defined, speaker-relative,
dead-zoned composite is a strict improvement at the same trust level, not a new
risk. ``voice_confidence.stamped_score`` is therefore the ungated reader.

FENCES.
  * BLIND COACH — this module must NEVER consult the shadow model
    or any experiment model. Its guess never becomes a surfaced star.
  * AC-9 / CONSTRUCT — ``confident`` / ``unconfident`` are internal routing
    words. They pick WHICH star fires; neither string is ever surfaced, and no
    score, band or ratio rides a payload out of here.

Pure: no DB, no LLM, unit-tested.
"""
from __future__ import annotations

from typing import Any, Optional

CONFIDENT = "confident"
UNCONFIDENT = "unconfident"


def resolve_moment_confidence(metrics: Any) -> Optional[str]:
    """``'confident'`` | ``'unconfident'`` | None for one moment.

    ``metrics`` is the snippet's metrics dict, read through
    ``voice_confidence.stamped_score``. Its zero is the dead zone, so "no
    lean" stays distinct from "leans slightly". Peer/panel input is not part
    of this product API by design.
    """
    from services.voice_confidence import stamped_score
    score = stamped_score(metrics)
    return _lean(score) if score is not None else None


def _lean(value: float) -> Optional[str]:
    if value > 0:
        return CONFIDENT
    if value < 0:
        return UNCONFIDENT
    return None


def is_confident(confidence: Any) -> bool:
    """The user sees confident moments; unconfident ones inform ranking and are
    never shown. The filter's JOB is unchanged by the re-point and it is worth
    naming: it is what stops the app being a list of your failures."""
    return confidence == CONFIDENT


def resolve_suggestion_kind(confidence: Optional[str], transcript: Any, *,
                            slide_stickiness: Any = None,
                            stickiness_max: float = 0.15) -> Optional[str]:
    """``'replace'`` | ``'emphasize'`` | None. Pure.

    REPLACE triggers (union — any one suffices): an UNCONFIDENT read ·
    profanity in the transcript · slide_stickiness present and ≤ the low band.
    The union is the founder's rule (2026-07-18, "very important to spot the
    right moments to replace") and it is why this lane does not go silent when
    confidence is unavailable: two of its three triggers never depended on the
    construct at all.

    EMPHASIZE = a clean CONFIDENT read with no replace trigger. This is the one
    branch that needs confidence.

    None → no star, and that outcome is now COUNTED rather than swallowed (see
    services/moment_suggestions.py) — a moment with no lean and no replace
    trigger is the single largest reason this lane emits nothing, and it used
    to be invisible from outside.
    """
    from services.text_flags import has_profanity
    _sticky_bad = (
        isinstance(slide_stickiness, (int, float))
        and not isinstance(slide_stickiness, bool)
        and float(slide_stickiness) <= float(stickiness_max)
    )
    if confidence == UNCONFIDENT or has_profanity(transcript) or _sticky_bad:
        return "replace"
    if confidence == CONFIDENT:
        return "emphasize"
    return None
