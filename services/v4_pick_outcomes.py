"""Each pick learns whether its paragraph rose by the next Take (V4 Phase 1,
B1.5; build plan D-ML-10; founder P5, V10b A, V11 B, V12 A; migration 0451).

THE PARAGRAPH. When a Take's dark frame is first drawn, each moment's words
are bound to the Ideal Text Paragraph they belong to, by the served path's
own rule (``ideal_text_parts.bind_pieces_to_parts``: slide first, span to
refine, never a guess). A moment whose words are all bound to one Paragraph
belongs to it; one that straddles two, or cannot be proven, belongs to none
and is measured by its slide instead (V10b A: "the slide as backup").
Paragraph ids survive rewording (D-ML-2), so the same id in the next Take is
the same paragraph.

THE OUTCOME. The database computes it (``compute_v4_pick_outcomes_v1``) once
both Takes have their willfidence reads (B1.3): per moment of Take N, the
mean S*W of all its paragraph's rated moments (V12 A) in Take N and Take
N+1, else of its slide's, and "rose" only when the rise is clearer than
``MARGIN`` (V11 B; a placeholder set later from dark-run data). ``outcome``
is the same rule in Python. Internal only (AC-9); every write here is a side
write that never raises (LIVE LOOP).
"""
from __future__ import annotations

import copy
import logging
from typing import Any, Callable, Iterable, Optional

logger = logging.getLogger(__name__)

MARGIN = 0.05
MARGIN_VERSION = "rise-margin-v0-placeholder"


def outcome(before: Optional[float], after: Optional[float],
            margin: float = MARGIN) -> str:
    if before is None or after is None:
        return "not_measured"
    return "rose" if after - before > margin else "did_not_rise"


def paragraph_of(block: dict, part_by_clip: dict[str, Optional[str]]) -> Optional[str]:
    """The one Paragraph all of a moment's clips are bound to, or None."""
    parts = {part_by_clip.get(str(clip)) for clip in block.get("snippet_ids") or []}
    if len(parts) != 1:
        return None
    (part,) = parts
    return str(part) if part else None


def paragraph_map(frame: dict, bound_document: Any) -> list[dict]:
    """[{block_id, paragraph_id}] for every frame block. Pure."""
    pieces = (bound_document or {}).get("pieces") if isinstance(bound_document, dict) else None
    part_by_clip: dict[str, Optional[str]] = {}
    for piece in pieces or []:
        if not isinstance(piece, dict) or not piece.get("snippet_id"):
            continue
        clip = str(piece["snippet_id"])
        part = str(piece.get("part_id") or "") or None
        # A clip bound to two Paragraphs is bound to none.
        if clip in part_by_clip and part_by_clip[clip] != part:
            part_by_clip[clip] = None
        else:
            part_by_clip[clip] = part
    return [{"block_id": str(block.get("block_id") or ""),
             "paragraph_id": paragraph_of(block, part_by_clip)}
            for block in frame.get("blocks") or []]


def map_paragraphs(database: Any, take_session_id: Any, frame: Any, document: Any, *,
                   served_text: Any, slide_regions: Any,
                   parts: Callable[[], Any]) -> Optional[dict]:
    """Bind the Take's moments to Paragraphs and store the map. Never raises."""
    take = str(take_session_id or "").strip()
    if not take or not isinstance(frame, dict):
        return None
    try:
        from services.ideal_text_parts import bind_pieces_to_parts
        bound = bind_pieces_to_parts(copy.deepcopy(document), served_text=served_text,
                                     slide_regions=slide_regions, parts=parts())
        return database.record_v4_moment_paragraphs(take, paragraph_map(frame, bound))
    except Exception as error:  # noqa: BLE001 -- dark measure; the Take stands
        logger.warning("v4 moment paragraphs not stored take=%s: %s", take, error)
        return None


def compute(database: Any, next_take_session_id: Any) -> Optional[dict]:
    """Ask the database for the previous Take's outcomes. Never raises."""
    take = str(next_take_session_id or "").strip()
    if not take:
        return None
    try:
        return database.compute_v4_pick_outcomes(take)
    except Exception as error:  # noqa: BLE001 -- dark measure
        logger.warning("v4 pick outcomes not computed take=%s: %s", take, error)
        return None


def rise_share(rows: Iterable[dict], kinds: Iterable[str]) -> Optional[float]:
    """Of the measured moments picked for any of ``kinds``, the share that
    rose: the next-Take rise BEXIT compares. Pure."""
    wanted = set(kinds)
    measured = [r for r in rows
                if r.get("outcome") in ("rose", "did_not_rise")
                and wanted & set(r.get("picks") or r.get("v3_picks") or [])]
    if not measured:
        return None
    return sum(1 for r in measured if r["outcome"] == "rose") / len(measured)
