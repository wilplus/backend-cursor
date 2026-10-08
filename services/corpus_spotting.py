"""The confident-moment spotting an imported talk gets (founder 2026-10-06,
CO1 A, decisions log N56.4): "each import runs the same confident-moment
spotting as a Take: V3 blocks of about 75 words and the machine's pick per
block, stored but never shown, so coaches still judge blind."

SAME CODE, NOT A COPY. The blocks and the pick are V3's own:
``take_feedback_policy_v3.build_shadow_frame`` over the import's transcript
document (``transcript_document.build_transcript_document``), the exact pair
the dark V3 frame of a Take is built from (``ideal_text_changes._v3_shadow``).
Nothing here partitions or ranks; it only feeds V3 and keeps the answer.

Two adaptations of the INPUT, never of the selection:

  * an import has no deck, so its pieces carry no slide; the whole talk is
    one Slide run (slide 0), which is what a deckless Take is to a speaker;
  * an import has no Ideal Text and no verbal Feedback, so the frame is
    built with no served text and no verbal candidates, selecting by rank
    alone, as the dark frame always has. Only the Confident Voice pick per
    block is kept.

STORED, NEVER SHOWN (BLIND COACH, AC-9). The record lands on the import's
``intake_context`` under ``corpus_v3_spotting``: the policy version, the
frame hash, and per block its boundaries, its snippet ids and the picked
snippet id. No score is kept (the clip's own metrics already hold it). No
route serialises ``intake_context`` wholesale; the queue and label payloads
are allowlists and carry none of it (tests/test_training_import_on.py).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

CONTEXT_KEY = "corpus_v3_spotting"
SPOTTING_SCHEMA_VERSION = "corpus-v3-spotting-v1"
#: An import is its own single-Take arc, always Take 1.
IMPORT_TAKE_INDEX = 1
DECKLESS_SLIDE = 0


def _one_slide_run(document: dict) -> dict:
    """A deckless import's pieces as one Slide run. A document whose pieces
    already carry slides is returned unchanged."""
    pieces = [p for p in document.get("pieces") or [] if isinstance(p, dict)]
    if any(p.get("slide_index") is not None for p in pieces):
        return document
    return {**document,
            "pieces": [{**p, "slide_index": DECKLESS_SLIDE} for p in pieces]}


def _picked_snippet(block: dict) -> Optional[str]:
    selected = block.get("selected_candidate_id")
    if not selected:
        return None
    row = next((c for c in block.get("confidence_candidates") or []
                if c.get("candidate_id") == selected), None)
    return str(row["snippet_id"]) if row and row.get("snippet_id") else None


def spotting_record(frame: Optional[dict]) -> dict:
    """What an import keeps of a V3 frame: blocks and picks, no score.
    Pure."""
    from services.take_feedback_policy_v3 import POLICY_VERSION

    base = {"schema_version": SPOTTING_SCHEMA_VERSION,
            "policy_version": POLICY_VERSION}
    if not isinstance(frame, dict) or not frame.get("blocks"):
        return {**base, "outcome": "no_blocks", "blocks": []}
    return {
        **base,
        "outcome": "spotted",
        "frame_schema_version": frame.get("frame_schema_version"),
        "frame_hash": frame.get("frame_hash"),
        "blocks": [
            {
                "block_id": block.get("block_id"),
                "slide_index": block.get("slide_index"),
                "word_count": block.get("word_count"),
                "partition_exception": block.get("partition_exception"),
                "snippet_ids": [str(s) for s in block.get("snippet_ids") or []],
                "selected_snippet_id": _picked_snippet(block),
                "selection_reason": block.get("selection_reason"),
            }
            for block in frame["blocks"]
        ],
    }


def spot_import(database: Any, *, arc_id: Any, session_id: Any,
                recording_id: Any) -> dict:
    """Run V3's block partition and per-block pick over one import.

    Returns the record to store (``spotting_record``); ``outcome`` is
    ``no_document`` when the import has no transcript document to spot on.
    Calls no provider: the transcript and the clips already exist.
    """
    from services.take_feedback_policy_v3 import (
        POLICY_VERSION, build_shadow_frame,
    )
    from services.transcript_document import build_transcript_document

    document = build_transcript_document(
        arc_id, database=database, session_id=str(session_id))
    if not isinstance(document, dict) or not document.get("pieces"):
        return {"schema_version": SPOTTING_SCHEMA_VERSION,
                "policy_version": POLICY_VERSION,
                "outcome": "no_document", "blocks": []}
    frame = build_shadow_frame(
        take_document=_one_slide_run(document),
        snippets=database.get_snippets_by_session(str(session_id)) or [],
        suggestions={},
        feedback_candidates=[],
        take_index=IMPORT_TAKE_INDEX,
        expected_recording_id=str(recording_id or ""),
    )
    record = spotting_record(frame)
    logger.info("corpus spotting sid=%s outcome=%s blocks=%d picks=%d",
                session_id, record["outcome"], len(record["blocks"]),
                sum(1 for b in record["blocks"] if b["selected_snippet_id"]))
    return record


def stored_spotting(context: Any) -> Optional[dict]:
    """The spotting record an import's ``intake_context`` holds, or None."""
    ctx = context if isinstance(context, dict) else {}
    record = ctx.get(CONTEXT_KEY)
    return record if isinstance(record, dict) else None
