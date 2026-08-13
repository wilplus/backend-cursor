"""Star-suggestion routing on the CONFIDENCE construct (SPEC §7.2/§17).

REPLACES services/moment_direction.py, retired 2026-08-13 by founder decision.
That module routed the live star lane off ``charisma`` / ``threat``, resolved
from ``acoustic_read.tone_hint`` — a fixed-weight potentiometer whose ±0.35
band decided, on every take and with no human anywhere in the loop, whether a
moment got a REPLACE star, an EMPHASIZE star, or nothing at all.

WHY IT WENT. Not because the arithmetic was wrong — the potentiometer is
deterministic and reproducible — but because of what it claimed to measure.
"Charisma" has no written operational definition (SPEC §1.4: a question that
cannot trace to one cannot ship), so nothing could say what the threshold was a
threshold ON, and §17 names charisma explicitly as one of the constructs
``confidence`` must NOT be folded together with. A subjective, undefined label
was routing an objective, measured lane.

``confidence`` (``conf-q-v1``) is the replacement and it is a strictly better
object: single-barrelled, externally anchored (Jiang & Pell 2017), defined as
"how assured the speaker SOUNDS in their delivery of this moment — a property
of the voice, not of the content", and rated by a blind panel on the same
ternary instrument as every other state.

THE RESOLUTION ORDER, and why the machine is not gated here:

    panel label (blind, multi-rater)  →  machine read  →  None

SPEC §7.3 scopes ``VOICE_CONFIDENCE_RANKING_ENABLED`` to RANKING — "is the
machine fallback trusted yet" for the blend. This is not the blend. Gating the
star lane on it would take EMPHASIZE dark entirely until validation passes,
which is a regression dressed as caution: the lane routes off an unvalidated
machine read TODAY (``tone_hint``), so moving it to a defined, speaker-relative,
dead-zoned composite is a strict improvement at the same trust level, not a new
risk. ``voice_confidence.stamped_score`` is therefore the ungated reader.

FENCES.
  * BLIND COACH — this module must NEVER consult the shadow model
    (services.learning_serve). The shadow keeps learning in the background;
    its guess never becomes a surfaced star. The import is banned from this
    module's source by test, so a future edit cannot quietly cross the wall.
  * AC-9 / CONSTRUCT — ``confident`` / ``unconfident`` are internal routing
    words. They pick WHICH star fires; neither string is ever surfaced, and no
    score, band or ratio rides a payload out of here.

Pure: no DB, no LLM, unit-tested.
"""
from __future__ import annotations

from typing import Any, Optional

CONFIDENT = "confident"
UNCONFIDENT = "unconfident"


def resolve_moment_confidence(panel_confidence: Any,
                              metrics: Any) -> Optional[str]:
    """``'confident'`` | ``'unconfident'`` | None for one moment.

    ``panel_confidence`` is ``services.state_ratings.aggregate``'s blob (or
    None); ``metrics`` is the snippet's metrics dict, read through
    ``voice_confidence.stamped_score``.

    THE PANEL WINS OUTRIGHT WHEN IT EXISTS — INCLUDING WHEN IT SAYS NEITHER.
    An aggregate of exactly 0.0 is people having looked and landed in the
    middle, which SPEC §17 is explicit about: ``neutral`` is a judgment about
    the moment, not an absence of one. Falling through to the machine there
    would let an estimate overrule the humans it is a stand-in for, on the one
    clip where they actually answered.

    The machine's own zero is the DEAD ZONE (``to_spectrum`` returns exactly
    0.0 inside the band), so the same ``> 0`` / ``< 0`` test reads both
    sources correctly and "no lean" stays distinct from "leans slightly".
    """
    if isinstance(panel_confidence, dict):
        value = panel_confidence.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return _lean(float(value))
        return None
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
    """The SURFACING filter — SPEC §7.2's rename of the retired
    ``challenge_threat.is_challenge``, and a change of construct with it.

    The user sees confident moments; unconfident ones inform ranking and are
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
    branch that needs confidence, so it is the branch that changed hands from
    the retired charisma potentiometer to the defined construct.

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
