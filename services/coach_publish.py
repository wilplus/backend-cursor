"""Canonical, atomic professional-review publishing.

This module is deliberately free of Flask, email, queue and UI concerns.  It
validates the complete final snapshot supplied by the coach and delegates the
single durable write to one database transaction.  Everything derived from a
published revision is described as outbox metadata and runs after success.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import uuid
from typing import Any, Mapping

from services.canonical_product import CoachReviewState, FeedbackFamily


class PublishReviewError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code = code
        self.status = status


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PublishReviewError("INVALID_INPUT", f"{field} is required", 400)
    return text


def _non_negative_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise PublishReviewError("INVALID_FEEDBACK_ITEM", f"{field} must be a non-negative integer")
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise PublishReviewError("INVALID_FEEDBACK_ITEM", f"{field} must be a non-negative integer")
    if number < 0:
        raise PublishReviewError("INVALID_FEEDBACK_ITEM", f"{field} must be a non-negative integer")
    return number


def _normalize_interval(value: Any) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise PublishReviewError("INVALID_FEEDBACK_ITEM", "audio_interval must be an object")
    start = _non_negative_int(value.get("start_ms"), "audio_interval.start_ms")
    end = _non_negative_int(value.get("end_ms"), "audio_interval.end_ms")
    if end <= start:
        raise PublishReviewError("INVALID_FEEDBACK_ITEM", "audio_interval.end_ms must be after start_ms")
    return {"start_ms": start, "end_ms": end}


def _normalize_span(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PublishReviewError("INVALID_FEEDBACK_ITEM", "evidence_span must be an object")
    start = _non_negative_int(value.get("start"), "evidence_span.start")
    end = _non_negative_int(value.get("end"), "evidence_span.end")
    if end <= start:
        raise PublishReviewError("INVALID_FEEDBACK_ITEM", "evidence_span.end must be after start")
    return {"start": start, "end": end, "text": _required_text(value.get("text"), "evidence_span.text")}


def _normalize_feedback_item(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PublishReviewError("INVALID_FEEDBACK_ITEM", "feedback_items entries must be objects")
    try:
        family = FeedbackFamily(str(value.get("family")))
    except ValueError:
        raise PublishReviewError("INVALID_FEEDBACK_ITEM", "feedback item has an unknown family")
    raw_state = value.get("review_state")
    review_state = None
    if raw_state is not None:
        try:
            review_state = CoachReviewState(str(raw_state))
        except ValueError:
            raise PublishReviewError("INVALID_FEEDBACK_ITEM", "feedback item has an unknown review_state")
    evidence = value.get("evidence")
    if not isinstance(evidence, Mapping):
        raise PublishReviewError("INVALID_FEEDBACK_ITEM", "feedback item evidence is required")
    audio_interval = _normalize_interval(evidence.get("audio_interval"))
    if family == FeedbackFamily.CONFIDENT_VOICE and audio_interval is None:
        raise PublishReviewError("INVALID_FEEDBACK_ITEM", "Confident Voice requires a playable audio interval")
    replacement = value.get("replacement_text")
    if family == FeedbackFamily.REWRITE_FOR_CLARITY:
        replacement = _required_text(replacement, "replacement_text")
    elif replacement is not None:
        replacement = str(replacement).strip() or None
    piece_id = str(evidence.get("piece_id") or "").strip() or None
    if family == FeedbackFamily.CONFIDENT_VOICE and piece_id is None:
        raise PublishReviewError("INVALID_FEEDBACK_ITEM", "Confident Voice requires an exact clip id")
    return {
        "id": _required_text(value.get("id"), "feedback item id"),
        "family": family.value,
        "message": _required_text(value.get("message"), "feedback item message"),
        "review_state": review_state.value if review_state else None,
        "replacement_text": replacement,
        "evidence": {
            "project_id": _required_text(evidence.get("project_id"), "evidence.project_id"),
            "take_id": _required_text(evidence.get("take_id"), "evidence.take_id"),
            "slide_index": _non_negative_int(evidence.get("slide_index"), "evidence.slide_index"),
            "paragraph_index": _non_negative_int(evidence.get("paragraph_index"), "evidence.paragraph_index"),
            "evidence_span": _normalize_span(evidence.get("evidence_span")),
            "audio_interval": audio_interval,
            "piece_id": piece_id,
        },
    }


@dataclass(frozen=True)
class PublishReviewCommand:
    session_id: str
    idempotency_key: str
    overall_message: str | None
    feedback_items: tuple[dict[str, Any], ...]
    share_video: bool

    @classmethod
    def from_payload(cls, payload: Any) -> "PublishReviewCommand":
        if not isinstance(payload, Mapping):
            raise PublishReviewError("INVALID_INPUT", "Publish payload must be an object", 400)
        if "feedback_items" not in payload:
            raise PublishReviewError("INVALID_INPUT", "feedback_items is a required complete final snapshot", 400)
        raw_items = payload.get("feedback_items")
        if not isinstance(raw_items, list):
            raise PublishReviewError("INVALID_INPUT", "feedback_items must be an array", 400)
        overall = payload.get("overall_message")
        if overall is not None:
            overall = str(overall).strip() or None
        return cls(
            session_id=_required_text(payload.get("session_id"), "session_id"),
            idempotency_key=_required_text(payload.get("idempotency_key"), "idempotency_key"),
            overall_message=overall,
            feedback_items=tuple(_normalize_feedback_item(item) for item in raw_items),
            share_video=payload.get("share_video") is True,
        )

    def payload_hash(self) -> str:
        canonical = json.dumps({
            "session_id": self.session_id,
            "overall_message": self.overall_message,
            "feedback_items": self.feedback_items,
            "share_video": self.share_video,
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PublishReviewResult:
    revision_id: str
    revision_number: int
    published_at: str
    replayed: bool
    side_effects_pending: bool = True


def _validate_exact_evidence(command: PublishReviewCommand, project_id: str) -> None:
    for item in command.feedback_items:
        evidence = item["evidence"]
        if evidence["take_id"] != command.session_id:
            raise PublishReviewError("EVIDENCE_SCOPE_MISMATCH", "Every feedback item must reference the exact take")
        if evidence["project_id"] != project_id:
            raise PublishReviewError("EVIDENCE_SCOPE_MISMATCH", "Every feedback item must reference the exact project")


def _delivery_payload(command: PublishReviewCommand) -> dict[str, Any]:
    material_items = [
        item for item in command.feedback_items
        if item.get("review_state") == CoachReviewState.MATERIAL_CORRECTION.value
    ]
    voice_clips: list[str] = []
    for item in command.feedback_items:
        if item["family"] != FeedbackFamily.CONFIDENT_VOICE.value:
            continue
        clip_id = item["evidence"].get("piece_id")
        if clip_id and clip_id not in voice_clips:
            voice_clips.append(clip_id)
    return {
        "material_correction_item_ids": [item["id"] for item in material_items],
        "material_corrections": material_items,
        "voice_album_clip_ids": voice_clips,
        "share_video": command.share_video,
    }


def publish_review(
    database,
    command: PublishReviewCommand,
    *,
    actor_user_id: str,
    actor_is_admin: bool = False,
    admin_override_reason: str | None = None,
) -> PublishReviewResult:
    return publish_reviews(
        database,
        [command],
        actor_user_id=actor_user_id,
        actor_is_admin=actor_is_admin,
        admin_override_reason=admin_override_reason,
    )[0]


def _prepared_revision(
    database,
    command: PublishReviewCommand,
    *,
    actor_user_id: str,
    actor_is_admin: bool,
    admin_override_reason: str | None,
) -> dict[str, Any]:
    session = database.v2_get_session_by_id(command.session_id) or {}
    if not session:
        raise PublishReviewError("NOT_FOUND", "Take not found", 404)
    if not session.get("user_id"):
        raise PublishReviewError("UNCLAIMED_GUEST", "A guest take must be claimed before coach review can be published", 409)
    project_id = str(session.get("project_id") or session.get("arc_id") or "")
    if not project_id:
        raise PublishReviewError("MISSING_PROJECT", "Take is not bound to a project", 409)
    _validate_exact_evidence(command, project_id)

    actor = _required_text(actor_user_id, "actor_user_id")
    assigned = str(session.get("coach_review_assigned_to") or "").strip()
    override_reason = str(admin_override_reason or "").strip() or None
    is_override = bool(actor_is_admin and assigned and assigned != actor)
    if assigned and assigned != actor and not actor_is_admin:
        raise PublishReviewError("REVIEW_ASSIGNED_TO_ANOTHER_COACH", "Only the assigned coach can publish this review", 403)
    if is_override and not override_reason:
        raise PublishReviewError("ADMIN_OVERRIDE_REASON_REQUIRED", "Admin override requires an audit reason", 422)

    return {
        "revision_id": str(uuid.uuid4()),
        "session_id": command.session_id,
        "owner_user_id": str(session["user_id"]),
        "project_id": project_id,
        "actor_user_id": actor,
        "actor_is_admin": bool(actor_is_admin),
        "admin_override_reason": override_reason,
        "idempotency_key": command.idempotency_key,
        "payload_hash": command.payload_hash(),
        "feedback_items": [dict(item) for item in command.feedback_items],
        "overall_message": command.overall_message,
        "share_video": command.share_video,
        "delivery_payload": _delivery_payload(command),
    }


def publish_reviews(
    database,
    commands: list[PublishReviewCommand],
    *,
    actor_user_id: str,
    actor_is_admin: bool = False,
    admin_override_reason: str | None = None,
) -> list[PublishReviewResult]:
    """Publish a complete set of takes in one all-or-nothing transaction."""
    if not commands:
        raise PublishReviewError(
            "INVALID_INPUT", "At least one review is required", 400,
        )
    session_ids = [command.session_id for command in commands]
    if len(set(session_ids)) != len(session_ids):
        raise PublishReviewError(
            "DUPLICATE_TAKE", "Each take may appear only once", 422,
        )
    prepared = [
        _prepared_revision(
            database,
            command,
            actor_user_id=actor_user_id,
            actor_is_admin=actor_is_admin,
            admin_override_reason=admin_override_reason,
        )
        for command in commands
    ]
    persisted = database.publish_coach_review_revisions(prepared) or []
    if len(persisted) != len(prepared):
        raise PublishReviewError(
            "PUBLISH_FAILED", "The complete review set was not published", 500,
        )
    return [
        PublishReviewResult(
            revision_id=str(row["revision_id"]),
            revision_number=int(row.get("revision_number") or 1),
            published_at=str(row.get("published_at") or ""),
            replayed=bool(row.get("replayed")),
        )
        for row in persisted
    ]
