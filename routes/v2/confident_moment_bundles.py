"""Confident Moment Coaching Bundle routes (Chunk 3).

All endpoints remain hard-disabled while CONFIDENT_MOMENT_BUNDLE_V1_ENABLED
is false. They reserve the typed HTTP boundary so later activation cannot be
smuggled into an unrelated route.

See Interface Manifest D6 §6.
"""
from __future__ import annotations

import logging
import re
import uuid
from functools import wraps

from flask import Response, jsonify, request

from auth import require_auth
from routes.admin import require_admin_or_coach
from routes.phase2_guard import mlc3_service_required
from routes.v2.blueprint import v2_bp
from services.confident_moment_bundle import (
    ConfidentMomentProjectionInvalid,
    runtime_is_enabled,
    validate_bundle_item_render_receipt,
    validate_coach_update_render_receipt,
    validate_bundle_text_update,
    validate_coach_feedback_language,
    validate_family_response,
    validate_projection_envelope,
    validate_root_action_result,
)
from services.confident_moment_bundle_repository import (
    ConfidentMomentBundleDisabled,
    ConfidentMomentBundleRepository,
)
from services.confident_moment_user_media import (
    ConfidentMomentSourceMediaPolicyInvalid,
    ConfidentMomentUserReadRetry,
    load_confident_moment_source_bytes,
)

logger = logging.getLogger(__name__)


def _disabled():
    return jsonify({"code": "CONFIDENT_MOMENT_BUNDLE_DISABLED"}), 404


def _bundle_gate(function):
    """Reject before auth/enrollment or any database client is reached."""
    @wraps(function)
    def gated(*args, **kwargs):
        if not runtime_is_enabled():
            return _disabled()
        return function(*args, **kwargs)
    return gated


def _coverage_gate(function):
    """Rooting is a distinct kill switch and also fails before authentication."""
    @wraps(function)
    def gated(*args, **kwargs):
        from config import Config
        if not runtime_is_enabled() or not bool(
            getattr(Config, "ROOTING_COVERAGE_V1_ENABLED", False)
        ):
            return _disabled()
        return function(*args, **kwargs)
    return gated


def _repo() -> ConfidentMomentBundleRepository:
    # Lazy import keeps services.db out of module import path for pure tests.
    from services.db import db
    return ConfidentMomentBundleRepository(client_provider=lambda: db.client)


