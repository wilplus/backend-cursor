"""Canonical, provenance-safe feedback write payloads.

The live product still reads its compatibility tables during the observation
window. This module creates deterministic immutable rows for the canonical
dual-write. It never decides what should surface; Manager membership is an
input and is preserved exactly.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Iterable, Optional
from config import Config

config = Config()


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
    # ("great_formulation", "acknowledged") is ABSENT ON PURPOSE (0333), the
    # same way `edit_myself` is. praise_helpfulness holds a judgement on a
    # scale; "I read this" is not a point on that scale, and recording it as
    # one would corrupt the only table whose values are supposed to mean
    # something. The owner self-report still lands — this map only decides
    # whether a CANONICAL judgement is also produced, and here none should be.
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
    return config.CODE_COMMIT_SHA or "unknown"


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
    served_text: str, document_snapshot_id: Optional[str] = None,
    document_surface_sha256: Optional[str] = None,
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

    snapshot_bound = (
        document_snapshot_id is not None or document_surface_sha256 is not None
    )
    if snapshot_bound:
        if (
            not isinstance(document_snapshot_id, str)
            or not document_snapshot_id
            or not isinstance(document_surface_sha256, str)
            or document_surface_sha256
            != hashlib.sha256(served_text.encode("utf-8")).hexdigest()
            or target_text is None
        ):
            return None
        locator = {
            "version": "ideal-text-target-locator-v1",
            "surface": "ideal_text",
            "surface_hash": document_surface_sha256,
            "start": target_start,
            "end": target_end,
            "exact_text": target_text,
        }
        locator_sha256 = content_hash({
            "document_snapshot_id": document_snapshot_id,
            "locator": locator,
        })
    else:
        # Historical/synthetic callers are explicitly non-snapshot-bound.
        # Text equality can never upgrade them to a locator after the fact.
        locator = None
        locator_sha256 = None
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
        "document_snapshot_id": document_snapshot_id,
        "target_locator": locator,
        "target_locator_sha256": locator_sha256,
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
        "document_snapshot_id": document_snapshot_id,
        "target_locator": locator,
        "target_locator_sha256": locator_sha256,
        "technical_metadata": {
            "duration_ms": duration_ms,
            "language": (piece or {}).get("language"),
        },
        "evidence_hash": evidence_hash,
        "input_hash": content_hash(evidence_identity),
        "target_matches_transcript": target_matches_transcript,
    }


def _valid_feedback_bundle_identity(session: dict) -> Optional[tuple]:
    project_id = str(session.get("project_id") or "")
    owner_id = str(session.get("owner_principal_id") or "")
    take_id = str(session.get("id") or "")
    take_index = _int(session.get("take_index"))
    if not project_id or not owner_id or not take_id or not take_index:
        return None
    return project_id, owner_id, take_id, take_index


def _valid_feedback_bundle_keys(
    selected_keys: Any, manager_rules_version: str,
) -> Optional[tuple]:
    keys = [dict(key) for key in selected_keys if isinstance(key, dict)] \
        if isinstance(selected_keys, list) else []
    service_v3 = manager_rules_version == "take-feedback-policy-v3-serving-v1"
    selected_families = {
        str(key.get("feedback_family")) for key in keys
    }
    if service_v3:
        if (
            not keys
            or "confident_voice" not in selected_families
            or not selected_families <= _FAMILIES
            or len({
                (str(key.get("id") or ""), str(key.get("feedback_family") or ""))
                for key in keys
            }) != len(keys)
        ):
            return None
    elif len(keys) != 3 or selected_families != _FAMILIES:
        return None
    return keys, service_v3


def _feedback_candidate_machine_prediction(
    raw: dict, *, evidence: dict, family: str,
    model_version: Optional[str], prompt_version: Optional[str],
) -> Optional[dict]:
    raw_prediction = raw.get("machine_prediction")
    if not isinstance(raw_prediction, dict):
        return None
    prediction_model = str(
        raw_prediction.get("model_version")
        or raw.get("model_version") or model_version or ""
    )
    if not prediction_model:
        return None
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
    return {
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


def _feedback_candidate_acoustic_snapshot(
    raw: dict, *, evidence: dict,
) -> Optional[dict]:
    raw_features = raw.get("acoustic_feature_snapshot")
    if not (isinstance(raw_features, dict)
            and isinstance(raw_features.get("features"), dict)):
        return None
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
    return {
        "id": _stable_uuid(
            "acoustic-feature-snapshot", feature_input_hash),
        "feature_schema_version": feature_schema,
        "speaker_baseline_version": baseline_version,
        "features": raw_features["features"],
        "input_hash": feature_input_hash,
    }


def _canonical_feedback_candidate(
    raw: dict, *, take_id: str, manager_rules_version: str, service_v3: bool,
    transcript_document: dict, transcript: dict, served_text: str,
    document_snapshot_id: Optional[str], document_surface_sha256: Optional[str],
    model_version: Optional[str], prompt_version: Optional[str],
) -> Optional[dict]:
    family = str(raw.get("feedback_family") or "")
    candidate_key = str(raw.get("id") or "")
    if family not in _FAMILIES or not candidate_key:
        return None
    evidence = _exact_transcript_evidence(
        family=family,
        row=raw,
        document=transcript_document,
        transcript=transcript,
        served_text=served_text,
        document_snapshot_id=document_snapshot_id,
        document_surface_sha256=document_surface_sha256,
    )
    if evidence is None:
        return None
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
        # A live product exposure is not a dataset release.  V3 service
        # records therefore remain structurally ineligible even where
        # their exact transcript target is valid.
        "training_eligible": eligible and not service_v3,
        "ineligibility_reason": (
            "service_product_evidence_only" if service_v3
            else None if eligible
            else "fallback_or_source_target_mismatch"
        ),
        "evidence": evidence,
    }
    prediction = _feedback_candidate_machine_prediction(
        raw, evidence=evidence, family=family, model_version=model_version,
        prompt_version=prompt_version,
    )
    if prediction is not None:
        canonical_candidate["machine_prediction"] = prediction
    snapshot = _feedback_candidate_acoustic_snapshot(raw, evidence=evidence)
    if snapshot is not None:
        canonical_candidate["acoustic_feature_snapshot"] = snapshot
    return canonical_candidate


def _valid_feedback_bundle_selection(
    canonical_candidates: list[dict], keys: list[dict], *,
    service_v3: bool, candidate_inputs: list[dict],
    detail: Optional[list[str]] = None,
) -> bool:
    available = {
        (row["candidate_key"], row["feedback_family"])
        for row in canonical_candidates
    }
    missing = [
        f"{str(key.get('feedback_family') or '∅')}"
        f"/{str(key.get('id') or '∅')}"
        for key in keys
        if (str(key.get("id")), str(key.get("feedback_family")))
        not in available
    ]
    if missing:
        if detail is not None:
            detail.append(f"selected_key_not_canonical:{','.join(missing)}")
        return False
    if service_v3 and len(canonical_candidates) != len(candidate_inputs):
        # Complete inventory is a service invariant.  A malformed excluded
        # candidate cannot disappear merely because it was never selectable.
        #
        # THE INVARIANT STAYS (2026-09-19). It is tempting to read this as the
        # same defect #567 fixed -- one unprovable row silencing a whole Take
        # -- and weaken it. It is not. #567 excluded rows that could not be
        # PROVEN at the policy layer, before anything was written. This is the
        # write itself: the bundle is the audit record, and a record that
        # quietly omits a row it was handed is a record that lies about what
        # the service considered. The counts say which way it went.
        if detail is not None:
            detail.append(
                "incomplete_inventory:"
                f"canonical={len(canonical_candidates)}"
                f",input={len(candidate_inputs)}"
            )
        return False
    return True


def _seal_candidate_identities(
    canonical_candidates: list, *, take_id: str, manager_rules_version: str,
    transcript_hash: str,
) -> None:
    """Give every candidate an id that is unique to THIS candidate set.

    PRODUCTION, 2026-09-21, minutes after the lineage write first succeeded:

        Feedback V3 service candidate set failed 23505/duplicate key value
        violates unique constraint "feedback_candidates_pkey"
        Key (id)=(cf0f0f8b-...) already exists.

    A candidate's id was `uuid5(take, rules, candidate_key)` — stable across
    every candidate set of the Take. The candidate SET's id and idempotency
    key hash the whole input, so the moment anything about the inventory
    changes (the speaker edits the words, a clip's evidence moves), a new
    set is recorded — carrying the same candidate ids as the old one, into
    a table whose primary key is that id. The second set could never be
    written, and V3 served "without lineage" from then on.

    So the id is sealed against the inventory it belongs to: the same take,
    rules, transcript and candidate content produce the same ids on every
    read (the replay branch keys on exactly that idempotency, and stays
    idempotent), and a changed inventory produces ids of its own. The
    exposure id follows the candidate id as before. Nothing about a
    candidate's evidence, key, family or content is touched (L2/L3).
    """
    inventory = content_hash({
        "take_id": take_id,
        "transcript_hash": transcript_hash,
        "candidates": [
            {key: value for key, value in candidate.items()
             if key not in ("id", "exposure_id")}
            for candidate in canonical_candidates
        ],
    })
    for candidate in canonical_candidates:
        candidate_id = _stable_uuid(
            "candidate", take_id, manager_rules_version, inventory,
            candidate["candidate_key"],
        )
        candidate["id"] = candidate_id
        candidate["exposure_id"] = _stable_uuid("exposure", candidate_id)


def _feedback_bundle_generation_runs(
    canonical_candidates: list[dict], *,
    model_version: Optional[str], prompt_version: Optional[str],
) -> list[dict]:
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
    return generation_runs


def build_feedback_exposure_bundle(
    *, session: Any, transcript_document: Any, served_text: Any,
    candidates: Iterable[Any], selected_keys: Any,
    manager_rules_version: str, model_version: Optional[str] = None,
    prompt_version: Optional[str] = None,
    experiment_assignment: Optional[dict] = None,
    commit: Optional[str] = None,
    document_snapshot_id: Optional[str] = None,
    document_surface_sha256: Optional[str] = None,
    detail: Optional[list[str]] = None,
) -> Optional[dict]:
    """Build one deterministic complete selection/exposure transaction.

    ``detail`` IS THE SAME LESSON, ONE LAYER DOWN (2026-09-19). This function
    has six ``return None`` exits and the caller turns every one of them --
    plus its own membership-count check -- into the single reason
    ``exposure_bundle_membership_count_mismatch``. Seven conditions, one name,
    and a name that actively misleads: six of them are not a count mismatch at
    all. ``prepare_v3_service_inventory`` learned this the same day, and the
    production line that taught it read ``detail=piece_has_no_part_id``.

    Pass a list and each exit appends the gate that closed. Log-only, never
    surfaced: why a Take has no Confident Voice item is not something AC-9
    lets us put on screen. Identifiers and counts, never candidate content.
    """
    def closed(gate: str) -> None:
        if detail is not None:
            detail.append(gate)

    if not isinstance(session, dict) or not isinstance(transcript_document, dict):
        closed("session_or_document_not_a_dict")
        return None
    identity = _valid_feedback_bundle_identity(session)
    if identity is None:
        closed("take_identity_invalid")
        return None
    project_id, owner_id, take_id, take_index = identity
    if not isinstance(served_text, str) or not served_text:
        closed("served_text_empty")
        return None
    key_selection = _valid_feedback_bundle_keys(selected_keys, manager_rules_version)
    if key_selection is None:
        closed("selected_keys_invalid")
        return None
    keys, service_v3 = key_selection

    candidate_inputs = [
        row for row in (candidates or []) if isinstance(row, dict)
    ]

    commit_value = commit or code_commit()
    transcript = _transcript_snapshot(
        project_id=project_id,
        take_id=take_id,
        document=transcript_document,
        take_index=take_index,
        commit=commit_value,
    )
    if transcript is None:
        closed("transcript_snapshot_unbuildable")
        return None

    canonical_candidates: list[dict] = []
    for raw in candidate_inputs:
        candidate = _canonical_feedback_candidate(
            raw, take_id=take_id, manager_rules_version=manager_rules_version,
            service_v3=service_v3, transcript_document=transcript_document,
            transcript=transcript, served_text=served_text,
            document_snapshot_id=document_snapshot_id,
            document_surface_sha256=document_surface_sha256,
            model_version=model_version, prompt_version=prompt_version,
        )
        if candidate is not None:
            canonical_candidates.append(candidate)
        else:
            # WHICH ROW, AND WHICH LANE. A candidate canonicalises to None
            # when its family is unknown, its key is empty, or its exact
            # transcript evidence cannot be built -- and under the V3
            # complete-inventory invariant below, ONE of these ends the whole
            # Take. Naming the row is the difference between "a candidate was
            # dropped" and a two-hour search for which.
            closed(
                "candidate_not_canonical:"
                f"{str(raw.get('feedback_family') or '∅')}"
                f"/{str(raw.get('id') or '∅')}"
            )

    if not _valid_feedback_bundle_selection(
        canonical_candidates, keys, service_v3=service_v3,
        candidate_inputs=candidate_inputs, detail=detail,
    ):
        return None
    _seal_candidate_identities(
        canonical_candidates, take_id=take_id,
        manager_rules_version=manager_rules_version,
        transcript_hash=str(transcript["transcript_hash"]),
    )

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
    generation_runs = _feedback_bundle_generation_runs(
        canonical_candidates, model_version=model_version,
        prompt_version=prompt_version,
    )
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
    candidate_id: Optional[str] = None,
    feedback_membership_id: Optional[str] = None,
    feedback_exposure_id: Optional[str] = None,
) -> Optional[dict]:
    """Map a UI action to one typed judgment without semantic inference.

    `edit_myself` intentionally maps to no correction label. It means that an
    editor was opened, not that the proposed correction was accepted or that
    the original was preferred.
    """
    value = _DECISION_MAP.get((feedback_family, response))
    if value is None:
        return None
    exact_ids = (
        candidate_id, feedback_membership_id, feedback_exposure_id,
    )
    if any(value is None for value in exact_ids):
        return None
    try:
        canonical_candidate_id = str(uuid.UUID(str(candidate_id)))
        canonical_membership_id = str(uuid.UUID(str(feedback_membership_id)))
        canonical_exposure_id = str(uuid.UUID(str(feedback_exposure_id)))
    except (TypeError, ValueError):
        return None
    key_payload = {
        "take_id": take_id,
        "rater_id": rater_id,
        "feedback_id": feedback_id,
        "candidate_id": canonical_candidate_id,
        "feedback_membership_id": canonical_membership_id,
        "feedback_exposure_id": canonical_exposure_id,
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
