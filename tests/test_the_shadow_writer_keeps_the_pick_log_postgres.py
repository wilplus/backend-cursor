"""0441: the shadow writer keeps the pick log (V4 B1.1, build plan D-ML-6).

Runs against the disposable confident-moment rehearsal cluster only. The
Take, the frame and the writer call are the 0431 suite's own, so the two
suites can never drift apart.
"""
from __future__ import annotations

import copy

import psycopg2
import pytest

from services.take_feedback_policy_v3 import PICK_LOG_VERSION
from tests import test_the_shadow_writer_accepts_the_frame_the_code_builds_postgres as base

DSN = base.DSN
_migration_body = base._migration_body
_seed_take = base._seed_take
_write = base._write

pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)


@pytest.fixture
def cur():
    yield from base.cur.__wrapped__()


def _fresh(cur):
    cur.execute(_migration_body())
    return _seed_take(cur)


def test_a_frame_with_its_pick_log_is_stored(cur):
    seed = _fresh(cur)
    assert seed["frame"]["pick_log"]["version"] == PICK_LOG_VERSION
    assert _write(cur, seed, seed["frame"])["outcome"] == "stored"
    cur.execute("SELECT frame -> 'pick_log' AS log FROM "
                "public.take_feedback_policy_v3_shadow_frames "
                "WHERE take_session_id = %s", (seed["take"],))
    assert cur.fetchone()["log"] == seed["frame"]["pick_log"]


@pytest.mark.parametrize("mutate", [
    lambda f: f.pop("pick_log"),
    lambda f: f["pick_log"].update(version="v4-pick-log-v0"),
    lambda f: f["pick_log"].update(seed_version="other"),
    lambda f: f["pick_log"].update(policy_version="other-policy"),
    lambda f: f["pick_log"].update(seed="12345678901234567"),
    lambda f: f["pick_log"].update(seed="-1"),
    lambda f: f["pick_log"].update(candidates={}),
])
def test_a_missing_or_malformed_pick_log_is_refused(cur, mutate):
    seed = _fresh(cur)
    frame = copy.deepcopy(seed["frame"])
    mutate(frame)
    with pytest.raises(psycopg2.errors.RaiseException,
                       match="invalid universal-v3 dark frame"):
        _write(cur, seed, frame)


def _first_eligible(frame):
    for entry in frame["pick_log"]["candidates"]:
        if entry["eligible"]:
            return entry
    raise AssertionError("fixture has no eligible candidate")


@pytest.mark.parametrize("change", [
    {"pick_probability": 1.5},
    {"pick_probability": -0.1},
    {"pick_probability": None},
    {"lane": "unknown_lane"},
    {"candidate_id": ""},
    {"eligible": "yes"},
])
def test_a_bad_pick_log_entry_is_refused(cur, change):
    seed = _fresh(cur)
    frame = copy.deepcopy(seed["frame"])
    _first_eligible(frame).update(change)
    with pytest.raises(psycopg2.errors.RaiseException,
                       match="invalid universal-v3 pick log"):
        _write(cur, seed, frame)


def test_a_selection_missing_from_the_log_is_refused(cur):
    seed = _fresh(cur)
    frame = copy.deepcopy(seed["frame"])
    selected = frame["blocks"][0]["selected_candidate_id"]
    for entry in frame["pick_log"]["candidates"]:
        if entry["candidate_id"] == selected:
            entry["pick_probability"] = 0.0
    with pytest.raises(psycopg2.errors.RaiseException,
                       match="universal-v3 pick log misses a selection"):
        _write(cur, seed, frame)


def test_the_v5_frame_is_refused_now(cur):
    seed = _fresh(cur)
    frame = {**seed["frame"],
             "frame_schema_version": "take-feedback-policy-v3-frame-v5"}
    with pytest.raises(psycopg2.errors.RaiseException,
                       match="invalid universal-v3 dark frame"):
        _write(cur, seed, frame)
