"""The acoustic swap lane — stage 4, the orchestration (founder 2026-08-13).

THE GAP THIS FILLS. A locked paragraph is frozen by construction: the ranker
selects the best take per slide, but a part the student locked is excluded from
that selection entirely, so no amount of better delivery on a later take can
reach it. The student's own words stay, and the take where they finally landed
that paragraph goes nowhere. This lane is the one path back in — it ASKS.

WHY THE COMPARISON IS ACOUSTIC AND NOT `power_score`. `power_score` is the
ranker, and the ranker has no opinion here: a locked part is not in its
selection. There is no second answer to contest. And today `power_score`
reduces to content terms alone (`VOICE_CONFIDENCE_RANKING_ENABLED` is off by
decision until the composite is validated, SPEC §7.3), so a lane whose whole
premise is "the VOICE landed" would have been deciding on slide coverage.
`beats_incumbent` reads the acoustic control composite, ungated, today.

THE CHAIN, in cost order — the free deterministic gates run first so the one
LLM call only ever sees candidates that already passed everything cheap:

    beats_incumbent  →  already-starred?  →  fumble floor  →  continuity gate

  1. BEATS THE INCUMBENT (services/part_acoustics) — this take's delivery of
     the part, against the persisted document's delivery of the same part, on
     the same baseline. Head-to-head, not against a rolling average: the
     document is the best-of assembly, so a rolling comparison asked this take
     to beat the strongest version that has ever survived, which is a bar that
     mostly cannot be cleared (founder's Option C, 2026-08-13).
  2. COLLISION — content first. A snippet already carrying a suggestion keeps
     it. Praise arrives when there is nothing louder to say, never instead of
     a correction.
  3. THE FUMBLE FLOOR (services/swap_offer) — booming delivery of a sentence
     the speaker stumbled through is still a stumble.
  4. THE CONTINUITY GATE (services/swap_offer) — the swap drops a paragraph
     into a document whose neighbours are LOCKED, so a clean line can still
     leave a dangling reference or a doubled transition.

Best-effort throughout: any miss is NO OFFER, never a failed take (LIVE LOOP).
Every decline is COUNTED and logged — this lane was designed on a day that
found six separate stages which declined without saying so.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

TRIGGER = "acoustic_swap"
"""The persisted `moment_suggestions.trigger` for this lane. Its own string so
the serve mix, the FE label and the anchoring exemption can all find it —
and so a swap is never mistaken for the polish lane's `replace`."""

MAX_PER_TAKE = 1
"""One offer per take. The lane interrupts a LOCKED paragraph — the student
already decided those words were finished — so it has a higher bar to clear
than an ordinary suggestion, and a take that opens three settled paragraphs
reads as the engine arguing with a decision rather than reporting a fact.
The strongest lift wins (`beats_incumbent` returns sorted)."""


def _locked_part_ids(parts: Any) -> set:
    return {
        str(p.get("id"))
        for p in (parts or [])
        if isinstance(p, dict) and p.get("locked") and p.get("id")
    }


def _take_text_for_part(pieces: Any, part_id: Any, parts: Any) -> str:
    """This take's words for one part, joined in speech order. Pure.

    The candidate is what the speaker ACTUALLY said this take for the span the
    locked part covers — verbatim, never assembled or rewritten (L1).
    """
    from services.ideal_text_parts import part_at, part_spans
    spans = part_spans(parts)
    if not spans:
        return ""
    target = str(part_id or "")
    out = []
    for p in (pieces or []):
        if not isinstance(p, dict):
            continue
        part = part_at(spans, p.get("start"), p.get("end"))
        if part and str(part.get("id") or "") == target:
            out.append((p.get("text") or "").strip())
    return " ".join(t for t in out if t).strip()


