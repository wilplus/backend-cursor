"""A coach answers in words too, executed on a disposable database (0402).
Founder 2026-09-30, C2 to C5. Pins:
  * resolve_exercise_coach_request_v2 records a line or a clearer version
    with its answer, once, and shares it like an exercise;
  * words and an exercise never mix on one resolution; no_safe_match takes
    neither; v1 still resolves an exercise as before;
  * feedback_pairs keeps only a differing (draft, final) with its coach, one
    per (surface, request), and reaches no browser role;
  * coach_moment_error_event takes a naming keyed by the moment alone.
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


def _row(db, sql, args=()):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, args)
        got = cur.fetchone()
        return dict(got) if got else None


def _request(db):
    return _row(db,
                "SELECT * FROM public.request_exercise_from_coach_v1("
                "%s, %s, %s, 'nothing_spotted', 'near_confident', "
                "%s::text[], %s::jsonb)",
                (str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()),
                 [], psycopg2.extras.Json({"signals": {}})))


def _resolve_v2(db, request_id, resolution, *, exercise_id=None, version=None,
                share=False, answer=None):
    return _row(db,
                "SELECT * FROM public.resolve_exercise_coach_request_v2("
                "%s, 'coach-1', %s, %s, %s, %s, %s)",
                (request_id, resolution, exercise_id, version, share, answer))


def _refused(db, code, fn, *args, **kwargs):
    with pytest.raises(psycopg2.Error) as caught:
        fn(db, *args, **kwargs)
    assert code in str(caught.value)


def test_a_line_is_answered_once_and_shared(db):
    req = _request(db)
    done = _resolve_v2(db, req["id"], "line_written",
                       answer="  You let the number land.  ", share=True)
    assert done["resolution"] == "line_written"
    assert done["answer_text"] == "You let the number land."
    assert done["resolved_exercise_id"] is None
    assert done["shared_at"] is not None
    again = _resolve_v2(db, req["id"], "line_written",
                        answer="You let the number land.")
    assert again["shared_at"] == done["shared_at"]
    _refused(db, "EXERCISE_COACH_REQUEST_ALREADY_RESOLVED", _resolve_v2,
             req["id"], "line_written", answer="Different words.")
    _refused(db, "EXERCISE_COACH_REQUEST_ALREADY_RESOLVED", _resolve_v2,
             req["id"], "version_written", answer="You let the number land.")
