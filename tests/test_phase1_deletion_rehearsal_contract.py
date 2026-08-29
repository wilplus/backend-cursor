from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREREQUISITES = (
    ROOT / "tests" / "integration" / "phase1_processing_prerequisites.sql"
).read_text()
REHEARSAL = (
    ROOT / "tests" / "integration" / "phase1_deletion_completion_rehearsal.sql"
).read_text()


def test_deletion_rehearsal_is_disposable_and_transaction_scoped():
    assert "not an application migration" in PREREQUISITES
    assert REHEARSAL.startswith("\\set ON_ERROR_STOP on")
    assert "BEGIN;" in REHEARSAL
    assert REHEARSAL.rstrip().endswith("ROLLBACK;")


def test_deletion_rehearsal_covers_fail_closed_and_evidence_invariants():
    for expected in (
        "purge_unclassified_fixture",
        "UNCLASSIFIED_SUBJECT_RELATION",
        "PURGE_MANIFEST_DUPLICATE_TARGET",
        "PURGE_INVENTORY_REPLAY_CONFLICT",
        "PURGE_TARGET_STILL_PRESENT",
        "PROVIDER_DELETION_CONTRACT_REPLAY_CONFLICT",
        "retire_phase1_provider_deletion_contract_v1",
        "Phase-1 evidence is append-only",
        "remaining_match_count",
        "has_table_privilege('service_role'",
    ):
        assert expected in REHEARSAL
