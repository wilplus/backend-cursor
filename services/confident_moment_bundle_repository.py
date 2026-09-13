"""Repository adapter for Confident Moment Coaching Bundle (Chunk 3).

Focused repository only — does not wrap services/db.py.  Calls the exact
Chunk 2 SECURITY DEFINER RPCs defined in
migrations/pending/add_confident_moment_coaching_bundle_v1.sql:

- prepare_confident_moment_bundle_v1
- project_confident_moment_bundles_v1
- ack_confident_moment_bundle_item_render_v3
- freeze_root_phrase_coverage_frame_v1
- record_confident_moment_bundle_family_response_v1
- record_confident_moment_bundle_root_action_v1
- apply_confident_moment_bundle_text_update_v1
- project_confident_moment_coach_authoring_context_v1
- publish_confident_moment_coach_feedback_language_v1
- ack_feedback_language_revision_render_v3
- resolve_confident_moment_source_playback_authority_v1
- authorize_confident_moment_source_playback_emit_v1
- resolve_confident_moment_exercise_offer_v1
- transition_ideal_text_root_state_v1 (internal; invoked by product-action RPC)

While CONFIDENT_MOMENT_BUNDLE_V1_ENABLED / ROOTING_COVERAGE_V1_ENABLED are
false, every public method fails closed with CONFIDENT_MOMENT_BUNDLE_DISABLED.
"""
from __future__ import annotations

import logging
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
import uuid

from config import Config
from services.confident_moment_bundle import (
    runtime_is_enabled,
    validate_bundle_item_render_receipt,
    validate_coach_authoring_context,
    validate_coach_update_render_receipt,
)
from services.confident_moment_user_media import (
    ConfidentMomentSourceMediaPolicyInvalid,
    ConfidentMomentUserReadRetry,
    validate_exercise_correlation,
)

logger = logging.getLogger(__name__)


class ConfidentMomentBundleDisabled(Exception):
    code = "CONFIDENT_MOMENT_BUNDLE_DISABLED"


class ReadRpcTransport(Protocol):
    def call(self, rpc_name: str, parameters: dict[str, Any]) -> dict[str, Any]: ...


