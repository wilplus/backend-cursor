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
    """The parts the student has settled, from a STORED row.

    ⚠️ THE COLUMN IS `locked_at`, NOT `locked`. `locked` is a WIRE field: it
    exists only after `ideal_text_parts.serve()` folds the timestamp down to a
    boolean for the client (see its docstring — "the timestamp stays
    server-side"). A stored row has never carried it. Reading `locked` here
    returned falsy for every part on every take, so this lane declined 100% of
    the time through its own "no locked parts" branch, which reads like the
    common case and is not (fixed 2026-08-13, same day it shipped).

    The caller must ALSO ask for the column: `get_ideal_text_parts` projects
    `id, ord, text` and adds `locked_at` only under `with_lock=True`.
    """
    return {
        str(p.get("id"))
        for p in (parts or [])
        if isinstance(p, dict) and p.get("locked_at") and p.get("id")
    }


def _take_z_by_slide(pieces: Any, baseline: Any = None) -> dict:
    """``{slide_index: z}`` for ONE take. Pure.

    WHY NOT `take_z_by_part`, WHICH IS RIGHT THERE. Because the two sides of
    this comparison are measured in different coordinate systems, and using it
    here silently mis-buckets.

    `part_spans` lays character offsets over `joined(parts)` — THE DOCUMENT
    (services/ideal_text_parts.py, and its own docstring warns the offsets may
    only be trusted "against a document the parts actually join to"). But this
    take's pieces come from `build_transcript_document(session_id=…)`, whose
    start/end are offsets into THAT TAKE'S OWN assembled text. Two different
    strings. Feeding the take's offsets to the document's spans buckets pieces
    onto whichever paragraph happens to sit at the same character index, drops
    the ones that straddle, and produces numbers that look plausible.

    SLIDE INDEX IS THE MAPPING THAT ACTUALLY HOLDS. Both sides carry it:
    `build_transcript_document` stamps `slide_index` on every piece from the
    slide run it belongs to, and the document is assembled one paragraph per
    slide run. So "which part of the talk is this?" is answerable across takes
    by slide, and is not answerable by character offset — the whole point of
    this lane is that the words differ.

    A slide with no pieces this take is ABSENT rather than 0.0, for the same
    reason `take_z_by_part` gives: the student may simply not have covered it,
    and a fabricated zero reads as "delivered exactly at baseline".
    """
    from services.snippet_salience import score_control_direction

    usable = [p for p in (pieces or [])
              if isinstance(p, dict) and isinstance(p.get("metrics"), dict)
              and isinstance(p.get("slide_index"), int)
              and not isinstance(p.get("slide_index"), bool)]
    if not usable:
        return {}
    scores = score_control_direction(usable, baseline=baseline)
    buckets: dict = {}
    for piece, z in zip(usable, scores):
        buckets.setdefault(int(piece["slide_index"]), []).append(float(z))
    return {si: sum(v) / len(v) for si, v in buckets.items()}


def _part_slides(doc_pieces: Any, parts: Any) -> dict:
    """``{part_id: slide_index}`` — which slide each document part came from.

    The join between the two coordinate systems, and it is derivable because
    the persisted document's pieces carry BOTH: their start/end are in the
    document's own text (so `part_at` is valid for them, unlike the take's),
    and their `slide_index` names the slide run they were spoken on.

    First piece wins for a part that spans several slide runs — parts are
    paragraphs and the document is joined one paragraph per run, so that is
    normally a 1:1 already; taking the first keeps it stable rather than
    letting a long paragraph's tail decide.
    """
    from services.ideal_text_parts import part_at, part_spans
    spans = part_spans(parts)
    if not spans:
        return {}
    out: dict = {}
    for p in (doc_pieces or []):
        if not isinstance(p, dict):
            continue
        si = p.get("slide_index")
        if not isinstance(si, int) or isinstance(si, bool):
            continue
        part = part_at(spans, p.get("start"), p.get("end"))
        if not part:
            continue
        pid = str(part.get("id") or "")
        if pid and pid not in out:
            out[pid] = int(si)
    return out


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
        # with_lock=True is LOAD-BEARING: without it the projection is
        # `id, ord, text` and no row carries a lock at all, so every part reads
        # as open and this lane declines on every take (the bug it shipped
        # with). The layer filter already asks for it the same way.
        parts = database.get_ideal_text_parts(
            str(arc_id), str(user_id), with_lock=True)
        locked = _locked_part_ids(parts)
        if not locked:
            # NOTHING TO OFFER, and this is a legitimate common case: a student
            # who has locked nothing has no frozen paragraph for a better take
            # to be shut out of. It is logged WITH the part count so "nobody
            # locked anything" cannot be confused with "the lock field never
            # arrived" — telling those two apart took a production audit once.
            logger.info(
                "swap_detector: no locked parts arc=%s (parts=%d, "
                "lock field present on %d)",
                arc_id,
                len(parts or []),
                sum(1 for p in (parts or [])
                    if isinstance(p, dict) and "locked_at" in p))
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

        # THE TWO SIDES ARE MEASURED DIFFERENTLY BECAUSE THEY LIVE IN
        # DIFFERENT COORDINATE SYSTEMS (see _take_z_by_slide).
        #   document side — its pieces ARE anchored in the document's own text,
        #                   so part_at is valid and take_z_by_part is correct.
        #   take side     — its pieces are anchored in THIS TAKE's text, so the
        #                   same call would bucket by character positions in a
        #                   string the parts do not describe. Bucket by SLIDE,
        #                   then map slide→part using the document's own pieces.
        doc_z = take_z_by_part(doc_scored, parts, baseline)
        take_by_slide = _take_z_by_slide(take_scored, baseline)
        part_slide = _part_slides(doc_scored, parts)
        take_z = {pid: take_by_slide[si]
                  for pid, si in part_slide.items() if si in take_by_slide}
        winners = [(pid, lift) for pid, lift in beats_incumbent(take_z, doc_z)
                   if pid in locked]
        if not winners:
            logger.info(
                "swap_detector: no locked part beat its incumbent arc=%s "
                "(locked=%d doc_parts=%d take_slides=%d comparable=%d)",
                arc_id, len(locked), len(doc_z), len(take_by_slide),
                len(take_z))
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

    ⚠️ THIS FAILS OPEN, AND IT CANNOT BE MADE TO FAIL CLOSED FROM HERE. The
    except below is DEAD: `get_moment_suggestions_by_arc` catches its own
    exceptions and returns {} on a missing table or a failed query
    (services/db.py, its docstring says so). So a read failure is
    indistinguishable from "this arc has no suggestions", and the caller then
    writes — where the upsert is snippet-keyed and would REPLACE a correction
    the student was about to see.

    It is kept and documented rather than silently deleted because the earlier
    version of this docstring claimed the opposite ("TRUE ON ERROR — the safe
    direction"), and a comment asserting a protection that does not exist is
    worse than no comment: the next reader budgets for a risk that is still
    live. Closing it for real needs the reader to distinguish empty from
    failed, which is a change to db.py and a separate decision.

    Residual exposure is bounded: one praise offer replacing one correction, on
    an arc whose suggestion table is already erroring.
    """
    try:
        existing = database.get_moment_suggestions_by_arc(str(arc_id)) or {}
    except Exception as e:      # pragma: no cover — see the docstring
        logger.warning("swap_detector: suggestion read failed arc=%s: %s",
                       arc_id, e)
        return True
    return str(snippet_id) in {str(k) for k in existing}
