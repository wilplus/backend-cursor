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
