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
  4. SKELETON LOCKS ON FIRST BUILD — seeded from the LATEST spoken take
     (the text the user currently sees), decked: block per slide;
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
    is nothing to build). Called from the analysis worker ONLY
    (process_new_take) — never from a serving path (the LLM pass must
    not ride a student GET). Best-effort."""
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
                # Same reason as the transcript document: a bake changes
                # the words it lands on, and the paragraph is still the
                # honest region for the piece that was there.
                pieces = relocate_pieces(doc, pieces,
                                         paragraph_fallback=True)
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

def _proportional_split(pieces: list, n: int) -> list:
    """The new take split into n contiguous ordered segments by piece
    count — the deckless take-to-skeleton segmentation. Blocks are whole-
    take macro-structure in speech order, so ordinal alignment is the
    honest deterministic mapping (piece-vs-block similarity was
    mathematically incapable of matching multi-piece blocks — ratio
    bounded by 2L/(L+B); review findings #1/#3/#26). Pure."""
    if n <= 0 or not pieces:
        return []
    total = len(pieces)
    if total <= n:
        return [[p] for p in pieces] + [[] for _ in range(n - total)]
    base, rem = divmod(total, n)
    out, start = [], 0
    for k in range(n):
        size = base + (1 if k < rem else 0)
        out.append(pieces[start:start + size])
        start += size
    return out


def segment_take_for_blocks(new_pieces: list, blocks: list,
                            snips_by_id: dict) -> tuple:
    """(mapping, extras): mapping = {block_key: [new pieces]} — the WHOLE
    contiguous segment of the new take that corresponds to each mappable
    block; extras = [(slide_index, [pieces])] for decked slides absent
    from the skeleton (candidate material).

    Decked (both sides carry slide identity): EXACT slide_index match —
    no similarity anywhere (review finding #1: character similarity
    mis-mapped a slide-8 retake onto slide 1). Deckless: FORCED
    ALIGNMENT against the known script when TAKE_ALIGNMENT_ENABLED
    (founder 2026-08-03 — anchor+NW word alignment, deterministic, the
    off-script fallback below), else the proportional ordinal split.

    Only ACTIVE, non-candidate blocks are mapping targets (a kept
    candidate is deleted outright — review finding #2's ghost). Pure
    given rows (the alignment flag is the one env read)."""
    targets = sorted(
        (r for r in (blocks or [])
         if r.get("active", True) and r.get("status") != "candidate"),
        key=lambda r: r.get("block_key") or 0)
    if not targets or not new_pieces:
        return {}, []

    by_slide = {}
    for r in targets:
        si = r.get("slide_index")
        if isinstance(si, int) and not isinstance(si, bool):
            by_slide[si] = r.get("block_key")

    new_by_slide: dict = {}
    any_slide = False
    for p in new_pieces:
        si = _slide_of(snips_by_id.get(str(p.get("snippet_id"))))
        if si is not None:
            any_slide = True
        new_by_slide.setdefault(si, []).append(p)

    if any_slide and by_slide:
        mapping: dict = {}
        extras: list = []
        for si, grp in new_by_slide.items():
            if si is not None and si in by_slide:
                mapping[by_slide[si]] = grp
            elif si is not None:
                extras.append((si, grp))
            # si None on a decked take: cutter gap — not mappable, skip.
        return mapping, extras

    # FORCED ALIGNMENT (founder 2026-08-03): the speaker is re-reading a
    # text we hold — map pieces to blocks by CONTENT, not count. An
    # off-script take (low coverage) falls back to the proportional
    # split rather than fabricating a mapping. Best-effort.
    try:
        from services.take_alignment import (
            alignment_enabled, map_take_to_blocks,
        )
        if alignment_enabled():
            aligned, _ai = map_take_to_blocks(list(new_pieces), targets)
            if aligned is not None:
                logger.info(
                    "take_alignment: %d pieces onto %d blocks "
                    "(coverage=%.2f)", len(new_pieces), len(aligned),
                    _ai.get("coverage") or 0)
                return aligned, []
            logger.info("take_alignment: off-script, proportional "
                        "fallback (coverage=%.2f)",
                        _ai.get("coverage") or 0)
    except Exception as _ae:
        logger.warning("take_alignment failed, proportional fallback: %s",
                       _ae)

    segments = _proportional_split(list(new_pieces), len(targets))
    return ({t.get("block_key"): seg
             for t, seg in zip(targets, segments) if seg}, [])


def _block_score(piece_ids: list, resolver: dict) -> Optional[float]:
    """Mean blended score over MEASURED pieces (rows from the bulk
    resolver); None when nothing is measured (no comparison without real
    data — review rule). Pure."""
    try:
        from services.power_phrase_ranking import power_score
        scores = []
        for sid in piece_ids:
            snip = resolver.get(str(sid)) or {}
            m = snip.get("metrics") if isinstance(snip.get("metrics"),
                                                  dict) else {}
            act = m.get("overall_score")
            if act is None or isinstance(act, bool):
                continue
            stick = m.get("slide_stickiness")
            if isinstance(stick, dict):
                stick = stick.get("composite")
            try:
                from services.voice_confidence import rank_term
                _conf = rank_term(m)
            except Exception:
                _conf = None
            scores.append(power_score(activation=act,
                                      slide_stickiness=stick,
                                      tag=None,
                                      machine_confidence=_conf))
        return (sum(scores) / len(scores)) if scores else None
    except Exception:
        return None


def _block_why(inc_ids: list, ch_ids: list, resolver: dict) -> str:
    """The four-key reason, from mean normalized features per side."""
    try:
        from services.delivery_stars import normalize_features
        from services.prior_take_changes import why_key

        def _mean(ids):
            feats: dict = {}
            counts: dict = {}
            stick_vals = []
            for sid in ids:
                snip = resolver.get(str(sid)) or {}
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
    """Called after a SPOKEN take's analysis (flag ON). The first build
    seeds the skeleton (from the latest take with pieces); later takes
    are judged BLOCK against SEGMENT:

      * the take is segmented onto the skeleton (slide-exact when decked,
        proportional ordinal split when deckless) — the challenger is
        always the WHOLE segment, so an accept can never silently drop
        unmapped sentences (review finding #4/#27);
      * segment OUTRANKS the incumbent (margin rule, both sides measured)
        → status='pending_upgrade' — APPROVE-GATED, the master does not
        move; a newer winning offer replaces an older pending one;
      * incumbent wins / no segment → silence;
      * a block whose incumbent came from THIS take is never judged
        against itself (per block — after accepts a take can own some
        blocks and still challenge others);
      * decked slides absent from the skeleton → candidate blocks
        (approve-gated additions), keyed after the last block, one per
        slide, deduped per take;
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
        doc = build_transcript_document(arc_id, database=database,
                                        session_id=sid)
        if not doc or not doc.get("pieces"):
            return 0
        take_index = doc.get("take_index")
        snips_by_id = {str(x.get("id")): x
                       for x in (database.get_snippets_by_session(sid)
                                 or [])}
        mapping, extras = segment_take_for_blocks(
            doc["pieces"], rows, snips_by_id)

        # DUAL-WRITE (founder 2026-08-03, fear #1): EVERY mapped segment
        # of this take enters the append-only pool BEFORE the duel —
        # losing blocks and displaced offers included. The single
        # challenger slot below keeps its legacy behavior; the pool is
        # what the picker reads. Best-effort, never blocks the judging.
        try:
            from services.ideal_text_variants import capture_take_variants
            capture_take_variants(database, arc_id, sid, take_index,
                                  mapping)
        except Exception as _ve:
            logger.warning("master_document: variant capture failed "
                           "arc=%s: %s", arc_id, _ve)

        # ONE bulk metrics read for every judged snippet (review finding
        # #21: per-snippet round trips inside the recording POST).
        wanted: set = set()
        for row in rows:
            for p in (row.get("incumbent_pieces") or []):
                wanted.add(str(p.get("snippet_id")))
        for seg in mapping.values():
            for p in seg:
                wanted.add(str(p.get("snippet_id")))
        resolver = dict(snips_by_id)
        missing = [x for x in wanted if x not in resolver]
        if missing:
            try:
                for r in (database.get_snippets_by_ids(missing) or []):
                    resolver[str(r.get("id"))] = r
            except Exception:
                pass

        offers = 0
        for row in rows:
            key = row.get("block_key")
            seg = mapping.get(key) or []
            if not seg:
                continue        # no segment → master retained, silence
            if str(row.get("incumbent_take_session_id")) == sid:
                continue        # this take owns the block — no self-duel
            rejected = {str(x) for x
                        in (row.get("rejected_take_session_ids") or [])}
            if sid in rejected:
                continue
            inc_ids = [p.get("snippet_id")
                       for p in (row.get("incumbent_pieces") or [])]
            seg_ids = [p.get("snippet_id") for p in seg]
            s_inc = _block_score(inc_ids, resolver)
            s_new = _block_score(seg_ids, resolver)
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
                    for p in seg],
                "challenger_why": _block_why(inc_ids, seg_ids, resolver),
            }
            if database.upsert_ideal_text_block(str(arc_id), int(key),
                                                fields):
                offers += 1

        # Decked slides the skeleton has never seen → candidate blocks.
        #
        # ONE OFFER PER SLIDE, NEWEST TAKE WINS (founder 2026-08-07). The
        # dedupe used to key on (slide, TAKE), so speaking on a new slide in
        # take 2 and again in take 3 produced two live offers for one slide —
        # and accepting both put that slide into the script twice. Per slide,
        # a later take REPLACES the standing offer in place: same block_key,
        # so the position holds and the FE's "block:<key>" id stays valid.
        #
        # PLACED BY SLIDE, not appended — see candidate_block_key.
        if extras:
            _rows = [r for r in rows if isinstance(r, dict)]
            cand_by_slide = {
                r.get("slide_index"): r for r in _rows
                if r.get("status") == "candidate"
                and isinstance(r.get("slide_index"), int)
                and not isinstance(r.get("slide_index"), bool)}
            for si, grp in sorted(extras, key=lambda t: t[0]):
                prior = cand_by_slide.get(si)
                next_key = None
                if prior is not None:
                    if str(prior.get("incumbent_take_session_id")) == str(sid):
                        continue      # same take — idempotent, nothing new
                    if not _newer_take(take_index,
                                       prior.get("incumbent_take_index")):
                        continue      # an older take never displaces a newer
                    next_key = prior.get("block_key")
                if next_key is None:
                    next_key = candidate_block_key(_rows, si)
                if next_key is None:
                    # The gap between this slide's neighbours is exhausted.
                    # Append rather than collide — and SAY SO, because the
                    # words then sit out of order and that is exactly the
                    # failure this function exists to have stopped.
                    next_key = max((r.get("block_key") or 0)
                                   for r in _rows) + _KEY_STEP
                    logger.warning(
                        "master_document: no room to place slide %s in order "
                        "arc=%s — appended at %s", si, arc_id, next_key)
                fields = {
                    "label": f"Slide {si + 1}",
                    "slide_index": si,
                    "active": False,
                    "status": "candidate",
                    "incumbent_take_session_id": sid,
                    "incumbent_take_index": take_index,
                    "incumbent_pieces": [
                        {"snippet_id": p["snippet_id"], "text": p["text"]}
                        for p in grp],
                    "challenger_take_session_id": None,
                    "challenger_take_index": None,
                    "challenger_pieces": None,
                    "challenger_why": None,
                }
                if database.upsert_ideal_text_block(str(arc_id),
                                                    int(next_key), fields):
                    # The candidate's material pools too — if it is
                    # kept-mine (row deleted) and said again later, the
                    # words survive either way. Best-effort.
                    try:
                        from services.ideal_text_variants import (
                            capture_take_variants,
                        )
                        capture_take_variants(database, arc_id, sid,
                                              take_index, {next_key: grp})
                    except Exception:
                        pass
                    offers += 1
                    # Keep the local view current so a SECOND new slide in
                    # this same take places against the one just written
                    # rather than colliding with it.
                    if prior is not None:
                        prior["incumbent_take_session_id"] = sid
                        prior["incumbent_take_index"] = take_index
                    else:
                        _rows.append({"block_key": int(next_key),
                                      "slide_index": si,
                                      "status": "candidate",
                                      "incumbent_take_session_id": sid,
                                      "incumbent_take_index": take_index})
                        cand_by_slide[si] = _rows[-1]
        return offers
    except Exception as e:
        logger.warning("master_document: take processing failed arc=%s: %s",
                       arc_id, e)
        return 0


def _newer_take(new_index: Any, old_index: Any) -> bool:
    """Is `new_index` a LATER take than `old_index`?

    Unknown → False. An offer that cannot PROVE it is newer never overwrites
    one that is already standing: the failure modes are not symmetric, since
    replacing a good offer with an older one loses material the speaker said,
    while declining to replace merely leaves the existing offer up.
    """
    if not isinstance(new_index, int) or isinstance(new_index, bool):
        return False
    if not isinstance(old_index, int) or isinstance(old_index, bool):
        return True          # nothing to compare against — the new one stands
    return new_index > old_index


def candidate_block_key(rows: Any, slide_index: Any) -> Optional[int]:
    """The block key a candidate for `slide_index` belongs at, or None when it
    cannot be placed in order.

    THE APPEND BUG THIS REPLACES (founder 2026-08-07). This used to be
    `max(block_key) + _KEY_STEP`, i.e. always the end of the document — so
    accepting the recovered words for slide 2 put them AFTER the closer. The
    `_KEY_STEP` gap exists precisely so this cannot happen: its own comment
    says candidates sit "between two existing blocks at its mapped position".
    The intent was right and the arithmetic was not, and nobody could see it
    while the offer never rendered.

    Placed by SLIDE, not by key order: the neighbours are the blocks whose
    slide index is nearest below and above, and the new key is the free
    integer between theirs. Slide order is the document's real order — key
    order only follows it because the skeleton was built that way, and legacy
    rows appended by the old code break that correspondence.

    None means the gap between the two neighbours is exhausted (nine
    insertions between one pair of skeleton blocks). The caller appends and
    says so out loud rather than colliding with an existing key or silently
    renumbering — block keys are public identity, carried in the FE's
    "block:<key>" id and in the decide route.
    """
    if not isinstance(slide_index, int) or isinstance(slide_index, bool):
        return None
    known: list = []
    used: set = set()
    for r in (rows or []):
        if not isinstance(r, dict):
            continue
        key = r.get("block_key")
        if not isinstance(key, int) or isinstance(key, bool):
            continue
        used.add(key)
        si = r.get("slide_index")
        if isinstance(si, int) and not isinstance(si, bool):
            known.append((si, key))

    lower = [t for t in known if t[0] < slide_index]
    upper = [t for t in known if t[0] > slide_index]
    before = max(lower, key=lambda t: t[0])[1] if lower else None
    after = min(upper, key=lambda t: t[0])[1] if upper else None

    if before is None and after is None:
        # No slide information to place against (a deckless skeleton, or an
        # empty document). Appending is then the honest answer rather than a
        # guess, because there is no order to respect.
        return (max(used) + _KEY_STEP) if used else 0
    if after is None:
        k = before + _KEY_STEP                     # genuinely the last slide
        while k in used:
            k += 1
        return k
    if before is None:
        # A slide added BEFORE the first one the speaker ever spoke on. The
        # column is INTEGER and negative keys sort correctly, so this is a
        # real position rather than an edge case to refuse.
        k = after - _KEY_STEP
        while k in used:
            k -= 1
        return k
    if after <= before:
        return None            # legacy rows out of slide order — cannot place
    mid = (before + after) // 2
    if before < mid < after and mid not in used:
        return mid
    for k in range(before + 1, after):
        if k not in used:
            return k
    return None


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
