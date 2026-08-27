"""True rendered-exposure boundary for seven isolated learning surfaces.

Preparing a presentation freezes provenance but does not mean it was shown.
Only the post-render acknowledgement creates an exposure receipt. This module
has no API for close, skip, timeout or no-response, so those states remain
unanswered by construction.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any
import uuid

from services.feedback_data_contract import content_hash


LEARNING_SURFACES = frozenset({
    "confidence_classification",
    "correction_generation",
    "coach_comment_generation",
    "praise_generation",
    "praise_selection",
    "correction_selection",
    "ideal_text_generation",
})

_FEEDBACK_SURFACES = {
    "confident_voice": ("confidence_classification",),
    "rewrite_clarity": (
        "correction_generation", "correction_selection",
    ),
    "great_formulation": ("praise_generation", "praise_selection"),
}


class LearningExposureError(RuntimeError):
    """A visible item could not receive a provenance-safe ACK handle."""


def _candidate_snapshot(candidate: dict) -> dict:
    evidence = candidate.get("evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    return {
        "candidate_id": candidate.get("id"),
        "candidate_key": candidate.get("candidate_key"),
        "feedback_family": candidate.get("feedback_family"),
        "candidate_score": candidate.get("candidate_score"),
        "rank_evidence": candidate.get("rank_evidence") or {},
        "generated_output": candidate.get("generated_output") or {},
        "evidence_span_id": evidence.get("id"),
        "evidence_hash": evidence.get("evidence_hash"),
        "training_eligible": bool(candidate.get("training_eligible")),
        "ineligibility_reason": candidate.get("ineligibility_reason"),
    }


def prepare_presentation(
    *, database: Any, owner_principal_id: str, project_id: str,
    take_id: str, learning_surface: str, actor_role: str, actor_id: str,
    complete_candidate_set: list[dict], selected_candidate: dict,
    visible_payload: dict, versions: dict, evidence_span_id: str | None = None,
    candidate_set_id: str | None = None,
    generation_run_id: str | None = None,
    delivery_mode: str = "production",
) -> dict:
    if learning_surface not in LEARNING_SURFACES:
        raise LearningExposureError("unknown learning surface")
    if actor_role not in ("owner", "coach", "peer"):
        raise LearningExposureError("unknown exposure actor role")
    if delivery_mode not in ("production", "canary", "shadow"):
        raise LearningExposureError("unknown delivery mode")
    if not all((owner_principal_id, project_id, take_id, actor_id)):
        raise LearningExposureError("presentation ownership is incomplete")
    if not complete_candidate_set or not isinstance(selected_candidate, dict):
        raise LearningExposureError("presentation selection is incomplete")
    if not isinstance(visible_payload, dict) or not isinstance(versions, dict):
        raise LearningExposureError("presentation payload is incomplete")

    material = {
        "owner_principal_id": owner_principal_id,
        "project_id": project_id,
        "take_id": take_id,
        "evidence_span_id": evidence_span_id,
        "candidate_set_id": candidate_set_id,
        "generation_run_id": generation_run_id,
        "learning_surface": learning_surface,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "complete_candidate_set": complete_candidate_set,
        "selected_candidate": selected_candidate,
        "visible_payload": visible_payload,
        "versions": versions,
        "delivery_mode": delivery_mode,
    }
    presentation = {
        **material,
        "content_hash": content_hash(material),
    }
    presentation["idempotency_key"] = (
        f"learning-presentation:{content_hash(presentation)}"
    )
    row = database.create_learning_surface_presentation(presentation)
    if not isinstance(row, dict) or not row.get("presentation_id") \
            or not row.get("acknowledgement_token"):
        raise LearningExposureError(
            f"{learning_surface} presentation was not persisted"
        )
    return {
        "presentation_id": str(row["presentation_id"]),
        "acknowledgement_token": str(row["acknowledgement_token"]),
        "learning_surface": learning_surface,
        "evaluation_only": bool(row.get("evaluation_only")),
    }


def prepare_feedback_presentations(
    *, database: Any, bundle: dict, actor_id: str,
    delivery_mode: str = "production",
) -> dict[str, list[dict]]:
    """Create five surface packets for the three frozen Feedback cards."""
    candidates = [
        row for row in (bundle.get("candidates") or [])
        if isinstance(row, dict)
    ]
    selected_keys = {
        (str(row.get("id") or ""), str(row.get("feedback_family") or ""))
        for row in (bundle.get("selected_keys") or [])
        if isinstance(row, dict)
    }
    selected = [
        row for row in candidates
        if (str(row.get("candidate_key") or ""),
            str(row.get("feedback_family") or "")) in selected_keys
    ]
    if len(selected) != 3:
        raise LearningExposureError("feedback selection is not exact-three")
    complete_snapshot = [_candidate_snapshot(row) for row in candidates]
    if len(complete_snapshot) < 3:
        raise LearningExposureError("feedback candidate inventory is incomplete")

    generation_ids = {
        (str(row.get("evidence_span_id") or ""), str(row.get("task_type") or "")):
        str(row.get("id"))
        for row in (bundle.get("generation_runs") or [])
        if isinstance(row, dict) and row.get("id")
    }
    prepared: dict[str, list[dict]] = defaultdict(list)
    for candidate in selected:
        candidate_key = str(candidate.get("candidate_key") or "")
        family = str(candidate.get("feedback_family") or "")
        evidence = candidate.get("evidence")
        evidence = evidence if isinstance(evidence, dict) else {}
        evidence_id = str(evidence.get("id") or "")
        if not candidate_key or family not in _FEEDBACK_SURFACES or not evidence_id:
            raise LearningExposureError("selected Feedback evidence is incomplete")
        selected_snapshot = _candidate_snapshot(candidate)
        visible_payload = {
            "candidate_key": candidate_key,
            "feedback_family": family,
            "generated_output": candidate.get("generated_output") or {},
            "evidence": {
                "evidence_span_id": evidence_id,
                "audio_ref": evidence.get("audio_ref"),
                "start_ms": evidence.get("start_ms"),
                "end_ms": evidence.get("end_ms"),
                "exact_text": evidence.get("exact_text"),
                "replacement_text": evidence.get("replacement_text"),
                "target_locator": evidence.get("target_locator") or {},
            },
        }
        for surface in _FEEDBACK_SURFACES[family]:
            generation_id = generation_ids.get((evidence_id, surface))
            packet = prepare_presentation(
                database=database,
                owner_principal_id=str(bundle.get("owner_principal_id") or ""),
                project_id=str(bundle.get("project_id") or ""),
                take_id=str(bundle.get("take_id") or ""),
                evidence_span_id=evidence_id,
                candidate_set_id=str(bundle.get("candidate_set_id") or "") or None,
                generation_run_id=generation_id,
                learning_surface=surface,
                actor_role="owner",
                actor_id=actor_id,
                complete_candidate_set=complete_snapshot,
                selected_candidate=selected_snapshot,
                visible_payload=visible_payload,
                versions=dict(bundle.get("versions") or {}),
                delivery_mode=delivery_mode,
            )
            if not packet["evaluation_only"]:
                prepared[candidate_key].append(packet)
    return dict(prepared)


def prepare_ideal_text_presentation(
    *, database: Any, owner_principal_id: str, project_id: str,
    take_id: str, actor_id: str, text: str, version: int | None,
    take_count: int, title: str | None, parts: list[dict] | None,
    delivery_mode: str = "production",
) -> dict:
    """Freeze the exact Ideal Text document offered to its owner.

    Ideal Text is a document-level generation surface, so it deliberately has
    no fabricated transcript span.  The canonical Take remains the immutable
    sample boundary and the browser ACK remains the exposure boundary.
    """
    if not isinstance(text, str) or not text.strip():
        raise LearningExposureError("ideal text presentation has no document")
    document = {
        "text": text,
        "version": version,
        "take_count": take_count,
        "title": title,
        "parts": parts if isinstance(parts, list) else None,
    }
    document_hash = content_hash(document)
    candidate = {
        "candidate_key": f"ideal-text:{document_hash}",
        "document_hash": document_hash,
        "text": text,
        "version": version,
        "take_count": take_count,
    }
    return prepare_presentation(
        database=database,
        owner_principal_id=owner_principal_id,
        project_id=project_id,
        take_id=take_id,
        learning_surface="ideal_text_generation",
        actor_role="owner",
        actor_id=actor_id,
        complete_candidate_set=[candidate],
        selected_candidate=candidate,
        visible_payload=document,
        versions={
            "surface_schema": "ideal-text-exposure-v1",
            "document_version": version,
            "take_count": take_count,
        },
        delivery_mode=delivery_mode,
    )


def prepare_blind_confidence_presentation(
    *, database: Any, owner_principal_id: str, project_id: str,
    take_id: str, evidence_span_id: str, actor_role: str, actor_id: str,
    complete_candidate_set: list[dict], selected_candidate: dict,
    visible_payload: dict, versions: dict,
    delivery_mode: str = "production",
) -> dict:
    """Freeze one genuinely blind coach/peer classification packet."""
    forbidden = {
        "machine_prediction", "user_self_report", "coach_judgment",
        "peer_judgment", "exact_text", "transcript_text",
    }
    if forbidden.intersection(visible_payload):
        raise LearningExposureError("blind packet contains answer context")
    if actor_role not in ("coach", "peer"):
        raise LearningExposureError("blind packet requires an independent rater")
    return prepare_presentation(
        database=database,
        owner_principal_id=owner_principal_id,
        project_id=project_id,
        take_id=take_id,
        evidence_span_id=evidence_span_id,
        learning_surface="confidence_classification",
        actor_role=actor_role,
        actor_id=actor_id,
        complete_candidate_set=complete_candidate_set,
        selected_candidate=selected_candidate,
        visible_payload=visible_payload,
        versions=versions,
        delivery_mode=delivery_mode,
    )


def acknowledge_visible_render(
    *, database: Any, presentation_id: str, acknowledgement_token: str,
    actor_role: str, actor_id: str, render_instance_id: str,
    client_rendered_at: str | None = None,
) -> dict:
    for raw in (
        presentation_id, acknowledgement_token, actor_id, render_instance_id,
    ):
        try:
            uuid.UUID(str(raw))
        except (TypeError, ValueError) as error:
            raise LearningExposureError(
                "exposure acknowledgement contains an invalid UUID"
            ) from error
    if actor_role not in ("owner", "coach", "peer"):
        raise LearningExposureError("unknown exposure actor role")
    key_material = {
        "presentation_id": presentation_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "render_instance_id": render_instance_id,
    }
    row = database.acknowledge_learning_surface_exposure({
        **key_material,
        "acknowledgement_token": acknowledgement_token,
        "client_rendered_at": client_rendered_at,
        "idempotency_key": f"learning-exposure:{content_hash(key_material)}",
    })
    if not isinstance(row, dict) or not row.get("exposure_receipt_id"):
        raise LearningExposureError("visible exposure was not acknowledged")
    return row
