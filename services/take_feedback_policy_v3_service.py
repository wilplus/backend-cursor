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


def prepare_v3_service_inventory(
    *, frame: Any, take_document: Any, feedback_candidates: Iterable[Any],
) -> dict | None:
    """Return a fail-closed V3 service inventory or ``None``.

    Service preparation requires exact lineage for every candidate considered.
    An excluded detector version remains a typed inventory row, but malformed
    clip/Paragraph lineage blocks the whole service freeze rather than hiding
    the invalid item inside an exclusion.
    """
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
    pieces = _source_parts(document)
    raw_by_identity = _candidate_map(feedback_candidates)
    candidates: list[dict] = []
    items: list[dict] = []
    selected: list[dict] = []
    visible: list[dict] = []
    selected_ids: set[tuple[str, str]] = set()
    confidence_selected = {
        str(row.get("candidate_id")): str(row.get("block_id"))
        for row in policy.get("selected_confidence") or []
        if isinstance(row, dict) and row.get("candidate_id") and row.get("block_id")
    }
    blocks = policy.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        return None

    position = 0
    for block_position, block in enumerate(blocks, 1):
        if not isinstance(block, dict):
            return None
        block_id = str(block.get("block_id") or "")
        slide_index = block.get("slide_index")
        if not block_id or not isinstance(slide_index, int):
            return None
        for raw in block.get("confidence_candidates") or []:
            if not isinstance(raw, dict):
                return None
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
                return None
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
                return None
            is_selected = candidate_key in confidence_selected
            if is_selected:
                position += 1
                selected_ids.add(("confident_voice", candidate_key))
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
            candidates.append(row)
            if is_selected:
                selected.append({
                    "id": candidate_key,
                    "feedback_family": "confident_voice",
                    "block_id": block_id,
                })
                visible.append(dict(row))
            items.append({
                "candidate_key": candidate_key,
                "feedback_family": "confident_voice",
                "slide_index": slide_index,
                "block_key": block_position,
                "source_ideal_part_id": str(source["part_id"]),
                "snippet_id": snippet_id,
                "eligibility": raw["eligibility"],
                "exclusion_reason": raw.get("exclusion_reason"),
                "selected": is_selected,
                "position_shown": position if is_selected else None,
            })

    verbal = policy.get("verbal_lanes")
    if not isinstance(verbal, dict):
        return None
    snippet_block: dict[str, tuple[int, int]] = {}
    for block_position, block in enumerate(blocks, 1):
        for snippet_id in block.get("snippet_ids") or []:
            snippet_block[str(snippet_id)] = (
                block_position, int(block.get("slide_index")),
            )
    for family in ("rewrite_clarity", "great_formulation"):
        lane = verbal.get(family)
        if not isinstance(lane, dict):
            return None
        lane_selected = str(lane.get("selected_candidate_id") or "")
        for inventory in lane.get("candidates") or []:
            if not isinstance(inventory, dict):
                return None
            candidate_key = str(inventory.get("candidate_id") or "")
            raw = raw_by_identity.get((family, candidate_key))
            snippet_id = str(inventory.get("snippet_id") or "")
            source = pieces.get(snippet_id)
            block_identity = snippet_block.get(snippet_id)
            if (
                not candidate_key or raw is None or source is None
                or block_identity is None or not source.get("part_id")
                or inventory.get("eligibility") not in {"eligible", "excluded"}
            ):
                return None
            is_selected = bool(lane_selected and candidate_key == lane_selected)
            if is_selected:
                position += 1
                selected_ids.add((family, candidate_key))
            copied = dict(raw)
            copied["feedback_family"] = family
            candidates.append(copied)
            if is_selected:
                selected.append({"id": candidate_key, "feedback_family": family})
                visible.append(dict(copied))
            items.append({
                "candidate_key": candidate_key,
                "feedback_family": family,
                "slide_index": block_identity[1],
                "block_key": block_identity[0],
                "source_ideal_part_id": str(source["part_id"]),
                "snippet_id": snippet_id,
                "eligibility": inventory["eligibility"],
                "exclusion_reason": inventory.get("exclusion_reason"),
                "selected": is_selected,
                "position_shown": position if is_selected else None,
            })

    if not selected or not any(
        row.get("feedback_family") == "confident_voice" for row in selected
    ):
        return None
    if len(candidates) != len(items) or len({
        (row["feedback_family"], row["candidate_key"]) for row in items
    }) != len(items):
        return None
    return {
        "candidates": candidates,
        "selected_keys": selected,
        "membership_items": items,
        "visible_rows": sorted(
            visible,
            key=lambda row: (
                int((row.get("span") or {}).get("start") or 0),
                str(row.get("id") or ""),
            ),
        ),
        "block_partition_version": "slide-run-75-word-partition-v1",
    }
