from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (
    ROOT / "migrations/add_mlc3_first_client_service_d2.sql"
).read_text()


def _function(name: str) -> str:
    marker = f"CREATE OR REPLACE FUNCTION public.{name}("
    start = SQL.index(marker)
    return SQL[start:SQL.index("\n$$;", start) + 4]


def test_original_and_practice_confidence_reviews_are_separate_and_blind():
    freeze = _function("freeze_exercise_service_blind_review_set_v1")
    judgment = _function("submit_exercise_service_confidence_judgment_v1")
    complete = _function("complete_exercise_service_blind_review_v1")
    assert "original_source" in freeze
    assert "first_valid_practice" in freeze
    assert "source_confidence_assignment_id" in freeze
    assert "practice_confidence_assignment_id" in freeze
    assert "blind_coach" in judgment
    assert "dataset_eligible" not in judgment or "false" in judgment
    assert "source_judgment" in complete
    assert "practice_judgment" in complete
    assert "exercise_pair_judgments" not in complete
