"""A practice remembers where it landed, on a disposable database (0407, F7).

Pins: the column exists, is nullable, and takes an integer; the migration is
idempotent (the rehearsal applies it twice).
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


def test_the_column_is_a_nullable_integer(db):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'confident_voice_practice' "
            "AND column_name = 'landed_attempt_index'")
        row = cur.fetchone()
    assert row is not None
    assert (row["data_type"], row["is_nullable"]) == ("integer", "YES")
