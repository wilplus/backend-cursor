"""Strict transport validation for the database-owned Bundle projection.

PostgreSQL owns subject/anchor selection, Feedback Language currentness, root
state and first-paint summary construction.  This module can reject malformed
transport data, but must never supplement or reinterpret it.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from config import Config

BUNDLE_PROJECTION_VERSION = "confident-moment-coaching-bundle-v2"
BUNDLE_FEEDBACK_LANGUAGE_SHAPE_VERSION = "feedback-language-items-v2"
BUNDLE_CORE_SUMMARY_VERSION = "confident-moment-core-summary-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_RESPONSE_KEYS = {
    "score", "rank", "verdict", "ratio", "qualification",
    "qualification_state", "coach_judgment", "reviewer_id",
    "reviewer_principal_id", "model_prediction", "confidence_score",
}
_RESOLUTION_STATES = {"coach_revision", "machine_fallback", "excluded"}
_OUTPUT_KINDS = {"comment", "rephrase"}
_COMMENT_PURPOSES = {
    "confidence_explanation", "actionable_observation", "positive_praise",
}
_BIGINT_RE = re.compile(r"^[1-9][0-9]*$")
_NONNEGATIVE_BIGINT_RE = re.compile(r"^(0|[1-9][0-9]*)$")
_UTC_MICROSECOND_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:"
    r"[0-9]{2}\.[0-9]{6}Z$"
)


class ConfidentMomentProjectionInvalid(ValueError):
    code = "CONFIDENT_MOMENT_PROJECTION_INVALID"


class ConfidentMomentProjectionRetry(RuntimeError):
    code = "CONFIDENT_MOMENT_PROJECTION_RETRY_REQUIRED"


def runtime_is_enabled() -> bool:
    """Structural kill switch — default false."""
    return bool(getattr(Config, "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED", False))


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfidentMomentProjectionInvalid(f"{field} must be an object")
    return value


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ConfidentMomentProjectionInvalid(f"{field} must be an array")
    return value


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfidentMomentProjectionInvalid(f"{field} must be non-empty")
    return value


def _sha256(value: Any, field: str) -> str:
    value = _required_string(value, field)
    if not _SHA256_RE.fullmatch(value):
        raise ConfidentMomentProjectionInvalid(f"{field} must be SHA-256")
    return value


def _uuid(value: Any, field: str) -> str:
    value = _required_string(value, field)
    try:
        canonical = str(uuid.UUID(value))
    except ValueError as error:
        raise ConfidentMomentProjectionInvalid(f"{field} must be a UUID") from error
    if value != canonical:
        raise ConfidentMomentProjectionInvalid(
            f"{field} must be a canonical lowercase UUID"
        )
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise ConfidentMomentProjectionInvalid(f"{field} keys invalid")


def _bigint_string(value: Any, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not _BIGINT_RE.fullmatch(value):
        raise ConfidentMomentProjectionInvalid(
            f"{field} must be a canonical positive bigint string"
        )
    return value


def _false(value: Any, field: str = "dataset_eligible") -> None:
    if value is not False:
        raise ConfidentMomentProjectionInvalid(f"{field} must be false")


def validate_family_response(value: Any, *, bundle_id: str,
                             attachment_id: str) -> dict[str, Any]:
    result = _object(value, "family response")
    _reject_forbidden_keys(result)
    _exact_keys(result, {
        "family_response_contract_version", "bundle_id",
        "bundle_attachment_id", "feedback_family", "response", "decision_id",
        "owner_response_id", "response_binding_id", "dataset_eligible",
    }, "family response")
    if result["family_response_contract_version"] != (
        "confident-moment-family-response-v1"
    ) or result.get("bundle_id") != bundle_id or result.get(
        "bundle_attachment_id"
    ) != attachment_id:
        raise ConfidentMomentProjectionInvalid("family response identity invalid")
    family = result.get("feedback_family")
    allowed = {
        "confident_voice": {"yes", "in_between", "no", "not_sure", "audio_unclear"},
        "rewrite_clarity": {"apply_suggestion", "keep_wording"},
        "great_formulation": {"useful", "not_useful", "not_sure"},
    }
    if family not in allowed or result.get("response") not in allowed[family]:
        raise ConfidentMomentProjectionInvalid("family response value invalid")
    _uuid(result.get("decision_id"), "decision_id")
    owner = result.get("owner_response_id")
    binding = result.get("response_binding_id")
    if family == "confident_voice":
        _uuid(owner, "owner_response_id")
        _uuid(binding, "response_binding_id")
    elif owner is not None or binding is not None:
        raise ConfidentMomentProjectionInvalid("non-confidence owner identity present")
    _false(result.get("dataset_eligible"))
    return result


def validate_root_action_result(value: Any, *, bundle_id: str,
                                attachment_id: str) -> dict[str, Any]:
    result = _object(value, "root action")
    _reject_forbidden_keys(result)
    _exact_keys(result, {
        "root_action_contract_version", "bundle_id", "bundle_attachment_id",
        "product_action_id", "active_root_action_id",
        "interaction_state_revision", "is_orange", "is_locked",
        "can_restore_previous", "restore_product_action_id", "dataset_eligible",
    }, "root action")
    if result.get("root_action_contract_version") != (
        "confident-moment-root-action-v1"
    ) or result.get("bundle_id") != bundle_id or result.get(
        "bundle_attachment_id"
    ) != attachment_id:
        raise ConfidentMomentProjectionInvalid("root action identity invalid")
    _uuid(result.get("product_action_id"), "product_action_id")
    for field in ("active_root_action_id", "restore_product_action_id"):
        if result.get(field) is not None:
            _uuid(result[field], field)
    _bigint_string(result.get("interaction_state_revision"), "interaction_state_revision")
    for field in ("is_orange", "is_locked", "can_restore_previous"):
        if not isinstance(result.get(field), bool):
            raise ConfidentMomentProjectionInvalid(f"{field} must be boolean")
    if result["is_locked"] and not result["is_orange"]:
        raise ConfidentMomentProjectionInvalid("locked root must be orange")
    if result["can_restore_previous"] is not (
        result["restore_product_action_id"] is not None
    ):
        raise ConfidentMomentProjectionInvalid("restore state invalid")
    _false(result.get("dataset_eligible"))
    return result


def validate_bundle_text_update(value: Any) -> dict[str, Any]:
    result = _object(value, "Bundle text update")
    _reject_forbidden_keys(result)
    _exact_keys(result, {
        "bundle_text_update_contract_version", "binding_id",
        "source_document_snapshot_id", "source_document_version",
        "previous_user_text_revision", "result_user_text_revision",
        "previous_user_text_sha256", "result_user_text_sha256",
        "target_part_id", "result_part_revision_id", "dataset_eligible",
    }, "Bundle text update")
    if result.get("bundle_text_update_contract_version") != "bundle-text-update-v1":
        raise ConfidentMomentProjectionInvalid("text update version invalid")
    for field in ("binding_id", "source_document_snapshot_id", "target_part_id"):
        _uuid(result.get(field), field)
    version = result.get("source_document_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ConfidentMomentProjectionInvalid("source_document_version invalid")
    previous_revision = _bigint_string(
        result.get("previous_user_text_revision"),
        "previous_user_text_revision", nullable=True,
    )
    _bigint_string(result.get("result_user_text_revision"), "result_user_text_revision")
    _bigint_string(result.get("result_part_revision_id"), "result_part_revision_id")
    previous_hash = result.get("previous_user_text_sha256")
    if (previous_revision is None) is not (previous_hash is None):
        raise ConfidentMomentProjectionInvalid("previous owner CAS pair invalid")
    if previous_hash is not None:
        _sha256(previous_hash, "previous_user_text_sha256")
    _sha256(result.get("result_user_text_sha256"), "result_user_text_sha256")
    _false(result.get("dataset_eligible"))
    return result


def validate_coach_feedback_language(value: Any, *, bundle_id: str,
                                     attachment_id: str) -> dict[str, Any]:
    result = _object(value, "coach Feedback Language")
    _reject_forbidden_keys(result)
    _exact_keys(result, {
        "coach_feedback_language_contract_version", "bundle_id",
        "bundle_attachment_id", "revision_id", "revision_sha256", "delivery_id",
        "delivery_state", "target_take_id", "dataset_eligible",
    }, "coach Feedback Language")
    if result.get("coach_feedback_language_contract_version") != (
        "confident-moment-coach-feedback-language-v1"
    ) or result.get("bundle_id") != bundle_id or result.get(
        "bundle_attachment_id"
    ) != attachment_id:
        raise ConfidentMomentProjectionInvalid("coach response identity invalid")
    _uuid(result.get("revision_id"), "revision_id")
    _sha256(result.get("revision_sha256"), "revision_sha256")
    nullable = (result.get("delivery_id"), result.get("delivery_state"),
                result.get("target_take_id"))
    if all(item is None for item in nullable):
        pass
    elif all(item is not None for item in nullable):
        _uuid(result["delivery_id"], "delivery_id")
        _uuid(result["target_take_id"], "target_take_id")
        if result["delivery_state"] not in {
            "scheduled_current_take", "scheduled_next_take",
        }:
            raise ConfidentMomentProjectionInvalid("delivery state invalid")
    else:
        raise ConfidentMomentProjectionInvalid("partial delivery result")
    _false(result.get("dataset_eligible"))
    return result


def validate_coach_authoring_context(value: Any) -> dict[str, Any]:
    """Validate only D17's additive Bundle authoring objects.

    The surrounding object remains the already-reviewed D5 context contract.
    This validator deliberately does not reconstruct or normalize it; it
    rejects a malformed Bundle extension and otherwise returns the database
    response byte-for-byte at the Python object boundary.
    """
    context = _object(value, "coach authoring context")

    found: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if "blind_judgment_id" in node:
                raise ConfidentMomentProjectionInvalid(
                    "coach context exposes blind judgment identity"
                )
            if "bundle_context" in node:
                raise ConfidentMomentProjectionInvalid(
                    "obsolete Bundle authoring context shape"
                )
            bundle_context = node.get("bundle_authoring_context")
            if bundle_context is not None:
                found.append(_object(bundle_context, "bundle_authoring_context"))
            for child in node.values():
                if child is not bundle_context:
                    visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(context)
    seen_sources: set[str] = set()
    seen_targets: set[str] = set()
    for authoring in found:
        _reject_forbidden_keys(authoring)
        _exact_keys(authoring, {
            "bundle_id", "source_review_attachment_id", "authorized_targets",
        }, "bundle_authoring_context")
        _uuid(authoring.get("bundle_id"), "bundle_authoring_context.bundle_id")
        source_id = _uuid(
            authoring.get("source_review_attachment_id"),
            "bundle_authoring_context.source_review_attachment_id",
        )
        if source_id in seen_sources:
            raise ConfidentMomentProjectionInvalid(
                "duplicate Bundle authoring source"
            )
        seen_sources.add(source_id)
        targets = _list(
            authoring.get("authorized_targets"),
            "bundle_authoring_context.authorized_targets",
        )
        for raw in targets:
            target = _object(raw, "authorized_target")
            _exact_keys(target, {
                "bundle_attachment_id", "review_assignment_id",
                "reveal_access_id", "feedback_family",
                "allowed_output_kind", "allowed_comment_purpose",
                "source_passage", "expected_current_revision_id",
                "expected_current_delivery_id",
            }, "authorized_target")
            target_id = _uuid(
                target.get("bundle_attachment_id"),
                "authorized_target.bundle_attachment_id",
            )
            _uuid(
                target.get("review_assignment_id"),
                "authorized_target.review_assignment_id",
            )
            _uuid(
                target.get("reveal_access_id"),
                "authorized_target.reveal_access_id",
            )
            if target_id in seen_targets:
                raise ConfidentMomentProjectionInvalid(
                    "duplicate Bundle authoring target"
                )
            seen_targets.add(target_id)
            family = target.get("feedback_family")
            output_kind = target.get("allowed_output_kind")
            purpose = target.get("allowed_comment_purpose")
            allowed = {
                ("confident_voice", "comment", "confidence_explanation"),
                ("rewrite_clarity", "rephrase", None),
                ("rewrite_clarity", "comment", "actionable_observation"),
                ("great_formulation", "comment", "positive_praise"),
            }
            if (family, output_kind, purpose) not in allowed:
                raise ConfidentMomentProjectionInvalid(
                    "Bundle authoring family/output matrix invalid"
                )
            passage = _object(target.get("source_passage"), "source_passage")
            _exact_keys(
                passage, {"evidence_span_id", "text", "text_sha256"},
                "source_passage",
            )
            _uuid(passage.get("evidence_span_id"), "source_passage.evidence_span_id")
            _required_string(passage.get("text"), "source_passage.text")
            _sha256(passage.get("text_sha256"), "source_passage.text_sha256")
            for field in (
                "expected_current_revision_id", "expected_current_delivery_id",
            ):
                if target.get(field) is not None:
                    _uuid(target[field], f"authorized_target.{field}")
    return context


def validate_owner_edit_transport(value: Any) -> dict[str, Any]:
    """Validate D22/D24 recursively closed Ideal Text editor state."""
    owner = _object(value, "owner_edit")
    _exact_keys(owner, {
        "text", "source_document_version", "user_text_revision",
        "user_text_sha256", "parts", "current_bundle_text_update_binding",
    }, "owner_edit")
    parts = _list(owner.get("parts"), "owner_edit.parts")
    if owner.get("text") is None:
        if any(owner.get(key) is not None for key in (
            "source_document_version", "user_text_revision", "user_text_sha256",
            "current_bundle_text_update_binding",
        )) or parts:
            raise ConfidentMomentProjectionInvalid("owner_edit empty state invalid")
        return owner
    _required_string(owner.get("text"), "owner_edit.text")
    version = owner.get("source_document_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ConfidentMomentProjectionInvalid("owner source version invalid")
    _bigint_string(owner.get("user_text_revision"), "user_text_revision")
    _sha256(owner.get("user_text_sha256"), "user_text_sha256")
    seen: set[str] = set()
    for expected_ord, raw in enumerate(parts):
        part = _object(raw, "owner_edit.part")
        _exact_keys(part, {
            "id", "ord", "text", "locked", "current_part_revision_id",
        }, "owner_edit.part")
        part_id = _uuid(part.get("id"), "part.id")
        if part_id in seen or part.get("ord") != expected_ord:
            raise ConfidentMomentProjectionInvalid("owner part inventory invalid")
        seen.add(part_id)
        if not isinstance(part.get("text"), str) or not isinstance(
            part.get("locked"), bool
        ):
            raise ConfidentMomentProjectionInvalid("owner part state invalid")
        _bigint_string(
            part.get("current_part_revision_id"),
            "current_part_revision_id", nullable=True,
        )
    binding = owner.get("current_bundle_text_update_binding")
    if binding is not None:
        binding = _object(binding, "current_bundle_text_update_binding")
        _exact_keys(binding, {
            "binding_id", "bundle_id", "attachment_id",
            "source_document_version", "result_user_text_revision",
            "result_user_text_sha256", "result_part_revision_id",
        }, "current_bundle_text_update_binding")
        for field in ("binding_id", "bundle_id", "attachment_id"):
            _uuid(binding.get(field), field)
        if binding.get("source_document_version") != version:
            raise ConfidentMomentProjectionInvalid("Bundle binding version mismatch")
        if binding.get("result_user_text_revision") != owner["user_text_revision"]:
            raise ConfidentMomentProjectionInvalid("Bundle binding revision mismatch")
        if binding.get("result_user_text_sha256") != owner["user_text_sha256"]:
            raise ConfidentMomentProjectionInvalid("Bundle binding hash mismatch")
        _bigint_string(
            binding.get("result_part_revision_id"), "result_part_revision_id"
        )
    return owner


def _validate_core_summary(value: Any, *, snapshot_id: str) -> dict[str, Any]:
    summary = _object(value, "confident_moment_summary")
    _reject_forbidden_keys(summary)
    _exact_keys(summary, {
        "contract_version", "document_snapshot_id", "items", "summary_sha256",
    }, "confident_moment_summary")
    if summary.get("contract_version") != BUNDLE_CORE_SUMMARY_VERSION:
        raise ConfidentMomentProjectionInvalid("unknown summary contract version")
    if _uuid(
        summary.get("document_snapshot_id"),
        "summary.document_snapshot_id",
    ) != snapshot_id:
        raise ConfidentMomentProjectionInvalid("summary snapshot mismatch")
    _list(summary.get("items"), "summary.items")
    _sha256(summary.get("summary_sha256"), "summary.summary_sha256")
    return summary


def validate_ideal_text_core_v2(value: Any) -> dict[str, Any]:
    """Validate D29's exact database-owned core-read envelope."""
    envelope = _object(value, "ideal_text core v2")
    _reject_forbidden_keys(envelope)
    _exact_keys(envelope, {
        "ideal_text_core_read_contract_version", "snapshot",
        "dynamic_overlay", "read_sha256",
    }, "ideal_text core v2")
    if envelope.get("ideal_text_core_read_contract_version") != (
        "ideal-text-document-core-v2"
    ):
        raise ConfidentMomentProjectionInvalid("core read version invalid")

    snapshot = _object(envelope.get("snapshot"), "snapshot")
    _exact_keys(snapshot, {
        "id", "arc_id", "actor_id", "acquisition_principal_id",
        "project_id", "source_take_session_id", "version",
        "source_generation", "source_fingerprint_sha256", "payload_sha256",
        "payload", "enrichment_seed", "supersedes_id", "created_at",
    }, "snapshot")
    for field in (
        "id", "acquisition_principal_id", "project_id",
        "source_take_session_id",
    ):
        _uuid(snapshot.get(field), f"snapshot.{field}")
    for field in ("arc_id", "actor_id"):
        value = snapshot.get(field)
        if not isinstance(value, str) or value == "":
            raise ConfidentMomentProjectionInvalid(
                f"snapshot.{field} must be non-empty exact text"
            )
    version = snapshot.get("version")
    if (
        isinstance(version, bool) or not isinstance(version, int)
        or version < 1 or version > 2_147_483_647
    ):
        raise ConfidentMomentProjectionInvalid("snapshot.version invalid")
    generation = snapshot.get("source_generation")
    if (
        not isinstance(generation, str)
        or not _NONNEGATIVE_BIGINT_RE.fullmatch(generation)
        or int(generation) > 9_223_372_036_854_775_807
    ):
        raise ConfidentMomentProjectionInvalid(
            "snapshot.source_generation must be a canonical bigint string"
        )
    _sha256(
        snapshot.get("source_fingerprint_sha256"),
        "snapshot.source_fingerprint_sha256",
    )
    _sha256(snapshot.get("payload_sha256"), "snapshot.payload_sha256")
    _object(snapshot.get("payload"), "snapshot.payload")
    _object(snapshot.get("enrichment_seed"), "snapshot.enrichment_seed")
    if snapshot.get("supersedes_id") is not None:
        _uuid(snapshot["supersedes_id"], "snapshot.supersedes_id")
    created_at = snapshot.get("created_at")
    if not isinstance(created_at, str) or not _UTC_MICROSECOND_RE.fullmatch(
        created_at
    ):
        raise ConfidentMomentProjectionInvalid(
            "snapshot.created_at must be six-digit UTC RFC3339"
        )

    overlay = _object(envelope.get("dynamic_overlay"), "dynamic_overlay")
    _exact_keys(overlay, {
        "owner_edit", "confident_moment_summary",
        "confident_moment_summary_status",
    }, "dynamic_overlay")
    validate_owner_edit_transport(overlay.get("owner_edit"))
    status = _object(
        overlay.get("confident_moment_summary_status"),
        "confident_moment_summary_status",
    )
    _exact_keys(status, {"state", "code", "retryable"}, "summary status")
    state = status.get("state")
    if state not in {"disabled", "unavailable", "available"}:
        raise ConfidentMomentProjectionInvalid("summary status state invalid")
    code = status.get("code")
    if code is not None and (
        not isinstance(code, str) or not code.strip()
    ):
        raise ConfidentMomentProjectionInvalid("summary status code invalid")
    if not isinstance(status.get("retryable"), bool):
        raise ConfidentMomentProjectionInvalid("summary retryable invalid")
    summary = overlay.get("confident_moment_summary")
    if state == "available":
        if summary is None or code is not None or status["retryable"]:
            raise ConfidentMomentProjectionInvalid("available summary state invalid")
        _validate_core_summary(summary, snapshot_id=snapshot["id"])
    elif summary is not None:
        raise ConfidentMomentProjectionInvalid("unavailable summary must be null")
    elif state == "disabled" and (code is not None or status["retryable"]):
        raise ConfidentMomentProjectionInvalid("disabled summary state invalid")
    _sha256(envelope.get("read_sha256"), "read_sha256")
    return envelope


