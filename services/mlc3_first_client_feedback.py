"""Fail-closed preparation of allowlisted Feedback V3 product rows.

This module is a product integration seam, not a learning producer.  It
creates a fresh service candidate inventory, freezes it against the current
Ideal Text snapshot, and adds exercise context only where an independently
frozen N1 inventory already exists for the exact clip.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from services.coach_guidance_delivery import principal_is_allowlisted
from services.feedback_data_contract import build_feedback_exposure_bundle
from services.take_feedback_policy_v3 import build_service_candidate_frame
from services.take_feedback_policy_v3_service import prepare_v3_service_inventory


def _canonical_index(bundle: dict) -> dict[tuple[str, str], dict]:
    return {
        (str(row.get("feedback_family") or ""), str(row.get("candidate_key") or "")): row
        for row in bundle.get("candidates") or []
        if isinstance(row, dict)
    }


def prepare_first_client_feedback(
    *,
    database: Any,
    session: Any,
    take_document: Any,
    served_text: str,
    snippets: Any,
    suggestions: Any,
    feedback_candidates: Iterable[Any],
    owner_user_id: str,
) -> list[dict] | None:
    """Return exact service rows, or ``None`` to preserve legacy fallback."""
    take = session if isinstance(session, dict) else {}
    principal_id = str(take.get("owner_principal_id") or "")
    project_id = str(take.get("project_id") or "")
    take_id = str(take.get("id") or "")
    if (
        not principal_is_allowlisted(principal_id=principal_id)
        or not project_id
        or not take_id
        or str(owner_user_id or "") != str(take.get("user_id") or owner_user_id)
    ):
        return None
    frame = build_service_candidate_frame(
        take_document=take_document,
        snippets=snippets,
        suggestions=suggestions,
        feedback_candidates=feedback_candidates,
        take_index=take.get("take_index"),
        expected_recording_id=take.get("recording_1_id"),
    )
    inventory = prepare_v3_service_inventory(
        frame=frame,
        take_document=take_document,
        feedback_candidates=feedback_candidates,
    )
    if inventory is None:
        return None
    bundle = build_feedback_exposure_bundle(
        session=take,
        transcript_document=take_document,
        served_text=served_text,
        candidates=inventory["candidates"],
        selected_keys=inventory["selected_keys"],
        manager_rules_version="take-feedback-policy-v3-serving-v1",
    )
    if bundle is None or len(bundle.get("candidates") or []) != len(
        inventory["membership_items"]
    ):
        return None
    candidate_result = database.record_feedback_v3_service_candidate_set(bundle)
    if (
        not isinstance(candidate_result, dict)
        or str(candidate_result.get("candidate_set_id") or "")
        != str(bundle["candidate_set_id"])
    ):
        return None
    snapshot = database.get_current_ideal_text_document_snapshot(project_id)
    if (
        not isinstance(snapshot, dict)
        or str(snapshot.get("source_take_session_id") or "") != take_id
        or not snapshot.get("id")
    ):
        return None
    canonical = _canonical_index(bundle)
    membership_items: list[dict] = []
    for raw in inventory["membership_items"]:
        row = dict(raw)
        item = canonical.get((row["feedback_family"], row["candidate_key"]))
        if item is None:
            return None
        row["candidate_id"] = item["id"]
        membership_items.append(row)
    membership = database.freeze_feedback_v3_service_membership({
        "p_acquisition_principal_id": principal_id,
        "p_project_id": project_id,
        "p_take_id": take_id,
        "p_candidate_set_id": bundle["candidate_set_id"],
        "p_document_snapshot_id": str(snapshot["id"]),
        "p_block_partition_version": inventory["block_partition_version"],
        "p_items": membership_items,
        "p_idempotency_key": (
            f"feedback-v3-service-membership:{bundle['candidate_set_id']}:"
            f"{snapshot['id']}"
        ),
    })
    if not isinstance(membership, dict) or not membership.get("id"):
        return None

    visible: list[dict] = []
    for raw in inventory["visible_rows"]:
        row = dict(raw)
        family = str(row.get("feedback_family") or "")
        key = str(row.get("id") or "")
        exact = canonical.get((family, key))
        if exact is None:
            return None
        row.update({
            "candidate_id": str(exact["id"]),
            "feedback_membership_id": str(membership["id"]),
            "feedback_exposure_id": str(exact["exposure_id"]),
        })
        if family == "confident_voice":
            context = database.prepare_feedback_v3_service_context({
                "p_membership_id": str(membership["id"]),
                "p_candidate_id": str(exact["id"]),
                "p_acquisition_principal_id": principal_id,
                "p_idempotency_key": (
                    f"feedback-v3-service-context:{membership['id']}:"
                    f"{exact['id']}"
                ),
            })
            if isinstance(context, dict):
                row["mlc3_service"] = {
                    "project_id": project_id,
                    "take_id": take_id,
                    "membership_id": str(membership["id"]),
                    "candidate_id": str(exact["id"]),
                    "feedback_exposure_id": str(exact["exposure_id"]),
                    "content_identity_sha256": str(
                        membership["content_identity_sha256"]
                    ),
                    "n1_candidate_set_id": str(
                        context["n1_candidate_set_id"]
                    ),
                    "authorization_check_id": str(
                        context["authorization_check_id"]
                    ),
                    "source_acquisition_receipt_id": str(
                        context["source_acquisition_receipt_id"]
                    ),
                }
        visible.append(row)
    return visible
