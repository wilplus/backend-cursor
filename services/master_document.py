"""The MASTER DOCUMENT (founder 2026-07-22) — one persistent ideal text
per project, evolving block by block.

THE FLIP (supersedes decision #4 of 2026-07-20, chosen after the founder
live-tested the latest-take model): a new take NEVER becomes the
document. The master text persists; from take 2 onward a take only
contributes BLOCK-level upgrade offers where it beats the master —
"the same old text evolves as it is being recorded from different
takes", each fragment wearing the badge of the take it came from.

The four founder decisions this module implements:
  1. MASTER PERSISTS — the document = the skeleton's active blocks'
     incumbent pieces, joined; stable across takes.
  2. APPROVE-GATED UPGRADES — a winning new-take block waits as
     status='pending_upgrade' until the student accepts (block flips,
     badge updates) or keeps (remembered, never re-offered). A losing
     or skipped block is SILENCE.
  3. SAVE = ACCEPT-AND-FREEZE — a save stamps a version row; the FE
     hides badges and gates the re-read on it (endpoint in routes).
  4. SKELETON LOCKS ON TAKE 1 — decked: block per slide (deterministic);
     deckless: ONE LLM pass returns BOUNDARIES ONLY (piece indices;
     short talk → Hook/Context/Core Message/Closer, longer → topic
     shifts). Deterministic quarter-split fallback. The LLM NEVER
     returns text — block text is always the verbatim pieces (L1).

JUDGING is the shipped blended ranking (power_score, L2 untouched); both
sides need real measurements or no comparison happens. The why is the
four-key vocabulary (energy|steadiness|coverage|overall) — AC-9-safe.

Flag: MASTER_DOCUMENT_ENABLED (default OFF) on top of
LIVING_TRANSCRIPT_ENABLED — OFF keeps the current latest-take document
byte-for-byte.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Skeleton keys leave gaps so a candidate block can sit between two
# existing blocks at its mapped position.
_KEY_STEP = 10
# The 4-part framework applies below this many pieces (~ a short talk).
_SHORT_TAKE_PIECES = 16
_FRAMEWORK = ("Hook", "Context", "Core Message", "Closer")
# A new-take block must beat the incumbent by more than noise.
_MIN_MARGIN = 0.04


def master_document_enabled() -> bool:
    return (os.getenv("MASTER_DOCUMENT_ENABLED") or "0").strip().lower() \
        in ("1", "true", "yes")


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
        numbered = "\n".join(f"{i}: {t}" for i, t in enumerate(piece_texts))
        short = len(piece_texts) <= _SHORT_TAKE_PIECES
        frame = (
            "Use exactly these four blocks in order: Hook, Context, "
            "Core Message, Closer." if short else
            "Chunk by natural topic shifts; label each block with a "
            "2-4 word neutral topic label.")
        result = chat_complete(
            spec=SPEC_MASTER_CHUNKING,
            system=(
                "You segment a spoken-talk transcript into logical blocks. "
                "You NEVER rewrite, summarise or quote the text — you only "
                "return piece INDEX boundaries and a short label per "
                "block. Blocks must be contiguous, cover every piece "
                "exactly once, and stay in order. Output strict JSON: "
                '{"blocks": [{"start": int, "end": int, "label": str}]}'),
            user=f"{frame}\n\nPieces:\n{numbered}",
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
    """Create + persist the block skeleton from the arc's FIRST spoken
    take. Decked: one block per slide (deterministic). Deckless: LLM
    boundaries, quarter-split fallback. Returns the block rows written
    ([] when there is nothing to build). Called from the analysis worker
    ONLY (process_new_take) — never from a serving path (the LLM pass
    must not ride a student GET). Best-effort."""
    try:
        from services.best_presentation import spoken_arc_sessions
        from services.transcript_document import build_transcript_document
        spoken = spoken_arc_sessions(database.get_arc_sessions(arc_id) or [])
        if not spoken:
            return []
        spoken.sort(key=lambda s: (s.get("take_index") or 0,
                                   s.get("created_at") or ""))
        first = spoken[0]
        sid = str(first.get("id") or "")
        take_index = first.get("take_index") or 1
        doc = build_transcript_document(arc_id, database=database,
                                        session_id=sid)
        if not doc or not doc.get("pieces"):
            return []
        pieces = doc["pieces"]

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
            groups = [(f"Slide {si + 1}" if isinstance(si, int) else None,
                       grp) for si, grp in slide_groups]
        else:
            texts = [p.get("text") or "" for p in pieces]
            bounds = _llm_boundaries(texts) or _quarter_split(len(texts))
            groups = [(label, pieces[s:e + 1]) for (s, e, label) in bounds]

        rows = []
        for i, (label, grp) in enumerate(g for g in groups if g[1]):
            fields = {
                "label": label,
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
    # is built exclusively in the analysis worker (process_new_take);
    # until it exists the caller falls back to the living-transcript
    # document — the user never sees an empty text.
    rows = database.list_ideal_text_blocks(str(arc_id))
    if not rows:
        return empty

    parts, pieces, cursor = [], [], 0
    for row in sorted((r for r in rows if r.get("active", True)
                       and r.get("status") != "candidate"),
                      key=lambda r: r.get("block_key") or 0):
        for p in (row.get("incumbent_pieces") or []):
            text = (p.get("text") or "").strip()
            if not text:
                continue
            if parts:
                cursor += 1          # the joining space
            start = cursor
            cursor += len(text)
            parts.append(text)
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
    if not pieces:
        return empty
    doc = finalize_document(" ".join(parts))
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
                pieces = relocate_pieces(doc, pieces)
    except Exception as _le:
        logger.warning("master_document: bake failed arc=%s: %s",
                       arc_id, _le)

    return {
        "text": doc,
        "key_moments": [],
        "polish": [],
        "ready": True,
        "document": {
            "pieces": pieces,
            "take_session_id": None,   # the master spans takes by design
            "take_index": None,
        },
    }


# ── take N+1 processing ────────────────────────────────────────────────

def _map_pieces_to_blocks(new_pieces: list, blocks: list) -> dict:
    """{block_key: [new pieces]} — decked by slide when both sides carry
    labels, else deterministic similarity under a monotonic constraint
    (an LLM ID-mapping can replace this later; identical contract)."""
    import difflib

    def _block_text(row):
        return " ".join((p.get("text") or "")
                        for p in (row.get("incumbent_pieces") or [])).lower()

    ordered = sorted((r for r in blocks if r.get("status") != "candidate"),
                     key=lambda r: r.get("block_key") or 0)
    if not ordered or not new_pieces:
        return {}
    texts = [_block_text(r) for r in ordered]
    out: dict = {}
    lo = 0
    for p in new_pieces:
        needle = (p.get("text") or "").lower()
        if not needle:
            continue
        best_j, best = -1, 0.0
        for j in range(lo, min(len(ordered), lo + 4)):
            score = difflib.SequenceMatcher(
                None, needle, texts[j], autojunk=False).ratio()
            # containment beats global ratio for a piece vs a whole block
            if needle and needle in texts[j]:
                score = max(score, 0.9)
            if score > best:
                best_j, best = j, score
        if best_j >= 0 and best >= 0.3:
            key = ordered[best_j].get("block_key")
            out.setdefault(key, []).append(p)
            lo = best_j
    return out


def _block_score(piece_ids: list, database) -> Optional[float]:
    """Mean blended score over MEASURED pieces; None when nothing is
    measured (no comparison without real data — review rule)."""
    try:
        from services.power_phrase_ranking import power_score
        scores = []
        for sid in piece_ids:
            snip = database.get_snippet_by_id(str(sid)) or {}
            m = snip.get("metrics") if isinstance(snip.get("metrics"),
                                                  dict) else {}
            act = m.get("overall_score")
            if act is None or isinstance(act, bool):
                continue
            stick = m.get("slide_stickiness")
            if isinstance(stick, dict):
                stick = stick.get("composite")
            scores.append(power_score(activation=act,
                                      slide_stickiness=stick,
                                      tag=None, direction=None,
                                      breakthrough=False))
        return (sum(scores) / len(scores)) if scores else None
    except Exception:
        return None


def _block_why(inc_ids: list, ch_ids: list, database) -> str:
    """The four-key reason, from mean normalized features per side."""
    try:
        from services.delivery_stars import normalize_features
        from services.prior_take_changes import why_key

        def _mean(ids):
            feats: dict = {}
            counts: dict = {}
            stick_vals = []
            for sid in ids:
                snip = database.get_snippet_by_id(str(sid)) or {}
                m = snip.get("metrics") if isinstance(
                    snip.get("metrics"), dict) else {}
                st = m.get("slide_stickiness")
                if isinstance(st, dict):
                    st = st.get("composite")
                if isinstance(st, (int, float)) and not isinstance(st, bool):
                    stick_vals.append(float(st))
                for k, v in normalize_features(m).items():
                    feats[k] = feats.get(k, 0.0) + v
                    counts[k] = counts.get(k, 0) + 1
            mm = {k: feats[k] / counts[k] for k in feats}
            return {"metrics": mm,
                    "slide_stickiness": (sum(stick_vals) / len(stick_vals)
                                         if stick_vals else None)}
        return why_key(_mean(inc_ids), _mean(ch_ids))
    except Exception:
        return "overall"


def process_new_take(arc_id: Any, session_id: Any, database) -> int:
    """Called after a SPOKEN take's analysis (flag ON). Take 1 builds the
    skeleton; later takes are judged per block:

      * new block OUTRANKS the incumbent (margin rule, both sides
        measured) → status='pending_upgrade' with the challenger —
        APPROVE-GATED, the master text does not move;
      * incumbent wins / block skipped → nothing;
      * unmatched new material → a 'candidate' row (approve-gated
        addition, active=false);
      * a take the student already rejected for a block never re-offers.

    Returns the number of offers written. Best-effort, never raises."""
    try:
        from services.transcript_document import build_transcript_document
        rows = database.list_ideal_text_blocks(str(arc_id))
        if rows is None:
            return 0            # read failed — never rebuild over unknown
        if not rows:
            build_skeleton(arc_id, database)
            return 0
        sid = str(session_id)
        if any(str(r.get("incumbent_take_session_id")) == sid
               for r in rows):
            return 0            # this take already IS the skeleton
        doc = build_transcript_document(arc_id, database=database,
                                        session_id=sid)
        if not doc or not doc.get("pieces"):
            return 0
        take_index = doc.get("take_index")
        mapped = _map_pieces_to_blocks(doc["pieces"], rows)

        offers = 0
        matched_ids = set()
        for row in rows:
            key = row.get("block_key")
            new_pieces = mapped.get(key) or []
            if not new_pieces:
                continue        # skipped block → master retained, silence
            matched_ids.update(str(p.get("snippet_id"))
                               for p in new_pieces)
            rejected = {str(x) for x
                        in (row.get("rejected_take_session_ids") or [])}
            if sid in rejected:
                continue
            inc_ids = [p.get("snippet_id")
                       for p in (row.get("incumbent_pieces") or [])]
            new_ids = [p.get("snippet_id") for p in new_pieces]
            s_inc = _block_score(inc_ids, database)
            s_new = _block_score(new_ids, database)
            if s_inc is None or s_new is None:
                continue        # unmeasured → no comparison (review rule)
            if s_new - s_inc <= _MIN_MARGIN:
                continue        # the master held its ground → silence
            fields = {
                "status": "pending_upgrade",
                "challenger_take_session_id": sid,
                "challenger_take_index": take_index,
                "challenger_pieces": [
                    {"snippet_id": p["snippet_id"], "text": p["text"]}
                    for p in new_pieces],
                "challenger_why": _block_why(inc_ids, new_ids, database),
            }
            if database.upsert_ideal_text_block(str(arc_id), int(key),
                                                fields):
                offers += 1

        # Genuinely new material → ONE candidate block (approve-gated).
        leftovers = [p for p in doc["pieces"]
                     if str(p.get("snippet_id")) not in matched_ids]
        if leftovers:
            max_key = max((r.get("block_key") or 0) for r in rows)
            fields = {
                "label": None,
                "active": False,
                "status": "candidate",
                "incumbent_take_session_id": sid,
                "incumbent_take_index": take_index,
                "incumbent_pieces": [
                    {"snippet_id": p["snippet_id"], "text": p["text"]}
                    for p in leftovers],
                "challenger_take_session_id": None,
                "challenger_take_index": None,
                "challenger_pieces": None,
                "challenger_why": None,
            }
            if database.upsert_ideal_text_block(
                    str(arc_id), int(max_key) + _KEY_STEP, fields):
                offers += 1
        return offers
    except Exception as e:
        logger.warning("master_document: take processing failed arc=%s: %s",
                       arc_id, e)
        return 0


def upgrade_changes(arc_id: Any, served_text: str, database) -> list:
    """The `source: "new_take"` entries for the serve layer — one per
    pending upgrade, span-anchored on the incumbent block's words in the
    served text (monotonic scan); one `insert` entry per candidate block
    (zero-width span at the document end). Same renderer shape as
    tracked_changes. Pure given db rows."""
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
            # (sentence capitals), the stored block text is not — the
            # exact-find-only version of this missed every block that
            # opens a sentence (the #230 raw-vs-document class). The
            # QUOTE is always the document's own slice, so the span
            # slices back exactly.
            i = doc.find(inc_text, cursor)
            if i < 0:
                i = doc.lower().find(inc_text.lower(), cursor)
            if i < 0:
                continue        # baked/edited away — never mis-point
            inc_text = doc[i:i + len(inc_text)]
            cursor = i + len(inc_text)
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
        elif row.get("status") == "candidate":
            add_text = " ".join(
                (p.get("text") or "").strip()
                for p in (row.get("incumbent_pieces") or [])).strip()
            if not add_text:
                continue
            out.append({
                "id": f"block:{row.get('block_key')}",
                "block_key": row.get("block_key"),
                "snippet_id": None,
                "take_session_id": row.get("incumbent_take_session_id"),
                "kind": "insert",
                "source": "new_take",
                "span": {"start": len(doc), "end": len(doc)},
                "quote": "",
                "proposed_text": add_text,
                "take_index": row.get("incumbent_take_index"),
                "why": None,
                "why_key": "overall",
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
        return (bool(ok), None if ok else "WRITE_FAILED")
    if status == "candidate":
        offered = str(row.get("incumbent_take_session_id") or "")
        if str(challenger_session_echo or "") != offered:
            return (False, "STALE_OFFER")
        if action == "accept":
            fields = {"status": "settled", "active": True}
        else:
            fields = {"status": "settled", "active": False}
        ok = database.upsert_ideal_text_block(str(arc_id), int(block_key),
                                              fields)
        return (bool(ok), None if ok else "WRITE_FAILED")
    return (False, "NOT_PENDING")
