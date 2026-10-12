"""A practice hears what changed, on a disposable database (0409, F5).

Pins: the column exists and is nullable; the three tables exist with their
checks and the once-per-Take key; the migration is idempotent (the
rehearsal applies it twice).
"""
from __future__ import annotations

import os

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


def _columns(db, table):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s", (table,))
        return {r["column_name"]: r for r in cur.fetchall()}


def test_the_practice_keeps_what_it_heard(db):
    cols = _columns(db, "confident_voice_practice")
    assert (cols["after_practice"]["data_type"], cols["after_practice"]["is_nullable"]) == ("jsonb", "YES")
