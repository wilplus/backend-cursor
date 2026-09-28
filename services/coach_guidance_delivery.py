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


class AttachmentServiceDisabled(Exception):
    """The form got as far as needing the pilot service, which is off.

    Only inline general guidance runs without it. The route answers with its
    disabled response, at exactly the point it always did: after the class
    and feedback-identity checks, before any id is parsed."""


@dataclass(frozen=True)
class GuidanceAttachmentRequest:
    attachment_class: str
    inline_general: bool
    reveal_access_id: str
    feedback_membership_id: str | None
    feedback_candidate_id: str | None
    review_batch_id: str | None
    reveal_grant_id: str | None
    review_assignment_id: str | None
    exercise_offer_id: str | None
    need_contract_id: str | None
    exercise_version_id: str | None
    written_note: str | None
    independent_clean_media: bool
    publish_to_catalog: bool


def _attachment_route(
    form: Mapping[str, Any], *, runtime_enabled: bool,
    inline_authoring_enabled: bool,
) -> tuple[str, str, str, bool]:
    """Class, feedback pair and which path serves the form: ``(class,
    membership, candidate, inline_general)``, or the service is off."""
    attachment_class = str(form.get("attachment_class") or "")
    if attachment_class not in {"general_product_guidance", "mlc3_exercise"}:
        raise ValueError("attachment_class invalid")
    membership_value = str(form.get("feedback_membership_id") or "").strip()
    candidate_value = str(form.get("feedback_candidate_id") or "").strip()
    if bool(membership_value) != bool(candidate_value):
        raise ValueError("feedback identity pair invalid")
    if attachment_class == "mlc3_exercise" and not membership_value:
        # Rejected before authority issuance, upload reservation or any R2
        # write: exercises always require the exact frozen V3 identity.
        raise ValueError("exercise feedback identity required")
    inline_general = (
        attachment_class == "general_product_guidance"
        and not membership_value
        and inline_authoring_enabled
    )
    if not runtime_enabled and not inline_general:
        raise AttachmentServiceDisabled()
    return attachment_class, membership_value, candidate_value, inline_general


def _attachment_content(
    form: Mapping[str, Any], attachment_class: str, *, has_video: bool,
) -> tuple[str | None, bool, bool]:
    """``(written_note, independent_clean_media, publish_to_catalog)``."""
    written_note = str(form.get("written_note") or "").strip() or None
    if written_note and len(written_note) > 2000:
        raise ValueError("written_note too long")
    clean = str(form.get("independent_clean_media") or "").lower() == "true"
    publish = str(form.get("publish_to_catalog") or "").lower() == "true"
    if publish and (
        attachment_class != "mlc3_exercise" or not has_video or not clean
    ):
        raise ValueError("catalog publication requires a clean exercise video")
    if not written_note and not has_video:
        raise ValueError("written note or video required")
    return written_note, clean, publish


def parse_attachment_request(
    form: Mapping[str, Any],
    *,
    has_video: bool,
    runtime_enabled: bool,
    inline_authoring_enabled: bool,
) -> GuidanceAttachmentRequest:
    """The one reading of a coach-guidance attachment form (audit C4).

    These are the route's rules, in the route's order (founder decision
    2026-09-28: the route wins, inline general guidance keeps working):

      * the class is ``general_product_guidance`` or ``mlc3_exercise``;
      * the feedback membership and candidate ids come as a pair or not at
        all, and an exercise always carries them;
      * general guidance without them is inline authoring, which alone runs
        while the pilot service is off (``AttachmentServiceDisabled``
        otherwise); it needs its batch, grant and assignment ids;
      * every id present is a UUID (``utils.ids.parse_uuid``);
      * a note is at most 2000 characters; a note or a video is required;
      * catalog publication needs a clean exercise video.

    Raises ``ValueError`` for a malformed form, which the route answers with
    ``INVALID_INPUT``. Validates only: no authority, upload or write."""
    from utils.ids import parse_uuid

    attachment_class, membership, candidate, inline_general = _attachment_route(
        form, runtime_enabled=runtime_enabled,
        inline_authoring_enabled=inline_authoring_enabled)

    def inline_id(field: str) -> str | None:
        return parse_uuid(form.get(field), field) if inline_general else None

    def optional_id(field: str) -> str | None:
        return parse_uuid(form.get(field), field) if form.get(field) else None

    reveal_access_id = parse_uuid(form.get("reveal_access_id"), "reveal_access_id")
    membership_id = (
        parse_uuid(membership, "feedback_membership_id") if membership else None
    )
    candidate_id = (
        parse_uuid(candidate, "feedback_candidate_id") if candidate else None
    )
    review_batch_id = inline_id("review_batch_id")
    reveal_grant_id = inline_id("reveal_grant_id")
    review_assignment_id = inline_id("review_assignment_id")
    offer_id = optional_id("exercise_offer_id")
    need_contract_id = optional_id("need_contract_id")
    exercise_version_id = optional_id("exercise_version_id")
    written_note, clean, publish = _attachment_content(
        form, attachment_class, has_video=has_video)
    return GuidanceAttachmentRequest(
        attachment_class=attachment_class,
        inline_general=inline_general,
        reveal_access_id=reveal_access_id,
        feedback_membership_id=membership_id,
        feedback_candidate_id=candidate_id,
        review_batch_id=review_batch_id,
        reveal_grant_id=reveal_grant_id,
        review_assignment_id=review_assignment_id,
        exercise_offer_id=offer_id,
        need_contract_id=need_contract_id,
        exercise_version_id=exercise_version_id,
        written_note=written_note,
        independent_clean_media=clean,
        publish_to_catalog=publish,
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
