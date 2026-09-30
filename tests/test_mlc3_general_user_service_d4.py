from __future__ import annotations

from pathlib import Path
from services.first_client_repository import FirstClientRepository

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "migrations/add_mlc3_general_user_service_d4.sql").read_text()
D2_SQL = (ROOT / "migrations/add_mlc3_first_client_service_d2.sql").read_text()
GUARD = (ROOT / "routes/phase2_guard.py").read_text()
GUIDANCE = (ROOT / "services/coach_guidance_delivery.py").read_text()
DESIGN_SHA256 = (
    "4ee8cc5f1dda8cf5e727fefdaef12a1a96a85d9fcd01c74e8953564026bf1085"
)


class _Result:
    def __init__(self, data):
        self.data = data


class _Rpc:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return _Result(self.result)


class _Client:
    def __init__(self):
        self.calls = []

    def rpc(self, name, payload):
        self.calls.append((name, payload))
        return _Rpc([{
            "id": "enrollment",
            "rollout_revision_id": "rollout",
            "operation_mode": "general_service",
        }])


def test_release_is_structurally_disabled_and_nonlearning():
    assert "'disabled'" in SQL
    assert "INSERT INTO public.mlc3_service_rollout_revisions" in SQL
    assert "serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user)" in SQL
    assert "dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible)" in SQL
    assert "MLC3_GENERAL_SERVICE_DATASET_FORBIDDEN" in SQL
    assert "training" not in SQL.lower() or "not created or enabled" in SQL


def test_exact_dual_purpose_same_receipt_is_required():
    body = SQL.split(
        "CREATE OR REPLACE FUNCTION public.resolve_mlc3_dual_purpose_receipt_v2",
        1,
    )[1].split("\n$$;", 1)[0]
    assert "processing_authorization_receipt_purposes" in body
    assert "processing_policy_purposes" in body
    assert "processing_purpose_registry" in body
    assert "personalized_exercise_recommendation" in body
    assert "coach_review" in body
    assert "registry.operational" in body
    assert "registry.authorizes_processing" in body
    assert "MLC3_DUAL_PURPOSE_AUTHORITY_REQUIRED" in body


def test_ga_requires_separate_exact_risk_decision():
    assert "founder_skip_cohort_v1" in SQL
    assert DESIGN_SHA256 in SQL
    activation = SQL.split(
        "CREATE OR REPLACE FUNCTION public.register_mlc3_general_rollout_v2",
        1,
    )[1].split("\n$$;", 1)[0]
    assert "activation_risk_decision_id" in activation
    assert "capacity_policy_sha256" in activation
    assert "review_state = 'accepted'" in activation


def test_legacy_allowlist_cannot_authorize_http_runtime():
    assert "MLC3_SERVICE_ENABLED" in GUIDANCE
    assert "MLC3_PILOT_PRINCIPAL_IDS" not in GUIDANCE
    assert "ensure_service_enrollment" in GUARD
    assert "MLC3_PILOT_ENABLED" not in GUARD


def test_runtime_cutover_registry_is_exact_and_fails_closed():
    assert "MLC3_RUNTIME_FUNCTION_MISSING" in SQL
    assert "MLC3_RUNTIME_FUNCTION_CUTOVER_CONFLICT" in SQL
    assert "current_mlc3_operation_mode_v2" in SQL
    assert "cohort_service" in SQL
    assert "general_service" in SQL
    assert "require_mlc3_service_access_v2" in SQL


def test_offer_event_uses_the_rollout_resolver_through_exact_live_guard():
    mode_registry, resolver_cutover = SQL.split(
        "-- Cut every runtime wrapper over to the rollout-aware resolver.", 1
    )
    resolver_registry, chain_check = resolver_cutover.split(
        "-- The offer event writer delegates authorization", 1
    )
    event_signature = (
        "public.record_exercise_offer_service_event_v1"
        "(uuid,uuid,uuid,text,uuid,text,jsonb,timestamptz,text)"
    )
    guard_signature = "public.require_exercise_service_offer_live_v1(uuid,uuid)"

    assert event_signature in mode_registry
    assert guard_signature in mode_registry
    assert guard_signature in resolver_registry
    assert event_signature not in resolver_registry
    assert "require_exercise_service_offer_live_v1" in chain_check
    assert "require_mlc3_service_access_v2" in chain_check
    assert "require_mlc3_service_principal_v1" in chain_check
    assert "MLC3_OFFER_RESOLVER_CHAIN_CONFLICT" in chain_check


def test_new_service_rows_freeze_rollout_enrollment_and_hash():
    assert "rollout_revision_id UUID" in SQL
    assert "enrollment_revision_id UUID" in SQL
    assert "rollout_identity_sha256 TEXT" in SQL
    assert "MLC3_EXACT_ROLLOUT_LINEAGE_REQUIRED" in SQL
    assert "require-mlc3-service-access-v2" in SQL


