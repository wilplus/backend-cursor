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
    {"pick_probability": 0.5},
    {"pick_probability": "1"},
    {"lane": None},
    {"block_id": None},
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
                       match="universal-v3 pick log does not match the inventory"):
        _write(cur, seed, frame)


def test_an_entry_without_its_lane_is_refused(cur):
    """GPT-0441 blocker: a missing lane made the NOT IN check unknown."""
    seed = _fresh(cur)
    frame = copy.deepcopy(seed["frame"])
    _first_eligible(frame).pop("lane")
    with pytest.raises(psycopg2.errors.RaiseException,
                       match="invalid universal-v3 pick log"):
        _write(cur, seed, frame)


def _mismatch(cur, mutate):
    seed = _fresh(cur)
    frame = copy.deepcopy(seed["frame"])
    mutate(frame)
    with pytest.raises(psycopg2.errors.RaiseException,
                       match="universal-v3 pick log does not match the inventory"):
        _write(cur, seed, frame)


def test_a_dropped_or_doubled_entry_is_refused(cur):
    _mismatch(cur, lambda f: f["pick_log"]["candidates"].pop())
    cur.connection.rollback()
    _mismatch(cur, lambda f: f["pick_log"]["candidates"].append(
        copy.deepcopy(f["pick_log"]["candidates"][0])))


def test_a_selection_bound_to_another_block_is_refused(cur):
    """GPT-0441 blocker: a chance-1 row must sit under its own block."""
    def move(frame):
        blocks = [b["block_id"] for b in frame["blocks"]]
        assert len(set(blocks)) > 1, "fixture needs two blocks"
        selected = frame["blocks"][0]["selected_candidate_id"]
        for entry in frame["pick_log"]["candidates"]:
            if entry["candidate_id"] == selected:
                entry["block_id"] = blocks[1]
    _mismatch(cur, move)


def test_a_verbal_selection_must_be_logged_at_chance_one(cur):
    seed = _fresh(cur)
    frame = copy.deepcopy(seed["frame"])
    picked = [(lane, cid) for lane in ("rewrite_clarity", "great_formulation")
              for cid in frame["verbal_lanes"][lane]["selected_candidate_ids"]]
    if not picked:
        pytest.skip("fixture selects no verbal candidate")
    lane, cid = picked[0]
    for entry in frame["pick_log"]["candidates"]:
        if entry["lane"] == lane and entry["candidate_id"] == cid:
            entry["pick_probability"] = 0.0
    with pytest.raises(psycopg2.errors.RaiseException,
                       match="universal-v3 pick log does not match the inventory"):
        _write(cur, seed, frame)


def test_the_seed_must_be_the_takes_own(cur):
    seed = _fresh(cur)
    frame = copy.deepcopy(seed["frame"])
    frame["pick_log"]["seed"] = str(int(frame["pick_log"]["seed"]) ^ 1)
    with pytest.raises(psycopg2.errors.RaiseException,
                       match="invalid universal-v3 pick log"):
        _write(cur, seed, frame)


def test_the_v5_frame_is_refused_now(cur):
    seed = _fresh(cur)
    frame = {**seed["frame"],
             "frame_schema_version": "take-feedback-policy-v3-frame-v5"}
    with pytest.raises(psycopg2.errors.RaiseException,
                       match="invalid universal-v3 dark frame"):
        _write(cur, seed, frame)


def _first_verbal_lane(frame):
    for lane in ("rewrite_clarity", "great_formulation"):
        if frame["verbal_lanes"][lane]["candidates"]:
            return lane
    raise AssertionError("fixture has no verbal candidate")


def _drop_confidence_id(frame):
    frame["blocks"][0]["confidence_candidates"][0].pop("candidate_id")


def _drop_verbal_id(frame):
    lane = _first_verbal_lane(frame)
    frame["verbal_lanes"][lane]["candidates"][0]["candidate_id"] = None


@pytest.mark.parametrize("mutate", [
    # GPT-0441 review 2: each of these raised "cannot extract elements"
    # (or let `?` read an object's keys) instead of being refused.
    lambda f: f.update(blocks={}),
    lambda f: f.update(blocks=None),
    lambda f: f.update(blocks="blocks"),
    lambda f: f["blocks"].append("not a block"),
    lambda f: f["blocks"][0].update(confidence_candidates="candidates"),
    lambda f: f["blocks"][0].update(confidence_candidates={}),
    lambda f: f["verbal_lanes"]["rewrite_clarity"].update(candidates={}),
    lambda f: f["verbal_lanes"]["great_formulation"].update(candidates=7),
    lambda f: f["verbal_lanes"]["rewrite_clarity"].update(
        selected_candidate_ids={}),
    lambda f: f["verbal_lanes"]["great_formulation"].update(
        selected_candidate_ids="best-praise"),
    lambda f: f["blocks"][0]["confidence_candidates"].append("not a row"),
    # An inventory candidate without its id is refused, not left out.
    _drop_confidence_id,
    _drop_verbal_id,
], ids=[
    "blocks-object", "blocks-json-null", "blocks-string", "block-scalar",
    "confidence-candidates-string", "confidence-candidates-object",
    "verbal-candidates-object", "verbal-candidates-number",
    "selected-ids-object", "selected-ids-string", "confidence-row-scalar",
    "confidence-candidate-no-id", "verbal-candidate-no-id",
])
def test_a_malformed_inventory_is_refused_cleanly(cur, mutate):
    seed = _fresh(cur)
    frame = copy.deepcopy(seed["frame"])
    mutate(frame)
    with pytest.raises(psycopg2.errors.RaiseException,
                       match="invalid universal-v3 pick log"):
        _write(cur, seed, frame)


def test_an_absent_inventory_key_reads_as_empty_as_0431_reads_it(cur):
    """Absent `selected_candidate_ids` is an empty list, not a malformed
    shape; the log then disagrees with the inventory and says so."""
    seed = _fresh(cur)
    frame = copy.deepcopy(seed["frame"])
    picked = [lane for lane in ("rewrite_clarity", "great_formulation")
              if frame["verbal_lanes"][lane]["selected_candidate_ids"]]
    if not picked:
        pytest.skip("fixture selects no verbal candidate")
    frame["verbal_lanes"][picked[0]].pop("selected_candidate_ids")
    with pytest.raises(psycopg2.errors.RaiseException,
                       match="universal-v3 pick log does not match the inventory"):
        _write(cur, seed, frame)


def test_a_chance_is_compared_as_a_number(cur):
    """GPT-0441 review 2: 1 and 1.0 (and 0 and 0.0) are the same chance."""
    seed = _fresh(cur)
    frame = copy.deepcopy(seed["frame"])
    for entry in frame["pick_log"]["candidates"]:
        if entry["pick_probability"] is not None:
            entry["pick_probability"] = int(entry["pick_probability"])
    assert _write(cur, seed, frame)["outcome"] == "stored"