def _reject_forbidden_keys(value: Any) -> None:
    if isinstance(value, dict):
        forbidden = _FORBIDDEN_RESPONSE_KEYS.intersection(value)
        if forbidden:
            raise ConfidentMomentProjectionInvalid(
                f"forbidden response field: {min(forbidden)}"
            )
        for child in value.values():
            _reject_forbidden_keys(child)
    elif isinstance(value, list):
        for child in value:
            _reject_forbidden_keys(child)


def _validate_render_receipt(
    value: Any,
    *,
    contract_version: str,
    expected_keys: set[str],
    echoed_identities: dict[str, str],
    receipt_identity_fields: tuple[str, ...],
    required_inequality_pairs: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    """Validate one closed D13 render receipt and return it unchanged."""
    receipt = _object(value, "render receipt")
    _reject_forbidden_keys(receipt)
    _exact_keys(receipt, expected_keys, "render receipt")
    if receipt.get("render_contract_version") != contract_version:
        raise ConfidentMomentProjectionInvalid("render contract version invalid")
    if receipt.get("dataset_eligible") is not False:
        raise ConfidentMomentProjectionInvalid(
            "render receipt must be dataset-ineligible"
        )
    for field in receipt_identity_fields:
        _uuid(receipt.get(field), field)
    for left, right in required_inequality_pairs:
        if receipt[left] == receipt[right]:
            raise ConfidentMomentProjectionInvalid(
                f"render receipt {left}/{right} identities overlap"
            )
    for field, expected in echoed_identities.items():
        if receipt.get(field) != expected:
            raise ConfidentMomentProjectionInvalid(
                f"render receipt {field} does not match request"
            )
    return receipt


def validate_bundle_item_render_receipt(
    value: Any,
    *,
    bundle_id: str,
    bundle_attachment_id: str,
    feedback_exposure_id: str,
    render_instance_id: str,
) -> dict[str, Any]:
    """Validate the exact Bundle-item v3 receipt from PostgreSQL."""
    return _validate_render_receipt(
        value,
        contract_version="confident-moment-bundle-item-render-v3",
        expected_keys={
            "render_contract_version",
            "bundle_id",
            "bundle_attachment_id",
            "feedback_exposure_id",
            "render_instance_id",
            "render_receipt_id",
            "dataset_eligible",
        },
        echoed_identities={
            "bundle_id": bundle_id,
            "bundle_attachment_id": bundle_attachment_id,
            "feedback_exposure_id": feedback_exposure_id,
            "render_instance_id": render_instance_id,
        },
        receipt_identity_fields=(
            "bundle_id",
            "bundle_attachment_id",
            "feedback_exposure_id",
            "render_instance_id",
            "render_receipt_id",
        ),
        required_inequality_pairs=((
            "render_receipt_id", "feedback_exposure_id",
        ),),
    )


def validate_coach_update_render_receipt(
    value: Any,
    *,
    bundle_id: str,
    bundle_attachment_id: str,
    revision_id: str,
    revision_delivery_id: str,
    presentation_id: str,
    render_instance_id: str,
) -> dict[str, Any]:
    """Validate the exact Feedback Language coach-update v3 receipt."""
    return _validate_render_receipt(
        value,
        contract_version="feedback-language-revision-render-v3",
        expected_keys={
            "render_contract_version",
            "bundle_id",
            "bundle_attachment_id",
            "current_revision_id",
            "revision_delivery_id",
            "presentation_id",
            "render_instance_id",
            "rendered_exposure_id",
            "dataset_eligible",
        },
        echoed_identities={
            "bundle_id": bundle_id,
            "bundle_attachment_id": bundle_attachment_id,
            "current_revision_id": revision_id,
            "revision_delivery_id": revision_delivery_id,
            "presentation_id": presentation_id,
            "render_instance_id": render_instance_id,
        },
        receipt_identity_fields=(
            "bundle_id",
            "bundle_attachment_id",
            "current_revision_id",
            "revision_delivery_id",
            "presentation_id",
            "render_instance_id",
            "rendered_exposure_id",
        ),
        required_inequality_pairs=((
            "presentation_id", "rendered_exposure_id",
        ),),
    )
def validate_projection_envelope(value: Any) -> dict[str, Any]:
    """Validate and return the exact v2 RPC envelope without enriching it."""
    envelope = _object(value, "projection envelope")
    _reject_forbidden_keys(envelope)
    _exact_keys(
        envelope,
        {"bundle_projection", "confident_moment_summary"},
        "projection envelope",
    )
    projection = _object(envelope["bundle_projection"], "bundle_projection")
    summary = _object(envelope["confident_moment_summary"], "summary")
    _exact_keys(projection, {
        "contract_version", "feedback_language_shape_version", "project_id",
        "take_id", "document_snapshot_id", "feedback_membership_id", "bundles",
        "coverage", "response_sha256",
    }, "bundle_projection")
    _exact_keys(summary, {
        "contract_version", "document_snapshot_id", "items", "summary_sha256",
    }, "summary")
    if projection.get("contract_version") != BUNDLE_PROJECTION_VERSION:
        raise ConfidentMomentProjectionInvalid("unknown bundle contract version")
    if projection.get("feedback_language_shape_version") != BUNDLE_FEEDBACK_LANGUAGE_SHAPE_VERSION:
        raise ConfidentMomentProjectionInvalid("unknown Feedback Language shape")
    if summary.get("contract_version") != BUNDLE_CORE_SUMMARY_VERSION:
        raise ConfidentMomentProjectionInvalid("unknown summary contract version")
    if projection.get("document_snapshot_id") != summary.get("document_snapshot_id"):
        raise ConfidentMomentProjectionInvalid("projection/summary snapshot mismatch")
    for key in (
        "project_id", "take_id", "document_snapshot_id", "feedback_membership_id",
    ):
        _uuid(projection.get(key), key)
    _sha256(projection.get("response_sha256"), "response_sha256")
    _sha256(summary.get("summary_sha256"), "summary_sha256")
    coverage = _object(projection.get("coverage"), "coverage")
    _exact_keys(coverage, {
        "target_slide_count", "achieved_slide_count", "target_met",
    }, "coverage")
    target = coverage.get("target_slide_count")
    achieved = coverage.get("achieved_slide_count")
    if (
        not isinstance(target, int) or isinstance(target, bool) or target < 0
        or not isinstance(achieved, int) or isinstance(achieved, bool)
        or achieved < 0
        or not isinstance(coverage.get("target_met"), bool)
        or coverage["target_met"] is not (target > 0 and achieved >= target)
    ):
        raise ConfidentMomentProjectionInvalid("coverage state invalid")
    bundles = _list(projection.get("bundles"), "bundles")
    seen_bundles: set[str] = set()
    seen_attachments: set[str] = set()
    seen_candidates: set[str] = set()
    seen_feedback_exposures: set[str] = set()
    seen_revisions: set[str] = set()
    seen_deliveries: set[str] = set()
    seen_presentations: set[str] = set()
    seen_exposures: set[str] = set()
    previous_bundle_bytes: bytes | None = None
    for bundle in bundles:
        bundle = _object(bundle, "bundle")
        _exact_keys(bundle, {
            "bundle_id", "bundle_subject_kind", "slide_index", "block_key",
            "paragraph_id", "subject", "confidence_anchor",
            "feedback_language_items", "exercise", "root", "state_revision",
        }, "bundle")
        bundle_id = _uuid(bundle.get("bundle_id"), "bundle_id")
        if bundle_id in seen_bundles:
            raise ConfidentMomentProjectionInvalid("duplicate bundle_id")
        bundle_bytes = uuid.UUID(bundle_id).bytes
        if previous_bundle_bytes is not None and bundle_bytes <= previous_bundle_bytes:
            raise ConfidentMomentProjectionInvalid("Bundle order invalid")
        previous_bundle_bytes = bundle_bytes
        seen_bundles.add(bundle_id)
        subject_kind = bundle.get("bundle_subject_kind")
        if subject_kind not in {"confidence_anchor", "no_anchor_paragraph_trigger"}:
            raise ConfidentMomentProjectionInvalid("bundle_subject_kind invalid")
        slide_index = bundle.get("slide_index")
        block_key = bundle.get("block_key")
        state_revision = bundle.get("state_revision")
        if any(
            not isinstance(item, int) or isinstance(item, bool) or item < 0
            for item in (slide_index, block_key)
        ) or not isinstance(state_revision, int) or isinstance(state_revision, bool) or state_revision < 1:
            raise ConfidentMomentProjectionInvalid("bundle numeric identity invalid")
        _uuid(bundle.get("paragraph_id"), "paragraph_id")
        subject = _object(bundle.get("subject"), "subject")
        _exact_keys(subject, {
            "candidate_id", "evidence_span_id", "canonical_feedback_presentation_id",
        }, "subject")
        subject_candidate = _uuid(subject.get("candidate_id"), "subject.candidate_id")
        _uuid(subject.get("evidence_span_id"), "subject.evidence_span_id")
        subject_feedback_exposure_id = _uuid(
            subject.get("canonical_feedback_presentation_id"),
            "subject.canonical_feedback_presentation_id",
        )
        if subject_candidate != bundle_id:
            raise ConfidentMomentProjectionInvalid("bundle/subject identity mismatch")
        anchor = bundle.get("confidence_anchor")
        if subject_kind == "confidence_anchor":
            anchor = _object(anchor, "confidence_anchor")
            _exact_keys(anchor, {
                "candidate_id", "evidence_span_id", "playback_reference_id",
            }, "confidence_anchor")
            if _uuid(anchor.get("candidate_id"), "anchor.candidate_id") != bundle_id:
                raise ConfidentMomentProjectionInvalid("confidence anchor mismatch")
            anchor_evidence_id = _uuid(
                anchor.get("evidence_span_id"), "anchor.evidence_span_id"
            )
            if anchor_evidence_id != subject["evidence_span_id"]:
                raise ConfidentMomentProjectionInvalid(
                    "confidence anchor evidence mismatch"
                )
            _required_string(anchor.get("playback_reference_id"), "playback_reference_id")
        elif anchor is not None:
            raise ConfidentMomentProjectionInvalid("no-anchor bundle has confidence anchor")
        root = _object(bundle.get("root"), "root")
        _exact_keys(root, {
            "active_root_action_id", "interaction_state_revision",
            "is_orange", "is_locked", "can_restore_previous",
            "restore_product_action_id",
        }, "root")
        if any(not isinstance(root[key], bool) for key in (
            "is_orange", "is_locked", "can_restore_previous",
        )):
            raise ConfidentMomentProjectionInvalid("root state invalid")
        for field in ("active_root_action_id", "restore_product_action_id"):
            if root.get(field) is not None:
                _uuid(root[field], f"root.{field}")
        _bigint_string(
            root.get("interaction_state_revision"),
            "root.interaction_state_revision",
        )
        if root["can_restore_previous"] is not (
            root["restore_product_action_id"] is not None
        ):
            raise ConfidentMomentProjectionInvalid("root restore state invalid")
        if root["is_locked"] and not root["is_orange"]:
            raise ConfidentMomentProjectionInvalid("locked root must be orange")
        if subject_kind == "no_anchor_paragraph_trigger" and (
            root["is_orange"] or root["is_locked"] or root["can_restore_previous"]
        ):
            raise ConfidentMomentProjectionInvalid("no-anchor bundle has root affordance")
        items = _list(bundle.get("feedback_language_items"), "feedback_language_items")
        positions: list[int] = []
        for item in items:
            item = _object(item, "feedback_language_item")
            _exact_keys(item, {
                "bundle_attachment_id", "attached_candidate_id",
                "feedback_family", "canonical_feedback_exposure_id",
                "canonical_position", "resolution_state", "exclusion_reason",
                "source_passage", "update_text_available",
                "coach_authoring_exclusion_reason", "output", "coach_update",
                "owner_decision",
            }, "feedback_language_item")
            attachment_id = _uuid(
                item.get("bundle_attachment_id"), "bundle_attachment_id"
            )
            if attachment_id in seen_attachments:
                raise ConfidentMomentProjectionInvalid("duplicate bundle attachment")
            seen_attachments.add(attachment_id)
            candidate_id = _uuid(item.get("attached_candidate_id"), "attached_candidate_id")
            if candidate_id in seen_candidates:
                raise ConfidentMomentProjectionInvalid("duplicate attached candidate")
            seen_candidates.add(candidate_id)
            family = item.get("feedback_family")
            if family not in {
                "confident_voice", "rewrite_clarity", "great_formulation",
            }:
                raise ConfidentMomentProjectionInvalid("feedback_family invalid")
            feedback_exposure_id = _uuid(
                item.get("canonical_feedback_exposure_id"),
                "canonical_feedback_exposure_id",
            )
            if (
                feedback_exposure_id in seen_feedback_exposures
                or feedback_exposure_id in seen_presentations
                or feedback_exposure_id in seen_exposures
            ):
                raise ConfidentMomentProjectionInvalid(
                    "duplicate canonical Feedback exposure"
                )
            seen_feedback_exposures.add(feedback_exposure_id)
            position = item.get("canonical_position")
            if not isinstance(position, int) or isinstance(position, bool) or position < 1:
                raise ConfidentMomentProjectionInvalid("canonical_position invalid")
            positions.append(position)
            source_passage = _object(item.get("source_passage"), "source_passage")
            _exact_keys(source_passage, {
                "evidence_span_id", "text", "text_sha256",
            }, "source_passage")
            _uuid(source_passage.get("evidence_span_id"), "source_passage.evidence_span_id")
            _required_string(source_passage.get("text"), "source_passage.text")
            _sha256(source_passage.get("text_sha256"), "source_passage.text_sha256")
            if not isinstance(item.get("update_text_available"), bool):
                raise ConfidentMomentProjectionInvalid("update_text_available invalid")
            if item.get("coach_authoring_exclusion_reason") not in {
                None, "source_audio_unavailable",
            }:
                raise ConfidentMomentProjectionInvalid(
                    "coach authoring exclusion invalid"
                )
            resolution = item.get("resolution_state")
            if resolution not in _RESOLUTION_STATES:
                raise ConfidentMomentProjectionInvalid("resolution_state invalid")
            output = item.get("output")
            coach_update = item.get("coach_update")
            owner_decision = item.get("owner_decision")
            if resolution == "excluded":
                if (
                    output is not None or coach_update is not None
                    or owner_decision is not None
                    or item.get("exclusion_reason") not in {
                        "delivery_explicitly_invalidated", "machine_output_invalid",
                    }
                ):
                    raise ConfidentMomentProjectionInvalid("excluded item shape invalid")
                continue
            if item.get("exclusion_reason") is not None:
                raise ConfidentMomentProjectionInvalid("resolved item has exclusion")
            output = _object(output, "output")
            _exact_keys(
                output,
                {"output_kind", "comment_purpose", "text", "origin"},
                "output",
            )
            kind = output.get("output_kind")
            if kind not in _OUTPUT_KINDS or output.get("origin") not in {"machine", "coach"}:
                raise ConfidentMomentProjectionInvalid("typed output invalid")
            _required_string(output.get("text"), "output.text")
            purpose = output.get("comment_purpose")
            if (kind == "comment" and purpose not in _COMMENT_PURPOSES) or (
                kind == "rephrase" and purpose is not None
            ):
                raise ConfidentMomentProjectionInvalid("output purpose invalid")
            if (
                family == "confident_voice"
                and (kind, purpose) != ("comment", "confidence_explanation")
            ) or (
                family == "great_formulation"
                and (kind, purpose) != ("comment", "positive_praise")
            ) or (
                family == "rewrite_clarity"
                and (kind, purpose) not in {
                    ("rephrase", None),
                    ("comment", "actionable_observation"),
                }
            ):
                raise ConfidentMomentProjectionInvalid(
                    "Feedback family/output mismatch"
                )
            if resolution == "machine_fallback":
                if coach_update is not None or output.get("origin") != "machine":
                    raise ConfidentMomentProjectionInvalid("machine fallback shape invalid")
            else:
                coach_update = _object(coach_update, "coach_update")
                _exact_keys(coach_update, {
                    "current_revision_id", "revision_sha256", "revision_delivery_id",
                    "delivery_subject_sha256", "presentation_id",
                    "rendered_exposure_id", "unread",
                }, "coach_update")
                if output.get("origin") != "coach" or not isinstance(coach_update.get("unread"), bool):
                    raise ConfidentMomentProjectionInvalid("coach update shape invalid")
                revision_id = _uuid(coach_update.get("current_revision_id"), "current_revision_id")
                delivery_id = _uuid(coach_update.get("revision_delivery_id"), "revision_delivery_id")
                presentation_id = _uuid(coach_update.get("presentation_id"), "presentation_id")
                if presentation_id in seen_feedback_exposures:
                    raise ConfidentMomentProjectionInvalid(
                        "Feedback exposure used as coach presentation"
                    )
                if revision_id in seen_revisions or delivery_id in seen_deliveries or presentation_id in seen_presentations:
                    raise ConfidentMomentProjectionInvalid("cross-item coach identity reused")
                seen_revisions.add(revision_id)
                seen_deliveries.add(delivery_id)
                seen_presentations.add(presentation_id)
                _sha256(coach_update.get("revision_sha256"), "revision_sha256")
                _sha256(coach_update.get("delivery_subject_sha256"), "delivery_subject_sha256")
                exposure = coach_update.get("rendered_exposure_id")
                if exposure is not None:
                    exposure = _uuid(exposure, "rendered_exposure_id")
                    if (
                        exposure in seen_exposures
                        or exposure in seen_feedback_exposures
                    ):
                        raise ConfidentMomentProjectionInvalid("cross-item exposure reused")
                    seen_exposures.add(exposure)
                if coach_update["unread"] is not (exposure is None):
                    raise ConfidentMomentProjectionInvalid("coach unread/exposure mismatch")
            if owner_decision is not None:
                owner_decision = _object(owner_decision, "owner_decision")
                _exact_keys(owner_decision, {
                    "feedback_family", "response", "decision_id",
                    "owner_response_id", "response_binding_id",
                }, "owner_decision")
                if owner_decision.get("feedback_family") != family:
                    raise ConfidentMomentProjectionInvalid(
                        "owner decision family mismatch"
                    )
                allowed = {
                    "confident_voice": {
                        "yes", "in_between", "no", "not_sure",
                        "audio_unclear",
                    },
                    "rewrite_clarity": {
                        "apply_suggestion", "keep_wording",
                    },
                    "great_formulation": {
                        "useful", "not_useful", "not_sure",
                    },
                }
                if owner_decision.get("response") not in allowed[family]:
                    raise ConfidentMomentProjectionInvalid(
                        "owner decision response invalid"
                    )
                _uuid(owner_decision.get("decision_id"), "owner_decision.decision_id")
                owner_response_id = owner_decision.get("owner_response_id")
                response_binding_id = owner_decision.get("response_binding_id")
                if family == "confident_voice":
                    _uuid(owner_response_id, "owner_decision.owner_response_id")
                    _uuid(response_binding_id, "owner_decision.response_binding_id")
                elif owner_response_id is not None or response_binding_id is not None:
                    raise ConfidentMomentProjectionInvalid(
                        "non-confidence owner decision has confidence identity"
                    )
        if positions != sorted(positions) or len(positions) != len(set(positions)):
            raise ConfidentMomentProjectionInvalid("Feedback Language order invalid")
        subject_items = [
            item for item in items
            if item["attached_candidate_id"] == subject_candidate
        ]
        if (
            len(subject_items) != 1
            or subject_items[0]["canonical_feedback_exposure_id"]
            != subject_feedback_exposure_id
        ):
            raise ConfidentMomentProjectionInvalid(
                "subject attachment Feedback exposure mismatch"
            )
        if bundle.get("exercise", object()) is not None:
            raise ConfidentMomentProjectionInvalid("exercise must be null")
    summary_items = _list(summary.get("items"), "summary.items")
    if len(summary_items) != len(bundles):
        raise ConfidentMomentProjectionInvalid("summary cardinality invalid")
    summary_ids: list[str] = []
    for index, row in enumerate(summary_items):
        row = _object(row, "summary.item")
        _exact_keys(row, {
            "bundle_id", "paragraph_id", "slide_index", "block_key",
            "marker_present", "is_orange", "is_locked",
            "has_coach_update", "has_unread_coach_update", "state_revision",
        }, "summary.item")
        bundle = bundles[index]
        summary_id = _uuid(row.get("bundle_id"), "summary.bundle_id")
        summary_ids.append(summary_id)
        if (
            _uuid(row.get("paragraph_id"), "summary.paragraph_id")
            != bundle["paragraph_id"]
            or row.get("slide_index") != bundle["slide_index"]
            or row.get("block_key") != bundle["block_key"]
            or row.get("marker_present") is not True
            or row.get("is_orange") is not bundle["root"]["is_orange"]
            or row.get("is_locked") is not bundle["root"]["is_locked"]
            or row.get("state_revision") != bundle["state_revision"]
        ):
            raise ConfidentMomentProjectionInvalid("summary state mismatch")
        expected_unread = any(
            item["resolution_state"] == "coach_revision"
            and item["coach_update"]["unread"] is True
            for item in bundle["feedback_language_items"]
        )
        if row.get("has_unread_coach_update") is not expected_unread:
            raise ConfidentMomentProjectionInvalid("summary unread state mismatch")
        expected_update = any(
            item["resolution_state"] == "coach_revision"
            for item in bundle["feedback_language_items"]
        )
        if row.get("has_coach_update") is not expected_update or (
            row.get("has_unread_coach_update") is True
            and row.get("has_coach_update") is not True
        ):
            raise ConfidentMomentProjectionInvalid("summary coach state mismatch")
    if summary_ids != [str(row["bundle_id"]) for row in bundles]:
        raise ConfidentMomentProjectionInvalid("summary bundle order invalid")
    return envelope
