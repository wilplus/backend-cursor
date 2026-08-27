from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREREQUISITES = (
    ROOT / "tests" / "integration" / "mlc2_rehearsal_prerequisites.sql"
).read_text()
REHEARSAL = (
    ROOT / "tests" / "integration" / "mlc2_confidence_rehearsal.sql"
).read_text()


def test_disposable_prerequisites_match_supabase_role_boundary():
    assert "CREATE EXTENSION IF NOT EXISTS pgcrypto" in PREREQUISITES
    assert "ALTER ROLE service_role BYPASSRLS" in PREREQUISITES
    for table in (
        "owner_principals", "projects", "recording_attempts", "takes",
        "paragraphs",
    ):
        assert f"CREATE TABLE IF NOT EXISTS public.{table}" in PREREQUISITES
    assert "not an application migration" in PREREQUISITES


def test_rehearsal_is_transaction_scoped_and_exercises_atomic_frame():
    assert "BEGIN;" in REHEARSAL
    assert REHEARSAL.rstrip().endswith("ROLLBACK;")
    assert "finalize_mlc2_confidence_frame_v1" in REHEARSAL
    for table in (
        "ml_model_runs", "ml_classification_runs", "ml_selection_runs",
        "ml_machine_predictions", "ml_candidate_sets", "ml_candidates",
    ):
        assert table in REHEARSAL
    assert "audio_too_short" in REHEARSAL
    assert "immutable_pool_sha256" in REHEARSAL
    assert "idempotent replay duplicated" in REHEARSAL
    assert "failed frame left partial canonical provenance" in REHEARSAL


def test_rehearsal_checks_permissions_and_immutability():
    assert "has_table_privilege('service_role'" in REHEARSAL
    assert "has_table_privilege('anon'" in REHEARSAL
    assert "has_table_privilege('authenticated'" in REHEARSAL
    assert "append-only mutation unexpectedly succeeded" in REHEARSAL
