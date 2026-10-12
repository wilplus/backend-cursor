from pathlib import Path

SQL = (Path(__file__).resolve().parents[1] / "migrations/add_confident_moment_coaching_bundle_v1.sql").read_text()


def test_weak_and_ambiguous_never_qualify_automatic_root():
    automatic = SQL.split("IF p_action='activate_automatic_root'", 1)[1]
    assert "x.response='confident_yes'" in automatic
    assert "result='aligned'" in automatic
    assert "eligible_automatic_proposal" in automatic
    assert "qualification:='not_qualified_reference'" in automatic
