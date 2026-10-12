"""A moment opens before it is judged, on a disposable database (0408, F1).

Pins: the three columns and their checks exist on exercise_coach_requests,
the moment_events table exists with its once-per-event key, the v3 request
function records where the request rose and stays insert-once, and the
migration is idempotent (the rehearsal applies it twice).
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
        with pytest.raises(psycopg2.errors.RaiseException):
            cur.execute(
                "SELECT * FROM public.request_exercise_from_coach_v3("
                "'owner', %s, %s, 'nothing_spotted', 'rewrite', 'elsewhere', NULL, "
                "ARRAY[]::text[], '{}'::jsonb)", (take, snip))
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("UPDATE public.exercise_coach_requests SET answer_kind = 'maybe' "
                        "WHERE take_session_id = %s", (take,))
