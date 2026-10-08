"""Dark, non-serving contract for Take feedback policy v3.

The frame is an immutable policy-evaluation artifact. It never serves feedback,
creates a rendered exposure, or becomes dataset input. Every candidate that the
policy examines is retained as eligible or excluded with a typed reason.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from pathlib import Path
from typing import Any, Iterable, NamedTuple, Optional

from services.feedback_data_contract import FEATURE_SCHEMA_VERSION
from services.reasonable_confidence import selection_summary
from services.take_feedback_manager import (
    EVIDENCE_SCHEMA_VERSION as MANAGER_EVIDENCE_SCHEMA_VERSION,
    POLICY_VERSION as MANAGER_RULES_VERSION,
    VERBAL_FAMILIES,
    TakeDocumentMap,
    producer_versions,
    verbal_evidence,
    verbal_exclusion,
)
from services.voice_confidence import (
    BAND_HIGH,
    BAND_MID_HIGH,
    VERSION as CONFIDENCE_DETECTOR_VERSION,
)
from config import Config

config = Config()
logger = logging.getLogger(__name__)


POLICY_VERSION = "take-feedback-policy-v3-universal-dark-v3"
SERVICE_POLICY_VERSION = "take-feedback-policy-v3-serving-v1"
FRAME_SCHEMA_VERSION = "take-feedback-policy-v3-frame-v6"
#: V4 Phase 1, B1.1 (pick logging). The frame carries every candidate with its
#: chance of being picked, the Take's seed and the policy version, so V4 can be
#: evaluated against what V3 would have done. Internal only (AC-9).
PICK_LOG_VERSION = "v4-pick-log-v1"
PICK_SEED_VERSION = "v4-pick-seed-v1"
SUGGESTION_GENERATOR_CONTRACT_VERSION = "feedback-candidate-generator-v1"
TARGET_WORDS = 75
MIN_WORDS = 60
MAX_WORDS = 90

#: Slide-coverage floor by Take index (founder, 2026-09-18 — contract 24c,
#: Appendix H.13.1). Take 3 and every Take after it are held at 100%.
COVERAGE_FLOOR_BY_TAKE: dict[int, float] = {1: 0.70, 2: 0.80}
COVERAGE_FLOOR_MATURE = 1.00
_WORD_RE = re.compile(r"[^\W_]+(?:[’'-][^\W_]+)*", re.UNICODE)
_VERBAL_FAMILIES = set(VERBAL_FAMILIES)


def dark_enabled(acquisition_principal_id: Any) -> bool:
    """True only for the exact configured founder in explicit dark mode.

    This gate decides whose Takes get a dark frame (with its pick log).
    Any change to it is its own founder-approved change with its own test.
    """
    mode = (config.TAKE_FEEDBACK_POLICY_V3_SHADOW_WRITE_MODE or "off").strip()
    founder = (config.TAKE_FEEDBACK_POLICY_V3_FOUNDER_PRINCIPAL_ID or "").strip()
    owner = str(acquisition_principal_id or "").strip()
    return bool(
        mode == "dark"
        and founder
        and owner
        and hmac.compare_digest(founder, owner)
    )


def pick_seed(take_id: Any) -> str:
    """The Take's random seed for V4 Phase 1 (B1.1, B1.2).

    Deterministic from the Take id, so the seeded random 20% (B1.2) and any
    replay draw the same numbers. A decimal string of at most 16 digits
    (52 bits): exact in JSON and in JavaScript.
    """
    take = str(take_id or "").strip().lower()
    digest = hashlib.sha256(
        f"{PICK_SEED_VERSION}:{take}".encode("utf-8")).hexdigest()
    return str(int(digest[:13], 16))


def _identified(inventory: list[dict]) -> list[dict]:
    """The inventory rows the frame lists: each with its candidate id.

    A verbal row with no id is excluded by `verbal_exclusion`
    (``missing_candidate_identity``), can never be anchored, and stays in
    ``excluded_candidates`` with that reason. It is not listed under its
    lane, so the lane's candidates and the pick log hold the same rows and
    the writer (0441) can refuse any listed candidate without an id.
    """
    return [item for item in inventory if str(item.get("candidate_id") or "")]


def _pick_entry(lane: str, block_id: Any, item: dict, chosen: Any) -> dict:
    candidate_id = str(item.get("candidate_id") or "")
    eligible = item.get("eligibility") == "eligible"
    return {
        "lane": lane,
        "block_id": block_id,
        "candidate_id": candidate_id,
        "eligible": eligible,
        "pick_probability": (
            (1.0 if candidate_id in chosen else 0.0) if eligible else None),
    }


def _pick_log(take_id: str, blocks: list[dict],
              lanes: Iterable[tuple[str, list[dict], list[str]]]) -> dict:
    """Every candidate with its chance of being picked (V4 B1.1).

    The writer (0441) refuses a log that is not the inventory exactly: every
    confidence candidate under its block, every verbal candidate under its
    lane, each once. Every listed candidate has an id (a confidence id is
    built from its clip; a verbal lane lists only `_identified` rows), and
    the writer refuses one without.

    V3 picks deterministically, so the chance is 1.0 for the candidate it
    selected and 0.0 for every other eligible one; an excluded candidate has
    no chance (None) and keeps its reason in the inventory. Internal only
    (AC-9): the service frame drops this section, and no route reads it.
    """
    entries: list[dict] = []
    for block in blocks:
        chosen = {str(block.get("selected_candidate_id") or "")}
        for item in block.get("confidence_candidates") or []:
            entries.append(_pick_entry(
                "confident_voice", block.get("block_id"), item, chosen))
    for lane, inventory, selected_ids in lanes:
        chosen = set(selected_ids)
        for item in inventory:
            entries.append(_pick_entry(lane, None, item, chosen))
    return {
        "version": PICK_LOG_VERSION,
        "policy_version": POLICY_VERSION,
        "seed": pick_seed(take_id),
        "seed_version": PICK_SEED_VERSION,
        "selection": "deterministic_relative_best",
        "candidates": entries,
    }


def _words(value: Any) -> int:
    return len(_WORD_RE.findall(value if isinstance(value, str) else ""))


def _integer(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _versions(row: Any) -> dict:
    return producer_versions(row)


def _source_code_sha256() -> str:
    """Hash every implementation module that can affect this frozen frame."""
    root = Path(__file__).resolve().parent
    names = (
        "take_feedback_policy_v3.py",
        "take_feedback_manager.py",
        "feedback_data_contract.py",
        "voice_confidence.py",
        "rewrite_declines.py",
    )
    digest = hashlib.sha256()
    for name in names:
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update((root / name).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _piece(raw: Any, ordinal: int) -> Optional[dict]:
    row = raw if isinstance(raw, dict) else {}
    snippet_id = str(row.get("snippet_id") or "")
    take_id = str(row.get("take_session_id") or "")
    slide = _integer(row.get("slide_index"))
    start, end = _integer(row.get("start")), _integer(row.get("end"))
    raw_text = row.get("text")
    text: str = raw_text if isinstance(raw_text, str) else ""
    if (
        not snippet_id
        or not take_id
        or slide is None
        or slide < 0
        or start is None
        or end is None
        or start < 0
        or end <= start
        or not text.strip()
    ):
        return None
    return {
        "snippet_id": snippet_id,
        "take_id": take_id,
        "slide_index": slide,
        "start": start,
        "end": end,
        "word_count": _words(text),
        "ordinal": ordinal,
        "recording_id": str(row.get("recording_id") or "") or None,
        "start_offset_ms": row.get("start_offset_ms"),
        "duration_ms": row.get("duration_ms"),
        # The same words' position in the SERVED Ideal Text, when the
        # relocation could prove one (`bind_pieces_to_parts`). `start`/`end`
        # above are transcript offsets and address a different document;
        # only these may be used for a span the client draws on.
        "served_start": _integer(row.get("served_start")),
        "served_end": _integer(row.get("served_end")),
        # The Paragraph the binding proved for these words, RAW, exactly as
        # the serve path reads it off the same piece: servable selection
        # (24b) asks the serve path's own predicate, so both must hand it the
        # same value. Internal to the partition; it never reaches the frame.
        "part_id": row.get("part_id"),
    }


def _block_cost(word_count: int) -> int:
    outside = (
        (MIN_WORDS - word_count) * 12 if word_count < MIN_WORDS
        else (word_count - MAX_WORDS) * 12 if word_count > MAX_WORDS
        else 0
    )
    return abs(word_count - TARGET_WORDS) + outside


def _partition_run(pieces: list[dict]) -> list[list[dict]]:
    """Globally closest piece-boundary partition to the 75-word target."""
    size = len(pieces)
    best: list[Optional[tuple[int, int, tuple[int, ...]]]] = [None] * (size + 1)
    best[size] = (0, 0, ())
    for at in range(size - 1, -1, -1):
        words = 0
        options: list[tuple[int, int, tuple[int, ...]]] = []
        for end in range(at + 1, size + 1):
            words += int(pieces[end - 1]["word_count"])
            tail = best[end]
            if tail is None:
                continue
            options.append((
                _block_cost(words) + tail[0],
                1 + tail[1],
                (end,) + tail[2],
            ))
        best[at] = min(options, key=lambda value: (value[0], value[1], value[2]))
    boundaries = best[0][2] if best[0] is not None else (size,)
    out: list[list[dict]] = []
    at = 0
    for end in boundaries:
        out.append(pieces[at:end])
        at = end
    return out


def _semantic_blocks(raw_pieces: Any) -> tuple[list[dict], list[dict]]:
    pieces: list[dict] = []
    exclusions: list[dict] = []
    for ordinal, raw in enumerate(raw_pieces or []):
        normalized = _piece(raw, ordinal)
        if normalized is None:
            row = raw if isinstance(raw, dict) else {}
            exclusions.append({
                "candidate_kind": "speech_piece",
                "snippet_id": str(row.get("snippet_id") or "") or None,
                "reason": "invalid_document_piece",
                "ordinal": ordinal,
            })
        else:
            pieces.append(normalized)

    # Returning to a slide creates a new presentation moment. Partition each
    # contiguous run independently so chronology cannot be reordered.
    runs: list[list[dict]] = []
    for piece in pieces:
        if not runs or runs[-1][-1]["slide_index"] != piece["slide_index"]:
            runs.append([piece])
        else:
            runs[-1].append(piece)

    blocks: list[dict] = []
    for run_index, run in enumerate(runs):
        for local_index, pack in enumerate(_partition_run(run)):
            raw_key = "\0".join([
                pack[0]["take_id"],
                str(pack[0]["slide_index"]),
                str(run_index),
                str(local_index),
                *(piece["snippet_id"] for piece in pack),
            ])
            block_id = "speech-block:" + hashlib.sha256(
                raw_key.encode("utf-8")
            ).hexdigest()[:20]
            blocks.append({
                "block_id": block_id,
                "slide_index": pack[0]["slide_index"],
                "word_count": sum(piece["word_count"] for piece in pack),
                "snippet_ids": [piece["snippet_id"] for piece in pack],
                "start": pack[0]["start"],
                "end": pack[-1]["end"],
                "partition_exception": _partition_exception(pack, run),
                "pieces": pack,
            })
    return blocks, exclusions


#: Why a block stands outside the normal 60-90 words (contract 24a: "An
#: indivisible short or long Paragraph remains intact with a typed partition
#: exception"). Internal arbitration record, never surfaced (24i).
#:   indivisible_long        one piece over 90 words: words are never cut
#:   short_slide_run         the whole Slide run is under 60 words, and a
#:                           block never crosses a Slide boundary
#:   closest_outside_range   any other: the closest partition at the piece
#:                           boundaries still falls outside the normal range
PARTITION_EXCEPTIONS = (
    "indivisible_long", "short_slide_run", "closest_outside_range",
)


def _partition_exception(pack: list[dict], run: list[dict]) -> Optional[str]:
    """The typed partition exception for one block, or None inside 60-90."""
    words = sum(int(piece["word_count"]) for piece in pack)
    if MIN_WORDS <= words <= MAX_WORDS:
        return None
    if words > MAX_WORDS and len(pack) == 1:
        return "indivisible_long"
    if words < MIN_WORDS and len(pack) == len(run):
        return "short_slide_run"
    return "closest_outside_range"


def _clip_lineage(
    piece: dict,
    snippet: dict,
    *,
    expected_take_id: str,
    expected_recording_id: str,
) -> tuple[Optional[dict], Optional[str]]:
    """Return exact immutable clip coordinates or a typed exclusion."""
    if not snippet:
        return None, "missing_snippet_record"
    if piece.get("take_id") != expected_take_id:
        return None, "document_take_mismatch"
    if str(snippet.get("session_id") or "") != expected_take_id:
        return None, "snippet_take_mismatch"
    if not expected_recording_id:
        return None, "missing_take_recording_identity"
    piece_recording = str(piece.get("recording_id") or "")
    snippet_recording = str(snippet.get("recording_id") or "")
    if not piece_recording or not snippet_recording:
        return None, "missing_recording_identity"
    if (
        piece_recording != expected_recording_id
        or snippet_recording != expected_recording_id
    ):
        return None, "recording_identity_mismatch"

    piece_start = _integer(piece.get("start_offset_ms"))
    snippet_start = _integer(snippet.get("start_offset_ms"))
    if piece_start is None or snippet_start is None or piece_start < 0 or snippet_start < 0:
        return None, "invalid_start_offset"
    piece_duration = _integer(piece.get("duration_ms"))
    snippet_duration = _integer(snippet.get("duration_ms"))
    if (
        piece_duration is None
        or snippet_duration is None
        or piece_duration <= 0
        or snippet_duration <= 0
    ):
        return None, "invalid_duration"
    if piece_start != snippet_start or piece_duration != snippet_duration:
        return None, "clip_interval_mismatch"

    identity = {
        "take_id": expected_take_id,
        "recording_id": expected_recording_id,
        "snippet_id": piece["snippet_id"],
        "start_offset_ms": piece_start,
        "duration_ms": piece_duration,
    }
    encoded = json.dumps(
        identity, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        **identity,
        "clip_identity_sha256": hashlib.sha256(encoded).hexdigest(),
    }, None


#: The Take's most and second-most Confident Voice items render green
#: (contract 24g). The number is the bookmark colour's, no longer praise's:
#: until 2026-09-29 praise anchored to these two blocks only.
MOST_CONFIDENT_LIMIT = 2

#: THE MANAGER'S READ OF A BLOCK (contract 24f, founder 2026-09-29: "praise on
#: any moment both sides call confident, a rewrite on any weak-words
#: moment"). Above neutral is read confident; neutral and below is read weak.
#: The same cut as `services.confident_voice_practice.machine_read`, which
#: reads the same stamped score on the clip when the judgement lands, so the
#: note the Manager anchored and the follow-up the matrix chooses agree.
#: Internal: the read chooses and is never surfaced (AC-9).
CONFIDENT_BANDS = (BAND_HIGH, BAND_MID_HIGH)

#: The practice threshold cuts BELOW neutral (founder, 2026-09-18). The two
#: bands under it prompt; neutral and above do not.
#:
#: Chosen sparing on H.0's asymmetry — offering practice to someone who spoke
#: well is the false-positive direction, and "when a choice here is arguable,
#: it goes toward silence". It is a policy dial, not a measured constant, so it
#: moves on evidence rather than on preference.
PRACTICE_BANDS = ("delivery_signal_mid_low", "delivery_signal_low")

#: A block whose confidence item was never selected has no delivery read, so
#: it prompts nothing. Stated once rather than defaulted at each use site.
_UNROUTED_BLOCK = {
    "delivery_band": None,
    "practice_prompt": False,
    "carries_exercise": False,
}


def _practice_routing(blocks: list[dict]) -> dict:
    """Which blocks prompt practice, and which carry an exercise.

    EVERY block below the neutral band shows "Let's practice". EVERY block the
    machine reads weak (the neutral band and below, `CONFIDENT_BANDS`) carries
    the exercise matched to its own clip (contract 24f, founder 2026-09-29,
    superseding "one exercise, on the weakest item below the neutral band":
    "they can carry as many exercises as bookmark indicates"). Whether one is
    there is the library's match under 35g-1, made on the serve path; this
    records which blocks it may be made for, nothing more.

    AC-9, and this is the sharp edge: `services.voice_confidence.band()` warns
    in its own docstring that the band IS a verdict and must never reach a user
    payload. So the band stays in this frame, which is the internal policy
    artifact, and what leaves here is two booleans. A client is told *that*
    practice is offered, never *how it was scored*.
    """
    from services.voice_confidence import band as delivery_band

    routing: dict[str, dict] = {}
    for block in blocks:
        selected_id = block.get("selected_candidate_id")
        if not selected_id:
            continue
        chosen = next(
            (
                row for row in block.get("confidence_candidates") or []
                if row.get("candidate_id") == selected_id
            ),
            None,
        )
        if chosen is None:
            continue
        label = delivery_band(chosen.get("machine_score"))
        routing[block["block_id"]] = {
            "delivery_band": label,
            "practice_prompt": label in PRACTICE_BANDS,
            "carries_exercise": (
                label is not None and label not in CONFIDENT_BANDS),
        }


    # Applied HERE rather than in the caller. build_shadow_frame is
    # grandfathered at CC 37 and the ratchet only lets it come down, so a loop
    # in the caller costs a point it cannot spend — and the routing belongs
    # beside the rule that computed it anyway.
    for block in blocks:
        block.update(routing.get(block["block_id"], _UNROUTED_BLOCK))
    return routing


def _top_confidence_blocks(blocks: list[dict], limit: int) -> list[dict]:
    """The blocks whose selected item ranked highest, best first.

    Reuses `_confidence_rank`, so "most confident" here means exactly what it
    means inside a block: measured beats unmeasured, higher score wins, and
    ordinal then candidate id break ties. One ranking, used at two scales —
    if these diverged, the item called strongest inside its block could lose
    the Take-level comparison to one the same rule ranked below it.
    """
    ranked: list[tuple[tuple, dict]] = []
    for block in blocks:
        selected_id = block.get("selected_candidate_id")
        if not selected_id:
            continue
        chosen = next(
            (
                row for row in block.get("confidence_candidates") or []
                if row.get("candidate_id") == selected_id
            ),
            None,
        )
        if chosen is not None:
            ranked.append((_confidence_rank(chosen), block))
    ranked.sort(key=lambda pair: pair[0])
    return [block for _, block in ranked[:limit]]


def _mark_top_confidence(blocks: list[dict], limit: int) -> list[dict]:
    """`_top_confidence_blocks`, and it writes the answer onto the blocks.

    THE GREEN BOOKMARK (contract 24g). The Take's two most Confident Voice
    items render green, identically — first and second are never distinguished,
    because a visible ordering is a surfaced ranking. Which two they are was
    once computed for praise anchoring and then thrown away, so the client
    had no way to draw them and every bookmark came out the same colour.
    Praise no longer anchors here (24f, founder 2026-09-29: every block read
    confident); the mark is the colour alone.

    A FLAG, NOT THE RANK. What lands on the block is a boolean: this item is
    one of the two, with no position and no score. `_top_confidence_blocks`
    returns them best-first; nothing downstream of here may see the order
    (24i).

    Written here rather than in the caller for the reason `_practice_routing`
    gives: `build_shadow_frame` is grandfathered at CC 37 and the ratchet only
    lets it come down, so a loop up there costs a point it cannot spend — and
    the mark belongs beside the rule that decided it.

    Every block is written, not only the winners, so a re-run cannot leave a
    stale green on a block that has since been beaten.
    """
    top = _top_confidence_blocks(blocks, limit)
    top_ids = {str(block.get("block_id")) for block in top}
    for block in blocks:
        block["most_confident"] = str(block.get("block_id")) in top_ids
    return top


def _blocks_read(blocks: list[dict], *, confident: bool) -> list[dict]:
    """The selected blocks the machine reads confident (above neutral) or
    weak (neutral and below), in document order.

    A block with no delivery band — no selected item, or a clip the detector
    could not measure — is neither. The machine could not read it, so neither
    note anchors there: the judgement still reaches the coach as an ambiguity
    (35g-2), and a human ear settles it.
    """
    return [
        block for block in blocks
        if block.get("selected_candidate_id")
        and block.get("delivery_band") is not None
        and (block["delivery_band"] in CONFIDENT_BANDS) == confident
    ]


def _anchored_notes(ranked: list[dict], blocks: list[dict]) -> list[dict]:
    """The best note inside each of these blocks: praise for the blocks read
    confident, the rewrite for the blocks read weak (contract 24f, founder
    2026-09-29 — the caps of two praise and one rewrite per Take are lifted).

    A candidate qualifies only when its document span falls INSIDE the block.
    The note stays evidence-led: it is the detector's own finding about words
    the speaker actually said, not a compliment or a correction attached to a
    block because of how the block was read.

    The consequence, accepted deliberately: a block read confident sometimes
    carries no praise and a block read weak no rewrite, because nothing
    defensible was found in its words. That is the honest outcome. The
    alternative — a note made from whatever text was nearest — is
    manufacturing, which L2 and contract 24d forbid.

    `ranked` arrives best-first, so the first candidate found inside a block
    is that block's best. One per block, never more, and a candidate anchors
    once.
    """
    chosen: list[dict] = []
    used: set[str] = set()
    for block in blocks:
        start, end = block.get("start"), block.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        for item in ranked:
            candidate_id = str(item.get("candidate_id") or "")
            span = item.get("document_span")
            if not candidate_id or candidate_id in used or not isinstance(span, dict):
                continue
            if span.get("start") is None or span.get("end") is None:
                continue
            if start <= int(span["start"]) and int(span["end"]) <= end:
                chosen.append({
                    "block_id": block["block_id"],
                    "candidate_id": candidate_id,
                })
                used.add(candidate_id)
                break
    return chosen


#: The typed outcome of a verbal lane that found nothing honest to say
#: (contract 25): no card, and nothing invented to fill it.
NO_DEFENSIBLE_CANDIDATE = "no_defensible_candidate"


def _lane_outcome(anchors: list[dict], read_blocks: list[dict]) -> dict:
    """What one verbal lane decided, typed (contract 25, as amended
    2026-09-29: the comparison is within the block).

    `outcome` is ``no_defensible_candidate`` when the lane anchored no note at
    all on this Take, and each block read for the lane that carries no note
    is named with the same reason: an honest empty lane shows no card, and
    the frame says so rather than leaving the lane merely absent. Missing or
    unusable source material stays its own typed exclusion
    (`excluded_candidates`)."""
    anchored = {str(row.get("block_id")) for row in anchors}
    return {
        "outcome": "selected" if anchors else NO_DEFENSIBLE_CANDIDATE,
        "blocks_without_note": [
            {"block_id": block["block_id"], "reason": NO_DEFENSIBLE_CANDIDATE}
            for block in read_blocks
            if str(block.get("block_id")) not in anchored
        ],
    }


def _log_verbal_lanes(take_id: Any, rewrite_ranked: list,
                      rewrite_selected: list, praise_ranked: list,
                      praise_selected: list, *, weak_blocks: int = 0) -> None:
    """Why a lane came out empty, in counts only (founder 2026-09-28: "no
    praise and no corrections"). No detector finding (candidates=0) and a
    finding outside every block its read would anchor it to (candidates>0,
    anchored=0) are different causes. `weak_blocks` is how many blocks were
    read weak, so `selected` over it is the share of weak blocks carrying a
    clearer version (D-ML-3). Internal log only, never a payload (AC-9)."""
    logger.info(
        "v3 lanes take=%s rewrite candidates=%d selected=%d weak_blocks=%d "
        "praise candidates=%d anchored=%d",
        take_id or "?", len(rewrite_ranked), len(rewrite_selected),
        weak_blocks, len(praise_ranked), len(praise_selected),
    )


def coverage_floor(take_index: Any) -> float:
    """The share of assessable Slides this Take is required to cover."""
    if isinstance(take_index, bool) or not isinstance(take_index, int):
        return COVERAGE_FLOOR_MATURE
    return COVERAGE_FLOOR_BY_TAKE.get(take_index, COVERAGE_FLOOR_MATURE)


def _slide_coverage(blocks: list[dict], take_index: Any) -> dict:
    """Which Slides this Take actually covered, and why the rest were missed.

    THE DENOMINATOR IS THE LOAD-BEARING PART (contract 24c, founder
    2026-09-18). It is Slides that produced **at least one block**, not Slides
    that carry speech and not every Slide in the deck.

    Measured against every Slide, a deck where four Slides are silent or too
    short to partition caps coverage at ten-fourteenths forever — 71% — so the
    80% rung is unreachable and 100% is unreachable by construction, through
    nobody's fault. Measured against blocks, 100% is reachable, because a valid
    block always has a relative best. Anything that never formed a block was
    never assessable, and failing to cover it is not a failure.

    A shortfall is a DEFECT TO INVESTIGATE, never a licence to pad (24d). So
    every uncovered Slide carries the `selection_reason` of each block on it,
    which is the only thing that makes a shortfall diagnosable rather than
    merely visible. Those strings are what tell a candidate-generation gap
    apart from a policy one.

    Internal only — coverage is an arbitration input and is never surfaced
    (AC-9, contract 24i).
    """
    by_slide: dict[int, list[dict]] = {}
    for block in blocks:
        by_slide.setdefault(int(block["slide_index"]), []).append(block)

    covered: list[int] = []
    uncovered: list[dict] = []
    for slide_index in sorted(by_slide):
        slide_blocks = by_slide[slide_index]
        if any(block.get("selected_candidate_id") for block in slide_blocks):
            covered.append(slide_index)
            continue
        uncovered.append({
            "slide_index": slide_index,
            "block_count": len(slide_blocks),
            "reasons": sorted({
                str(block.get("selection_reason") or "unknown")
                for block in slide_blocks
            }),
        })

    assessable = len(by_slide)
    floor = coverage_floor(take_index)
    # An empty document is not a coverage failure: there was nothing to cover,
    # and reporting 0% against a 70% floor would make "no speech at all" look
    # like a broken selector.
    ratio = (len(covered) / assessable) if assessable else 1.0
    return {
        "denominator": "slides_with_at_least_one_valid_block",
        "assessable_slides": assessable,
        "covered_slides": len(covered),
        "covered_slide_indexes": covered,
        "uncovered": uncovered,
        "ratio": round(ratio, 4),
        "required_floor": floor,
        "meets_floor": ratio + 1e-9 >= floor,
    }


def _confidence_candidate(
    piece: dict,
    snippet: dict,
    suggestion: dict,
    *,
    expected_take_id: str,
    expected_recording_id: str,
) -> dict:
    from services.reasonable_confidence import reason_tier
    from services.voice_confidence import stamped_score

    metrics = snippet.get("metrics") if isinstance(snippet, dict) else None
    metrics = metrics if isinstance(metrics, dict) else {}
    _reason_tier, _reason_degraded = reason_tier(metrics)
    stamped = metrics.get("voice_confidence")
    stamped = stamped if isinstance(stamped, dict) else {}
    observed_version = str(stamped.get("version") or "") or None
    score = (
        stamped_score(metrics)
        if observed_version == CONFIDENCE_DETECTOR_VERSION else None
    )
    clip_identity, exclusion_reason = _clip_lineage(
        piece,
        snippet,
        expected_take_id=expected_take_id,
        expected_recording_id=expected_recording_id,
    )
    # A detector-version change is a construct/provenance boundary, not
    # missing evidence. Old sex-routed v2 measurements stay visible in the
    # frozen inventory but cannot be ranked by the universal-v3 policy until
    # the exact clip is recomputed.
    if (
        exclusion_reason is None
        and observed_version is not None
        and observed_version != CONFIDENCE_DETECTOR_VERSION
    ):
        exclusion_reason = "incompatible_detector_version"
    return {
        "candidate_id": (
            f"relative-confidence:{piece['take_id']}:{piece['snippet_id']}"
        ),
        "snippet_id": piece["snippet_id"],
        "take_id": piece["take_id"],
        "slide_index": piece["slide_index"],
        "document_span": {"start": piece["start"], "end": piece["end"]},
        # TRANSCRIPT above, IDEAL TEXT here, and they are different
        # documents. `document_span` locates the spoken words for the audio
        # and transcript evidence; `target_span` is where the bookmark is
        # drawn. None when the relocation could not prove a position -- the
        # row is then rejected rather than anchored by guess.
        "target_span": (
            {"start": piece["served_start"], "end": piece["served_end"]}
            if piece.get("served_start") is not None
            and piece.get("served_end") is not None
            else None
        ),
        "word_count": piece["word_count"],
        "clip_identity": clip_identity,
        "eligibility": (
            "eligible" if clip_identity and exclusion_reason is None
            else "excluded"
        ),
        "exclusion_reason": exclusion_reason,
        "machine_score": score,
        "machine_version": observed_version,
        # THE REASON LAYER (24j). What the words did, read back from the slide
        # score already stored on this piece. `None` means the piece carries no
        # usable slide read at all, which sorts last rather than being excluded
        # — excluding could empty a block, and 24b says every valid block
        # yields one. `reason_degraded` marks a verdict that came from word
        # overlap rather than entailment, so nothing downstream mistakes the
        # coarse read for the measured one.
        "reason_tier": _reason_tier,
        "reason_degraded": _reason_degraded,
        "suggestion_provenance": _versions(suggestion),
        "ordinal": piece["ordinal"],
        "selection_language": (
            "relatively_strongest_measured"
            if score is not None and score > 0
            else "best_available_tentative"
        ),
    }


def _confidence_rank(candidate: dict) -> tuple:
    """Sort key for the candidates inside one block. Lower wins.

    THE REASON LAYER LEADS (24j, founder 2026-09-23): what the words did
    outranks how the delivery sounded, and the delivery read then orders
    candidates only WITHIN a tier. Sequenced, never blended — see
    `services/reasonable_confidence.py` for why that distinction is the whole
    design rather than a detail of it.

    `ordering_rank` returns one constant for every candidate while the flag is
    off, so this tuple is byte-for-byte what it was until the layer is turned
    on deliberately.
    """
    from services.reasonable_confidence import ordering_rank

    score = candidate.get("machine_score")
    measured = isinstance(score, (int, float)) and not isinstance(score, bool)
    numeric_score = (
        float(score)
        if isinstance(score, (int, float)) and not isinstance(score, bool)
        else 0.0
    )
    return (
        ordering_rank(candidate),
        0 if measured else 1,
        -numeric_score if measured else 0.0,
        int(candidate.get("ordinal") or 0),
        str(candidate.get("candidate_id") or ""),
    )


# ── SERVABILITY IS PART OF SELECTION (contract 24b, audit 2026-10-05) ────────
#
# The frame used to choose each block's item by rank alone, and only after it
# had chosen did the serve path try to prove that item's Paragraph and served
# span (`take_feedback_policy_v3_service._row_rejection`). A winner it could
# not prove was dropped there, and the block came out EMPTY although a
# lower-ranked clip in the same block could have been served: 24b's "one
# item per valid block" lost to an ordering accident.
#
# So the serve path's proof now runs INSIDE selection, through one predicate
# both sides call (`unservable`). Two copies of the rule are exactly how the
# frame and the serve path came to disagree; one cannot.

#: Why the serve path cannot prove a lineage-eligible Confident Voice
#: candidate: the typed exclusion the frame records. Internal arbitration
#: record, never surfaced (AC-9, 24i).
#:   unservable_paragraph  the binding proved no Paragraph for its words
#:                         (`ideal_text_parts.bind_pieces_to_parts`)
#:   unservable_span       no span on the served Ideal Text holds its words
UNSERVABLE_PARAGRAPH = "unservable_paragraph"
UNSERVABLE_SPAN = "unservable_span"


class Unservable(NamedTuple):
    """Why one candidate cannot be served, in the two forms its readers use.

    ``reason`` is the typed exclusion the frame records; ``detail`` is the
    exact failed condition the serve path logs (`detail=` in `_decline`),
    unchanged from the strings that log has always carried."""

    reason: str
    detail: str


def span_rejection(span: dict, text: str, *, prefix: str) -> Optional[str]:
    """A ``{start, end}`` span that is not integer, not forward, or runs
    past ``text``; ``prefix`` names which document ("" or "served_").

    The one span check of the V3 serve path, used for the transcript span
    there and for the served span here."""
    start, end = span.get("start"), span.get("end")
    if not isinstance(start, int) or not isinstance(end, int):
        return f"{prefix}span_bounds_not_integers"
    if start < 0 or end <= start:
        return f"{prefix}span_inverted:{start}..{end}"
    if end > len(text):
        return f"{prefix}span_past_document_end:{end}>{len(text)}"
    return None


def unservable(part_id: Any, target_span: Any,
               served_text: Any) -> Optional[Unservable]:
    """THE servability predicate: None when the serve path can prove this
    Confident Voice candidate, else why it cannot.

    Two proofs, checked in the order the serve path has always checked them:

      1. Its Paragraph. ``part_id`` is the binding's answer for the piece
         (slide first, span to refine, never a guess). No Paragraph is an
         item attached to nothing: ``source_ideal_part_id`` is required.
      2. Its served span, which is not the span measured. ``document_span``
         locates the spoken words in the TRANSCRIPT; ``target_span`` is where
         the bookmark is drawn, on the SERVED Ideal Text. Two documents, two
         spans; conflating them once put V3's highlight past the end of the
         served text in production, and silently on the wrong words whenever
         it happened to fit.

    Called by servable selection (`_winner`) with the frame's own candidate
    and piece, and by the serve path (`take_feedback_policy_v3_service.
    _row_rejection`) with the same candidate row and the same piece off the
    same document. One rule, so the item a block selects is an item the
    serve path will prove. It never stretches a span or guesses a Paragraph
    to make a candidate pass (L2): what cannot be proven is excluded.
    """
    if not part_id:
        return Unservable(UNSERVABLE_PARAGRAPH, "piece_has_no_part_id")
    if not isinstance(target_span, dict):
        return Unservable(UNSERVABLE_SPAN, "piece_has_no_served_span")
    text = served_text if isinstance(served_text, str) else ""
    detail = span_rejection(target_span, text, prefix="served_")
    return Unservable(UNSERVABLE_SPAN, detail) if detail else None


class _Servability(NamedTuple):
    """What servable selection reads: the served Ideal Text a bookmark is
    drawn on, and this Take's already frozen selection (by candidate id)."""

    served_text: Any
    frozen_ids: frozenset


def _servability(select_servable: bool, served_text: Any,
                 frozen_candidate_ids: Any) -> Optional[_Servability]:
    """None selects by rank alone, as the dark frame always has."""
    if not select_servable:
        return None
    return _Servability(served_text, frozenset(
        str(value) for value in (frozen_candidate_ids or ())))


def _winner(
    ranked: list[tuple[dict, dict]], servability: Optional[_Servability],
) -> tuple[Optional[dict], list[tuple[dict, str]]]:
    """The block's selected candidate, and the candidates passed over for it.

    ``ranked`` is the block's lineage-eligible ``(candidate, piece)`` pairs,
    best first (`_confidence_rank`). Without ``servability`` the winner is
    the first, exactly the rule the frame has always had.

    With it, the winner is the best-ranked candidate the serve path can
    prove (`unservable`). WHEN THE BEST IS PROVABLE, NOTHING CHANGES: it is
    the first pair asked, it wins, and nothing is passed over. Every
    unprovable candidate ranked above the winner is passed over with its
    typed reason, never dropped in silence; candidates below the winner were
    never in contention and are not re-judged. When nothing is provable the
    block is empty and every eligible candidate carries its reason. Nothing
    is stretched or invented to fill it: 24c/24d make coverage a target,
    never a floor.

    A FROZEN TAKE DOES NOT GROW. On a Take whose selection is already frozen
    (`take_feedback_set`, insert-once per Take), a fallback the freeze does
    not hold is not taken, and the block keeps the choice it was frozen
    with, which the serve path drops exactly as before. Taking it would
    gain the speaker nothing: the frozen set filters every row it does not
    name out of the page. And it would cost the Take its lineage: the fresh
    candidate set would no longer be the one the membership for this Ideal
    Text snapshot was frozen from (one membership per Take and snapshot),
    so the freeze would be refused and every row served without the
    `feedback_membership_id` its answers' canonical record needs (L3). A
    fallback chosen before the freeze is in the frozen set, so it is chosen
    again on every later read.
    """
    if servability is None:
        return (ranked[0][0] if ranked else None), []
    passed_over: list[tuple[dict, str]] = []
    for candidate, piece in ranked:
        verdict = unservable(piece.get("part_id"), candidate.get("target_span"),
                             servability.served_text)
        if verdict is not None:
            passed_over.append((candidate, verdict.reason))
            continue
        if (passed_over and servability.frozen_ids
                and candidate["candidate_id"] not in servability.frozen_ids):
            return ranked[0][0], []
        return candidate, passed_over
    return None, passed_over


def _select_in_block(block: dict, candidates: list[dict], pieces: list[dict],
                     servability: Optional[_Servability]) -> Optional[dict]:
    """Write the block's candidates and its one selected item (24b: at most
    one Confident Voice item per valid block); return the item.

    ``candidates`` are built from ``pieces`` one for one, in order. `sorted`
    is stable, so the first of the ranking is exactly the item `min` chose
    before servability was part of selection."""
    ranked = sorted(
        (pair for pair in zip(candidates, pieces)
         if pair[0]["eligibility"] == "eligible"),
        key=lambda pair: _confidence_rank(pair[0]),
    )
    selected, passed_over = _winner(ranked, servability)
    for row, reason in passed_over:
        row["eligibility"] = "excluded"
        row["exclusion_reason"] = reason
    block["confidence_candidates"] = candidates
    block["selected_candidate_id"] = (
        selected["candidate_id"] if selected else None
    )
    # An empty block names why: the typed reason of its best candidate when
    # none could be proven, otherwise that no clip had exact lineage.
    block["selection_reason"] = (
        selected["selection_language"] if selected
        else passed_over[0][1] if passed_over
        else "no_exact_clip_lineage_candidate"
    )
    return selected


def _select_confidence(
    blocks: list[dict], exclusions: list[dict], *, snippet_map: dict,
    suggestion_map: dict, take_id: str, recording_id: str,
    servability: Optional[_Servability],
) -> list[dict]:
    """Every block's Confident Voice inventory and selection, and the Take's
    selected ``{block_id, candidate_id}`` rows; each excluded clip is also
    named in ``exclusions``.

    Lifted out of `build_shadow_frame` (grandfathered at the complexity
    ratchet, which only lets it come down) unchanged, apart from the winner
    now being asked of `_winner`."""
    selections: list[dict] = []
    for block in blocks:
        pieces = block.pop("pieces")
        candidates = [
            _confidence_candidate(
                piece,
                snippet_map.get(piece["snippet_id"], {}),
                suggestion_map.get(piece["snippet_id"], {}),
                expected_take_id=take_id,
                expected_recording_id=recording_id,
            )
            for piece in pieces
        ]
        selected = _select_in_block(block, candidates, pieces, servability)
        if selected:
            selections.append({
                "block_id": block["block_id"],
                "candidate_id": selected["candidate_id"],
            })
        for row in candidates:
            if row["eligibility"] == "excluded":
                exclusions.append({
                    "candidate_kind": "confidence_clip",
                    "snippet_id": row["snippet_id"],
                    "reason": row["exclusion_reason"],
                    "block_id": block["block_id"],
                })
    return selections


def _owner_declined(row: dict, candidate_id: str, declined: Any) -> bool:
    """A rewrite the speaker declined on an earlier Take, on a Paragraph
    whose words have not changed since (N48.2, Q3 A;
    `services.rewrite_declines`). `declined` carries the standing keys, the
    candidates already in this Take's frozen selection (never taken back)
    and the Paragraph each snippet sits in."""
    from services.rewrite_declines import rewrite_key

    if not isinstance(declined, dict) or not declined.get("keys"):
        return False
    if candidate_id in (declined.get("frozen_ids") or ()):
        return False
    part_of = declined.get("part_of") or {}
    key = rewrite_key(part_of.get(str(row.get("snippet_id") or "")),
                      row.get("quote"), row.get("proposed_text"))
    return key is not None and key in declined["keys"]


def _with_owner_decline(reason: Optional[str], family: str, row: dict,
                        candidate_id: str, declined: Any) -> Optional[str]:
    """`reason` unchanged, or ``declined_by_owner`` for an otherwise
    eligible rewrite the owner declined (N48.2, Q3 A)."""
    from services.rewrite_declines import DECLINED_BY_OWNER

    if (reason is None and family == "rewrite_clarity"
            and _owner_declined(row, candidate_id, declined)):
        return DECLINED_BY_OWNER
    return reason


def _verbal_inventory(
    candidates: Iterable[Any],
    family: str,
    *,
    document_map: TakeDocumentMap,
    declined: Any = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Every row of one verbal family, eligible or excluded with its reason.

    Eligibility is `verbal_exclusion` (take_feedback_manager), the one rule
    `ensure_required_families` also decides fallbacks by (N48.1, Wave 1, E1).
    `document_span` is the row's words in THIS Take's transcript document --
    the coordinates the blocks are cut in -- and `target_span` is the same
    words in the served Ideal Text, where the row is drawn. Comparing the
    served span with block offsets anchored notes to the wrong block.

    A rewrite the owner declined while its Paragraph had these same words
    is excluded as ``declined_by_owner`` (N48.2, Q3 A): kept in the
    inventory with its reason, never served, never replaced by anything
    the block does not already hold.
    """
    ranked: list[tuple[tuple, dict]] = []
    inventory: list[dict] = []
    exclusions: list[dict] = []
    for input_index, raw in enumerate(candidates or []):
        row = raw if isinstance(raw, dict) else {}
        if row.get("feedback_family") != family:
            continue
        candidate_id = str(row.get("id") or "")
        snippet_id = str(row.get("snippet_id") or "")
        resolved_take = str(row.get("take_session_id") or "") or (
            document_map.snippet_take(snippet_id) or "")
        raw_span = row.get("span")
        span: dict = raw_span if isinstance(raw_span, dict) else {}
        start, end = _integer(span.get("start")), _integer(span.get("end"))
        versions = _versions(row)
        evidence = verbal_evidence(row)
        reason, mapped = verbal_exclusion(row, document_map)
        reason = _with_owner_decline(reason, family, row, candidate_id, declined)

        item = {
            "input_index": input_index,
            "candidate_id": candidate_id or None,
            "feedback_family": family,
            "snippet_id": snippet_id or None,
            "take_id": resolved_take or None,
            "document_span": (
                {"start": mapped[0], "end": mapped[1]}
                if mapped is not None else None
            ),
            "target_span": (
                {"start": start, "end": end}
                if start is not None and end is not None else None
            ),
            "evidence": evidence,
            "producer_versions": versions,
            "tentative": bool(row.get("tentative")),
            "eligibility": "excluded" if reason else "eligible",
            "exclusion_reason": reason,
        }
        inventory.append(item)
        if reason or mapped is None:
            exclusions.append({
                "candidate_kind": "verbal_feedback",
                "feedback_family": family,
                "candidate_id": candidate_id or None,
                "input_index": input_index,
                "reason": reason,
            })
            continue

        changed = int(bool(
            row.get("proposed_text")
            and str(row.get("proposed_text")).strip()
            != str(row.get("quote") or "").strip()
        ))
        specificity = int(evidence.get("specificity") or 0)
        supported = 0 if evidence.get("fallback") else 1
        cue_count = len(row.get("cue_keys") or [])
        quality = (
            (changed, specificity, supported)
            if family == "rewrite_clarity"
            else (cue_count, specificity, supported)
        )
        rank = tuple(-int(value) for value in quality) + (
            mapped[0], mapped[1], candidate_id,
        )
        ranked.append((rank, item))

    ranked.sort(key=lambda value: value[0])
    # Return the whole ranking, not just the winner. Neither lane is a single
    # global pick: each anchors one note per block by the block's read
    # (contract 24f), so the caller has to ask "best candidate INSIDE this
    # block", which the winner alone cannot answer.
    return inventory, [item for _, item in ranked], exclusions


def _document_map(
    doc: dict, *, take_id: str, document_text: str, served_text: Any,
    snippet_map: dict[str, dict],
) -> TakeDocumentMap:
    """This Take's served-to-transcript map. Snippet lineage comes from the
    Take's own snippet rows, exactly as the confidence lane reads it."""
    return TakeDocumentMap(
        take_id=take_id,
        document_text=document_text,
        served_text=served_text,
        pieces=doc.get("pieces"),
        snippet_takes={
            snippet_id: str(row.get("session_id") or "")
            for snippet_id, row in snippet_map.items()
        },
    )


def _declined_context(declined_rewrites: Any, frozen_candidate_ids: Any,
                      pieces: Any) -> dict:
    """What `_owner_declined` reads (N48.2, Q3 A)."""
    return {
        "keys": frozenset(declined_rewrites or ()),
        "frozen_ids": frozenset(
            str(value) for value in (frozen_candidate_ids or ())),
        "part_of": _snippet_parts(pieces),
    }


def _snippet_parts(pieces: Any) -> dict[str, str]:
    """{snippet_id: part_id} for the pieces bound to a Paragraph
    (`ideal_text_parts.bind_pieces_to_parts`): the Paragraph a verbal row
    sits in, the same join the service inventory names it by."""
    return {
        str(piece.get("snippet_id")): str(piece.get("part_id"))
        for piece in pieces or []
        if isinstance(piece, dict) and piece.get("snippet_id")
        and piece.get("part_id")
    }


def _unrouted_inventory(candidates: Iterable[Any]) -> list[dict]:
    out: list[dict] = []
    for input_index, raw in enumerate(candidates or []):
        row = raw if isinstance(raw, dict) else {}
        family = str(row.get("feedback_family") or "")
        if family in _VERBAL_FAMILIES:
            continue
        out.append({
            "candidate_kind": "manager_feedback",
            "candidate_id": str(row.get("id") or "") or None,
            "feedback_family": family or None,
            "input_index": input_index,
            "reason": (
                "confidence_inventory_rebuilt_from_exact_clips"
                if family == "confident_voice"
                else "unsupported_feedback_family"
            ),
        })
    return out


def build_shadow_frame(
    *,
    take_document: Any,
    snippets: Any,
    suggestions: Any,
    feedback_candidates: Iterable[Any],
    take_index: Any,
    expected_recording_id: Any,
    served_text: Any = None,
    declined_rewrites: Any = frozenset(),
    frozen_candidate_ids: Any = frozenset(),
    select_servable: bool = False,
) -> Optional[dict]:
    """Build the complete v3 frame; return None for an unusable Take.

    ``served_text`` is the Ideal Text the verbal rows' spans address. Without
    it no verbal row can be proven to sit in this Take's words, so every one
    is excluded as ``document_span_unmapped`` (N48.1, Wave 1).

    ``declined_rewrites`` are the standing "Keep my words" keys
    (`services.rewrite_declines.standing_declines`); a matching rewrite is
    excluded as ``declined_by_owner`` unless its id is in
    ``frozen_candidate_ids``, this Take's already frozen selection (N48.2,
    Q3 A).

    ``select_servable`` makes the serve path's proof part of selection
    (contract 24b; `_winner`): each block's item is its best-ranked
    candidate whose Paragraph and served span can be proven against
    ``served_text``. Only the service frame sets it
    (`build_service_candidate_frame`), whose document the live path binds
    to Paragraphs first (`ideal_text_changes._ask_v3`,
    `ideal_text_parts.bind_pieces_to_parts`). The dark frame's document is
    never bound, so judged there every clip would be unprovable; it keeps
    selecting by rank alone, unchanged.
    """
    doc = take_document if isinstance(take_document, dict) else {}
    take_id = str(doc.get("take_session_id") or "")
    recording_id = str(expected_recording_id or "")
    raw_document_text = doc.get("text")
    document_text: str = (
        raw_document_text if isinstance(raw_document_text, str) else ""
    )
    if (
        not take_id
        or not recording_id
        or isinstance(take_index, bool)
        or not isinstance(take_index, int)
        or take_index < 1
    ):
        return None
    blocks, exclusions = _semantic_blocks(doc.get("pieces"))
    if not blocks:
        return None
    snippet_map = {
        str(row.get("id")): row
        for row in (snippets or []) if isinstance(row, dict) and row.get("id")
    }
    suggestion_map = suggestions if isinstance(suggestions, dict) else {}
    confidence_selections = _select_confidence(
        blocks, exclusions, snippet_map=snippet_map,
        suggestion_map=suggestion_map, take_id=take_id,
        recording_id=recording_id,
        servability=_servability(
            select_servable, served_text, frozen_candidate_ids),
    )

    # THE ONLY PLACE THE REASON LAYER IS OBSERVABLE (24j). Everything else it
    # does is internal ordering that leaves no trace: the failure it can have
    # is quiet, not loud. One aggregate line per Take, counts only, computed
    # by a function that cannot raise — a log line is never worth a failed
    # Take (live loop).
    logger.info("reason layer take=%s %s", take_id, selection_summary(blocks))

    coverage = _slide_coverage(blocks, take_index)
    _practice_routing(blocks)

    feedback_rows = list(feedback_candidates or [])
    document_map = _document_map(
        doc, take_id=take_id, document_text=document_text,
        served_text=served_text, snippet_map=snippet_map,
    )
    rewrite_inventory, rewrite_ranked, rewrite_exclusions = _verbal_inventory(
        feedback_rows, "rewrite_clarity", document_map=document_map,
        declined=_declined_context(
            declined_rewrites, frozen_candidate_ids, doc.get("pieces")),
    )
    praise_inventory, praise_ranked, praise_exclusions = _verbal_inventory(
        feedback_rows, "great_formulation", document_map=document_map,
    )
    exclusions.extend(rewrite_exclusions)
    exclusions.extend(praise_exclusions)
    exclusions.extend(_unrouted_inventory(feedback_rows))

    # BOTH LANES RUN ON TAKE 1 (contract 24b, founder 2026-09-18). The
    # `take_index >= 2` gate is gone: it made the first take the one take whose
    # bookmarks lead nowhere, which is the worst place in the product to have
    # that happen.
    #
    # ONE NOTE PER BLOCK, BY THE READ (contract 24f, founder 2026-09-29). The
    # caps — two praise on the two most Confident blocks, one rewrite for the
    # whole Take — are lifted: praise anchors to every block read confident
    # and the rewrite to every block read weak, each only where a defensible
    # candidate sits inside the block. The green mark stays on the top two
    # (24g); it no longer decides where praise goes.
    _mark_top_confidence(blocks, MOST_CONFIDENT_LIMIT)
    weak_blocks = _blocks_read(blocks, confident=False)
    rewrite_anchors = _anchored_notes(rewrite_ranked, weak_blocks)
    praise_anchors = _anchored_notes(
        praise_ranked, _blocks_read(blocks, confident=True))
    rewrite_selected_ids = [row["candidate_id"] for row in rewrite_anchors]
    praise_selected_ids = [row["candidate_id"] for row in praise_anchors]
    _log_verbal_lanes(take_id, rewrite_ranked, rewrite_selected_ids,
                      praise_ranked, praise_selected_ids,
                      weak_blocks=len(weak_blocks))
    # The lanes list only rows with an id (V4 B1.1, 0441): an id-less row
    # is already excluded and kept in `exclusions` with its reason.
    rewrite_candidates = _identified(rewrite_inventory)
    praise_candidates = _identified(praise_inventory)

    generator_versions = sorted({
        version
        for lane in (rewrite_inventory, praise_inventory)
        for item in lane
        for version in item["producer_versions"].values()
        if version
    } | {
        version
        for suggestion in suggestion_map.values()
        for version in _versions(suggestion).values()
        if version
    })
    frame = {
        "policy_version": POLICY_VERSION,
        "frame_schema_version": FRAME_SCHEMA_VERSION,
        "take_id": take_id,
        "recording_id": recording_id,
        "take_index": take_index,
        "implementation_versions": {
            "confidence_detector_version": CONFIDENCE_DETECTOR_VERSION,
            "acoustic_feature_schema_version": FEATURE_SCHEMA_VERSION,
            "suggestion_generator_contract_version": (
                SUGGESTION_GENERATOR_CONTRACT_VERSION
            ),
            "observed_suggestion_generator_versions": generator_versions,
            "manager_rules_version": MANAGER_RULES_VERSION,
            "manager_evidence_schema_version": MANAGER_EVIDENCE_SCHEMA_VERSION,
            "source_code_sha256": _source_code_sha256(),
            "deployment_commit": config.CODE_COMMIT_SHA or None,
        },
        "block_policy": {
            "unit": "slide_bounded_semantic_speech_block",
            "target_words": TARGET_WORDS,
            "normal_min_words": MIN_WORDS,
            "normal_max_words": MAX_WORDS,
            "split_only_at_exact_snippet_boundaries": True,
        },
        "practice_policy": {
            "threshold": "below_neutral_delivery_band",
            "prompt_bands": list(PRACTICE_BANDS),
            # 24f (founder 2026-09-29): an exercise on any bookmark the
            # machine reads weak, each matched to its own clip (35g-1).
            "exercise_budget": "one_per_block_read_weak",
            "exercise_target": "each_block_read_weak_own_clip",
        },
        "confidence_definition": {
            "scope": "relative_within_block",
            "winner": "highest_ranked_exact_lineage_candidate",
            "absolute_confidence_threshold_required": False,
            "missing_or_weak_evidence_language": "tentative",
        },
        "coverage": coverage,
        "blocks": blocks,
        "selected_confidence": confidence_selections,
        "verbal_lanes": {
            "enabled": True,
            "rewrite_clarity": {
                "selection_scope": "anchored_to_blocks_read_weak",
                "budget": "one_per_block",
                "anchors": rewrite_anchors,
                "candidates": rewrite_candidates,
                "selected_candidate_ids": rewrite_selected_ids,
                **_lane_outcome(
                    rewrite_anchors, _blocks_read(blocks, confident=False)),
            },
            "great_formulation": {
                "selection_scope": "anchored_to_blocks_read_confident",
                "budget": "one_per_block",
                "anchors": praise_anchors,
                "candidates": praise_candidates,
                "selected_candidate_ids": praise_selected_ids,
                **_lane_outcome(
                    praise_anchors, _blocks_read(blocks, confident=True)),
            },
        },
        "excluded_candidates": exclusions,
        "pick_log": _pick_log(take_id, blocks, (
            ("rewrite_clarity", rewrite_candidates, rewrite_selected_ids),
            ("great_formulation", praise_candidates, praise_selected_ids),
        )),
        "exposure_semantics": {
            "shadow_computation_is_exposure": False,
            "delivery_is_exposure": False,
            "rendered_exposure_requires_authenticated_client_confirmation": True,
            "rendered_exposure_id": None,
        },
        "blindness": {
            "hidden_before_independent_judgment": [
                "machine_score",
                "machine_version",
                "suggestion_provenance",
                "selection_reason",
                "other_human_judgments",
            ],
        },
        "serves_user_feedback": False,
        "dataset_eligible": False,
    }
    encoded = json.dumps(
        frame, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return {**frame, "frame_hash": hashlib.sha256(encoded).hexdigest()}


def build_service_candidate_frame(**kwargs: Any) -> Optional[dict]:
    """Build a fresh service candidate calculation without recording exposure.

    The shared calculator preserves the accepted 75-word and Take budgets, but
    the returned identity is explicitly service preparation.  It is never read
    from, nor written to, the dark-frame table.

    Its selection is servable (contract 24b; `build_shadow_frame`'s
    ``select_servable``): this frame chooses what the serve path then
    proves, so it chooses only what the serve path can prove.
    """
    shadow = build_shadow_frame(**kwargs, select_servable=True)
    if shadow is None:
        return None
    frame = {
        **shadow,
        "policy_version": SERVICE_POLICY_VERSION,
        "frame_schema_version": "take-feedback-policy-v3-service-candidates-v1",
        "operation_mode": "allowlisted_service_preparation",
    }
    frame.pop("frame_hash", None)
    # The pick log is the dark frame's alone (V4 B1.1): the service frame
    # chooses what is served and must not carry a pick chance (AC-9).
    frame.pop("pick_log", None)
    encoded = json.dumps(
        frame, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return {**frame, "frame_hash": hashlib.sha256(encoded).hexdigest()}
