from pathlib import Path


ROOT = Path(__file__).parents[1]
SQL = (ROOT / "migrations" / "add_seven_surface_readiness_report.sql").read_text()

SURFACES = {
    "confidence_classification", "correction_generation",
    "coach_comment_generation", "praise_generation", "praise_selection",
    "correction_selection", "ideal_text_generation",
}


def test_0301_is_ordered_before_the_mlc2_foundation_and_reports_all_seven_surfaces():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    readiness = "0301\tadd_seven_surface_readiness_report.sql"
    foundation = "0302\tadd_mlc2_foundation.sql"
    assert readiness in manifest
    assert foundation in manifest
    assert manifest.index(readiness) < manifest.index(foundation)
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


# ── 0395 · the eighth row (founder 2026-09-29, decision 2) ────────────────

COUNTED = (ROOT / "migrations" / "module_8_is_counted.sql").read_text()


def test_0395_reports_eight_surfaces_and_reads_module_8_from_the_exercise_tables():
    for surface in SURFACES:
        assert f"('{surface}'" in COUNTED
    assert "'exercise_adequacy_classification'::text AS surface" in COUNTED
    assert "8 AS position" in COUNTED
    assert "public.confident_voice_exercise_assignments" in COUNTED
    assert "public.confident_voice_exercise_exposures" in COUNTED
    assert "public.confident_voice_practice" in COUNTED
    assert "exercise_assignment_id" in COUNTED
    # No contradiction instrument for module 8, and said so rather than 0.
    assert "NULL::integer AS contradiction_count" in COUNTED
    assert "false AS contradictions_supported" in COUNTED


def test_0395_keeps_the_function_name_its_grants_and_its_read_only_shape():
    assert "CREATE OR REPLACE FUNCTION public.get_seven_surface_readiness_v1()" \
        in COUNTED
    assert "RETURNS JSONB" in COUNTED and "STABLE" in COUNTED
    assert "REVOKE ALL ON FUNCTION public.get_seven_surface_readiness_v1()" \
        in COUNTED
    assert "FROM PUBLIC, anon, authenticated" in COUNTED
    for forbidden in ("INSERT INTO", "UPDATE public.", "DELETE FROM"):
        assert forbidden not in COUNTED
    # Every field the seven-row report carries, the eight-row one carries.
    for field in (
        "visible_coverage_ratio", "version_coverage_ratio", "versions",
        "exclusion_count", "contradiction_count", "blockers",
        "authorized_dataset_release_count", "shadow_evaluation_count",
        "answered_exposure_count", "unanswered_exposure_count",
        "covered_project_count", "covered_coach_count",
        "coverage_dimensions", "missing_metadata", "exclusions_by_reason",
        "potential_duplicate_count", "speaker_disjoint_split",
    ):
        assert f"'{field}'" in COUNTED
