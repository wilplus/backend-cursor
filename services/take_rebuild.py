"""Every Take rewrites the Slides it spoke (contract 8-9, founder 2026-09-25).

Take 1 builds the Ideal Text. From Take 2 on, each Slide the speaker spoke in
this Take is rebuilt from exactly what they said in it; a Slide they did not
speak keeps its last version (Q4 A). The new words replace owner edits and
coach-verified text too (Q5 A, Q13 A) — nothing is lost, because the previous
version stays in `ideal_text_versions`. Accepted rewrites are NOT re-applied to
the new words (Q16 A): the Paragraph is what was said.

This module plans the rebuild (pure merge + reads) and re-identifies the
Paragraphs afterwards. The durable write is one atomic RPC,
`finalize_ideal_text_take_v2`, called from `services/take_review.py`.

DROP, NEVER GUESS. Whenever the Slide of a Paragraph cannot be proven — an old
document with no provenance, Paragraph rows that do not tile the text, a mix
of Slide-less and Slide-bearing Paragraphs — `plan_rebuild` returns None and
the Take finalizes exactly as before (text unchanged). A Take never fails
because its rebuild could not be planned (LIVE LOOP).
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

_PARA = "\n\n"

# (source, index into that source's paragraph list)
Source = tuple[str, int]


@dataclass
class Rebuild:
    text: str
    document: dict
    # One entry per merged Paragraph, in order.
    sources: list[Source]
    slides: list[Optional[int]]
    # The Slide of each Paragraph of the OLD document, in its order.
    old_slides: list[Optional[int]] = field(default_factory=list)
    rebuilt_slides: set = field(default_factory=set)


def _slide(p: Any) -> Optional[int]:
    s = p.get("slide_index") if isinstance(p, Mapping) else None
    if isinstance(s, int) and not isinstance(s, bool) and s >= 0:
        return s
    return None


def _paragraph_texts(text: str, paragraphs: list) -> Optional[list[str]]:
    """The Paragraph texts, proven to tile the document one to one."""
    if not isinstance(text, str) or not text.strip():
        return None
    blocks = text.split(_PARA)
    if len(blocks) != len(paragraphs):
        return None
    return blocks


def _pieces_in(doc: Mapping, text: str, start: int, end: int,
               shift: int) -> list:
    """The document's pieces that provably sit inside [start, end), moved."""
    out = []
    for piece in doc.get("pieces") or []:
        if not isinstance(piece, Mapping):
            continue
        a, b = piece.get("start"), piece.get("end")
        if (isinstance(a, int) and isinstance(b, int)
                and start <= a < b <= end
                and text[a:b] == piece.get("text")):
            out.append(dict(piece, start=a + shift, end=b + shift))
    return out


def _order(old_slides: list, new_slides: list
           ) -> Optional[tuple[list[tuple[str, int, Optional[int]]], set]]:
    """Which Paragraph comes from where, Slide by Slide. None if unprovable."""
    if all(s is None for s in new_slides) and all(s is None for s in old_slides):
        # No Slide lineage anywhere: the whole text is one run (Q15).
        return [("new", i, None) for i in range(len(new_slides))], {None}
    if None in new_slides or None in old_slides:
        return None
    spoken = {s for s in new_slides if s is not None}
    order: list[tuple[str, int, Optional[int]]] = []
    known = spoken | {s for s in old_slides if s is not None}
    for slide in sorted(known):
        src = "new" if slide in spoken else "old"
        slides = new_slides if src == "new" else old_slides
        order.extend((src, i, slide) for i, s in enumerate(slides)
                     if s == slide)
    return order, spoken


