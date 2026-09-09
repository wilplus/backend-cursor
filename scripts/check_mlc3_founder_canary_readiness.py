#!/usr/bin/env python3
"""Read-only readiness check for the MLC-3 founder canary.

The command performs aggregate SELECTs only.  It does not allowlist a
principal, activate a contract, touch R2, or enable a frontend/backend gate.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from config import Config  # noqa: E402
from migrate import CannotRun, connect  # noqa: E402
from services.mlc3_founder_canary_readiness import (  # noqa: E402
    READINESS_CONTRACT_VERSION,
    TRUSTED_ATTESTATION_ISSUER,
    TRUSTED_ATTESTATION_KEY_ID,
    assess_founder_canary_readiness,
    validate_deployment_attestation,
    validate_r2_smoke_manifest,
)
from services.user_media_storage import user_media_use_r2  # noqa: E402
from services.coach_video_storage import coach_videos_use_r2  # noqa: E402


_TRUSTED_ATTESTATION_PUBLIC_KEY = (
    ROOT / "config" / "mlc3_founder_attestation_public_key.pem"
)
_MONITOR_SOURCE = ROOT / "services" / "mlc3_founder_canary_monitor.py"
_REVIEWED_BACKEND_RELEASE_COMMIT = (
    "324430b3b773185dc21793ba77540f769071f5e0"
)
_REVIEWED_FRONTEND_RELEASE_COMMIT = (
    "724ce3c0c58ccd019180fc1d663effa2b5eeabe9"
)


_REQUIRED_RPC_SIGNATURES = (
    "access_exercise_service_blind_reveal_v1(uuid,uuid,uuid,text,text)",
    "ack_coach_inline_blind_render_v1(uuid,uuid,uuid,uuid,uuid,uuid,uuid,timestamp with time zone,text,text,text)",
    "ack_exercise_practice_service_upload_v1(uuid,uuid,text,bigint,text)",
    "ack_exercise_service_confidence_render_v1(uuid,uuid,uuid,text,timestamp with time zone,text,text)",
    "ack_feedback_v3_service_render_v1(uuid,uuid,uuid,uuid,uuid,uuid,text,timestamp with time zone,text,text)",
    "assign_exercise_service_owner_pair_v1(uuid,uuid,text)",
    "attach_exercise_practice_service_attempt_v1(uuid,uuid,uuid,uuid,uuid,text,integer,timestamp with time zone,timestamp with time zone,jsonb,text)",
    "authorize_exercise_practice_transcription_v1(uuid,uuid,uuid,uuid,uuid,text,text,text,text,text,text,text)",
    "complete_exercise_service_blind_review_v1(uuid,uuid,text)",
    "complete_synthetic_coach_guidance_batch_v1(uuid,uuid,text)",
    "create_coach_guidance_service_attachment_v1(uuid,uuid,uuid,uuid,text,text,text,uuid,uuid,uuid,uuid,text,text,text,text,text)",
    "create_coach_inline_exercise_attachment_v1(uuid,uuid,uuid,uuid,uuid,text,uuid,uuid,uuid,text,text,text,text,text)",
    "create_coach_inline_exercise_draft_v1(uuid,uuid,text,text,text,text[],text)",
    "create_coach_inline_general_guidance_v1(uuid,uuid,uuid,uuid,uuid,uuid,text,text,uuid,text,text,text,text,text)",
    "create_exercise_practice_service_session_v1(uuid,uuid,uuid,text)",
    "finalize_coach_guidance_service_media_v1(uuid,uuid,text,boolean,text,text,text,text,text,text)",
    "finalize_exercise_practice_service_media_v1(uuid,uuid,uuid,uuid,text,text)",
    "finalize_exercise_practice_transcription_v1(uuid,uuid,text,jsonb,text,text)",
    "freeze_exercise_practice_service_selection_v1(uuid,uuid,integer,integer,text)",
    "freeze_exercise_service_blind_review_set_v1(uuid,uuid,text)",
    "freeze_exercise_service_offer_v2(uuid,uuid,uuid,uuid,text)",
    "freeze_exercise_service_pair_v1(uuid,uuid,uuid,integer,text)",
    "freeze_feedback_v3_service_membership_v1(uuid,uuid,uuid,uuid,uuid,text,jsonb,text)",
    "freeze_synthetic_coach_guidance_batch_v1(uuid,uuid,uuid,text)",
    "issue_coach_inline_general_authority_v1(uuid,uuid,uuid,uuid,uuid,text)",
    "mark_exercise_practice_transcription_dispatched_v1(uuid,uuid,text)",
    "prepare_coach_inline_blind_batch_v1(uuid,uuid,uuid,text)",
    "prepare_coach_inline_guidance_context_v1(uuid,uuid,uuid,text)",
    "prepare_feedback_v3_service_context_v1(uuid,uuid,uuid,text)",
    "publish_coach_guidance_service_exercise_v1(uuid,uuid,text,text,text,text)",
    "reconcile_exercise_practice_transcription_request_v1(uuid,uuid,text,text)",
    "reconcile_exercise_practice_transcription_v1(uuid,uuid,text)",
    "record_coach_guidance_service_event_v1(uuid,uuid,text,uuid,jsonb,text)",
    "record_coach_guidance_service_upload_event_v1(uuid,uuid,text,text,bigint,text)",
    "record_exercise_offer_service_event_v1(uuid,uuid,uuid,text,uuid,text,jsonb,timestamp with time zone,text)",
    "record_exercise_practice_service_event_v1(uuid,uuid,uuid,uuid,text,uuid,text,jsonb,timestamp with time zone,text)",
    "record_exercise_practice_service_measurement_v1(uuid,integer,text,text,jsonb,jsonb,text)",
    "record_exercise_practice_service_validity_v1(uuid,uuid,integer,text,text[],text,text)",
    "record_feedback_v3_service_candidate_set_v1(uuid,uuid,uuid,jsonb)",
    "record_feedback_v3_service_response_v1(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid,text,text)",
    "record_synthetic_coach_guidance_upload_event_v1(uuid,uuid,text,uuid,text)",
    "register_exercise_media_object_v1(text,text,text,bigint,text,text,timestamp with time zone,text,text)",
    "register_synthetic_coach_guidance_media_v1(uuid,uuid,uuid,text,text,uuid,uuid,uuid,text,text,text,text,text)",
    "reserve_coach_guidance_service_upload_v1(uuid,uuid,text,text,text,text,bigint,text,timestamp with time zone,text)",
    "reserve_exercise_practice_service_upload_v1(uuid,uuid,uuid,text,bigint,text,text,text,integer)",
    "reserve_synthetic_coach_guidance_upload_v1(uuid,uuid,uuid,text,text,text,text,bigint,text,timestamp with time zone,text)",
    "resolve_coach_guidance_service_media_read_v1(uuid,uuid)",
    "resolve_coach_inline_blind_audio_read_v1(uuid,uuid,uuid)",
    "resolve_coach_inline_media_read_v1(uuid,uuid)",
    "resolve_exercise_confidence_media_read_v1(uuid,uuid)",
    "resolve_exercise_practice_media_read_v1(uuid,uuid)",
    "resolve_exercise_practice_session_read_v1(uuid,uuid)",
    "resolve_exercise_service_offer_read_v1(uuid,uuid)",
    "submit_coach_inline_blind_judgment_v1(uuid,uuid,uuid,uuid,uuid,text,timestamp with time zone,text)",
    "submit_exercise_service_confidence_judgment_v1(uuid,uuid,uuid,text,timestamp with time zone,text)",
    "submit_exercise_service_owner_pair_judgment_v1(uuid,uuid,text,text)",
)

_RLS_TABLES = (
    "mlc3_service_contracts", "mlc3_service_principal_allowlist",
    "feedback_v3_memberships", "feedback_v3_membership_items",
    "feedback_v3_owner_responses",
    "feedback_v3_service_response_bindings",
    "feedback_v3_service_render_receipts", "exercise_service_offers",
    "exercise_service_offer_candidates", "exercise_service_offer_events",
    "exercise_service_acquisition_receipts", "exercise_practice_sessions",
    "exercise_practice_attempts", "exercise_practice_events",
    "exercise_practice_upload_recoveries",
    "exercise_practice_transcription_runs",
    "exercise_practice_measurement_revisions",
    "exercise_practice_validity_assessments",
    "exercise_practice_selection_revisions", "exercise_pair_revisions",
    "exercise_pair_assignments", "exercise_pair_judgments",
    "exercise_service_confidence_assignments",
    "exercise_service_confidence_render_receipts",
    "exercise_service_confidence_judgments",
    "exercise_service_blind_review_sets",
    "exercise_service_blind_reveal_grants",
    "exercise_service_blind_reveal_accesses", "exercise_blind_packets",
    "coach_guidance_review_frames",
    "coach_guidance_review_frame_items", "coach_guidance_review_batches",
    "coach_guidance_reveal_grants", "coach_guidance_reveal_grant_judgments",
    "coach_guidance_reveal_accesses", "coach_guidance_upload_permits",
    "coach_guidance_upload_recoveries", "coach_guidance_upload_events",
    "coach_guidance_media_validity_events",
    "coach_guidance_independent_media_reviews",
    "coach_guidance_media_bindings", "coach_guidance_attachments",
    "coach_guidance_attachment_versions", "coach_guidance_lifecycle_events",
    "coach_guidance_publications", "coach_guidance_publication_invalidations",
    "coach_inline_source_roles", "coach_inline_exercise_drafts",
    "coach_inline_context_assessments",
    "coach_inline_exercise_eligibility_reviews", "exercise_audio_lineages",
    "exercise_need_contracts", "exercise_definitions", "exercise_versions",
    "exercise_catalog_snapshots", "exercise_catalog_snapshot_items",
    "exercise_candidate_sets", "exercise_candidates",
    "exercise_n1_source_pattern_results", "exercise_n1_pattern_snapshots",
    "exercise_n1_pattern_candidates",
    "exercise_n1_version_compatibility_profiles",
    "exercise_authorization_checks",
)

_DEPENDENCY_TABLES = _RLS_TABLES + (
    "feedback_exposures", "ml_review_assignments", "ml_presentations",
    "ml_rendered_exposures", "ml_judgments",
    "processing_authorization_receipts",
    "processing_authorization_receipt_purposes",
    "processing_authorization_snapshots", "processing_recording_attempts",
    "processing_audio_objects", "processing_purpose_registry",
    "processing_policy_versions", "processing_policy_purposes",
)

_FORBIDDEN_RPC_SIGNATURES = (
    "prepare_feedback_v3_service_row_v1()",
    "prepare_exercise_service_row_v1()",
    "prepare_exercise_practice_service_row_v1()",
    "reject_feedback_exposure_mutation_v2()",
    "serialize_mlc3_service_purge_v1()",
    "serialize_mlc3_processing_audio_leaf_v1()",
    "serialize_mlc3_exercise_media_leaf_v1()",
    "require_mlc3_service_principal_v1(uuid)",
    "require_feedback_v3_service_membership_live_v1(uuid,uuid)",
    "require_exercise_practice_service_live_v1(uuid,uuid)",
    "require_coach_guidance_service_access_v1(uuid,uuid,text)",
    "require_coach_guidance_service_media_live_v1(uuid,uuid)",
    "record_feedback_human_decision_v1(uuid,uuid,uuid,text,text,text,text,text)",
    "submit_mlc2_confidence_blind_judgment_v1(uuid,uuid,uuid,text,timestamp with time zone,text)",
    "record_exercise_service_acquisition_receipt_v1(uuid,text,uuid,uuid,uuid,uuid,text)",
)

_SERVICE_ZERO_PREDICATES = (
    ("feedback_v3_memberships", "operation_mode='allowlisted_service'"),
    ("feedback_v3_membership_items", "operation_mode='allowlisted_service'"),
    ("feedback_v3_owner_responses", "operation_mode='allowlisted_service'"),
    ("feedback_v3_service_response_bindings", "TRUE"),
    ("feedback_v3_service_render_receipts", "TRUE"),
    ("exercise_service_offers", "operation_mode='allowlisted_service'"),
    ("exercise_service_offer_candidates", "operation_mode='allowlisted_service'"),
    ("exercise_service_offer_events", "operation_mode='allowlisted_service'"),
    ("exercise_service_acquisition_receipts", "TRUE"),
    ("exercise_practice_sessions", "operation_mode='allowlisted_service'"),
    ("exercise_practice_attempts", "operation_mode='allowlisted_service'"),
    ("exercise_practice_events", "operation_mode='allowlisted_service'"),
    ("exercise_practice_upload_recoveries", "operation_mode='allowlisted_service'"),
    ("exercise_practice_transcription_runs", "TRUE"),
    ("exercise_practice_measurement_revisions", "operation_mode='allowlisted_service'"),
    ("exercise_practice_validity_assessments", "operation_mode='allowlisted_service'"),
    ("exercise_practice_selection_revisions", "operation_mode='allowlisted_service'"),
    ("exercise_pair_revisions", "operation_mode='allowlisted_service'"),
    ("exercise_pair_assignments", "operation_mode='allowlisted_service'"),
    ("exercise_pair_judgments", "operation_mode='allowlisted_service'"),
    ("exercise_service_confidence_assignments", "TRUE"),
    ("exercise_service_confidence_render_receipts", "TRUE"),
    ("exercise_service_confidence_judgments", "TRUE"),
    ("exercise_service_blind_review_sets", "TRUE"),
    ("exercise_service_blind_reveal_grants", "TRUE"),
    ("exercise_service_blind_reveal_accesses", "TRUE"),
    ("coach_guidance_review_frames", "TRUE"),
    ("coach_guidance_review_frame_items", "TRUE"),
    ("coach_guidance_review_batches", "TRUE"),
    ("coach_guidance_reveal_grants", "TRUE"),
    ("coach_guidance_reveal_grant_judgments", "TRUE"),
    ("coach_guidance_reveal_accesses", "TRUE"),
    ("coach_guidance_upload_permits", "operation_mode='allowlisted_service'"),
    ("coach_guidance_upload_recoveries", "operation_mode='allowlisted_service'"),
    ("coach_guidance_upload_events", "operation_mode='allowlisted_service'"),
    ("coach_guidance_media_validity_events", "operation_mode='allowlisted_service'"),
    ("coach_guidance_independent_media_reviews", "operation_mode='allowlisted_service'"),
    ("coach_guidance_media_bindings", "operation_mode='allowlisted_service'"),
    ("coach_guidance_attachments", "operation_mode='allowlisted_service'"),
    ("coach_guidance_attachment_versions", "operation_mode='allowlisted_service'"),
    ("coach_guidance_lifecycle_events", "operation_mode='allowlisted_service'"),
    ("coach_guidance_publications", "operation_mode='allowlisted_service'"),
    ("coach_guidance_publication_invalidations", "operation_mode='allowlisted_service'"),
    ("coach_inline_source_roles", "TRUE"),
    ("coach_inline_exercise_drafts", "TRUE"),
    ("coach_inline_context_assessments", "TRUE"),
    ("coach_inline_exercise_eligibility_reviews", "TRUE"),
)

_DATASET_TABLES = tuple(
    table for table, _ in _SERVICE_ZERO_PREDICATES
    if table not in {
        "exercise_practice_upload_recoveries",
        "coach_guidance_review_frame_items",
        "coach_guidance_reveal_grant_judgments",
        "coach_guidance_upload_recoveries",
    }
)


def _service_family(table: str) -> str:
    if table.startswith("feedback_"):
        return "feedback"
    if table.startswith("exercise_service_offer"):
        return "offer"
    if (table.startswith("exercise_practice")
            or table == "exercise_service_acquisition_receipts"):
        return "practice"
    if table.startswith("exercise_pair"):
        return "comparison"
    if (table.startswith("exercise_service_confidence")
            or table.startswith("exercise_service_blind")):
        return "blind_review"
    if table.startswith("coach_guidance"):
        return "coach_guidance"
    if table.startswith("coach_inline"):
        return "inline_authoring"
    raise ValueError(f"unregistered service table family: {table}")


_SERVICE_ZERO_FAMILIES = {
    family: tuple(row for row in _SERVICE_ZERO_PREDICATES
                  if _service_family(row[0]) == family)
    for family in {
        _service_family(table) for table, _ in _SERVICE_ZERO_PREDICATES
    }
}

def _count_union(rows: tuple[tuple[str, str], ...]) -> str:
    return " UNION ALL ".join(
        f"SELECT count(*) count_value FROM public.{table} WHERE {predicate}"
        for table, predicate in rows
    )


def _dataset_union() -> str:
    return " UNION ALL ".join(
        f"SELECT count(*) count_value FROM public.{table} "
        "WHERE dataset_eligible"
        for table in _DATASET_TABLES
    )


def _load_manifest(path: str) -> dict:
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, dict):
        raise ValueError("manifest must be an object")
    return payload


def _aggregate_health(connection, principal_id: str, coach_email: str) -> dict:
    service_rows_sql = _count_union(_SERVICE_ZERO_PREDICATES)
    dataset_rows_sql = _dataset_union()
    family_fields_sql = ",".join(
        f"'service_{family}_record_count',"
        f"(SELECT COALESCE(sum(count_value),0) FROM "
        f"({_count_union(rows)}) family_rows)"
        for family, rows in sorted(_SERVICE_ZERO_FAMILIES.items())
    )
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            SELECT jsonb_build_object(
              'readiness_contract_version', %s,
              'service_contract_version', 'mlc3-first-client-service-v1',
              'service_contract_count', (
                SELECT count(*) FROM public.mlc3_service_contracts
                WHERE contract_version='mlc3-first-client-service-v1'),
              'service_contract_state', (
                SELECT state FROM public.mlc3_service_contracts
                WHERE contract_version='mlc3-first-client-service-v1'),
              'allowlisted_principal_count', (
                SELECT count(*) FROM public.mlc3_service_principal_allowlist
                WHERE state='active' AND revoked_at IS NULL),
              'founder_principal_count', (
                SELECT count(*) FROM public.owner_principals WHERE id=%s::uuid),
              'founder_account_binding_count', (
                SELECT count(*) FROM public.owner_principals
                WHERE id=%s::uuid AND user_id IS NOT NULL),
              'founder_project_count', (
                SELECT count(*) FROM public.projects
                WHERE owner_principal_id=%s::uuid),
              'active_processing_policy_count', (
                SELECT count(*) FROM public.processing_policy_versions
                WHERE status='active' AND activated_at<=clock_timestamp()
                  AND (retired_at IS NULL OR retired_at>clock_timestamp())),
              'required_operational_purpose_count', (
                SELECT count(*) FROM public.processing_purpose_registry purpose
                WHERE purpose.id IN (
                    'personalized_exercise_recommendation', 'coach_review')
                  AND purpose.operational AND purpose.authorizes_processing),
              'founder_current_full_service_receipt_count', (
                SELECT count(DISTINCT receipt.id)
                FROM public.processing_authorization_receipts receipt
                JOIN public.processing_policy_versions policy
                  ON policy.id=receipt.policy_id
                WHERE receipt.acquisition_principal_id=%s::uuid
                  AND policy.status='active'
                  AND policy.activated_at<=clock_timestamp()
                  AND (policy.retired_at IS NULL
                       OR policy.retired_at>clock_timestamp())
                  AND NOT EXISTS (
                    SELECT 1 FROM unnest(ARRAY[
                      'personalized_exercise_recommendation', 'coach_review'
                    ]::text[]) required(purpose_id)
                    WHERE NOT EXISTS (
                      SELECT 1
                      FROM public.processing_authorization_receipt_purposes rp
                      JOIN public.processing_purpose_registry registry
                        ON registry.id=rp.purpose_id
                      WHERE rp.receipt_id=receipt.id
                        AND rp.purpose_id=required.purpose_id
                        AND registry.operational
                        AND registry.authorizes_processing)
                    OR NOT EXISTS (
                      SELECT 1 FROM public.processing_policy_purposes pp
                      WHERE pp.policy_id=policy.id
                        AND pp.purpose_id=required.purpose_id))),
              'founder_active_service_block_count', (
                SELECT count(*) FROM public.processing_service_blocks
                WHERE acquisition_principal_id=%s::uuid
                  AND effective_at<=clock_timestamp()),
              'founder_open_purge_count', (
                SELECT count(*) FROM public.data_purge_requests
                WHERE acquisition_principal_id=%s::uuid AND state<>'done'),
              'active_coach_allowlist_count', (
                SELECT count(*) FROM public.coach_users
                WHERE lower(email)=lower(%s) AND is_active),
              'coach_principal_count', (
                SELECT count(*) FROM public.owner_principals principal
                JOIN auth.users account ON account.id=principal.user_id
                WHERE lower(account.email)=lower(%s)),
              'approved_need_contract_count', (
                SELECT count(*) FROM public.exercise_need_contracts
                WHERE need_code='rushed_phrase_endings'
                  AND approval_state='approved'),
              'catalog_snapshot_count', (
                SELECT count(*) FROM public.exercise_catalog_snapshots),
              'approved_active_exercise_version_count', (
                SELECT count(*) FROM public.exercise_versions version
                JOIN public.exercise_need_contracts need
                  ON need.id=version.need_contract_id
                WHERE need.need_code='rushed_phrase_endings'
                  AND need.approval_state='approved'
                  AND version.safety_state='approved'
                  AND version.catalogue_state='active'),
              'missing_required_rpc_count', (
                SELECT count(*) FROM unnest(%s::text[]) required(signature)
                WHERE to_regprocedure('public.' || required.signature) IS NULL),
              'missing_service_rpc_grant_count', (
                SELECT count(*) FROM unnest(%s::text[]) required(signature)
                WHERE to_regprocedure('public.' || required.signature) IS NULL
                   OR NOT has_function_privilege(
                     'service_role',
                     to_regprocedure('public.' || required.signature),
                     'EXECUTE')),
              'runtime_rpc_client_grant_count', (
                SELECT count(*) FROM unnest(%s::text[]) required(signature)
                WHERE has_function_privilege(
                        'anon', to_regprocedure('public.' || required.signature),
                        'EXECUTE')
                   OR has_function_privilege(
                        'authenticated',
                        to_regprocedure('public.' || required.signature),
                        'EXECUTE')),
              'forbidden_rpc_runtime_grant_count', (
                SELECT count(*) FROM unnest(%s::text[]) forbidden(signature)
                WHERE to_regprocedure('public.' || forbidden.signature) IS NOT NULL
                  AND (has_function_privilege(
                         'service_role',
                         to_regprocedure('public.' || forbidden.signature),
                         'EXECUTE')
                    OR has_function_privilege(
                         'anon',
                         to_regprocedure('public.' || forbidden.signature),
                         'EXECUTE')
                    OR has_function_privilege(
                         'authenticated',
                         to_regprocedure('public.' || forbidden.signature),
                         'EXECUTE'))),
              'missing_required_table_count', (
                SELECT count(*) FROM unnest(%s::text[]) required(name)
                WHERE to_regclass('public.' || required.name) IS NULL),
              'rls_disabled_table_count', (
                SELECT count(*) FROM unnest(%s::text[]) required(name)
                WHERE NOT COALESCE((
                  SELECT relation.relrowsecurity
                  FROM pg_class relation
                  WHERE relation.oid=to_regclass('public.' || required.name)
                ), false)),
              'runtime_table_write_grant_count', (
                SELECT count(*) FROM unnest(%s::text[]) required(name)
                WHERE to_regclass('public.' || required.name) IS NOT NULL
                  AND (has_table_privilege(
                         'service_role',
                         to_regclass('public.' || required.name),
                         'INSERT,UPDATE,DELETE')
                    OR has_table_privilege(
                         'anon', to_regclass('public.' || required.name),
                         'INSERT,UPDATE,DELETE')
                    OR has_table_privilege(
                         'authenticated',
                         to_regclass('public.' || required.name),
                         'INSERT,UPDATE,DELETE'))),
              'runtime_owned_table_count', (
                SELECT count(*) FROM unnest(%s::text[]) required(name)
                JOIN pg_class relation
                  ON relation.oid=to_regclass('public.' || required.name)
                WHERE pg_get_userbyid(relation.relowner) IN (
                    'service_role','anon','authenticated')),
              'service_mode_record_count', (
                SELECT COALESCE(sum(count_value),0) FROM ({service_rows_sql}) rows),
              {family_fields_sql},
              'dataset_eligible_record_count', (
                SELECT COALESCE(sum(count_value),0) FROM ({dataset_rows_sql}) rows),
              'unresolved_founder_media_write_count', (
                SELECT sum(count_value) FROM (
                  SELECT count(*) count_value
                  FROM public.exercise_practice_upload_recoveries recovery
                  WHERE recovery.acquisition_principal_id=%s::uuid
                    AND recovery.operation_mode='allowlisted_service'
                    AND recovery.status NOT IN ('attached','deleted')
                  UNION ALL
                  SELECT count(*)
                  FROM public.coach_guidance_upload_permits permit
                  WHERE permit.acquisition_principal_id=%s::uuid
                    AND permit.operation_mode='allowlisted_service'
                    AND NOT EXISTS (
                      SELECT 1 FROM public.coach_guidance_upload_events event
                      WHERE event.upload_permit_id=permit.id
                        AND event.event_kind IN ('finalized','abandoned'))
                ) media_rows
              )
            )
            """,
            (
                READINESS_CONTRACT_VERSION,
                principal_id, principal_id, principal_id, principal_id,
                principal_id, principal_id, coach_email, coach_email,
                list(_REQUIRED_RPC_SIGNATURES),
                list(_REQUIRED_RPC_SIGNATURES),
                list(_REQUIRED_RPC_SIGNATURES),
                list(_FORBIDDEN_RPC_SIGNATURES),
                list(_DEPENDENCY_TABLES), list(_RLS_TABLES), list(_RLS_TABLES),
                list(_RLS_TABLES), principal_id, principal_id,
            ),
        )
        row = cursor.fetchone()
    payload = row[0] if row else None
    return dict(payload) if isinstance(payload, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--principal-id", required=True)
    parser.add_argument("--coach-email", required=True)
    parser.add_argument("--r2-smoke-manifest", required=True)
    parser.add_argument("--deployment-attestation", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    try:
        r2_manifest = _load_manifest(args.r2_smoke_manifest)
        deployment_manifest = _load_manifest(args.deployment_attestation)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({
            "ready_for_activation_review": False,
            "blocker_codes": ["readiness_evidence_manifest_unavailable"],
            "detail": type(error).__name__,
        }, sort_keys=True))
        return 2

    practice_bucket = (Config.R2_USER_MEDIA_BUCKET or "").strip()
    coach_bucket = (Config.R2_BUCKET_NAME or "").strip()
    account_id = (Config.R2_ACCOUNT_ID or "").strip()
    try:
        trusted_public_key = _TRUSTED_ATTESTATION_PUBLIC_KEY.read_bytes()
    except OSError:
        trusted_public_key = b""
    r2_manifest_valid = validate_r2_smoke_manifest(
        r2_manifest, account_id=account_id,
        practice_bucket=practice_bucket, coach_video_bucket=coach_bucket,
        trusted_public_key_pem=trusted_public_key,
        trusted_issuer=TRUSTED_ATTESTATION_ISSUER,
        trusted_key_id=TRUSTED_ATTESTATION_KEY_ID,
    )
    deployment_attestation_valid = validate_deployment_attestation(
        deployment_manifest,
        backend_commit=_REVIEWED_BACKEND_RELEASE_COMMIT,
        frontend_commit=_REVIEWED_FRONTEND_RELEASE_COMMIT,
        trusted_public_key_pem=trusted_public_key,
        trusted_issuer=TRUSTED_ATTESTATION_ISSUER,
        trusted_key_id=TRUSTED_ATTESTATION_KEY_ID,
        founder_principal_id=args.principal_id,
        monitor_code_sha256=(
            sha256(_MONITOR_SOURCE.read_bytes()).hexdigest()
            if _MONITOR_SOURCE.is_file() else ""
        ),
    )

    try:
        connection = connect()
    except CannotRun as error:
        print(json.dumps({
            "ready_for_activation_review": False,
            "blocker_codes": ["production_database_unavailable"],
            "detail": str(error),
        }, sort_keys=True))
        return 2

    try:
        try:
            health = _aggregate_health(
                connection, args.principal_id, args.coach_email,
            )
        except Exception as error:
            connection.rollback()
            print(json.dumps({
                "ready_for_activation_review": False,
                "blocker_codes": ["readiness_database_contract_unavailable"],
                "detail": type(error).__name__,
            }, sort_keys=True))
            return 2
    finally:
        connection.close()

    report = assess_founder_canary_readiness(
        health,
        founder_principal_id=args.principal_id,
        coach_email=args.coach_email,
        backend_serving_enabled=Config.MLC3_PILOT_ENABLED,
        backend_inline_authoring_enabled=(
            Config.MLC3_COACH_INLINE_AUTHORING_ENABLED
        ),
        # Frontend build-time gates are verified from the Vercel attestation,
        # never inferred from this backend process environment.
        frontend_serving_enabled=False,
        frontend_inline_authoring_enabled=False,
        r2_credentials_configured=(
            user_media_use_r2() and coach_videos_use_r2()
        ),
        practice_bucket=practice_bucket,
        coach_video_bucket=coach_bucket,
        r2_smoke_evidence_sha256=r2_manifest.get("evidence_sha256"),
        r2_smoke_manifest_valid=r2_manifest_valid,
        deployment_attestation_valid=deployment_attestation_valid,
        deployed_backend_gates_disabled=deployment_attestation_valid,
        deployed_frontend_gates_disabled=deployment_attestation_valid,
        deployed_learning_gates_disabled=deployment_attestation_valid,
        dataset_creation_enabled=Config.MLC2_DATASET_RELEASES_ENABLED,
        training_enabled=Config.MLC2_TRAINING_ENABLED,
        evaluation_enabled=bool(
            getattr(Config, "MLC2_EVALUATION_ENABLED", False)
        ),
        promotion_enabled=Config.MLC2_PROMOTION_ENABLED,
    ).as_dict()
    if args.json:
        print(json.dumps(report, sort_keys=True, default=str))
    else:
        status = "READY" if report["ready_for_activation_review"] else "BLOCKED"
        print(f"MLC-3 founder canary activation review: {status}")
        for blocker in report["blocker_codes"]:
            print(f"  BLOCKER {blocker}")
        for warning in report["warning_codes"]:
            print(f"  WARNING {warning}")
        if report["ready_for_activation_review"]:
            for action in report["activation_actions"]:
                print(f"  AFTER REVIEW {action}")
    return 0 if report["ready_for_activation_review"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
