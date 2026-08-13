"""The swap offer's two gates — stages 2 and 3 of the praise lane.

Stage 1 (`part_acoustics.strong_parts`) finds the parts this take delivered
above their own rolling average. That signal is ACOUSTIC: it says the voice
landed, and says nothing at all about the words. Two gates stand between it
and an offer, and they exist for different reasons:

  * THE FUMBLE FLOOR (stage 2, here, deterministic) — "was this said
    cleanly?" A booming, confident delivery of a sentence the speaker
    stumbled through is still a stumble, and offering to swap it in would
    make the engine look like it cannot hear the words. Free to run, so it
    runs first and keeps the LLM off obviously-bad candidates.

  * THE CONTINUITY GATE (stage 3, here, one LLM call) — "does it still make
    sense where it goes?" The swap drops a paragraph into a document whose
    NEIGHBOURS ARE LOCKED. A perfectly clean improvised line can still leave
    a dangling reference, a doubled transition, or a "like I said" pointing
    at something that is no longer there. The speech breaks even though every
    piece of it is fine.

WHY A DETERMINISTIC FLOOR AND AN LLM GATE, RATHER THAN ONE OR THE OTHER.
Founder ruling 2026-08-13 (Q3/Q4): the floor is NOT a similarity check
against the locked text. Similarity is inversely correlated with the value of
a swap — it only passes when the new words are nearly identical, which is
exactly when swapping them changes nothing, and it rejects the improvised
better formulation that is the whole point. So the floor asks about FUMBLES,
and coherence is left to the gate that can actually judge it.

THE LLM HERE IS FENCE-CLEAN, and the distinction matters because verbal
PRAISE was refused an LLM for what looks like the same reason. A praise
model would publish a subjective verdict to the student ("your phrasing is
strong") — a machine opinion on a user surface. This gate only ever REMOVES
an offer. Nothing it decides is ever shown, quoted or implied. An internal
filter is not a surfaced verdict, which is why one is allowed and the other
is not.

L1 ANTICIPATED THE THIRD OUTCOME. "SELECT the best ACTUAL take, VERBATIM +
a LIGHT AI continuity polish" — the polish exists in the locked choices
precisely because selected takes have to fit together. So the gate returns
fits / fits-with-polish / no, and the middle case is the one that saves the
good improvised line instead of discarding it for a connective word.

Best-effort throughout: any miss is NO OFFER, never a failed take (LIVE
LOOP).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Stage 2: the fumble floor ────────────────────────────────────────────
#
# Absolute thresholds, NOT a comparison against the locked text. The locked
# text has already been through `finalize_document`, so it carries no fillers
# by construction; measuring the live take against it would reject every
# candidate for the crime of being live.

MAX_FILLER_RATE = 0.06
"""Fillers per word. Roughly one 'um' in every seventeen words — above that
the sentence reads as hesitant no matter how it sounded. Deliberately
generous: the floor exists to catch a STUMBLE, not to demand fluency, and a
speaker who says one 'so' in a long paragraph has not fumbled it."""

MAX_REPEAT_RATE = 0.04
"""Immediate word repeats per word ("the the", "we we"). The clearest
signature of a false start that the transcript preserves."""

MIN_WORDS = 4
"""Below this there is nothing to judge and nothing worth swapping. Also
stops a one-word fragment from scoring a perfect 0.0 on every rate above and
sailing through as pristine."""

_REPEAT_RE = re.compile(r"\b(\w+)(\s+\1\b)+", re.IGNORECASE)
_TERMINAL = (".", "!", "?", "…")


def _words(text: str) -> list:
    return [w for w in re.split(r"\s+", text.strip()) if w]


def filler_rate(text: Any, language: Optional[str] = None) -> float:
    """Fillers per word, by the SHIPPED filler definition. Pure.

    Counted as the words `strip_fillers` removes, rather than against a
    second word list of this module's own. The smoothing fence is the
    product's one definition of a filler and it is language-aware; a private
    copy here would drift from it and then two parts of the pipeline would
    disagree about what an 'um' is. The founder's standing rule on filler
    data — never silently redefine it — applies to detectors, not just to
    stored labels.
    """
    doc = text if isinstance(text, str) else ""
    total = len(_words(doc))
    if not total:
        return 0.0
    try:
        from services.transcript_smoothing import strip_fillers
        kept = len(_words(strip_fillers(doc, language)))
    except Exception:
        return 0.0
    # ⚠️ THIS INCLUDES IMMEDIATE REPEATS. `strip_fillers` removes hesitations
    # AND collapses "we we we" in one pass, so the two signals cannot be
    # separated here without re-implementing it — which is exactly the
    # duplication this function exists to avoid. `fumble_reason` therefore
    # asks about repeats FIRST, so a false start is reported as one instead of
    # being blamed on fillers it does not contain. A wrong reason is worse
    # than no reason: the string exists so the lane can be tuned.
    return max(0.0, (total - kept) / total)


def repeat_rate(text: Any) -> float:
    """Immediately repeated words per word. Pure."""
    doc = text if isinstance(text, str) else ""
    words = _words(doc)
    if not words:
        return 0.0
    extra = 0
    for m in _REPEAT_RE.finditer(doc):
        extra += len(_words(m.group(0))) - 1
    return min(1.0, extra / len(words))


def is_truncated(text: Any) -> bool:
    """True when the piece does not close. Pure.

    Pieces carry restored punctuation by the time they reach here (the
    two-pointer alignment in lab_recording runs before assembly), so a
    missing terminal mark means the speaker was cut off or trailed away —
    not that punctuation was never available.
    """
    doc = (text if isinstance(text, str) else "").strip()
    if not doc:
        return True
    return not doc.endswith(_TERMINAL)


def fumble_reason(text: Any, language: Optional[str] = None) -> Optional[str]:
    """Why this take's words are not offerable, or None when they are clean.

    A REASON rather than a bool, because these three fail for different
    reasons and a lane that can only say "rejected" cannot be tuned. The
    string is internal — it rides the log and the funnel, never a payload.
    Pure.
    """
    doc = text if isinstance(text, str) else ""
    if len(_words(doc)) < MIN_WORDS:
        return "too_short"
    if is_truncated(doc):
        return "truncated"
    # REPEATS BEFORE FILLERS, and the order is the rule rather than taste.
    # `filler_rate` counts collapsed repeats too (see there), so asking it
    # first reports "We we we shipped it" as a filler problem in a sentence
    # containing no fillers at all.
    if repeat_rate(doc) > MAX_REPEAT_RATE:
        return "false_start"
    if filler_rate(doc, language) > MAX_FILLER_RATE:
        return "fillers"
    return None


# ── Stage 3: the continuity gate ─────────────────────────────────────────

FITS = "fits"
FITS_WITH_POLISH = "fits_with_polish"
NO_FIT = "no_fit"


def document_with_swap(parts: Any, part_id: Any, candidate: Any) -> str:
    """The document AS IT WOULD BE after the swap. Pure.

    The gate is asked about the WHOLE document rather than the candidate in
    isolation, because that is the thing that can break: neighbours are
    locked, so a dangling reference or a doubled transition only becomes
    visible next to the paragraphs that are staying. Same `\\n\\n` join the
    parts, the chunks and the provenance all use.

    Empty string when the part is not in the list — the caller then has
    nothing to evaluate and makes no offer, rather than evaluating a document
    the swap does not belong to.
    """
    rows = [p for p in (parts or []) if isinstance(p, dict)]
    target = str(part_id or "")
    if not target or not any(str(p.get("id") or "") == target for p in rows):
        return ""
    out = []
    for p in rows:
        if str(p.get("id") or "") == target:
            out.append(str(candidate or "").strip())
        else:
            out.append(str(p.get("text") or "").strip())
    return "\n\n".join(x for x in out if x)


def evaluate_continuity(document: Any, candidate: Any, *,
                        user_id: Optional[str] = None) -> dict:
    """Does the swapped document still hold together?

    ``{"verdict": FITS|FITS_WITH_POLISH|NO_FIT, "polish": str|None}``.

    NO_FIT ON EVERY FAILURE, and that direction is the opposite of the rest
    of this pipeline. A feedback read that hiccups must never take the
    surface dark, so those degrade toward SHOWING something; a gate that
    hiccups must never wave through a swap nobody checked, so this degrades
    toward showing NOTHING. Different failure, different safe direction.

    The polish is guarded through the same `_guard_copy` every other LLM lane
    uses, so the construct fence and the digit ban apply here too. A polish
    that fails the guard downgrades the verdict to FITS rather than being
    served unguarded — the candidate was fine, only the suggested connective
    was not.
    """
    doc = document if isinstance(document, str) else ""
    cand = str(candidate or "").strip()
    if not doc or not cand:
        return {"verdict": NO_FIT, "polish": None}
    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_DELIVERY_ALIGNMENT
        from services.prompts.swap_continuity import system as _system
        from services.say_it_stronger import _guard_copy
    except Exception as e:
        logger.info("swap_offer: continuity deps unavailable (%s)",
                    type(e).__name__)
        return {"verdict": NO_FIT, "polish": None}

    user = (f"CANDIDATE PARAGRAPH:\n{cand}\n\n"
            f"THE TALK AS IT WOULD READ:\n{doc[:4000]}")
    try:
        res = chat_complete(
            spec=SPEC_DELIVERY_ALIGNMENT, system=_system(), user=user,
            surface="swap_continuity", user_id=user_id,
            response_format_override={"type": "json_object"},
        )
    except Exception as e:
        logger.warning("swap_offer: continuity call failed: %s", e)
        return {"verdict": NO_FIT, "polish": None}
    if not res:
        return {"verdict": NO_FIT, "polish": None}
    try:
        import json
        parsed = json.loads(res.text or "{}")
    except Exception:
        return {"verdict": NO_FIT, "polish": None}
    if not isinstance(parsed, dict) or parsed.get("fits") is not True:
        return {"verdict": NO_FIT, "polish": None}

    polish = (parsed.get("polish") or "").strip()
    if not polish or polish == cand:
        return {"verdict": FITS, "polish": None}
    # A "polish" that rewrites the paragraph is not a polish — it is the
    # AI authoring the slide text, which L1 forbids outright. Length is a
    # blunt proxy and deliberately so: a connective fix moves a few words,
    # and anything past that is the model doing the speaker's job.
    if abs(len(polish) - len(cand)) > max(40, len(cand) * 0.25):
        logger.info("swap_offer: polish rejected as a rewrite (L1)")
        return {"verdict": FITS, "polish": None}
    try:
        guarded = _guard_copy(polish)
    except Exception:
        guarded = None
    if not guarded:
        return {"verdict": FITS, "polish": None}
    return {"verdict": FITS_WITH_POLISH, "polish": guarded}
