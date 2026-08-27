from pathlib import Path


ROOT = Path(__file__).parents[1]
SQL = (ROOT / "migrations" / "add_seven_surface_readiness_report.sql").read_text()

SURFACES = {
    "confidence_classification", "correction_generation",
    "coach_comment_generation", "praise_generation", "praise_selection",
    "correction_selection", "ideal_text_generation",
}


def test_0301_is_latest_and_reports_all_seven_surfaces():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    assert manifest[-1] == "0301\tadd_seven_surface_readiness_report.sql"
    for surface in SURFACES:
        assert f"('{surface}'" in SQL


def test_readiness_is_aggregate_read_only_and_has_no_command_surface():
    assert "RETURNS JSONB" in SQL
    assert "STABLE" in SQL
    assert "REVOKE ALL ON FUNCTION" in SQL
    assert "FROM PUBLIC, anon, authenticated" in SQL
    for forbidden in ("INSERT INTO", "UPDATE public.", "DELETE FROM"):
        assert forbidden not in SQL


def test_rows_report_coverage_versions_exclusions_contradictions_and_blockers():
    for field in (
        "visible_coverage_ratio", "version_coverage_ratio", "versions",
        "exclusion_count", "contradiction_count", "blockers",
        "authorized_dataset_release_count", "shadow_evaluation_count",
        "answered_exposure_count", "unanswered_exposure_count",
        "covered_project_count", "covered_coach_count",
        "coverage_dimensions", "missing_metadata", "exclusions_by_reason",
        "potential_duplicate_count", "speaker_disjoint_split",
    ):
        assert f"'{field}'" in SQL
    assert "contradiction_metric_not_defined" in SQL
    assert "no_authorized_consent_release" in SQL
