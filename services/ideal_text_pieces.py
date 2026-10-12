"""The slide linkage of the speaker's Ideal Text: one `pieces[]` entry per
served paragraph, each with the deck page its words were bucketed to when
the mapping is provable (FE handoff 2026-08-03, FE PR #222).

Moved out of ``routes.v2.explore_ideal_text`` unchanged (founder 2026-10-12).
Provenance only, no scores (AC-9); the composer never runs on a read.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _snip_slide(snip):
    # The cutter's own bucket (the slide on screen when the words
    # were spoken).
    m = (snip or {}).get("metrics")
    piece = m.get("piece") if isinstance(m, dict) else None
    si = piece.get("slide_index") if isinstance(piece, dict) else None
    return si if isinstance(si, int) and not isinstance(si, bool) \
        else None


def _ideal_piece_provenance_from_stored_paragraphs(_stored_paragraphs, _same_body):
    if not (_stored_paragraphs and _same_body):
        return None
    return [{
        "slide_index": p.get("slide_index"),
        "snippet_id": p.get("snippet_id"),
        "take_session_id": p.get("take_session_id"),
        "take_index": p.get("take_index"),
        "status": "settled",
        "challenger": None,
    } for p in _stored_paragraphs if isinstance(p, dict)]


def _ideal_piece_provenance_from_relocated_pieces(
    _stored_pieces, _same_body, served_text,
):
    if not (_stored_pieces and _same_body
            and isinstance(served_text, str) and served_text):
        return None
    from services.transcript_document import (
        paragraph_spans, relocate_pieces,
    )
    _located = relocate_pieces(
        served_text, _stored_pieces, paragraph_fallback=True)
    _derived = []
    for _lo, _hi in paragraph_spans(served_text):
        _piece = next((p for p in _located
                       if isinstance(p.get("start"), int)
                       and isinstance(p.get("end"), int)
                       and p["start"] < _hi
                       and p["end"] > _lo), None)
        if _piece is None:
            _derived = []
            break
        _derived.append({
            "slide_index": _piece.get("slide_index"),
            "snippet_id": _piece.get("snippet_id"),
            "take_session_id": _piece.get("take_session_id"),
            "take_index": _piece.get("take_index"),
            "status": "settled",
            "challenger": None,
        })
    return _derived or None


def _ideal_piece_provenance_by_slot(_stored_paragraphs, served_text):
    """Slot-for-slot Slide lineage when the words changed but the shape did
    not (founder 2026-09-28: "the text was not assigned to the slides ... it
    was all concatenated").

    The same proof the immutable snapshot already accepts
    (`ideal_text_core_snapshot._exact_pieces`, compatibility adoption): the
    edit surfaces rewrite Paragraph slots in place and cannot insert, delete,
    split, merge or reorder them, so on an equal Paragraph count slot N is
    still the Slide-bounded Paragraph N. Without this, any difference between
    the served words and the stored Take-1 body -- a later Take's rewrite, a
    folded suggestion -- threw every Slide away and the deck rendered one
    untitled section. A changed count still proves nothing and returns None."""
    if not (_stored_paragraphs and isinstance(served_text, str)
            and served_text.strip()):
        return None
    served = [p for p in served_text.split("\n\n") if p.strip()]
    rows = [p for p in _stored_paragraphs if isinstance(p, dict)]
    if len(rows) != len(_stored_paragraphs) or len(rows) != len(served):
        return None
    return _ideal_piece_provenance_from_stored_paragraphs(rows, True)


def _ideal_piece_provenance_canonical(database, arc_id, served_text):
    # CANONICAL SOURCE FIRST. Take 1's document provenance is persisted in
    # the same database write as its text. Later Takes advance the REVIEW
    # version without replacing those words, so rebuilding provenance from
    # the latest transcript describes a different document. That mismatch
    # is what made the FE reject the whole Ideal Text after Take 2.
    try:
        _ideal_row = database.ideal_text.get_coach_arc_ideal_text(arc_id) or {}
        _stored_doc = _ideal_row.get("document") or {}
        _stored_paragraphs = _stored_doc.get("paragraphs") or []
        _canonical_body = str(
            _ideal_row.get("auto_text") or _ideal_row.get("text") or "")
        try:
            from services.ideal_text_block import (
                sanitize_markers, strip_moment_markers,
            )
            _canonical_body = sanitize_markers(
                strip_moment_markers(_canonical_body))
        except Exception:
            _canonical_body = _canonical_body.strip()
        _same_body = (
            not isinstance(served_text, str)
            or not served_text
            or served_text.strip() == _canonical_body.strip()
        )
        exact = _ideal_piece_provenance_from_stored_paragraphs(
            _stored_paragraphs, _same_body)
        if exact is not None:
            return exact
        # Compatibility for canonical rows persisted between the document
        # column migration and this paragraph-grain fix. They have exact
        # canonical snippet pieces but no paragraph list. Re-anchor those
        # pieces to the currently served body, then derive one provenance
        # row per actual paragraph. Every paragraph must be covered; a
        # partial map falls through to the unlinked compatibility path.
        _stored_pieces = _stored_doc.get("pieces") or []
        relocated = _ideal_piece_provenance_from_relocated_pieces(
            _stored_pieces, _same_body, served_text)
        if relocated:
            return relocated
        adopted = _ideal_piece_provenance_by_slot(
            _stored_paragraphs, served_text)
        if adopted is not None:
            return adopted
    except Exception as _stored_doc_err:
        logger.warning(
            "stored ideal-text provenance failed arc=%s: %s",
            arc_id, _stored_doc_err)
    return None


def _ideal_piece_provenance_compat(database, arc_id):
    from services.transcript_document import build_transcript_document
    doc = build_transcript_document(arc_id, database=database)
    # ONE ROW PER PARAGRAPH (founder 2026-08-11). The consumer aligns
    # this list against the served text's "\n\n" paragraphs by LENGTH,
    # and `pieces` is per SNIPPET — so on any take where a slide held
    # more than one piece the counts disagreed, the alignment test
    # failed, and every slide attachment was dropped. `paragraphs` is
    # cut the same way the text is, by construction.
    rows = (doc or {}).get("paragraphs") or []
    if not rows:
        return []
    sid = doc.get("take_session_id")
    snips = {str(s.get("id")): s
             for s in (database.get_snippets_by_session(sid) or [])} \
        if sid else {}
    return [{
        # The document already resolved this (coach correction first,
        # then the cutter's bucket); `_snip_slide` stays as the floor
        # for a row that predates the field.
        "slide_index": (
            p.get("slide_index")
            if isinstance(p.get("slide_index"), int)
            and not isinstance(p.get("slide_index"), bool)
            else _snip_slide(snips.get(str(p.get("snippet_id"))))
        ),
        "snippet_id": p.get("snippet_id"),
        "take_session_id": p.get("take_session_id"),
        "take_index": p.get("take_index"),
        "status": "settled",
        "challenger": None,
    } for p in rows]


def _ideal_piece_provenance_legacy_cache(database, arc_id):
    from services.ideal_text_block import _polish_as_suggestions_enabled
    _get_cache = getattr(database, "get_best_presentation_cache", None)
    cached = _get_cache(arc_id) if callable(_get_cache) else None
    slides = ((cached or {}).get("payload") or {}).get("slides") or []
    _polish_on = _polish_as_suggestions_enabled()
    out = []
    for s in slides:
        if not isinstance(s, dict):
            continue
        _edited = (s.get("text") or "").strip()
        _verbatim = (s.get("verbatim") or "").strip()
        # Mirror the (removed, N48.3 Q13 A) best-of assembly's paragraph
        # filter exactly — a pick it skipped must not shift the alignment
        # of a document it built.
        if not ((_verbatim if _polish_on else _edited) or _edited):
            continue
        out.append({
            "slide_index": s.get("index"),
            "snippet_id": s.get("snippet_id"),
            "take_session_id": s.get("session_id"),
            "take_index": s.get("take_index"),
            "status": "settled",
            "challenger": None,
        })
    return out


def _ideal_piece_provenance(database, arc_id, deckless_ok=True, served_text=None):
    """``(lane, rows)``: the machine assembly's per-piece slide identity, in
    served order, and which lane produced it — mirrors
    mirrors maybe_assemble_ideal_text's source choice WITHOUT re-running
    any composition on the student GET:

      * living transcript: the take's pieces, slide from the cutter's
        metrics.piece.slide_index bucket;
      * legacy: the persisted best-presentation compose cache — the very
        picks auto_text's paragraphs were joined from. No cache row →
        no attachment; the composer (its LLM pass included) NEVER runs
        on this GET.

    ONE ENTRY PER SERVED PARAGRAPH, because that is what the caller aligns
    it against. `deckless_ok` gates the LEGACY lane only — see the comment
    at that branch.

    Each entry: {slide_index, snippet_id, take_session_id, take_index,
    status, challenger}. Best-effort; [] when nothing is provable.

    ``lane`` is one of canonical / compat / legacy_cache / deckless, so a
    misaligned read can say which source it came from (audit A3). The
    master-document skeleton lane is retired (audit C2)."""
    from services.ideal_text_block import _living_transcript_enabled

    if _living_transcript_enabled():
        canonical = _ideal_piece_provenance_canonical(database, arc_id, served_text)
        # `is not None`, not truthiness: stored paragraphs that yield no rows
        # are still the canonical answer, never a cue to rebuild provenance
        # from the latest transcript.
        if canonical is not None:
            return "canonical", canonical
        # Compatibility only: rows created before document provenance was
        # added have no canonical map. The latest transcript remains the best
        # available structural source, but the FE now treats any mismatch as
        # optional metadata failure and still renders the text unlinked.
        return "compat", _ideal_piece_provenance_compat(database, arc_id)
    # LEGACY compose cache — and the ONLY lane the deckless guard belongs
    # to. This one keys its picks by SECTION index, which is not a deck page,
    # so without an uploaded deck it must not attach. The living-transcript
    # lanes above read the CUTTER's own bucket (the slide that was on screen when the
    # words were spoken), which is a real page whether or not a PDF was ever
    # uploaded — and applying the guard to every lane is what made the
    # built-in mock deck attach nothing at all (founder 2026-08-11).
    if not deckless_ok:
        return "deckless", []
    return "legacy_cache", _ideal_piece_provenance_legacy_cache(database, arc_id)


def _report_misaligned_pieces(arc_id, lane, prov, paragraphs, degradation):
    """Say so when provenance exists but does not line up with the served
    paragraphs, because every slide link on the read then becomes null
    (audit A3). The log line names the lane; the payload's ``degraded``
    list names the stage, so the FE can tell a shorter read for what it
    is. Nothing to say when there is no provenance at all."""
    if not prov or len(prov) == len(paragraphs):
        return
    logger.warning(
        "ideal-text pieces misaligned arc=%s lane=%s provenance=%d "
        "paragraphs=%d", arc_id, lane, len(prov), len(paragraphs))
    if degradation is not None:
        degradation.note("pieces", "misaligned")


def _part_roots(database, arc_id, user_id, paragraphs, served_text) -> dict:
    """The served parts by paragraph index, when they join 1:1; else {}."""
    if not user_id:
        return {}
    try:
        from services.ideal_text_parts import agrees_with_text, serve
        served_parts = serve(database.get_ideal_text_parts(
            arc_id, str(user_id), with_lock=True)) or []
        if (len(served_parts) == len(paragraphs)
                and agrees_with_text(served_parts, served_text)):
            return {i: part for i, part in enumerate(served_parts)}
    except Exception:
        return {}
    return {}


def _piece_row(index: int, para: str, src: dict, part: dict) -> dict:
    metadata_root = part.get("root_phrase")
    # The API serves only explicit, locked orange roots. A generated
    # first-words fallback is not a user decision and must not become a
    # prompt in the next Take or in Presentation Mode.
    root = ({"text": metadata_root, "type": "flagship"}
            if isinstance(metadata_root, str) and metadata_root
            else {"text": None, "type": None})
    si = src.get("slide_index")
    if isinstance(si, bool) or not isinstance(si, int) or si < 0:
        si = None
    snip = src.get("snippet_id")
    sess = src.get("take_session_id")
    bk = src.get("block_key")
    return {
        "piece_key": index,
        "text": para,
        "root_phrase": root["text"],
        "root_type": root["type"],
        "slide_index": si,
        "block_key": (bk if isinstance(bk, int)
                      and not isinstance(bk, bool) else None),
        "snippet_id": str(snip) if snip else None,
        "take_session_id": str(sess) if sess else None,
        "take_index": src.get("take_index"),
        "status": src.get("status") or "settled",
        "challenger": src.get("challenger"),
    }


def ideal_text_pieces(database, arc_id, served_text, presentation_ref,
                      user_id=None, degradation=None):
    """The slide-linkage `pieces[]` of the SD student GET (FE handoff
    2026-08-03, FE PR #222): one entry per "\\n\\n"-paragraph of the
    SERVED text, each carrying the deck page its words were bucketed to.

    `slide_index` attaches ONLY when the mapping is structural — the
    machine assembly's piece list lines up 1:1 with the served
    paragraphs (the FE's own provability bar: it zips or hides on
    anything weaker). A reshaped text (user rewrite, coach restructure,
    stale cache) misaligns the counts and every slide_index degrades to
    null — the FE falls back to its exact-count zip, never a guessed
    attachment. An arc with no UPLOADED deck still attaches when the cutter
    bucketed its words against slides the speaker actually saw (the built-in
    deck); only the legacy compose lane, which keys picks by SECTION index
    rather than a deck page, stays deckless-gated — applying that guard to
    every lane is what made the mock deck attach nothing (founder
    2026-08-11). Provenance only, no scores (AC-9). Best-effort; []."""
    try:
        paragraphs = [p.strip() for p in (served_text or "").split("\n\n")
                      if p.strip()]
        if not paragraphs:
            return []
        # The deckless guard is passed DOWN rather than applied here, so it
        # lands on the one lane whose slide identity is not a deck page.
        lane, prov = _ideal_piece_provenance(
            database, arc_id, deckless_ok=bool(presentation_ref),
            served_text=served_text)
        _report_misaligned_pieces(arc_id, lane, prov, paragraphs, degradation)
        aligned = bool(prov) and len(prov) == len(paragraphs)
        part_roots = _part_roots(database, arc_id, user_id, paragraphs,
                                 served_text)
        return [_piece_row(i, para, prov[i] if aligned else {},
                           part_roots.get(i) or {})
                for i, para in enumerate(paragraphs)]
    except Exception as e:
        logger.warning("ideal-text pieces failed arc=%s: %s", arc_id, e)
        return []
