"""The ledger keeps its weeks, executed on a disposable database (0404).
Founder 2026-09-30, C9, L4 to L7. Pins:
  * one ledger snapshot per ISO week (a second write on the same week
    conflicts, so the job upserts on week_start);
  * a golden judgement is one per (surface, moment, judge) and takes only
    the five answers;
  * a surface's golden set seals once;
  * every new table has RLS on and reaches no browser role.
"""
from __future__ import annotations

import os
import uuid

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

TABLES = ("ledger_snapshots", "research_users", "golden_judgements", "golden_sets")


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


def _row(db, sql, args=()):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, args)
        got = cur.fetchone()
        return dict(got) if got else None


def _exec(db, sql, args=()):
    with db.cursor() as cur:
        cur.execute(sql, args)


def _refused(db, sql, args=()):
    """The constraint refuses it: an integrity error, never a fetch error."""
    with pytest.raises(psycopg2.IntegrityError):
        _exec(db, sql, args)


def test_one_snapshot_per_week(db):
    week = "2099-01-04"
    first = _row(db, "INSERT INTO public.ledger_snapshots (week_start, ledger_version, snapshot) "
                     "VALUES (%s, 'learning-ledger-v1', '{\"a\": 1}'::jsonb) RETURNING id", (week,))
    _refused(db, "INSERT INTO public.ledger_snapshots (week_start, ledger_version, snapshot) "
                 "VALUES (%s, 'learning-ledger-v1', '{}'::jsonb)", (week,))
    replaced = _row(db, "INSERT INTO public.ledger_snapshots (week_start, ledger_version, snapshot) "
                        "VALUES (%s, 'learning-ledger-v1', '{\"a\": 2}'::jsonb) "
                        "ON CONFLICT (week_start) DO UPDATE SET snapshot = EXCLUDED.snapshot "
                        "RETURNING id, snapshot", (week,))
    assert replaced["id"] == first["id"]
    assert replaced["snapshot"] == {"a": 2}


def test_a_golden_judgement_is_one_per_moment_with_five_answers(db):
    snippet = str(uuid.uuid4())
    _exec(db, "INSERT INTO public.golden_judgements (surface, snippet_id, judge_email, value) "
              "VALUES ('confidence', %s, 'founder@example.test', 'yes')", (snippet,))
    _refused(db, "INSERT INTO public.golden_judgements (surface, snippet_id, judge_email, value) "
                 "VALUES ('confidence', %s, 'founder@example.test', 'no')", (snippet,))
    _refused(db, "INSERT INTO public.golden_judgements (surface, snippet_id, judge_email, value) "
                 "VALUES ('confidence', %s, 'founder@example.test', '7')", (str(uuid.uuid4()),))


def test_a_golden_set_seals_once(db):
    surface = f"probe-{uuid.uuid4().hex[:8]}"
    _exec(db, "INSERT INTO public.golden_sets (surface, judge_email, count, sha256) "
              "VALUES (%s, 'founder@example.test', 50, repeat('a', 64))", (surface,))
    _refused(db, "INSERT INTO public.golden_sets (surface, judge_email, count, sha256) "
                 "VALUES (%s, 'founder@example.test', 51, repeat('b', 64))", (surface,))


def test_every_new_table_has_rls_and_no_browser_grant(db):
    for table in TABLES:
        got = _row(db, "SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass",
                   (f"public.{table}",))
        assert got and got["relrowsecurity"] is True, table
        grants = _row(db, "SELECT count(*) AS n FROM information_schema.role_table_grants "
                          "WHERE table_schema = 'public' AND table_name = %s "
                          "AND grantee IN ('anon', 'authenticated')", (table,))
        assert grants["n"] == 0, table
