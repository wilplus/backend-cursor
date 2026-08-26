"""Canonical, provenance-safe feedback write payloads.

The live product still reads its compatibility tables during the observation
window. This module creates deterministic immutable rows for the canonical
dual-write. It never decides what should surface; Manager membership is an
input and is preserved exactly.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from typing import Any, Iterable, Optional


TAXONOMY_VERSION = "feedback-taxonomy-v1"
SELECTOR_VERSION = "take-feedback-selector-v2"
THRESHOLD_VERSION = "take-feedback-thresholds-v1"
FEATURE_SCHEMA_VERSION = "acoustic-feature-schema-v1"
SPEAKER_BASELINE_VERSION = "speaker-relative-baseline-v1"

_NAMESPACE = uuid.UUID("aa78ba92-3d38-43fb-83d4-e4268ad5ab73")
_FAMILIES = {
    "confident_voice", "rewrite_clarity", "great_formulation",
}
_DECISION_MAP = {
    ("confident_voice", "yes"): "yes",
    ("confident_voice", "in_between"): "in_between",
    ("confident_voice", "no"): "no",
    ("confident_voice", "not_sure"): "not_sure",
    ("confident_voice", "audio_unclear"): "audio_unclear",
    ("great_formulation", "useful"): "useful",
    ("great_formulation", "not_useful"): "not_useful",
    ("great_formulation", "not_sure"): "not_sure",
    ("rewrite_clarity", "apply_suggestion"): "accept_proposed",
    ("rewrite_clarity", "keep_wording"): "keep_original",
}


def _json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        default=str,
    )


def content_hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _stable_uuid(*parts: Any) -> str:
    return str(uuid.uuid5(_NAMESPACE, "\0".join(str(part) for part in parts)))


def code_commit() -> str:
    return (
        os.environ.get("RAILWAY_GIT_COMMIT_SHA")
        or os.environ.get("GIT_COMMIT_SHA")
        or os.environ.get("SOURCE_COMMIT")
        or "unknown"
    )


def _int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _normalized_slide(value: Any) -> int:
    parsed = _int(value)
    return parsed if parsed is not None and parsed >= 0 else 0


def _paragraph_index(document: dict, position: int) -> Optional[int]:
    for index, paragraph in enumerate(document.get("paragraphs") or []):
        if not isinstance(paragraph, dict):
            continue
        start, end = _int(paragraph.get("start")), _int(paragraph.get("end"))
        if start is not None and end is not None and start <= position < end:
            return index
    return None


def _piece_by_snippet(document: dict) -> dict[str, dict]:
    return {
        str(piece.get("snippet_id")): piece
        for piece in (document.get("pieces") or [])
        if isinstance(piece, dict) and piece.get("snippet_id")
    }


def _transcript_snapshot(
    *, project_id: str, take_id: str, document: dict, take_index: int,
    commit: str,
) -> Optional[dict]:
    text = document.get("text")
    if not isinstance(text, str) or not text.strip() or take_index < 1:
        return None
    transcript_hash = content_hash(text)
    transcript_id = _stable_uuid(
        "transcript", project_id, take_id, take_index, transcript_hash,
    )
    raw_paragraphs = [
        row for row in (document.get("paragraphs") or [])
        if isinstance(row, dict)
    ]
    if not raw_paragraphs:
        return None
    slide_indexes = sorted({
        _normalized_slide(row.get("slide_index")) for row in raw_paragraphs
    })
    slides = [{
        "id": _stable_uuid("slide", transcript_id, slide_index),
        "slide_index": slide_index,
        "title": None,
        "source_payload": {
            "virtual": all(
                _int(row.get("slide_index")) is None
                for row in raw_paragraphs
            ),
        },
    } for slide_index in slide_indexes]
    paragraphs: list[dict] = []
    for index, row in enumerate(raw_paragraphs):
        start, end = _int(row.get("start")), _int(row.get("end"))
        if start is None or end is None or start < 0 or end <= start:
            return None
        paragraph_text = text[start:end]
        if not paragraph_text:
            return None
        paragraphs.append({
            "id": _stable_uuid("paragraph", transcript_id, index),
            "paragraph_index": index,
            "slide_index": _normalized_slide(row.get("slide_index")),
            "source_ideal_part_id": row.get("part_id"),
            "text": paragraph_text,
            "start_char": start,
            "end_char": end,
        })
    return {
        "id": transcript_id,
        "version": take_index,
        "source_kind": "aligned",
        "text": text,
        "transcript_hash": transcript_hash,
        "input_hash": content_hash({
            "text": text,
            "pieces": document.get("pieces") or [],
            "paragraphs": raw_paragraphs,
        }),
        "model_version": document.get("model_version"),
        "prompt_version": document.get("prompt_version"),
        "code_commit": commit,
        "slides": slides,
        "paragraphs": paragraphs,
    }


def _exact_transcript_evidence(
    *, family: str, row: dict, document: dict, transcript: dict,
    served_text: str,
) -> Optional[dict]:
    pieces = _piece_by_snippet(document)
    snippet_id = str(row.get("snippet_id") or "")
    piece = pieces.get(snippet_id)
    transcript_text = transcript["text"]

    start = end = None
    exact_text = None
    if piece:
        start, end = _int(piece.get("start")), _int(piece.get("end"))
        if (start is not None and end is not None
                and 0 <= start < end <= len(transcript_text)):
            exact_text = transcript_text[start:end]
        else:
            start = end = None

    raw_target_span = row.get("span")
    target_span: dict = raw_target_span if isinstance(
        raw_target_span, dict) else {}
    target_start = _int(target_span.get("start"))
    target_end = _int(target_span.get("end"))
    target_text = None
    if (target_start is not None and target_end is not None
            and 0 <= target_start < target_end <= len(served_text)):
        target_text = served_text[target_start:target_end]

    # For verbal evidence prefer the exact target words in the Take transcript.
    # If they are absent, retain the exact snippet span but mark the candidate
    # research-only. This preserves evidence without inventing equivalence.
    target_matches_transcript = False
    if family != "confident_voice" and target_text:
        located = transcript_text.find(target_text)
        if located >= 0:
            start, end, exact_text = located, located + len(target_text), target_text
            target_matches_transcript = True
    elif family == "confident_voice":
        target_matches_transcript = exact_text is not None

    paragraph_index = (
        _paragraph_index(document, start) if start is not None else None
    )
    paragraph = (
        transcript["paragraphs"][paragraph_index]
        if paragraph_index is not None
        and paragraph_index < len(transcript["paragraphs"])
        else None
    )
    if not paragraph or start is None or end is None or not exact_text:
        return None

    piece_slide = piece.get("slide_index") if piece else None
    slide_index = _normalized_slide(
        piece_slide if _int(piece_slide) is not None
        else paragraph.get("slide_index")
    )
    start_ms = _int((piece or {}).get("start_offset_ms"))
    duration_ms = _int((piece or {}).get("duration_ms"))
    end_ms = (
        start_ms + duration_ms
        if start_ms is not None and start_ms >= 0
        and duration_ms is not None and duration_ms > 0
        else None
    )

    replacement = str(row.get("proposed_text") or "").strip() or None
    if family == "confident_voice":
        if start_ms is None or end_ms is None:
            return None
        kind = "audio_and_transcript"
        task_type = "confidence_classification"
    elif family == "rewrite_clarity":
        if not replacement:
            return None
        kind = "correction_pair"
        task_type = "correction_selection"
    else:
        kind = "transcript_span"
        task_type = "praise_selection"

    locator = {
        "surface": "ideal_text",
        "start": target_start,
        "end": target_end,
        "exact_text": target_text,
        "paragraph_index": (
            (row.get("evidence") or {}).get("paragraph_index")
            if isinstance(row.get("evidence"), dict) else None
        ),
        "surface_hash": content_hash(served_text),
    }
    evidence_identity = {
        "take_id": row.get("take_session_id") or document.get("take_session_id"),
        "snippet_id": snippet_id,
        "family": family,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "start_char": start,
        "end_char": end,
        "exact_text": exact_text,
        "replacement_text": replacement,
        "target_locator": locator,
    }
    evidence_hash = content_hash(evidence_identity)
    return {
        "id": _stable_uuid("evidence", evidence_hash),
        "recording_id": (piece or {}).get("recording_id"),
        "legacy_piece_id": snippet_id or None,
        "uses_transcript": True,
        "evidence_kind": kind,
        "task_type": task_type,
        "audio_ref": (piece or {}).get("audio_ref"),
        "start_ms": start_ms,
        "end_ms": end_ms,
        "start_char": start,
        "end_char": end,
        "exact_text": exact_text,
        "replacement_text": replacement,
        "slide_index": slide_index,
        "paragraph_index": paragraph_index,
        "target_locator": locator,
        "technical_metadata": {
            "duration_ms": duration_ms,
            "language": (piece or {}).get("language"),
        },
        "evidence_hash": evidence_hash,
        "input_hash": content_hash(evidence_identity),
        "target_matches_transcript": target_matches_transcript,
    }


def build_feedback_exposure_bundle(
    *, session: Any, transcript_document: Any, served_text: Any,
    candidates: Iterable[Any], selected_keys: Any,
    manager_rules_version: str, model_version: Optional[str] = None,
    prompt_version: Optional[str] = None,
    experiment_assignment: Optional[dict] = None,
    commit: Optional[str] = None,
) -> Optional[dict]:
    """Build one deterministic complete selection/exposure transaction."""
    if not isinstance(session, dict) or not isinstance(transcript_document, dict):
        return None
    project_id = str(session.get("project_id") or "")
    owner_id = str(session.get("owner_principal_id") or "")
    take_id = str(session.get("id") or "")
    take_index = _int(session.get("take_index"))
    if not project_id or not owner_id or not take_id or not take_index:
        return None
    if not isinstance(served_text, str) or not served_text:
        return None
    keys = [dict(key) for key in selected_keys if isinstance(key, dict)] \
        if isinstance(selected_keys, list) else []
    if (len(keys) != 3
            or {str(key.get("feedback_family")) for key in keys} != _FAMILIES):
        return None

    commit_value = commit or code_commit()
    transcript = _transcript_snapshot(
        project_id=project_id,
        take_id=take_id,
        document=transcript_document,
        take_index=take_index,
        commit=commit_value,
    )
    if transcript is None:
        return None

    canonical_candidates: list[dict] = []
    for raw in candidates or []:
        if not isinstance(raw, dict):
            continue
        family = str(raw.get("feedback_family") or "")
        candidate_key = str(raw.get("id") or "")
        if family not in _FAMILIES or not candidate_key:
            continue
        evidence = _exact_transcript_evidence(
            family=family,
            row=raw,
            document=transcript_document,
            transcript=transcript,
            served_text=served_text,
        )
        if evidence is None:
            continue
        fallback = bool((raw.get("_manager_evidence") or {}).get("fallback")) \
            if isinstance(raw.get("_manager_evidence"), dict) else False
        eligible = bool(evidence.pop("target_matches_transcript")) and not fallback
        candidate_id = _stable_uuid(
            "candidate", take_id, manager_rules_version, candidate_key,
        )
        generated_output = {
            "quote": raw.get("quote"),
            "proposed_text": raw.get("proposed_text"),
            "why_key": raw.get("why_key"),
            "device": raw.get("device"),
            "tentative": bool(raw.get("tentative")),
        }
        canonical_candidate = {
            "id": candidate_id,
            "exposure_id": _stable_uuid("exposure", candidate_id),
            "candidate_key": candidate_key,
            "feedback_family": family,
            "lane": family,
            "candidate_score": raw.get("candidate_score"),
            "rank_evidence": {
                "manager_evidence": raw.get("_manager_evidence") or {},
                "rank_key": raw.get("rank_key") or [],
                "cue_keys": raw.get("cue_keys") or [],
            },
            "generated_output": generated_output,
            "detector_version": raw.get("detector_version"),
            "rule_version": raw.get("rule_version"),
            "model_version": raw.get("model_version"),
            "prompt_version": raw.get("prompt_version"),
            "training_eligible": eligible,
            "ineligibility_reason": (
                None if eligible
                else "fallback_or_source_target_mismatch"
            ),
            "evidence": evidence,
        }
        raw_prediction = raw.get("machine_prediction")
        if isinstance(raw_prediction, dict):
            prediction_model = str(
                raw_prediction.get("model_version")
                or raw.get("model_version") or model_version or ""
            )
            if prediction_model:
                prediction_output = (
                    raw_prediction.get("complete_output")
                    if isinstance(raw_prediction.get("complete_output"), dict)
                    else dict(raw_prediction)
                )
                prediction_input_hash = content_hash({
                    "evidence_hash": evidence["evidence_hash"],
                    "task_type": evidence["task_type"],
                    "model_version": prediction_model,
                    "complete_output": prediction_output,
                })
                canonical_candidate["machine_prediction"] = {
                    "id": _stable_uuid(
                        "machine-prediction", prediction_input_hash),
                    "task_type": str(
                        raw_prediction.get("task_type")
                        or evidence["task_type"]),
                    "surface": str(
                        raw_prediction.get("surface") or family),
                    "classification": raw_prediction.get("classification"),
                    "score": raw_prediction.get("score"),
                    "model_version": prediction_model,
                    "rule_version": (
                        raw_prediction.get("rule_version")
                        or raw.get("rule_version")),
                    "threshold_version": (
                        raw_prediction.get("threshold_version")
                        or THRESHOLD_VERSION),
                    "feature_schema_version": (
                        raw_prediction.get("feature_schema_version")
                        or FEATURE_SCHEMA_VERSION),
                    "speaker_baseline_version": (
                        raw_prediction.get("speaker_baseline_version")
                        or SPEAKER_BASELINE_VERSION),
                    "prompt_version": (
                        raw_prediction.get("prompt_version")
                        or raw.get("prompt_version") or prompt_version),
                    "input_hash": prediction_input_hash,
                    "complete_output": prediction_output,
                }
        raw_features = raw.get("acoustic_feature_snapshot")
        if (isinstance(raw_features, dict)
                and isinstance(raw_features.get("features"), dict)):
            feature_schema = str(
                raw_features.get("feature_schema_version")
                or FEATURE_SCHEMA_VERSION)
            baseline_version = str(
                raw_features.get("speaker_baseline_version")
                or SPEAKER_BASELINE_VERSION)
            feature_input_hash = content_hash({
                "evidence_hash": evidence["evidence_hash"],
                "feature_schema_version": feature_schema,
                "speaker_baseline_version": baseline_version,
                "features": raw_features["features"],
            })
            canonical_candidate["acoustic_feature_snapshot"] = {
                "id": _stable_uuid(
                    "acoustic-feature-snapshot", feature_input_hash),
                "feature_schema_version": feature_schema,
                "speaker_baseline_version": baseline_version,
                "features": raw_features["features"],
                "input_hash": feature_input_hash,
            }
        canonical_candidates.append(canonical_candidate)
    available = {
        (row["candidate_key"], row["feedback_family"])
        for row in canonical_candidates
    }
    if any(
        (str(key.get("id")), str(key.get("feedback_family"))) not in available
        for key in keys
    ):
        return None

    versions = {
        "taxonomy_version": TAXONOMY_VERSION,
        "selector_version": SELECTOR_VERSION,
        "manager_rules_version": manager_rules_version,
        "threshold_version": THRESHOLD_VERSION,
        "model_version": model_version,
        "prompt_version": prompt_version,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "speaker_baseline_version": SPEAKER_BASELINE_VERSION,
    }
    generation_runs: list[dict] = []
    for candidate in canonical_candidates:
        family = candidate["feedback_family"]
        if family not in ("rewrite_clarity", "great_formulation"):
            continue
        candidate_model = str(
            candidate.get("model_version") or model_version or "")
        candidate_prompt = str(
            candidate.get("prompt_version") or prompt_version or "")
        output = candidate.get("generated_output") or {}
        if not candidate_model or not candidate_prompt or not any(
                value is not None and value is not False
                for value in output.values()):
            continue
        generation_input_hash = content_hash({
            "evidence_hash": candidate["evidence"]["evidence_hash"],
            "task_type": (
                "correction_generation" if family == "rewrite_clarity"
                else "praise_generation"
            ),
            "model_version": candidate_model,
            "prompt_version": candidate_prompt,
            "output": output,
        })
        generation_runs.append({
            "id": _stable_uuid("generation-run", generation_input_hash),
            "evidence_span_id": candidate["evidence"]["id"],
            "task_type": (
                "correction_generation" if family == "rewrite_clarity"
                else "praise_generation"
            ),
            "surface": family,
            "model_version": candidate_model,
            "prompt_version": candidate_prompt,
            "input_hash": generation_input_hash,
            "complete_output": output,
        })
    input_payload = {
        "take_id": take_id,
        "transcript_hash": transcript["transcript_hash"],
        "candidates": canonical_candidates,
        "selected_keys": keys,
        "versions": versions,
        "experiment_assignment": experiment_assignment or {},
    }
    input_hash = content_hash(input_payload)
    return {
        "owner_principal_id": owner_id,
        "project_id": project_id,
        "take_id": take_id,
        "candidate_set_id": _stable_uuid(
            "candidate-set", take_id, manager_rules_version, input_hash,
        ),
        "transcript": transcript,
        "candidates": canonical_candidates,
        "selected_keys": keys,
        "versions": versions,
        "experiment_assignment": experiment_assignment or {},
        "generation_runs": generation_runs,
        "input_hash": input_hash,
        "idempotency_key": (
            f"feedback-exposure:{take_id}:{manager_rules_version}:{input_hash}"
        ),
        "code_commit": commit_value,
    }


def canonical_feedback_decision(
    *, take_id: str, rater_id: str, feedback_id: str,
    feedback_family: str, response: str,
) -> Optional[dict]:
    """Map a UI action to one typed judgment without semantic inference.

    `edit_myself` intentionally maps to no correction label. It means that an
    editor was opened, not that the proposed correction was accepted or that
    the original was preferred.
    """
    value = _DECISION_MAP.get((feedback_family, response))
    if value is None:
        return None
    key_payload = {
        "take_id": take_id,
        "rater_id": rater_id,
        "feedback_id": feedback_id,
        "feedback_family": feedback_family,
        "value": value,
        "taxonomy_version": TAXONOMY_VERSION,
    }
    return {
        **key_payload,
        "idempotency_key": f"feedback-decision:{content_hash(key_payload)}",
    }


def canonical_paragraph_decision(
    *, take_id: str, project_id: str, rater_id: str,
    source_ideal_part_id: str, exact_text: str, value: str,
    revision_coordinate: str,
) -> Optional[dict]:
    """Build one explicit paragraph-version decision; never infer a lock."""
    if value not in (
            "lock_for_next_take", "keep_evolving", "reopen_for_edit"):
        return None
    if not all((take_id, project_id, rater_id, source_ideal_part_id,
                exact_text, revision_coordinate)):
        return None
    try:
        uuid.UUID(str(source_ideal_part_id))
    except (TypeError, ValueError):
        return None
    evidence_material = {
        "take_id": str(take_id),
        "project_id": str(project_id),
        "source_ideal_part_id": str(source_ideal_part_id),
        "exact_text": str(exact_text),
        "task_type": "paragraph_decision",
    }
    evidence_hash = content_hash(evidence_material)
    decision_material = {
        **evidence_material,
        "rater_id": str(rater_id),
        "value": value,
        "taxonomy_version": TAXONOMY_VERSION,
        "revision_coordinate": str(revision_coordinate),
    }
    return {
        "take_id": str(take_id),
        "project_id": str(project_id),
        "rater_id": str(rater_id),
        "source_ideal_part_id": str(source_ideal_part_id),
        "exact_text": str(exact_text),
        "value": value,
        "taxonomy_version": TAXONOMY_VERSION,
        "evidence_id": _stable_uuid("paragraph-evidence", evidence_hash),
        "evidence_hash": evidence_hash,
        "input_hash": content_hash(evidence_material),
        "idempotency_key": (
            "paragraph-decision:" + content_hash(decision_material)
        ),
    }


def canonical_root_phrase(
    *, take_id: str, project_id: str, rater_id: str,
    source_ideal_part_id: str, exact_text: str, start: int, end: int,
    revision_coordinate: str,
) -> Optional[dict]:
    """Build an exact, explicit orange-root choice for a locked paragraph."""
    if (not all((take_id, project_id, rater_id, source_ideal_part_id,
                 exact_text, revision_coordinate))
            or isinstance(start, bool) or isinstance(end, bool)
            or not isinstance(start, int) or not isinstance(end, int)
            or start < 0 or end <= start):
        return None
    try:
        uuid.UUID(str(source_ideal_part_id))
    except (TypeError, ValueError):
        return None
    material = {
        "take_id": str(take_id),
        "project_id": str(project_id),
        "rater_id": str(rater_id),
        "source_ideal_part_id": str(source_ideal_part_id),
        "exact_text": str(exact_text),
        "start": start,
        "end": end,
        "revision_coordinate": str(revision_coordinate),
    }
    return {
        **material,
        "idempotency_key": "root-phrase:" + content_hash(material),
    }


def canonical_root_phrase_skip(
    *, take_id: str, project_id: str, rater_id: str,
    source_ideal_part_id: str, revision_coordinate: str,
) -> Optional[dict]:
    """Build the explicit “do not color this locked paragraph” response."""
    if not all((take_id, project_id, rater_id, source_ideal_part_id,
                revision_coordinate)):
        return None
    try:
        uuid.UUID(str(source_ideal_part_id))
    except (TypeError, ValueError):
        return None
    material = {
        "take_id": str(take_id),
        "project_id": str(project_id),
        "rater_id": str(rater_id),
        "source_ideal_part_id": str(source_ideal_part_id),
        "taxonomy_version": TAXONOMY_VERSION,
        "revision_coordinate": str(revision_coordinate),
    }
    return {
        **material,
        "idempotency_key": "root-phrase-skip:" + content_hash(material),
    }


def blind_packet_hash(evidence: Any) -> Optional[str]:
    """Hash only fields allowed on the pre-judgment coach packet."""
    if not isinstance(evidence, dict) or not evidence.get("evidence_span_id"):
        return None
    allowed = {
        "evidence_span_id": evidence.get("evidence_span_id"),
        "audio_ref": evidence.get("audio_ref"),
        "start_ms": evidence.get("start_ms"),
        "end_ms": evidence.get("end_ms"),
        "technical_metadata": evidence.get("technical_metadata") or {},
    }
    return content_hash(allowed)
