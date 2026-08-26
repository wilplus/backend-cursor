import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "migrations" / "add_canonical_feedback_data_contract.sql"
SQL = MIGRATION.read_text()


TABLES = {
    "transcript_versions", "slides", "paragraphs", "evidence_spans",
    "acoustic_feature_snapshots", "candidate_sets", "feedback_candidates",
    "feedback_exposures", "machine_predictions", "generation_runs",
    "evidence_review_assignments", "confidence_self_reports",
    "confidence_coach_labels", "confidence_peer_labels",
    "praise_helpfulness", "correction_decisions", "paragraph_decisions",
    "feedback_revisions", "voice_album_admissions", "accepted_flagships",
    "root_phrases", "processing_stage_runs", "dataset_releases",
    "dataset_split_assignments", "dataset_release_items",
    "dataset_exclusions",
}


def _function(name):
    match = re.search(
        rf"CREATE OR REPLACE FUNCTION public\.{name}\b(.*?)\n\$\$;",
        SQL,
        flags=re.S,
    )
    assert match, name
    return match.group(1)


def test_migration_is_additive_and_manifested_last():
    destructive = re.sub(
        r"DROP TRIGGER IF EXISTS.*?;", "", SQL,
        flags=re.I | re.S,
    )
    assert not re.search(r"\bDROP\s+(TABLE|COLUMN)\b", destructive, re.I)
    assert not re.search(r"\bTRUNCATE\b", SQL, re.I)
    assert not re.search(r"\bDELETE\s+FROM\b", SQL, re.I)
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    version, filename = manifest[-1].split("\t", 1)
    assert version.isdigit()
    assert filename == "add_canonical_feedback_data_contract.sql"


def test_every_canonical_table_has_rls_and_service_role_only_grant():
    for table in TABLES:
        assert f"CREATE TABLE IF NOT EXISTS public.{table}" in SQL
        assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;" in SQL
        assert f"GRANT ALL ON TABLE public.{table} TO service_role;" in SQL
    assert "CREATE POLICY" not in SQL


def test_immutable_evidence_predictions_judgments_and_releases_are_guarded():
    guarded_block = re.search(
        r"FOREACH table_name IN ARRAY ARRAY\[(.*?)\] LOOP",
        SQL,
        flags=re.S,
    ).group(1)
    mutable_only = {"processing_stage_runs"}
    for table in TABLES - mutable_only:
        assert f"'{table}'" in guarded_block
    assert "BEFORE UPDATE OR DELETE" in SQL


def test_human_judgments_are_typed_and_provenance_is_not_collapsed():
    typed = {
        "confidence_self_reports", "confidence_coach_labels",
        "confidence_peer_labels", "praise_helpfulness",
        "correction_decisions", "paragraph_decisions",
    }
    for table in typed:
        block = re.search(
            rf"CREATE TABLE IF NOT EXISTS public\.{table} \((.*?)\n\);",
            SQL,
            flags=re.S,
        ).group(1)
        for required in (
                "evidence_span_id", "task_type", "value", "rater_role",
                "rater_id", "taxonomy_version", "created_at",
                "supersedes_id", "idempotency_key"):
            assert required in block
    assert "CREATE TABLE IF NOT EXISTS public.human_labels" not in SQL


def test_blind_sql_payloads_are_allowlisted_and_comparison_is_post_commit():
    blind = _function("blind_coach_evidence_v1")
    return_signature = blind.split("LANGUAGE sql", 1)[0]
    for allowed in (
            "evidence_span_id", "audio_ref", "start_ms", "end_ms",
            "technical_metadata"):
        assert allowed in return_signature
    for forbidden in (
            "owner_value", "machine_value", "peer_values", "exact_text",
            "transcript_text", "classification"):
        assert forbidden not in return_signature
    assert "confidence_coach_labels" in blind
    comparison = _function("coach_evidence_comparison_v1")
    assert "FROM public.confidence_coach_labels coach" in comparison
    assert "coach.rater_id = p_coach_id" in comparison
    assignment = _function("assign_confidence_coach_evidence_v1")
    assert "blind coach packet changed after assignment" in assignment
    judgment = _function("record_confidence_coach_judgment_v1")
    assert "row.blind_packet_hash = p_blind_packet_hash" in judgment
    assert "evidence_review_assignments" in judgment


def test_exposure_stage_and_dataset_constraints_are_atomic():
    exposure = _function("record_feedback_exposure_v1")
    assert "selected_count <> 3" in exposure
    assert "candidate_count <> jsonb_array_length(candidate_rows)" in exposure
    stage = _function("record_processing_stage_run_v1")
    assert "processing stage idempotency conflict" in stage
    assert "terminal processing stage is immutable" in stage
    release = _function("create_dataset_release_v1")
    assert "speaker split conflict" in release
    assert "dataset release mixes learning surfaces" in release
    assert "dataset item split is not speaker-stable" in release
    assert "dataset item evidence ownership mismatch" in release
    assert "dataset exclusion evidence ownership mismatch" in release
    assert "dataset release item count mismatch" in release


def test_human_decision_replays_refuse_cross_evidence_or_changed_values():
    decision = _function("record_feedback_human_decision_v1")
    assert decision.count("decision idempotency conflict") == 3
    assert "existing_evidence_id IS DISTINCT FROM" in decision
    assert "existing_rater_id IS DISTINCT FROM p_rater_id" in decision
    assert "existing_value IS DISTINCT FROM p_value" in decision


def test_parity_report_is_internal_observation_only():
    parity = _function("feedback_data_parity_v1")
    assert "'mode', 'observation_only'" in parity
    assert "candidate_count_equal" in parity
    assert "exact_three_equal" in parity
    assert "decisions_covered" in parity
    assert "REVOKE ALL ON FUNCTION public.feedback_data_parity_v1(UUID)" \
        in SQL
    assert "GRANT EXECUTE ON FUNCTION public.feedback_data_parity_v1(UUID)" \
        in SQL


def test_paragraph_versioning_and_root_phrase_require_exact_evidence():
    paragraph = _function("record_paragraph_decision_v1")
    assert "paragraph decision exact text is stale" in paragraph
    assert "paragraph evidence crosses a Take boundary" in paragraph
    assert "paragraph decision idempotency conflict" in paragraph
    root = _function("record_root_phrase_v1")
    assert "root phrase is not an exact paragraph span" in root
    assert "root phrase requires a current lock decision" in root
    assert "root phrase idempotency conflict" in root
    skipped = _function("record_root_phrase_skip_v1")
    assert "root phrase skip requires a current lock decision" in skipped
    assert "root_phrase_skipped" in skipped
    assert "root phrase skip idempotency conflict" in skipped
