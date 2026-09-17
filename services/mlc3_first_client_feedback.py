"""Fail-closed preparation of allowlisted Feedback V3 product rows.

This module is a product integration seam, not a learning producer.  It
creates a fresh service candidate inventory, freezes it against the current
Ideal Text snapshot, and adds exercise context only where an independently
frozen N1 inventory already exists for the exact clip.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from hashlib import sha256
from typing import Any
import uuid

from services.coach_guidance_delivery import principal_is_allowlisted
from services.feedback_data_contract import build_feedback_exposure_bundle
from services.take_feedback_policy_v3 import build_service_candidate_frame
from services.take_feedback_policy_v3_service import prepare_v3_service_inventory


logger = logging.getLogger(__name__)


def _decline(take_id: Any, reason: str) -> list[dict] | None:
    """Say WHY v3 stood down, then stand down.

    FOUNDER 2026-09-17, after an afternoon of log searches that found
    nothing: "please make the V3 finally work." It could not be made to
    work because it could not be diagnosed — this function is fail-closed
    by design, with TWELVE separate `return None` exits, and not one of
    them said anything. The surface simply fell back to v2 and the only
    evidence was an absence.

    Fail-closed is right and stays. Fail-SILENT is not the same thing and
    was never intended: refusing to serve a candidate you cannot prove is a
    safety property, refusing to say which proof was missing is just a
    missing log line. Every exit now names itself once per attempt.

    INFO, not WARNING: standing down is the designed behaviour, not a
    fault. `first_client` in the backend log is now a complete account of
    why this take is on v2 rather than v3.
    """
    logger.info("first_client: v3 stood down take=%s reason=%s",
                take_id or "?", reason)
    # Typed as the CALLER's return so `return _decline(...)` reads as one
    # statement at each of the twelve exits. `-> None` made every one of them
    # a mypy error ("does not return a value"), and splitting them into a log
    # line plus a bare `return None` is twenty-four lines in which one exit
    # can quietly lose its log again — the exact failure this function exists
    # to prevent.
    return None


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
        return _decline(take_id, "not_allowlisted_or_identity_incomplete")
    enrollment = database.ensure_service_enrollment(
        acquisition_principal_id=principal_id,
        owner_user_id=str(owner_user_id),
        idempotency_key=f"feedback-entry:{take_id}",
    )
    if not isinstance(enrollment, dict) or not enrollment.get("id"):
        return _decline(take_id, "service_enrollment_missing")
    # D20 snapshot-first boundary. Immutable evidence coordinates may only be
    # produced after PostgreSQL identifies the exact current source surface.
    try:
        snapshot_result = database.client.rpc(
            "read_feedback_v3_candidate_source_snapshot_v1",
            {
                "p_acquisition_principal_id": principal_id,
                "p_project_id": project_id,
                "p_take_id": take_id,
            },
        ).execute()
        source_snapshot = getattr(snapshot_result, "data", snapshot_result)
    except Exception:
        return _decline(take_id, "source_snapshot_rpc_failed")
    if not isinstance(source_snapshot, dict) or set(source_snapshot) != {
        "snapshot_contract_version", "document_snapshot_id",
        "source_generation", "surface", "surface_sha256",
    }:
        return _decline(take_id, "source_snapshot_shape_unexpected")
    try:
        snapshot_id = str(uuid.UUID(str(source_snapshot.get(
            "document_snapshot_id"
        ))))
    except (TypeError, ValueError, AttributeError):
        return _decline(take_id, "source_snapshot_id_not_a_uuid")
    source_generation = source_snapshot.get("source_generation")
    if (
        source_snapshot.get("snapshot_contract_version")
        != "feedback-v3-candidate-source-snapshot-v1"
        or snapshot_id != source_snapshot.get("document_snapshot_id")
        or not isinstance(source_generation, int)
        or isinstance(source_generation, bool)
        or source_generation < 1
        or source_snapshot.get("surface") != served_text
        or source_snapshot.get("surface_sha256")
        != sha256(served_text.encode("utf-8")).hexdigest()
    ):
        return _decline(take_id, "source_snapshot_does_not_match_served_text")
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
        return _decline(take_id, "service_inventory_unavailable")
    bundle = build_feedback_exposure_bundle(
        session=take,
        transcript_document=take_document,
        served_text=served_text,
        candidates=inventory["candidates"],
        selected_keys=inventory["selected_keys"],
        manager_rules_version="take-feedback-policy-v3-serving-v1",
        document_snapshot_id=str(source_snapshot["document_snapshot_id"]),
        document_surface_sha256=str(source_snapshot["surface_sha256"]),
    )
    if bundle is None or len(bundle.get("candidates") or []) != len(
        inventory["membership_items"]
    ):
        return _decline(take_id, "exposure_bundle_membership_count_mismatch")
    candidate_result = database.record_feedback_v3_service_candidate_set(bundle)
    if (
        not isinstance(candidate_result, dict)
        or str(candidate_result.get("candidate_set_id") or "")
        != str(bundle["candidate_set_id"])
    ):
        return _decline(take_id, "candidate_set_write_failed")
    canonical = _canonical_index(bundle)
    membership_items: list[dict] = []
    for raw in inventory["membership_items"]:
        row = dict(raw)
        item = canonical.get((row["feedback_family"], row["candidate_key"]))
        if item is None:
            return _decline(take_id, "membership_candidate_not_in_bundle")
        row["candidate_id"] = item["id"]
        membership_items.append(row)
    membership = database.freeze_feedback_v3_service_membership({
        "p_acquisition_principal_id": principal_id,
        "p_project_id": project_id,
        "p_take_id": take_id,
        "p_candidate_set_id": bundle["candidate_set_id"],
        "p_document_snapshot_id": str(source_snapshot["document_snapshot_id"]),
        "p_block_partition_version": inventory["block_partition_version"],
        "p_items": membership_items,
        "p_idempotency_key": (
            f"feedback-v3-service-membership:{bundle['candidate_set_id']}:"
            f"{source_snapshot['document_snapshot_id']}"
        ),
    })
    if not isinstance(membership, dict) or not membership.get("id"):
        return _decline(take_id, "membership_freeze_failed")

    visible: list[dict] = []
    for raw in inventory["visible_rows"]:
        row = dict(raw)
        family = str(row.get("feedback_family") or "")
        key = str(row.get("id") or "")
        exact = canonical.get((family, key))
        if exact is None:
            return _decline(take_id, "visible_row_candidate_not_in_bundle")
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
