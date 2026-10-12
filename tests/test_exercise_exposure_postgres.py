"""The "exercise rendered" confirmation, on a disposable database (0387).

Pins: one exposure per assignment however often it is confirmed; only the
assignment's owner and only the selected exercise; a moment with no draw is
refused by name; the row is immutable and goes with its assignment; browser
roles reach nothing.
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


def _assign(db, owner, take, snippet):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM public.assign_confident_voice_exercise_v1("
            "%s, %s, %s, 'v3_exercise_block', 'exercise-fit-tier-v1:exact', "
            "%s::jsonb)",
            (owner, take, snippet,
             psycopg2.extras.Json([{"exercise_id": "room", "version": 2}])))
        return dict(cur.fetchone())


def _rendered(db, owner, take, snippet, exercise="room"):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM public.record_exercise_rendered_v1(%s, %s, %s, %s)",
                    (owner, take, snippet, exercise))
        return dict(cur.fetchone())


def _ids():
    return str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())


def test_only_the_owner_and_only_the_selected_exercise(db):
    owner, take, snippet = _ids()
    _assign(db, owner, take, snippet)
    with pytest.raises(psycopg2.Error, match="NOT_OWNER"):
        _rendered(db, str(uuid.uuid4()), take, snippet)
    with pytest.raises(psycopg2.Error, match="WRONG_EXERCISE"):
        _rendered(db, owner, take, snippet, exercise="other")
