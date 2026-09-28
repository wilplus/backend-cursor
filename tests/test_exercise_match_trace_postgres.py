"""Why an exercise was chosen, executed on a disposable database (0384).

Founder 2026-09-28, step 2 of the exercise routing plan. Pins what makes the
trace trustworthy later:

  * the call that draws writes exactly one trace beside the assignment;
  * a replay returns the frozen choice and writes nothing, so a trace can
    never be recomputed afterwards and passed off as the original;
  * a trace whose ranked candidates are not the pool that was drawn from is
    refused, and so is the draw with it;
  * a trace cannot be updated, browser roles reach nothing, the server reaches
    the function (to write) and the table (to read and erase), and erasing
    the assignment erases its trace.
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


def _pool(*ids):
    return [{"exercise_id": i, "version": 1} for i in ids]


def _trace(ranked, excluded=(), fit="exact"):
    candidates = [{"exercise_id": e, "outcome": "ranked", "rank": i}
                  for i, e in enumerate(ranked, start=1)]
    candidates += [{"exercise_id": e, "outcome": "excluded", "rank": None,
                    "reason": "targets_nothing_that_fired"} for e in excluded]
    return {"trace_schema": "exercise-match-trace-v1", "fit": fit,
            "candidates": candidates, "observed_tags": ["rushing"],
            "signals": {"insufficient_pauses": True}, "vocabulary": ["rushing"]}


def _assign(db, pool, trace, take=None, snippet=None, policy=None):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM public.assign_confident_voice_exercise_v2("
            "%s, %s, %s, 'v3_exercise_block', %s, %s::jsonb, %s::jsonb)",
            (str(uuid.uuid4()), take or str(uuid.uuid4()),
             snippet or str(uuid.uuid4()),
             policy or "exercise-fit-tier-v1:exact",
             psycopg2.extras.Json(pool), psycopg2.extras.Json(trace)))
        return dict(cur.fetchone())


def _traces(db, assignment_id):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM public.confident_voice_exercise_match_traces "
                    "WHERE assignment_id = %s", (assignment_id,))
        return [dict(r) for r in cur.fetchall()]


def test_the_draw_writes_one_trace_beside_it(db):
    row = _assign(db, _pool("a", "b"), _trace(["a", "b"], ["c"]))
    traces = _traces(db, row["id"])
    assert len(traces) == 1
    trace = traces[0]
    assert trace["take_session_id"] == row["take_session_id"]
    assert trace["snippet_id"] == row["snippet_id"]
    assert trace["fit"] == "exact"
    assert trace["matching_policy_version"] == "exercise-fit-tier-v1:exact"
    assert len(trace["trace_sha256"]) == 64
    assert [c["exercise_id"] for c in trace["trace"]["candidates"]] == ["a", "b", "c"]


def test_a_replay_writes_nothing(db):
    take, snippet = str(uuid.uuid4()), str(uuid.uuid4())
    first = _assign(db, _pool("a", "b"), _trace(["a", "b"]), take, snippet)
    again = _assign(db, _pool("b"), _trace(["b"], fit="trial"), take, snippet)
    assert again["id"] == first["id"]
    traces = _traces(db, first["id"])
    assert len(traces) == 1
    assert traces[0]["fit"] == "exact"


def test_a_trace_that_disagrees_with_the_pool_refuses_the_draw(db):
    take = str(uuid.uuid4())
    with pytest.raises(psycopg2.Error, match="DISAGREES_WITH_POOL"):
        _assign(db, _pool("a", "b"), _trace(["b", "a"]), take)
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM public.confident_voice_exercise_assignments "
                    "WHERE take_session_id = %s", (take,))
        assert cur.fetchone()[0] == 0


def test_a_malformed_trace_is_refused(db):
    for bad in ({}, {**_trace(["a"]), "trace_schema": "other"},
                {**_trace(["a"]), "fit": "close"}):
        with pytest.raises(psycopg2.Error, match="TRACE_INPUT_INVALID"):
            _assign(db, _pool("a"), bad)


def test_an_assignment_drawn_before_traces_keeps_no_trace(db):
    take, snippet = str(uuid.uuid4()), str(uuid.uuid4())
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM public.assign_confident_voice_exercise_v1("
            "%s, %s, %s, 'v3_exercise_block', 'exercise-proximity-service-v1', "
            "%s::jsonb)", (str(uuid.uuid4()), take, snippet,
                           psycopg2.extras.Json(_pool("a"))))
        old = dict(cur.fetchone())
    again = _assign(db, _pool("a"), _trace(["a"]), take, snippet)
    assert again["id"] == old["id"]
    assert _traces(db, old["id"]) == []


def test_a_trace_is_immutable_and_goes_with_its_assignment(db):
    row = _assign(db, _pool("a"), _trace(["a"]))
    with pytest.raises(psycopg2.Error, match="IMMUTABLE"):
        with db.cursor() as cur:
            cur.execute("UPDATE public.confident_voice_exercise_match_traces "
                        "SET fit = 'trial' WHERE assignment_id = %s", (row["id"],))
    with db.cursor() as cur:
        cur.execute("DELETE FROM public.confident_voice_exercise_assignments "
                    "WHERE id = %s", (row["id"],))
    assert _traces(db, row["id"]) == []


def test_browser_roles_reach_nothing_and_the_server_only_reads_and_erases(db):
    with db.cursor() as cur:
        for role in ("anon", "authenticated"):
            cur.execute("SELECT has_table_privilege(%s, "
                        "'public.confident_voice_exercise_match_traces', 'SELECT')",
                        (role,))
            assert cur.fetchone()[0] is False
            cur.execute("SELECT has_function_privilege(%s, "
                        "'public.assign_confident_voice_exercise_v2(text,text,text,"
                        "text,text,jsonb,jsonb)', 'EXECUTE')", (role,))
            assert cur.fetchone()[0] is False
        for privilege, expected in (("SELECT", True), ("DELETE", True),
                                    ("INSERT", False), ("UPDATE", False)):
            cur.execute("SELECT has_table_privilege('service_role', "
                        "'public.confident_voice_exercise_match_traces', %s)",
                        (privilege,))
            assert cur.fetchone()[0] is expected, privilege
        cur.execute("SELECT has_function_privilege('service_role', "
                    "'public.assign_confident_voice_exercise_v2(text,text,text,"
                    "text,text,jsonb,jsonb)', 'EXECUTE')")
        assert cur.fetchone()[0] is True
