"""
STORY    As a coach, I want to answer a speaker's request with a written line
         or clearer version, recorded once and shared, so that the speaker
         gets words from me.
OUTCOME
  O1  A line is recorded once, trimmed, and shared; the same answer again is
      a no-op; a different answer is refused (ALREADY_RESOLVED).
  O2  Words and an exercise never mix on one answer: either way round is
      refused (INPUT_INVALID) and the request stays unanswered.
  O3  feedback_pairs keeps a (draft, final) only when they differ, and one
      per (surface, request).
PROVES   O1 -> test_a_line_is_answered_once_and_shared
         O2 -> test_words_and_an_exercise_never_mix
         O3 -> test_a_pair_is_kept_only_when_the_coach_changed_the_draft
WHY      Migration 0402 (founder 2026-09-30, C2 to C5). Runs only on a
         disposable database whose name starts with willab_confident_moment_.
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


def test_words_and_an_exercise_never_mix(db):
    req = _request(db)
    _refused(db, "EXERCISE_COACH_REQUEST_INPUT_INVALID", _resolve_v2,
             req["id"], "line_written", answer="You let it land.",
             exercise_id="ex-1", version=1)
    _refused(db, "EXERCISE_COACH_REQUEST_INPUT_INVALID", _resolve_v2,
             req["id"], "exercise_chosen", answer="You let it land.",
             exercise_id="ex-1", version=1)
    still = _row(db, "SELECT resolution, answer_text, resolved_exercise_id "
                     "FROM public.exercise_coach_requests WHERE id = %s", (req["id"],))
    assert still == {"resolution": None, "answer_text": None, "resolved_exercise_id": None}


def _pair(db, request_id, draft, final):
    return _row(db, "INSERT INTO public.feedback_pairs "
                    "(surface, draft_text, final_text, coach_id, request_id) "
                    "VALUES ('clearer_version', %s, %s, 'coach-1', %s) RETURNING id",
                (draft, final, request_id))


def test_a_pair_is_kept_only_when_the_coach_changed_the_draft(db):
    req = _request(db)
    with pytest.raises(psycopg2.errors.CheckViolation):
        _pair(db, req["id"], "Say it slower.", "  Say it slower. ")
    assert _pair(db, req["id"], "Say it slower.", "Let the number land.")["id"]
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _pair(db, req["id"], "Say it slower.", "Another final.")
    pairs = _row(db, "SELECT count(*) AS n FROM public.feedback_pairs "
                     "WHERE request_id = %s", (req["id"],))
    assert pairs["n"] == 1
