"""Allowlisted first-client coach guidance and catalogue authoring."""
from __future__ import annotations

import json
import mimetypes
import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from flask import Response, jsonify, request

from config import Config
from routes.admin import require_admin_or_coach
from routes.v2.blueprint import v2_bp
from services.coach_guidance_delivery import (
    inline_authoring_is_enabled,
    require_video_upload,
    runtime_is_enabled,
)
from services.coach_video_storage import require_coach_video_r2
from services.db import db as identity_db
from services.db import first_client_repository as db
from services.mlc3_pilot_storage import (
    CoachVideoR2Storage,
    ReservedObject,
    store_exact_object,
)

_POLICY = "first-client-coach-guidance-v1"
_INLINE_POLICY = "coach-inline-exercise-authoring-d5"


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
    principal = identity_db.get_owner_principal_for_user(user_id) or {}
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


def _store_inline_general_media(
    *,
    video: Any,
    reviewer: str,
    reveal_access_id: str,
    authorization_snapshot_id: str,
    idempotency: str,
) -> str:
    """Store one case-scoped general-guidance video behind the D5 boundary."""
    body = video.read(Config.MLC3_PILOT_MAX_VIDEO_MB * 1024 * 1024 + 1)
    content_type = require_video_upload(
        body=body,
        content_type=video.mimetype or "",
        max_bytes=Config.MLC3_PILOT_MAX_VIDEO_MB * 1024 * 1024,
    )
    bucket = require_coach_video_r2()
    object_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"coach-inline-general:{reviewer}:{reveal_access_id}:{idempotency}",
    ))
    object_key = (
        f"mlc3-coach-inline-general/{reviewer}/{object_id}"
        f"{_extension(video.filename or '', content_type)}"
    )
    finalized: dict[str, Any] = {}
    upload_context: dict[str, Any] = {}

    def reserve(**media: Any) -> ReservedObject:
        row = db.reserve_coach_inline_upload({
            "p_reveal_access_id": reveal_access_id,
            "p_reviewer_principal_id": reviewer,
            "p_authorization_snapshot_id": authorization_snapshot_id,
            "p_purpose_id": "coach_review",
            "p_bucket": bucket,
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
            raise RuntimeError("COACH_INLINE_GENERAL_UPLOAD_RESERVE_FAILED")
        upload_context.update(row)
        return ReservedObject(
            recovery_id=str(row["id"]),
            bucket=str(row["bucket"]),
            object_key=str(row["object_key"]),
            exact_bytes_sha256=str(row["intended_exact_bytes_sha256"]),
            byte_size=int(row["intended_byte_size"]),
            content_type=str(row["content_type"]),
        )

    def upload_event(
        kind: str,
        reserved: ReservedObject,
        media_object_id: str | None = None,
    ) -> None:
        row = db.record_coach_inline_upload_event({
            "p_upload_permit_id": reserved.recovery_id,
            "p_reviewer_principal_id": reviewer,
            "p_event_kind": kind,
            "p_media_object_id": media_object_id,
            "p_idempotency_key": f"{idempotency}:{kind}",
        })
        if not row:
            raise RuntimeError("COACH_INLINE_GENERAL_UPLOAD_EVENT_FAILED")

    def finalize(**media: Any) -> str:
        reserved = media["recovery"]
        media_row = db.register_exercise_media_object({
            "p_bucket": reserved.bucket,
            "p_object_key": reserved.object_key,
            "p_exact_bytes_sha256": reserved.exact_bytes_sha256,
            "p_byte_size": reserved.byte_size,
            "p_content_type": reserved.content_type,
            "p_verification_method": media["verification_method"],
            "p_verified_at": datetime.now(UTC).isoformat(),
            "p_content_authority": "case-scoped-coach-general-guidance",
            "p_created_by": reviewer,
        })
        if not media_row:
            raise RuntimeError("COACH_INLINE_GENERAL_MEDIA_REGISTER_FAILED")
        media_object_id = _uuid(media_row.get("id"), "media_object_id")
        upload_event("finalized", reserved, media_object_id)
        principal_id = _uuid(
            upload_context.get("acquisition_principal_id"),
            "acquisition_principal_id",
        )
        binding = db.register_coach_inline_media({
            "p_media_object_id": media_object_id,
            "p_acquisition_principal_id": principal_id,
            "p_authorization_snapshot_id": authorization_snapshot_id,
            "p_purpose_id": "coach_review",
            "p_provenance_class": "user_scoped",
            "p_source_acquisition_principal_id": principal_id,
            "p_independent_media_review_id": None,
            "p_upload_authorization_id": reserved.recovery_id,
            "p_language_policy_version": _INLINE_POLICY,
            "p_safety_policy_version": _INLINE_POLICY,
            "p_rights_policy_version": _INLINE_POLICY,
            "p_content_review_version": _INLINE_POLICY,
            "p_idempotency_key": f"{idempotency}:media-binding",
        })
        if not binding:
            raise RuntimeError("COACH_INLINE_GENERAL_MEDIA_BIND_FAILED")
        finalized.update(binding)
        return media_object_id

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
    return _uuid(finalized.get("id"), "media_binding_id")


@v2_bp.get("/coach/guidance/batches/<arc_id>")
@require_admin_or_coach
def v2_coach_guidance_batch(arc_id: str):
    from services.confident_moment_bundle import (
        runtime_is_enabled as confident_moment_is_enabled,
    )
    if (
        not runtime_is_enabled()
        and not inline_authoring_is_enabled()
        and not confident_moment_is_enabled()
    ):
        return _disabled_response()
    try:
        project_id = _uuid(arc_id, "project_id")
        reviewer = _reviewer_principal_id()
        if confident_moment_is_enabled():
            from services.confident_moment_bundle_repository import (
                ConfidentMomentBundleRepository,
            )
            bundle_context = ConfidentMomentBundleRepository(
                client_provider=lambda: db.client
            ).project_coach_authoring_context(
                project_id=project_id,
                reviewer_principal_id=reviewer,
                idempotency_key=(
                    f"confident-moment-coach-context:{project_id}:{reviewer}"
                ),
            )
            if not isinstance(bundle_context, dict):
                return _unavailable()
            return jsonify(bundle_context), 200
        if inline_authoring_is_enabled():
            project = db.get_project_identity(project_id)
            if not project:
                return _unavailable()
            owner_principal_id = _uuid(
                project.get("owner_principal_id"),
                "acquisition_principal_id",
            )
            inline_context = db.prepare_coach_inline_guidance_context({
                "p_project_id": project_id,
                "p_acquisition_principal_id": owner_principal_id,
                "p_reviewer_principal_id": reviewer,
                "p_idempotency_key": (
                    f"coach-inline-context:{project_id}:{reviewer}"
                ),
            })
            if not inline_context:
                return _unavailable()
            return jsonify(inline_context), 200
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
            "operation_mode": str(
                getattr(request, "mlc3_operation_mode", "")
                or "allowlisted_service"
            ),
            "synthetic_only": False,
            "serves_user": False,
            "dataset_eligible": False,
        }), 200
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT"}), 400