def _uuid(value, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a canonical UUID string")
    try:
        canonical = str(uuid.UUID(value))
    except ValueError as error:
        raise ValueError(f"{field} must be a UUID") from error
    if value != canonical:
        raise ValueError(f"{field} must be a canonical lowercase UUID")
    return value


def _text(value, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    value = value.strip()
    if not value or len(value) > 200:
        raise ValueError(f"{field} is required")
    return value


def _long_text(value, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if not value.strip() or len(value) > 20000:
        raise ValueError(f"{field} is required")
    return value


def _nullable_uuid(value, field: str) -> str | None:
    return None if value is None else _uuid(value, field)


def _positive_int(value, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _nullable_bigint(value, field: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
        raise ValueError(f"{field} must be a canonical positive bigint string")
    parsed = int(value)
    if parsed > 9223372036854775807:
        raise ValueError(f"{field} exceeds PostgreSQL bigint")
    return parsed


def _sha256(value, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError(f"{field} must be lowercase SHA-256")
    return value


def _expected_part_inventory(value) -> list[dict]:
    if not isinstance(value, list):
        raise TypeError("expected_part_inventory must be an array")
    result: list[dict] = []
    for position, raw in enumerate(value):
        if not isinstance(raw, dict) or set(raw) != {
            "position", "part_id", "text_sha256", "locked",
            "current_part_revision_id",
        }:
            raise ValueError("expected_part_inventory item keys invalid")
        if raw.get("position") != position:
            raise ValueError("expected_part_inventory positions invalid")
        if not isinstance(raw.get("locked"), bool):
            raise TypeError("expected_part_inventory locked must be boolean")
        result.append({
            "position": position,
            "part_id": _uuid(raw.get("part_id"), "part_id"),
            "text_sha256": _sha256(raw.get("text_sha256"), "text_sha256"),
            # Keep the wire value a string/null in JSONB. PostgreSQL is the
            # only authority that parses and compares the bigint head.
            "current_part_revision_id": (
                None if raw.get("current_part_revision_id") is None else str(
                    _nullable_bigint(
                        raw.get("current_part_revision_id"),
                        "current_part_revision_id",
                    )
                )
            ),
            "locked": raw["locked"],
        })
    if len({row["part_id"] for row in result}) != len(result):
        raise ValueError("expected_part_inventory duplicate part")
    return result


def _principal_id() -> str:
    return _uuid(getattr(request, "mlc3_principal_id", None), "principal_id")


def _request_object(expected_keys: set[str]) -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise TypeError("JSON object required")
    if set(body) != expected_keys:
        raise ValueError("request keys invalid")
    return body


def _database_error(error: Exception):
    match = re.search(r"\b(CONFIDENT_MOMENT_[A-Z0-9_]+|FEEDBACK_LANGUAGE_[A-Z0-9_]+|IDEAL_TEXT_[A-Z0-9_]+)\b", str(error))
    code = match.group(1) if match else "CONFIDENT_MOMENT_DATABASE_FAILURE"
    status = 409 if code.endswith(("RETRY_REQUIRED", "CONFLICT", "SUPERSEDED")) else 422
    return jsonify({"code": code}), status


def load_confident_moment_projection(project_id: str, take_id: str) -> dict:
    """Return the exact database envelope; never supplement its projection."""
    raw = _repo().project_take_bundles(
        acquisition_principal_id=_principal_id(),
        project_id=_uuid(project_id, "project_id"),
        take_id=_uuid(take_id, "take_id"),
    )
    return validate_projection_envelope(raw)


@v2_bp.get("/explore/arcs/<project_id>/confident-moment-bundles")
@_bundle_gate
@require_auth
@mlc3_service_required
def list_confident_moment_bundles(project_id: str):
    """Return only the canonical database-owned v2 Bundle projection."""
    try:
        envelope = load_confident_moment_projection(
            project_id, request.args.get("take_id") or ""
        )
        return jsonify(envelope["bundle_projection"])
    except (ValueError, ConfidentMomentProjectionInvalid) as error:
        return jsonify({"code": "CONFIDENT_MOMENT_EXACT_IDENTITY_REQUIRED", "error": str(error)}), 400
    except ConfidentMomentBundleDisabled:
        return _disabled()
    except Exception as error:  # noqa: BLE001 - normalize typed PostgREST errors
        return _database_error(error)


@v2_bp.get(
    "/user/confident-moment-bundles/<bundle_id>/attachments/"
    "<bundle_attachment_id>/source-playback"
)
@_bundle_gate
@require_auth
@mlc3_service_required
def get_confident_moment_source_playback(
    bundle_id: str, bundle_attachment_id: str,
):
    """Return exact private source bytes only after fresh phase-3 authority."""
    try:
        bundle = _uuid(bundle_id, "bundle_id")
        attachment = _uuid(bundle_attachment_id, "bundle_attachment_id")
        principal = _principal_id()
        repository = _repo()

        def resolve_authority():
            return repository.resolve_source_playback_authority(
                acquisition_principal_id=principal,
                bundle_id=bundle,
                bundle_attachment_id=attachment,
            )

        def authorize_emit(
            expected_authority_sha256: str,
            buffered_bytes_sha256: str,
            playback_request_id: str,
        ):
            return repository.authorize_source_playback_emit(
                acquisition_principal_id=principal,
                bundle_id=bundle,
                bundle_attachment_id=attachment,
                expected_authority_sha256=expected_authority_sha256,
                buffered_bytes_sha256=buffered_bytes_sha256,
                playback_request_id=playback_request_id,
            )

        body, content_type = load_confident_moment_source_bytes(
            resolve_authority=resolve_authority,
            authorize_emit=authorize_emit,
            principal_id=principal,
            bundle_id=bundle,
            attachment_id=attachment,
        )
        response = Response(body, status=200, mimetype=content_type)
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    except ConfidentMomentSourceMediaPolicyInvalid:
        return jsonify({
            "code": "CONFIDENT_MOMENT_SOURCE_MEDIA_POLICY_INVALID",
        }), 422
    except ConfidentMomentUserReadRetry:
        return jsonify({
            "code": "CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED",
        }), 409
    except (TypeError, ValueError, ConfidentMomentProjectionInvalid) as error:
        return jsonify({
            "code": "CONFIDENT_MOMENT_EXACT_IDENTITY_REQUIRED",
            "error": str(error),
        }), 400
    except ConfidentMomentBundleDisabled:
        return _disabled()
    except Exception as error:  # noqa: BLE001
        return _database_error(error)


@v2_bp.get(
    "/user/mlc3/confident-moment-exercise/<bundle_id>/"
    "<bundle_attachment_id>"
)
@_bundle_gate
@require_auth
@mlc3_service_required
def get_confident_moment_exercise_correlation(
    bundle_id: str, bundle_attachment_id: str,
):
    """Return only a database-derived reference to an existing live offer."""
    try:
        bundle = _uuid(bundle_id, "bundle_id")
        attachment = _uuid(bundle_attachment_id, "bundle_attachment_id")
        result = _repo().resolve_exercise_offer(
            acquisition_principal_id=_principal_id(),
            bundle_id=bundle,
            bundle_attachment_id=attachment,
        )
        response = jsonify(result)
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    except (TypeError, ValueError, ConfidentMomentProjectionInvalid) as error:
        return jsonify({
            "code": "CONFIDENT_MOMENT_EXACT_IDENTITY_REQUIRED",
            "error": str(error),
        }), 400
    except ConfidentMomentBundleDisabled:
        return _disabled()
    except Exception as error:  # noqa: BLE001
        return _database_error(error)


@v2_bp.post("/user/confident-moment-bundles/<bundle_id>/render")
@_bundle_gate
@require_auth
@mlc3_service_required
def ack_confident_moment_bundle_render(bundle_id: str):
    """Visible render acknowledgement (D6 §6.2). Creates/reuses one exposure."""
    try:
        canonical_bundle_id = _uuid(bundle_id, "bundle_id")
        body = _request_object({
            "bundle_attachment_id",
            "feedback_exposure_id",
            "render_instance_id",
            "idempotency_key",
        })
        result = _repo().ack_item_render(
            acquisition_principal_id=_principal_id(),
            bundle_id=canonical_bundle_id,
            bundle_attachment_id=_uuid(body.get("bundle_attachment_id"), "bundle_attachment_id"),
            feedback_exposure_id=_uuid(
                body.get("feedback_exposure_id"), "feedback_exposure_id"
            ),
            render_instance_id=_uuid(body.get("render_instance_id"), "render_instance_id"),
            idempotency_key=_text(body.get("idempotency_key"), "idempotency_key"),
        )
        result = validate_bundle_item_render_receipt(
            result,
            bundle_id=canonical_bundle_id,
            bundle_attachment_id=body["bundle_attachment_id"],
            feedback_exposure_id=body["feedback_exposure_id"],
            render_instance_id=body["render_instance_id"],
        )
        return jsonify(result)
    except (TypeError, ValueError, ConfidentMomentProjectionInvalid) as error:
        return jsonify({"code": "CONFIDENT_MOMENT_EXACT_IDENTITY_REQUIRED", "error": str(error)}), 400
    except ConfidentMomentBundleDisabled:
        return _disabled()
    except Exception as error:  # noqa: BLE001 - normalize typed PostgREST errors
        return _database_error(error)


@v2_bp.post(
    "/user/confident-moment-bundles/<bundle_id>/coach-updates/<revision_id>/render"
)
@_bundle_gate
@require_auth
@mlc3_service_required
def ack_coach_update_render(bundle_id: str, revision_id: str):
    """Coach-update render (D6 §6.4). Independent of accept/cancel."""
    try:
        canonical_bundle_id = _uuid(bundle_id, "bundle_id")
        canonical_revision_id = _uuid(revision_id, "revision_id")
        body = _request_object({
            "bundle_attachment_id",
            "revision_delivery_id",
            "presentation_id",
            "render_instance_id",
            "idempotency_key",
        })
        result = _repo().ack_revision_render(
            recipient_principal_id=_principal_id(),
            bundle_id=canonical_bundle_id,
            bundle_attachment_id=_uuid(body.get("bundle_attachment_id"), "bundle_attachment_id"),
            revision_id=canonical_revision_id,
            revision_delivery_id=_uuid(body.get("revision_delivery_id"), "revision_delivery_id"),
            presentation_id=_uuid(body.get("presentation_id"), "presentation_id"),
            render_instance_id=_uuid(body.get("render_instance_id"), "render_instance_id"),
            idempotency_key=_text(body.get("idempotency_key"), "idempotency_key"),
        )
        result = validate_coach_update_render_receipt(
            result,
            bundle_id=canonical_bundle_id,
            bundle_attachment_id=body["bundle_attachment_id"],
            revision_id=canonical_revision_id,
            revision_delivery_id=body["revision_delivery_id"],
            presentation_id=body["presentation_id"],
            render_instance_id=body["render_instance_id"],
        )
        return jsonify(result)
    except (TypeError, ValueError, ConfidentMomentProjectionInvalid) as error:
        return jsonify({"code": "CONFIDENT_MOMENT_EXACT_IDENTITY_REQUIRED", "error": str(error)}), 400
    except ConfidentMomentBundleDisabled:
        return _disabled()
    except Exception as error:  # noqa: BLE001 - normalize typed PostgREST errors
        return _database_error(error)


@v2_bp.post(
    "/user/confident-moment-bundles/<bundle_id>/attachments/"
    "<bundle_attachment_id>/response"
)
@_bundle_gate
@require_auth
@mlc3_service_required
def record_confident_moment_family_response(
    bundle_id: str, bundle_attachment_id: str,
):
    """Persist exactly one rendered Bundle-family response (D16)."""
    try:
        bundle_id = _uuid(bundle_id, "bundle_id")
        bundle_attachment_id = _uuid(
            bundle_attachment_id, "bundle_attachment_id"
        )
        body = _request_object({
            "feedback_exposure_id", "render_receipt_id", "response",
            "idempotency_key",
        })
        response = body.get("response")
        if response not in {
            "yes", "in_between", "no", "not_sure", "audio_unclear",
            "apply_suggestion", "keep_wording", "useful", "not_useful",
        }:
            raise ValueError("response value invalid")
        result = _repo().record_family_response(
            acquisition_principal_id=_principal_id(),
            bundle_id=bundle_id,
            bundle_attachment_id=bundle_attachment_id,
            feedback_exposure_id=_uuid(
                body.get("feedback_exposure_id"), "feedback_exposure_id"
            ),
            render_receipt_id=_uuid(
                body.get("render_receipt_id"), "render_receipt_id"
            ),
            response=response,
            idempotency_key=_text(body.get("idempotency_key"), "idempotency_key"),
        )
        return jsonify(validate_family_response(
            result, bundle_id=bundle_id, attachment_id=bundle_attachment_id
        ))
    except (TypeError, ValueError, ConfidentMomentProjectionInvalid) as error:
        return jsonify({
            "code": "CONFIDENT_MOMENT_EXACT_IDENTITY_REQUIRED",
            "error": str(error),
        }), 400
    except ConfidentMomentBundleDisabled:
        return _disabled()
    except Exception as error:  # noqa: BLE001
        return _database_error(error)


@v2_bp.post("/user/confident-moment-bundles/<bundle_id>/root-actions")
@_coverage_gate
@require_auth
@mlc3_service_required
def record_confident_moment_root_action(bundle_id: str):
    """Public database-derived root transition; automatic activation is absent."""
    try:
        bundle_id = _uuid(bundle_id, "bundle_id")
        keys = {
            "bundle_attachment_id", "action", "expected_block_head_action_id",
            "source_feedback_exposure_id", "source_owner_response_id",
            "source_practice_attempt_id", "source_ideal_text_revision_id",
            "source_text_update_binding_id", "source_target_speaker_binding_id",
            "practice_target_speaker_binding_id", "restore_product_action_id",
            "policy_version", "idempotency_key",
        }
        body = _request_object(keys)
        action = body.get("action")
        if action not in {
            "save_owner_selected_root", "lock_current_root",
            "restore_previous_root", "unlock_current_root", "remove_current_root",
        }:
            raise ValueError("root action invalid")
        if body.get("policy_version") != "rooting-coverage-30-80-100-v1":
            raise ValueError("root policy invalid")
        attachment_id = _uuid(
            body.get("bundle_attachment_id"), "bundle_attachment_id"
        )
        nullable_source_fields = (
            "source_feedback_exposure_id", "source_owner_response_id",
            "source_practice_attempt_id", "source_ideal_text_revision_id",
            "source_text_update_binding_id", "source_target_speaker_binding_id",
            "practice_target_speaker_binding_id",
        )
        present = {field: body.get(field) is not None for field in nullable_source_fields}
        restore_present = body.get("restore_product_action_id") is not None
        if action in {
            "lock_current_root", "unlock_current_root", "remove_current_root",
        } and (any(present.values()) or restore_present):
            raise ValueError("root action source matrix invalid")
        if action == "restore_previous_root" and (
            not restore_present or any(present.values())
        ):
            raise ValueError("restore source matrix invalid")
        if action == "save_owner_selected_root":
            if restore_present:
                raise ValueError("save cannot carry restore identity")
            if present["source_feedback_exposure_id"] is not present[
                "source_owner_response_id"
            ]:
                raise ValueError("feedback response source pair invalid")
            practice_fields = (
                present["source_practice_attempt_id"],
                present["source_target_speaker_binding_id"],
                present["practice_target_speaker_binding_id"],
            )
            if any(practice_fields) and not all(practice_fields):
                raise ValueError("practice source triple invalid")
            if present["source_text_update_binding_id"] and not present[
                "source_ideal_text_revision_id"
            ]:
                raise ValueError("text update binding requires revision")
            # Exactly one of four frozen source lanes may be selected.  The
            # database derives candidate/evidence/content identity, but the
            # HTTP boundary rejects cross-lane mixtures before any RPC call.
            if present["source_text_update_binding_id"] and (
                present["source_feedback_exposure_id"]
                or present["source_owner_response_id"]
                or any(practice_fields)
            ):
                raise ValueError("accepted Rephrase source matrix invalid")
            if present["source_practice_attempt_id"] and present[
                "source_text_update_binding_id"
            ]:
                raise ValueError("practice/text-update source matrix invalid")
            if not (
                present["source_owner_response_id"]
                or present["source_ideal_text_revision_id"]
                or present["source_practice_attempt_id"]
            ):
                raise ValueError("save requires one exact source")
        result = _repo().record_root_action(
            acquisition_principal_id=_principal_id(),
            bundle_id=bundle_id,
            bundle_attachment_id=attachment_id,
            action=action,
            expected_block_head_action_id=_nullable_uuid(
                body.get("expected_block_head_action_id"),
                "expected_block_head_action_id",
            ),
            source_feedback_exposure_id=_nullable_uuid(
                body.get("source_feedback_exposure_id"),
                "source_feedback_exposure_id",
            ),
            source_owner_response_id=_nullable_uuid(
                body.get("source_owner_response_id"), "source_owner_response_id"
            ),
            source_practice_attempt_id=_nullable_uuid(
                body.get("source_practice_attempt_id"), "source_practice_attempt_id"
            ),
            source_ideal_text_revision_id=_nullable_bigint(
                body.get("source_ideal_text_revision_id"),
                "source_ideal_text_revision_id",
            ),
            source_text_update_binding_id=_nullable_uuid(
                body.get("source_text_update_binding_id"),
                "source_text_update_binding_id",
            ),
            source_target_speaker_binding_id=_nullable_uuid(
                body.get("source_target_speaker_binding_id"),
                "source_target_speaker_binding_id",
            ),
            practice_target_speaker_binding_id=_nullable_uuid(
                body.get("practice_target_speaker_binding_id"),
                "practice_target_speaker_binding_id",
            ),
            restore_product_action_id=_nullable_uuid(
                body.get("restore_product_action_id"), "restore_product_action_id"
            ),
            policy_version=body["policy_version"],
            idempotency_key=_text(body.get("idempotency_key"), "idempotency_key"),
        )
        return jsonify(validate_root_action_result(
            result, bundle_id=bundle_id, attachment_id=attachment_id
        ))
    except (TypeError, ValueError, ConfidentMomentProjectionInvalid) as error:
        return jsonify({
            "code": "CONFIDENT_MOMENT_EXACT_IDENTITY_REQUIRED",
            "error": str(error),
        }), 400
    except ConfidentMomentBundleDisabled:
        return _disabled()
    except Exception as error:  # noqa: BLE001
        return _database_error(error)


@v2_bp.post(
    "/user/confident-moment-bundles/<bundle_id>/attachments/"
    "<bundle_attachment_id>/update-text"
)
@_bundle_gate
@require_auth
@mlc3_service_required
def update_confident_moment_bundle_text(
    bundle_id: str, bundle_attachment_id: str,
):
    """Apply the database-derived accepted Rephrase; browser sends no wording."""
    try:
        bundle_id = _uuid(bundle_id, "bundle_id")
        attachment_id = _uuid(bundle_attachment_id, "bundle_attachment_id")
        body = _request_object({
            "correction_decision_id", "feedback_exposure_id", "render_receipt_id",
            "source_document_snapshot_id", "source_document_version",
            "expected_current_part_revision_id", "expected_user_text_revision",
            "expected_user_text_sha256", "expected_part_inventory",
            "idempotency_key",
        })
        expected_owner_revision = _nullable_bigint(
            body.get("expected_user_text_revision"), "expected_user_text_revision"
        )
        expected_owner_hash = body.get("expected_user_text_sha256")
        if (expected_owner_revision is None) is not (expected_owner_hash is None):
            raise ValueError("expected owner CAS pair invalid")
        if expected_owner_hash is not None:
            expected_owner_hash = _sha256(
                expected_owner_hash, "expected_user_text_sha256"
            )
        result = _repo().update_text(
            owner_user_id=_uuid(getattr(request, "user_id", None), "owner_user_id"),
            bundle_id=bundle_id,
            attachment_id=attachment_id,
            correction_decision_id=_uuid(
                body.get("correction_decision_id"), "correction_decision_id"
            ),
            feedback_exposure_id=_uuid(
                body.get("feedback_exposure_id"), "feedback_exposure_id"
            ),
            render_receipt_id=_uuid(
                body.get("render_receipt_id"), "render_receipt_id"
            ),
            source_document_snapshot_id=_uuid(
                body.get("source_document_snapshot_id"),
                "source_document_snapshot_id",
            ),
            source_document_version=_positive_int(
                body.get("source_document_version"), "source_document_version"
            ),
            expected_current_part_revision_id=_nullable_bigint(
                body.get("expected_current_part_revision_id"),
                "expected_current_part_revision_id",
            ),
            expected_user_text_revision=expected_owner_revision,
            expected_user_text_sha256=expected_owner_hash,
            expected_part_inventory=_expected_part_inventory(
                body.get("expected_part_inventory")
            ),
            idempotency_key=_text(body.get("idempotency_key"), "idempotency_key"),
        )
        return jsonify(validate_bundle_text_update(result))
    except (TypeError, ValueError, ConfidentMomentProjectionInvalid) as error:
        return jsonify({
            "code": "CONFIDENT_MOMENT_EXACT_IDENTITY_REQUIRED",
            "error": str(error),
        }), 400
    except ConfidentMomentBundleDisabled:
        return _disabled()
    except Exception as error:  # noqa: BLE001
        return _database_error(error)


@v2_bp.post(
    "/coach/confident-moment-bundles/<bundle_id>/attachments/"
    "<bundle_attachment_id>/feedback-language"
)
@_bundle_gate
@require_admin_or_coach
def publish_confident_moment_coach_feedback_language(
    bundle_id: str, bundle_attachment_id: str,
):
    """Atomic post-reveal coach wording authoring (D14/D16)."""
    try:
        from services.db import db as identity_db
        bundle = _uuid(bundle_id, "bundle_id")
        attachment = _uuid(bundle_attachment_id, "bundle_attachment_id")
        body = _request_object({
            "review_batch_id", "reveal_grant_id", "reveal_access_id",
            "review_assignment_id", "output_kind", "comment_purpose",
            "revision_text", "expected_current_revision_id",
            "expected_current_delivery_id", "idempotency_key",
        })
        output_kind = body.get("output_kind")
        purpose = body.get("comment_purpose")
        if output_kind == "comment":
            if purpose not in {
                "confidence_explanation", "actionable_observation",
                "positive_praise",
            }:
                raise ValueError("comment_purpose invalid")
        elif output_kind == "rephrase":
            if purpose is not None:
                raise ValueError("rephrase comment_purpose must be null")
        else:
            raise ValueError("output_kind invalid")
        user_id = _uuid(getattr(request, "user_id", None), "reviewer_user_id")
        principal = identity_db.get_owner_principal_for_user(user_id) or {}
        result = _repo().publish_coach_feedback_language(
            reviewer_principal_id=_uuid(
                principal.get("id"), "reviewer_principal_id"
            ),
            bundle_id=bundle,
            bundle_attachment_id=attachment,
            review_batch_id=_uuid(body.get("review_batch_id"), "review_batch_id"),
            reveal_grant_id=_uuid(body.get("reveal_grant_id"), "reveal_grant_id"),
            reveal_access_id=_uuid(body.get("reveal_access_id"), "reveal_access_id"),
            review_assignment_id=_uuid(
                body.get("review_assignment_id"), "review_assignment_id"
            ),
            output_kind=output_kind,
            comment_purpose=purpose,
            revision_text=_long_text(body.get("revision_text"), "revision_text"),
            expected_current_revision_id=_nullable_uuid(
                body.get("expected_current_revision_id"),
                "expected_current_revision_id",
            ),
            expected_current_delivery_id=_nullable_uuid(
                body.get("expected_current_delivery_id"),
                "expected_current_delivery_id",
            ),
            idempotency_key=_text(body.get("idempotency_key"), "idempotency_key"),
        )
        public_payload = validate_coach_feedback_language(
            result.public_payload, bundle_id=bundle, attachment_id=attachment
        )
        if result.materialization_job_id is not None:
            try:
                from services.confident_moment_delivery_worker import (
                    enqueue_confident_moment_delivery,
                )
                enqueue_confident_moment_delivery(
                    result.materialization_job_id
                )
            except Exception as error:  # noqa: BLE001
                logger.warning(
                    "confident-moment delivery wake-up failed: %s", error
                )
        return jsonify(public_payload)
    except (TypeError, ValueError, ConfidentMomentProjectionInvalid) as error:
        return jsonify({
            "code": "CONFIDENT_MOMENT_EXACT_IDENTITY_REQUIRED",
            "error": str(error),
        }), 400
    except ConfidentMomentBundleDisabled:
        return _disabled()
    except Exception as error:  # noqa: BLE001
        return _database_error(error)
