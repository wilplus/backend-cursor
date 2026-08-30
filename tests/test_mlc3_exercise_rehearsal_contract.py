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
CONCURRENCY_REHEARSAL = (
    ROOT / "tests" / "integration"
    / "mlc3_exercise_blind_packet_concurrency_rehearsal.sh"
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
        "EXERCISE_AUDIO_LINEAGE_SNIPPET_INTERVAL_MISMATCH",
        "catalog snapshot did not freeze the complete universe",
        "service role direct catalogue write unexpectedly succeeded",
        "wrong-surface blind packet unexpectedly succeeded",
        "unrelated-evidence blind packet unexpectedly succeeded",
        "wrong-duration blind packet unexpectedly succeeded",
        "wrong-taxonomy blind packet unexpectedly succeeded",
        "wrong-payload blind packet unexpectedly succeeded",
        "caller-built payload unexpectedly succeeded",
        "EXERCISE_BLIND_PACKET_PAYLOAD_NOT_CANONICAL",
        "caller transcript hash unexpectedly succeeded",
        "EXERCISE_BLIND_PACKET_TRANSCRIPT_HASH_MISMATCH",
        "server-derived packet or exact replay is invalid",
        "revoked blind packet replay unexpectedly succeeded",
        "missing policy purpose unexpectedly authorized replay",
        "receipt policy mismatch unexpectedly authorized replay",
        "EXERCISE_CURRENT_AUTHORIZATION_REVOKED",
        "wrong-evidence blind judgment unexpectedly succeeded",
        "reveal before judgment unexpectedly succeeded",
        "repaired purge graph omitted exact practice lineage",
        "M3-2 dark boundary is not fail closed",
        "confidence-exercise-blind-packet-v1",
        "exact_bytes_sha256",
    ):
        assert expected in REHEARSAL


def test_m3_2_concurrency_rehearsal_covers_atomic_first_creation():
    for expected in (
        "pg_advisory_xact_lock",
        "concurrent-blind-packet",
        "first_pid=$!",
        "second_pid=$!",
        'packet_count" != "1"',
        'created_event_count" != "1"',
        "Concurrent blind-packet idempotency rehearsal passed.",
    ):
        if expected == "pg_advisory_xact_lock":
            assert expected in (
                ROOT / "migrations" / "add_mlc3_exercise_dark_foundation.sql"
            ).read_text()
        else:
            assert expected in CONCURRENCY_REHEARSAL
