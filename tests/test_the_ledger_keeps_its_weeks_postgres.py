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


def _exec(db, sql, args=()):
    with db.cursor() as cur:
        cur.execute(sql, args)


def _refused(db, sql, args=()):
    """The constraint refuses it: an integrity error, never a fetch error."""
    with pytest.raises(psycopg2.IntegrityError):
        _exec(db, sql, args)


def test_a_golden_set_seals_once(db):
    surface = f"probe-{uuid.uuid4().hex[:8]}"
    _exec(db, "INSERT INTO public.golden_sets (surface, judge_email, count, sha256) "
              "VALUES (%s, 'founder@example.test', 50, repeat('a', 64))", (surface,))
    _refused(db, "INSERT INTO public.golden_sets (surface, judge_email, count, sha256) "
                 "VALUES (%s, 'founder@example.test', 51, repeat('b', 64))", (surface,))
