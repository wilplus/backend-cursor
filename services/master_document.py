"""Retired master-document experiment compatibility helpers.

Canonical Ideal Text no longer creates incumbent/challenger comparisons or
block upgrade offers. The remaining readers and decision adapters exist only
for historical rows and stay disabled behind ``master_document_enabled()``.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Skeleton keys leave gaps so a candidate block can sit between two
# existing blocks at its mapped position.
_KEY_STEP = 10
# The 4-part framework applies below this many pieces (~ a short talk).
_SHORT_TAKE_PIECES = 16
_FRAMEWORK = ("Hook", "Context", "Core Message", "Closer")


def master_document_enabled() -> bool:
    """The incumbent/challenger document experiment is retired."""
    return False


# ── skeleton creation (take 1) ─────────────────────────────────────────

def _slide_of(snip: Any) -> Optional[int]:
    m = (snip or {}).get("metrics")
    piece = m.get("piece") if isinstance(m, dict) else None
    si = piece.get("slide_index") if isinstance(piece, dict) else None
    if isinstance(si, bool) or not isinstance(si, int):
        return None
    return si


def _quarter_split(n: int) -> list:
    """Deterministic fallback boundaries: four roughly equal piece groups
    labeled with the framework. Pure."""
    if n <= 0:
        return []
    if n < 4:
        return [(i, i, _FRAMEWORK[i]) for i in range(n)]
    q, out, start = n // 4, [], 0
    for i, label in enumerate(_FRAMEWORK):
        end = n - 1 if i == 3 else start + q - 1 + (1 if i < n % 4 else 0)
        out.append((start, end, label))
        start = end + 1
    return out


def _llm_boundaries(piece_texts: list) -> Optional[list]:
    """ONE chunking pass — [(start_idx, end_idx, label)] covering the
    pieces contiguously, or None (caller falls back). The LLM returns
    INDICES AND LABELS ONLY — it never writes or returns transcript text
    (L1). Validated hard; any inconsistency discards the answer."""
    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_MASTER_CHUNKING
        # Prompt text lives in the registry (services/prompts/) — moved
        # verbatim 2026-08-03; hash-locked in prompts.lock.json.
        from services.prompts import master_document as _prompts
        numbered = "\n".join(f"{i}: {t}" for i, t in enumerate(piece_texts))
        short = len(piece_texts) <= _SHORT_TAKE_PIECES
        frame = _prompts.FRAME_SHORT if short else _prompts.FRAME_LONG
        result = chat_complete(
            spec=SPEC_MASTER_CHUNKING,
            system=_prompts.CHUNKING_SYSTEM,
            user=_prompts.chunking_user(frame, numbered),
            surface="master_document_chunking",
        )
        parsed = getattr(result, "parsed", None) or {}
        blocks = parsed.get("blocks")
        if not isinstance(blocks, list) or not blocks:
            return None
        out, expect = [], 0
        for b in blocks:
            s, e = b.get("start"), b.get("end")
            if not isinstance(s, int) or not isinstance(e, int) \
                    or s != expect or e < s:
                return None
            label = (b.get("label") or "").strip()[:40] or None
            out.append((s, e, label))
            expect = e + 1
        if expect != len(piece_texts):
            return None
        return out
    except Exception as e:
        logger.warning("master_document: chunking failed: %s", e)
        return None


def build_skeleton(arc_id: Any, database) -> list:
    """Create + persist the block skeleton from the arc's LATEST spoken
    take that has pieces (flip-ON continuity — review #20/#24). Decked:
    one block per slide (deterministic). Deckless: LLM boundaries,
    quarter-split fallback. Returns the block rows written ([] when there
    is nothing to build). No runtime caller remains; this is retained only
    while historical master-document rows still have compatibility readers.
    Best-effort."""
    try:
        from services.best_presentation import spoken_arc_sessions
        from services.transcript_document import build_transcript_document
        spoken = spoken_arc_sessions(database.get_arc_sessions(arc_id) or [])
        if not spoken:
            return []
        spoken.sort(key=lambda s: (s.get("take_index") or 0,
                                   s.get("created_at") or ""))
        # SEED FROM THE LATEST spoken take (review findings #5/#20/#24):
        # seeding from take 1 regressed a flipped-on live arc to its
        # oldest text and locked an empty first take in forever. The
        # latest take IS what the user currently sees under the living-
        # transcript flag — the master starts exactly there, walking
        # back through earlier takes only if the latest has no pieces.
        seed = None
        seed_doc = None
        for cand in reversed(spoken):
            _sid = str(cand.get("id") or "")
            if not _sid:
                continue
            _doc = build_transcript_document(arc_id, database=database,
                                             session_id=_sid)
            if _doc and _doc.get("pieces"):
                seed, seed_doc = cand, _doc
                break
        if seed is None:
            return []
        sid = str(seed.get("id"))
        take_index = seed.get("take_index") or 1
        pieces = seed_doc["pieces"]

        # Decked → group by the cutter's exact slide_index.
        snips = {str(s.get("id")): s
                 for s in (database.get_snippets_by_session(sid) or [])}
        slide_groups: list = []
        current: list = []
        current_slide = None
        any_slide = False
        for p in pieces:
            si = _slide_of(snips.get(str(p.get("snippet_id"))))
            if si is not None:
                any_slide = True
            if current and si != current_slide:
                slide_groups.append((current_slide, current))
                current = []
            current_slide = si
            current.append(p)
        if current:
            slide_groups.append((current_slide, current))

        if any_slide:
            groups = [((f"Slide {si + 1}" if isinstance(si, int) else None),
                       grp, si) for si, grp in slide_groups]
        else:
            texts = [p.get("text") or "" for p in pieces]
            bounds = _llm_boundaries(texts) or _quarter_split(len(texts))
            groups = [(label, pieces[s:e + 1], None)
                      for (s, e, label) in bounds]

        rows = []
        for i, (label, grp, slide_idx) in enumerate(
                g for g in groups if g[1]):
            fields = {
                "label": label,
                "slide_index": slide_idx,
                "active": True,
                "incumbent_take_session_id": sid,
                "incumbent_take_index": take_index,
                "incumbent_pieces": [
                    {"snippet_id": p["snippet_id"], "text": p["text"]}
                    for p in grp],
                "status": "settled",
                "challenger_take_session_id": None,
                "challenger_take_index": None,
                "challenger_pieces": None,
                "challenger_why": None,
            }
            if database.upsert_ideal_text_block(str(arc_id), i * _KEY_STEP,
                                                fields):
                rows.append({"arc_id": str(arc_id),
                             "block_key": i * _KEY_STEP, **fields,
                             "rejected_take_session_ids": []})
        # DUAL-WRITE (founder 2026-08-03): the seed take's blocks enter
        # the append-only variant pool and revision 1 pins the head —
        # from the first build, "my text" is a pointer list that later
        # takes can never overwrite. Best-effort beside the skeleton.
        if rows:
            try:
                from services.ideal_text_variants import (
                    snapshot_composition,
                )
                snapshot_composition(database, arc_id, reason="seed")
            except Exception as _ve:
                logger.warning("master_document: seed variants failed "
                               "arc=%s: %s", arc_id, _ve)
        return rows
    except Exception as e:
        logger.warning("master_document: skeleton build failed arc=%s: %s",
                       arc_id, e)
        return []


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
    rows = database.list_ideal_text_blocks(str(arc_id))
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


def upgrade_changes(arc_id: Any, served_text: str, database) -> list:
    """The `source: "new_take"` entries for the serve layer — one per
    pending upgrade, span-anchored on the incumbent block's words in the
    served text (monotonic scan). Same renderer shape as tracked_changes.
    Pure given db rows.

    CANDIDATE BLOCKS LEFT THIS FUNCTION (2026-08-07). They used to ride here as
    `kind: "insert"` with a zero-width span, and reached nobody — an addition
    is not a span-anchored edit, and forcing it into that shape produced an
    anchor pointing at no text. They are their own lane now: `block_additions`.
    """
    rows = database.list_ideal_text_blocks(str(arc_id))
    if not rows:
        return []
    out, cursor = [], 0
    doc = served_text if isinstance(served_text, str) else ""
    for row in sorted(rows, key=lambda r: r.get("block_key") or 0):
        if row.get("status") == "pending_upgrade" \
                and row.get("challenger_pieces"):
            inc_text = " ".join(
                (p.get("text") or "").strip()
                for p in (row.get("incumbent_pieces") or [])).strip()
            ch_text = " ".join(
                (p.get("text") or "").strip()
                for p in (row.get("challenger_pieces") or [])).strip()
            if not inc_text or not ch_text:
                continue
            # Case-tolerant, monotonic: the document is finalize-cased
            # (sentence capitals), the stored block text is not (the
            # #230 raw-vs-document class). The regex search yields REAL
            # spans on the document itself (a lower() index could shift
            # on length-changing case mappings — review finding #14),
            # and the monotonic cursor advances PER BLOCK so an earlier
            # block sharing wording can never steal a later block's
            # anchor (review finding #10). The QUOTE is the document's
            # own slice.
            import re as _re
            m = _re.compile(_re.escape(inc_text), _re.IGNORECASE).search(
                doc, cursor)
            if not m:
                continue        # baked/edited away — never mis-point
            i = m.start()
            inc_text = doc[i:m.end()]
            cursor = m.end()
            why = row.get("challenger_why")
            out.append({
                "id": f"block:{row.get('block_key')}",
                "block_key": row.get("block_key"),
                "snippet_id": None,
                "take_session_id": row.get("challenger_take_session_id"),
                "kind": "replace",
                "source": "new_take",
                "span": {"start": i, "end": i + len(inc_text)},
                "quote": inc_text,
                "proposed_text": ch_text,
                "take_index": row.get("challenger_take_index"),
                "why": None,
                "why_key": (why if why in ("energy", "steadiness",
                                           "coverage", "overall")
                            else "overall"),
            })
    return out


def block_additions(arc_id: Any, served_text: str, database) -> list:
    """Material the speaker SAID that is not in the master document at all.

    One entry per candidate block: a decked slide the skeleton has never seen,
    carrying the words spoken over it. Accept promotes the block into the
    master (`decide_block`); keep deletes the row, and the same material may
    honestly be offered again if said again.

    ── WHY THIS IS NOT A TRACKED CHANGE, which is the bug it fixes ────────────

    It used to ride in `upgrade_changes` as `kind: "insert"` with a ZERO-WIDTH
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
    rows = database.list_ideal_text_blocks(str(arc_id))
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
    row = database.get_ideal_text_block(str(arc_id), int(block_key))
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
        ok = database.upsert_ideal_text_block(str(arc_id), int(block_key),
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
            ok = database.upsert_ideal_text_block(
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
        ok = database.delete_ideal_text_block(str(arc_id), int(block_key))
        return (bool(ok), None if ok else "WRITE_FAILED")
    return (False, "NOT_PENDING")
