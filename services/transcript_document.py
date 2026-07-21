"""The Living Transcript document (founder decision 2026-07-20, #1).

THE RE-SHAPE: the ideal text stops being a stitched selection of the
best-ranked moments — which is why the founder's live test came back
"much shorter than what I really said" — and becomes the SPEAKER'S FULL
TRANSCRIPT of the take, literally, in speech order, with only the
minimum smoothing (services/transcript_smoothing.py).

Version N is the transcript of SPOKEN take N (decision #4: a new take's
words become the new document; where a PREVIOUS take's fragment ranked
better it comes back as an approvable revert-suggestion — BE-D). Reads
never produce a document (they are paired variants, not takes).

Per piece the text source mirrors the coach packet's locked priority
(assumption A1): the coach's correction > the student's approved edit >
the raw transcript. Every piece keeps its CHARACTER SPAN in the assembled
document — that span is what the tracked-change suggestions anchor to
(BE-C), so a suggestion always points at exactly the words it is about.

L1: the document is verbatim actual speech; the only silent transforms
are the fenced fillers/punctuation. AC-9: text only, no scores.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Pieces are joined into flowing prose — the document reads as one talk,
# not as a list of fragments.
_JOIN = " "
_MAX_DOC_CHARS = 40000


def _piece_text(snip: dict, corrections: dict, edits: dict) -> str:
    """One piece's source text, locked priority (A1)."""
    sid = str(snip.get("id") or "")
    return ((corrections.get(sid) or "").strip()
            or (edits.get(sid) or "").strip()
            or (snip.get("transcript") or "").strip()
            or (snip.get("transcription_text") or "").strip())


def _load_overlays(database, session_id: str) -> tuple:
    """(coach corrections, student edits) for a take. Best-effort — an
    overlay read failure degrades to the raw transcript, never breaks
    the document."""
    corrections: dict = {}
    edits: dict = {}
    try:
        for d in (database.get_coach_snippet_drafts(session_id) or []):
            _t = (d.get("transcript_corrected") or "").strip()
            if _t and d.get("snippet_id") is not None:
                corrections[str(d["snippet_id"])] = _t
    except Exception:
        pass
    try:
        for e in (database.get_user_transcript_edits(session_id) or []):
            _t = (e.get("text") or "").strip()
            if _t and e.get("snippet_id") is not None:
                edits[str(e["snippet_id"])] = _t
    except Exception:
        pass
    return corrections, edits


def _breakthrough_ids(database, session_id: str) -> set:
    """Coach-SURFACED pieces of this take — they stay key moments on the
    document so the explanations lane (and the only paid surface) keeps
    working in transcript mode (review finding). Best-effort."""
    out = set()
    try:
        for d in (database.get_coach_snippet_drafts(session_id) or []):
            if d.get("surfaced") and d.get("snippet_id") is not None:
                out.add(str(d["snippet_id"]))
    except Exception:
        pass
    return out


