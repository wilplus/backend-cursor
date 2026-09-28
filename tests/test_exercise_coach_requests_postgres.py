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


def _resolve(db, request_id, resolution, exercise_id=None, version=None,
             share=False):
    return _row(db,
                "SELECT * FROM public.resolve_exercise_coach_request_v1("
                "%s, 'coach-1', %s, %s, %s, %s)",
                (request_id, resolution, exercise_id, version, share))


def test_one_request_per_moment(db):
    take, snippet = str(uuid.uuid4()), str(uuid.uuid4())
    first = _request(db, take, snippet)
    again = _request(db, take, snippet, reason="nothing_spotted", tags=())
    assert again["id"] == first["id"]
    assert again["reason"] == "nothing_targets_it"
    assert again["observed_tags"] == ["rushing"]


def test_a_later_call_carries_the_resolution(db):
    take, snippet = str(uuid.uuid4()), str(uuid.uuid4())
    first = _request(db, take, snippet)
    _resolve(db, first["id"], "exercise_chosen", "ex-1", 1, share=True)
    again = _request(db, take, snippet)
    assert again["resolution"] == "exercise_chosen"
    assert again["resolved_exercise_id"] == "ex-1"
    assert again["shared_at"] is not None


def test_resolve_once_share_once(db):
    request = _request(db)
    resolved = _resolve(db, request["id"], "exercise_chosen", "ex-1", 1)
    assert resolved["shared_at"] is None
    # The same answer again is harmless, and may now carry the share.
    shared = _resolve(db, request["id"], "exercise_chosen", "ex-1", 1, share=True)
    assert shared["resolved_at"] == resolved["resolved_at"]
    assert shared["shared_at"] is not None
    with pytest.raises(psycopg2.Error, match="ALREADY_RESOLVED"):
        _resolve(db, request["id"], "exercise_chosen", "ex-2", 1)
    with pytest.raises(psycopg2.Error, match="ALREADY_RESOLVED"):
        _resolve(db, request["id"], "no_safe_match")


def test_only_an_exercise_can_be_shared(db):
    request = _request(db)
    with pytest.raises(psycopg2.Error, match="INPUT_INVALID"):
        _resolve(db, request["id"], "no_safe_match", share=True)
    with pytest.raises(psycopg2.Error, match="INPUT_INVALID"):
        _resolve(db, request["id"], "no_safe_match", "ex-1", 1)
    with pytest.raises(psycopg2.Error, match="INPUT_INVALID"):
        _resolve(db, request["id"], "exercise_chosen")
    done = _resolve(db, request["id"], "no_safe_match")
    assert done["resolved_exercise_id"] is None and done["shared_at"] is None


def test_what_was_requested_never_changes(db):
    request = _request(db)
    for column, value in (("reason", "'nothing_spotted'"),
                          ("observed_tags", "'{}'::text[]"),
                          ("request_trace", "'{}'::jsonb")):
        with pytest.raises(psycopg2.Error, match="IMMUTABLE"):
            with db.cursor() as cur:
                cur.execute(f"UPDATE public.exercise_coach_requests SET {column} "
                            f"= {value} WHERE id = %s", (request["id"],))


def test_a_share_is_never_unset(db):
    request = _request(db)
    _resolve(db, request["id"], "exercise_chosen", "ex-1", 1, share=True)
    with pytest.raises(psycopg2.Error, match="ALREADY_SHARED"):
        with db.cursor() as cur:
            cur.execute("UPDATE public.exercise_coach_requests SET shared_at = NULL "
                        "WHERE id = %s", (request["id"],))


def test_bad_input_is_refused(db):
    with pytest.raises(psycopg2.Error, match="INPUT_INVALID"):
        _request(db, reason="bored")
    with pytest.raises(psycopg2.Error, match="NOT_FOUND"):
        _resolve(db, str(uuid.uuid4()), "no_safe_match")


def test_who_may_do_what(db):
    with db.cursor() as cur:
        for role in ("anon", "authenticated"):
            cur.execute("SELECT has_table_privilege(%s, "
                        "'public.exercise_coach_requests', 'SELECT')", (role,))
            assert cur.fetchone()[0] is False
            for fn in ("request_exercise_from_coach_v1(text,text,text,text,text,"
                       "text[],jsonb)",
                       "resolve_exercise_coach_request_v1(uuid,text,text,text,"
                       "integer,boolean)"):
                cur.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                            (role, "public." + fn))
                assert cur.fetchone()[0] is False, (role, fn)
        for privilege, expected in (("SELECT", True), ("DELETE", True),
                                    ("INSERT", False), ("UPDATE", False)):
            cur.execute("SELECT has_table_privilege('service_role', "
                        "'public.exercise_coach_requests', %s)", (privilege,))
            assert cur.fetchone()[0] is expected, privilege