@v2_bp.post("/coach/guidance/attachments")
@require_admin_or_coach
def v2_coach_guidance_attachment():
    if not runtime_is_enabled() and not inline_authoring_is_enabled():
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
        membership_value = str(form.get("feedback_membership_id") or "").strip()
        candidate_value = str(form.get("feedback_candidate_id") or "").strip()
        if bool(membership_value) != bool(candidate_value):
            raise ValueError("feedback identity pair invalid")
        if attachment_class == "mlc3_exercise" and not membership_value:
            # Reject before authority issuance, upload reservation, or any R2
            # write. Exercises always require the exact frozen V3 identity.
            raise ValueError("exercise feedback identity required")
        inline_general = (
            attachment_class == "general_product_guidance"
            and not membership_value
            and inline_authoring_is_enabled()
        )
        if not runtime_is_enabled() and not inline_general:
            return _disabled_response()
        reveal_access_id = _uuid(
            form.get("reveal_access_id"), "reveal_access_id"
        )
        membership_id = (
            _uuid(membership_value, "feedback_membership_id")
            if membership_value else None
        )
        candidate_id = (
            _uuid(candidate_value, "feedback_candidate_id")
            if candidate_value else None
        )
        review_batch_id = (
            _uuid(form.get("review_batch_id"), "review_batch_id")
            if inline_general else None
        )
        reveal_grant_id = (
            _uuid(form.get("reveal_grant_id"), "reveal_grant_id")
            if inline_general else None
        )
        review_assignment_id = (
            _uuid(form.get("review_assignment_id"), "review_assignment_id")
            if inline_general else None
        )
        authorization_snapshot_id = None
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
        if not written_note and video is None:
            raise ValueError("written note or video required")
        if inline_general:
            authority = db.issue_coach_inline_general_authority({
                "p_review_batch_id": review_batch_id,
                "p_reveal_grant_id": reveal_grant_id,
                "p_reveal_access_id": reveal_access_id,
                "p_review_assignment_id": review_assignment_id,
                "p_reviewer_principal_id": reviewer,
                "p_idempotency_key": f"{idempotency}:authority",
            })
            if not authority:
                raise RuntimeError("COACH_INLINE_GENERAL_AUTHORITY_FAILED")
            authorization_snapshot_id = _uuid(
                authority.get("id"), "authorization_snapshot_id"
            )
        media_binding_id = None
        finalized: dict[str, Any] = {}
        if video is not None and inline_general:
            media_binding_id = _store_inline_general_media(
                video=video,
                reviewer=reviewer,
                reveal_access_id=reveal_access_id,
                authorization_snapshot_id=authorization_snapshot_id,
                idempotency=idempotency,
            )
        elif video is not None:
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
                    "p_bucket": require_coach_video_r2(),
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
        if inline_general:
            row = db.create_coach_inline_general_guidance({
                "p_review_batch_id": review_batch_id,
                "p_reveal_grant_id": reveal_grant_id,
                "p_reveal_access_id": reveal_access_id,
                "p_review_assignment_id": review_assignment_id,
                "p_reviewer_principal_id": reviewer,
                "p_authorization_snapshot_id": authorization_snapshot_id,
                "p_product_subcategory": (
                    str(form.get("product_subcategory") or "").strip() or None
                ),
                "p_written_note": written_note,
                "p_media_binding_id": media_binding_id,
                "p_language_policy_version": _INLINE_POLICY,
                "p_safety_policy_version": _INLINE_POLICY,
                "p_rights_policy_version": _INLINE_POLICY,
                "p_content_review_version": _INLINE_POLICY,
                "p_idempotency_key": f"{idempotency}:attachment",
            })
        else:
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
            "serves_user": not inline_general,
            "dataset_eligible": False,
        }), 201
    except (TypeError, ValueError):
        return jsonify({"code": "INVALID_INPUT"}), 400
    except RuntimeError:
        return _unavailable()