def test_enrollment_is_exact_account_principal_and_append_only():
    assert "MLC3_ACCOUNT_PRINCIPAL_AMBIGUOUS" in SQL
    assert "guest_secret_hash IS NULL" in SQL
    assert "mlc3_service_enrollment_revisions" in SQL
    assert "MLC3_GENERAL_SERVICE_APPEND_ONLY" in SQL
    assert "supersedes_enrollment_revision_id" in SQL


def test_speaker_count_identity_and_target_span_are_separate():
    assert "speaker_count_status" in SQL
    assert "speaker_identity_status" in SQL
    assert "target_start_ms" in SQL
    assert "target_duration_ms" in SQL
    assert "transcript_sha256" in SQL
    assert "audio_sha256" in SQL
    assert "reviewed_segmentation" in SQL


def test_self_speaker_is_explicit_and_not_inferred_from_account():
    function = SQL.split(
        "CREATE OR REPLACE FUNCTION public.record_mlc3_self_speaker_target_v1",
        1,
    )[1].split("\n$$;", 1)[0]
    assert "this_is_my_voice" in function
    assert "mlc3-self-speaker-assertion-v1" in function
    assert "processing_audio_object_deletion_events" in function
    assert "MLC3_SELF_SPEAKER_AUDIO_NOT_LIVE" in function
    assert "email" not in function.lower()
    assert "similarity" not in function.lower()
    assert "record_mlc3_feedback_self_speaker_target_v1" in SQL
    assert "record_mlc3_practice_self_speaker_target_v1" in SQL
    assert "confirm_mlc3_practice_speaker_and_pair_v1" in SQL


def test_pair_insert_requires_current_exact_same_speaker():
    assert "freeze_mlc3_same_speaker_eligibility_v1" in SQL
    assert "speaker_identity_mismatch_or_unresolved" in SQL
    assert "speaker_eligibility_revision_id" in SQL
    assert "a0_mlc3_pair_speaker_identity" in SQL
    assert "source_binding.speaker_id = practice_binding.speaker_id" in SQL
    assert "require_mlc3_current_pair_speaker_identity_v1" in SQL
    assert "source_binding.binding_state <> 'active'" in SQL
    assert "practice_binding.binding_state <> 'active'" in SQL
    assert "assign_synthetic_exercise_pair_v1" in SQL
    assert "submit_synthetic_exercise_pair_judgment_v1" in SQL


def test_capacity_and_halt_states_are_typed_product_evidence():
    for state in (
        "MLC3_ENROLLMENT_CAPACITY_REACHED",
        "MLC3_UPLOAD_CAPACITY_REACHED",
        "MLC3_COACH_QUEUE_BACKPRESSURE",
        "MLC3_MEDIA_BUDGET_REACHED",
        "MLC3_RECOVERY_BACKLOG_BLOCKED",
        "MLC3_ROLLOUT_HALTED",
    ):
        assert state in SQL
    assert "halt_mlc3_service_rollout_v1" in SQL


def test_rpc_permissions_keep_operator_writes_private():
    assert (
        "register_mlc3_activation_risk_decision_v1" in SQL
        and "FROM PUBLIC, anon, authenticated, service_role" in SQL
    )
    assert "GRANT EXECUTE ON FUNCTION public.ensure_mlc3_service_enrollment_v2" in SQL
    assert "REVOKE ALL ON FUNCTION public.require_mlc3_service_principal_v1" in SQL


def test_repository_uses_exact_rollout_enrollment_rpc():
    client = _Client()
    repository = FirstClientRepository(lambda: client)
    result = repository.ensure_service_enrollment(
        acquisition_principal_id="principal",
        owner_user_id="user",
        idempotency_key="entry",
    )
    assert result and result["operation_mode"] == "general_service"
    assert client.calls == [(
        "ensure_mlc3_service_enrollment_v2",
        {
            "p_acquisition_principal_id": "principal",
            "p_owner_user_id": "user",
            "p_idempotency_key": "entry",
        },
    )]


def test_database_allocates_practice_attempt_indexes_for_runtime():
    assert "reserve_exercise_practice_service_upload_v2" in SQL
    assert (
        "reserve_exercise_practice_service_upload_v1"
        "(uuid,uuid,uuid,text,bigint,text,text,text,integer)" in SQL
    )
    assert (
        "reserve_exercise_practice_service_upload_v1"
        "(uuid,uuid,integer,uuid,text,bigint,text,text,text,integer)"
        not in SQL
    )
    assert "practice-service-upload-session:" in D2_SQL
    assert "COALESCE(max(row.attempt_index), 0) + 1" in D2_SQL
    v2_body = SQL.split(
        "CREATE OR REPLACE FUNCTION "
        "public.reserve_exercise_practice_service_upload_v2",
        1,
    )[1].split("\n$$;", 1)[0]
    assert "next_attempt_index" not in v2_body
    assert "RETURN public.reserve_exercise_practice_service_upload_v1(" in v2_body
    repository = (ROOT / "services/first_client_repository.py").read_text()
    assert '"reserve_exercise_practice_service_upload_v2"' in repository
    assert (
        "reserve_exercise_practice_service_upload_v1\", payload"
        not in repository
    )