def offer_for_take(arc_id: Any, user_id: Any, session_id: Any, *,
                   database=None) -> int:
    """Find at most one locked paragraph this take delivered better, and offer
    the swap. Returns the number of offers stored (0 or 1).

    Runs after the eager assembly and after the acoustic fold, so the document
    it compares against is the one this take just contributed to.
    """
    if not arc_id or not user_id or not session_id:
        return 0
    try:
        if database is None:
            from services.db import db as database
        from services.acoustic_baseline import current as current_baseline
        from services.part_acoustics import (
            _with_metrics, beats_incumbent, take_z_by_part,
        )
        from services.swap_offer import (
            FITS, FITS_WITH_POLISH, document_with_swap, evaluate_continuity,
            fumble_reason,
        )
        from services.transcript_document import build_transcript_document

        baseline, _bid = current_baseline(user_id, database=database)
        if not baseline:
            return 0                     # cold start; nothing to compare on
        parts = database.get_ideal_text_parts(str(arc_id), str(user_id))
        locked = _locked_part_ids(parts)
        if not locked:
            # NOTHING TO OFFER, and this is the common case rather than a
            # fault: a student who has locked nothing has no frozen paragraph
            # for a better take to be shut out of.
            logger.info("swap_detector: no locked parts arc=%s", arc_id)
            return 0

        row = database.get_coach_arc_ideal_text(str(arc_id)) or {}
        doc_pieces = ((row.get("document") or {}).get("pieces")
                      if isinstance(row.get("document"), dict) else None)
        doc_scored = _with_metrics(doc_pieces, arc_id, database)
        take_doc = build_transcript_document(
            arc_id, database=database, session_id=session_id) or {}
        take_scored = _with_metrics(
            take_doc.get("pieces"), arc_id, database)
        if not doc_scored or not take_scored:
            logger.info(
                "swap_detector: no comparison arc=%s (doc_pieces=%d "
                "take_pieces=%d after the metrics join)",
                arc_id, len(doc_scored), len(take_scored))
            return 0

        take_z = take_z_by_part(take_scored, parts, baseline)
        doc_z = take_z_by_part(doc_scored, parts, baseline)
        winners = [(pid, lift) for pid, lift in beats_incumbent(take_z, doc_z)
                   if pid in locked]
        if not winners:
            logger.info(
                "swap_detector: no locked part beat its incumbent arc=%s "
                "(scored=%d locked=%d)", arc_id, len(take_z), len(locked))
            return 0

        return _offer_best(winners, arc_id, session_id, parts, take_scored,
                           database=database,
                           gates=(fumble_reason, document_with_swap,
                                  evaluate_continuity),
                           verdicts=(FITS, FITS_WITH_POLISH))
    except Exception as e:
        logger.warning("swap_detector: pass failed arc=%s: %s", arc_id, e)
        return 0


def _offer_best(winners: list, arc_id: Any, session_id: Any, parts: Any,
                take_pieces: Any, *, database, gates, verdicts) -> int:
    """Walk the winners strongest-first and store the first that clears every
    gate. Split out so the gate order reads in one screen."""
    fumble_reason, document_with_swap, evaluate_continuity = gates
    fits, fits_with_polish = verdicts
    stored = 0
    _no_text = _starred = _fumbled = _no_fit = 0

    for part_id, _lift in winners:
        if stored >= MAX_PER_TAKE:
            break
        candidate = _take_text_for_part(take_pieces, part_id, parts)
        if not candidate:
            _no_text += 1
            continue
        snippet_id = _snippet_for_part(take_pieces, part_id, parts)
        if not snippet_id:
            _no_text += 1
            continue
        # COLLISION — content first (founder). A snippet already carrying a
        # suggestion keeps it: a correction outranks praise every time, and
        # the upsert is snippet-keyed so writing here would REPLACE it rather
        # than sit beside it.
        if _already_starred(snippet_id, arc_id, database):
            _starred += 1
            continue
        why_not = fumble_reason(candidate)
        if why_not:
            _fumbled += 1
            continue
        swapped = document_with_swap(parts, part_id, candidate)
        if not swapped:
            _no_text += 1
            continue
        verdict = evaluate_continuity(swapped, candidate)
        if verdict.get("verdict") not in (fits, fits_with_polish):
            _no_fit += 1
            continue
        # L1: the offer is the speaker's own words. A polish is the light
        # continuity fix the lock explicitly permits, and `evaluate_continuity`
        # has already refused anything longer than a connective.
        replacement = verdict.get("polish") or candidate
        if database.upsert_moment_suggestion(
                str(snippet_id), str(arc_id), "replace", replacement,
                None, TRIGGER):
            stored += 1

    logger.info(
        "swap_detector: sid=%s arc=%s winners=%d stored=%d "
        "(no_text=%d already_starred=%d fumbled=%d no_fit=%d)",
        session_id, arc_id, len(winners), stored,
        _no_text, _starred, _fumbled, _no_fit)
    return stored


def _snippet_for_part(pieces: Any, part_id: Any, parts: Any) -> Optional[str]:
    """The snippet a part's offer hangs on — the FIRST piece in the part.

    The suggestion table is keyed by snippet, and a part may span several
    pieces. First-in-speech-order is the stable choice: it is the paragraph's
    opening words, which is where the student's eye lands, and it does not
    move between takes the way "longest" or "best" would.
    """
    from services.ideal_text_parts import part_at, part_spans
    spans = part_spans(parts)
    if not spans:
        return None
    target = str(part_id or "")
    for p in (pieces or []):
        if not isinstance(p, dict):
            continue
        part = part_at(spans, p.get("start"), p.get("end"))
        if part and str(part.get("id") or "") == target and p.get("snippet_id"):
            return str(p["snippet_id"])
    return None


def _already_starred(snippet_id: Any, arc_id: Any, database) -> bool:
    """Does this snippet already carry a suggestion? Best-effort.

    TRUE ON ERROR — the safe direction here, and the opposite of most reads on
    this path. Failing open would let the swap OVERWRITE a correction the
    student was about to see (the upsert is snippet-keyed), so an unreadable
    ledger costs at most one praise offer instead of silently eating a
    content fix.
    """
    try:
        existing = database.get_moment_suggestions_by_arc(str(arc_id)) or {}
    except Exception as e:
        logger.warning("swap_detector: suggestion read failed arc=%s: %s",
                       arc_id, e)
        return True
    return str(snippet_id) in {str(k) for k in existing}
