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


def test_blind_packet_schema_has_allowlisted_fields_and_reveal_sequence():
    packet = _table("exercise_blind_packets")
    for field in (
        "review_assignment_id", "audio_lineage_id", "authorization_check_id",
        "reviewer_principal_id",
        "packet_schema_version", "confidence_taxonomy_version",
        "playback_token_sha256", "playback_expires_at", "clip_duration_ms",
        "language_code", "asr_transcript", "visible_payload",
        "visible_payload_sha256",
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
    assert "evidence_span_id = assignment.evidence_span_id" in validator
    assert "EXERCISE_BLIND_JUDGMENT_EVIDENCE_MISMATCH" in validator
