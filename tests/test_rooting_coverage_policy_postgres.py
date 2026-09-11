from pathlib import Path

SQL = (Path(__file__).resolve().parents[1] / "migrations/pending/add_confident_moment_coaching_bundle_v1.sql").read_text()


def test_coverage_is_database_derived_and_honest():
    assert "ceil(n*.30)" in SQL
    assert "ceil(n*.80)" in SQL
    assert "ELSE n END" in SQL
    assert "target_met boolean GENERATED ALWAYS" in SQL
    assert "achieved_slide_count" in SQL


def test_weak_and_ambiguous_never_qualify_automatic_root():
    automatic = SQL.split("IF p_action='activate_automatic_root'", 1)[1]
    assert "x.response='confident_yes'" in automatic
    assert "result='aligned'" in automatic
    assert "eligible_automatic_proposal" in automatic
    assert "qualification:='not_qualified_reference'" in automatic


def test_root_axes_are_separate_and_restore_is_exact():
    for value in ("automatic_product_selection", "owner_selection", "automatic_replaceable", "owner_locked", "not_qualified_reference", "qualified_confident_reference"):
        assert value in SQL
    assert "p_restore_product_action_id" in SQL
    assert "CONFIDENT_MOMENT_STALE_REVISION" in SQL

