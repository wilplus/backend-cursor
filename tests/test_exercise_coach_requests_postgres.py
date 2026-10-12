"""The coach request, executed on a disposable database (0385).

Founder 2026-09-28; contract 35b/35f. Pins:

  * one request per (Take, moment): every later call returns the first row,
    unchanged, with whatever resolution it has gained;
  * what was requested never changes;
  * a resolution is recorded once (repeating the same one is harmless, a
    different one is refused), and a share once;
  * only an exercise can be shared; no_safe_match names no exercise;
  * browser roles reach nothing; the server reaches the functions (to write)
    and the table (to read and erase).
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


def _row(db, sql, args):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, args)
        return dict(cur.fetchone())


def _request(db, take=None, snippet=None, reason="nothing_targets_it",
             tags=("rushing",)):
    return _row(db,
                "SELECT * FROM public.request_exercise_from_coach_v1("
                "%s, %s, %s, %s, 'near_confident', %s::text[], %s::jsonb)",
                (str(uuid.uuid4()), take or str(uuid.uuid4()),
                 snippet or str(uuid.uuid4()), reason, list(tags),
                 psycopg2.extras.Json({"signals": {"insufficient_pauses": True}})))


def test_one_request_per_moment(db):
    take, snippet = str(uuid.uuid4()), str(uuid.uuid4())
    first = _request(db, take, snippet)
    again = _request(db, take, snippet, reason="nothing_spotted", tags=())
    assert again["id"] == first["id"]
    assert again["reason"] == "nothing_targets_it"
    assert again["observed_tags"] == ["rushing"]