def build_transcript_document(arc_id: Any, *, database=None,
                              session_id: Any = None) -> Optional[dict]:
    """The full-transcript document for an arc's LATEST spoken take (or an
    explicit session_id — the historical/per-take form).

    Returns {"text", "pieces": [{snippet_id, take_session_id, take_index,
    start, end, text}], "take_session_id", "take_index"} or None when
    there is nothing to build (no spoken take / no transcribed pieces).

    `start`/`end` are CHARACTER offsets into `text` — the anchor contract
    for tracked changes. Best-effort; never raises."""
    try:
        if database is None:
            from services.db import db as database
        from services.best_presentation import spoken_arc_sessions
        from services.transcript_smoothing import (
            finalize_document, smooth_piece,
        )

        take_index = None
        if session_id:
            sid = str(session_id)
            try:
                _row = database.v2_get_session_by_id(sid) or {}
                take_index = _row.get("take_index")
            except Exception:
                take_index = None
        else:
            spoken = spoken_arc_sessions(
                database.get_arc_sessions(arc_id) or [])
            if not spoken:
                return None
            # The LATEST spoken take IS the current document (decision #4).
            spoken.sort(key=lambda s: (s.get("take_index") or 0,
                                       s.get("created_at") or ""))
            latest = spoken[-1]
            sid = str(latest.get("id") or "")
            take_index = latest.get("take_index")
            if not sid:
                return None

        snips = database.get_snippets_by_session(sid) or []
        if not snips:
            return None
        corrections, edits = _load_overlays(database, sid)
        breakthroughs = _breakthrough_ids(database, sid)

        pieces: list = []
        parts: list = []
        cursor = 0
        for s in sorted(snips, key=lambda x: ((x.get("start_offset_ms") or 0),
                                              str(x.get("id") or ""))):
            raw = _piece_text(s, corrections, edits)
            if not raw:
                continue
            # PER-PIECE: hesitations + repeats + tidy only. Casing and the
            # terminal mark belong to the finished document (a piece is
            # very often mid-sentence — review finding).
            text = smooth_piece(raw, s.get("language"))
            if not text:
                continue
            if parts:
                cursor += len(_JOIN)
            start = cursor
            cursor += len(text)
            parts.append(text)
            pieces.append({
                "snippet_id": str(s.get("id")),
                "take_session_id": sid,
                "take_index": take_index,
                "start": start,
                "end": cursor,
                "text": text,
                "breakthrough": str(s.get("id")) in breakthroughs,
                "start_offset_ms": s.get("start_offset_ms"),
                "duration_ms": s.get("duration_ms"),
            })
        if not pieces:
            return None

        # DOCUMENT-level finish: length-preserving casing + ONE terminal
        # mark at the very end, so every span above stays valid. The
        # pieces then re-slice from the finished text so piece text and
        # document text can never disagree.
        doc = finalize_document(_JOIN.join(parts))
        for p in pieces:
            p["text"] = doc[p["start"]:p["end"]]
        if len(doc) > _MAX_DOC_CHARS:
            cut = doc.rfind(" ", 0, _MAX_DOC_CHARS)
            doc = doc[:cut if cut > 0 else _MAX_DOC_CHARS].rstrip()
            doc = finalize_document(doc)
            pieces = [p for p in pieces if p["end"] <= len(doc)]
            if not pieces:
                return None
        return {
            "text": doc,
            "pieces": pieces,
            "take_session_id": sid,
            "take_index": take_index,
        }
    except Exception as e:
        logger.warning("transcript_document: build failed arc=%s: %s",
                       arc_id, e)
        return None


def relocate_pieces(text: Any, pieces: Any) -> list:
    """Re-anchor pieces onto a text that has CHANGED since the build (an
    approved change baked in, a coach correction landed).

    The search is MONOTONIC — each piece is looked for after the previous
    one's end — so repeated wording can never steal another piece's
    anchor (the first-occurrence defect the review found). A piece whose
    words are gone (it was the one that got replaced) is DROPPED: it has
    nothing left to point at. Pure."""
    doc = text if isinstance(text, str) else ""
    out: list = []
    cursor = 0
    for p in (pieces or []):
        if not isinstance(p, dict):
            continue
        needle = (p.get("text") or "").strip()
        if not needle:
            continue
        i = doc.find(needle, cursor)
        if i < 0:
            continue
        out.append({**p, "start": i, "end": i + len(needle)})
        cursor = i + len(needle)
    return out


def verify_spans(doc: Any) -> bool:
    """Every piece's [start,end) must slice back to its own text — the
    invariant the whole anchor contract rests on. Pure; used in tests and
    as a cheap runtime assert before persisting."""
    if not isinstance(doc, dict):
        return False
    text = doc.get("text") or ""
    for p in (doc.get("pieces") or []):
        try:
            if text[p["start"]:p["end"]] != p["text"]:
                return False
        except Exception:
            return False
    return True
