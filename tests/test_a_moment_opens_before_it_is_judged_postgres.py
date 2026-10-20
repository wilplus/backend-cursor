"""
STORY    As a coach, I want to know whether a speaker's request came from the
         open moment or from a judgement, recorded once, so that I answer in
         the right context.
OUTCOME
  O1  request_exercise_from_coach_v3 records raised_on; a repeat on the same
      moment keeps the first request.
  O2  A raised_on outside judgement/open is refused by name
      (EXERCISE_COACH_REQUEST_INPUT_INVALID).
  O3  Opening a moment is logged once: the app's writer
      (DatabaseService.record_moment_event) reports True the first time and
      False on a repeat, and one row is stored.
PROVES   O1, O2 -> test_v3_records_where_the_request_rose_and_stays_insert_once
         O3     -> test_opening_a_moment_is_logged_once
WHY      Migration 0408 (F1). Runs only on a disposable database whose name
         starts with willab_confident_moment_.
"""
from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

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


def test_v3_records_where_the_request_rose_and_stays_insert_once(db):
    take, snip = f"take-{uuid.uuid4().hex[:8]}", f"snip-{uuid.uuid4().hex[:8]}"
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM public.request_exercise_from_coach_v3("
            "'owner', %s, %s, 'nothing_targets_it', 'error', 'open', NULL, "
            "ARRAY['rushing'], '{}'::jsonb)", (take, snip))
        first = cur.fetchone()
        cur.execute(
            "SELECT * FROM public.request_exercise_from_coach_v3("
            "'owner', %s, %s, 'nothing_spotted', 'rewrite', 'judgement', NULL, "
            "ARRAY[]::text[], '{}'::jsonb)", (take, snip))
        second = cur.fetchone()
    assert (first["kind"], first["raised_on"], first["answer_kind"]) == ("error", "open", None)
    assert second["id"] == first["id"] and second["raised_on"] == "open"
    with db.cursor() as cur:
        with pytest.raises(psycopg2.errors.RaiseException,
                           match="EXERCISE_COACH_REQUEST_INPUT_INVALID"):
            cur.execute(
                "SELECT * FROM public.request_exercise_from_coach_v3("
                "'owner', %s, %s, 'nothing_spotted', 'rewrite', 'elsewhere', NULL, "
                "ARRAY[]::text[], '{}'::jsonb)", (f"take-{uuid.uuid4().hex[:8]}", snip))


class _MomentEvents:
    """The PostgREST upsert(ignore_duplicates=True) record_moment_event makes,
    as SQL: the row comes back only when this call inserted it."""

    def __init__(self, conn):
        self.conn, self.row = conn, None

    def upsert(self, row, on_conflict, ignore_duplicates):
        assert ignore_duplicates and on_conflict == "take_session_id,snippet_id,event"
        self.row = row
        return self

    def execute(self):
        row = self.row
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO public.moment_events (owner_user_id, take_session_id, "
                "snippet_id, event, co_exposed) VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (take_session_id, snippet_id, event) DO NOTHING RETURNING id",
                (row["owner_user_id"], row["take_session_id"], row["snippet_id"],
                 row["event"], psycopg2.extras.Json(row["co_exposed"])))
            return SimpleNamespace(data=[dict(r) for r in cur.fetchall()])


def test_opening_a_moment_is_logged_once(db):
    from services.db import DatabaseService
    service = DatabaseService.__new__(DatabaseService)
    service.client = SimpleNamespace(table=lambda _name: _MomentEvents(db))
    take, snip = f"take-{uuid.uuid4().hex[:8]}", f"snip-{uuid.uuid4().hex[:8]}"
    opened = dict(owner_user_id="owner", take_session_id=take, snippet_id=snip,
                  event="opened", co_exposed={})
    assert service.record_moment_event(**opened) is True
    assert service.record_moment_event(**opened) is False
    # A skip on the same moment is its own event, not a repeat of the open.
    assert service.record_moment_event(**{**opened, "event": "skipped"}) is True
    with db.cursor() as cur:
        cur.execute("SELECT event, count(*) FROM public.moment_events "
                    "WHERE take_session_id = %s GROUP BY event ORDER BY event", (take,))
        assert cur.fetchall() == [("opened", 1), ("skipped", 1)]
