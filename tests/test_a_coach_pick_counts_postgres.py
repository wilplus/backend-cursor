"""0398 on a disposable database: a coach's pick is frozen once with its
trace, its render is receipted, it sits beside an 80/20 row on the same
moment, and the draw's own shape is still enforced.

Founder 2026-09-29, decision 3. The target must be a disposable local
database whose name starts with ``willab_confident_moment_``.
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


def _draw(db, owner, take, snippet):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM public.assign_confident_voice_exercise_v1("
            "%s, %s, %s, 'v3_exercise_block', 'exercise-fit-tier-v1:exact', "
            "%s::jsonb)",
            (owner, take, snippet,
             psycopg2.extras.Json([{"exercise_id": "room", "version": 2},
                                   {"exercise_id": "slow", "version": 1}])))
        return dict(cur.fetchone())


def _rendered(db, owner, take, snippet, exercise, version="v2"):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM public.record_exercise_rendered_{version}"
                    "(%s, %s, %s, %s)", (owner, take, snippet, exercise))
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


@pytest.mark.parametrize("bad", [
    _trace(outcome="ranked"),
    _trace(fit="exact"),
    _trace(count=2),
    _trace(exercise="another"),
    {"trace_schema": "exercise-match-trace-v1", "candidates": "x"},
])
def test_a_trace_that_is_not_one_coach_pick_is_refused(db, bad):
    owner, take, snippet = _ids()
    with pytest.raises(psycopg2.Error, match="CV_EXERCISE_MATCH_TRACE_INPUT_INVALID"):
        _coach(db, owner, take, snippet, trace=bad)


def test_the_lane_must_be_a_coach_lane(db):
    owner, take, snippet = _ids()
    with pytest.raises(psycopg2.Error, match="CV_EXERCISE_ASSIGNMENT_INPUT_INVALID"):
        _coach(db, owner, take, snippet, lane="v3_exercise_block")


def test_the_render_is_receipted_on_the_coach_row(db):
    owner, take, snippet = _ids()
    assignment = _coach(db, owner, take, snippet)
    seen = _rendered(db, owner, take, snippet, "coach-pick")
    again = _rendered(db, owner, take, snippet, "coach-pick")
    assert seen["id"] == again["id"]
    assert seen["assignment_id"] == assignment["id"]
    assert seen["exercise_version"] == 3
    # v1 still knows only the draw: a coach row is "not drawn" to it.
    with pytest.raises(psycopg2.Error, match="EXERCISE_RENDERED_NOT_DRAWN"):
        _rendered(db, owner, take, snippet, "coach-pick", version="v1")


def test_a_coach_row_and_a_draw_share_one_moment_and_each_is_receipted(db):
    owner, take, snippet = _ids()
    drawn = _draw(db, owner, take, snippet)
    coach = _coach(db, owner, take, snippet)
    assert drawn["id"] != coach["id"]
    seen_draw = _rendered(db, owner, take, snippet, drawn["selected_exercise_id"])
    seen_coach = _rendered(db, owner, take, snippet, "coach-pick")
    assert seen_draw["assignment_id"] == drawn["id"]
    assert seen_coach["assignment_id"] == coach["id"]
    with pytest.raises(psycopg2.Error, match="EXERCISE_RENDERED_WRONG_EXERCISE"):
        _rendered(db, owner, take, snippet, "nobody-offered-this")


def test_v2_refuses_the_wrong_owner_and_a_moment_with_nothing(db):
    owner, take, snippet = _ids()
    _coach(db, owner, take, snippet)
    with pytest.raises(psycopg2.Error, match="EXERCISE_RENDERED_NOT_OWNER"):
        _rendered(db, str(uuid.uuid4()), take, snippet, "coach-pick")
    with pytest.raises(psycopg2.Error, match="EXERCISE_RENDERED_NOT_DRAWN"):
        _rendered(db, owner, take, str(uuid.uuid4()), "coach-pick")


def test_the_draw_s_own_shape_is_still_enforced(db):
    """The widened CHECKs accept the coach shape and nothing looser."""
    owner, take, snippet = _ids()
    base = ("INSERT INTO public.confident_voice_exercise_assignments ("
            "owner_user_id, take_session_id, snippet_id, lane, "
            "exposure_policy_version, matching_policy_version, candidates, "
            "candidate_count, pool_sha256, selected_exercise_id, "
            "selected_exercise_version, selected_rank, selection_mode, "
            "rng_algorithm_version, below_minimum_probability) VALUES "
            "(%s, %s, %s, %s, %s, 'p', '[{}]'::jsonb, %s, repeat('a', 64), "
            "'x', 1, 1, %s, 'none', false)")
    with db.cursor() as cur:
        # A randomized row without a seed.
        with pytest.raises(psycopg2.Error):
            cur.execute(base, (owner, take, snippet, "v3_exercise_block",
                               "exercise-80-20-v1", 2, "top"))
        # A coach mode under the draw's policy.
        with pytest.raises(psycopg2.Error):
            cur.execute(base, (owner, take, snippet, "coach_request",
                               "exercise-80-20-v1", 1, "coach_chosen"))
        # A draw mode under the coach policy.
        with pytest.raises(psycopg2.Error):
            cur.execute(base, (owner, take, snippet, "coach_request",
                               "exercise-coach-shared-v1", 1,
                               "deterministic_singleton"))
        # An unknown lane.
        with pytest.raises(psycopg2.Error):
            cur.execute(base, (owner, take, snippet, "somewhere",
                               "exercise-coach-shared-v1", 1, "coach_chosen"))


def test_browser_roles_reach_neither_writer(db):
    with db.cursor() as cur:
        for role in ("anon", "authenticated"):
            for fn in ("public.assign_coach_shared_exercise_v1"
                       "(text,text,text,text,text,text,integer,jsonb)",
                       "public.record_exercise_rendered_v2(text,text,text,text)"):
                cur.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                            (role, fn))
                assert cur.fetchone()[0] is False, (role, fn)
