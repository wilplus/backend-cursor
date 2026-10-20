"""
STORY    As a speaker practising, I want my 4th and 10th tries saved like my
         1st, so that practice never silently stops recording.
OUTCOME
  O1  Through the app's writer (DatabaseService.
      insert_confident_voice_practice_attempt), attempts 1, 2, 3, 4 and 10
      of one practice all save.
  O2  An attempt numbered 0 is refused: the writer returns None and no row
      is stored.
PROVES   O1, O2 -> test_attempts_four_and_ten_save_and_zero_is_refused
WHY      Migration 0417 (F1 Repair Plan Phase 4; founder lock 2026-09-30, D2:
         "attempt 10 works like attempt 1"). Every write is rolled back.
"""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import psycopg2
import psycopg2.extras
import pytest
from psycopg2 import sql

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)


@pytest.fixture
def cur():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            yield cursor
    finally:
        conn.rollback()
        conn.close()


class _Insert:
    """table(name).insert(row).execute() as one INSERT ... RETURNING *, in a
    savepoint so a refused row leaves the test's transaction usable."""

    def __init__(self, cur, name):
        self.cur, self.name, self.row = cur, name, None

    def insert(self, row):
        self.row = row
        return self

    def execute(self):
        cols = list(self.row)
        self.cur.execute("SAVEPOINT attempt")
        try:
            self.cur.execute(sql.SQL("INSERT INTO public.{} ({}) VALUES ({}) RETURNING *").format(
                sql.Identifier(self.name), sql.SQL(", ").join(map(sql.Identifier, cols)),
                sql.SQL(", ").join(sql.Placeholder() * len(cols))),
                [self.row[c] for c in cols])
        except psycopg2.Error:
            self.cur.execute("ROLLBACK TO SAVEPOINT attempt")
            raise
        return SimpleNamespace(data=[dict(r) for r in self.cur.fetchall()])


def test_attempts_four_and_ten_save_and_zero_is_refused(cur):
    from services.db import DatabaseService
    service = DatabaseService.__new__(DatabaseService)
    service.client = SimpleNamespace(table=lambda name: _Insert(cur, name))
    practice = str(uuid.uuid4())
    cur.execute("INSERT INTO public.confident_voice_practice "
                "(id, owner_user_id, take_session_id) "
                "VALUES (%s, gen_random_uuid(), gen_random_uuid())", (practice,))

    def save(index):
        return service.insert_confident_voice_practice_attempt(
            {"id": str(uuid.uuid4()), "practice_id": practice, "attempt_index": index})

    for index in (1, 2, 3, 4, 10):
        assert save(index)["attempt_index"] == index
    assert save(0) is None
    cur.execute("SELECT array_agg(attempt_index ORDER BY attempt_index) AS saved "
                "FROM public.confident_voice_practice_attempt WHERE practice_id = %s",
                (practice,))
    assert cur.fetchone()["saved"] == [1, 2, 3, 4, 10]
