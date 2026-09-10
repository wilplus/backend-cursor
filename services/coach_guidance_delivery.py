"""Coach-guidance and practice pilot boundary.

The released D3 foundation remains dark by default.  The product loop has a
separate two-part gate (global switch plus an exact user/principal allowlist),
while dataset, training, evaluation and promotion are intentionally absent
from this module.  In other words, enabling this service can expose an
exercise, but can never make its evidence learning-eligible.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any


def runtime_is_enabled() -> bool:
    """Return the rollout-aware backend gate; disabled is the default.

    Founder-pilot environment values are deliberately ignored here. Exact
    principal access is decided by the database enrollment resolver.
    """
    from config import Config

    return bool(Config.MLC3_SERVICE_ENABLED)


def inline_authoring_is_enabled() -> bool:
    """Coach draft gate; separate from user serving and learning switches."""
    from config import Config

    return bool(Config.MLC3_COACH_INLINE_AUTHORING_ENABLED)


def principal_is_allowlisted(*, principal_id: str | None) -> bool:
    """Compatibility name for the presentation gate only.

    Database enrollment remains authoritative. This helper cannot authorize a
    principal and intentionally ignores the retired environment allowlist.
    """
    return bool(runtime_is_enabled() and principal_id)


def exact_bytes_sha256(body: bytes) -> str:
    """Fingerprint exact media bytes; this is not a speaker identifier."""
    return sha256(body).hexdigest()


def require_video_upload(
    *, body: bytes, content_type: str, max_bytes: int
) -> str:
    """Validate coach video before an upload permit is requested."""
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if not normalized.startswith("video/"):
        raise ValueError("COACH_GUIDANCE_VIDEO_REQUIRED")
    if not body or len(body) > max_bytes:
        raise ValueError("COACH_GUIDANCE_VIDEO_SIZE_INVALID")
    return normalized


def require_audio_upload(
    *, body: bytes, content_type: str, max_bytes: int
) -> str:
    """Validate a practice recording without interpreting its outcome."""
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if not normalized.startswith("audio/"):
        raise ValueError("PRACTICE_AUDIO_REQUIRED")
    if not body or len(body) > max_bytes:
        raise ValueError("PRACTICE_AUDIO_SIZE_INVALID")
    return normalized


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
