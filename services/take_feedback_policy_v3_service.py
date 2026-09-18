"""Pure adapter from an accepted V3 policy frame to service persistence.

This module does not authorize serving.  It converts one already-built V3
frame into the exact visible rows, complete canonical candidate inventory and
membership item inventory used by the database-authoritative service gate.
Human answers and coach judgments are deliberately absent from its inputs.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

_FAMILIES = {"confident_voice", "rewrite_clarity", "great_formulation"}


def _source_parts(document: dict) -> dict[str, dict]:
    return {
        str(row.get("snippet_id")): row
        for row in document.get("pieces") or []
        if isinstance(row, dict) and row.get("snippet_id")
    }


def _candidate_map(rows: Iterable[Any]) -> dict[tuple[str, str], dict]:
    return {
        (str(row.get("feedback_family") or ""), str(row.get("id") or "")): row
        for row in rows
        if isinstance(row, dict)
        and row.get("feedback_family") in _FAMILIES
        and row.get("id")
    }


def _valid_v3_policy_frame(frame: Any, take_document: Any) -> tuple | None:
    policy = frame if isinstance(frame, dict) else {}
    document = take_document if isinstance(take_document, dict) else {}
    document_text = document.get("text")
    if (
        policy.get("policy_version")
        != "take-feedback-policy-v3-serving-v1"
        or not isinstance(document_text, str)
        or not document_text
        or policy.get("take_id") != document.get("take_session_id")
    ):
        return None
    return policy, document, document_text


class _V3ServiceInventory:
    """Accumulator threaded through one inventory-preparation pass."""

    def __init__(self) -> None:
        self.candidates: list[dict] = []
        self.items: list[dict] = []
        self.selected: list[dict] = []
        self.visible: list[dict] = []
        self.selected_ids: set[tuple[str, str]] = set()
        self.position = 0


def _v3_confidence_candidate_row(
    raw: Any, *, block_id: str, block_position: int, slide_index: int,
    pieces: dict[str, dict], policy: dict, document_text: str,
    confidence_selected: dict[str, str], inventory: _V3ServiceInventory,
) -> bool:
    if not isinstance(raw, dict):
        return False
    candidate_key = str(raw.get("candidate_id") or "")
    snippet_id = str(raw.get("snippet_id") or "")
    source = pieces.get(snippet_id)
    span = raw.get("document_span")
    lineage = raw.get("clip_identity")
    if (
        not candidate_key or not source
        or not isinstance(span, dict)
        or not isinstance(lineage, dict)
        or raw.get("eligibility") not in {"eligible", "excluded"}
    ):
        return False
    start, end = span.get("start"), span.get("end")
    if (
        not isinstance(start, int) or not isinstance(end, int)
        or start < 0 or end <= start or end > len(document_text)
        or str(source.get("recording_id") or "")
        != str(lineage.get("recording_id") or "")
        or source.get("start_offset_ms") != lineage.get("start_offset_ms")
        or source.get("duration_ms") != lineage.get("duration_ms")
        or not source.get("part_id")
    ):
        return False
    is_selected = candidate_key in confidence_selected
    if is_selected:
        inventory.position += 1
        inventory.selected_ids.add(("confident_voice", candidate_key))
    row = {
        "id": candidate_key,
        "kind": "bold",
        "source": "confident_voice",
        "feedback_family": "confident_voice",
        "snippet_id": snippet_id,
        "take_session_id": policy["take_id"],
        "span": {"start": start, "end": end},
        "quote": document_text[start:end],
        "proposed_text": None,
        "why_key": "confident_voice",
        "tentative": raw.get("selection_language")
        == "best_available_tentative",
        "candidate_score": raw.get("machine_score"),
        "detector_version": raw.get("machine_version"),
        "rule_version": policy.get("policy_version"),
        "_manager_evidence": {
            "basis": "relative_best_within_v3_block",
            "block_id": block_id,
            "selection_language": raw.get("selection_language"),
            "fallback": False,
            "specificity": 1,
        },
    }
    inventory.candidates.append(row)
    if is_selected:
        inventory.selected.append({
            "id": candidate_key,
            "feedback_family": "confident_voice",
            "block_id": block_id,
        })
        inventory.visible.append(dict(row))
    inventory.items.append({
        "candidate_key": candidate_key,
        "feedback_family": "confident_voice",
        "slide_index": slide_index,
        "block_key": block_position,
        "source_ideal_part_id": str(source["part_id"]),
        "snippet_id": snippet_id,
        "eligibility": raw["eligibility"],
        "exclusion_reason": raw.get("exclusion_reason"),
        "selected": is_selected,
        "position_shown": inventory.position if is_selected else None,
    })
    return True


def _v3_confidence_block(
    block: Any, block_position: int, *, pieces: dict[str, dict],
    policy: dict, document_text: str, confidence_selected: dict[str, str],
    inventory: _V3ServiceInventory,
) -> bool:
    if not isinstance(block, dict):
        return False
    block_id = str(block.get("block_id") or "")
    slide_index = block.get("slide_index")
    if not block_id or not isinstance(slide_index, int):
        return False
    for raw in block.get("confidence_candidates") or []:
        if not _v3_confidence_candidate_row(
            raw, block_id=block_id, block_position=block_position,
            slide_index=slide_index, pieces=pieces, policy=policy,
            document_text=document_text,
            confidence_selected=confidence_selected, inventory=inventory,
        ):
            return False
    return True


def _v3_snippet_block_index(blocks: list[Any]) -> dict[str, tuple[int, int]]:
    snippet_block: dict[str, tuple[int, int]] = {}
    for block_position, block in enumerate(blocks, 1):
        for snippet_id in block.get("snippet_ids") or []:
            snippet_block[str(snippet_id)] = (
                block_position, int(block.get("slide_index")),
            )
    return snippet_block


def _v3_verbal_candidate_row(
    row_input: Any, *, family: str, lane_selected: frozenset[str],
    raw_by_identity: dict[tuple[str, str], dict],
    pieces: dict[str, dict], snippet_block: dict[str, tuple[int, int]],
    inventory: _V3ServiceInventory,
) -> bool:
    if not isinstance(row_input, dict):
        return False
    candidate_key = str(row_input.get("candidate_id") or "")
    raw = raw_by_identity.get((family, candidate_key))
    snippet_id = str(row_input.get("snippet_id") or "")
    source = pieces.get(snippet_id)
    block_identity = snippet_block.get(snippet_id)
    if (
        not candidate_key or raw is None or source is None
        or block_identity is None or not source.get("part_id")
        or row_input.get("eligibility") not in {"eligible", "excluded"}
    ):
        return False
    is_selected = candidate_key in lane_selected
    if is_selected:
        inventory.position += 1
        inventory.selected_ids.add((family, candidate_key))
    copied = dict(raw)
    copied["feedback_family"] = family
    inventory.candidates.append(copied)
    if is_selected:
        inventory.selected.append({"id": candidate_key, "feedback_family": family})
        inventory.visible.append(dict(copied))
    inventory.items.append({
        "candidate_key": candidate_key,
        "feedback_family": family,
        "slide_index": block_identity[1],
        "block_key": block_identity[0],
        "source_ideal_part_id": str(source["part_id"]),
        "snippet_id": snippet_id,
        "eligibility": row_input["eligibility"],
        "exclusion_reason": row_input.get("exclusion_reason"),
        "selected": is_selected,
        "position_shown": inventory.position if is_selected else None,
    })
    return True


def _v3_verbal_lane(
    lane: Any, *, family: str, raw_by_identity: dict[tuple[str, str], dict],
    pieces: dict[str, dict], snippet_block: dict[str, tuple[int, int]],
    inventory: _V3ServiceInventory,
) -> bool:
    if not isinstance(lane, dict):
        return False
    # A SET, NOT A STRING (contract 24f). Praise anchors to the Take's two
    # most Confident Voice blocks, so this lane can carry two winners; a
    # string comparison would have silently marked only the first as selected
    # and dropped the second on the floor with no error anywhere.
    lane_selected = frozenset(
        str(value) for value in (lane.get("selected_candidate_ids") or [])
        if str(value or "")
    )
    for row_input in lane.get("candidates") or []:
        if not _v3_verbal_candidate_row(
            row_input, family=family, lane_selected=lane_selected,
            raw_by_identity=raw_by_identity, pieces=pieces,
            snippet_block=snippet_block, inventory=inventory,
        ):
            return False
    return True


def _v3_inventory_is_complete(inventory: _V3ServiceInventory) -> bool:
    if not inventory.selected or not any(
        row.get("feedback_family") == "confident_voice"
        for row in inventory.selected
    ):
        return False
    if len(inventory.candidates) != len(inventory.items) or len({
        (row["feedback_family"], row["candidate_key"])
        for row in inventory.items
    }) != len(inventory.items):
        return False
    return True


def prepare_v3_service_inventory(
    *, frame: Any, take_document: Any, feedback_candidates: Iterable[Any],
) -> dict | None:
    """Return a fail-closed V3 service inventory or ``None``.

    Service preparation requires exact lineage for every candidate considered.
    An excluded detector version remains a typed inventory row, but malformed
    clip/Paragraph lineage blocks the whole service freeze rather than hiding
    the invalid item inside an exclusion.
    """
    frame_data = _valid_v3_policy_frame(frame, take_document)
    if frame_data is None:
        return None
    policy, document, document_text = frame_data
    pieces = _source_parts(document)
    raw_by_identity = _candidate_map(feedback_candidates)
    inventory = _V3ServiceInventory()
    confidence_selected = {
        str(row.get("candidate_id")): str(row.get("block_id"))
        for row in policy.get("selected_confidence") or []
        if isinstance(row, dict) and row.get("candidate_id") and row.get("block_id")
    }
    blocks = policy.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        return None

    for block_position, block in enumerate(blocks, 1):
        if not _v3_confidence_block(
            block, block_position, pieces=pieces, policy=policy,
            document_text=document_text, confidence_selected=confidence_selected,
            inventory=inventory,
        ):
            return None

    verbal = policy.get("verbal_lanes")
    if not isinstance(verbal, dict):
        return None
    snippet_block = _v3_snippet_block_index(blocks)
    for family in ("rewrite_clarity", "great_formulation"):
        if not _v3_verbal_lane(
            verbal.get(family), family=family, raw_by_identity=raw_by_identity,
            pieces=pieces, snippet_block=snippet_block, inventory=inventory,
        ):
            return None

    if not _v3_inventory_is_complete(inventory):
        return None
    return {
        "candidates": inventory.candidates,
        "selected_keys": inventory.selected,
        "membership_items": inventory.items,
        "visible_rows": sorted(
            inventory.visible,
            key=lambda row: (
                int((row.get("span") or {}).get("start") or 0),
                str(row.get("id") or ""),
            ),
        ),
        "block_partition_version": "slide-run-75-word-partition-v1",
    }
