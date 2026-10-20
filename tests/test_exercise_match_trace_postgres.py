"""
STORY    As the founder, I want every exercise draw to write one frozen trace
         of why it was chosen, so that later analysis cannot be faked by
         recomputing.
OUTCOME
  O1  The call that draws writes exactly one trace beside the assignment.
  O2  A replay returns the frozen choice and writes nothing: the first
      trace stays, byte for byte.
  O3  A trace whose ranked list is not the drawn pool is refused, and the
      draw with it.
  O4  A trace cannot be updated, and erasing the assignment erases it.
PROVES   O1 -> test_the_draw_writes_one_trace_beside_it
         O2 -> test_a_replay_writes_nothing
         O3 -> test_a_trace_that_disagrees_with_the_pool_refuses_the_draw
         O4 -> test_a_trace_is_immutable_and_goes_with_its_draw
WHY      Founder 2026-09-28, step 2 of the exercise routing plan (0384).
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


def _count(db, sql, args):
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()[0]


def test_a_replay_writes_nothing(db):
    take, snippet = str(uuid.uuid4()), str(uuid.uuid4())
    first = _assign(db, _pool("a", "b"), _trace(["a", "b"]), take, snippet)
    original = _traces(db, first["id"])
    replay_trace = {**_trace(["a", "b"], ["c"], fit="trial"),
                    "observed_tags": ["mumbling"]}
    again = _assign(db, _pool("a", "b"), replay_trace, take, snippet)
    assert again["id"] == first["id"]
    assert _traces(db, first["id"]) == original


def test_a_trace_that_disagrees_with_the_pool_refuses_the_draw(db):
    take, snippet = str(uuid.uuid4()), str(uuid.uuid4())
    with pytest.raises(psycopg2.Error, match="CV_EXERCISE_MATCH_TRACE_DISAGREES_WITH_POOL"):
        _assign(db, _pool("a", "b"), _trace(["b", "a"]), take, snippet)
    assert _count(db, "SELECT count(*) FROM public.confident_voice_exercise_assignments "
                      "WHERE take_session_id = %s AND snippet_id = %s",
                  (take, snippet)) == 0


def test_a_trace_is_immutable_and_goes_with_its_draw(db):
    row = _assign(db, _pool("a", "b"), _trace(["a", "b"]))
    with db.cursor() as cur:
        with pytest.raises(psycopg2.Error, match="CV_EXERCISE_MATCH_TRACE_IMMUTABLE"):
            cur.execute("UPDATE public.confident_voice_exercise_match_traces "
                        "SET fit = 'trial' WHERE assignment_id = %s", (row["id"],))
        cur.execute("DELETE FROM public.confident_voice_exercise_assignments "
                    "WHERE id = %s", (row["id"],))
    assert _traces(db, row["id"]) == []
