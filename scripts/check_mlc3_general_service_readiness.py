#!/usr/bin/env python3
"""SELECT-only activation-readiness report for the disabled D4 rollout."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from check_mlc3_founder_canary_readiness import (  # noqa: E402
    _FORBIDDEN_RPC_SIGNATURES as _FOUNDER_FORBIDDEN_RPCS,
    _REQUIRED_RPC_SIGNATURES as _FOUNDER_REQUIRED_RPCS,
    _RLS_TABLES as _FOUNDER_RLS_TABLES,
)
from config import Config  # noqa: E402
from migrate import CannotRun, connect  # noqa: E402
from services.mlc3_founder_canary_readiness import (  # noqa: E402
    validate_r2_smoke_manifest,
)
from services.mlc3_general_service_readiness import (  # noqa: E402
    READINESS_CONTRACT_VERSION,
    TRUSTED_ATTESTATION_ISSUER,
    TRUSTED_ATTESTATION_KEY_ID,
    assess_general_service_readiness,
    validate_general_deployment_attestation,
)


_TRUSTED_PUBLIC_KEY = ROOT / "config/mlc3_founder_attestation_public_key.pem"
_MONITOR_SOURCE = ROOT / "services/mlc3_general_service_monitor.py"
_D4_TABLES = (
    "mlc3_service_cohort_sets", "mlc3_service_cohort_members",
    "mlc3_service_activation_risk_decisions",
    "mlc3_service_rollout_revisions",
    "mlc3_service_enrollment_revisions", "mlc3_service_access_events",
    "mlc3_speaker_acquisition_revisions", "mlc3_self_speaker_assertions",
    "mlc3_target_speaker_bindings",
    "mlc3_comparison_speaker_eligibility_revisions",
    "mlc3_service_backpressure_events",
)
_REQUIRED_RPCS = tuple(
    signature for signature in _FOUNDER_REQUIRED_RPCS
    if not signature.startswith("reserve_exercise_practice_service_upload_v1(")
) + (
    "ensure_mlc3_service_enrollment_v2(uuid,uuid,text)",
    "require_mlc3_service_access_v2(uuid,uuid,uuid)",
    "record_mlc3_feedback_self_speaker_target_v1(uuid,uuid,uuid,uuid,text)",
    "confirm_mlc3_practice_speaker_and_pair_v1(uuid,uuid,uuid,text)",
    "reserve_exercise_practice_service_upload_v2(uuid,uuid,uuid,text,bigint,text,text,text,integer)",
    "get_mlc3_general_service_monitor_v1()",
    "halt_mlc3_service_rollout_v1(text,text)",
)
_FORBIDDEN_RPCS = _FOUNDER_FORBIDDEN_RPCS + (
    "record_mlc3_self_speaker_target_v1(uuid,uuid,uuid,uuid,uuid,text)",
    "record_mlc3_practice_self_speaker_target_v1(uuid,uuid,uuid,text)",
    "require_mlc3_current_pair_speaker_identity_v1(uuid,uuid)",
    "assign_synthetic_exercise_pair_v1(uuid,uuid,text,text)",
    "submit_synthetic_exercise_pair_judgment_v1(uuid,uuid,text,text)",
    "reserve_exercise_practice_service_upload_v1(uuid,uuid,integer,uuid,text,bigint,text,text,text,integer)",
)
_RLS_TABLES = tuple(dict.fromkeys(_FOUNDER_RLS_TABLES + _D4_TABLES))


def _load(path: str) -> dict:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError("evidence must be a JSON object")
    return value


def _surface_health(connection) -> dict:
    with connection.cursor() as cursor:
        cursor.execute("SELECT public.get_mlc3_general_service_monitor_v1()")
        monitor_row = cursor.fetchone()
        monitor = dict(monitor_row[0]) if monitor_row else {}
        cursor.execute(
            """
            WITH required(signature) AS (SELECT unnest(%s::text[])),
            forbidden(signature) AS (SELECT unnest(%s::text[])),
            tables(name) AS (SELECT unnest(%s::text[]))
            SELECT jsonb_build_object(
              'missing_required_rpc_count', (
                SELECT count(*) FROM required
                WHERE to_regprocedure('public.' || signature) IS NULL),
              'missing_service_rpc_grant_count', (
                SELECT count(*) FROM required
                WHERE to_regprocedure('public.' || signature) IS NULL
                   OR NOT has_function_privilege(
                       'service_role','public.' || signature,'EXECUTE')),
              'forbidden_rpc_runtime_grant_count', (
                SELECT count(*) FROM forbidden
                WHERE to_regprocedure('public.' || signature) IS NOT NULL
                  AND (has_function_privilege(
                         'service_role','public.' || signature,'EXECUTE')
                    OR has_function_privilege(
                         'authenticated','public.' || signature,'EXECUTE')
                    OR has_function_privilege(
                         'anon','public.' || signature,'EXECUTE'))),
              'missing_required_table_count', (
                SELECT count(*) FROM tables
                WHERE to_regclass('public.' || name) IS NULL),
              'rls_disabled_table_count', (
                SELECT count(*) FROM tables
                LEFT JOIN pg_class c ON c.oid=to_regclass('public.' || name)
                WHERE c.oid IS NULL OR NOT c.relrowsecurity),
              'runtime_table_write_grant_count', (
                SELECT count(*) FROM tables
                WHERE to_regclass('public.' || name) IS NOT NULL
                  AND (has_table_privilege(
                         'service_role','public.' || name,'INSERT,UPDATE,DELETE')
                    OR has_table_privilege(
                         'authenticated','public.' || name,'INSERT,UPDATE,DELETE')
                    OR has_table_privilege(
                         'anon','public.' || name,'INSERT,UPDATE,DELETE'))),
              'service_contract_state', (
                SELECT state FROM public.mlc3_service_contracts
                WHERE contract_version='mlc3-first-client-service-v1'),
              'approved_need_contract_count', (
                SELECT count(*) FROM public.exercise_need_contracts
                WHERE need_code='rushed_phrase_endings'
                  AND approval_state='approved')
            )
            """,
            (list(_REQUIRED_RPCS), list(_FORBIDDEN_RPCS), list(_RLS_TABLES)),
        )
        surface = dict(cursor.fetchone()[0])
        cursor.execute("SELECT to_regclass('public.coach_users')")
        if cursor.fetchone()[0] is None:
            surface["active_coach_count"] = -1
        else:
            cursor.execute(
                "SELECT count(*) FROM public.coach_users WHERE is_active"
            )
            surface["active_coach_count"] = cursor.fetchone()[0]
        cursor.execute("SELECT to_regclass('public.schema_migrations')")
        if cursor.fetchone()[0] is None:
            surface["security_closure_0325_applied"] = False
        else:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM public.schema_migrations "
                "WHERE version='0325' AND filename="
                "'add_mlc3_founder_canary_security_closure.sql' "
                "AND NOT baselined)"
            )
            surface["security_closure_0325_applied"] = cursor.fetchone()[0]
    return {**monitor, **surface,
            "readiness_contract_version": READINESS_CONTRACT_VERSION}


def _enabled(name: str) -> bool:
    return (os.getenv(name) or "0").strip().lower() in {"1", "true", "yes", "on"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deployment-attestation", required=True)
    parser.add_argument("--r2-manifest", required=True)
    parser.add_argument("--backend-commit", required=True)
    parser.add_argument("--frontend-commit", required=True)
    args = parser.parse_args(argv)
    key = _TRUSTED_PUBLIC_KEY.read_bytes()
    deployment = _load(args.deployment_attestation)
    r2 = _load(args.r2_manifest)
    monitor_sha = __import__("hashlib").sha256(
        _MONITOR_SOURCE.read_bytes()
    ).hexdigest()
    deployment_valid = validate_general_deployment_attestation(
        deployment, backend_commit=args.backend_commit,
        frontend_commit=args.frontend_commit,
        monitor_code_sha256=monitor_sha, trusted_public_key_pem=key,
    )
    r2_valid = validate_r2_smoke_manifest(
        r2, account_id=str(Config.R2_ACCOUNT_ID or ""),
        practice_bucket=str(Config.R2_USER_MEDIA_BUCKET or ""),
        coach_video_bucket=str(Config.R2_BUCKET_NAME or ""),
        trusted_public_key_pem=key,
        trusted_issuer=TRUSTED_ATTESTATION_ISSUER,
        trusted_key_id=TRUSTED_ATTESTATION_KEY_ID,
    )
    try:
        connection = connect()
    except CannotRun as error:
        print(json.dumps({"ready_for_activation_review": False,
                          "blocker_codes": [str(error)]}))
        return 2
    try:
        health = _surface_health(connection)
    finally:
        connection.close()
    report = assess_general_service_readiness(
        health, deployment_attestation_valid=deployment_valid,
        r2_evidence_valid=r2_valid,
        local_product_gates={
            "backend_user": bool(Config.MLC3_SERVICE_ENABLED),
            "backend_coach": bool(Config.MLC3_COACH_INLINE_AUTHORING_ENABLED),
            "frontend_user": _enabled("NEXT_PUBLIC_MLC3_SERVICE_UI_ENABLED"),
            "frontend_coach": _enabled(
                "NEXT_PUBLIC_MLC3_COACH_INLINE_AUTHORING_ENABLED"
            ),
        },
        local_learning_gates={
            "dataset": _enabled("MLC2_DATASET_RELEASES_ENABLED"),
            "training": _enabled("MLC2_TRAINING_ENABLED"),
            "evaluation": _enabled("MLC2_EVALUATION_ENABLED"),
            "promotion": _enabled("MLC2_PROMOTION_ENABLED"),
        },
    ).as_dict()
    print(json.dumps(report, sort_keys=True, default=str))
    return 0 if report["ready_for_activation_review"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
