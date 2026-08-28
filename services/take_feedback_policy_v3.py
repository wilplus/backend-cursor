"""Dark, non-serving contract for Take feedback policy v3.

The frame is an immutable policy-evaluation artifact. It never serves feedback,
creates a rendered exposure, or becomes dataset input. Every candidate that the
policy examines is retained as eligible or excluded with a typed reason.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable, Optional

from services.feedback_data_contract import FEATURE_SCHEMA_VERSION
from services.take_feedback_manager import (
    EVIDENCE_SCHEMA_VERSION as MANAGER_EVIDENCE_SCHEMA_VERSION,
    POLICY_VERSION as MANAGER_RULES_VERSION,
)
from services.voice_confidence import VERSION as CONFIDENCE_DETECTOR_VERSION


POLICY_VERSION = "take-feedback-policy-v3-dark-v2"
FRAME_SCHEMA_VERSION = "take-feedback-policy-v3-frame-v2"
SUGGESTION_GENERATOR_CONTRACT_VERSION = "feedback-candidate-generator-v1"
TARGET_WORDS = 75
MIN_WORDS = 60
MAX_WORDS = 90
_WORD_RE = re.compile(r"[^\W_]+(?:[’'-][^\W_]+)*", re.UNICODE)
_VERBAL_FAMILIES = {"rewrite_clarity", "great_formulation"}
_VERSION_KEYS = (
    "suggestion_version",
    "model_version",
    "prompt_version",
    "rule_version",
    "detector_version",
)


def dark_enabled(acquisition_principal_id: Any) -> bool:
    """True only for the exact configured founder in explicit dark mode."""
    mode = (os.getenv("TAKE_FEEDBACK_POLICY_V3_MODE") or "off").strip()
    founder = (
        os.getenv("TAKE_FEEDBACK_POLICY_V3_FOUNDER_PRINCIPAL_ID") or ""
    ).strip()
    owner = str(acquisition_principal_id or "").strip()
    return bool(
        mode == "dark"
        and founder
        and owner
        and hmac.compare_digest(founder, owner)
    )


def _words(value: Any) -> int:
    return len(_WORD_RE.findall(value if isinstance(value, str) else ""))


def _integer(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _versions(row: Any) -> dict:
    item = row if isinstance(row, dict) else {}
    return {
        key: str(item.get(key)) if item.get(key) not in (None, "") else None
        for key in _VERSION_KEYS
    }


def _has_producer_version(versions: dict) -> bool:
    return any(versions.get(key) for key in _VERSION_KEYS)


def _source_code_sha256() -> str:
    """Hash every implementation module that can affect this frozen frame."""
    root = Path(__file__).resolve().parent
    names = (
        "take_feedback_policy_v3.py",
        "take_feedback_manager.py",
        "feedback_data_contract.py",
        "voice_confidence.py",
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
                "pieces": pack,
            })
    return blocks, exclusions


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


def _confidence_candidate(
    piece: dict,
    snippet: dict,
    suggestion: dict,
    *,
    expected_take_id: str,
    expected_recording_id: str,
) -> dict:
    from services.voice_confidence import stamped_score

    metrics = snippet.get("metrics") if isinstance(snippet, dict) else None
    metrics = metrics if isinstance(metrics, dict) else {}
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
    return {
        "candidate_id": (
            f"relative-confidence:{piece['take_id']}:{piece['snippet_id']}"
        ),
        "snippet_id": piece["snippet_id"],
        "take_id": piece["take_id"],
        "slide_index": piece["slide_index"],
        "document_span": {"start": piece["start"], "end": piece["end"]},
        "word_count": piece["word_count"],
        "clip_identity": clip_identity,
        "eligibility": "eligible" if clip_identity else "excluded",
        "exclusion_reason": exclusion_reason,
        "machine_score": score,
        "machine_version": observed_version,
        "suggestion_provenance": _versions(suggestion),
        "ordinal": piece["ordinal"],
        "selection_language": (
            "relatively_strongest_measured"
            if score is not None and score > 0
            else "best_available_tentative"
        ),
    }


def _confidence_rank(candidate: dict) -> tuple:
    score = candidate.get("machine_score")
    measured = isinstance(score, (int, float)) and not isinstance(score, bool)
    numeric_score = (
        float(score)
        if isinstance(score, (int, float)) and not isinstance(score, bool)
        else 0.0
    )
    return (
        0 if measured else 1,
        -numeric_score if measured else 0.0,
        int(candidate.get("ordinal") or 0),
        str(candidate.get("candidate_id") or ""),
    )


def _verbal_inventory(
    candidates: Iterable[Any],
    family: str,
    take_id: str,
    *,
    document_length: int,
    snippet_map: dict[str, dict],
) -> tuple[list[dict], Optional[str], list[dict]]:
    ranked: list[tuple[tuple, dict]] = []
    inventory: list[dict] = []
    exclusions: list[dict] = []
    for input_index, raw in enumerate(candidates or []):
        row = raw if isinstance(raw, dict) else {}
        if row.get("feedback_family") != family:
            continue
        candidate_id = str(row.get("id") or "")
        snippet_id = str(row.get("snippet_id") or "")
        snippet = snippet_map.get(snippet_id, {})
        row_take = str(row.get("take_session_id") or "")
        resolved_take = row_take or str(snippet.get("session_id") or "")
        raw_span = row.get("span")
        span: dict = raw_span if isinstance(raw_span, dict) else {}
        start, end = _integer(span.get("start")), _integer(span.get("end"))
        producer_versions = _versions(row)
        raw_evidence = row.get("_manager_evidence")
        raw_evidence = raw_evidence if isinstance(raw_evidence, dict) else {}
        evidence = {
            key: raw_evidence[key]
            for key in (
                "specificity",
                "fallback",
                "detector",
                "detector_rank",
                "lexical_words_invented",
                "basis",
                "anchor_score",
                "cue_count",
            )
            if key in raw_evidence
        }

        reason: Optional[str] = None
        if not candidate_id:
            reason = "missing_candidate_identity"
        elif not snippet_id or not snippet:
            reason = "missing_snippet_lineage"
        elif resolved_take != take_id or str(snippet.get("session_id") or "") != take_id:
            reason = "candidate_take_mismatch"
        elif start is None or end is None or start < 0 or end <= start:
            reason = "invalid_document_span"
        elif end > document_length:
            reason = "document_span_out_of_bounds"
        elif not evidence:
            reason = "missing_evidence_metadata"
        elif not _has_producer_version(producer_versions):
            reason = "missing_suggestion_generator_version"

        item = {
            "input_index": input_index,
            "candidate_id": candidate_id or None,
            "feedback_family": family,
            "snippet_id": snippet_id or None,
            "take_id": resolved_take or None,
            "document_span": (
                {"start": start, "end": end}
                if start is not None and end is not None else None
            ),
            "evidence": evidence,
            "producer_versions": producer_versions,
            "tentative": bool(row.get("tentative")),
            "eligibility": "excluded" if reason else "eligible",
            "exclusion_reason": reason,
        }
        inventory.append(item)
        if reason:
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
            int(start or 0), int(end or 0), candidate_id,
        )
        ranked.append((rank, item))

    ranked.sort(key=lambda value: value[0])
    selected_id = ranked[0][1]["candidate_id"] if ranked else None
    return inventory, selected_id, exclusions


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
) -> Optional[dict]:
    """Build the complete v3 frame; return None for an unusable Take."""
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
    confidence_selections: list[dict] = []
    for block in blocks:
        candidates = [
            _confidence_candidate(
                piece,
                snippet_map.get(piece["snippet_id"], {}),
                suggestion_map.get(piece["snippet_id"], {}),
                expected_take_id=take_id,
                expected_recording_id=recording_id,
            )
            for piece in block.pop("pieces")
        ]
        eligible = [row for row in candidates if row["eligibility"] == "eligible"]
        selected = min(eligible, key=_confidence_rank) if eligible else None
        block["confidence_candidates"] = candidates
        block["selected_candidate_id"] = (
            selected["candidate_id"] if selected else None
        )
        block["selection_reason"] = (
            selected["selection_language"]
            if selected else "no_exact_clip_lineage_candidate"
        )
        if selected:
            confidence_selections.append({
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

    feedback_rows = list(feedback_candidates or [])
    rewrite_inventory, rewrite_selected, rewrite_exclusions = _verbal_inventory(
        feedback_rows,
        "rewrite_clarity",
        take_id,
        document_length=len(document_text),
        snippet_map=snippet_map,
    )
    praise_inventory, praise_selected, praise_exclusions = _verbal_inventory(
        feedback_rows,
        "great_formulation",
        take_id,
        document_length=len(document_text),
        snippet_map=snippet_map,
    )
    exclusions.extend(rewrite_exclusions)
    exclusions.extend(praise_exclusions)
    exclusions.extend(_unrouted_inventory(feedback_rows))
    mature = take_index >= 2

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
            "deployment_commit": (
                os.getenv("RAILWAY_GIT_COMMIT_SHA")
                or os.getenv("GIT_COMMIT_SHA")
                or os.getenv("SOURCE_VERSION")
                or None
            ),
        },
        "block_policy": {
            "unit": "slide_bounded_semantic_speech_block",
            "target_words": TARGET_WORDS,
            "normal_min_words": MIN_WORDS,
            "normal_max_words": MAX_WORDS,
            "split_only_at_exact_snippet_boundaries": True,
        },
        "confidence_definition": {
            "scope": "relative_within_block",
            "winner": "highest_ranked_exact_lineage_candidate",
            "absolute_confidence_threshold_required": False,
            "missing_or_weak_evidence_language": "tentative",
        },
        "blocks": blocks,
        "selected_confidence": confidence_selections,
        "verbal_lanes": {
            "enabled": mature,
            "rewrite_clarity": {
                "selection_scope": "global_absolute_quality",
                "candidates": rewrite_inventory,
                "selected_candidate_id": rewrite_selected if mature else None,
            },
            "great_formulation": {
                "selection_scope": "global_absolute_quality",
                "candidates": praise_inventory,
                "selected_candidate_id": praise_selected if mature else None,
            },
        },
        "excluded_candidates": exclusions,
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