class ServiceRoleReadRpcTransport:
    """Dedicated 500 ms/no-retry client deadline for D46 reads.

    The deadline is a no-byte client boundary.  It discards late results and
    makes no claim that disconnecting cancels an already-running PostgreSQL
    statement; server-side execution remains bounded by deployed database and
    PostgREST configuration.
    """

    def __init__(self, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic

    def call(self, rpc_name: str, parameters: dict[str, Any]) -> dict[str, Any]:
        import urllib3
        from urllib3.util import Timeout

        base = (getattr(Config, "SUPABASE_URL", None) or "").strip().rstrip("/")
        key = (
            getattr(Config, "SUPABASE_SERVICE_ROLE_KEY", None) or ""
        ).strip()
        if not base or not key:
            raise ConfidentMomentUserReadRetry(
                ConfidentMomentUserReadRetry.code
            )
        pool = urllib3.PoolManager(
            retries=False,
            timeout=Timeout(total=0.5, connect=0.25, read=0.5),
        )
        try:
            started = self._monotonic()
            response = pool.request(
                "POST", f"{base}/rest/v1/rpc/{rpc_name}",
                body=json.dumps(parameters, separators=(",", ":")).encode(),
                headers={
                    "Authorization": f"Bearer {key}", "apikey": key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                retries=False,
                timeout=Timeout(total=0.5, connect=0.25, read=0.5),
            )
        except Exception as error:
            raise ConfidentMomentUserReadRetry(
                ConfidentMomentUserReadRetry.code
            ) from error
        finally:
            try:
                pool.clear()
            except Exception:  # noqa: BLE001 - cleanup cannot change outcome
                pass
        if self._monotonic() - started >= 0.5:
            raise ConfidentMomentUserReadRetry(
                ConfidentMomentUserReadRetry.code
            )
        raw = bytes(response.data or b"")
        if response.status >= 400:
            text = raw.decode("utf-8", errors="replace")
            if "CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED" in text:
                raise ConfidentMomentUserReadRetry(
                    ConfidentMomentUserReadRetry.code
                )
            if "CONFIDENT_MOMENT_SOURCE_MEDIA_POLICY_INVALID" in text:
                raise ConfidentMomentSourceMediaPolicyInvalid(
                    ConfidentMomentSourceMediaPolicyInvalid.code
                )
            raise RuntimeError("CONFIDENT_MOMENT_READ_RPC_FAILURE")
        try:
            value = json.loads(raw)
        except (TypeError, ValueError) as error:
            raise RuntimeError("CONFIDENT_MOMENT_READ_RPC_RESPONSE_INVALID") from error
        if type(value) is not dict:
            raise RuntimeError("CONFIDENT_MOMENT_READ_RPC_RESPONSE_INVALID")
        return value


@dataclass(frozen=True)
class PublishCoachFeedbackLanguageResult:
    public_payload: dict[str, Any]
    materialization_job_id: str | None


class ConfidentMomentBundleRepository:
    """RPC facade for the gated Confident Moment Coaching Bundle."""

    def __init__(
        self, client_provider: Callable[[], Any],
        read_transport_provider: Callable[[], ReadRpcTransport] | None = None,
    ) -> None:
        self._client_provider = client_provider
        self._read_transport_provider = (
            read_transport_provider or ServiceRoleReadRpcTransport
        )

    @property
    def client(self) -> Any:
        return self._client_provider()

    @staticmethod
    def _rpc_payload(data: Any) -> Any:
        if type(data) is dict:
            return data
        raise TypeError("Chunk 3 RPC must return one scalar JSON object")

    def _require_bundle_gate(self) -> None:
        if not runtime_is_enabled():
            raise ConfidentMomentBundleDisabled()

    def _require_coverage_gate(self) -> None:
        self._require_bundle_gate()
        if not bool(getattr(Config, "ROOTING_COVERAGE_V1_ENABLED", False)):
            raise ConfidentMomentBundleDisabled()

    def project_take_bundles(
        self,
        *,
        acquisition_principal_id: str,
        project_id: str,
        take_id: str,
    ) -> dict[str, Any]:
        self._require_bundle_gate()
        result = self.client.rpc(
            "project_confident_moment_bundles_v1",
            {
                "p_acquisition_principal_id": acquisition_principal_id,
                "p_project_id": project_id,
                "p_take_id": take_id,
            },
        ).execute()
        data = self._rpc_payload(getattr(result, "data", result))
        if not isinstance(data, dict):
            raise TypeError(
                "project_confident_moment_bundles_v1 returned non-object"
            )
        return data

    def resolve_source_playback_authority(
        self, *, acquisition_principal_id: str, bundle_id: str,
        bundle_attachment_id: str,
    ) -> dict[str, Any]:
        """Resolve one fresh database-owned phase-1/phase-3 authority."""
        self._require_bundle_gate()
        return self._read_transport_provider().call(
            "resolve_confident_moment_source_playback_authority_v1",
            {
                "p_acquisition_principal_id": acquisition_principal_id,
                "p_bundle_id": bundle_id,
                "p_bundle_attachment_id": bundle_attachment_id,
            },
        )

    def authorize_source_playback_emit(
        self, *, acquisition_principal_id: str, bundle_id: str,
        bundle_attachment_id: str, expected_authority_sha256: str,
        buffered_bytes_sha256: str, playback_request_id: str,
    ) -> dict[str, Any]:
        """Obtain one stateless, request-bound final emit authorization."""
        self._require_bundle_gate()
        return self._read_transport_provider().call(
            "authorize_confident_moment_source_playback_emit_v1",
            {
                "p_acquisition_principal_id": acquisition_principal_id,
                "p_bundle_id": bundle_id,
                "p_bundle_attachment_id": bundle_attachment_id,
                "p_expected_authority_sha256": expected_authority_sha256,
                "p_buffered_bytes_sha256": buffered_bytes_sha256,
                "p_playback_request_id": playback_request_id,
            },
        )

    def resolve_exercise_offer(
        self, *, acquisition_principal_id: str, bundle_id: str,
        bundle_attachment_id: str,
    ) -> dict[str, Any]:
        """Read the exact existing offer correlation; never create an offer."""
        self._require_bundle_gate()
        result = self._read_transport_provider().call(
            "resolve_confident_moment_exercise_offer_v1",
            {
                "p_acquisition_principal_id": acquisition_principal_id,
                "p_bundle_id": bundle_id,
                "p_bundle_attachment_id": bundle_attachment_id,
            },
        )
        return validate_exercise_correlation(
            result,
            bundle_id=bundle_id,
            attachment_id=bundle_attachment_id,
        )

    def prepare_bundle(
        self,
        *,
        acquisition_principal_id: str,
        project_id: str,
        take_id: str,
        feedback_membership_id: str,
        bundle_subject_candidate_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_bundle_gate()
        result = self.client.rpc(
            "prepare_confident_moment_bundle_v1",
            {
                "p_acquisition_principal_id": acquisition_principal_id,
                "p_project_id": project_id,
                "p_take_id": take_id,
                "p_feedback_membership_id": feedback_membership_id,
                "p_bundle_subject_candidate_id": bundle_subject_candidate_id,
                "p_idempotency_key": idempotency_key,
            },
        ).execute()
        data = self._rpc_payload(getattr(result, "data", result))
        if not isinstance(data, dict):
            raise TypeError("prepare_confident_moment_bundle_v1 returned non-object")
        return data

    def ack_item_render(
        self,
        *,
        acquisition_principal_id: str,
        bundle_id: str,
        bundle_attachment_id: str,
        feedback_exposure_id: str,
        render_instance_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_bundle_gate()
        result = self.client.rpc(
            "ack_confident_moment_bundle_item_render_v3",
            {
                "p_acquisition_principal_id": acquisition_principal_id,
                "p_bundle_id": bundle_id,
                "p_bundle_attachment_id": bundle_attachment_id,
                "p_feedback_exposure_id": feedback_exposure_id,
                "p_render_instance_id": render_instance_id,
                "p_idempotency_key": idempotency_key,
            },
        ).execute()
        data = self._rpc_payload(getattr(result, "data", result))
        return validate_bundle_item_render_receipt(
            data,
            bundle_id=bundle_id,
            bundle_attachment_id=bundle_attachment_id,
            feedback_exposure_id=feedback_exposure_id,
            render_instance_id=render_instance_id,
        )

    def ack_revision_render(
        self,
        *,
        recipient_principal_id: str,
        bundle_id: str,
        bundle_attachment_id: str,
        revision_id: str,
        revision_delivery_id: str,
        presentation_id: str,
        render_instance_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_bundle_gate()
        result = self.client.rpc(
            "ack_feedback_language_revision_render_v3",
            {
                "p_recipient_principal_id": recipient_principal_id,
                "p_bundle_id": bundle_id,
                "p_bundle_attachment_id": bundle_attachment_id,
                "p_revision_id": revision_id,
                "p_revision_delivery_id": revision_delivery_id,
                "p_presentation_id": presentation_id,
                "p_render_instance_id": render_instance_id,
                "p_idempotency_key": idempotency_key,
            },
        ).execute()
        data = self._rpc_payload(getattr(result, "data", result))
        return validate_coach_update_render_receipt(
            data,
            bundle_id=bundle_id,
            bundle_attachment_id=bundle_attachment_id,
            revision_id=revision_id,
            revision_delivery_id=revision_delivery_id,
            presentation_id=presentation_id,
            render_instance_id=render_instance_id,
        )

    def freeze_coverage_frame(
        self,
        *,
        acquisition_principal_id: str,
        project_id: str,
        take_id: str,
        feedback_membership_id: str,
        document_snapshot_id: str,
        policy_version: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_coverage_gate()
        result = self.client.rpc(
            "freeze_root_phrase_coverage_frame_v1",
            {
                "p_acquisition_principal_id": acquisition_principal_id,
                "p_project_id": project_id,
                "p_take_id": take_id,
                "p_feedback_membership_id": feedback_membership_id,
                "p_document_snapshot_id": document_snapshot_id,
                "p_policy_version": policy_version,
                "p_idempotency_key": idempotency_key,
            },
        ).execute()
        data = self._rpc_payload(getattr(result, "data", result))
        if not isinstance(data, dict):
            raise TypeError(
                "freeze_root_phrase_coverage_frame_v1 returned non-object"
            )
        return data

    def record_family_response(
        self,
        *,
        acquisition_principal_id: str,
        bundle_id: str,
        bundle_attachment_id: str,
        feedback_exposure_id: str,
        render_receipt_id: str,
        response: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_bundle_gate()
        result = self.client.rpc(
            "record_confident_moment_bundle_family_response_v1",
            {
                "p_acquisition_principal_id": acquisition_principal_id,
                "p_bundle_id": bundle_id,
                "p_bundle_attachment_id": bundle_attachment_id,
                "p_feedback_exposure_id": feedback_exposure_id,
                "p_render_receipt_id": render_receipt_id,
                "p_response": response,
                "p_idempotency_key": idempotency_key,
            },
        ).execute()
        data = self._rpc_payload(getattr(result, "data", result))
        return data

    def record_root_action(
        self,
        *,
        acquisition_principal_id: str,
        bundle_id: str,
        bundle_attachment_id: str,
        action: str,
        expected_block_head_action_id: str | None,
        source_feedback_exposure_id: str | None,
        source_owner_response_id: str | None,
        source_practice_attempt_id: str | None,
        source_ideal_text_revision_id: int | None,
        source_text_update_binding_id: str | None,
        source_target_speaker_binding_id: str | None,
        practice_target_speaker_binding_id: str | None,
        restore_product_action_id: str | None,
        policy_version: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_coverage_gate()
        result = self.client.rpc(
            "record_confident_moment_bundle_root_action_v1",
            {
                "p_acquisition_principal_id": acquisition_principal_id,
                "p_bundle_id": bundle_id,
                "p_bundle_attachment_id": bundle_attachment_id,
                "p_action": action,
                "p_expected_block_head_action_id": expected_block_head_action_id,
                "p_source_feedback_exposure_id": source_feedback_exposure_id,
                "p_source_owner_response_id": source_owner_response_id,
                "p_source_practice_attempt_id": source_practice_attempt_id,
                "p_source_ideal_text_revision_id": source_ideal_text_revision_id,
                "p_source_text_update_binding_id": source_text_update_binding_id,
                "p_source_target_speaker_binding_id": source_target_speaker_binding_id,
                "p_practice_target_speaker_binding_id": practice_target_speaker_binding_id,
                "p_restore_product_action_id": restore_product_action_id,
                "p_policy_version": policy_version,
                "p_idempotency_key": idempotency_key,
            },
        ).execute()
        return self._rpc_payload(getattr(result, "data", result))

    def update_text(
        self,
        *,
        owner_user_id: str,
        bundle_id: str,
        attachment_id: str,
        correction_decision_id: str,
        feedback_exposure_id: str,
        render_receipt_id: str,
        source_document_snapshot_id: str,
        source_document_version: int,
        expected_current_part_revision_id: int | None,
        expected_user_text_revision: int | None,
        expected_user_text_sha256: str | None,
        expected_part_inventory: list[dict[str, Any]],
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_bundle_gate()
        result = self.client.rpc(
            "apply_confident_moment_bundle_text_update_v1",
            {
                "p_owner_user_id": owner_user_id,
                "p_bundle_id": bundle_id,
                "p_attachment_id": attachment_id,
                "p_correction_decision_id": correction_decision_id,
                "p_feedback_exposure_id": feedback_exposure_id,
                "p_render_receipt_id": render_receipt_id,
                "p_source_document_snapshot_id": source_document_snapshot_id,
                "p_source_document_version": source_document_version,
                "p_expected_current_part_revision_id": expected_current_part_revision_id,
                "p_expected_user_text_revision": expected_user_text_revision,
                "p_expected_user_text_sha256": expected_user_text_sha256,
                "p_expected_part_inventory": expected_part_inventory,
                "p_idempotency_key": idempotency_key,
            },
        ).execute()
        return self._rpc_payload(getattr(result, "data", result))

    def project_coach_authoring_context(
        self, *, project_id: str, reviewer_principal_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_bundle_gate()
        result = self.client.rpc(
            "project_confident_moment_coach_authoring_context_v2",
            {
                "p_project_id": project_id,
                "p_reviewer_principal_id": reviewer_principal_id,
                "p_idempotency_key": idempotency_key,
            },
        ).execute()
        return validate_coach_authoring_context(
            self._rpc_payload(getattr(result, "data", result))
        )

    def publish_coach_feedback_language(
        self, *, reviewer_principal_id: str, bundle_id: str,
        bundle_attachment_id: str, review_batch_id: str,
        reveal_grant_id: str, reveal_access_id: str,
        review_assignment_id: str, output_kind: str,
        comment_purpose: str | None, revision_text: str,
        expected_current_revision_id: str | None,
        expected_current_delivery_id: str | None, idempotency_key: str,
    ) -> PublishCoachFeedbackLanguageResult:
        self._require_bundle_gate()
        result = self.client.rpc(
            "publish_confident_moment_coach_feedback_language_v1",
            {
                "p_reviewer_principal_id": reviewer_principal_id,
                "p_bundle_id": bundle_id,
                "p_bundle_attachment_id": bundle_attachment_id,
                "p_review_batch_id": review_batch_id,
                "p_reveal_grant_id": reveal_grant_id,
                "p_reveal_access_id": reveal_access_id,
                "p_review_assignment_id": review_assignment_id,
                "p_output_kind": output_kind,
                "p_comment_purpose": comment_purpose,
                "p_revision_text": revision_text,
                "p_expected_current_revision_id": expected_current_revision_id,
                "p_expected_current_delivery_id": expected_current_delivery_id,
                "p_idempotency_key": idempotency_key,
            },
        ).execute()
        raw = self._rpc_payload(getattr(result, "data", result))
        if "_materialization_job_id" not in raw:
            raise TypeError("publish result missing internal job identity")
        job_id = raw.get("_materialization_job_id")
        if job_id is not None:
            try:
                canonical = str(uuid.UUID(job_id))
            except (TypeError, ValueError) as error:
                raise TypeError("publish internal job identity invalid") from error
            if canonical != job_id:
                raise TypeError("publish internal job identity invalid")
        public_payload = {
            key: value for key, value in raw.items()
            if key != "_materialization_job_id"
        }
        from services.confident_moment_bundle import (
            validate_coach_feedback_language,
        )
        validate_coach_feedback_language(
            public_payload,
            bundle_id=bundle_id,
            attachment_id=bundle_attachment_id,
        )
        return PublishCoachFeedbackLanguageResult(
            public_payload=public_payload,
            materialization_job_id=job_id,
        )
