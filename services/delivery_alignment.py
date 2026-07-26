"""Congruence delivery star — the content-aware member of the delivery-star
family (founder 2026-07-24 sign-off).

WHAT THIS IS
------------
The ONE integrity/alignment gap we can honestly detect from an ecological
phone-mic recording, per Juslin & Laukka (2003): the words are clearly UP
(positive) but the delivery came through FLAT / low-arousal — the
low-activation, sadness-side profile, reliably voice-decoded and built from
cues we measure. Rather than a bespoke readout note (the earlier
``readout.delivery_note`` shape — now RETIRED), it is folded into the existing
measured delivery-star family as ``device: "congruence"`` so it surfaces on
the SD ideal-text GET's ``key_moments[]`` and inherits the delivery re-record
mic. The copy lives FE-side, keyed by ``device`` (same pattern as the other
delivery stars) — this module surfaces NO prose.

SCOPE (deliberately narrow)
---------------------------
Only the flat/low-arousal side. The gate is main's baseline-relative
``arousal_z`` (services/delivery_stars.arousal_z) — LOW = flat/deflated —
plus a positive-content check. The valence-confusable HIGH-arousal case
(upbeat words over a masked-tension / anxious voice) is never flagged: on a
phone mic we cannot tell it from genuine excitement, so we don't try. Low
arousal_z carries no sign of positivity, so the content gate is what makes
this "words up, voice down" rather than the plain (content-blind) ``emphasis``
flatness star.

FENCES
------
* AC-9 / CONSTRUCT — surfaces only ``{kind:"delivery", device:"congruence"}``;
  no number, no prose, no score ever leaves this module. arousal_z is used to
  GATE only, never surfaced (it is the same signal main captures "never to a
  user").
* BLIND COACH / not-the-shadow — the gate is arousal_z (fixed-weight,
  baseline-relative) plus a content classifier; the learned shadow model never
  enters the decision.
* LIVE LOOP — best-effort; any failure returns []/False and never raises.
  Flag-gated (``DELIVERY_ALIGNMENT_ENABLED``), default OFF (costs one model
  call per take; the FE renders the ``congruence`` copy).
* ONE star per piece — congruence runs BEFORE the deterministic delivery
  stars and claims its snippet, so a positive-content flat moment reads as
  ``congruence`` (the meaningful signal) rather than a plain ``emphasis``.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# One congruence star per take — a nudge, not a nag. We walk the lowest-arousal
# candidates and stop at the first whose WORDS the model judges clearly
# positive, capping the model calls so a take of all-flat pieces can't fan out.
_MAX_LLM_ATTEMPTS = 2

# arousal_z is a mean of the speaker-normalized delivery cues (z vs their OWN
# reference). This is the "clearly below their norm" bar — provisional, not
# calibrated (mirrors the delivery-star z convention), tune on a separate set.
_CONGRUENCE_AROUSAL_MAX = -0.6

_SYSTEM_PROMPT = (
    "You judge ONE thing for a speaker reviewing their own recording: are the "
    "WORDS of this moment clearly upbeat / positive in meaning? Not neutral, "
    "not negative — clearly positive.\n\n"
    'Return JSON only: {"words_positive": true|false}. Judge the meaning of '
    "the words alone. Do not explain."
)


def delivery_alignment_enabled() -> bool:
    """Flag-gated (``DELIVERY_ALIGNMENT_ENABLED``), default OFF. It adds a
    surfaced star and costs a model call per take, so it ships dark until
    flipped (the FE renders the ``congruence`` copy)."""
    return (os.getenv("DELIVERY_ALIGNMENT_ENABLED") or "0").strip().lower() \
        in ("1", "true", "yes")


def congruence_candidates(unstarred: Any, baseline: Any) -> list:
    """From the no-acoustic-star snippets, the CLEARLY flat/low-arousal ones
    with words — lowest arousal first. Pure: keys on
    ``delivery_stars.arousal_z`` (baseline-relative) and the
    ``_CONGRUENCE_AROUSAL_MAX`` bar; a neutral or high-arousal read never
    qualifies, so the valence-confusable case is excluded by construction.

    ``unstarred`` = [(snip_id, transcript, features_dict), ...].
    Returns [(arousal_z, snip_id, transcript), ...], lowest arousal_z first.
    """
    if not unstarred or not baseline:
        return []
    try:
        from services.delivery_stars import arousal_z
    except Exception:
        return []
    scored = []
    for item in unstarred:
        try:
            sid, transcript, feats = item
        except (ValueError, TypeError):
            continue
        if not sid or not (transcript or "").strip():
            continue
        az = arousal_z(feats or {}, baseline)
        if isinstance(az, (int, float)) and not isinstance(az, bool) \
                and az <= _CONGRUENCE_AROUSAL_MAX:
            scored.append((float(az), str(sid), transcript.strip()))
    scored.sort(key=lambda t: t[0])   # lowest arousal (flattest) first
    return scored


def build_sentiment_messages(transcript: str) -> tuple[str, str]:
    """(system, user) for the positive-content judgment. Pure."""
    return _SYSTEM_PROMPT, f'The words for this moment:\n"{(transcript or "").strip()}"'


def words_positive(parsed: Any) -> bool:
    """True iff the model clearly judged the words positive. Pure, defensive:
    anything but an explicit truthy ``words_positive`` is False."""
    return bool(isinstance(parsed, dict) and parsed.get("words_positive"))


def _default_chat(system: str, user: str, *, user_id: Optional[str] = None) -> Optional[dict]:
    """Resolve + run the real model call, returning parsed JSON or None. Lazy
    imports keep this module importable without the LLM stack."""
    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_DELIVERY_ALIGNMENT
    except Exception:
        return None
    res = chat_complete(
        spec=SPEC_DELIVERY_ALIGNMENT, system=system, user=user,
        surface="delivery_alignment", user_id=user_id,
    )
    if res is None:
        return None
    return res.parsed if isinstance(res.parsed, dict) else None


def generate_congruence_stars(
    database: Any,
    arc_id: Any,
    unstarred: Any,
    baseline: Any,
    *,
    user_id: Optional[str] = None,
    chat_fn: Optional[Callable[[str, str], Optional[dict]]] = None,
) -> list:
    """Persist a ``congruence`` delivery star on the flattest low-arousal
    moment whose WORDS are clearly positive (cap: one per take). Returns the
    snip_ids starred (so the deterministic delivery/structural lanes skip them
    — never double-star).

    The caller gates on :func:`delivery_alignment_enabled`; this is best-effort
    and never raises. ``chat_fn`` is injectable ``(system, user) -> parsed |
    None`` so the logic is unit-testable without the model.
    """
    if not arc_id or not unstarred or not baseline:
        return []
    chat = chat_fn or (lambda s, u: _default_chat(s, u, user_id=user_id))
    starred: list = []
    try:
        candidates = congruence_candidates(unstarred, baseline)
        for _az, sid, transcript in candidates[:_MAX_LLM_ATTEMPTS]:
            system, user = build_sentiment_messages(transcript)
            if not words_positive(chat(system, user)):
                continue
            if database.upsert_moment_suggestion(
                    str(sid), str(arc_id), "delivery", None, None, "congruence"):
                starred.append(str(sid))
                break   # one congruence star per take
    except Exception as err:   # LIVE LOOP: never break the pipeline
        logger.warning(
            "delivery_alignment: congruence generation failed err=%s "
            "(non-fatal)", err,
        )
    return starred
