from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import base64
import json
from pathlib import Path
import re

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from scripts.check_mlc3_founder_canary_readiness import (
    _DEPENDENCY_TABLES,
    _FORBIDDEN_RPC_SIGNATURES,
    _REQUIRED_RPC_SIGNATURES,
    _RLS_TABLES,
    _SERVICE_ZERO_PREDICATES,
)
from scripts.sign_mlc3_founder_deployment_attestation import sign_manifest
from scripts import rehearse_mlc3_founder_r2 as r2_rehearsal

from services.mlc3_founder_canary_readiness import (
    READINESS_CONTRACT_VERSION,
    DEPLOYMENT_ATTESTATION_VERSION,
    EMERGENCY_DISABLE_EVIDENCE_VERSION,
    MONITORING_EVIDENCE_VERSION,
    R2_EVIDENCE_VERSION,
    SERVICE_CONTRACT_VERSION,
    TRUSTED_ATTESTATION_ISSUER,
    TRUSTED_ATTESTATION_KEY_ID,
    assess_founder_canary_readiness,
    validate_deployment_attestation,
    validate_r2_smoke_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT / "scripts" / "check_mlc3_founder_canary_readiness.py"
).read_text()
R2_SCRIPT = (ROOT / "scripts/rehearse_mlc3_founder_r2.py").read_text()
SECURITY_MIGRATION = (
    ROOT / "migrations" / "add_mlc3_founder_canary_security_closure.sql"
).read_text()
REPOSITORY = (ROOT / "services/first_client_repository.py").read_text()

PRINCIPAL = "11111111-1111-4111-8111-111111111111"
SHA = "a" * 64
_TEST_PRIVATE_KEY = Ed25519PrivateKey.generate()
_TEST_PUBLIC_KEY = _TEST_PRIVATE_KEY.public_key().public_bytes(
    Encoding.PEM, PublicFormat.SubjectPublicKeyInfo,
)


def _sign(payload):
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()
    return {**payload, "evidence_sha256": sha256(canonical).hexdigest()}