def merge_by_slide(old_text: str, old_doc: Mapping, new_text: str,
                   new_doc: Mapping) -> Optional[Rebuild]:
    """Old document with every Slide the new Take spoke replaced by it.

    Slides are ordered ascending; within a Slide the source order is kept.
    None when the Slide of any Paragraph cannot be proven."""
    old_paras = list(old_doc.get("paragraphs") or [])
    new_paras = list(new_doc.get("paragraphs") or [])
    old_blocks = _paragraph_texts(old_text, old_paras)
    new_blocks = _paragraph_texts(new_text, new_paras)
    if old_blocks is None or new_blocks is None or not new_paras:
        return None
    old_slides = [_slide(p) for p in old_paras]
    planned = _order(old_slides, [_slide(p) for p in new_paras])
    if planned is None:
        return None
    order, rebuilt = planned
    sources = {
        "new": (new_doc, new_text, new_blocks, new_paras),
        "old": (old_doc, old_text, old_blocks, old_paras),
    }
    texts: list[str] = []
    pieces: list = []
    paragraphs: list = []
    cursor = 0
    for n, (src, i, _slide_index) in enumerate(order):
        cursor += len(_PARA) if n else 0
        doc, text, blocks, paras = sources[src]
        block = blocks[i]
        src_start = sum(len(b) + len(_PARA) for b in blocks[:i])
        pieces.extend(_pieces_in(doc, text, src_start,
                                 src_start + len(block), cursor - src_start))
        paragraphs.append(dict(paras[i], start=cursor,
                               end=cursor + len(block)))
        texts.append(block)
        cursor += len(block)
    return Rebuild(
        text=_PARA.join(texts),
        document={
            "pieces": pieces,
            "paragraphs": paragraphs,
            "take_session_id": new_doc.get("take_session_id"),
            "take_index": new_doc.get("take_index"),
        },
        sources=[(src, i) for src, i, _ in order],
        slides=[slide for _, _, slide in order],
        old_slides=old_slides,
        rebuilt_slides=rebuilt,
    )


def plan_rebuild(database: Any, arc_id: str,
                 take_session_id: str) -> Optional[Rebuild]:
    """Read the current document and this Take's transcript; merge them.

    Raw transcript, no ledger bake (Q16 A). None whenever anything cannot
    be proven, and on any error — the Take then finalizes unchanged."""
    try:
        row = database.ideal_text.get_coach_arc_ideal_text(str(arc_id)) or {}
        old_text = str(row.get("auto_text") or "").strip()
        old_doc = row.get("document")
        if not old_text or not isinstance(old_doc, Mapping):
            return None
        from services.transcript_document import build_transcript_document
        new = build_transcript_document(
            str(arc_id), database=database, session_id=str(take_session_id))
        if not isinstance(new, Mapping) or not str(new.get("text") or "").strip():
            return None
        merged = merge_by_slide(old_text, old_doc, str(new["text"]), new)
        if merged is None:
            # Safe (the Take finalizes with its words unchanged) but never
            # silent: this Project is not following its speaker.
            logger.warning("take rebuild: Slides not provable, text kept "
                           "arc=%s take=%s", arc_id, take_session_id)
        return merged
    except Exception as error:
        logger.warning("take rebuild: plan failed arc=%s take=%s: %s",
                       arc_id, take_session_id, error)
        return None


def reidentify_parts(old_rows: list, old_text: str,
                     rebuild: Rebuild) -> list[dict]:
    """Paragraph identity after the rebuild.

    An untouched Paragraph keeps its id (and its lock). A rebuilt Slide reuses
    that Slide's old ids in order (1st with 1st), so history stays continuous;
    extra Paragraphs get fresh ids and dropped ones go. When the old rows do
    not tile the old text, every Paragraph gets a fresh id."""
    from services.ideal_text_parts import agrees_with_text, serve

    rows_by_id = {str(r.get("id")): r for r in old_rows or []
                  if isinstance(r, Mapping)}
    served = serve(old_rows) if old_rows else None
    old_ids: list[str] = []
    if served and agrees_with_text(served, old_text) \
            and len(served) == len(rebuild.old_slides):
        old_ids = [str(p["id"]) for p in served]

    kept = {old_ids[i] for src, i in rebuild.sources
            if src == "old" and i < len(old_ids)}
    spare: dict = {}
    for pid, slide in zip(old_ids, rebuild.old_slides):
        if pid not in kept:
            spare.setdefault(slide, []).append(pid)

    blocks = rebuild.text.split(_PARA)
    out: list[dict] = []
    for n, ((src, i), slide) in enumerate(zip(rebuild.sources,
                                              rebuild.slides)):
        if src == "old" and i < len(old_ids):
            pid = old_ids[i]
        elif spare.get(slide):
            pid = spare[slide].pop(0)
        else:
            pid = str(uuid.uuid4())
        out.append({
            "id": pid,
            "ord": n,
            "text": blocks[n],
            "locked_at": (rows_by_id.get(pid) or {}).get("locked_at"),
        })
    return out


