"""
STORY    As the founder, I want coach-written words to be usable for training
         only through the listed model keys, so that nothing unlisted is
         promoted.
OUTCOME
  O1  The promote RPC accepts the two coach-word keys, refuses an unlisted
      key, and no browser role can call it.
  O2  The four door tables accept both coach-word surfaces; both aliases map
      to coach_comment_generation; the drafter's snapshot columns are
      nullable.
  O3  Applying the file again changes nothing.
PROVES   O1 -> test_the_promote_rpc_accepts_only_the_listed_keys
         O2 -> test_the_doors_hold_the_coach_words
         O3 -> test_applying_the_file_again_changes_nothing
WHY      0459 (the_coach_s_words_reach_the_doors.sql), Privacy/Terms 3.5, N68.
         Runs on the released lane, which has no runtime_config: the test
         creates it (0051) and re-applies 0459 inside a rolled-back
         transaction.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import psycopg2
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
COACH_WORDS = ("coach_moment_line", "coach_take_word")
DOORS = ("pair_releases", "fine_tune_runs", "evaluation_reports", "model_promotions")


@pytest.fixture
def cur():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cursor:
            yield cursor
    finally:
        conn.rollback()
        conn.close()


def _apply(cur, name):
    """Run a migration inside the test's transaction (its BEGIN/COMMIT cut)."""
    lines = (MIGRATIONS / name).read_text().splitlines()
    cur.execute("\n".join(line for line in lines if line not in ("BEGIN;", "COMMIT;")))


def _state(cur):
    cur.execute("SELECT conrelid::regclass::text, pg_get_constraintdef(oid) "
                "FROM pg_constraint WHERE conname = ANY(%s) ORDER BY 1",
                ([f"{door}_surface_check" for door in DOORS],))
    checks = cur.fetchall()
    cur.execute("SELECT alias, learning_surface_id FROM public.ml_learning_surface_aliases "
                "WHERE alias = ANY(%s) ORDER BY 1", (list(COACH_WORDS),))
    aliases = cur.fetchall()
    # 0459's two drafter columns. Later tables that keep a draft's prompt too
    # (the Take word's version history) are theirs to test, not this file's.
    cur.execute("SELECT table_name, is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = 'draft_prompt' "
                "AND table_name IN ('coach_take_words', 'exercise_coach_requests') ORDER BY 1")
    return checks, aliases, cur.fetchall()


def test_the_promote_rpc_accepts_only_the_listed_keys(cur):
    _apply(cur, "add_runtime_model_config.sql")
    _apply(cur, "the_coach_s_words_reach_the_doors.sql")
    meta = json.dumps({"prompt_lock_sha256": hashlib.sha256(b"lock").hexdigest()})
    promote = "SELECT public.promote_runtime_surface_model_v1(%s, %s, %s, %s::jsonb)"
    for surface in COACH_WORDS:
        cur.execute(promote, (f"openai_surface_model_{surface}", "ft:w", "test", meta))
        assert cur.fetchone()[0]["value"] == "ft:w"
    cur.execute("SAVEPOINT refused")
    with pytest.raises(psycopg2.Error) as refused:
        cur.execute(promote, ("openai_surface_model_coach_note_v9", "ft:w", "test", meta))
    cur.execute("ROLLBACK TO SAVEPOINT refused")
    assert "RUNTIME_MODEL_KEY_NOT_ENUMERATED" in str(refused.value)
    for role in ("anon", "authenticated"):
        cur.execute("SELECT has_function_privilege(%s, "
                    "'public.promote_runtime_surface_model_v1(text, text, text, jsonb)', "
                    "'EXECUTE')", (role,))
        assert cur.fetchone()[0] is False


def test_the_doors_hold_the_coach_words(cur):
    checks, aliases, columns = _state(cur)
    assert [table for table, _ in checks] == sorted(DOORS)
    for _table, definition in checks:
        assert all(f"'{surface}'" in definition for surface in COACH_WORDS)
    assert aliases == [(alias, "coach_comment_generation") for alias in COACH_WORDS]
    assert columns == [("coach_take_words", "YES"), ("exercise_coach_requests", "YES")]


def test_applying_the_file_again_changes_nothing(cur):
    before = _state(cur)
    _apply(cur, "the_coach_s_words_reach_the_doors.sql")
    assert _state(cur) == before
