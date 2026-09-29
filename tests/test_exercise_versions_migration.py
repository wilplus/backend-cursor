"""0399, as text: one immutable version row per save of the live library,
written only through its RPCs, with one transcript transition.

Founder 2026-09-29, decision 4. The database pins run on a disposable lane
(tests/test_exercise_versions_postgres.py).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
SQL = (ROOT / "migrations" / "an_exercise_keeps_its_versions.sql").read_text()


def test_0399_is_in_the_manifest_and_the_rehearsal_chain():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    assert "0399\tan_exercise_keeps_its_versions.sql" in manifest
    recipe = (ROOT / "tests" / "integration"
              / "confident_moment_rehearsal.sh").read_text()
    assert recipe.count("hard migrations/an_exercise_keeps_its_versions.sql") == 2
    tier = (ROOT / "scripts" / "rehearsal_tier.sh").read_text()
    assert "tests/test_exercise_versions_postgres.py" in tier


def test_the_row_holds_the_three_texts_the_video_lineage_and_the_transcript():
    assert "CREATE TABLE IF NOT EXISTS public.diagnostic_exercise_version" in SQL
    for column in ("ai_draft_text", "instruction", "transcript", "video_sha256",
                   "video_bytes", "explanation_video_url", "transcript_status",
                   "source", "created_by"):
        assert column in SQL, column
    assert "UNIQUE (exercise_id, version)" in SQL
    assert "'cms', 'coach_panel', 'coach_request', 'coach_review'" in SQL
    assert "'not_requested', 'pending', 'done', 'coach_authorization_missing'" in SQL


def test_written_only_through_rpcs_and_immutable_but_for_the_transcript():
    assert "REVOKE ALL ON public.diagnostic_exercise_version FROM service_role" in SQL
    assert "GRANT SELECT, DELETE ON public.diagnostic_exercise_version TO service_role" in SQL
    assert "CREATE OR REPLACE FUNCTION public.record_exercise_version_v1(p_row JSONB)" in SQL
    assert "ON CONFLICT (exercise_id, version) DO NOTHING" in SQL
    assert "CREATE OR REPLACE FUNCTION public.set_exercise_version_transcript_v1(" in SQL
    assert "AND transcript_status = 'pending'" in SQL
    assert "EXERCISE_VERSION_IMMUTABLE" in SQL
    assert "EXERCISE_VERSION_NOT_PENDING" in SQL
    assert "BEFORE UPDATE ON public.diagnostic_exercise_version" in SQL


def test_additive_idempotent_and_browser_roles_reach_nothing():
    upper = SQL.upper()
    for forbidden in ("DROP TABLE", "DELETE FROM", "UPDATE PUBLIC.DIAGNOSTIC_EXERCISE ",
                      "TRUNCATE"):
        assert forbidden not in upper
    assert "CREATE TABLE IF NOT EXISTS" in SQL and "CREATE OR REPLACE FUNCTION" in SQL
    assert "DROP TRIGGER IF EXISTS" in SQL
    assert SQL.count("FROM PUBLIC, anon, authenticated") >= 3
    assert "ENABLE ROW LEVEL SECURITY" in SQL
