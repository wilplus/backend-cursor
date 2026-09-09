"""Fail-closed readiness evaluation for the MLC-3 founder canary.

This module is deliberately outside every product route.  It consumes only
aggregate database evidence and configuration presence; it never reads audio,
transcripts, blind packets, notes, or exercise content and cannot activate a
runtime or learning capability.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Mapping
from uuid import UUID

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key


READINESS_CONTRACT_VERSION = "mlc3-founder-canary-readiness-v1"
SERVICE_CONTRACT_VERSION = "mlc3-first-client-service-v1"
APPROVED_NEED_CODE = "rushed_phrase_endings"
_SHA256_LENGTH = 64
R2_EVIDENCE_VERSION = "mlc3-founder-r2-smoke-v1"
CLOUDFLARE_PRIVACY_EVIDENCE_VERSION = "mlc3-cloudflare-r2-privacy-v1"
DEPLOYMENT_ATTESTATION_VERSION = "mlc3-founder-deployment-attestation-v2"
MONITORING_EVIDENCE_VERSION = "mlc3-founder-monitoring-evidence-v1"
EMERGENCY_DISABLE_EVIDENCE_VERSION = "mlc3-founder-emergency-disable-v1"
TRUSTED_ATTESTATION_ISSUER = "willpowerlab-release-operator"
TRUSTED_ATTESTATION_KEY_ID = "mlc3-founder-canary-2026-09"
_EVIDENCE_MAX_AGE = timedelta(hours=24)


@dataclass(frozen=True)
class FounderCanaryReadinessReport:
    ready_for_activation_review: bool
    blocker_codes: tuple[str, ...]
    warning_codes: tuple[str, ...]
    activation_actions: tuple[str, ...]
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "readiness_contract_version": READINESS_CONTRACT_VERSION,
            "ready_for_activation_review": self.ready_for_activation_review,
            "blocker_codes": list(self.blocker_codes),
            "warning_codes": list(self.warning_codes),
            "activation_actions": list(self.activation_actions),
            "evidence": self.evidence,
        }


def _count(health: Mapping[str, Any], key: str) -> int:
    value = health.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return -1
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def _valid_uuid(value: Any) -> bool:
    try:
        return bool(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return False


def _valid_sha256(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return len(normalized) == _SHA256_LENGTH and all(
        char in "0123456789abcdef" for char in normalized
    )


def _manifest_sha256(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items()
               if key not in {"evidence_sha256", "signature_ed25519_base64"}}
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def evidence_manifest_sha256(value: Mapping[str, Any]) -> str:
    """Return the canonical checksum used by operator evidence manifests."""
    return _manifest_sha256(value)


def _value_sha256(value: Any) -> str:
    canonical = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _valid_git_sha(value: Any) -> bool:
    normalized = str(value or "").lower()
    return len(normalized) in {40, 64} and all(
        char in "0123456789abcdef" for char in normalized
    )


def _verify_ed25519_manifest(
    manifest: Mapping[str, Any], trusted_public_key_pem: bytes,
) -> bool:
    """Require a detached signature from the configured evidence authority."""
    try:
        signature = base64.b64decode(
            str(manifest.get("signature_ed25519_base64") or ""),
            validate=True,
        )
        public_key = load_pem_public_key(trusted_public_key_pem)
        if not isinstance(public_key, Ed25519PublicKey):
            return False
        payload = {key: item for key, item in manifest.items()
                   if key != "signature_ed25519_base64"}
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        public_key.verify(signature, canonical)
        return True
    except (
        ValueError, TypeError, AttributeError, InvalidSignature,
        UnsupportedAlgorithm,
    ):
        return False


def _fresh_timestamp(value: Any, now: datetime | None = None) -> bool:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return False
    current = now or datetime.now(timezone.utc)
    age = current - parsed
    return timedelta(0) <= age <= _EVIDENCE_MAX_AGE


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def validate_cloudflare_r2_privacy_export(
    value: Mapping[str, Any], *, account_id: str,
    practice_bucket: str, coach_video_bucket: str,
    trusted_public_key_pem: bytes, trusted_issuer: str,
    trusted_key_id: str,
) -> bool:
    """Verify signed control-plane proof that both exact buckets are private."""
    if (
        value.get("contract_version") != CLOUDFLARE_PRIVACY_EVIDENCE_VERSION
        or value.get("issuer") != trusted_issuer
        or value.get("key_id") != trusted_key_id
        or value.get("source") != "cloudflare_authenticated_api"
        or not value.get("request_id")
        or value.get("account_id_sha256")
        != sha256(account_id.encode("utf-8")).hexdigest()
        or value.get("evidence_sha256") != _manifest_sha256(value)
        or not _verify_ed25519_manifest(value, trusted_public_key_pem)
    ):
        return False
    bucket_controls = value.get("buckets")
    if not isinstance(bucket_controls, list) or len(bucket_controls) != 2:
        return False
    expected = {
        "practice_audio": practice_bucket,
        "coach_video": coach_video_bucket,
    }
    seen: set[str] = set()
    for control in bucket_controls:
        if not isinstance(control, Mapping):
            return False
        role = str(control.get("role") or "")
        if (
            role in seen or expected.get(role) != control.get("bucket")
            or control.get("public_access_enabled") is not False
            or control.get("r2_dev_domain_enabled") is not False
            or control.get("custom_domain_count") != 0
        ):
            return False
        seen.add(role)
    return seen == set(expected)


def validate_r2_smoke_manifest(
    manifest: Mapping[str, Any], *, account_id: str,
    practice_bucket: str, coach_video_bucket: str,
    trusted_public_key_pem: bytes, trusted_issuer: str,
    trusted_key_id: str,
    now: datetime | None = None,
) -> bool:
    """Validate a fresh, exact-bucket write/read/delete evidence manifest."""
    expected_sha = str(manifest.get("evidence_sha256") or "").lower()
    endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
    if (
        manifest.get("contract_version") != R2_EVIDENCE_VERSION
        or manifest.get("environment") != "production"
        or manifest.get("endpoint") != endpoint
        or manifest.get("account_id_sha256")
        != sha256(account_id.encode("utf-8")).hexdigest()
        or manifest.get("issuer") != trusted_issuer
        or manifest.get("key_id") != trusted_key_id
        or not _fresh_timestamp(manifest.get("completed_at"), now)
        or not _valid_sha256(expected_sha)
        or expected_sha != _manifest_sha256(manifest)
        or not _verify_ed25519_manifest(manifest, trusted_public_key_pem)
    ):
        return False
    control_plane = manifest.get("cloudflare_authenticated_provider_export")
    if (
        not isinstance(control_plane, Mapping)
        or manifest.get("cloudflare_provider_export_sha256")
        != _value_sha256(control_plane)
        or not validate_cloudflare_r2_privacy_export(
            control_plane, account_id=account_id,
            practice_bucket=practice_bucket,
            coach_video_bucket=coach_video_bucket,
            trusted_public_key_pem=trusted_public_key_pem,
            trusted_issuer=trusted_issuer,
            trusted_key_id=trusted_key_id,
        )
    ):
        return False
    results = manifest.get("results")
    if not isinstance(results, list) or len(results) != 2:
        return False
    expected = {
        "practice_audio": practice_bucket,
        "coach_video": coach_video_bucket,
    }
    seen: set[str] = set()
    for item in results:
        if not isinstance(item, Mapping):
            return False
        role = str(item.get("role") or "")
        write_hash = item.get("write_sha256")
        if (
            role in seen or expected.get(role) != item.get("bucket")
            or not _valid_sha256(write_hash)
            or item.get("read_sha256") != write_hash
            or not _valid_sha256(item.get("object_key_sha256"))
            or item.get("object_key_prefix") != "mlc3-founder-readiness/"
            or not isinstance(item.get("byte_size"), int)
            or item.get("byte_size", 0) < 32
            or item.get("write_verified") is not True
            or item.get("read_verified") is not True
            or item.get("deletion_verified") is not True
        ):
            return False
        seen.add(role)
    return seen == set(expected)


def validate_deployment_attestation(
    manifest: Mapping[str, Any], *, backend_commit: str,
    frontend_commit: str, trusted_public_key_pem: bytes,
    trusted_issuer: str, trusted_key_id: str,
    founder_principal_id: str,
    monitor_code_sha256: str,
    now: datetime | None = None,
) -> bool:
    """Validate production-bound Railway and Vercel disabled-gate evidence."""
    evidence_sha = str(manifest.get("evidence_sha256") or "").lower()
    if (
        manifest.get("contract_version") != DEPLOYMENT_ATTESTATION_VERSION
        or manifest.get("environment") != "production"
        or manifest.get("backend_commit_sha") != backend_commit
        or manifest.get("frontend_commit_sha") != frontend_commit
        or manifest.get("issuer") != trusted_issuer
        or manifest.get("key_id") != trusted_key_id
        or not _valid_git_sha(backend_commit)
        or not _valid_git_sha(frontend_commit)
        or not _valid_uuid(founder_principal_id)
        or not _valid_sha256(monitor_code_sha256)
        or not _fresh_timestamp(manifest.get("verified_at"), now)
        or not _valid_sha256(evidence_sha)
        or evidence_sha != _manifest_sha256(manifest)
        or not _verify_ed25519_manifest(manifest, trusted_public_key_pem)
    ):
        return False
    railway = manifest.get("railway")
    vercel = manifest.get("vercel")
    if not isinstance(railway, Mapping) or not isinstance(vercel, Mapping):
        return False
    railway_export = railway.get("authenticated_provider_export")
    vercel_export = vercel.get("authenticated_provider_export")
    if not isinstance(railway_export, Mapping) or not isinstance(
        vercel_export, Mapping,
    ):
        return False
    services = railway_export.get("services")
    if (
        railway.get("provider_export_sha256") != _value_sha256(railway_export)
        or railway_export.get("source") != "railway_authenticated_api"
        or not railway_export.get("request_id")
        or not railway_export.get("project_id")
        or not railway_export.get("environment_id")
        or not isinstance(services, list) or not services
        or railway_export.get("observed_service_count") != len(services)
    ):
        return False
    backend_gates = {
        "MLC3_PILOT_ENABLED", "MLC3_COACH_INLINE_AUTHORING_ENABLED",
        "MLC2_DATASET_RELEASES_ENABLED", "MLC2_TRAINING_ENABLED",
        "MLC2_EVALUATION_ENABLED", "MLC2_PROMOTION_ENABLED",
    }
    seen_services: set[str] = set()
    seen_roles: set[str] = set()
    service_roles: dict[str, str] = {}
    for service in services:
        if not isinstance(service, Mapping):
            return False
        service_id = str(service.get("service_id") or "")
        gates = service.get("effective_gates")
        if (
            not service_id or service_id in seen_services
            or not service.get("deployment_id")
            or service.get("commit_sha") != backend_commit
            or not isinstance(gates, Mapping)
            or set(gates) != backend_gates
            or any(value is not False for value in gates.values())
        ):
            return False
        config_identity = {
            "service_id": service_id,
            "deployment_id": service.get("deployment_id"),
            "role": service.get("role"),
            "commit_sha": service.get("commit_sha"),
            "effective_gates": gates,
        }
        role = str(service.get("role") or "")
        if role == "monitor":
            monitor_config = service.get("monitor_config")
            if (
                not isinstance(monitor_config, Mapping)
                or monitor_config.get("schedule") != "*/5 * * * *"
                or monitor_config.get("start_command")
                != "bin/railway-mlc3-founder-canary-monitor.sh"
                or monitor_config.get("founder_principal_id")
                != founder_principal_id
                or monitor_config.get("expected_contract_state") != "disabled"
                or monitor_config.get("monitor_contract_version")
                != "mlc3-founder-canary-monitor-v1"
                or monitor_config.get("monitor_code_sha256")
                != monitor_code_sha256
                or monitor_config.get("start_command_sha256")
                != sha256(
                    b"bin/railway-mlc3-founder-canary-monitor.sh"
                ).hexdigest()
            ):
                return False
            config_identity["monitor_config"] = monitor_config
        expected_config_sha = _value_sha256(config_identity)
        if service.get("config_sha256") != expected_config_sha:
            return False
        seen_services.add(service_id)
        if role not in {"web", "worker", "monitor"}:
            return False
        seen_roles.add(role)
        service_roles[service_id] = role
    if seen_roles != {"web", "worker", "monitor"}:
        return False
    inventory = sorted(services, key=lambda row: str(row.get("service_id")))
    if railway_export.get("service_inventory_sha256") != _value_sha256(inventory):
        return False
    frontend_gates = vercel_export.get("effective_build_gates")
    expected_build_sha = _value_sha256({
        "deployment_id": vercel_export.get("deployment_id"),
        "commit_sha": vercel_export.get("commit_sha"),
        "effective_build_gates": frontend_gates,
    })
    monitoring = manifest.get("monitoring")
    emergency = manifest.get("emergency_disable_rehearsal")
    if not isinstance(monitoring, Mapping) or not isinstance(emergency, Mapping):
        return False
    required_signals = {
        "service_contract_or_allowlist_violation",
        "authorization_or_deletion_violation",
        "feedback_offer_or_practice_failure",
        "blind_review_or_reveal_failure",
        "coach_guidance_or_inline_authoring_failure",
        "unresolved_practice_media_write",
        "unresolved_coach_media_write",
    }
    monitor_valid = bool(
        monitoring.get("contract_version") == MONITORING_EVIDENCE_VERSION
        and service_roles.get(str(monitoring.get("monitor_service_id") or ""))
        == "monitor"
        and monitoring.get("monitor_service_role") == "monitor"
        and set(monitoring.get("covered_signals") or ()) == required_signals
        and monitoring.get("sentry_test_event_received") is True
        and monitoring.get("operations_alert_received") is True
        and monitoring.get("sentry_event_id")
        and monitoring.get("sentry_alert_rule_id")
        and _valid_sha256(monitoring.get("sentry_receipt_sha256"))
        and monitoring.get("operations_receipt_id")
        and _valid_sha256(monitoring.get("operations_receipt_sha256"))
        and _fresh_timestamp(monitoring.get("verified_at"), now)
    )
    expected_disabled_targets = {
        "database_contract_state": "disabled",
        "MLC3_PILOT_ENABLED": False,
        "MLC3_COACH_INLINE_AUTHORING_ENABLED": False,
        "NEXT_PUBLIC_MLC3_PILOT_UI_ENABLED": False,
        "NEXT_PUBLIC_MLC3_COACH_INLINE_AUTHORING_ENABLED": False,
    }
    attempts_value = emergency.get("attempts")
    attempts = attempts_value if isinstance(attempts_value, list) else []
    attempts_valid = len(attempts) == 2
    previous_after: Mapping[str, Any] | None = None
    previous_completed_at: datetime | None = None
    operation_ids: set[str] = set()
    if attempts_valid:
        for expected_number, attempt in enumerate(attempts, start=1):
            if not isinstance(attempt, Mapping):
                attempts_valid = False
                break
            before = attempt.get("before_states")
            after = attempt.get("after_states")
            operation_id = str(attempt.get("operation_id") or "")
            started_at = _parse_timestamp(attempt.get("started_at"))
            completed_at = _parse_timestamp(attempt.get("completed_at"))
            result_payload = {
                key: value for key, value in attempt.items()
                if key != "result_sha256"
            }
            if (
                attempt.get("attempt_number") != expected_number
                or not _valid_uuid(operation_id)
                or operation_id in operation_ids
                or not _fresh_timestamp(attempt.get("started_at"), now)
                or not _fresh_timestamp(attempt.get("completed_at"), now)
                or started_at is None or completed_at is None
                or started_at > completed_at
                or (previous_completed_at is not None
                    and previous_completed_at > started_at)
                or not isinstance(before, Mapping)
                or set(before) != set(expected_disabled_targets)
                or after != expected_disabled_targets
                or not _valid_sha256(attempt.get("result_sha256"))
                or attempt.get("result_sha256") != _value_sha256(result_payload)
                or attempt.get("completed") is not True
                or (expected_number == 2 and before != previous_after)
            ):
                attempts_valid = False
                break
            operation_ids.add(operation_id)
            previous_after = after
            previous_completed_at = completed_at
    emergency_valid = bool(
        emergency.get("contract_version")
        == EMERGENCY_DISABLE_EVIDENCE_VERSION
        and emergency.get("mode") == "idempotent_disabled_rehearsal"
        and attempts_valid
        and emergency.get("final_states") == expected_disabled_targets
        and emergency.get("verification_completed") is True
        and emergency.get("rollback_command_sha256")
        and _valid_sha256(emergency.get("rollback_command_sha256"))
        and _fresh_timestamp(emergency.get("verified_at"), now)
    )
    return bool(
        vercel.get("provider_export_sha256") == _value_sha256(vercel_export)
        and vercel_export.get("source") == "vercel_authenticated_api"
        and vercel_export.get("request_id")
        and vercel_export.get("project_id")
        and vercel_export.get("deployment_id")
        and vercel_export.get("commit_sha") == frontend_commit
        and vercel_export.get("build_config_sha256") == expected_build_sha
        and isinstance(frontend_gates, Mapping)
        and set(frontend_gates) == {
            "NEXT_PUBLIC_MLC3_PILOT_UI_ENABLED",
            "NEXT_PUBLIC_MLC3_COACH_INLINE_AUTHORING_ENABLED",
        }
        and all(value is False for value in frontend_gates.values())
        and monitor_valid
        and emergency_valid
    )


def assess_founder_canary_readiness(
    health: Mapping[str, Any],
    *,
    founder_principal_id: Any,
    coach_email: Any,
    backend_serving_enabled: bool,
    backend_inline_authoring_enabled: bool,
    frontend_serving_enabled: bool,
    frontend_inline_authoring_enabled: bool,
    r2_credentials_configured: bool,
    practice_bucket: Any,
    coach_video_bucket: Any,
    r2_smoke_evidence_sha256: Any,
    r2_smoke_manifest_valid: bool,
    deployment_attestation_valid: bool,
    deployed_backend_gates_disabled: bool,
    deployed_frontend_gates_disabled: bool,
    deployed_learning_gates_disabled: bool,
    dataset_creation_enabled: bool,
    training_enabled: bool,
    evaluation_enabled: bool,
    promotion_enabled: bool,
) -> FounderCanaryReadinessReport:
    """Return readiness for review while every activation switch stays off."""
    blockers: list[str] = []
    warnings: list[str] = []
    actions: list[str] = []

    founder_valid = _valid_uuid(founder_principal_id)
    normalized_coach_email = str(coach_email or "").strip().lower()
    practice_bucket_name = str(practice_bucket or "").strip()
    coach_bucket_name = str(coach_video_bucket or "").strip()

    if not founder_valid:
        blockers.append("founder_acquisition_principal_not_configured")
    if not normalized_coach_email or "@" not in normalized_coach_email:
        blockers.append("coach_email_not_configured")

    if health.get("readiness_contract_version") != READINESS_CONTRACT_VERSION:
        blockers.append("readiness_health_contract_mismatch")
    if health.get("service_contract_version") != SERVICE_CONTRACT_VERSION:
        blockers.append("service_contract_version_mismatch")
    if health.get("service_contract_state") != "disabled":
        blockers.append("database_service_gate_must_remain_disabled")
    if _count(health, "service_contract_count") != 1:
        blockers.append("service_contract_count_invalid")
    if _count(health, "allowlisted_principal_count") != 0:
        blockers.append("principal_allowlist_must_be_empty_before_review")
    if _count(health, "service_mode_record_count") != 0:
        blockers.append("unexpected_service_records_before_activation")

    exact_counts = {
        "founder_principal_count": 1,
        "founder_account_binding_count": 1,
        "founder_active_service_block_count": 0,
        "founder_open_purge_count": 0,
        "active_coach_allowlist_count": 1,
        "coach_principal_count": 1,
        "approved_need_contract_count": 1,
        "missing_required_rpc_count": 0,
        "missing_service_rpc_grant_count": 0,
        "runtime_rpc_client_grant_count": 0,
        "forbidden_rpc_runtime_grant_count": 0,
        "missing_required_table_count": 0,
        "rls_disabled_table_count": 0,
        "runtime_table_write_grant_count": 0,
        "runtime_owned_table_count": 0,
        "dataset_eligible_record_count": 0,
        "unresolved_founder_media_write_count": 0,
        "service_feedback_record_count": 0,
        "service_offer_record_count": 0,
        "service_practice_record_count": 0,
        "service_comparison_record_count": 0,
        "service_blind_review_record_count": 0,
        "service_coach_guidance_record_count": 0,
        "service_inline_authoring_record_count": 0,
    }
    for key, expected in exact_counts.items():
        if _count(health, key) != expected:
            blockers.append(f"{key}_invalid")

    if _count(health, "active_processing_policy_count") < 1:
        blockers.append("active_processing_policy_missing")
    if _count(health, "required_operational_purpose_count") != 2:
        blockers.append("required_processing_purpose_not_operational")
    if _count(health, "founder_current_full_service_receipt_count") < 1:
        blockers.append("founder_current_full_service_receipt_missing")
    if _count(health, "founder_project_count") < 1:
        blockers.append("founder_has_no_project")
    if _count(health, "catalog_snapshot_count") < 1:
        blockers.append("reviewed_catalogue_snapshot_missing")
    if _count(health, "approved_active_exercise_version_count") < 1:
        warnings.append("no_matching_exercise_may_require_inline_authoring")

    switch_states = {
        "backend_serving": bool(backend_serving_enabled),
        "backend_inline_authoring": bool(backend_inline_authoring_enabled),
        "frontend_serving": bool(frontend_serving_enabled),
        "frontend_inline_authoring": bool(frontend_inline_authoring_enabled),
    }
    for name, enabled in switch_states.items():
        if enabled:
            blockers.append(f"{name}_must_remain_disabled_before_review")

    learning_states = {
        "dataset_creation": bool(dataset_creation_enabled),
        "training": bool(training_enabled),
        "evaluation": bool(evaluation_enabled),
        "promotion": bool(promotion_enabled),
    }
    for name, enabled in learning_states.items():
        if enabled:
            blockers.append(f"{name}_must_remain_disabled")

    if not r2_credentials_configured:
        blockers.append("r2_credentials_not_configured")
    if not practice_bucket_name:
        blockers.append("practice_r2_bucket_not_configured")
    if not coach_bucket_name:
        blockers.append("coach_video_r2_bucket_not_configured")
    if practice_bucket_name and practice_bucket_name == coach_bucket_name:
        blockers.append("practice_and_coach_media_buckets_must_be_distinct")
    if not _valid_sha256(r2_smoke_evidence_sha256):
        blockers.append("live_r2_synthetic_rehearsal_not_verified")
    if not r2_smoke_manifest_valid:
        blockers.append("live_r2_rehearsal_manifest_invalid")
    if not deployment_attestation_valid:
        blockers.append("production_deployment_attestation_invalid")
    if not deployed_backend_gates_disabled:
        blockers.append("deployed_backend_gates_not_disabled")
    if not deployed_frontend_gates_disabled:
        blockers.append("deployed_frontend_gates_not_disabled")
    if not deployed_learning_gates_disabled:
        blockers.append("deployed_learning_gates_not_disabled")

    actions.extend((
        "activate_exact_database_service_contract",
        "allowlist_exact_founder_acquisition_principal",
        "enable_backend_founder_and_inline_gates",
        "enable_frontend_founder_and_inline_presentation_gates",
    ))

    evidence = {
        "founder_principal_configured": founder_valid,
        "coach_email_configured": bool(normalized_coach_email),
        "database_gate_state": health.get("service_contract_state"),
        "all_product_gates_disabled": (
            not any(switch_states.values())
            and deployed_backend_gates_disabled
            and deployed_frontend_gates_disabled
        ),
        "all_learning_gates_disabled": (
            not any(learning_states.values())
            and deployed_learning_gates_disabled
        ),
        "r2_credentials_configured": bool(r2_credentials_configured),
        "practice_bucket_configured": bool(practice_bucket_name),
        "coach_video_bucket_configured": bool(coach_bucket_name),
        "media_buckets_distinct": bool(
            practice_bucket_name
            and coach_bucket_name
            and practice_bucket_name != coach_bucket_name
        ),
        "r2_smoke_verified": _valid_sha256(r2_smoke_evidence_sha256),
        "r2_smoke_manifest_valid": bool(r2_smoke_manifest_valid),
        "deployment_attestation_valid": bool(deployment_attestation_valid),
        "approved_need_code": APPROVED_NEED_CODE,
        "aggregate_health_only": True,
        "real_collection_performed": False,
    }
    return FounderCanaryReadinessReport(
        ready_for_activation_review=not blockers,
        blocker_codes=tuple(dict.fromkeys(blockers)),
        warning_codes=tuple(dict.fromkeys(warnings)),
        activation_actions=tuple(actions),
        evidence=evidence,
    )
