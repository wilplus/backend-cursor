"""Delivery–content alignment note — the user-facing "worth a re-listen"
nudge (founder 2026-07-24 sign-off).

WHAT THIS IS
------------
The ONE integrity/alignment gap we can honestly detect from an ecological
phone-mic recording, per Juslin & Laukka (2003): the words are clearly UP
(positive) but the delivery came through FLAT / low-energy / down — the
low-arousal, sadness-side acoustic profile, which J&L show is both reliably
voice-decoded and built from cues we actually measure (F0 level/variability,
intensity, rate). We surface it to the speaker as a gentle "your delivery
landed flatter than your words here — worth a re-listen," never a verdict.

SCOPE (deliberately narrow)
---------------------------
Only the flat/low-arousal side. The gate is the deterministic acoustic
potentiometer's DOWN lean (``tone_hint == "stressed"``, potentiometer
≤ −0.35) — the exact boundary the auto-comment already uses. The
valence-confusable HIGH-arousal case (upbeat words over a masked-tension /
anxious voice) is NEVER flagged: on a phone mic we cannot tell it apart from
genuine excitement, so we don't try.

FENCES
------
* AC-9 — user-facing, so QUALITATIVE only. The acoustic read is used
  server-side to GATE; the user sees ONLY the sentence, never a number. The
  model line is run through ``say_it_stronger._guard_copy`` (kills any digit
  / retired-construct word) before it can be surfaced.
* BLIND COACH / not-the-shadow — the gate is the fixed-weight
  ``acoustic_read`` only; the learned shadow model never enters the decision.
* LIVE LOOP — best-effort. Any failure returns None and never breaks the
  record→transcribe loop. Flag-gated (``DELIVERY_ALIGNMENT_ENABLED``),
  default OFF (the FE must render ``delivery_note`` first, and it costs one
  LLM call per take).

Computed ONCE at record time (at most a couple of LLM calls per take),
stamped as ``metrics["delivery_alignment_note"]`` on the single strongest
flat moment (cap: one per take), served on the USER readout only.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# One note per take — a nudge, not a nag. We walk the flattest candidates and
# stop at the first whose WORDS the model judges clearly positive, capping the
# number of model calls so a take of all-flat pieces can't fan out.
_MAX_LLM_ATTEMPTS = 2

# The plain-language delivery read handed to the model — NEVER a number. The
# gate already guarantees a clear down-lean, so this is honest for every
# candidate.
_DELIVERY_DESCRIPTOR = "flat and low-energy, with little pitch movement or lift"

_SYSTEM_PROMPT = (
    "You judge ONE thing and optionally write ONE line, for a speaker "
    "reviewing their own recording.\n\n"
    "You are given: their exact words for one moment, and a plain-language "
    "read of how the delivery sounded (never any numbers).\n\n"
    "Decide: are the WORDS clearly upbeat / positive in meaning? Not neutral, "
    "not negative — clearly positive.\n\n"
    'Return JSON: {"words_positive": true|false, "note": "..."}\n\n'
    'If words_positive is false, set note to "" and do nothing else.\n\n'
    "If words_positive is true, the delivery read will be flat / low-energy — "
    "write ONE sentence that gently reflects the CONTRAST between the upbeat "
    "words and the flat delivery, and invites a re-listen or a retry of that "
    "line. Rules for the sentence:\n"
    "- exactly one sentence, at most twenty words, warm, second person\n"
    "- anchor it to their own words\n"
    "- an observation plus an invitation — never a correction\n"
    "- NEVER a number, score, rating, percentage, or level\n"
    '- NEVER state an emotion as fact ("you sound sad/anxious/stressed") or '
    "claim what they felt\n"
    "- NEVER use the words fake, inauthentic, insincere, lying, integrity, "
    "incongruent, or mismatch\n"
    "- NEVER say the delivery is wrong or bad, and never add coaching theory\n\n"
    "Return ONLY the JSON."
)


def delivery_alignment_enabled() -> bool:
    """Flag-gated (``DELIVERY_ALIGNMENT_ENABLED``), default OFF. It is a
    user-facing surface (the FE must render ``delivery_note``) and costs a
    model call per take, so it ships dark until flipped."""
    return (os.getenv("DELIVERY_ALIGNMENT_ENABLED") or "0").strip().lower() \
        in ("1", "true", "yes")


def _is_flat_delivery(metrics: Any) -> bool:
    """True when the deterministic acoustic read leans clearly DOWN
    (flat/low-energy) — the ONLY side we flag. Reuses the exact
    ``tone_hint == "stressed"`` boundary (potentiometer ≤ −0.35) so we never
    invent a threshold and never touch the learned shadow model. A neutral or
    UP (charisma) lean, or no read at all, is not a candidate — which is
    exactly how the valence-confusable high-arousal case gets excluded."""
    m = metrics if isinstance(metrics, dict) else {}
    try:
        from services.acoustic_read import tone_hint
        return tone_hint(m.get("acoustic_read")) == "stressed"
    except Exception:
        return False


def _flatness(metrics: Any) -> float:
    """How far DOWN the read leans (higher = flatter). Orders candidates only;
    never surfaced."""
    m = metrics if isinstance(metrics, dict) else {}
    ar = m.get("acoustic_read") if isinstance(m.get("acoustic_read"), dict) else {}
    v = ar.get("potentiometer")
    return -float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def flat_delivery_candidates(pieces: Any) -> list:
    """The pieces whose delivery leans clearly flat/down AND carry words,
    flattest first. Pure — the deterministic pre-gate before any model call."""
    cands = [
        p for p in (pieces or [])
        if isinstance(p, dict)
        and (p.get("transcript") or "").strip()
        and _is_flat_delivery(p.get("metrics"))
    ]
    cands.sort(key=lambda p: _flatness(p.get("metrics")), reverse=True)
    return cands


def build_messages(transcript: str) -> tuple[str, str]:
    """(system, user) for the constrained model call. Pure. The delivery read
    is a fixed plain-language phrase — never a number."""
    user = (
        f'Their words for this moment:\n"{(transcript or "").strip()}"\n\n'
        f"How the delivery came across: {_DELIVERY_DESCRIPTOR}."
    )
    return _SYSTEM_PROMPT, user


def extract_note(parsed: Any) -> Optional[str]:
    """Pull the note from the model's parsed JSON, applying every fence:
    only when ``words_positive`` is truthy, only a non-empty string, and only
    if it survives the AC-9 guard (no digits / construct vocabulary). None
    otherwise — silence beats an unguarded line."""
    if not isinstance(parsed, dict):
        return None
    if not parsed.get("words_positive"):
        return None
    note = parsed.get("note")
    if not isinstance(note, str) or not note.strip():
        return None
    try:
        from services.say_it_stronger import _guard_copy
        return _guard_copy(note)
    except Exception:
        return None


def _default_chat(system: str, user: str, *, user_id: Optional[str] = None) -> Optional[dict]:
    """Resolve and run the real model call, returning the parsed JSON dict or
    None. Lazy imports keep this module importable without the LLM stack."""
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


def annotate_pieces_with_alignment(
    pieces: Any,
    *,
    user_id: Optional[str] = None,
    chat_fn: Optional[Callable[[str, str], Optional[dict]]] = None,
) -> Optional[str]:
    """Find the strongest flat-delivery moment whose WORDS are clearly
    positive, and stamp a guarded ``delivery_alignment_note`` on that piece's
    metrics (cap: one per take). Returns the note, or None.

    The caller gates on :func:`delivery_alignment_enabled`; this function does
    the work and is best-effort — any failure returns None and never raises.
    ``chat_fn`` is injectable ``(system, user) -> parsed dict | None`` so the
    logic is unit-testable without the model.
    """
    chat = chat_fn or (lambda s, u: _default_chat(s, u, user_id=user_id))
    try:
        candidates = flat_delivery_candidates(pieces)
        for piece in candidates[:_MAX_LLM_ATTEMPTS]:
            transcript = (piece.get("transcript") or "").strip()
            if not transcript:
                continue
            system, user = build_messages(transcript)
            note = extract_note(chat(system, user))
            if note:
                metrics = piece.get("metrics")
                if isinstance(metrics, dict):
                    metrics["delivery_alignment_note"] = note
                return note
    except Exception as err:  # LIVE LOOP: never break the pipeline
        logger.warning(
            "delivery_alignment: annotate failed err=%s (non-fatal)", err,
        )
    return None
