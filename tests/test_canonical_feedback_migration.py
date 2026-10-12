import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "migrations" / "add_canonical_feedback_data_contract.sql"
SQL = MIGRATION.read_text()


def _function(name):
    match = re.search(
        rf"CREATE OR REPLACE FUNCTION public\.{name}\b(.*?)\n\$\$;",
        SQL,
        flags=re.S,
    )
    assert match, name
    return match.group(1)


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
