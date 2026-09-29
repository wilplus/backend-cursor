"""Retired master-document experiment compatibility helpers.

Canonical Ideal Text no longer creates incumbent/challenger comparisons or
block upgrade offers. The remaining readers and decision adapters exist only
for historical rows and stay disabled behind ``master_document_enabled()``.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def master_document_enabled() -> bool:
    """The incumbent/challenger document experiment is retired."""
    return False


# ── the master document ────────────────────────────────────────────────

def assemble_master_document(arc_id: str, *, database=None) -> dict:
    """The persistent master text: active blocks in key order, incumbent
    pieces joined, document-finalized. Same return shape as the
    transcript assembly so persist/version/snapshot/serve lanes work
    unchanged; document.pieces carry per-piece spans + the block's
    take_index (the badge) so the tracked-change lane anchors exactly as
    before."""
    if database is None:
        from services.db import db as database
    from services.transcript_smoothing import finalize_document

    empty = {"text": "", "key_moments": [], "polish": [], "ready": False}
    # READ-ONLY: the serving path never builds the skeleton (that would
    # put the take-1 LLM chunking pass on the student GET). The skeleton
    # is no longer built by the runtime. Historical rows can still be read;
    # without them the caller falls back to the canonical Ideal Text path.
    rows = database.ideal_text.list_ideal_text_blocks(str(arc_id))
    if not rows:
        return empty

    # THE MASTER AUTHORS PARAGRAPHS TOO (SPEC §11.1, founder 2026-08-14).
    # This join used to be `" ".join(parts)` — the whole master document
    # was ONE flowing paragraph, so the read surface (chunk = "\n\n"
    # paragraph) served the entire talk as a single wall: the 2026-08-11
    # slide-aware join landed in the transcript builder only, and the
    # master path silently regressed past it. Now: a BLOCK boundary is a
    # hard paragraph break (blocks are the master's slides), and WITHIN a
    # block pieces pack greedily up to PARAGRAPH_CAP_CHARS — the same one
    # packer, one cap, one `_close` seam rule the transcript builder uses.
    from services.slide_word_split import PARAGRAPH_CAP_CHARS
    from services.transcript_document import _close, pack_items
    pieces, para_meta = [], []
    out_frag: list = []
    cursor = 0
    para_i = 0
    for row in sorted((r for r in rows if r.get("active", True)
                       and r.get("status") != "candidate"),
                      key=lambda r: r.get("block_key") or 0):
        items = []
        for p in (row.get("incumbent_pieces") or []):
            text = (p.get("text") or "").strip()
            if text:
                items.append((p, text))
        for pack in pack_items(items, PARAGRAPH_CAP_CHARS):
            if para_i:
                out_frag.append("\n\n")
                cursor += 2
            para_i += 1
            para_start = cursor
            for i, (p, text) in enumerate(pack):
                if i:
                    out_frag.append(" ")
                    cursor += 1
                mark = ""
                if i == len(pack) - 1:
                    text, mark = _close(text)
                start = cursor
                cursor += len(text)
                out_frag.append(text)
                pieces.append({
                    "snippet_id": str(p.get("snippet_id")),
                    "take_session_id": row.get("incumbent_take_session_id"),
                    "take_index": row.get("incumbent_take_index"),
                    "block_key": row.get("block_key"),
                    "block_label": row.get("label"),
                    "start": start,
                    "end": cursor,
                    "text": text,
                })
                # OUTSIDE the piece's span — see transcript_document._close.
                if mark:
                    out_frag.append(mark)
                    cursor += len(mark)
            # One provenance row per emitted paragraph — the count the
            # serve-side zip aligns against. Sibling paragraphs of one
            # block repeat their block's slide_index.
            para_meta.append({
                "slide_index": row.get("slide_index"),
                "block_key": row.get("block_key"),
                "snippet_id": str(pack[0][0].get("snippet_id")),
                "take_session_id": row.get("incumbent_take_session_id"),
                "take_index": row.get("incumbent_take_index"),
                "start": para_start,
                "end": cursor,
            })
    if not pieces:
        return empty
    doc = finalize_document("".join(out_frag))
    for p in pieces:
        p["text"] = doc[p["start"]:p["end"]]

    # The student's APPROVED star/tracked changes bake into the master
    # exactly as they did into the transcript document — without this,
    # every approval would silently stop applying under the master flag.
    try:
        from services.ideal_decision_ledger import bake_piece, load_ledger
        from services.transcript_document import relocate_pieces
        _approved = [r for r in load_ledger(database, arc_id)
                     if r.get("decision") == "approved"]
        if _approved:
            baked = bake_piece(doc, _approved)
            if baked != doc:
                doc = baked
                # Same reason as the transcript document: a bake changes
                # the words it lands on, and the paragraph is still the
                # honest region for the piece that was there.
                pieces = relocate_pieces(doc, pieces,
                                         paragraph_fallback=True)
    except Exception as _le:
        logger.warning("master_document: bake failed arc=%s: %s",
                       arc_id, _le)

    # Paragraph provenance for the FINAL text. A bake rewrites words inside
    # paragraphs, never the separators between them, so the counts must
    # agree; re-deriving the spans from the finished document keeps every
    # offset exact for the exact text being returned. If a bake ever DOES
    # change the paragraph count (a replacement smuggling a "\n\n"), the
    # meta no longer describes the text — serve nothing rather than
    # attaching slides to the wrong paragraphs (drop, never guess).
    paragraphs: list = []
    try:
        from services.transcript_document import paragraph_spans
        _spans = paragraph_spans(doc)
        if len(_spans) == len(para_meta):
            paragraphs = [dict(m, start=lo, end=hi)
                          for m, (lo, hi) in zip(para_meta, _spans)]
        else:
            logger.warning(
                "master_document: paragraph count changed under bake "
                "arc=%s (%d -> %d) — paragraph provenance dropped",
                arc_id, len(para_meta), len(_spans))
    except Exception as _pe:
        logger.warning("master_document: paragraph provenance failed "
                       "arc=%s: %s", arc_id, _pe)

    return {
        "text": doc,
        "key_moments": [],
        "polish": [],
        "ready": True,
        "document": {
            "pieces": pieces,
            "paragraphs": paragraphs,
            "take_session_id": None,   # the master spans takes by design
            "take_index": None,
        },
    }


def block_additions(arc_id: Any, served_text: str, database) -> list:
    """Material the speaker SAID that is not in the master document at all.

    One entry per candidate block: a decked slide the skeleton has never seen,
    carrying the words spoken over it. Accept promotes the block into the
    master (`decide_block`); keep deletes the row, and the same material may
    honestly be offered again if said again.

    ── WHY THIS IS NOT A TRACKED CHANGE, which is the bug it fixes ────────────

    It used to ride in `upgrade_changes` (since deleted, 2026-09-29: no
    production caller) as `kind: "insert"` with a ZERO-WIDTH
    span at the document end, and it reached nobody. It was dropped three
    separate times: the FE's `kind` vocabulary is replace/bold/advice, its span
    check requires `end > start`, and the manager gate refuses zero-width spans
    because an invisible candidate would win a budget slot and render nothing.

    Every one of those rejections is CORRECT. The mistake was upstream: an
    addition is not a span-anchored edit to existing words, and forcing it into
    a shape that is one produced an anchor pointing at no text. So it gets its
    own lane, with no span at all.

    ── AND IT IS NOT BUDGETED ─────────────────────────────────────────────────

    Appendix H's ≤3 is a cognitive-load limit on FEEDBACK — notes about how you
    spoke, which the manager engine arbitrates. This is not feedback. It is
    material recovery: words the speaker actually said, on a slide in their own
    deck, currently missing from their script. Putting it through the budget
    would mean three polish notes could silently swallow it, which is the same
    disappearance in a new costume.

    Founder call if that is wrong — it is stated here rather than buried
    because it is exactly the kind of quiet scope decision the filter exists to
    catch.

    Pure given db rows; [] on anything missing.
    """
    rows = database.ideal_text.list_ideal_text_blocks(str(arc_id))
    if not rows:
        return []
    doc = served_text if isinstance(served_text, str) else ""
    out: list = []
    for row in sorted(rows, key=lambda r: r.get("block_key") or 0):
        if row.get("status") != "candidate":
            continue
        add_text = " ".join(
            (p.get("text") or "").strip()
            for p in (row.get("incumbent_pieces") or [])).strip()
        if not add_text:
            continue
        if add_text.lower() in doc.lower():
            continue    # already verbatim in the master — no offer
        out.append({
            "id": f"block:{row.get('block_key')}",
            "block_key": row.get("block_key"),
            # The decision echoes this back (STALE_OFFER otherwise), so an
            # offer decided against a take that has since been superseded
            # cannot be applied to a different one.
            "take_session_id": row.get("incumbent_take_session_id"),
            "take_index": row.get("incumbent_take_index"),
            "slide_index": row.get("slide_index"),
            "label": row.get("label"),
            "text": add_text,
        })
    return out


def decide_block(arc_id: Any, block_key: Any, action: str,
                 challenger_session_echo: Any, database) -> tuple:
    """The block decision. accept → the challenger becomes the incumbent
    (candidate → active); keep → remembered in the rejected list, offer
    cleared. Returns (ok, error_code): error codes NOT_PENDING /
    STALE_OFFER / NOT_FOUND for the route to map."""
    row = database.ideal_text.get_ideal_text_block(str(arc_id), int(block_key))
    if not row:
        return (False, "NOT_FOUND")
    status = row.get("status")
    if status == "pending_upgrade":
        offered = str(row.get("challenger_take_session_id") or "")
        if not offered:
            return (False, "NOT_PENDING")
        if str(challenger_session_echo or "") != offered:
            return (False, "STALE_OFFER")
        if action == "accept":
            fields = {
                "status": "settled",
                "incumbent_take_session_id": offered,
                "incumbent_take_index": row.get("challenger_take_index"),
                "incumbent_pieces": row.get("challenger_pieces") or [],
                "challenger_take_session_id": None,
                "challenger_take_index": None,
                "challenger_pieces": None,
                "challenger_why": None,
            }
        else:
            rej = [str(x) for x
                   in (row.get("rejected_take_session_ids") or []) if x]
            rej.append(offered)
            fields = {
                "status": "settled",
                "rejected_take_session_ids": sorted(set(rej)),
                "challenger_take_session_id": None,
                "challenger_take_index": None,
                "challenger_pieces": None,
                "challenger_why": None,
            }
        ok = database.ideal_text.upsert_ideal_text_block(str(arc_id), int(block_key),
                                              fields)
        if ok and action == "accept":
            # DUAL-WRITE (2026-08-03): an accepted upgrade is a new
            # composition revision — the displaced incumbent stays in
            # the pool, restorable. Best-effort.
            try:
                from services.ideal_text_variants import (
                    snapshot_composition,
                )
                snapshot_composition(database, arc_id, reason="accept")
            except Exception:
                pass
        return (bool(ok), None if ok else "WRITE_FAILED")
    if status == "candidate":
        offered = str(row.get("incumbent_take_session_id") or "")
        if str(challenger_session_echo or "") != offered:
            return (False, "STALE_OFFER")
        if action == "accept":
            ok = database.ideal_text.upsert_ideal_text_block(
                str(arc_id), int(block_key),
                {"status": "settled", "active": True})
            if ok:
                try:
                    from services.ideal_text_variants import (
                        snapshot_composition,
                    )
                    snapshot_composition(database, arc_id,
                                         reason="accept")
                except Exception:
                    pass
            return (bool(ok), None if ok else "WRITE_FAILED")
        # keep → the row is DELETED, not parked: a settled-inactive
        # candidate became an invisible ghost that swallowed later takes'
        # material forever (review finding #2). The same material said
        # again in a future take may honestly be offered again.
        ok = database.ideal_text.delete_ideal_text_block(str(arc_id), int(block_key))
        return (bool(ok), None if ok else "WRITE_FAILED")
    return (False, "NOT_PENDING")
