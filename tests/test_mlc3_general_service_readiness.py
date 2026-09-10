from __future__ import annotations

import base64
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import re
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)

from services.mlc3_general_service_readiness import (
    DEPLOYMENT_EVIDENCE_VERSION,
    EMERGENCY_DISABLE_EVIDENCE_VERSION,
    MONITORING_EVIDENCE_VERSION,
    READINESS_CONTRACT_VERSION,
    assess_general_service_readiness,
    validate_general_deployment_attestation,
)
from scripts.check_mlc3_general_service_readiness import (
    _D4_TABLES,
    _FORBIDDEN_RPCS,
    _REQUIRED_RPCS,
)


NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
BACKEND = "a" * 40
FRONTEND = "b" * 40
MONITOR_SHA = "c" * 64
BACKEND_GATES = {
    "MLC3_SERVICE_ENABLED": False,
    "MLC3_COACH_INLINE_AUTHORING_ENABLED": False,
    "MLC2_DATASET_RELEASES_ENABLED": False,
    "MLC2_TRAINING_ENABLED": False,
    "MLC2_EVALUATION_ENABLED": False,
    "MLC2_PROMOTION_ENABLED": False,
}
FRONTEND_GATES = {
    "NEXT_PUBLIC_MLC3_SERVICE_UI_ENABLED": False,
    "NEXT_PUBLIC_MLC3_COACH_INLINE_AUTHORING_ENABLED": False,
}
DISABLED = {
    "database_rollout_state": "disabled",
    "database_service_contract_state": "disabled",
    "MLC3_SERVICE_ENABLED": False,
    "MLC3_COACH_INLINE_AUTHORING_ENABLED": False,
    "NEXT_PUBLIC_MLC3_SERVICE_UI_ENABLED": False,
    "NEXT_PUBLIC_MLC3_COACH_INLINE_AUTHORING_ENABLED": False,
}


def _hash(value) -> str:
    return sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()


def _private_key():
    return Ed25519PrivateKey.generate()


