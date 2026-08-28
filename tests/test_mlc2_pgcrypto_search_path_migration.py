from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "fix_mlc2_pgcrypto_search_path.sql"
SQL = MIGRATION.read_text()


def test_manifest_appends_supabase_pgcrypto_fix_as_0307():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    assert manifest[-1] == "0307\tfix_mlc2_pgcrypto_search_path.sql"


def test_every_digest_using_mlc2_function_gets_trusted_extension_path():
    affected = (
        "assign_ml_speaker_split_v1(UUID, TEXT)",
        "create_mlc2_consent_snapshot_v1(UUID, UUID, UUID, UUID)",
        "finalize_mlc2_confidence_frame_v1(\n    UUID, TEXT, JSONB, JSONB\n)",
        "promote_recording_attempt_with_mlc2_confidence_v1(\n"
        "    UUID, TEXT, UUID, INTEGER, TEXT, TEXT, TEXT, JSONB\n)",
        "create_mlc2_confidence_blind_packet_v1(\n"
        "    UUID, UUID, TEXT, TEXT, TEXT, TEXT, TEXT\n)",
        "configure_mlc2_consent_policy_v1(\n"
        "    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT[], TEXT,\n"
        "    TEXT, TEXT, TIMESTAMPTZ\n)",
    )
    for signature in affected:
        assert f"ALTER FUNCTION public.{signature}" in SQL
    assert SQL.count("SET search_path = extensions, public") == len(affected)
    assert "to_regprocedure('extensions.digest(bytea,text)')" in SQL
    assert "to_regprocedure('extensions.digest(text,text)')" in SQL


def test_fix_changes_no_data_and_activates_no_writer():
    upper = SQL.upper()
    assert "INSERT INTO" not in upper
    assert "UPDATE " not in upper
    assert "DELETE FROM" not in upper
    assert "MLC2_CONFIDENCE_CUTOVER_MODE" not in SQL


def test_policy_registration_defaults_to_existing_r2_bucket():
    script = (ROOT / "scripts" / "configure_mlc2_consent_policy.py").read_text()
    assert "Config.R2_BUCKET_NAME or Config.COACH_FEEDBACK_VIDEO_BUCKET" in script
