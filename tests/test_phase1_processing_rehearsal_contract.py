from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREREQUISITES = (
    ROOT / "tests" / "integration" / "phase1_processing_prerequisites.sql"
).read_text()
REHEARSAL = (
    ROOT / "tests" / "integration" / "phase1_processing_rehearsal.sql"
).read_text()


def test_rehearsal_is_disposable_and_transaction_scoped():
    assert "not an application migration" in PREREQUISITES
    assert "CREATE EXTENSION IF NOT EXISTS pgcrypto" in PREREQUISITES
    assert "ALTER ROLE service_role BYPASSRLS" in PREREQUISITES
    assert REHEARSAL.startswith("\\set ON_ERROR_STOP on")
    assert "BEGIN;" in REHEARSAL
    assert REHEARSAL.rstrip().endswith("ROLLBACK;")


def test_rehearsal_covers_authorization_intake_provider_and_termination():
    for expected in (
        "passive authorization check created acceptance",
        "register_phase1_policy_v1",
        "activate_phase1_policy_v1",
        "accept_phase1_processing_authorization_v1",
        "acceptance replay was not idempotent",
        "finalize_phase1_recording_intake_v1",
        "issue_phase1_provider_permit_v1",
        "claim_phase1_orphan_audio_v1",
        "request_phase1_purge_v1",
        "termination did not block processing immediately",
        "append-only evidence mutation unexpectedly succeeded",
    ):
        assert expected in REHEARSAL