def _sign(value: dict, private_key) -> dict:
    result = deepcopy(value)
    result["evidence_sha256"] = _hash(result)
    payload = json.dumps(
        result, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()
    result["signature_ed25519_base64"] = base64.b64encode(
        private_key.sign(payload)
    ).decode()
    return result


def _attempt(number: int, start: datetime) -> dict:
    result = {
        "attempt_number": number,
        "operation_id": str(uuid4()),
        "started_at": start.isoformat(),
        "completed_at": (start + timedelta(seconds=1)).isoformat(),
        "before_states": DISABLED,
        "after_states": DISABLED,
        "completed": True,
    }
    result["result_sha256"] = _hash(result)
    return result


def _manifest(private_key) -> dict:
    services = []
    monitor_id = "monitor-service"
    for role in ("web", "worker", "monitor"):
        item = {
            "service_id": monitor_id if role == "monitor" else f"{role}-service",
            "deployment_id": f"{role}-deployment",
            "role": role,
            "commit_sha": BACKEND,
            "effective_gates": BACKEND_GATES,
        }
        if role == "monitor":
            item["monitor_config"] = {
                "schedule": "*/5 * * * *",
                "start_command": "bin/railway-mlc3-general-service-monitor.sh",
                "expected_rollout_state": "disabled",
                "monitor_contract_version": "mlc3-general-service-monitor-v1",
                "monitor_code_sha256": MONITOR_SHA,
                "start_command_sha256": sha256(
                    b"bin/railway-mlc3-general-service-monitor.sh"
                ).hexdigest(),
            }
        item["config_sha256"] = _hash({
            key: value for key, value in item.items()
            if key != "config_sha256"
        })
        services.append(item)
    railway = {
        "source": "railway_authenticated_api",
        "request_id": "railway-request",
        "project_id": "project",
        "environment_id": "production",
        "observed_service_count": 3,
        "services": services,
        "service_inventory_sha256": _hash(sorted(
            services, key=lambda row: row["service_id"],
        )),
    }
    vercel = {
        "source": "vercel_authenticated_api",
        "request_id": "vercel-request",
        "project_id": "frontend",
        "deployment_id": "frontend-deployment",
        "commit_sha": FRONTEND,
        "effective_build_gates": FRONTEND_GATES,
    }
    vercel["build_config_sha256"] = _hash({
        "deployment_id": vercel["deployment_id"],
        "commit_sha": vercel["commit_sha"],
        "effective_build_gates": FRONTEND_GATES,
    })
    first = _attempt(1, NOW - timedelta(minutes=2))
    second = _attempt(2, NOW - timedelta(minutes=1))
    return _sign({
        "contract_version": DEPLOYMENT_EVIDENCE_VERSION,
        "environment": "production",
        "backend_commit_sha": BACKEND,
        "frontend_commit_sha": FRONTEND,
        "issuer": "willpowerlab-release-operator",
        "key_id": "mlc3-founder-canary-2026-09",
        "verified_at": NOW.isoformat(),
        "railway_authenticated_provider_export": railway,
        "vercel_authenticated_provider_export": vercel,
        "monitoring": {
            "contract_version": MONITORING_EVIDENCE_VERSION,
            "monitor_service_id": monitor_id,
            "covered_signals": sorted({
                "rollout_or_enrollment_lineage_violation",
                "authorization_deletion_or_cross_principal_violation",
                "r2_hash_or_recovery_violation",
                "feedback_offer_playback_or_practice_failure",
                "blind_review_guidance_or_inline_authoring_failure",
                "capacity_or_backpressure_violation",
                "dataset_or_learning_boundary_violation",
            }),
            "sentry_test_event_received": True,
            "operations_alert_received": True,
            "sentry_event_id": "sentry-event",
            "sentry_receipt_sha256": "d" * 64,
            "operations_receipt_id": "operations-event",
            "operations_receipt_sha256": "e" * 64,
            "verified_at": NOW.isoformat(),
        },
        "emergency_disable_rehearsal": {
            "contract_version": EMERGENCY_DISABLE_EVIDENCE_VERSION,
            "mode": "idempotent_disabled_rehearsal",
            "attempts": [first, second],
            "final_states": DISABLED,
            "verification_completed": True,
            "rollback_command_sha256": "f" * 64,
            "verified_at": NOW.isoformat(),
        },
    }, private_key)


def _public_pem(private_key) -> bytes:
    return private_key.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo,
    )


def test_signed_exact_deployment_monitor_and_two_pass_disable_are_valid():
    key = _private_key()
    assert validate_general_deployment_attestation(
        _manifest(key), backend_commit=BACKEND, frontend_commit=FRONTEND,
        monitor_code_sha256=MONITOR_SHA,
        trusted_public_key_pem=_public_pem(key), now=NOW,
    )


def test_wrong_monitor_or_duplicated_disable_operation_fails_closed():
    key = _private_key()
    for mutate in ("schedule", "duplicate"):
        value = _manifest(key)
        unsigned = {k: v for k, v in value.items()
                    if k not in {"evidence_sha256", "signature_ed25519_base64"}}
        if mutate == "schedule":
            unsigned["railway_authenticated_provider_export"]["services"][2][
                "monitor_config"
            ]["schedule"] = "0 * * * *"
        else:
            attempts = unsigned["emergency_disable_rehearsal"]["attempts"]
            attempts[1]["operation_id"] = attempts[0]["operation_id"]
            attempts[1]["result_sha256"] = _hash({
                k: v for k, v in attempts[1].items() if k != "result_sha256"
            })
        value = _sign(unsigned, key)
        assert not validate_general_deployment_attestation(
            value, backend_commit=BACKEND, frontend_commit=FRONTEND,
            monitor_code_sha256=MONITOR_SHA,
            trusted_public_key_pem=_public_pem(key), now=NOW,
        )


