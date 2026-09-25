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


# The two choices a person can change after accepting (0361).
PERSONALISED_PRACTICE = "personalised_practice"
SENSITIVE_INFORMATION = "sensitive_information"
CONSENT_CHOICES = (PERSONALISED_PRACTICE, SENSITIVE_INFORMATION)


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
        "PROCESSING_BOUNDARY_INCOMPLETE", "CONSENT_CHOICE_INVALID",
        "PROCESSING_PRINCIPAL_UNRESOLVED",
    )
    for code in known:
        if code in text:
            return code
    return fallback


def _optional_purposes(payload: Any) -> list[str]:
    """The optional purposes named in an acceptance, as a clean list.

    A missing field and an empty list mean the same thing — nothing optional
    was chosen — because a client that has never heard of optional purposes
    must keep working exactly as it did. What is NOT accepted is a value of
    the wrong shape: a string, a number, or a list with a non-string in it is
    a client bug, and recording consent from a malformed payload is worse than
    refusing it.

    Order and duplicates are left alone; the RPC canonicalises them and is the
    one place that decides whether a named purpose is in the policy at all.
    """
    raw = payload.get("optional_purposes") if isinstance(payload, dict) else None
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ProcessingAuthorizationError(
            "OPTIONAL_PURPOSES_INVALID",
            "Optional purposes must be a list.", 422,
        )
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ProcessingAuthorizationError(
                "OPTIONAL_PURPOSES_INVALID",
                "Each optional purpose must be a non-empty string.", 422,
            )
        out.append(item.strip())
    return out


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
        """Resolve immutable acquisition identity without rewriting evidence.

        B-11 (audit 2026-09-22). This used to return the product owner
        unchanged whenever the gate was off, and that made one human's
        acquisition identity depend on which mode happened to be active when
        they tapped Agree. A guest accepts in `off` mode, so the receipt is
        written against whatever principal they own at that moment; they sign
        up, the claim moves product ownership to the account principal, and
        the client — still in `off` mode — resolves to the account, sees no
        authorization, and asks the same person to accept a second time. Flip
        the gate to `enforce` later and the resolver now prefers the guest
        principal, so processing is judged against the guest's receipt while
        the account's receipt is orphaned evidence that
        `export_authorization_evidence` reports and nothing else honours. One
        person, two acquisition principals, decided by a deployment setting.

        Acquisition identity is a fact about the past. It cannot depend on a
        runtime mode, so the resolution below is the same in both. What the
        mode still decides is what to do when the answer cannot be computed:
        `enforce` refuses, because processing without a resolved acquirer is
        the thing the gate exists to stop, while `off` degrades to the product
        owner it would have returned anyway. A gate that is off may not start
        failing requests for the state it was off for.
        """
        owner_id = str(product_owner_principal_id or "")
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
            if not self.enforced:
                return owner_id
            raise ProcessingAuthorizationError(
                "PROCESSING_PRINCIPAL_UNRESOLVED",
                "The acquisition principal could not be resolved.",
                503,
            ) from error
        if not self.enforced:
            return owner_id
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
        if operation == "recording" and not self.choice_permitted(
                acquisition_principal_id, SENSITIVE_INFORMATION):
            # E5-A (founder 2026-09-25). Withdrawing the sensitive-information
            # consent stops NEW recording, and only that: reads, exports and
            # everything else keep answering. Checked before the mode, because
            # an explicit withdrawal is honoured whether or not the gate is on.
            raise ProcessingAuthorizationError(
                "PROCESSING_RECORDING_WITHDRAWN",
                "Recording is off because the consent for it was withdrawn.",
                403,
            )
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

    # ── Choices a person changes after accepting (0361) ────────────────────
    # FOUNDER 2026-09-25, E1-E5. The receipt records the ticks given at
    # acceptance; these read and record what the person changed since. Every
    # caller that needs to know whether a choice is on asks choice_permitted,
    # so the rule lives in one place and no route decides it for itself.

    def consent_choices(self, acquisition_principal_id: str) -> dict | None:
        """The choices in force now, or None when they cannot be read."""
        try:
            result = self.client.rpc("get_phase1_consent_choices_v1", {
                "p_acquisition_principal_id": str(acquisition_principal_id),
            }).execute()
            return _one(result.data)
        except Exception:
            return None

    def choice_permitted(self, acquisition_principal_id: str, choice: str) -> bool:
        """Whether this person's choice allows the processing it covers.

        An explicit "no" (a tick left empty, a switch turned off, a consent
        withdrawn) is refused in every mode. When there is nothing to read —
        no receipt, or a read that failed — the answer follows the gate: an
        enforcing gate refuses, because it cannot show consent; a gate that is
        off keeps the established product path, which it may not start
        failing for the state it was off for.
        """
        choices = self.consent_choices(acquisition_principal_id)
        if not choices or not choices.get("has_receipt"):
            return not self.enforced
        return choices.get(choice) is True

    def set_consent_choice(
        self, acquisition_principal_id: str, *, choice: str, enabled: bool,
        idempotency_key: str, client_version: str | None,
    ) -> dict:
        if choice not in CONSENT_CHOICES or not isinstance(enabled, bool):
            raise ProcessingAuthorizationError(
                "CONSENT_CHOICE_INVALID", "Unknown choice.", 400,
            )
        if not isinstance(idempotency_key, str) or not (
                8 <= len(idempotency_key.strip()) <= 200):
            raise ProcessingAuthorizationError(
                "IDEMPOTENCY_KEY_REQUIRED",
                "An idempotency key of 8 to 200 characters is required.", 400,
            )
        try:
            result = self.client.rpc("set_phase1_consent_choice_v1", {
                "p_acquisition_principal_id": str(acquisition_principal_id),
                "p_choice": choice,
                "p_enabled": enabled,
                "p_idempotency_key": idempotency_key.strip(),
                "p_client_version": (client_version or "")[:120] or None,
            }).execute()
            row = _one(result.data)
            if not row:
                raise RuntimeError("empty consent choice state")
            return row
        except Exception as error:
            code = _domain_code(error, "CONSENT_CHOICE_FAILED")
            status = {
                "PROCESSING_AUTHORIZATION_REQUIRED": 403,
                "CONSENT_CHOICE_INVALID": 400,
                "PROCESSING_PRINCIPAL_UNRESOLVED": 403,
            }.get(code, 503)
            raise ProcessingAuthorizationError(
                code, "The choice could not be saved.", status,
            ) from error

    def change_consent_choice(
        self, acquisition_principal_id: str, *, choice: str, enabled: Any,
        idempotency_key: str, client_version: str | None,
    ) -> dict:
        """Record a change, and carry out what it promises.

        Turning practice off deletes the person's practice recordings (E2,
        founder 2026-09-25), straight away. If storage fails midway the
        answer says so (`practice_erasure.complete` false) and the worker's
        withdrawal sweep finishes it; processing already stopped with the
        change itself.
        """
        state = self.set_consent_choice(
            acquisition_principal_id, choice=choice, enabled=enabled,
            idempotency_key=idempotency_key, client_version=client_version)
        if (choice == PERSONALISED_PRACTICE and enabled is False
                and state.get(PERSONALISED_PRACTICE) is False):
            from services.practice_retention import erase_practice_for_principal

            erasure = erase_practice_for_principal(
                database=self.database, principal_id=acquisition_principal_id)
            state = {**state,
                     "practice_erasure": {"complete": bool(erasure["complete"])}}
        return state

    def user_acquisition_principal(self, user_id: str) -> str:
        """The acquirer behind a signed-in user, as the routes resolve it."""
        from services.project_repository import ProjectRepository

        owner = ProjectRepository(self.database).owner_for_user(str(user_id))
        return self.resolve_acquisition_principal(owner.id, user_id=str(user_id))

    def take_acquisition_principal(self, take_id: str) -> str:
        """The acquirer behind a Take, as the recording pipeline resolves it."""
        session = self.database.v2_get_session_by_id(str(take_id)) or {}
        return self.resolve_acquisition_principal(
            str(session.get("owner_principal_id") or ""),
            user_id=str(session.get("user_id") or "") or None,
            recording_id=str(session.get("recording_id") or "") or None,
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
            # Proven True by the guard above, which raises
            # AGE_ATTESTATION_REQUIRED on anything else. The literal was
            # not a hole -- no caller can reach here without having sent
            # it -- but it READ like the payload was ignored, and that
            # misreading has already cost one wrong finding. Pass the
            # value that was checked, so the code says what it does.
            "p_age_18_attested": bool(payload["age_18_attested"]),
            "p_country_of_residence": str(payload.get("country_of_residence") or ""),
            "p_locale": str(payload.get("locale") or ""),
            "p_client_version": str(payload.get("client_version") or ""),
            "p_accepted_at": accepted_at,
            "p_idempotency_key": str(payload.get("idempotency_key") or ""),
            # ONLY what the person affirmatively ticked. An empty list is the
            # recorded "no", and v2 behaves exactly as v1 does for it — an
            # absent field could not tell a refusal from never having asked.
            # Shape is checked here; whether a purpose is IN the policy, and
            # whether it is one that may be optional at all, is the RPC's to
            # decide (PROCESSING_OPTIONAL_PURPOSE_INVALID). Validating it in
            # two places is how the two drift apart.
            "p_optional_purposes": _optional_purposes(payload),
        }
        if not args["p_idempotency_key"]:
            raise ProcessingAuthorizationError(
                "IDEMPOTENCY_KEY_REQUIRED", "An acceptance idempotency key is required.", 422,
            )
        try:
            result = self.client.rpc(
                "accept_phase1_processing_authorization_v2", args
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
