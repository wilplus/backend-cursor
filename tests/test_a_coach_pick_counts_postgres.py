"""
STORY    As the founder, I want a coach's chosen exercise frozen once, with the
         reason it was chosen, and its showing receipted, so that what the
         speaker practises is traceable and never silently swapped.
OUTCOME
  O1  A coach pick is frozen once (a replay naming another exercise returns
      the first row) under the coach policy, with no seed and no draw.
  O2  Its match trace is stored once, with outcome coach_chosen.
  O3  Showing the card is receipted once against that frozen pick; a card
      for another exercise is refused by name.
PROVES   O1, O2 -> test_a_coach_pick_is_frozen_once_with_its_trace
         O3     -> test_showing_the_coach_pick_is_receipted_once
WHY      Migration 0398 (founder 2026-09-29, decision 3). Runs only on a
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


def _trace(exercise="coach-pick", outcome="coach_chosen", fit=None, count=1):
    candidates = [{"exercise_id": exercise, "version": 3, "outcome": outcome,
                   "rank": 1, "main_targets": ["rushing"],
                   "secondary_targets": ["ending_compression"]}] * count
    return {"trace_schema": "exercise-match-trace-v1", "lane": "coach_request",
            "fit": fit, "matching_policy_version": "exercise-coach-request-v1",
            "signal_rules_version": "cv-exercise-signals-v1",
            "observed_tags": ["rushing"], "source_id": "req-1",
            "candidates": candidates}


def _coach(db, owner, take, snippet, *, lane="coach_request",
           exercise="coach-pick", version=3, trace=None):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM public.assign_coach_shared_exercise_v1("
            "%s, %s, %s, %s, 'exercise-coach-request-v1', %s, %s, %s::jsonb)",
            (owner, take, snippet, lane, exercise, version,
             psycopg2.extras.Json(trace if trace is not None else _trace())))
        return dict(cur.fetchone())


def _ids():
    return str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())


def test_a_coach_pick_is_frozen_once_with_its_trace(db):
    owner, take, snippet = _ids()
    first = _coach(db, owner, take, snippet)
    # A replay naming another pick (with a trace consistent with it) is a
    # no-op: the first freeze stands.
    again = _coach(db, owner, take, snippet, exercise="other", version=9,
                   trace=_trace(exercise="other"))
    assert first["id"] == again["id"]
    assert first["exposure_policy_version"] == "exercise-coach-shared-v1"
    assert first["selection_mode"] == "coach_chosen"
    assert first["lane"] == "coach_request"
    assert first["selected_exercise_id"] == "coach-pick"
    assert first["selected_exercise_version"] == 3
    assert first["candidate_count"] == 1 and first["selected_rank"] == 1
    assert first["protected_seed"] is None and first["draw"] is None
    assert first["rng_algorithm_version"] == "none"
    assert first["below_minimum_probability"] is False
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM public.confident_voice_exercise_match_traces "
                    "WHERE assignment_id = %s", (first["id"],))
        rows = cur.fetchall()
    assert len(rows) == 1
    trace = rows[0]
    assert trace["fit"] is None
    assert trace["matching_policy_version"] == "exercise-coach-request-v1"
    assert trace["trace"]["candidates"][0]["outcome"] == "coach_chosen"


def _rendered(db, owner, take, snippet, exercise):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM public.record_exercise_rendered_v2(%s, %s, %s, %s)",
            (owner, take, snippet, exercise))
        return dict(cur.fetchone())


def test_showing_the_coach_pick_is_receipted_once(db):
    owner, take, snippet = _ids()
    pick = _coach(db, owner, take, snippet)
    seen = _rendered(db, owner, take, snippet, "coach-pick")
    assert seen["assignment_id"] == pick["id"]
    assert (seen["exercise_id"], seen["exercise_version"]) == ("coach-pick", 3)
    again = _rendered(db, owner, take, snippet, "coach-pick")
    assert again["id"] == seen["id"]
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM public.confident_voice_exercise_exposures "
                    "WHERE assignment_id = %s", (pick["id"],))
        assert cur.fetchone()[0] == 1
    with pytest.raises(psycopg2.errors.RaiseException,
                       match="EXERCISE_RENDERED_WRONG_EXERCISE"):
        _rendered(db, owner, take, snippet, "not-the-pick")
