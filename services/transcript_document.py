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

# WITHIN a slide, pieces flow into prose — the talk reads as a talk, not as
# a list of fragments. ACROSS a slide boundary they become real paragraphs.
#
# That second separator is load-bearing, and it was missing (founder
# 2026-08-11). The read surface defines a CHUNK — the unit that carries one
# lock and one state — as a "\n\n" paragraph. With every piece space-joined,
# a whole talk was one chunk: one lock for 233 words, one pending suggestion
# painting the entire document, and no slide sections to scroll through,
# because the deck groups by slide and there was only ever one group. The
# 1:1 per-slide segmentation existed in the data the whole time and was
# thrown away here, at the join, in the one place the user reads it.
_JOIN = " "
_PARA = "\n\n"
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


def _slide_corrections(database, session_id: str) -> dict:
    """{snippet_id: slide_index} — the coach's own bucketing for this take.

    Best-effort: pre-migration or on hiccup the pipeline's bucket stands, the
    same floor `_build_take` uses. Never darkens a document."""
    try:
        return database.get_snippet_slide_corrections(session_id) or {}
    except Exception:
        return {}


def _slide_of(snip: Any, fixes: dict) -> Optional[int]:
    """The deck slide this piece's words were spoken on, or None.

    Coach correction first — the whole slide-correction affordance exists to
    make the human the ground truth here — then the cutter's own bucket
    (`metrics.piece.slide_index`), which is the same read every other surface
    keys on, so the document can never disagree with the take view about
    which slide a piece belongs to.

    A correction stored as None is a REVERT (the coach withdrew it) and falls
    THROUGH to the pipeline, exactly as `_build_take` treats it — hence the
    `isinstance(..., int)` test rather than a plain membership check."""
    fix = fixes.get(str((snip or {}).get("id") or ""))
    if isinstance(fix, int) and not isinstance(fix, bool):
        return fix
    m = (snip or {}).get("metrics")
    piece = m.get("piece") if isinstance(m, dict) else None
    si = piece.get("slide_index") if isinstance(piece, dict) else None
    return si if isinstance(si, int) and not isinstance(si, bool) else None


def _slide_runs(rows: list) -> list:
    """Group [(snippet, text, slide_index)] into CONTIGUOUS slide runs — one
    run per paragraph of the finished document.

    A run breaks only on a PROVABLE change of slide. A piece whose slide is
    unknown (no deck, no timeline, no correction) joins the run it is in and
    never starts one: an unprovable boundary must not become a lock unit, and
    a document with no slide information at all stays a single flowing
    paragraph — precisely today's behaviour, which is the right degradation
    rather than invented structure."""
    runs: list = []
    for snip, text, si in rows:
        last = runs[-1] if runs else None
        if last is not None and (si is None or last["slide"] is None
                                 or si == last["slide"]):
            last["items"].append((snip, text))
            if last["slide"] is None:
                last["slide"] = si
        else:
            runs.append({"slide": si, "items": [(snip, text)]})
    return runs


def _close(text: str) -> tuple:
    """(body, terminal mark) for the LAST piece of a paragraph.

    `smooth_piece` deliberately leaves pieces unpunctuated (a piece is very
    often mid-sentence) and `finalize_document` closes only the document's
    very end — invisible while the whole talk was one paragraph, and the seam
    between every pair of them the moment slides split it.

    THE MARK IS RETURNED SEPARATELY because a piece's text is not only what
    it reads as: it is the KEY that suggestion feedback is filed under, and
    the span the tracked-change anchors point at. Growing a piece by a full
    stop silently rewrites those keys. So the mark goes into the document
    AFTER the piece's span closes — exactly where `finalize_document` used to
    put the document's own, which is why nothing downstream ever saw it.

    A dangling separator is trimmed rather than closed over (",." reads as a
    typo); that is the one case where the piece's own text moves, and it is
    the same trim `finalize_document` already applied at the document end."""
    body = text.rstrip()
    if not body:
        return text, ""
    if body[-1] in ".!?":
        return body, ""
    trimmed = body.rstrip(",;: ")
    if not trimmed:
        return body, ""
    if trimmed[-1] in "\"'’”)]" and len(trimmed) >= 2 and trimmed[-2] in ".!?":
        return trimmed, ""
    return trimmed, "."