def test_readiness_requires_disabled_clean_surface_and_external_evidence():
    health = {
        "readiness_contract_version": READINESS_CONTRACT_VERSION,
        "monitor_contract_version": "mlc3-general-service-monitor-v1",
        "rollout_state": "disabled",
        "service_contract_state": "disabled",
        "approved_need_contract_count": 1,
        "active_coach_count": 1,
        "security_closure_0325_applied": True,
        **{key: 0 for key in (
            "missing_required_rpc_count", "missing_service_rpc_grant_count",
            "forbidden_rpc_runtime_grant_count", "missing_required_table_count",
            "rls_disabled_table_count", "runtime_table_write_grant_count",
            "active_service_rows_without_enrollment", "dataset_eligible_rows",
            "unresolved_practice_recoveries", "unresolved_coach_recoveries",
        )},
    }
    report = assess_general_service_readiness(
        health, deployment_attestation_valid=True, r2_evidence_valid=True,
        local_product_gates={"user": False, "coach": False},
        local_learning_gates={"dataset": False, "training": False},
    )
    assert report.ready_for_activation_review
    blocked = assess_general_service_readiness(
        {**health, "dataset_eligible_rows": 1},
        deployment_attestation_valid=True, r2_evidence_valid=True,
        local_product_gates={"user": False},
        local_learning_gates={"dataset": False},
    )
    assert not blocked.ready_for_activation_review
    assert "dataset_eligible_rows_invalid" in blocked.blocker_codes


def test_readiness_registry_covers_d4_and_closes_superseded_writers():
    assert set(_D4_TABLES) == {
        "mlc3_service_cohort_sets",
        "mlc3_service_cohort_members",
        "mlc3_service_activation_risk_decisions",
        "mlc3_service_rollout_revisions",
        "mlc3_service_enrollment_revisions",
        "mlc3_service_access_events",
        "mlc3_speaker_acquisition_revisions",
        "mlc3_self_speaker_assertions",
        "mlc3_target_speaker_bindings",
        "mlc3_comparison_speaker_eligibility_revisions",
        "mlc3_service_backpressure_events",
    }
    assert {
        "ensure_mlc3_service_enrollment_v2(uuid,uuid,text)",
        "require_mlc3_service_access_v2(uuid,uuid,uuid)",
        "record_mlc3_feedback_self_speaker_target_v1(uuid,uuid,uuid,uuid,text)",
        "confirm_mlc3_practice_speaker_and_pair_v1(uuid,uuid,uuid,text)",
        "reserve_exercise_practice_service_upload_v2(uuid,uuid,uuid,text,bigint,text,text,text,integer)",
        "get_mlc3_general_service_monitor_v1()",
        "halt_mlc3_service_rollout_v1(text,text)",
    }.issubset(_REQUIRED_RPCS)
    assert {
        "require_mlc3_current_pair_speaker_identity_v1(uuid,uuid)",
        "assign_synthetic_exercise_pair_v1(uuid,uuid,text,text)",
        "submit_synthetic_exercise_pair_judgment_v1(uuid,uuid,text,text)",
        "reserve_exercise_practice_service_upload_v1(uuid,uuid,integer,uuid,text,bigint,text,text,text,integer)",
    }.issubset(_FORBIDDEN_RPCS)
    assert not any(
        signature.startswith("reserve_exercise_practice_service_upload_v1(")
        for signature in _REQUIRED_RPCS
    )
    repository = (Path(__file__).resolve().parents[1] / (
        "services/first_client_repository.py"
    )).read_text()
    called = set(re.findall(
        r'self\.client\.rpc\(\s*"([a-z0-9_]+)"', repository,
    ))
    registered = {signature.split("(", 1)[0] for signature in _REQUIRED_RPCS}
    assert called <= registered
    assert registered - called == {
        "require_mlc3_service_access_v2",
        "get_mlc3_general_service_monitor_v1",
        "halt_mlc3_service_rollout_v1",
    }
    assert len(_REQUIRED_RPCS) == len(registered)