def _attest(payload, private_key=_TEST_PRIVATE_KEY):
    with_hash = _sign(payload)
    canonical = json.dumps(
        with_hash, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()
    return {
        **with_hash,
        "signature_ed25519_base64": base64.b64encode(
            private_key.sign(canonical)
        ).decode(),
    }


def _hash_value(value):
    return sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()


def _r2_manifest():
    controls = _attest({
        "contract_version": "mlc3-cloudflare-r2-privacy-v1",
        "issuer": TRUSTED_ATTESTATION_ISSUER,
        "key_id": TRUSTED_ATTESTATION_KEY_ID,
        "source": "cloudflare_authenticated_api",
        "request_id": "cloudflare-request",
        "account_id_sha256": sha256(b"account").hexdigest(),
        "buckets": [
            {
                "role": role,
                "bucket": bucket,
                "public_access_enabled": False,
                "r2_dev_domain_enabled": False,
                "custom_domain_count": 0,
            }
            for role, bucket in (
                ("practice_audio", "private-practice-audio"),
                ("coach_video", "private-coach-video"),
            )
        ],
    })
    return _attest({
        "contract_version": R2_EVIDENCE_VERSION,
        "environment": "production",
        "issuer": TRUSTED_ATTESTATION_ISSUER,
        "key_id": TRUSTED_ATTESTATION_KEY_ID,
        "endpoint": "https://account.r2.cloudflarestorage.com",
        "account_id_sha256": sha256(b"account").hexdigest(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "cloudflare_authenticated_provider_export": controls,
        "cloudflare_provider_export_sha256": _hash_value(controls),
        "results": [
            {
                "role": role, "bucket": bucket, "byte_size": 64,
                "object_key_sha256": sha256(role.encode()).hexdigest(),
                "object_key_prefix": "mlc3-founder-readiness/",
                "write_sha256": SHA, "read_sha256": SHA,
                "write_verified": True, "read_verified": True,
                "deletion_verified": True,
            }
            for role, bucket in (
                ("practice_audio", "private-practice-audio"),
                ("coach_video", "private-coach-video"),
            )
        ],
    })


def _deployment_manifest():
    backend_gates = {
        "MLC3_PILOT_ENABLED": False,
        "MLC3_COACH_INLINE_AUTHORING_ENABLED": False,
        "MLC2_DATASET_RELEASES_ENABLED": False,
        "MLC2_TRAINING_ENABLED": False,
        "MLC2_EVALUATION_ENABLED": False,
        "MLC2_PROMOTION_ENABLED": False,
    }
    services = [
        {
            "service_id": role, "role": role,
            "deployment_id": f"deployment-{role}",
            "commit_sha": "b" * 40,
            "effective_gates": backend_gates,
        }
        for role in ("web", "worker", "monitor")
    ]
    for service in services:
        if service["role"] == "monitor":
            service["monitor_config"] = {
                "schedule": "*/5 * * * *",
                "start_command": (
                    "bin/railway-mlc3-founder-canary-monitor.sh"
                ),
                "start_command_sha256": sha256(
                    b"bin/railway-mlc3-founder-canary-monitor.sh"
                ).hexdigest(),
                "founder_principal_id": PRINCIPAL,
                "expected_contract_state": "disabled",
                "monitor_contract_version": "mlc3-founder-canary-monitor-v1",
                "monitor_code_sha256": SHA,
            }
        service["config_sha256"] = _hash_value(service)
    frontend_export = {
        "source": "vercel_authenticated_api",
        "request_id": "vercel-request",
        "project_id": "vercel-project",
        "deployment_id": "vercel-deployment",
        "commit_sha": "f" * 40,
        "effective_build_gates": {
            "NEXT_PUBLIC_MLC3_PILOT_UI_ENABLED": False,
            "NEXT_PUBLIC_MLC3_COACH_INLINE_AUTHORING_ENABLED": False,
        },
    }
    frontend_export["build_config_sha256"] = _hash_value({
        key: frontend_export[key] for key in (
            "deployment_id", "commit_sha", "effective_build_gates",
        )
    })
    railway_export = {
        "source": "railway_authenticated_api",
        "request_id": "railway-request",
        "project_id": "railway-project",
        "environment_id": "production",
        "service_inventory_sha256": _hash_value(sorted(
            services, key=lambda row: row["service_id"],
        )),
        "observed_service_count": len(services),
        "services": services,
    }
    now = datetime.now(timezone.utc).isoformat()
    disabled_targets = {
        "database_contract_state": "disabled",
        "MLC3_PILOT_ENABLED": False,
        "MLC3_COACH_INLINE_AUTHORING_ENABLED": False,
        "NEXT_PUBLIC_MLC3_PILOT_UI_ENABLED": False,
        "NEXT_PUBLIC_MLC3_COACH_INLINE_AUTHORING_ENABLED": False,
    }
    attempts = []
    for number in (1, 2):
        attempt = {
            "attempt_number": number,
            "operation_id": (
                f"00000000-0000-4000-8000-00000000000{number}"
            ),
            "started_at": now,
            "completed_at": now,
            "before_states": dict(disabled_targets),
            "after_states": dict(disabled_targets),
            "completed": True,
        }
        attempt["result_sha256"] = _hash_value(attempt)
        attempts.append(attempt)
    return _attest({
        "contract_version": DEPLOYMENT_ATTESTATION_VERSION,
        "environment": "production",
        "verified_at": now,
        "issuer": TRUSTED_ATTESTATION_ISSUER,
        "key_id": TRUSTED_ATTESTATION_KEY_ID,
        "backend_commit_sha": "b" * 40,
        "frontend_commit_sha": "f" * 40,
        "railway": {
            "provider_export_sha256": _hash_value(railway_export),
            "authenticated_provider_export": railway_export,
        },
        "vercel": {
            "provider_export_sha256": _hash_value(frontend_export),
            "authenticated_provider_export": frontend_export,
        },
        "monitoring": {
            "contract_version": MONITORING_EVIDENCE_VERSION,
            "monitor_service_id": "monitor",
            "monitor_service_role": "monitor",
            "covered_signals": [
                "service_contract_or_allowlist_violation",
                "authorization_or_deletion_violation",
                "feedback_offer_or_practice_failure",
                "blind_review_or_reveal_failure",
                "coach_guidance_or_inline_authoring_failure",
                "unresolved_practice_media_write",
                "unresolved_coach_media_write",
            ],
            "sentry_test_event_received": True,
            "operations_alert_received": True,
            "sentry_event_id": "sentry-event",
            "sentry_alert_rule_id": "sentry-alert-rule",
            "sentry_receipt_sha256": SHA,
            "operations_receipt_id": "operations-receipt",
            "operations_receipt_sha256": SHA,
            "verified_at": now,
        },
        "emergency_disable_rehearsal": {
            "contract_version": EMERGENCY_DISABLE_EVIDENCE_VERSION,
            "mode": "idempotent_disabled_rehearsal",
            "attempts": attempts,
            "final_states": dict(disabled_targets),
            "verification_completed": True,
            "rollback_command_sha256": SHA,
            "verified_at": now,
        },
    })


def _validate_deployment(manifest):
    return validate_deployment_attestation(
        manifest, backend_commit="b" * 40, frontend_commit="f" * 40,
        trusted_public_key_pem=_TEST_PUBLIC_KEY,
        trusted_issuer=TRUSTED_ATTESTATION_ISSUER,
        trusted_key_id=TRUSTED_ATTESTATION_KEY_ID,
        founder_principal_id=PRINCIPAL,
        monitor_code_sha256=SHA,
    )


def _health(**changes):
    value = {
        "readiness_contract_version": READINESS_CONTRACT_VERSION,
        "service_contract_version": SERVICE_CONTRACT_VERSION,
        "service_contract_count": 1,
        "service_contract_state": "disabled",
        "allowlisted_principal_count": 0,
        "service_mode_record_count": 0,
        "founder_principal_count": 1,
        "founder_account_binding_count": 1,
        "founder_project_count": 2,
        "active_processing_policy_count": 1,
        "required_operational_purpose_count": 2,
        "founder_current_full_service_receipt_count": 1,
        "founder_active_service_block_count": 0,
        "founder_open_purge_count": 0,
        "active_coach_allowlist_count": 1,
        "coach_principal_count": 1,
        "approved_need_contract_count": 1,
        "catalog_snapshot_count": 1,
        "approved_active_exercise_version_count": 1,
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
    value.update(changes)
    return value


def _assess(health=None, **changes):
    args = {
        "founder_principal_id": PRINCIPAL,
        "coach_email": "coach@example.com",
        "backend_serving_enabled": False,
        "backend_inline_authoring_enabled": False,
        "frontend_serving_enabled": False,
        "frontend_inline_authoring_enabled": False,
        "r2_credentials_configured": True,
        "practice_bucket": "private-practice-audio",
        "coach_video_bucket": "private-coach-video",
        "r2_smoke_evidence_sha256": SHA,
        "r2_smoke_manifest_valid": True,
        "deployment_attestation_valid": True,
        "deployed_backend_gates_disabled": True,
        "deployed_frontend_gates_disabled": True,
        "deployed_learning_gates_disabled": True,
        "dataset_creation_enabled": False,
        "training_enabled": False,
        "evaluation_enabled": False,
        "promotion_enabled": False,
    }
    args.update(changes)
    return assess_founder_canary_readiness(health or _health(), **args)


def test_ready_report_requires_all_gates_to_stay_off_until_review():
    report = _assess()
    assert report.ready_for_activation_review is True
    assert report.blocker_codes == ()
    assert report.activation_actions == (
        "activate_exact_database_service_contract",
        "allowlist_exact_founder_acquisition_principal",
        "enable_backend_founder_and_inline_gates",
        "enable_frontend_founder_and_inline_presentation_gates",
    )
    assert report.evidence["real_collection_performed"] is False


def test_any_product_gate_open_before_review_fails_closed():
    report = _assess(frontend_serving_enabled=True)
    assert report.ready_for_activation_review is False
    assert "frontend_serving_must_remain_disabled_before_review" in (
        report.blocker_codes
    )


def test_learning_capabilities_never_follow_product_activation():
    report = _assess(training_enabled=True, dataset_creation_enabled=True)
    assert "training_must_remain_disabled" in report.blocker_codes
    assert "dataset_creation_must_remain_disabled" in report.blocker_codes


def test_exact_principal_coach_authority_and_deletion_are_required():
    report = _assess(_health(
        founder_account_binding_count=0,
        active_coach_allowlist_count=0,
        founder_open_purge_count=1,
    ))
    assert {
        "founder_account_binding_count_invalid",
        "active_coach_allowlist_count_invalid",
        "founder_open_purge_count_invalid",
    } <= set(report.blocker_codes)


def test_one_or_more_current_service_receipts_are_accepted():
    report = _assess(_health(
        active_processing_policy_count=2,
        founder_current_full_service_receipt_count=3,
    ))
    assert report.ready_for_activation_review is True
    missing = _assess(_health(
        active_processing_policy_count=0,
        required_operational_purpose_count=1,
        founder_current_full_service_receipt_count=0,
    ))
    assert {
        "active_processing_policy_missing",
        "required_processing_purpose_not_operational",
        "founder_current_full_service_receipt_missing",
    } <= set(missing.blocker_codes)


def test_live_r2_evidence_and_distinct_private_buckets_are_required():
    report = _assess(
        r2_smoke_evidence_sha256="",
        r2_smoke_manifest_valid=False,
        practice_bucket="shared",
        coach_video_bucket="shared",
    )
    assert "live_r2_synthetic_rehearsal_not_verified" in report.blocker_codes
    assert "live_r2_rehearsal_manifest_invalid" in report.blocker_codes
    assert "practice_and_coach_media_buckets_must_be_distinct" in (
        report.blocker_codes
    )


def test_catalogue_can_warn_for_no_match_but_frozen_inventory_is_required():
    report = _assess(_health(approved_active_exercise_version_count=0))
    assert report.ready_for_activation_review is True
    assert report.warning_codes == (
        "no_matching_exercise_may_require_inline_authoring",
    )
    blocked = _assess(_health(catalog_snapshot_count=0))
    assert "reviewed_catalogue_snapshot_missing" in blocked.blocker_codes


def test_database_contract_and_runtime_records_must_remain_dark():
    report = _assess(_health(
        service_contract_state="active",
        allowlisted_principal_count=1,
        service_mode_record_count=1,
    ))
    assert {
        "database_service_gate_must_remain_disabled",
        "principal_allowlist_must_be_empty_before_review",
        "unexpected_service_records_before_activation",
    } <= set(report.blocker_codes)


def test_each_service_family_independently_blocks_a_false_zero_state():
    for key in (
        "service_feedback_record_count", "service_offer_record_count",
        "service_practice_record_count", "service_comparison_record_count",
        "service_blind_review_record_count",
        "service_coach_guidance_record_count",
        "service_inline_authoring_record_count",
    ):
        report = _assess(_health(**{key: 1, "service_mode_record_count": 1}))
        assert f"{key}_invalid" in report.blocker_codes


def test_script_is_select_only_and_checks_full_chain_security():
    lowered = SCRIPT.lower()
    assert "insert into" not in lowered
    assert "update public." not in lowered
    assert "delete from" not in lowered
    for token in (
        "ack_feedback_v3_service_render_v1",
        "freeze_exercise_service_offer_v2",
        "create_exercise_practice_service_session_v1",
        "finalize_exercise_practice_service_media_v1",
        "freeze_exercise_practice_service_selection_v1",
        "freeze_exercise_service_pair_v1",
        "freeze_exercise_service_blind_review_set_v1",
        "prepare_coach_inline_guidance_context_v1",
        "create_coach_inline_exercise_draft_v1",
        "create_coach_inline_general_guidance_v1",
        "resolve_coach_inline_blind_audio_read_v1",
        "authorize_exercise_practice_transcription_v1",
        "dataset_eligible_record_count",
        "runtime_rpc_client_grant_count",
        "runtime_table_write_grant_count",
    ):
        assert token in SCRIPT


def test_script_resolves_rls_tables_in_public_schema_exactly():
    assert "to_regclass('public.' || required.name)" in SCRIPT
    assert "relation.relname=required.name" not in SCRIPT


def test_script_fails_closed_when_database_contract_is_unavailable():
    assert "readiness_database_contract_unavailable" in SCRIPT
    assert "connection.rollback()" in SCRIPT


def test_r2_manifest_binds_buckets_roundtrip_deletion_and_hash():
    manifest = _r2_manifest()
    assert validate_r2_smoke_manifest(
        manifest, account_id="account",
        practice_bucket="private-practice-audio",
        coach_video_bucket="private-coach-video",
        trusted_public_key_pem=_TEST_PUBLIC_KEY,
        trusted_issuer=TRUSTED_ATTESTATION_ISSUER,
        trusted_key_id=TRUSTED_ATTESTATION_KEY_ID,
    )
    for mutation in (
        lambda value: value["results"][0].update(bucket="foreign"),
        lambda value: value["results"][0].update(deletion_verified=False),
        lambda value: value["results"][0].update(read_sha256="b" * 64),
    ):
        changed = json.loads(json.dumps(manifest))
        mutation(changed)
        assert not validate_r2_smoke_manifest(
            changed, account_id="account",
            practice_bucket="private-practice-audio",
            coach_video_bucket="private-coach-video",
            trusted_public_key_pem=_TEST_PUBLIC_KEY,
            trusted_issuer=TRUSTED_ATTESTATION_ISSUER,
            trusted_key_id=TRUSTED_ATTESTATION_KEY_ID,
        )


def test_unsigned_or_public_r2_evidence_fails_closed():
    manifest = _r2_manifest()
    unsigned = {key: value for key, value in manifest.items()
                if key != "signature_ed25519_base64"}
    assert not validate_r2_smoke_manifest(
        unsigned, account_id="account",
        practice_bucket="private-practice-audio",
        coach_video_bucket="private-coach-video",
        trusted_public_key_pem=_TEST_PUBLIC_KEY,
        trusted_issuer=TRUSTED_ATTESTATION_ISSUER,
        trusted_key_id=TRUSTED_ATTESTATION_KEY_ID,
    )
    public = json.loads(json.dumps(manifest))
    control = public["cloudflare_authenticated_provider_export"]
    control["buckets"][0]["public_access_enabled"] = True
    control = _attest({
        key: value for key, value in control.items()
        if key not in {"evidence_sha256", "signature_ed25519_base64"}
    })
    public["cloudflare_authenticated_provider_export"] = control
    public["cloudflare_provider_export_sha256"] = _hash_value(control)
    public = _attest({
        key: value for key, value in public.items()
        if key not in {"evidence_sha256", "signature_ed25519_base64"}
    })
    assert not validate_r2_smoke_manifest(
        public, account_id="account",
        practice_bucket="private-practice-audio",
        coach_video_bucket="private-coach-video",
        trusted_public_key_pem=_TEST_PUBLIC_KEY,
        trusted_issuer=TRUSTED_ATTESTATION_ISSUER,
        trusted_key_id=TRUSTED_ATTESTATION_KEY_ID,
    )


def test_unsigned_cloudflare_export_causes_zero_r2_storage_calls(
    tmp_path, monkeypatch,
):
    controls = _r2_manifest()["cloudflare_authenticated_provider_export"]
    controls.pop("signature_ed25519_base64")
    export_path = tmp_path / "unsigned-cloudflare.json"
    export_path.write_text(json.dumps(controls))
    monkeypatch.setattr(r2_rehearsal.Config, "R2_ACCOUNT_ID", "account")
    monkeypatch.setattr(
        r2_rehearsal.Config, "R2_ACCESS_KEY_ID", "synthetic-key",
    )
    monkeypatch.setattr(
        r2_rehearsal.Config, "R2_SECRET_ACCESS_KEY", "synthetic-secret",
    )
    monkeypatch.setattr(
        r2_rehearsal.Config, "R2_USER_MEDIA_BUCKET",
        "private-practice-audio",
    )
    monkeypatch.setattr(
        r2_rehearsal.Config, "R2_BUCKET_NAME", "private-coach-video",
    )
    storage_called = False

    def forbidden_client():
        nonlocal storage_called
        storage_called = True
        raise AssertionError("storage client must not be constructed")

    monkeypatch.setattr(r2_rehearsal, "_client", forbidden_client)
    with pytest.raises(SystemExit, match="SIGNATURE_OR_PRIVACY_INVALID"):
        r2_rehearsal.main([
            "--confirm", "write-read-delete-synthetic-r2-objects",
            "--cloudflare-control-plane-export", str(export_path),
        ])
    assert storage_called is False


def test_deployment_attestation_binds_all_services_and_vercel_build():
    manifest = _deployment_manifest()
    assert _validate_deployment(manifest)
    changed = json.loads(json.dumps(manifest))
    changed["railway"]["authenticated_provider_export"]["services"] = (
        changed["railway"]["authenticated_provider_export"]["services"][:2]
    )
    changed = _attest({key: value for key, value in changed.items()
                       if key not in {"evidence_sha256", "signature_ed25519_base64"}})
    assert not _validate_deployment(changed)
    enabled = json.loads(json.dumps(manifest))
    enabled["vercel"]["authenticated_provider_export"]["effective_build_gates"][
        "NEXT_PUBLIC_MLC3_PILOT_UI_ENABLED"
    ] = True
    enabled = _attest({key: value for key, value in enabled.items()
                       if key not in {"evidence_sha256", "signature_ed25519_base64"}})
    assert not _validate_deployment(enabled)


def test_locally_fabricated_attestation_and_omitted_monitor_fail_closed():
    manifest = _deployment_manifest()
    unsigned = {key: value for key, value in manifest.items()
                if key != "signature_ed25519_base64"}
    assert not _validate_deployment(unsigned)
    foreign_key = Ed25519PrivateKey.generate()
    forged = _attest({
        key: value for key, value in manifest.items()
        if key not in {"evidence_sha256", "signature_ed25519_base64"}
    }, private_key=foreign_key)
    assert not _validate_deployment(forged)

    omitted = json.loads(json.dumps(manifest))
    export = omitted["railway"]["authenticated_provider_export"]
    export["services"] = [row for row in export["services"]
                          if row["role"] != "monitor"]
    export["observed_service_count"] = len(export["services"])
    export["service_inventory_sha256"] = _hash_value(export["services"])
    omitted["railway"]["provider_export_sha256"] = _hash_value(export)
    omitted = _attest({
        key: value for key, value in omitted.items()
        if key not in {"evidence_sha256", "signature_ed25519_base64"}
    })
    assert not _validate_deployment(omitted)


def test_monitor_deployment_binds_principal_command_and_schedule():
    for field, value in (
        ("founder_principal_id", "22222222-2222-4222-8222-222222222222"),
        ("start_command", "python wrong_monitor.py"),
        ("schedule", "0 * * * *"),
    ):
        manifest = _deployment_manifest()
        export = manifest["railway"]["authenticated_provider_export"]
        monitor = next(row for row in export["services"]
                       if row["role"] == "monitor")
        monitor["monitor_config"][field] = value
        monitor["config_sha256"] = _hash_value({
            key: item for key, item in monitor.items()
            if key != "config_sha256"
        })
        export["service_inventory_sha256"] = _hash_value(sorted(
            export["services"], key=lambda row: row["service_id"],
        ))
        manifest["railway"]["provider_export_sha256"] = _hash_value(export)
        manifest = _attest({
            key: item for key, item in manifest.items()
            if key not in {"evidence_sha256", "signature_ed25519_base64"}
        })
        assert not _validate_deployment(manifest)


def test_monitor_and_emergency_disable_evidence_are_required():
    for field in ("monitoring", "emergency_disable_rehearsal"):
        manifest = _deployment_manifest()
        manifest.pop(field)
        manifest = _attest({
            key: value for key, value in manifest.items()
            if key not in {"evidence_sha256", "signature_ed25519_base64"}
        })
        assert not _validate_deployment(manifest)


def test_emergency_disable_requires_two_exact_idempotent_receipts():
    mutations = []

    def one_attempt(value):
        value["emergency_disable_rehearsal"]["attempts"] = (
            value["emergency_disable_rehearsal"]["attempts"][:1]
        )

    mutations.append(one_attempt)

    def differing_targets(value):
        value["emergency_disable_rehearsal"]["attempts"][1][
            "before_states"
        ].pop("MLC3_PILOT_ENABLED")

    mutations.append(differing_targets)

    def partial_failure(value):
        value["emergency_disable_rehearsal"]["attempts"][0][
            "completed"
        ] = False

    mutations.append(partial_failure)

    def non_idempotent_second_result(value):
        value["emergency_disable_rehearsal"]["attempts"][1][
            "before_states"
        ]["MLC3_PILOT_ENABLED"] = True

    mutations.append(non_idempotent_second_result)

    def duplicate_operation_id(value):
        attempts = value["emergency_disable_rehearsal"]["attempts"]
        attempts[1]["operation_id"] = attempts[0]["operation_id"]

    mutations.append(duplicate_operation_id)

    def reversed_timestamps(value):
        attempts = value["emergency_disable_rehearsal"]["attempts"]
        attempts[0]["completed_at"] = (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ).isoformat()

    mutations.append(reversed_timestamps)

    def overlapping_attempts(value):
        attempts = value["emergency_disable_rehearsal"]["attempts"]
        attempts[1]["started_at"] = (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ).isoformat()

    mutations.append(overlapping_attempts)

    for mutate in mutations:
        manifest = _deployment_manifest()
        mutate(manifest)
        # Recompute every attacker-controlled hash and sign again: semantic
        # validation, not merely the outer signature, must reject the record.
        for attempt in manifest["emergency_disable_rehearsal"]["attempts"]:
            attempt["result_sha256"] = _hash_value({
                key: value for key, value in attempt.items()
                if key != "result_sha256"
            })
        manifest = _attest({
            key: value for key, value in manifest.items()
            if key not in {"evidence_sha256", "signature_ed25519_base64"}
        })
        assert not _validate_deployment(manifest)


def test_operator_signer_binds_manifest_to_pinned_public_key():
    unsigned = _deployment_manifest()
    unsigned = {key: value for key, value in unsigned.items()
                if key not in {"evidence_sha256", "signature_ed25519_base64"}}
    private_pem = _TEST_PRIVATE_KEY.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption(),
    )
    signed = sign_manifest(unsigned, private_pem)
    assert _validate_deployment(signed)


def test_operator_signer_binds_r2_rehearsal_to_pinned_public_key():
    unsigned = _r2_manifest()
    unsigned = {
        key: value for key, value in unsigned.items()
        if key not in {"issuer", "key_id", "evidence_sha256",
                       "signature_ed25519_base64"}
    }
    private_pem = _TEST_PRIVATE_KEY.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption(),
    )
    signed = sign_manifest(unsigned, private_pem)
    assert validate_r2_smoke_manifest(
        signed, account_id="account",
        practice_bucket="private-practice-audio",
        coach_video_bucket="private-coach-video",
        trusted_public_key_pem=_TEST_PUBLIC_KEY,
        trusted_issuer=TRUSTED_ATTESTATION_ISSUER,
        trusted_key_id=TRUSTED_ATTESTATION_KEY_ID,
    )


def test_invalid_production_attestations_block_readiness():
    report = _assess(
        deployment_attestation_valid=False,
        deployed_backend_gates_disabled=False,
        deployed_frontend_gates_disabled=False,
        deployed_learning_gates_disabled=False,
    )
    assert {
        "production_deployment_attestation_invalid",
        "deployed_backend_gates_not_disabled",
        "deployed_frontend_gates_not_disabled",
        "deployed_learning_gates_not_disabled",
    } <= set(report.blocker_codes)


def test_exact_rpc_registry_covers_every_first_client_repository_call():
    called = set(re.findall(
        r'self\.client\.rpc\(\s*"([a-z0-9_]+)"', REPOSITORY,
    ))
    registered = {signature.split("(", 1)[0]
                  for signature in _REQUIRED_RPC_SIGNATURES}
    assert called == registered
    assert len(_REQUIRED_RPC_SIGNATURES) == len(registered)


def test_security_and_zero_state_registries_cover_every_canary_family():
    rls = set(_RLS_TABLES)
    dependencies = set(_DEPENDENCY_TABLES)
    zero = {table for table, _ in _SERVICE_ZERO_PREDICATES}
    for family in (
        "feedback_v3_service", "exercise_service_offer",
        "exercise_practice", "exercise_pair",
        "exercise_service_confidence", "exercise_service_blind",
        "coach_guidance", "coach_inline",
    ):
        assert any(table.startswith(family) for table in zero)
    assert rls <= dependencies
    assert zero <= dependencies
    assert len(zero) == len(_SERVICE_ZERO_PREDICATES)


def test_lower_level_writers_are_forbidden_and_revoked_before_activation():
    for name in (
        "submit_mlc2_confidence_blind_judgment_v1",
        "record_exercise_service_acquisition_receipt_v1",
    ):
        assert any(signature.startswith(f"{name}(")
                   for signature in _FORBIDDEN_RPC_SIGNATURES)
        assert f"REVOKE ALL ON FUNCTION public.{name}(" in SECURITY_MIGRATION
    assert "FROM PUBLIC, anon, authenticated, service_role" in SECURITY_MIGRATION


def test_security_closure_is_terminal_release_migration_0325():
    manifest = (ROOT / "migrations/manifest.txt").read_text().splitlines()
    assert manifest[-1] == (
        "0325\tadd_mlc3_founder_canary_security_closure.sql"
    )
    assert "release migration 0325" in SECURITY_MIGRATION
    assert SECURITY_MIGRATION.rindex("NOTIFY pgrst, 'reload schema';") < (
        SECURITY_MIGRATION.rindex("COMMIT;")
    )


def test_r2_rehearsal_has_fixed_synthetic_prefix_and_cleanup_confirmation():
    assert 'f"mlc3-founder-readiness/{run_id}/{role}.bin"' in R2_SCRIPT
    assert "secrets.token_bytes(64)" in R2_SCRIPT
    assert "client.delete_object" in R2_SCRIPT
    assert "_confirm_absent" in R2_SCRIPT
    assert "write-read-delete-synthetic-r2-objects" in R2_SCRIPT
    assert "--cloudflare-control-plane-export" in R2_SCRIPT
    assert "validate_cloudflare_r2_privacy_export" in R2_SCRIPT
    assert "R2_CONTROL_PLANE_SIGNATURE_OR_PRIVACY_INVALID" in R2_SCRIPT
    assert (
        R2_SCRIPT.index("control_plane = _load_private_bucket_export(")
        < R2_SCRIPT.index("client = _client()")
    )
