"""Allowlisted first-client coach guidance and catalogue authoring."""
from __future__ import annotations

import json
import mimetypes
import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from flask import jsonify, request

from config import Config
from routes.admin import require_admin_or_coach
from routes.v2.blueprint import v2_bp
from services.coach_guidance_delivery import require_video_upload, runtime_is_enabled
from services.coach_video_storage import r2_bucket_name
from services.db import db
from services.mlc3_pilot_storage import (
    CoachVideoR2Storage,
    ReservedObject,
    store_exact_object,
)

_POLICY = "first-client-coach-guidance-v1"


def _disabled_response():
    return jsonify({"code": "COACH_GUIDANCE_D3_DISABLED"}), 404


def _unavailable():
    return jsonify({"code": "COACH_GUIDANCE_D3_NOT_AVAILABLE"}), 409


def _uuid(value: Any, field: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError(f"{field} must be a UUID") from error


def _reviewer_principal_id() -> str:
    user_id = _uuid(getattr(request, "user_id", None), "reviewer_user_id")
    principal = db.get_owner_principal_for_user(user_id) or {}
    return _uuid(principal.get("id"), "reviewer_principal_id")


def _idempotency_key() -> str:
    value = str(request.headers.get("Idempotency-Key") or "").strip()
    if not 1 <= len(value) <= 160:
        raise ValueError("Idempotency-Key is required")
    return value


def _extension(filename: str, content_type: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix and len(suffix) <= 8:
        return suffix
    return mimetypes.guess_extension(content_type) or ".video"


def _clean_attestation(form: Any) -> bool:
    return str(form.get("independent_clean_media") or "").lower() == "true"


@v2_bp.get("/coach/guidance/batches/<arc_id>")
@require_admin_or_coach
def v2_coach_guidance_batch(arc_id: str):
    if not runtime_is_enabled():
        return _disabled_response()
    try:
        project_id = _uuid(arc_id, "project_id")
        reviewer = _reviewer_principal_id()
        sessions = db.list_exercise_service_review_sessions(project_id)
        if sessions is None:
            return _unavailable()
        items = []
        reveal_grants: list[str] = []
        for session in sessions:
            state = db.freeze_exercise_service_blind_review_set({
                "p_practice_session_id": str(session["id"]),
                "p_reviewer_principal_id": reviewer,
                "p_idempotency_key": (
                    f"first-client-review:{session['id']}:{reviewer}"
                ),
            })
            if not state:
                return _unavailable()
            context = db.get_exercise_service_guidance_context(
                str(state["id"]), reviewer,
            )
            if context is None:
                return _unavailable()
            grant = context["reveal_grant"]
            source_assignment = context["source_assignment"]
            access = db.access_exercise_service_blind_reveal({
                "p_reveal_grant_id": str(grant["id"]),
                "p_reviewer_principal_id": reviewer,
                "p_assignment_id": str(source_assignment["id"]),
                "p_access_purpose": "guidance_authoring",
                "p_idempotency_key": (
                    f"first-client-guidance:{grant['id']}:"
                    f"{source_assignment['id']}:{reviewer}"
                ),
            })
            if not access:
                return _unavailable()
            offer = context["offer"]
            feedback_item = context["feedback_item"]
            features = context.get("features") or {}
            reveal_grants.append(str(grant["id"]))
            items.append({
                "review_batch_id": str(state["id"]),
                "reveal_grant_id": str(grant["id"]),
                "reveal_access_id": str(access["id"]),
                "review_assignment_id": str(source_assignment["id"]),
                "feedback_membership_id": str(offer["feedback_membership_id"]),
                "feedback_candidate_id": str(offer["feedback_candidate_id"]),
                "snippet_id": str(feedback_item["snippet_id"]),
                "legacy_star_key": None,
                "feedback_family": feedback_item["feedback_family"],
                "features": {
                    **(features.get("raw_measurements") or {}),
                    "safeguards": features.get("safeguards") or {},
                    "extractor_version": features.get("extractor_version"),
                    "feature_schema_version": features.get(
                        "feature_schema_version"
                    ),
                },
                "exercise_eligible": (
                    feedback_item["feedback_family"] == "confident_voice"
                ),
                "exercise_offer_id": str(offer["id"]),
                "exercise_version_id": (
                    str(offer["selected_exercise_version_id"])
                    if offer.get("selected_exercise_version_id") else None
                ),
                "need_contract_id": str(context["need_contract_id"]),
            })
        return jsonify({
            "review_batch_id": reveal_grants[0] if reveal_grants else project_id,
            "reveal_grant_id": reveal_grants[0] if reveal_grants else project_id,
            "batch_complete": True,
            "items": items,
            "operation_mode": "allowlisted_service",
            "synthetic_only": False,
            "serves_user": False,
            "dataset_eligible": False,
        }), 200
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT"}), 400


@v2_bp.post("/coach/guidance/attachments")
@require_admin_or_coach
def v2_coach_guidance_attachment():
    if not runtime_is_enabled():
        return _disabled_response()
    try:
        reviewer = _reviewer_principal_id()
        idempotency = _idempotency_key()
        form = request.form
        attachment_class = str(form.get("attachment_class") or "")
        if attachment_class not in {
            "general_product_guidance", "mlc3_exercise",
        }:
            raise ValueError("attachment_class invalid")
        reveal_access_id = _uuid(
            form.get("reveal_access_id"), "reveal_access_id"
        )
        membership_id = _uuid(
            form.get("feedback_membership_id"), "feedback_membership_id"
        )
        candidate_id = _uuid(
            form.get("feedback_candidate_id"), "feedback_candidate_id"
        )
        offer_id = (
            _uuid(form.get("exercise_offer_id"), "exercise_offer_id")
            if form.get("exercise_offer_id") else None
        )
        need_contract_id = (
            _uuid(form.get("need_contract_id"), "need_contract_id")
            if form.get("need_contract_id") else None
        )
        exercise_version_id = (
            _uuid(form.get("exercise_version_id"), "exercise_version_id")
            if form.get("exercise_version_id") else None
        )
        written_note = str(form.get("written_note") or "").strip() or None
        if written_note and len(written_note) > 2000:
            raise ValueError("written_note too long")
        video = request.files.get("video")
        clean = _clean_attestation(form)
        publish_requested = (
            str(form.get("publish_to_catalog") or "").lower() == "true"
        )
        if publish_requested and (
            attachment_class != "mlc3_exercise" or video is None or not clean
        ):
            raise ValueError(
                "catalog publication requires a clean exercise video"
            )
        media_binding_id = None
        finalized: dict[str, Any] = {}
        if video is not None:
            body = video.read(Config.MLC3_PILOT_MAX_VIDEO_MB * 1024 * 1024 + 1)
            content_type = require_video_upload(
                body=body,
                content_type=video.mimetype or "",
                max_bytes=Config.MLC3_PILOT_MAX_VIDEO_MB * 1024 * 1024,
            )
            object_id = str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"coach-guidance:{reviewer}:{reveal_access_id}:{idempotency}",
            ))
            object_key = (
                f"mlc3-coach-guidance/{reviewer}/{object_id}"
                f"{_extension(video.filename or '', content_type)}"
            )
            purpose = (
                "personalized_exercise_recommendation"
                if attachment_class == "mlc3_exercise" else "coach_review"
            )

            def reserve(**media: Any) -> ReservedObject:
                row = db.reserve_coach_guidance_service_upload({
                    "p_reveal_access_id": reveal_access_id,
                    "p_reviewer_principal_id": reviewer,
                    "p_purpose_id": purpose,
                    "p_bucket": r2_bucket_name(),
                    "p_object_key": object_key,
                    "p_intended_exact_bytes_sha256": media["exact_bytes_sha256"],
                    "p_intended_byte_size": media["byte_size"],
                    "p_content_type": media["content_type"],
                    "p_expires_at": (
                        datetime.now(UTC) + timedelta(minutes=15)
                    ).isoformat(),
                    "p_idempotency_key": f"{idempotency}:upload",
                })
                if not row:
                    raise RuntimeError("COACH_GUIDANCE_UPLOAD_RESERVE_FAILED")
                return ReservedObject(
                    recovery_id=str(row["id"]),
                    bucket=str(row["bucket"]),
                    object_key=str(row["object_key"]),
                    exact_bytes_sha256=str(row["intended_exact_bytes_sha256"]),
                    byte_size=int(row["intended_byte_size"]),
                    content_type=str(row["content_type"]),
                )

            def upload_event(kind: str, reserved: ReservedObject) -> None:
                row = db.record_coach_guidance_service_upload_event({
                    "p_upload_permit_id": reserved.recovery_id,
                    "p_reviewer_principal_id": reviewer,
                    "p_event_kind": kind,
                    "p_exact_bytes_sha256": reserved.exact_bytes_sha256,
                    "p_byte_size": reserved.byte_size,
                    "p_idempotency_key": f"{idempotency}:{kind}",
                })
                if not row:
                    raise RuntimeError("COACH_GUIDANCE_UPLOAD_EVENT_FAILED")

            def finalize(**media: Any) -> str:
                evidence_hash = sha256(json.dumps({
                    "clean": clean,
                    "policy": _POLICY,
                    "reviewer": reviewer,
                    "exact_bytes_sha256": media["recovery"].exact_bytes_sha256,
                }, sort_keys=True).encode()).hexdigest()
                row = db.finalize_coach_guidance_service_media({
                    "p_upload_permit_id": media["recovery"].recovery_id,
                    "p_reviewer_principal_id": reviewer,
                    "p_verification_method": media["verification_method"],
                    "p_independent_clean_media": clean,
                    "p_language_policy_version": _POLICY,
                    "p_safety_policy_version": _POLICY,
                    "p_rights_policy_version": _POLICY,
                    "p_content_review_version": _POLICY,
                    "p_review_evidence_sha256": evidence_hash,
                    "p_idempotency_key": f"{idempotency}:finalize",
                })
                if not row:
                    raise RuntimeError("COACH_GUIDANCE_MEDIA_FINALIZE_FAILED")
                finalized.update(row)
                return str(row["media_object_id"])

            store_exact_object(
                body=body,
                content_type=content_type,
                reserve=reserve,
                finalize=finalize,
                storage=CoachVideoR2Storage(),
                record_write_started=lambda reserved: upload_event(
                    "write_started", reserved
                ),
                record_write_acknowledged=lambda reserved: upload_event(
                    "write_acknowledged", reserved
                ),
            )
            media_binding_id = _uuid(
                finalized.get("media_binding_id"), "media_binding_id"
            )
        if not written_note and media_binding_id is None:
            raise ValueError("written note or video required")
        row = db.create_coach_guidance_service_attachment({
            "p_reveal_access_id": reveal_access_id,
            "p_reviewer_principal_id": reviewer,
            "p_feedback_membership_id": membership_id,
            "p_feedback_candidate_id": candidate_id,
            "p_attachment_class": attachment_class,
            "p_product_subcategory": (
                str(form.get("product_subcategory") or "").strip() or None
            ),
            "p_written_note": written_note,
            "p_media_binding_id": media_binding_id,
            "p_exercise_offer_id": offer_id,
            "p_exercise_version_id": exercise_version_id,
            "p_need_contract_id": need_contract_id,
            "p_language_policy_version": _POLICY,
            "p_safety_policy_version": _POLICY,
            "p_rights_policy_version": _POLICY,
            "p_content_review_version": _POLICY,
            "p_idempotency_key": f"{idempotency}:attachment",
        })
        if not row:
            return _unavailable()
        publication = None
        if publish_requested:
            publication = db.publish_coach_guidance_service_exercise({
                "p_source_attachment_version_id": str(row["id"]),
                "p_reviewer_principal_id": reviewer,
                "p_exercise_key": str(form.get("exercise_key") or "").strip(),
                "p_language_code": str(form.get("language_code") or "en"),
                "p_instruction_text": str(
                    form.get("exercise_instruction") or written_note or ""
                ).strip(),
                "p_idempotency_key": f"{idempotency}:publication",
            })
            if not publication:
                return _unavailable()
        return jsonify({
            "attachment_version_id": str(row["id"]),
            "publication_id": str(publication["id"]) if publication else None,
            "serves_user": True,
            "dataset_eligible": False,
        }), 201
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT"}), 400
    except RuntimeError:
        return _unavailable()


@v2_bp.post("/coach/guidance/events")
@require_admin_or_coach
def v2_coach_guidance_event():
    if not runtime_is_enabled():
        return _disabled_response()
    return jsonify({"code": "RECIPIENT_EVENT_REQUIRED"}), 403


@v2_bp.post("/coach/guidance/publications")
@require_admin_or_coach
def v2_coach_guidance_publication():
    if not runtime_is_enabled():
        return _disabled_response()
    return jsonify({"code": "PUBLICATION_REQUIRES_ATTACHMENT_REQUEST"}), 409