def legacy_helper_words(old_rows: list, rebuild: Rebuild,
                        old_text: str) -> dict:
    """Locked Paragraph-level helper words, grouped by the Slide they were on.

    Helper words locked before the Slide table existed live only on the
    Paragraph row. A rebuilt Slide may give that Paragraph new words, so they
    are carried onto the Slide first (Q12 A) — never lost to a rebuild."""
    from services.ideal_text_parts import agrees_with_text, serve

    served = serve(old_rows) if old_rows else None
    if not served or not agrees_with_text(served, old_text) \
            or len(served) != len(rebuild.old_slides):
        return {}
    out: dict = {}
    for part, slide in zip(served, rebuild.old_slides):
        phrase = part.get("root_phrase")
        if slide is not None and part.get("locked") and phrase:
            out.setdefault(slide, []).append(
                {"phrase": phrase, "source_part_id": str(part["id"])})
    return out


def apply_after_finalize(database: Any, arc_id: str, user_id: str,
                         old_text: str, old_rows: list,
                         rebuild: Rebuild) -> bool:
    """After the atomic RPC wrote the rebuilt text: carry legacy helper words
    onto their Slides, then give the Paragraphs their new identity.

    Best-effort: the words are already durable. A failure here leaves the
    Paragraph rows stale, which every reader treats as "no identity yet" —
    the same state a document has before its first publish."""
    from datetime import datetime, timezone

    # Two independent steps: helper words that cannot be carried must not
    # also cost the Paragraphs their identity, and vice versa.
    try:
        legacy = legacy_helper_words(old_rows, rebuild, old_text)
        if legacy:
            existing = database.get_slide_helper_words(arc_id, user_id) or []
            covered = {r.get("slide_index") for r in existing}
            now = datetime.now(timezone.utc).isoformat()
            for slide, words in legacy.items():
                if slide in covered:
                    continue
                database.replace_slide_helper_words(arc_id, user_id, slide, [
                    {"ord": n, "phrase": w["phrase"], "take_session_id": None,
                     "source_part_id": w["source_part_id"],
                     "locked_at": now, "selected_at": now}
                    for n, w in enumerate(words)])
    except Exception as error:
        logger.warning("take rebuild: helper words not carried arc=%s: %s",
                       arc_id, error)
    try:
        parts = reidentify_parts(old_rows, old_text, rebuild)
        return bool(database.replace_ideal_text_parts(arc_id, user_id, parts))
    except Exception as error:
        logger.warning("take rebuild: identity failed arc=%s: %s",
                       arc_id, error)
        return False


@dataclass
class Plan:
    """What `finalize_later_take_review` needs around its atomic write."""
    rebuild: Optional[Rebuild]
    old_text: str
    old_rows: list

    @property
    def auto_text(self) -> Optional[str]:
        return self.rebuild.text if self.rebuild else None

    @property
    def document(self) -> Optional[dict]:
        return self.rebuild.document if self.rebuild else None

    def confirm(self, database: Any, arc_id: str, user_id: str,
                after: Any) -> bool:
        """After the RPC reported a rebuild: prove the words, then apply
        identity. False when the current row does not carry the words."""
        if self.rebuild is None:
            return False
        if (after or {}).get("auto_text") != self.rebuild.text:
            return False
        apply_after_finalize(database, arc_id, user_id, self.old_text,
                             self.old_rows, self.rebuild)
        return True


def prepare(database: Any, arc_id: str, user_id: str,
            take_session_id: str, before: Any) -> Plan:
    """Plan the rebuild and read what identity needs, before the RPC."""
    rebuild = plan_rebuild(database, arc_id, take_session_id)
    rows: list = []
    if rebuild is not None:
        try:
            rows = database.get_ideal_text_parts(
                arc_id, user_id, with_lock=True) or []
        except Exception as error:
            logger.warning("take rebuild: parts unreadable arc=%s: %s",
                           arc_id, error)
    return Plan(rebuild, str((before or {}).get("auto_text") or ""), rows)