@v2_bp.post("/coach/guidance/exercise-drafts")
@require_admin_or_coach
def v2_coach_inline_exercise_draft():
    """Save one case-bound exercise draft below its exact feedback card.

    The draft is deliberately non-serving and non-dataset. A later reviewed
    transition must create an approved exercise version and a fresh candidate
    inventory before any user can receive it.
    """
    if not inline_authoring_is_enabled():
        return _disabled_response()
    try:
        reviewer = _reviewer_principal_id()
        idempotency = _idempotency_key()
        form = request.form
        reveal_access_id = _uuid(
            form.get("reveal_access_id"), "reveal_access_id"
        )
        membership_id = _uuid(
            form.get("feedback_membership_id"), "feedback_membership_id"
        )
        candidate_id = _uuid(
            form.get("feedback_candidate_id"), "feedback_candidate_id"
        )
        authorization_snapshot_id = _uuid(
            form.get("authorization_snapshot_id"),
            "authorization_snapshot_id",
        )
        offer_id = _uuid(form.get("exercise_offer_id"), "exercise_offer_id")
        need_contract_id = _uuid(
            form.get("need_contract_id"), "need_contract_id"
        )
        title = str(form.get("title") or "").strip()
        instruction = str(form.get("instruction_text") or "").strip()
        language_code = str(form.get("language_code") or "en").strip()
        patterns = [
            value.strip()
            for value in form.getlist("supported_confidence_patterns")
            if value.strip()
        ]
        video = request.files.get("video")
        if (
            not title
            or len(title) > 120
            or not instruction
            or len(instruction) > 2000
            or not patterns
            or video is None
        ):
            raise ValueError("draft fields invalid")
        body = video.read(Config.MLC3_PILOT_MAX_VIDEO_MB * 1024 * 1024 + 1)
        content_type = require_video_upload(
            body=body,
            content_type=video.mimetype or "",
            max_bytes=Config.MLC3_PILOT_MAX_VIDEO_MB * 1024 * 1024,
        )
        bucket = require_coach_video_r2()
        object_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"coach-inline:{reviewer}:{reveal_access_id}:{idempotency}",
        ))
        object_key = (
            f"mlc3-coach-inline/{reviewer}/{object_id}"
            f"{_extension(video.filename or '', content_type)}"
        )
        finalized: dict[str, Any] = {}
        upload_context: dict[str, Any] = {}

        def reserve(**media: Any) -> ReservedObject:
            row = db.reserve_coach_inline_upload({
                "p_reveal_access_id": reveal_access_id,
                "p_reviewer_principal_id": reviewer,
                "p_authorization_snapshot_id": authorization_snapshot_id,
                "p_purpose_id": "personalized_exercise_recommendation",
                "p_bucket": bucket,
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
                raise RuntimeError("COACH_INLINE_UPLOAD_RESERVE_FAILED")
            upload_context.update(row)
            return ReservedObject(
                recovery_id=str(row["id"]),
                bucket=str(row["bucket"]),
                object_key=str(row["object_key"]),
                exact_bytes_sha256=str(row["intended_exact_bytes_sha256"]),
                byte_size=int(row["intended_byte_size"]),
                content_type=str(row["content_type"]),
            )

        def upload_event(
            kind: str, reserved: ReservedObject, media_object_id: str | None = None,
        ) -> None:
            row = db.record_coach_inline_upload_event({
                "p_upload_permit_id": reserved.recovery_id,
                "p_reviewer_principal_id": reviewer,
                "p_event_kind": kind,
                "p_media_object_id": media_object_id,
                "p_idempotency_key": f"{idempotency}:{kind}",
            })
            if not row:
                raise RuntimeError("COACH_INLINE_UPLOAD_EVENT_FAILED")

        def finalize(**media: Any) -> str:
            reserved = media["recovery"]
            media_row = db.register_exercise_media_object({
                "p_bucket": reserved.bucket,
                "p_object_key": reserved.object_key,
                "p_exact_bytes_sha256": reserved.exact_bytes_sha256,
                "p_byte_size": reserved.byte_size,
                "p_content_type": reserved.content_type,
                "p_verification_method": media["verification_method"],
                "p_verified_at": datetime.now(UTC).isoformat(),
                "p_content_authority": "user-source-dependent-coach-draft",
                "p_created_by": reviewer,
            })
            if not media_row:
                raise RuntimeError("COACH_INLINE_MEDIA_REGISTER_FAILED")
            media_object_id = _uuid(media_row.get("id"), "media_object_id")
            upload_event("finalized", reserved, media_object_id)
            acquisition_principal_id = _uuid(
                upload_context.get("acquisition_principal_id"),
                "acquisition_principal_id",
            )
            binding = db.register_coach_inline_media({
                "p_media_object_id": media_object_id,
                "p_acquisition_principal_id": acquisition_principal_id,
                "p_authorization_snapshot_id": authorization_snapshot_id,
                "p_purpose_id": "personalized_exercise_recommendation",
                "p_provenance_class": "user_source_dependent",
                "p_source_acquisition_principal_id": acquisition_principal_id,
                "p_independent_media_review_id": None,
                "p_upload_authorization_id": reserved.recovery_id,
                "p_language_policy_version": _INLINE_POLICY,
                "p_safety_policy_version": _INLINE_POLICY,
                "p_rights_policy_version": _INLINE_POLICY,
                "p_content_review_version": _INLINE_POLICY,
                "p_idempotency_key": f"{idempotency}:media-binding",
            })
            if not binding:
                raise RuntimeError("COACH_INLINE_MEDIA_BIND_FAILED")
            finalized.update(binding)
            return media_object_id

        stored = store_exact_object(
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
        binding_id = _uuid(finalized.get("id"), "media_binding_id")
        # The binding RPC derives and enforces the exact acquisition principal;
        # never trust a browser-provided principal. If registration did not
        # return one, the entire request fails closed before an attachment.
        principal_id = _uuid(
            finalized.get("acquisition_principal_id"),
            "acquisition_principal_id",
        )
        attachment = db.create_coach_inline_attachment({
            "p_reveal_access_id": reveal_access_id,
            "p_reviewer_principal_id": reviewer,
            "p_feedback_membership_id": membership_id,
            "p_feedback_candidate_id": candidate_id,
            "p_authorization_snapshot_id": authorization_snapshot_id,
            "p_written_note": instruction,
            "p_media_binding_id": binding_id,
            "p_exercise_offer_id": offer_id,
            "p_need_contract_id": need_contract_id,
            "p_language_policy_version": _INLINE_POLICY,
            "p_safety_policy_version": _INLINE_POLICY,
            "p_rights_policy_version": _INLINE_POLICY,
            "p_content_review_version": _INLINE_POLICY,
            "p_idempotency_key": f"{idempotency}:attachment",
        })
        if not attachment:
            raise RuntimeError("COACH_INLINE_ATTACHMENT_FAILED")
        draft = db.create_coach_inline_exercise_draft({
            "p_attachment_version_id": str(attachment["id"]),
            "p_reviewer_principal_id": reviewer,
            "p_title": title,
            "p_instruction_text": instruction,
            "p_language_code": language_code,
            "p_supported_confidence_patterns": patterns,
            "p_idempotency_key": f"{idempotency}:draft",
        })
        if not draft:
            raise RuntimeError("COACH_INLINE_DRAFT_FAILED")
        return jsonify({
            "draft_id": str(draft["id"]),
            "state": "awaiting_review",
            "source_role": "source_before_exercise",
            "playback_ref": (
                f"/api/v2/coach/guidance/exercise-drafts/{draft['id']}"
                "/playback"
            ),
            "acquisition_principal_id": principal_id,
            "media_object_id": stored.media_object_id,
            "serves_user": False,
            "dataset_eligible": False,
        }), 201
    except (TypeError, ValueError, KeyError):
        return jsonify({"code": "INVALID_INPUT"}), 400
    except RuntimeError as error:
        return jsonify({"code": str(error)}), 409


@v2_bp.get("/coach/guidance/exercise-drafts/<draft_id>/playback")
@require_admin_or_coach
def v2_coach_inline_exercise_playback(draft_id: str):
    if not inline_authoring_is_enabled():
        return _disabled_response()
    try:
        draft = _uuid(draft_id, "draft_id")
        reviewer = _reviewer_principal_id()
        before = db.resolve_coach_inline_media_read(draft, reviewer)
        if not before:
            return _unavailable()
        body = CoachVideoR2Storage().get(
            bucket=str(before["bucket"]), key=str(before["object_key"])
        )
        if (
            len(body) != int(before["byte_size"])
            or sha256(body).hexdigest() != str(before["exact_bytes_sha256"])
        ):
            return _unavailable()
        after = db.resolve_coach_inline_media_read(draft, reviewer)
        if not after or any(
            str(after.get(key)) != str(before.get(key))
            for key in (
                "media_binding_id", "media_object_id", "bucket", "object_key",
                "exact_bytes_sha256", "byte_size", "content_type",
            )
        ):
            return _unavailable()
        response = Response(body, status=200, mimetype=str(before["content_type"]))
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    except (TypeError, ValueError, KeyError, RuntimeError):
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
