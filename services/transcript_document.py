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


def _snap(doc: str, at: int, lo: int, hi: int) -> int:
    """`at` moved to the nearest whitespace boundary inside [lo, hi] — so a
    computed split never lands mid-word. Prefers the break at or before
    `at`; falls back to the next one after it."""
    left = doc.rfind(" ", lo, at)
    if left > lo:
        return left + 1
    right = doc.find(" ", at, hi)
    if 0 <= right < hi:
        return right + 1
    return at


def _share_gap(doc: str, lo: int, hi: int, runs: list) -> list:
    """Assign [lo, hi) to the `runs` pieces, in order, proportionally to
    their ORIGINAL lengths and snapped to word boundaries.

    Only reached for a piece whose words the bake changed, so there is no
    exact anchor left to find. One piece takes the whole gap (the common
    case, and exact). Two or more adjacent changed pieces cannot have
    their internal boundary recovered from the text alone — proportional
    is the honest approximation, and it is strictly better than the
    alternative it replaces (dropping them, which loses the slide the
    words belong to and any coach moment on them)."""
    if lo >= hi or not runs:
        return []
    widths = [max(1, len((p.get("text") or "").strip())) for p in runs]
    total = sum(widths)
    out: list = []
    at = lo
    for i, p in enumerate(runs):
        end = hi if i == len(runs) - 1 else _snap(
            doc, lo + round((hi - lo) * sum(widths[:i + 1]) / total), at, hi)
        end = min(max(end, at), hi)
        chunk = doc[at:end]
        start = at + (len(chunk) - len(chunk.lstrip()))
        stop = end - (len(chunk) - len(chunk.rstrip()))
        if stop > start:
            out.append({**p, "start": start, "end": stop,
                        "text": doc[start:stop]})
        at = end
    return out


def relocate_pieces(text: Any, pieces: Any) -> list:
    """Re-anchor pieces onto a text that has CHANGED since the build (an
    approved change baked in, a coach correction landed).

    A PIECE IS A REGION OF THE DOCUMENT, not a string that must still
    exist verbatim (founder-critical fix 2026-08-11). This used to be a
    single monotonic exact find that DROPPED whatever it could not
    locate — and a bake changes exactly the words it lands on: a
    polish/replace swaps the phrase, an emphasis wraps {{orange:…}}
    around it. So the piece the student had just accepted a change on was
    the one that vanished, taking with it the slide index the FE zips 1:1
    to build the per-slide deck (a short list collapses the deck into one
    untitled section — the 1:1 north star) and, when the piece was a
    surfaced breakthrough, the coach's key moment on those words.

    Two passes:
      1. MONOTONIC EXACT FIND, unchanged — each piece looked for after
         the previous one's end, so repeated wording can never steal
         another piece's anchor (the first-occurrence defect the earlier
         review found). Untouched documents come out byte-identical.
      2. Every piece the find missed takes the GAP its located neighbours
         leave. The document is its pieces in order, so the words between
         two anchors belong to whatever sat between them — that IS the
         changed piece, in its new spelling. Its `text` is re-read from
         the document, which keeps `verify_spans` true and keeps every
         anchor derived from it (key_moments) indexing the served text.

    A piece whose gap is EMPTY is still dropped: the words really are
    gone, so there is no region either. Pure."""
    doc = text if isinstance(text, str) else ""
    src = [p for p in (pieces or [])
           if isinstance(p, dict) and (p.get("text") or "").strip()]
    # Pass 1 — where each piece still is, or None.
    found: list = []
    cursor = 0
    for p in src:
        needle = (p.get("text") or "").strip()
        i = doc.find(needle, cursor)
        if i < 0:
            found.append(None)
            continue
        found.append((i, i + len(needle)))
        cursor = i + len(needle)
    # Pass 2 — hand each unlocated RUN the space between its neighbours.
    out: list = []
    i = 0
    while i < len(src):
        if found[i] is not None:
            lo, hi = found[i]
            out.append({**src[i], "start": lo, "end": hi})
            i += 1
            continue
        j = i
        while j < len(src) and found[j] is None:
            j += 1
        gap_lo = found[i - 1][1] if i > 0 and found[i - 1] else 0
        gap_hi = found[j][0] if j < len(src) and found[j] else len(doc)
        out.extend(_share_gap(doc, gap_lo, gap_hi, src[i:j]))
        i = j
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
