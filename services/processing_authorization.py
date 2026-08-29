"""One Phase-1 authority boundary for routes, workers and provider adapters.

The database is authoritative.  This module translates its typed decisions
into stable domain errors; callers never reproduce policy, purpose, age,
country, copy-version or termination rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from typing import Any, Mapping


_ENFORCED_VALUES = {"enforce", "enforced", "active"}


@dataclass(frozen=True)
class ProcessingAuthorizationError(RuntimeError):
    code: str
    message: str
    status: int = 403

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class ProcessingAuthority:
    acquisition_principal_id: str
    receipt_id: str | None
    policy_id: str | None
    policy_version: str | None
    code: str
    enforced: bool


def rethrow_processing_authorization(error: BaseException) -> None:
    """Prevent optional AI fallbacks from laundering a policy failure.

    Many established generators intentionally degrade on provider/model
    errors.  At the authorization boundary that behavior is unsafe: a denied
    permit is a hard domain outcome, not an empty model response.
    """
    if isinstance(error, ProcessingAuthorizationError):
        raise error


def _one(data: Any) -> dict | None:
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return None


def _domain_code(error: Exception, fallback: str) -> str:
    text = str(error or "")
    known = (
        "PROCESSING_POLICY_INACTIVE", "PROCESSING_POLICY_UNAPPROVED",
        "PROCESSING_POLICY_STALE", "PROCESSING_AUTHORIZATION_REQUIRED",
        "PROCESSING_SERVICE_BLOCKED", "PROCESSING_PURPOSE_NOT_OPERATIONAL",
        "PROCESSING_PURPOSE_NOT_AUTHORIZED", "EXPLICIT_ACCEPTANCE_REQUIRED",
        "COUNTRY_NOT_ALLOWED", "PHASE2_PURPOSE_FORBIDDEN",
        "IDEMPOTENCY_CONFLICT", "PROVIDER_PERMIT_INVALID",
        "PROCESSING_BOUNDARY_INCOMPLETE",
    )
    for code in known:
        if code in text:
            return code
    return fallback


class ProcessingAuthorizationService:
    """The only application API for Phase-1 processing authority."""

    def __init__(self, database: Any, *, mode: str | None = None) -> None:
        self.database = database
        self.client = database.client
        self.mode = (mode if mode is not None else os.getenv(
            "PLF1_PROCESSING_AUTHORIZATION_MODE", "off"
        )).strip().lower()

    @property
    def enforced(self) -> bool:
        return self.mode in _ENFORCED_VALUES

    def resolve_acquisition_principal(
        self, product_owner_principal_id: str, *, user_id: str | None = None,
        recording_id: str | None = None,
    ) -> str:
        """Resolve immutable acquisition identity without rewriting evidence."""
        owner_id = str(product_owner_principal_id or "")
        if not self.enforced:
            return owner_id
        if recording_id:
            try:
                result = (
                    self.client.table("processing_recording_attempts")
                    .select("acquisition_principal_id")
                    .eq("recording_id", str(recording_id))
                    .limit(1).execute()
                )
                row = _one(result.data)
                if row and row.get("acquisition_principal_id"):
                    return str(row["acquisition_principal_id"])
            except Exception:
                pass
        try:
            result = self.client.rpc(
                "resolve_phase1_acquisition_principal_v1",
                {
                    "p_product_owner_principal_id": owner_id,
                    "p_user_id": str(user_id) if user_id else None,
                },
            ).execute()
            value = result.data
            if isinstance(value, list) and value:
                value = value[0]
            if value:
                return str(value)
        except Exception as error:
            raise ProcessingAuthorizationError(
                "PROCESSING_PRINCIPAL_UNRESOLVED",
                "The acquisition principal could not be resolved.",
                503,
            ) from error
        raise ProcessingAuthorizationError(
            "PROCESSING_PRINCIPAL_UNRESOLVED",
            "The acquisition principal could not be resolved.",
            503,
        )

    def status(self, acquisition_principal_id: str) -> dict:
        try:
            result = self.client.rpc(
                "get_phase1_processing_authorization_v1",
                {"p_acquisition_principal_id": str(acquisition_principal_id)},
            ).execute()
            row = _one(result.data)
            if row:
                row["gate_mode"] = "enforce" if self.enforced else "off"
                return row
        except Exception:
            # Before migration/policy activation the gate is explicitly
            # unavailable.  Never fabricate accepted state.
            pass
        return {
            "authorized": False,
            "code": "PROCESSING_POLICY_INACTIVE",
            "policy_available": False,
            "pooled_learning_eligible": False,
            "gate_mode": "enforce" if self.enforced else "off",
        }

    def require_current(
        self, acquisition_principal_id: str, *, operation: str
    ) -> ProcessingAuthority:
        if not self.enforced:
            return ProcessingAuthority(
                str(acquisition_principal_id), None, None, None,
                "PROCESSING_GATE_INACTIVE", False,
            )
        status = self.status(acquisition_principal_id)
        if not status.get("authorized"):
            code = str(status.get("code") or "PROCESSING_AUTHORIZATION_REQUIRED")
            raise ProcessingAuthorizationError(
                code,
                "Current processing authorization is required for this action.",
                403,
            )
        if status.get("pooled_learning_eligible") is not False:
            raise ProcessingAuthorizationError(
                "PHASE1_POOLING_INVARIANT_FAILED",
                "Phase-1 processing cannot authorize pooled learning.",
                500,
            )
        return ProcessingAuthority(
            str(acquisition_principal_id),
            str(status.get("receipt_id") or "") or None,
            str(status.get("policy_id") or "") or None,
            str(status.get("policy_version") or "") or None,
            str(status.get("code") or "PROCESSING_AUTHORIZED"), True,
        )

    def accept(self, acquisition_principal_id: str, payload: Mapping[str, Any]) -> dict:
        if payload.get("explicit_action") != "agree_and_continue":
            raise ProcessingAuthorizationError(
                "EXPLICIT_ACCEPTANCE_REQUIRED",
                "Choose Agree and continue to accept the current policy.", 422,
            )
        if payload.get("age_18_attested") is not True:
            raise ProcessingAuthorizationError(
                "AGE_ATTESTATION_REQUIRED", "You must confirm that you are 18+.", 422,
            )
        accepted_at = str(payload.get("accepted_at") or "")
        if not accepted_at:
            accepted_at = datetime.now(timezone.utc).isoformat()
        args = {
            "p_acquisition_principal_id": str(acquisition_principal_id),
            "p_policy_version": str(payload.get("policy_version") or ""),
            "p_terms_copy_sha256": str(payload.get("terms_copy_sha256") or ""),
            "p_privacy_copy_sha256": str(payload.get("privacy_copy_sha256") or ""),
            "p_ai_notice_copy_sha256": str(payload.get("ai_notice_copy_sha256") or ""),
            "p_agreement_copy_sha256": str(payload.get("agreement_copy_sha256") or ""),
            "p_explicit_action": "agree_and_continue",
            "p_age_18_attested": True,
            "p_country_of_residence": str(payload.get("country_of_residence") or ""),
            "p_locale": str(payload.get("locale") or ""),
            "p_client_version": str(payload.get("client_version") or ""),
            "p_accepted_at": accepted_at,
            "p_idempotency_key": str(payload.get("idempotency_key") or ""),
        }
        if not args["p_idempotency_key"]:
            raise ProcessingAuthorizationError(
                "IDEMPOTENCY_KEY_REQUIRED", "An acceptance idempotency key is required.", 422,
            )
        try:
            result = self.client.rpc(
                "accept_phase1_processing_authorization_v1", args
            ).execute()
            row = _one(result.data)
            if not row:
                raise RuntimeError("empty authorization receipt")
            return row
        except ProcessingAuthorizationError:
            raise
        except Exception as error:
            code = _domain_code(error, "PROCESSING_AUTHORIZATION_FAILED")
            status = 409 if code in ("PROCESSING_POLICY_STALE", "IDEMPOTENCY_CONFLICT") else 403
            raise ProcessingAuthorizationError(
                code, "The processing agreement could not be recorded.", status
            ) from error

    def finalize_recording(
        self, *, attempt_id: str, acquisition_principal_id: str,
        project_id: str, recording_id: str, upload_idempotency_key: str,
        storage_provider: str, bucket: str, object_key: str,
        byte_size: int, content_type: str, exact_bytes_sha256: str,
        verification_method: str,
    ) -> dict | None:
        if not self.enforced:
            return None
        self.require_current(acquisition_principal_id, operation="recording")
        try:
            result = self.client.rpc("finalize_phase1_recording_intake_v1", {
                "p_attempt_id": attempt_id,
                "p_acquisition_principal_id": acquisition_principal_id,
                "p_project_id": project_id,
                "p_recording_id": recording_id,
                "p_upload_idempotency_key": upload_idempotency_key,
                "p_storage_provider": storage_provider,
                "p_bucket": bucket,
                "p_object_key": object_key,
                "p_byte_size": int(byte_size),
                "p_content_type": content_type,
                "p_exact_bytes_sha256": exact_bytes_sha256,
                "p_verification_method": verification_method,
            }).execute()
            row = _one(result.data)
            if not row or row.get("pooled_learning_eligible") is not False:
                raise RuntimeError("invalid Phase-1 intake result")
            return row
        except Exception as error:
            code = _domain_code(error, "PROCESSING_INTAKE_FAILED")
            raise ProcessingAuthorizationError(
                code, "The authorized recording boundary could not be created.", 503
            ) from error

    def queue_orphan(
        self, *, acquisition_principal_id: str, storage_provider: str,
        bucket: str, object_key: str, exact_bytes_sha256: str, reason_code: str,
    ) -> None:
        if not self.enforced:
            return
        self.client.rpc("queue_phase1_orphan_audio_v1", {
            "p_acquisition_principal_id": acquisition_principal_id,
            "p_storage_provider": storage_provider,
            "p_bucket": bucket, "p_object_key": object_key,
            "p_exact_bytes_sha256": exact_bytes_sha256,
            "p_reason_code": reason_code,
        }).execute()

    def sync_processing_job(
        self, *, attempt_id: str, runtime_job_id: str | None,
        status: str, attempts: int, error_code: str | None = None,
    ) -> dict | None:
        """Advance the durable Phase-1 job alongside the runtime worker row."""
        if not self.enforced:
            return None
        try:
            result = self.client.rpc("sync_phase1_processing_job_v1", {
                "p_attempt_id": str(attempt_id),
                "p_runtime_job_id": (
                    str(runtime_job_id) if runtime_job_id else None
                ),
                "p_status": str(status),
                "p_attempts": max(0, int(attempts)),
                "p_error_code": str(error_code)[:160] if error_code else None,
            }).execute()
            row = _one(result.data)
            if not row:
                raise RuntimeError("empty processing-job transition")
            return row
        except Exception as error:
            raise ProcessingAuthorizationError(
                "PROCESSING_JOB_SYNC_FAILED",
                "The durable processing state could not be synchronized.",
                503,
            ) from error

    def issue_provider_permit(
        self, *, acquisition_principal_id: str, take_id: str | None,
        recording_id: str | None, provider: str, operation_kind: str,
        minimum_data_manifest: Mapping[str, Any], idempotency_key: str,
    ) -> dict | None:
        if not self.enforced:
            return None
        # The database alone may grant the narrowly scoped policy-cutover
        # carryover for an already accepted full processing job. Interactive
        # recording, retry, and coach routes call ``require_current`` before
        # reaching this boundary; the RPC also rejects every operation not
        # explicitly needed to finish that exact job.
        pseudonym = hashlib.sha256(
            f"{acquisition_principal_id}:{take_id or 'no-take'}".encode("utf-8")
        ).hexdigest()
        try:
            result = self.client.rpc("issue_phase1_provider_permit_v1", {
                "p_acquisition_principal_id": acquisition_principal_id,
                "p_source_take_id": take_id or None,
                "p_source_recording_id": recording_id or None,
                "p_provider": provider,
                "p_operation_kind": operation_kind,
                "p_pseudonymous_subject_ref": pseudonym,
                "p_minimum_data_manifest": dict(minimum_data_manifest),
                "p_idempotency_key": idempotency_key,
                "p_ttl_seconds": 900,
            }).execute()
            row = _one(result.data)
            if not row:
                raise RuntimeError("empty provider permit")
            return row
        except Exception as error:
            code = _domain_code(error, "PROVIDER_PERMIT_DENIED")
            raise ProcessingAuthorizationError(
                code, "Provider processing is not authorized.", 403
            ) from error

    def record_provider_event(
        self, permit_id: str | None, event_kind: str, *,
        provider_operation_ref: str | None = None,
        error_code: str | None = None, metadata: Mapping[str, Any] | None = None,
    ) -> None:
        if not self.enforced or not permit_id:
            return
        self.client.rpc("record_phase1_provider_operation_v1", {
            "p_permit_id": permit_id, "p_event_kind": event_kind,
            "p_provider_operation_ref": provider_operation_ref,
            "p_error_code": error_code,
            "p_metadata": dict(metadata or {}),
        }).execute()

    def record_transparency_render(
        self, *, acquisition_principal_id: str, ai_notice_version: str,
        surface: str, client_render_id: str, rendered_at: str,
        client_version: str, authenticated_actor_id: str | None,
    ) -> dict:
        result = self.client.rpc("record_ai_transparency_render_v1", {
            "p_acquisition_principal_id": acquisition_principal_id,
            "p_ai_notice_version": ai_notice_version,
            "p_surface": surface,
            "p_client_render_id": client_render_id,
            "p_rendered_at": rendered_at,
            "p_client_version": client_version,
            "p_authenticated_actor_id": authenticated_actor_id,
        }).execute()
        return _one(result.data) or {}

    def request_purge(
        self, *, acquisition_principal_id: str, trigger_kind: str,
        idempotency_key: str, reason_code: str,
    ) -> dict:
        try:
            result = self.client.rpc("request_phase1_purge_v1", {
                "p_acquisition_principal_id": acquisition_principal_id,
                "p_trigger_kind": trigger_kind,
                "p_idempotency_key": idempotency_key,
                "p_reason_code": reason_code,
            }).execute()
            row = _one(result.data)
            if not row:
                raise RuntimeError("empty purge receipt")
            return row
        except Exception as error:
            raise ProcessingAuthorizationError(
                "PURGE_REQUEST_FAILED",
                "The data request could not be recorded.", 503,
            ) from error

    def request_data_right(
        self, *, acquisition_principal_id: str, request_kind: str,
        idempotency_key: str, subject_payload: Mapping[str, Any],
    ) -> dict:
        try:
            result = self.client.rpc("request_phase1_data_right_v1", {
                "p_acquisition_principal_id": acquisition_principal_id,
                "p_request_kind": request_kind,
                "p_idempotency_key": idempotency_key,
                "p_subject_payload": dict(subject_payload),
            }).execute()
            row = _one(result.data)
            if not row:
                raise RuntimeError("empty data-right receipt")
            return row
        except Exception as error:
            raise ProcessingAuthorizationError(
                "DATA_RIGHT_REQUEST_FAILED",
                "The data-rights request could not be recorded.", 503,
            ) from error

    def purge_status(
        self, acquisition_principal_id: str, purge_request_id: str,
    ) -> dict | None:
        try:
            result = (
                self.client.table("data_purge_requests")
                .select("id,trigger_kind,state,requested_at,completed_at")
                .eq("id", purge_request_id)
                .eq("acquisition_principal_id", acquisition_principal_id)
                .limit(1).execute()
            )
            return _one(result.data)
        except Exception:
            return None

    def export_authorization_evidence(
        self, acquisition_principal_id: str,
    ) -> dict:
        """A data-rights export of Phase-1 evidence metadata only.

        Raw recording/transcript export remains in the existing product export
        route; this method intentionally cannot mint storage URLs.
        """
        receipts = (
            self.client.table("processing_authorization_receipts")
            .select("id,policy_id,accepted_at,country_of_residence,locale,client_version,pooled_learning_eligible")
            .eq("acquisition_principal_id", acquisition_principal_id)
            .execute().data or []
        )
        purges = (
            self.client.table("data_purge_requests")
            .select("id,trigger_kind,state,requested_at,completed_at")
            .eq("acquisition_principal_id", acquisition_principal_id)
            .execute().data or []
        )
        rights = (
            self.client.table("data_rights_requests")
            .select("id,request_kind,state,requested_at,completed_at")
            .eq("acquisition_principal_id", acquisition_principal_id)
            .execute().data or []
        )
        return {
            "acquisition_principal_id": acquisition_principal_id,
            "authorization_receipts": receipts,
            "data_requests": purges,
            "data_rights_requests": rights,
            "pooled_learning_eligible": False,
        }


def evidence_sha256(value: Mapping[str, Any]) -> str:
    """Deterministic hash for non-content orchestration evidence."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
