from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREREQUISITES = (
    ROOT / "tests" / "integration"
    / "mlc3_exercise_foundation_prerequisites.sql"
).read_text()
REHEARSAL = (
    ROOT / "tests" / "integration"
    / "mlc3_exercise_foundation_rehearsal.sql"
).read_text()


def test_m3_2_rehearsal_is_disposable_and_transaction_scoped():
    assert "not an application migration" in PREREQUISITES
    assert REHEARSAL.startswith("\\set ON_ERROR_STOP on")
    assert "BEGIN;" in REHEARSAL
    assert REHEARSAL.rstrip().endswith("ROLLBACK;")


def test_m3_2_rehearsal_covers_dark_security_and_lineage_rejections():
    for expected in (
        "inactive exercise purpose unexpectedly authorized",
        "changed exact lineage replay unexpectedly succeeded",
        "catalog snapshot did not freeze the complete universe",
        "service role direct catalogue write unexpectedly succeeded",
        "reveal before judgment unexpectedly succeeded",
        "repaired purge graph omitted exact practice lineage",
        "M3-2 dark boundary is not fail closed",
        "confidence-exercise-blind-packet-v1",
        "exact_bytes_sha256",
    ):
        assert expected in REHEARSAL
