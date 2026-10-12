import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "migrations" / "add_learning_surface_exposure_receipts.sql"
SQL = MIGRATION.read_text()


def _function(name: str) -> str:
    match = re.search(
        rf"CREATE OR REPLACE FUNCTION public\.{name}\b(.*?)\n\$\$;",
        SQL,
        flags=re.S,
    )
    assert match, name
    return match.group(1)


def test_blind_review_packet_rejects_prior_labels_predictions_and_transcript():
    create = _function("create_learning_surface_presentation_v1")
    for forbidden_key in (
        "machine_prediction", "user_self_report", "coach_judgment",
        "peer_judgment", "exact_text", "transcript_text",
    ):
        assert f"p_visible_payload ? '{forbidden_key}'" in create
    assert "coach draft requires an immutable blind judgment" in create
    assert "evidence_review_assignments" in create
