from pathlib import Path


ROOT = Path(__file__).parents[1]
MIGRATION = (
    ROOT / "migrations" / "extend_dataset_releases_to_seven_surfaces.sql"
)
SQL = MIGRATION.read_text()

SURFACES = {
    "confidence_classification", "correction_generation",
    "coach_comment_generation", "praise_generation", "praise_selection",
    "correction_selection", "ideal_text_generation",
}


def test_migration_0300_widens_both_release_boundaries_to_exactly_seven():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    assert "0300\textend_dataset_releases_to_seven_surfaces.sql" in manifest
    for surface in SURFACES:
        assert SQL.count(f"'{surface}'") >= 2


def test_only_document_level_ideal_text_may_omit_an_evidence_span():
    assert "ALTER COLUMN evidence_span_id DROP NOT NULL" in SQL
    assert "learning_surface = 'ideal_text_generation'" in SQL
    assert "OR evidence_span_id IS NOT NULL" in SQL
    assert "FROM public.takes take_row" in SQL
    assert "ideal text dataset item Take mismatch" in SQL


def test_widening_is_additive_and_does_not_rewrite_existing_release_rows():
    upper = SQL.upper()
    assert "DELETE FROM PUBLIC.DATASET" not in upper
    assert "UPDATE PUBLIC.DATASET" not in upper
    assert "DROP TABLE" not in upper


# ── 0395 · module 8 is counted (founder 2026-09-29, decision 2) ───────────

WIDENED = ROOT / "migrations" / "module_8_is_counted.sql"
WIDENED_SQL = WIDENED.read_text()


def test_migration_0395_re_adds_both_release_checks_with_eight_names():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    assert "0395\tmodule_8_is_counted.sql" in manifest
    for surface in SURFACES | {"exercise_adequacy_classification"}:
        assert WIDENED_SQL.count(f"'{surface}'") >= 2, surface
    for name in ("dataset_releases_learning_surface_check",
                 "dataset_release_items_learning_surface_check"):
        assert f"DROP CONSTRAINT IF EXISTS {name}" in WIDENED_SQL
        assert f"ADD CONSTRAINT {name}" in WIDENED_SQL


def test_0395_is_additive_and_leaves_the_packet_tables_at_seven():
    upper = WIDENED_SQL.upper()
    assert "DELETE FROM PUBLIC.DATASET" not in upper
    assert "UPDATE PUBLIC.DATASET" not in upper
    assert "DROP TABLE" not in upper
    assert "learning_surface_exposure_receipts_learning_surface_check" \
        not in WIDENED_SQL
    assert "learning_surface_presentations_learning_surface_check" \
        not in WIDENED_SQL
    # The reason is in the header, where the next reader will look.
    assert "0299" in WIDENED_SQL and "stay at seven".upper() in upper
