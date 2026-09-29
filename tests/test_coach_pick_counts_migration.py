"""0398, as text: a coach-shared exercise gets the same three rows a machine
pick gets, under the coach policy name, and nothing else changes shape.

Founder 2026-09-29, decision 3. The database pins run on a disposable lane
(tests/test_a_coach_pick_counts_postgres.py); these hold the file itself to
what the header says.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
SQL = (ROOT / "migrations" / "a_coach_pick_counts.sql").read_text()


def test_0398_is_in_the_manifest_and_the_rehearsal_chain():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    assert "0398\ta_coach_pick_counts.sql" in manifest
    recipe = (ROOT / "tests" / "integration"
              / "confident_moment_rehearsal.sh").read_text()
    assert recipe.count("hard migrations/a_coach_pick_counts.sql") == 2
    tier = (ROOT / "scripts" / "rehearsal_tier.sh").read_text()
    assert "tests/test_a_coach_pick_counts_postgres.py" in tier


def test_the_coach_shape_is_named_and_told_apart_from_the_draw():
    assert "'exercise-coach-shared-v1'" in SQL
    assert "'coach_chosen'" in SQL
    assert "'coach_request', 'coach_review'" in SQL
    # A coach pick is only ever under the coach policy, and vice versa.
    assert "cv_exercise_assignment_coach_policy_check" in SQL
    assert ("(selection_mode = 'coach_chosen')\n"
            "        = (exposure_policy_version = 'exercise-coach-shared-v1')") in SQL
    # Not randomized: the singleton shape, no seed and no draw.
    assert ("selection_mode IN ('deterministic_singleton', 'coach_chosen')\n"
            "         AND candidate_count = 1") in SQL


def test_the_writer_is_insert_once_with_its_trace_and_a_coach_only_trace():
    assert "CREATE OR REPLACE FUNCTION public.assign_coach_shared_exercise_v1(" in SQL
    assert "pg_advisory_xact_lock" in SQL
    assert "RETURN existing;" in SQL
    assert "INSERT INTO public.confident_voice_exercise_match_traces" in SQL
    assert "->>'outcome' IS DISTINCT FROM 'coach_chosen'" in SQL
    assert "jsonb_array_length(p_trace->'candidates') <> 1" in SQL
    assert "OR (p_trace->>'fit') IS NOT NULL" in SQL


def test_the_render_receipt_v2_finds_any_policy_and_v1_is_kept():
    assert "CREATE OR REPLACE FUNCTION public.record_exercise_rendered_v2(" in SQL
    assert "AND selected_exercise_id = p_exercise_id" in SQL
    assert "EXERCISE_RENDERED_WRONG_EXERCISE" in SQL
    assert "EXERCISE_RENDERED_NOT_DRAWN" in SQL
    assert "EXERCISE_RENDERED_NOT_OWNER" in SQL
    assert "DROP FUNCTION" not in SQL.upper()


def test_additive_idempotent_and_service_role_only():
    upper = SQL.upper()
    for forbidden in ("DROP TABLE", "DELETE FROM", "UPDATE PUBLIC.",
                      "TRUNCATE"):
        assert forbidden not in upper
    assert "DROP CONSTRAINT %I" in SQL and "DROP CONSTRAINT IF EXISTS" in SQL
    for fn in ("assign_coach_shared_exercise_v1", "record_exercise_rendered_v2"):
        assert f"REVOKE ALL ON FUNCTION public.{fn}(" in SQL
        assert f"GRANT EXECUTE ON FUNCTION public.{fn}(" in SQL
    assert "FROM PUBLIC, anon, authenticated" in SQL
    assert "TO service_role" in SQL


def test_the_readiness_and_fair_test_read_the_flag():
    readiness = (ROOT / "services" / "exercise_learning_readiness.py").read_text()
    assert 'row.get("outcome") == "coach_chosen"' in readiness
    fair = (ROOT / "services" / "exercise_fair_test.py").read_text()
    assert '== "coach_chosen"' in fair
    exposure = (ROOT / "services" / "exercise_exposure.py").read_text()
    assert "0398" in exposure
