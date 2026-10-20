"""
STORY    As a coach, I want each moment to raise exactly one request that never
         changes and that I resolve once, so that the speaker's moment has one
         clear record.
OUTCOME
  O1  A repeat request for the same moment returns the first row unchanged;
      what was requested cannot be edited afterwards.
  O2  Once resolved, another coach's different resolution is refused and the
      row keeps the first answer.
  O3  Only an exercise answer names an exercise: no_safe_match naming one,
      or shared, is refused.
  O4  Browser roles reach neither the table nor the request/resolve functions.
PROVES   O1 -> test_one_request_per_moment
         O2 -> test_another_coachs_different_answer_is_refused
         O3 -> test_no_safe_match_names_no_exercise_and_is_not_shared
         O4 -> test_browser_roles_reach_nothing
NOTE     The same coach changing their own answer (0446) and share-once are
         pinned in tests/test_a_coach_may_change_their_answer_postgres.py.
         Both files call the RPCs production calls: request v2 (judgement
         time) and resolve v3.
WHY      Founder 2026-09-28; contract 35b/35f (0385).
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


REQUEST = ("public.request_exercise_from_coach_v2("
           "text, text, text, text, text, text, text[], jsonb)")
RESOLVE = ("public.resolve_exercise_coach_request_v3("
           "uuid, text, text, text, integer, boolean, text, text)")


def _request(db, take=None, snippet=None, reason="nothing_targets_it",
             tags=("rushing",)):
    return _row(db,
                "SELECT * FROM public.request_exercise_from_coach_v2("
                "%s, %s, %s, %s, 'error', 'near_confident', %s::text[], %s::jsonb)",
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
    with db.cursor() as cur:
        with pytest.raises(psycopg2.Error, match="EXERCISE_COACH_REQUEST_IMMUTABLE"):
            cur.execute("UPDATE public.exercise_coach_requests "
                        "SET reason = 'nothing_spotted' WHERE id = %s", (first["id"],))


def _resolve(db, request_id, coach, resolution, *, exercise_id=None,
             version=None, share=False):
    return _row(db, "SELECT * FROM public.resolve_exercise_coach_request_v3("
                    "%s, %s, %s, %s, %s, %s, NULL, NULL)",
                (request_id, coach, resolution, exercise_id, version, share))


def test_another_coachs_different_answer_is_refused(db):
    request = _request(db)
    first = _resolve(db, request["id"], "coach-1", "exercise_chosen",
                     exercise_id="ex-1", version=1)
    assert (first["resolution"], first["resolved_exercise_id"]) == (
        "exercise_chosen", "ex-1")
    with pytest.raises(psycopg2.Error, match="EXERCISE_COACH_REQUEST_ALREADY_RESOLVED"):
        _resolve(db, request["id"], "coach-2", "no_safe_match")
    again = _request(db, request["take_session_id"], request["snippet_id"])
    assert (again["resolution"], again["resolved_by"]) == ("exercise_chosen", "coach-1")


def test_no_safe_match_names_no_exercise_and_is_not_shared(db):
    request = _request(db)
    with pytest.raises(psycopg2.Error, match="EXERCISE_COACH_REQUEST_INPUT_INVALID"):
        _resolve(db, request["id"], "coach-1", "no_safe_match",
                 exercise_id="ex-1", version=1)
    with pytest.raises(psycopg2.Error, match="EXERCISE_COACH_REQUEST_INPUT_INVALID"):
        _resolve(db, request["id"], "coach-1", "no_safe_match", share=True)
    resolved = _resolve(db, request["id"], "coach-1", "no_safe_match")
    assert resolved["resolved_exercise_id"] is None
    assert resolved["shared_at"] is None


def _one(db, sql, args):
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()[0]


def test_browser_roles_reach_nothing(db):
    for role in ("anon", "authenticated"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert _one(db, "SELECT has_table_privilege(%s, "
                            "'public.exercise_coach_requests', %s)",
                        (role, privilege)) is False, (role, privilege)
        for function in (REQUEST, RESOLVE):
            assert _one(db, "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                        (role, function)) is False, (role, function)
