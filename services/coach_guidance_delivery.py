"""Disabled D3 coach-guidance boundary.

The persistence contract is executable in synthetic rehearsals, while this
module deliberately exposes no production activation path.  Keeping the gate
literal prevents a configuration typo from turning product evidence into live
delivery or ML supervision.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


COACH_GUIDANCE_D3_RUNTIME_ENABLED = False


def runtime_is_enabled() -> bool:
    """Return the reviewed gate state; D3 is local/synthetic only."""
    return COACH_GUIDANCE_D3_RUNTIME_ENABLED


@dataclass(frozen=True)
class GuidanceAttachmentRequest:
    review_batch_id: str
    reveal_grant_id: str
    reveal_access_id: str
    review_assignment_id: str
    feedback_membership_id: str
    feedback_candidate_id: str
    attachment_class: str
    written_note: str | None
    media_binding_id: str | None
    exercise_offer_id: str | None
    exercise_version_id: str | None
    need_contract_id: str | None
    product_subcategory: str | None


def parse_attachment_request(payload: Mapping[str, Any]) -> GuidanceAttachmentRequest:
    """Validate the browser contract without inferring an acoustic need."""
    required = (
        "review_batch_id",
        "reveal_grant_id",
        "reveal_access_id",
        "review_assignment_id",
        "feedback_membership_id",
        "feedback_candidate_id",
    )
    values = {key: str(payload.get(key) or "").strip() for key in required}
    if any(not value for value in values.values()):
        raise ValueError("COACH_GUIDANCE_EXACT_IDENTITY_REQUIRED")
    attachment_class = str(payload.get("attachment_class") or "").strip()
    if attachment_class not in {"general_product_guidance", "mlc3_exercise"}:
        raise ValueError("COACH_GUIDANCE_ATTACHMENT_CLASS_INVALID")
    subcategory = payload.get("product_subcategory")
    if subcategory not in {None, "structure", "delivery"}:
        raise ValueError("COACH_GUIDANCE_SUBCATEGORY_INVALID")
    note = str(payload.get("written_note") or "").strip() or None
    media_binding_id = str(payload.get("media_binding_id") or "").strip() or None
    if note is None and media_binding_id is None:
        raise ValueError("COACH_GUIDANCE_CONTENT_REQUIRED")
    offer_id = str(payload.get("exercise_offer_id") or "").strip() or None
    version_id = str(payload.get("exercise_version_id") or "").strip() or None
    need_id = str(payload.get("need_contract_id") or "").strip() or None
    if attachment_class == "general_product_guidance" and any(
        (offer_id, version_id, need_id)
    ):
        raise ValueError("COACH_GUIDANCE_GENERAL_EXERCISE_FIELDS_FORBIDDEN")
    if attachment_class == "mlc3_exercise" and (offer_id is None or need_id is None):
        raise ValueError("COACH_GUIDANCE_APPROVED_NEED_AND_INVENTORY_REQUIRED")
    return GuidanceAttachmentRequest(
        **values,
        attachment_class=attachment_class,
        written_note=note,
        media_binding_id=media_binding_id,
        exercise_offer_id=offer_id,
        exercise_version_id=version_id,
        need_contract_id=need_id,
        product_subcategory=subcategory,
    )


def synthetic_context_payload(
    *, review_batch_id: str, reveal_grant_id: str, items: list[dict[str, Any]]
) -> dict[str, Any]:
    """Shape synthetic fixtures without exposing a score or model verdict."""
    return {
        "review_batch_id": review_batch_id,
        "reveal_grant_id": reveal_grant_id,
        "batch_complete": True,
        "items": items,
        "synthetic_only": True,
        "serves_user": False,
        "dataset_eligible": False,
    }
