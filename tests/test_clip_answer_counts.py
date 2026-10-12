"""Answer counts per clip as soft-label data (V4 brief 1.7; D-ML-11): the
pure rule, the side write, and the two places it is made. The database half
is tests/test_answer_counts_per_clip_are_soft_label_data_postgres.py."""
from __future__ import annotations


def test_the_sql_filter_carries_the_blind_rule_the_lock_and_neutral():
    import pathlib
    sql = (pathlib.Path(__file__).resolve().parents[1] / "migrations"
           / "answer_counts_per_clip_are_soft_label_data.sql").read_text()
    assert "AND label.blind IS NOT FALSE" in sql
    assert "value IN ('not_sure', 'neutral')" in sql
    assert "pg_advisory_xact_lock(hashtext(p_snippet_id::text))" in sql
    assert sql.index("pg_advisory_xact_lock") < sql.index("FROM public.confidence_labels label")
