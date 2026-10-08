"""The coach's own words reach doors 2, 3 and 4 on a disposable database
(0459; Privacy/Terms 3.5, N68). Pins:
  * the four door tables take a row of either coach-word surface and still
    refuse an unknown surface;
  * the promote RPC accepts the two coach-word keys, still refuses an
    unlisted one, and reaches no browser role;
  * the two aliases exist under coach_comment_generation;
  * the drafter's snapshot columns exist and are nullable;
  * applying the file again changes nothing.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import date, timedelta
from pathlib import Path

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

SQL = (Path(__file__).resolve().parents[1] / "migrations"
       / "the_coach_s_words_reach_the_doors.sql").read_text(encoding="utf-8")
COACH_WORDS = ("coach_moment_line", "coach_take_word")


@pytest.fixture(scope="module")
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    try:
        yield conn
    finally:
        conn.close()


def _one(db, sql, args=()):
    with db.cursor() as cur:
        cur.execute(sql, args)
        row = cur.fetchone()
        return row[0] if row else None


def _row(db, sql, args=()):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, args)
        got = cur.fetchone()
        return dict(got) if got else None


def _week() -> str:
    return str(date(1900, 1, 1) + timedelta(days=uuid.uuid4().int % 60000))


def _release(db, surface):
    return _one(db, """
        INSERT INTO public.pair_releases (release_version, surface, week_start, item_count, storage_bucket,
            storage_key, manifest, manifest_sha256, file_sha256, signature, signing_key_id)
        VALUES ('pair-release-v1', %s, %s, 1, 'b', %s, '{}'::jsonb, repeat('a', 64), repeat('b', 64), 'sig', 'k1')
        RETURNING id""", (surface, _week(), f"pair-releases/{surface}/{uuid.uuid4()}/pairs.jsonl"))


def _run(db, surface):
    return _one(db, """
        INSERT INTO public.fine_tune_runs (run_version, surface, base_model, item_count, train_count,
            validation_count, file_sha256, owners_sha256, openai_job_id, openai_file_id)
        VALUES ('fine-tune-run-v1', %s, 'gpt-4.1-mini', 1, 1, 0, repeat('c', 64), repeat('d', 64), 'job-1', 'file-1')
        RETURNING id""", (surface,))


def _report(db, surface):
    return _one(db, """
        INSERT INTO public.evaluation_reports (report_version, surface, candidate_model, baseline_model,
            golden_sha256, golden_count, report, passed)
        VALUES ('golden-evaluation-v1', %s, 'ft:w', 'stock', repeat('e', 64), 50, '{}'::jsonb, false)
        RETURNING id""", (surface,))


def _promotion(db, surface):
    return _one(db, """
        INSERT INTO public.model_promotions (surface, candidate_model, promoted_by)
        VALUES (%s, 'ft:w', 'test') RETURNING id""", (surface,))


def test_the_door_tables_hold_both_coach_word_surfaces(db):
    for surface in COACH_WORDS:
        assert _release(db, surface)
        assert _run(db, surface)
        assert _report(db, surface)
        assert _promotion(db, surface)
    for writer in (_release, _run, _report, _promotion):
        with pytest.raises(psycopg2.errors.CheckViolation):
            writer(db, "coach_note_v9")


def test_the_promote_rpc_accepts_the_coach_word_keys(db):
    if _one(db, "SELECT to_regclass('public.runtime_config')") is None:
        pytest.skip("runtime_config absent on this rehearsal")
    meta = json.dumps({"prompt_lock_sha256": hashlib.sha256(b"lock").hexdigest()})
    for surface in COACH_WORDS:
        out = _one(db, "SELECT public.promote_runtime_surface_model_v1(%s, %s, %s, %s::jsonb)",
                   (f"openai_surface_model_{surface}", "ft:w", "test", meta))
        assert out["value"] == "ft:w"
    with pytest.raises(psycopg2.Error) as refused:
        _one(db, "SELECT public.promote_runtime_surface_model_v1(%s, %s, %s, %s::jsonb)",
             ("openai_surface_model_coach_note_v9", "ft:w", "test", meta))
    assert "RUNTIME_MODEL_KEY_NOT_ENUMERATED" in str(refused.value)
    for role in ("anon", "authenticated"):
        if _one(db, "SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)):
            assert _one(db, "SELECT has_function_privilege(%s, "
                            "'public.promote_runtime_surface_model_v1(text, text, text, jsonb)', 'EXECUTE')",
                        (role,)) is False


def test_the_aliases_and_the_snapshot_columns(db):
    for alias in COACH_WORDS:
        row = _row(db, "SELECT learning_surface_id, canonical_writes_allowed "
                       "FROM public.ml_learning_surface_aliases WHERE alias = %s", (alias,))
        assert row == {"learning_surface_id": "coach_comment_generation", "canonical_writes_allowed": True}
    for table in ("exercise_coach_requests", "coach_take_words"):
        col = _row(db, "SELECT data_type, is_nullable FROM information_schema.columns "
                       "WHERE table_schema = 'public' AND table_name = %s AND column_name = 'draft_prompt'",
                   (table,))
        assert col == {"data_type": "jsonb", "is_nullable": "YES"}, table


def test_applying_the_file_again_changes_nothing(db):
    before = _one(db, "SELECT count(*) FROM public.ml_learning_surface_aliases")
    with db.cursor() as cur:
        cur.execute(SQL)
    assert _one(db, "SELECT count(*) FROM public.ml_learning_surface_aliases") == before
    assert _release(db, "coach_take_word")
