"""
STORY    As the founder, I want one ledger snapshot per week and a golden set
         that seals once, so that the model quality record cannot be
         rewritten.
OUTCOME
  O1  A second snapshot for the same week is refused (the job upserts).
  O2  A golden judgement is one per (surface, moment, judge) and takes only
      the five answers.
  O3  A surface's golden set seals once.
  O4  Every new table has RLS on and no policy, so no browser role reads it.
PROVES   O1 -> test_one_snapshot_per_week
         O2 -> test_a_golden_judgement_takes_one_of_five_answers_once
         O3 -> test_a_golden_set_seals_once
         O4 -> test_no_browser_reaches_the_ledger
WHY      0404 (the_ledger_keeps_its_weeks.sql), founder 2026-09-30, C9, L4-L7.
         Runs on the released lane; every write is rolled back.
"""
from __future__ import annotations

import os
import uuid

import psycopg2
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)
TABLES = ("ledger_snapshots", "research_users", "golden_judgements", "golden_sets")


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


def _refused(cur, sql, args=()):
    """The constraint refuses it: an integrity error, never a fetch error."""
    cur.execute("SAVEPOINT refused")
    with pytest.raises(psycopg2.IntegrityError):
        cur.execute(sql, args)
    cur.execute("ROLLBACK TO SAVEPOINT refused")


def test_one_snapshot_per_week(cur):
    week = "1999-01-04"
    insert = ("INSERT INTO public.ledger_snapshots (week_start, ledger_version, snapshot) "
              "VALUES (%s, 'probe', '{}'::jsonb)")
    cur.execute(insert, (week,))
    _refused(cur, insert, (week,))


def test_a_golden_judgement_takes_one_of_five_answers_once(cur):
    moment = f"probe-{uuid.uuid4().hex[:8]}"
    insert = ("INSERT INTO public.golden_judgements (surface, snippet_id, judge_email, value) "
              "VALUES ('probe', %s, 'founder@example.test', %s)")
    for answer in ("yes", "in_between", "no", "not_sure", "audio_unclear"):
        cur.execute(insert, (f"{moment}-{answer}", answer))
    _refused(cur, insert, (f"{moment}-x", "maybe"))
    _refused(cur, insert, (f"{moment}-yes", "no"))


def test_a_golden_set_seals_once(cur):
    surface = f"probe-{uuid.uuid4().hex[:8]}"
    cur.execute("INSERT INTO public.golden_sets (surface, judge_email, count, sha256) "
                "VALUES (%s, 'founder@example.test', 50, repeat('a', 64))", (surface,))
    _refused(cur, "INSERT INTO public.golden_sets (surface, judge_email, count, sha256) "
                  "VALUES (%s, 'founder@example.test', 51, repeat('b', 64))", (surface,))


def test_no_browser_reaches_the_ledger(cur):
    cur.execute("SELECT relname, relrowsecurity FROM pg_class "
                "WHERE relnamespace = 'public'::regnamespace AND relname = ANY(%s)",
                (list(TABLES),))
    assert dict(cur.fetchall()) == {table: True for table in TABLES}
    cur.execute("SELECT tablename FROM pg_policies "
                "WHERE schemaname = 'public' AND tablename = ANY(%s)", (list(TABLES),))
    assert cur.fetchall() == []
