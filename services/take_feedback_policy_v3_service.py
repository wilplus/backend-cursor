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


def _block_presentation(block: dict, block_id: str) -> dict:
    """What the client is allowed to know about how to DRAW this block.

    THE LADDER WAS COMPUTED AND THEN THROWN AWAY (founder 2026-09-18: "there
    are no green bookmarks... none of that actually landed"). `_practice_routing`
    and `_mark_top_confidence` already decide, per block, which item carries the
    exercise, which two are the Take's most confident, and which prompt practice
    — and every one of those decisions stayed on the internal frame. The row the
    browser received had no tier at all, so every bookmark could only render the
    same colour and contract 24g was unbuildable.

    AC-9 IS WHY THIS IS A TRANSLATION AND NOT A PASS-THROUGH.
    `voice_confidence.band()` warns in its own docstring that the band IS a
    verdict and must never reach a user payload, so `delivery_band` stays on the
    frame and does not appear here. What crosses is a tier NAME and one boolean:
    the client is told which bookmark to draw and that practice is offered,
    never how it was scored, where it ranked, or how it compares.

    `most_confident` deliberately carries no position. First and second are
    identical green (24g) because a visible ordering is a surfaced ranking.
    """
    tier = (
        "exercise" if block.get("carries_exercise")
        else "most_confident" if block.get("most_confident")
        else "standard"
    )
    return {
        "block_id": block_id,
        "bookmark_tier": tier,
        # "Let's practice" with no exercise attached — contract 24f: an exercise
        # is work the user must go and do, and a list of them is a list nobody
        # starts, so only the weakest below-neutral item carries one.
        "practice_prompt": bool(block.get("practice_prompt")),
    }


def _presentable(row: dict, presentation: dict) -> dict:
    """The visible copy of a candidate row: how to draw it, minus the score.

    `candidate_score` is the detector's raw machine number. It belongs in the
    canonical bundle, which is persisted evidence, and nowhere near a browser —
    AC-9 bans surfacing scores, and a number that is merely PRESENT in a payload
    is one render away from being surfaced by someone who assumes anything sent
    was meant to be shown. The canonical row keeps it; this copy does not.
    """
    visible = dict(row)
    visible.pop("candidate_score", None)
    visible.update(presentation)
    return visible


def _row_rejection(
    raw: dict, *, candidate_key: str, snippet_id: str, source: Any,
    span: Any, lineage: Any, document_text: str, served_text: str,
) -> str | None:
    """Which single condition rejects this candidate row, or None if none does.

    THE CONDITIONS WERE OR-ED INTO TWO `if`s (2026-09-19). Ten reasons shared
    two exits, both silent, and the caller collapsed all of them into one
    rejected block. `detail=confidence_block_rejected:1` located the block and
    then stopped being useful, which is the third time in one day that a typed
    reason has named a step instead of a condition.

    Split one per line so the log says which. The values carried are
    identifiers and millisecond offsets -- lineage, not content, and not a
    score. AC-9 is about what reaches a user; none of this does.
    """
    if not candidate_key:
        return "no_candidate_id"
    if source is None:
        return f"snippet_not_in_document:{snippet_id or '∅'}"
    if not isinstance(span, dict):
        return "document_span_missing"
    if not isinstance(lineage, dict):
        return "clip_identity_missing"
    if raw.get("eligibility") not in {"eligible", "excluded"}:
        return f"eligibility_unknown:{raw.get('eligibility')!r}"
    start, end = span.get("start"), span.get("end")
    if not isinstance(start, int) or not isinstance(end, int):
        return "span_bounds_not_integers"
    if start < 0 or end <= start:
        return f"span_inverted:{start}..{end}"
    if end > len(document_text):
        return f"span_past_document_end:{end}>{len(document_text)}"
    if str(source.get("recording_id") or "") != str(
        lineage.get("recording_id") or ""
    ):
        return (
            "recording_id_mismatch:"
            f"piece={source.get('recording_id')!r}"
            f",clip={lineage.get('recording_id')!r}"
        )
    if source.get("start_offset_ms") != lineage.get("start_offset_ms"):
        return (
            "start_offset_mismatch:"
            f"piece={source.get('start_offset_ms')!r}"
            f",clip={lineage.get('start_offset_ms')!r}"
        )
    if source.get("duration_ms") != lineage.get("duration_ms"):
        return (
            "duration_mismatch:"
            f"piece={source.get('duration_ms')!r}"
            f",clip={lineage.get('duration_ms')!r}"
        )
    if not source.get("part_id"):
        return "piece_has_no_part_id"
    # THE SPAN THE BOOKMARK IS DRAWN ON, which is not the one measured. The
    # checks above validate `document_span` against the TRANSCRIPT; these
    # validate `target_span` against the SERVED Ideal Text. Two documents,
    # two spans, and conflating them put V3's highlight at transcript
    # offsets inside a shorter document -- past its end in production, and
    # silently on the wrong words whenever it happened to fit.
    target = raw.get("target_span")
    if not isinstance(target, dict):
        return "piece_has_no_served_span"
    t_start, t_end = target.get("start"), target.get("end")
    if not isinstance(t_start, int) or not isinstance(t_end, int):
        return "served_span_bounds_not_integers"
    if t_start < 0 or t_end <= t_start:
        return f"served_span_inverted:{t_start}..{t_end}"
    if t_end > len(served_text):
        return f"served_span_past_document_end:{t_end}>{len(served_text)}"
    return None


