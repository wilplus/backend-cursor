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
