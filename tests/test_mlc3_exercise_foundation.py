from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = ROOT / "migrations" / "add_mlc3_exercise_dark_foundation.sql"
SQL = MIGRATION_PATH.read_text()


def _table(name: str) -> str:
    start = SQL.index(f"CREATE TABLE IF NOT EXISTS public.{name}")
    next_table = SQL.find("CREATE TABLE IF NOT EXISTS public.", start + 1)
    return SQL[start: next_table if next_table >= 0 else len(SQL)]


def _function(name: str) -> str:
    start = SQL.index(f"CREATE OR REPLACE FUNCTION public.{name}")
    next_function = SQL.find("CREATE OR REPLACE FUNCTION public.", start + 1)
    return SQL[start: next_function if next_function >= 0 else len(SQL)]


def test_manifest_appends_m3_2_after_the_accepted_foundations():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    assert "0313\tadd_mlc3_exercise_dark_foundation.sql" in manifest
    assert manifest.index(
        "0312\tadd_phase1_deletion_completion.sql"
    ) < manifest.index("0313\tadd_mlc3_exercise_dark_foundation.sql")


def test_registry_adds_one_surface_and_explicit_aliases():
    assert "'MLC-3', 1, 'MLC-3-D2/M3-2'" in SQL
    assert "'exercise_adequacy_classification'" in SQL
    assert "WHEN 'exercise_adequacy_classification' THEN 'exercise_adequacy_event'" in SQL
    for alias in ("exercise_match", "practice_recommendation", "diagnostic_exercise"):
        assert f"('{alias}', 'exercise_adequacy_classification', true" in SQL
    assert (
        "exercise_adequacy_classification'\n"
        "        ) AND feedback_family_id IS NULL"
    ) in SQL


def test_catalogue_contracts_are_typed_versioned_and_immutable():
    for table in (
        "exercise_need_contracts", "exercise_media_objects",
        "exercise_definitions", "exercise_versions",
        "exercise_catalog_snapshots", "exercise_catalog_snapshot_items",
    ):
        assert f"CREATE TABLE IF NOT EXISTS public.{table}" in SQL
        assert f"'{table}'" in SQL
    need = _table("exercise_need_contracts")
    for field in (
        "operational_definition", "allowed_feature_names",
        "required_feature_names", "exclusion_reason_codes",
        "contraindications", "feature_schema_version",
        "ml_data_approval_ref", "approval_evidence_sha256",
    ):
        assert field in need
    assert "required_feature_names <@ allowed_feature_names" in need
    version = _table("exercise_versions")
    for field in (
        "need_contract_id", "media_object_id", "instruction_sha256",
        "safety_state", "catalogue_state", "version_sha256",
    ):
        assert field in version


def test_complete_catalogue_is_computed_by_database_not_supplied_by_caller():
    function = _function("finalize_exercise_catalog_snapshot_v1")
    assert "FROM public.exercise_versions version_row" in function
    assert "version_row.created_at <= p_version_cutoff_at" in function
    assert "jsonb_agg(jsonb_build_object" in function
    assert "EXERCISE_CATALOG_SNAPSHOT_INCOMPLETE" in function
    assert "p_items" not in function
    assert "p_candidates" not in function
    assert "manifest_sha256" in _table("exercise_catalog_snapshots")


def test_authorization_is_product_purpose_not_learning_surface_and_fails_closed():
    checks = _table("exercise_authorization_checks")
    assert "personalized_exercise_recommendation" in checks
    assert "exercise_adequacy_classification" not in checks
    function = _function("record_exercise_authorization_check_v1")
    for boundary in (
        "purpose.operational", "purpose.authorizes_processing",
        "processing_authorization_receipt_purposes",
        "processing_policy_purposes", "processing_service_blocks",
        "EXERCISE_PURPOSE_INACTIVE",
    ):
        assert boundary in function
    current = _function("require_current_exercise_authorization_v1")
    for boundary in (
        "checked_at >= now() - interval '5 minutes'",
        "purpose.operational AND purpose.authorizes_processing",
        "policy.status = 'active'", "processing_service_blocks",
        "EXERCISE_CURRENT_AUTHORIZATION_REVOKED",
    ):
        assert boundary in current
    assert "INSERT INTO public.processing_authorization" not in function
    assert "UPDATE public.processing_purpose_registry" not in SQL


def test_profile_is_stable_speaker_identity_not_a_trait_store():
    profile = _table("learning_profiles")
    assert "speaker_id                 UUID NOT NULL UNIQUE" in profile
    assert "learning_profile_speaker_principal_fk" in profile
    assert "profile_identity_sha256" in profile
    for forbidden in ("emotion", "diagnosis", "personality", "gender", "stress"):
        assert forbidden not in profile.lower()
    function = _function("ensure_learning_profile_v1")
    assert "require_current_exercise_authorization_v1" in function
    assert "'profile_identity'" in function
    assert "assign_ml_speaker_split_v1" in function


