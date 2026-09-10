"""Fail-closed, aggregate-only readiness for the MLC-3 D4 rollout.

The evaluator cannot activate a rollout. It verifies signed production
evidence while every product and learning switch is still disabled.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any, Mapping

from services.mlc3_founder_canary_readiness import (
    _fresh_timestamp,
    _manifest_sha256,
    _parse_timestamp,
    _valid_git_sha,
    _valid_sha256,
    _valid_uuid,
    _value_sha256,
    _verify_ed25519_manifest,
)


READINESS_CONTRACT_VERSION = "mlc3-general-service-readiness-v1"
DEPLOYMENT_EVIDENCE_VERSION = "mlc3-general-service-deployment-v1"
MONITORING_EVIDENCE_VERSION = "mlc3-general-service-monitoring-v1"
EMERGENCY_DISABLE_EVIDENCE_VERSION = (
    "mlc3-general-service-emergency-disable-v1"
)
TRUSTED_ATTESTATION_ISSUER = "willpowerlab-release-operator"
TRUSTED_ATTESTATION_KEY_ID = "mlc3-founder-canary-2026-09"

_BACKEND_GATES = {
    "MLC3_SERVICE_ENABLED",
    "MLC3_COACH_INLINE_AUTHORING_ENABLED",
    "MLC2_DATASET_RELEASES_ENABLED",
    "MLC2_TRAINING_ENABLED",
    "MLC2_EVALUATION_ENABLED",
    "MLC2_PROMOTION_ENABLED",
}
_FRONTEND_GATES = {
    "NEXT_PUBLIC_MLC3_SERVICE_UI_ENABLED",
    "NEXT_PUBLIC_MLC3_COACH_INLINE_AUTHORING_ENABLED",
}
_DISABLED_TARGETS = {
    "database_rollout_state": "disabled",
    "database_service_contract_state": "disabled",
    "MLC3_SERVICE_ENABLED": False,
    "MLC3_COACH_INLINE_AUTHORING_ENABLED": False,
    "NEXT_PUBLIC_MLC3_SERVICE_UI_ENABLED": False,
    "NEXT_PUBLIC_MLC3_COACH_INLINE_AUTHORING_ENABLED": False,
}
_MONITOR_SIGNALS = {
    "rollout_or_enrollment_lineage_violation",
    "authorization_deletion_or_cross_principal_violation",
    "r2_hash_or_recovery_violation",
    "feedback_offer_playback_or_practice_failure",
    "blind_review_guidance_or_inline_authoring_failure",
    "capacity_or_backpressure_violation",
    "dataset_or_learning_boundary_violation",
}


@dataclass(frozen=True)
class GeneralServiceReadinessReport:
    ready_for_activation_review: bool
    blocker_codes: tuple[str, ...]
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "readiness_contract_version": READINESS_CONTRACT_VERSION,
            "ready_for_activation_review": self.ready_for_activation_review,
            "blocker_codes": list(self.blocker_codes),
            "evidence": self.evidence,
        }


def _exact_disabled_gates(value: object, expected: set[str]) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == expected
        and all(item is False for item in value.values())
    )


def _valid_emergency_disable(value: object, now: datetime | None) -> bool:
    if not isinstance(value, Mapping):
        return False
    attempts_value = value.get("attempts")
    attempts = attempts_value if isinstance(attempts_value, list) else []
    if (
        value.get("contract_version")
        != EMERGENCY_DISABLE_EVIDENCE_VERSION
        or value.get("mode") != "idempotent_disabled_rehearsal"
        or len(attempts) != 2
        or value.get("final_states") != _DISABLED_TARGETS
        or value.get("verification_completed") is not True
        or not _valid_sha256(value.get("rollback_command_sha256"))
        or not _fresh_timestamp(value.get("verified_at"), now)
    ):
        return False
    operation_ids: set[str] = set()
    previous_after: Mapping[str, Any] | None = None
    previous_completed: datetime | None = None
    for number, attempt in enumerate(attempts, start=1):
        if not isinstance(attempt, Mapping):
            return False
        operation_id = str(attempt.get("operation_id") or "")
        started = _parse_timestamp(attempt.get("started_at"))
        completed = _parse_timestamp(attempt.get("completed_at"))
        before = attempt.get("before_states")
        after = attempt.get("after_states")
        identity = {
            key: item for key, item in attempt.items()
            if key != "result_sha256"
        }
        if (
            attempt.get("attempt_number") != number
            or not _valid_uuid(operation_id)
            or operation_id in operation_ids
            or started is None or completed is None or started > completed
            or (previous_completed is not None and previous_completed > started)
            or not _fresh_timestamp(attempt.get("started_at"), now)
            or not _fresh_timestamp(attempt.get("completed_at"), now)
            or not isinstance(before, Mapping)
            or set(before) != set(_DISABLED_TARGETS)
            or after != _DISABLED_TARGETS
            or (number == 2 and before != previous_after)
            or attempt.get("completed") is not True
            or attempt.get("result_sha256") != _value_sha256(identity)
        ):
            return False
        operation_ids.add(operation_id)
        previous_after = after
        previous_completed = completed
    return True


def validate_general_deployment_attestation(
    manifest: Mapping[str, Any], *, backend_commit: str,
    frontend_commit: str, monitor_code_sha256: str,
    trusted_public_key_pem: bytes,
    trusted_issuer: str = TRUSTED_ATTESTATION_ISSUER,
    trusted_key_id: str = TRUSTED_ATTESTATION_KEY_ID,
    now: datetime | None = None,
) -> bool:
    """Validate exact disabled Railway/Vercel, monitor, and rollback proof."""
    if (
        manifest.get("contract_version") != DEPLOYMENT_EVIDENCE_VERSION
        or manifest.get("environment") != "production"
        or manifest.get("backend_commit_sha") != backend_commit
        or manifest.get("frontend_commit_sha") != frontend_commit
        or not _valid_git_sha(backend_commit)
        or not _valid_git_sha(frontend_commit)
        or not _valid_sha256(monitor_code_sha256)
        or manifest.get("issuer") != trusted_issuer
        or manifest.get("key_id") != trusted_key_id
        or not _fresh_timestamp(manifest.get("verified_at"), now)
        or manifest.get("evidence_sha256") != _manifest_sha256(manifest)
        or not _verify_ed25519_manifest(manifest, trusted_public_key_pem)
    ):
        return False
    railway = manifest.get("railway_authenticated_provider_export")
    vercel = manifest.get("vercel_authenticated_provider_export")
    if not isinstance(railway, Mapping) or not isinstance(vercel, Mapping):
        return False
    services = railway.get("services")
    if (
        railway.get("source") != "railway_authenticated_api"
        or not railway.get("request_id")
        or not railway.get("project_id")
        or not railway.get("environment_id")
        or not isinstance(services, list) or len(services) != 3
        or railway.get("observed_service_count") != 3
        or railway.get("service_inventory_sha256")
        != _value_sha256(sorted(services, key=lambda row: row.get("service_id", "")))
    ):
        return False
    roles: set[str] = set()
    monitor_service_id = ""
    for service in services:
        if not isinstance(service, Mapping):
            return False
        role = str(service.get("role") or "")
        gates = service.get("effective_gates")
        if (
            role not in {"web", "worker", "monitor"} or role in roles
            or not service.get("service_id") or not service.get("deployment_id")
            or service.get("commit_sha") != backend_commit
            or not _exact_disabled_gates(gates, _BACKEND_GATES)
        ):
            return False
        identity = {
            "service_id": service.get("service_id"),
            "deployment_id": service.get("deployment_id"),
            "role": role,
            "commit_sha": service.get("commit_sha"),
            "effective_gates": gates,
        }
        if role == "monitor":
            config = service.get("monitor_config")
            if (
                not isinstance(config, Mapping)
                or config.get("schedule") != "*/5 * * * *"
                or config.get("start_command")
                != "bin/railway-mlc3-general-service-monitor.sh"
                or config.get("expected_rollout_state") != "disabled"
                or config.get("monitor_contract_version")
                != "mlc3-general-service-monitor-v1"
                or config.get("monitor_code_sha256") != monitor_code_sha256
                or config.get("start_command_sha256")
                != sha256(
                    b"bin/railway-mlc3-general-service-monitor.sh"
                ).hexdigest()
            ):
                return False
            identity["monitor_config"] = config
            monitor_service_id = str(service.get("service_id"))
        if service.get("config_sha256") != _value_sha256(identity):
            return False
        roles.add(role)
    if roles != {"web", "worker", "monitor"}:
        return False
    frontend_gates = vercel.get("effective_build_gates")
    build_identity = {
        "deployment_id": vercel.get("deployment_id"),
        "commit_sha": vercel.get("commit_sha"),
        "effective_build_gates": frontend_gates,
    }
    if (
        vercel.get("source") != "vercel_authenticated_api"
        or not vercel.get("request_id") or not vercel.get("project_id")
        or not vercel.get("deployment_id")
        or vercel.get("commit_sha") != frontend_commit
        or not _exact_disabled_gates(frontend_gates, _FRONTEND_GATES)
        or vercel.get("build_config_sha256") != _value_sha256(build_identity)
    ):
        return False
    monitoring = manifest.get("monitoring")
    if (
        not isinstance(monitoring, Mapping)
        or monitoring.get("contract_version") != MONITORING_EVIDENCE_VERSION
        or monitoring.get("monitor_service_id") != monitor_service_id
        or set(monitoring.get("covered_signals") or ()) != _MONITOR_SIGNALS
        or monitoring.get("sentry_test_event_received") is not True
        or monitoring.get("operations_alert_received") is not True
        or not monitoring.get("sentry_event_id")
        or not _valid_sha256(monitoring.get("sentry_receipt_sha256"))
        or not monitoring.get("operations_receipt_id")
        or not _valid_sha256(monitoring.get("operations_receipt_sha256"))
        or not _fresh_timestamp(monitoring.get("verified_at"), now)
    ):
        return False
    return _valid_emergency_disable(
        manifest.get("emergency_disable_rehearsal"), now,
    )


def assess_general_service_readiness(
    health: Mapping[str, Any], *, deployment_attestation_valid: bool,
    r2_evidence_valid: bool, local_product_gates: Mapping[str, bool],
    local_learning_gates: Mapping[str, bool],
) -> GeneralServiceReadinessReport:
    """Return readiness for activation review, never activation authority."""
    blockers: list[str] = []
    required_zero = (
        "missing_required_rpc_count", "missing_service_rpc_grant_count",
        "forbidden_rpc_runtime_grant_count", "missing_required_table_count",
        "rls_disabled_table_count", "runtime_table_write_grant_count",
        "active_service_rows_without_enrollment", "dataset_eligible_rows",
        "unresolved_practice_recoveries", "unresolved_coach_recoveries",
    )
    if health.get("readiness_contract_version") != READINESS_CONTRACT_VERSION:
        blockers.append("readiness_health_contract_mismatch")
    if health.get("monitor_contract_version") != (
        "mlc3-general-service-monitor-v1"
    ):
        blockers.append("monitor_contract_mismatch")
    if health.get("rollout_state") != "disabled":
        blockers.append("database_rollout_must_remain_disabled")
    if health.get("service_contract_state") != "disabled":
        blockers.append("database_service_contract_must_remain_disabled")
    for key in required_zero:
        if health.get(key) != 0:
            blockers.append(f"{key}_invalid")
    if health.get("approved_need_contract_count") != 1:
        blockers.append("approved_n1_contract_missing_or_ambiguous")
    if health.get("active_coach_count", 0) < 1:
        blockers.append("active_coach_capacity_missing")
    if health.get("security_closure_0325_applied") is not True:
        blockers.append("security_closure_0325_missing")
    if any(local_product_gates.values()):
        blockers.append("local_product_gates_must_remain_disabled")
    if any(local_learning_gates.values()):
        blockers.append("learning_gates_must_remain_disabled")
    if not deployment_attestation_valid:
        blockers.append("production_deployment_attestation_invalid")
    if not r2_evidence_valid:
        blockers.append("live_r2_evidence_invalid")
    return GeneralServiceReadinessReport(
        ready_for_activation_review=not blockers,
        blocker_codes=tuple(dict.fromkeys(blockers)),
        evidence={
            "aggregate_only": True,
            "deployment_attestation_valid": deployment_attestation_valid,
            "r2_evidence_valid": r2_evidence_valid,
            "all_product_gates_disabled": not any(local_product_gates.values()),
            "all_learning_gates_disabled": not any(local_learning_gates.values()),
            "activation_performed": False,
        },
    )
