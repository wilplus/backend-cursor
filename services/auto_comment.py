"""Deterministic per-piece auto-comment (founder 2026-07-14) — the qualitative
sentence in the comment slot: filler/pause observations + a tone word.

TWO SURFACES, computed at SERVE time from the piece's own metrics (no LLM, no
persistence) so they can never leak the wrong thing:

  * USER instant view — observations + the LEARNED tone word (the founder-locked
    carve-out: the shadow model's read colors THIS SENTENCE, and only this
    sentence — never a badge, chip, needle, or label). The learned word is
    computed ONCE at record time and persisted (metrics["user_tone_word"]) so
    the read path never fires the model per poll.

  * COACH pre-fill — observations + the ACOUSTIC tone word ONLY (the
    deterministic potentiometer's lean). NEVER the learned word: the coach
    labels blind, so the model's direction guess must not reach the labeling
    surface (BLIND COACH). The acoustic lean is already on the coach's
    potentiometer, so an acoustic tone word tells the coach nothing new.

threat leans → "stressed"; challenge leans → "confident" (founder: "threat
leans stress feeling in the voice and challenge leans more to confidence").
Output through say_it_stronger._guard_copy (AC-9: any digit / construct-
vocabulary hit kills the sentence).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services.say_it_stronger import _guard_copy, qualitative_self_comparison

logger = logging.getLogger(__name__)

_TONE_BY_DIRECTION = {"challenge": "confident", "threat": "stressed"}

# Shadow tone gate — the learned read only speaks when clearly confident.
_SHADOW_TONE_MIN_CONFIDENCE = 0.7


def acoustic_tone_word(metrics: Any) -> Optional[str]:
    """The COACH-safe tone word: the deterministic acoustic potentiometer's
    lean only (never the learned model). None in the neutral band."""
    m = metrics if isinstance(metrics, dict) else {}
    try:
        from services.acoustic_read import tone_hint
        return tone_hint(m.get("acoustic_read"))
    except Exception:
        return None


def learned_tone_word(metrics: Any) -> Optional[str]:
    """The USER tone word (founder carve-out): the LEARNED shadow read first
    (confidence-gated), the acoustic lean second, None otherwise. Computed
    ONCE at record time and persisted — never at serve. Best-effort: a model
    hiccup falls through to the acoustic read."""
    m = metrics if isinstance(metrics, dict) else {}
    try:
        from services.learning_serve import predict_direction
        pred = predict_direction(m)
        if isinstance(pred, dict):
            conf = pred.get("confidence")
            word = _TONE_BY_DIRECTION.get(pred.get("label"))
            if word and isinstance(conf, (int, float)) \
                    and conf >= _SHADOW_TONE_MIN_CONFIDENCE:
                return word
    except Exception:
        pass
    return acoustic_tone_word(m)


def _observations(metrics: Any, session_means: Any) -> list:
    """The non-average self-comparison clauses for this piece (plain words,
    no numbers). Shared by both surfaces. Pure."""
    comparisons = qualitative_self_comparison(metrics, session_means) or {}
    out = []
    pace = comparisons.get("pace")
    if pace and "about" not in pace:
        out.append(f"the pace here was {pace}")
    pausing = comparisons.get("pausing")
    if pausing and "about" not in pausing:
        out.append(f"you took {pausing}")
    energy = comparisons.get("energy")
    if energy and "about" not in energy:
        out.append(f"it came through {energy}")
    return out


def build_auto_comment(metrics: Any, session_means: Any, *,
                       tone_word: Optional[str] = None) -> Optional[str]:
    """One qualitative sentence-pair: this piece's self-comparison
    observations + the CALLER-CHOSEN tone word (learned for the user surface,
    acoustic for the coach surface, None to omit). Deterministic, digit-free,
    guarded. None when there is nothing honest to say (no observations and no
    tone) — silence beats filler."""
    observations = _observations(metrics, session_means)
    if not observations and not tone_word:
        return None
    parts = []
    if observations:
        parts.append("In this moment, " + " and ".join(observations[:2]) + ".")
    if tone_word:
        parts.append(f"This sounded rather {tone_word}.")
    return _guard_copy(" ".join(parts))