def test_audio_lineage_binds_exact_bytes_and_all_owner_coordinates():
    lineage = _table("exercise_audio_lineages")
    for field in (
        "acquisition_principal_id", "speaker_id", "learning_profile_id",
        "authorization_check_id", "processing_audio_object_id", "project_id",
        "take_id", "recording_attempt_id", "recording_id", "snippet_id",
        "start_offset_ms", "duration_ms", "exact_audio_sha256",
        "object_byte_size", "verification_method", "lineage_sha256",
    ):
        assert field in lineage
    function = _function("register_exercise_audio_lineage_v1")
    for boundary in (
        "storage_provider = 'r2'", "deleted_at IS NULL",
        "owner_principal_id = p_acquisition_principal_id",
        "session_id = p_take_id", "recording_id = p_recording_id",
        "object_row.exact_bytes_sha256", "source_audio_lineage",
    ):
        assert boundary in function
    assert "require_current_exercise_authorization_v1" in function
    assert "recording_id OR audio_ref" not in SQL


def test_blind_packet_schema_has_allowlisted_fields_and_reveal_sequence():
    packet = _table("exercise_blind_packets")
    for field in (
        "review_assignment_id", "audio_lineage_id", "reviewer_principal_id",
        "packet_schema_version", "confidence_taxonomy_version",
        "playback_token_sha256", "playback_expires_at", "clip_duration_ms",
        "language_code", "asr_transcript", "visible_payload_sha256",
    ):
        assert field in packet
    for forbidden in (
        "machine_score", "machine_prediction", "selection_probability",
        "exercise_version_id", "need_code", "user_answer",
    ):
        assert forbidden not in packet
    events = _table("exercise_blind_packet_events")
    for event in (
        "blind_packet_created", "blind_packet_accessed",
        "blind_judgment_submitted", "post_judgment_reveal_granted",
        "post_judgment_reveal_accessed",
    ):
        assert event in events
    validator = _function("validate_exercise_blind_event_sequence_v1")
    assert "EXERCISE_BLIND_REVEAL_REQUIRES_JUDGMENT" in validator
    assert "EXERCISE_BLIND_REVEAL_NOT_GRANTED" in validator
    assert "actor_provenance IN ('blind_coach', 'blind_peer')" in validator


def test_all_new_tables_are_rls_append_only_and_rpc_only():
    assert "ENABLE ROW LEVEL SECURITY" in SQL
    assert "REVOKE ALL ON TABLE public.%I FROM anon, authenticated, service_role" in SQL
    assert "GRANT SELECT ON TABLE public.%I TO service_role" in SQL
    assert "reject_mlc2_immutable_mutation" in SQL
    assert "GRANT INSERT ON" not in SQL
    for function in (
        "register_exercise_need_contract_v1",
        "register_exercise_media_object_v1",
        "register_exercise_version_v1",
        "finalize_exercise_catalog_snapshot_v1",
        "record_exercise_authorization_check_v1",
        "ensure_learning_profile_v1",
        "register_exercise_audio_lineage_v1",
    ):
        assert f"GRANT EXECUTE ON FUNCTION public.{function}" in SQL


def test_m3_2_is_structurally_dark_and_has_no_later_slice_tables():
    lowered = SQL.lower()
    for forbidden in (
        "create table if not exists public.exercise_candidate_sets",
        "create table if not exists public.exercise_candidates",
        "create table if not exists public.exercise_assignments",
        "create table if not exists public.exercise_practice_sessions",
        "create table if not exists public.exercise_practice_attempts",
        "create table if not exists public.exercise_outcome_events",
        "create table if not exists public.ml_dataset",
        "create table if not exists public.ml_training",
        "create table if not exists public.ml_evaluation",
        "create table if not exists public.ml_promotion",
    ):
        assert forbidden not in lowered
    health = _function("get_mlc3_exercise_foundation_health_v1")
    for flag in (
        "'producer_integration', false", "'serves_user', false",
        "'dataset_creation_enabled', false", "'training_enabled', false",
        "'evaluation_enabled', false", "'promotion_enabled', false",
    ):
        assert flag in health


def test_deletion_repair_is_versioned_and_uses_physical_practice_keys():
    assert "resolve_phase1_purge_subject_graph_v2" in SQL
    assert "freeze_phase1_purge_inventory_v4" in SQL
    assert "phase1-purge-resolver-v4" in SQL
    for key in (
        "speaker_ids", "practice_ids", "practice_attempt_ids",
        "exercise_audio_lineage_ids", "exercise_blind_packet_ids",
    ):
        assert key in SQL
    assert "practice.owner_user_id::text = ANY(user_values)" in SQL
    assert "attempt.practice_id::text = ANY(practice_values)" in SQL
    legacy = (ROOT / "migrations" / "add_phase1_deletion_completion.sql").read_text()
    assert "phase1-purge-resolver-v3" in legacy
    assert "freeze_phase1_purge_inventory_v3" in legacy