def _v3_confidence_candidate_row(
    raw: Any, *, block_id: str, block_position: int, slide_index: int,
    pieces: dict[str, dict], policy: dict, document_text: str,
    served_text: str,
    confidence_selected: dict[str, str], inventory: _V3ServiceInventory,
    presentation: dict, detail: list[str] | None = None,
) -> bool:
    def closed(gate: str) -> None:
        if detail is not None:
            detail.append(gate)

    if not isinstance(raw, dict):
        closed("candidate_row_not_a_dict")
        return False
    candidate_key = str(raw.get("candidate_id") or "")
    snippet_id = str(raw.get("snippet_id") or "")
    source = pieces.get(snippet_id)
    span = raw.get("document_span")
    lineage = raw.get("clip_identity")
    rejection = _row_rejection(
        raw, candidate_key=candidate_key, snippet_id=snippet_id,
        source=source, span=span, lineage=lineage,
        document_text=document_text, served_text=served_text,
    )
    if rejection is not None:
        closed(rejection)
        return False
    # `_row_rejection` returning None has already proven both of these are
    # dicts -- that is most of what it checks. Re-stating it is how the proof
    # reaches the type checker, which cannot follow it across the call. Same
    # device `ideal_text_core_snapshot` uses for `provenance_rows`.
    assert isinstance(span, dict) and isinstance(source, dict)
    # THE SPAN THE CLIENT DRAWS ON IS NOT THE ONE MEASURED (2026-09-19).
    # `document_span` (validated above against the transcript) locates the
    # spoken words for the audio and transcript evidence. `span` and `quote`
    # below are consumed against the SERVED Ideal Text -- by the evidence
    # contract's target locator and by the client's highlight -- so they
    # come from `target_span`, which the relocation proved. Filling them
    # from the transcript put the bookmark on whatever words happened to sit
    # at those offsets in a shorter document, and usually past its end.
    assert isinstance(target := raw.get("target_span"), dict)
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
        "span": {"start": target["start"], "end": target["end"]},
        "quote": served_text[target["start"]:target["end"]],
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
        inventory.visible.append(_presentable(row, presentation))
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
    policy: dict, document_text: str, served_text: str,
    confidence_selected: dict[str, str],
    inventory: _V3ServiceInventory, detail: list[str] | None = None,
) -> bool:
    def closed(gate: str) -> None:
        if detail is not None:
            detail.append(gate)

    if not isinstance(block, dict):
        closed("block_not_a_dict")
        return False
    block_id = str(block.get("block_id") or "")
    slide_index = block.get("slide_index")
    if not block_id:
        closed("block_has_no_id")
        return False
    if not isinstance(slide_index, int):
        closed(f"block_slide_index_not_an_int:{slide_index!r}")
        return False
    presentation = _block_presentation(block, block_id)
    candidates = block.get("confidence_candidates") or []
    if not candidates:
        # Not itself a rejection -- an empty block passes below, exactly as it
        # did before -- but worth naming, because a partition that produced no
        # candidate at all is a different fault from one whose candidate was
        # malformed, and the two are indistinguishable downstream.
        closed(f"block_has_no_candidates:{block_id}")
    for row_position, raw in enumerate(candidates, 1):
        if not _v3_confidence_candidate_row(
            raw, block_id=block_id, block_position=block_position,
            slide_index=slide_index, pieces=pieces, policy=policy,
            document_text=document_text, served_text=served_text,
            confidence_selected=confidence_selected, inventory=inventory,
            presentation=presentation, detail=detail,
        ):
            # EXCLUDED, NOT FATAL (founder 2026-09-19). This used to return
            # False, which aborted the block, which aborted the whole
            # inventory -- so ONE candidate whose Paragraph could not be
            # proven silenced every other slide's item for that Take. The
            # safety property is unchanged: a row we cannot prove is still
            # never served. What changes is the blast radius, which was never
            # the point. Contract 24c: coverage is a target on selection,
            # never a floor on output, and an honest empty lane shows no card
            # -- not an empty Take.
            closed(f"excluded_candidate:{row_position}")
            continue
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
    *, frame: Any, take_document: Any, served_text: str,
    feedback_candidates: Iterable[Any], detail: list[str] | None = None,
) -> dict | None:
    """Return a fail-closed V3 service inventory or ``None``.

    Service preparation requires exact lineage for every candidate considered.
    An excluded detector version remains a typed inventory row, but malformed
    clip/Paragraph lineage blocks the whole service freeze rather than hiding
    the invalid item inside an exclusion.

    ``detail`` IS THE SAME LESSON AS ``_decline`` (2026-09-19). This function
    has six separate ``return None`` exits and the caller turns every one of
    them into the single reason ``service_inventory_unavailable``. That is
    fail-closed, which is right, and fail-SILENT, which is not: on 2026-09-19 a
    V3 stand-down had to be chased through four database queries and a live RPC
    call before it named itself, and this function would have hidden the next
    one exactly as well. Pass a list and each exit appends the gate that closed.
    Log-only, never surfaced: the reason a Take has no Confident Voice item is
    not something AC-9 lets us put on screen.
    """
    def closed(gate: str) -> None:
        if detail is not None:
            detail.append(gate)

    frame_data = _valid_v3_policy_frame(frame, take_document)
    if frame_data is None:
        closed("policy_frame_invalid")
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
        closed("no_blocks_in_policy")
        return None

    for block_position, block in enumerate(blocks, 1):
        if not _v3_confidence_block(
            block, block_position, pieces=pieces, policy=policy,
            document_text=document_text, served_text=served_text,
            confidence_selected=confidence_selected,
            inventory=inventory, detail=detail,
        ):
            # Skipped for the same reason a rejected row is: a block we
            # cannot read contributes nothing, and contributing nothing must
            # not mean silencing the blocks we can.
            closed(f"confidence_block_excluded:{block_position}")
            continue

    verbal = policy.get("verbal_lanes")
    if not isinstance(verbal, dict):
        # An absent verbal block is an empty rewrite and praise lane, which
        # 24f already allows to show no card. Withholding Confident Voice
        # over it would be the same over-reach as aborting on one unprovable
        # row. Named, then carried on from.
        closed("no_verbal_lanes")
        verbal = {}
    snippet_block = _v3_snippet_block_index(blocks)
    for family in ("rewrite_clarity", "great_formulation"):
        if not _v3_verbal_lane(
            verbal.get(family), family=family, raw_by_identity=raw_by_identity,
            pieces=pieces, snippet_block=snippet_block, inventory=inventory,
        ):
            # 24f: at most one rewrite and two praise, and an honest empty
            # lane shows no card. A lane that cannot be proven is an empty
            # lane, not a reason to withhold Confident Voice.
            closed(f"verbal_lane_excluded:{family}")
            continue

    # THE ONE REMAINING FAIL-CLOSED GATE, and it is the right one: everything
    # above now excludes what it cannot prove and keeps what it can, so
    # reaching here with an incomplete inventory means nothing provable
    # survived. That is an honest decline; aborting because a single row was
    # unprovable was not.
    if not _v3_inventory_is_complete(inventory):
        closed(
            "inventory_incomplete:"
            f"selected={len(inventory.selected)}"
            f",candidates={len(inventory.candidates)}"
            f",items={len(inventory.items)}"
        )
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