def build_transcript_document(arc_id: Any, *, database=None,
                              session_id: Any = None) -> Optional[dict]:
    """The full-transcript document for an arc's LATEST spoken take (or an
    explicit session_id — the historical/per-take form).

    Returns {"text", "pieces": [{snippet_id, take_session_id, take_index,
    start, end, text, slide_index}], "paragraphs": [{slide_index,
    snippet_id, take_session_id, take_index, start, end}],
    "take_session_id", "take_index"} or None when there is nothing to build
    (no spoken take / no transcribed pieces).

    `pieces` is per SNIPPET — the anchor contract tracked changes hang on.
    `paragraphs` is per "\\n\\n" PARAGRAPH, which is what the read surface
    turns into chunks; the two differ whenever a slide holds more than one
    piece, and conflating them is what silently dropped every slide
    attachment before (founder 2026-08-11).

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
        slide_fixes = _slide_corrections(database, sid)

        # PASS 1 — every piece that has words, in spoken order, carrying the
        # slide it was delivered on.
        rows: list = []
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
            rows.append((s, text, _slide_of(s, slide_fixes)))
        if not rows:
            return None

        # PASS 2 — slide runs become paragraphs, and the spans are laid out
        # over the separators that actually go between them.
        pieces: list = []
        paragraphs: list = []
        out: list = []
        cursor = 0
        for run_i, run in enumerate(_slide_runs(rows)):
            if run_i:
                out.append(_PARA)
                cursor += len(_PARA)
            para_start = cursor
            items = run["items"]
            for i, (s, text) in enumerate(items):
                if i:
                    out.append(_JOIN)
                    cursor += len(_JOIN)
                mark = ""
                if i == len(items) - 1:
                    text, mark = _close(text)
                start = cursor
                cursor += len(text)
                out.append(text)
                pieces.append({
                    "snippet_id": str(s.get("id")),
                    "take_session_id": sid,
                    "take_index": take_index,
                    "start": start,
                    "end": cursor,
                    "text": text,
                    "slide_index": run["slide"],
                    "breakthrough": str(s.get("id")) in breakthroughs,
                    "start_offset_ms": s.get("start_offset_ms"),
                    "duration_ms": s.get("duration_ms"),
                })
                # OUTSIDE the piece's span, on purpose — see `_close`.
                if mark:
                    out.append(mark)
                    cursor += len(mark)
            # ONE ROW PER PARAGRAPH — the read surface's chunks are the
            # document's paragraphs, so provenance has to be counted the same
            # way. Serving one row per SNIPPET is what made the consumer's
            # "same length?" alignment test fail and drop every slide
            # attachment on the floor.
            paragraphs.append({
                "slide_index": run["slide"],
                "snippet_id": str(items[0][0].get("id")),
                "take_session_id": sid,
                "take_index": take_index,
                "start": para_start,
                "end": cursor,
            })

        # DOCUMENT-level finish: length-preserving casing + ONE terminal
        # mark at the very end, so every span above stays valid. The
        # pieces then re-slice from the finished text so piece text and
        # document text can never disagree.
        doc = finalize_document("".join(out))
        for p in pieces:
            p["text"] = doc[p["start"]:p["end"]]
        if len(doc) > _MAX_DOC_CHARS:
            cut = doc.rfind(" ", 0, _MAX_DOC_CHARS)
            doc = doc[:cut if cut > 0 else _MAX_DOC_CHARS].rstrip()
            doc = finalize_document(doc)
            pieces = [p for p in pieces if p["end"] <= len(doc)]
            paragraphs = [p for p in paragraphs if p["end"] <= len(doc)]
            if not pieces or not paragraphs:
                return None
        return {
            "text": doc,
            "pieces": pieces,
            # One entry per "\n\n" paragraph of `text`, in order — what the
            # read surface's chunks actually are.
            "paragraphs": paragraphs,
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


# How exactly a piece's span was established. Two values, because there is
# exactly one question a consumer needs answered: may I trust this to the
# word? A gap-shared span is less precise than a paragraph one, and both
# answer that question the same way.
WORD_GRAIN = "word"
PARAGRAPH_GRAIN = "paragraph"


def paragraph_spans(text: Any) -> list:
    """[(start, end)] of the document's non-blank paragraphs. Pure.

    The same `\\n\\n` split the parts, the deck chunks and the per-slide
    provenance all use — one definition of "paragraph", not a fourth.
    Offsets are into `text` and exclude the surrounding blank space.
    """
    doc = text if isinstance(text, str) else ""
    out: list = []
    at = 0
    for block in doc.split(_PARA):
        stripped = block.strip()
        if stripped:
            lo = at + (len(block) - len(block.lstrip()))
            out.append((lo, lo + len(stripped)))
        at += len(block) + len(_PARA)
    return out


def relocate_pieces(text: Any, pieces: Any, *,
                    paragraph_fallback: bool = False) -> list:
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
    gone, so there is no region either.

    THE ANCHOR GUARD (2026-08-12). Pass 2 is a REPAIR, and what makes it a
    repair rather than a guess is the located neighbours: they are the
    evidence that bounds the gap. Every unlocated run is bounded on at least
    one side by a real anchor EXCEPT one — the run that is the whole list,
    which happens when NOTHING anchored (a take recomposed the text, a coach
    retyped it, the wrong arc's pieces were handed in). There the "gap" is
    `0..len(doc)` and both bounds are invented, so the pieces get split at
    width-proportional positions derived from nothing. The result passes
    `verify_spans` — the text is re-read from the document — which is exactly
    what makes it dangerous: slide indexes attach to arbitrary paragraphs and
    every anchor derived from a piece (key_moments, the coach's video chip)
    points at words the coach never spoke about.

    So an unbounded run is dropped, with ONE exception that is not a guess: a
    single piece IS the whole document by definition, so it may take it. Two
    or more with no anchors is invention, and the deck's standing rule is
    drop, never guess — a short piece list collapses the deck to one untitled
    section, which is legible; chips on the wrong words are not.

    Pure."""
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
    # ── Pass 2a — THE PARAGRAPH FALLBACK (founder 2026-08-12) ──────────────
    #
    # "If a chunk is locked (edited or not), the AI shouldn't drop the new
    # feedback entirely just because the cross-take words shifted."
    #
    # THIS IS THE NORMAL PATH, not an edge case. Lock a paragraph — even the
    # AI's own words, unedited — and record again: `compose_locked` keeps the
    # locked text while the pieces come from the NEW take's assembly, so not
    # one of them is found. Every later take makes it worse. R1 gen-4 exists
    # to re-open a locked chunk on new feedback and had never once been able
    # to fire, because the anchoring died upstream of it.
    #
    # WHY THIS IS NOT THE GUESSING THE GUARD FORBIDS. The paragraph split is
    # the same `\n\n` the parts, the chunks and the provenance all use, and
    # `compose_locked` BUILDS the served text out of those paragraphs. So a
    # paragraph span is not a match and not an interpolation — it is a
    # construction, exact in its own coordinate system. What it loses is
    # PRECISION, not correctness, and `anchor_grain` says so out loud rather
    # than letting a consumer assume word-level accuracy it no longer has.
    #
    # Only on an exact 1:1 count — the same safe-ahead rule the slide zip
    # follows. A mismatch means the pieces and the document disagree about
    # what the paragraphs are, and then position is a guess again.
    para = paragraph_spans(doc) if paragraph_fallback else []
    if para and len(para) == len(src):
        zipped: list = []
        for i, p in enumerate(src):
            if found[i] is not None:
                lo, hi = found[i]
                zipped.append({**p, "start": lo, "end": hi,
                               "anchor_grain": WORD_GRAIN})
            else:
                lo, hi = para[i]
                # Re-read from the document, so `verify_spans` holds and
                # tracked_changes' own words-still-there check passes.
                zipped.append({**p, "start": lo, "end": hi,
                               "text": doc[lo:hi],
                               "anchor_grain": PARAGRAPH_GRAIN})
        _coarse = sum(1 for q in zipped
                      if q["anchor_grain"] == PARAGRAPH_GRAIN)
        if _coarse:
            logger.info(
                "relocate_pieces: %d/%d piece(s) anchored at PARAGRAPH grain "
                "(cross-take drift or a locked paragraph) — feedback keeps "
                "flowing, word-precise consumers will decline",
                _coarse, len(zipped))
        return zipped

    if len(src) > 1 and not any(f is not None for f in found):
        logger.warning(
            "relocate_pieces: NO anchor survived — dropping %d pieces rather "
            "than width-guessing them across %d chars (chips would point at "
            "the wrong words). No paragraph fallback available: "
            "fallback=%s paragraphs=%d pieces=%d",
            len(src), len(doc), paragraph_fallback, len(para), len(src))
        return []
    # Pass 2 — hand each unlocated RUN the space between its neighbours.
    out: list = []
    i = 0
    while i < len(src):
        if found[i] is not None:
            lo, hi = found[i]
            out.append({**src[i], "start": lo, "end": hi,
                        "anchor_grain": WORD_GRAIN})
            i += 1
            continue
        j = i
        while j < len(src) and found[j] is None:
            j += 1
        gap_lo = found[i - 1][1] if i > 0 and found[i - 1] else 0
        gap_hi = found[j][0] if j < len(src) and found[j] else len(doc)
        # A gap-shared span is a width interpolation — LESS precise than a
        # paragraph, and certainly not word-exact. It answers the only
        # question a consumer asks ("may I trust this to the word?") the same
        # way a paragraph span does, so it carries the same grain rather than
        # inventing a third value nobody would branch on differently.
        out.extend({**q, "anchor_grain": PARAGRAPH_GRAIN}
                   for q in _share_gap(doc, gap_lo, gap_hi, src[i:j]))
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
