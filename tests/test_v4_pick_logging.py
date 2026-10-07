"""V4 Phase 1, B1.1: the dark frame logs every pick (build plan D-ML-6).

Every candidate V3 weighed is logged with its chance of being picked, the
Take's seed and the policy version. The serving frame never carries it
(AC-9).
"""
from __future__ import annotations

import json
from pathlib import Path

from services.take_feedback_policy_v3 import (
    FRAME_SCHEMA_VERSION,
    PICK_LOG_VERSION,
    PICK_SEED_VERSION,
    POLICY_VERSION,
    build_service_candidate_frame,
    pick_seed,
)
from tests.test_take_feedback_policy_v3 import _frame

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "the_shadow_writer_keeps_the_pick_log.sql"


def test_the_frame_version_moves_with_the_pick_log():
    assert FRAME_SCHEMA_VERSION == "take-feedback-policy-v3-frame-v6"
    assert PICK_LOG_VERSION == "v4-pick-log-v1"
    assert PICK_SEED_VERSION == "v4-pick-seed-v1"


def test_every_confidence_candidate_is_logged_with_its_chance():
    frame = _frame()
    log = frame["pick_log"]
    assert log["version"] == PICK_LOG_VERSION
    assert log["policy_version"] == POLICY_VERSION
    assert log["selection"] == "deterministic_relative_best"
    by_id = {(e["lane"], e["candidate_id"]): e for e in log["candidates"]}
    for block in frame["blocks"]:
        for candidate in block["confidence_candidates"]:
            entry = by_id[("confident_voice", candidate["candidate_id"])]
            assert entry["block_id"] == block["block_id"]
            if candidate["eligibility"] == "eligible":
                expected = (1.0 if candidate["candidate_id"]
                            == block["selected_candidate_id"] else 0.0)
                assert entry["pick_probability"] == expected
            else:
                assert entry["pick_probability"] is None


def test_each_block_has_exactly_one_certain_pick():
    frame = _frame()
    for block in frame["blocks"]:
        certain = [e for e in frame["pick_log"]["candidates"]
                   if e["lane"] == "confident_voice"
                   and e["block_id"] == block["block_id"]
                   and e["pick_probability"] == 1.0]
        assert [e["candidate_id"] for e in certain] == [
            block["selected_candidate_id"]]


def test_verbal_lanes_log_their_selection():
    frame = _frame()
    for lane in ("rewrite_clarity", "great_formulation"):
        selected = set(frame["verbal_lanes"][lane]["selected_candidate_ids"])
        logged = {e["candidate_id"]: e for e in frame["pick_log"]["candidates"]
                  if e["lane"] == lane}
        for candidate in frame["verbal_lanes"][lane]["candidates"]:
            cid = candidate.get("candidate_id")
            if not cid:
                continue
            entry = logged[cid]
            if candidate["eligibility"] == "eligible":
                assert entry["pick_probability"] == (
                    1.0 if cid in selected else 0.0)
            else:
                assert entry["pick_probability"] is None


def test_the_seed_is_deterministic_per_take_and_json_safe():
    assert pick_seed("take-1") == pick_seed("take-1")
    assert pick_seed("take-1") != pick_seed("take-2")
    seed = pick_seed("take-1")
    assert seed.isdigit() and len(seed) <= 16
    assert int(seed) < 2 ** 53
    assert _frame()["pick_log"]["seed"] == pick_seed(_frame()["take_id"])


def test_the_serving_frame_carries_no_pick_chance():
    service = build_service_candidate_frame(**_frame_kwargs())
    assert service is not None
    assert "pick_log" not in service
    assert "pick_probability" not in json.dumps(service)
    assert "pick_probability" in json.dumps(_frame())


def _frame_kwargs() -> dict:
    """The exact inputs the dark-frame fixture builds from."""
    from tests import test_take_feedback_policy_v3 as base
    captured: dict = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return None

    original = base.build_shadow_frame
    base.build_shadow_frame = fake
    try:
        base._frame()
    finally:
        base.build_shadow_frame = original
    return captured


def test_the_writer_requires_the_frame_and_pick_log_the_code_builds():
    sql = MIGRATION.read_text()
    assert f"'{FRAME_SCHEMA_VERSION}'" in sql
    assert f"'{PICK_LOG_VERSION}'" in sql
    assert f"'{PICK_SEED_VERSION}'" in sql
    assert "take-feedback-policy-v3-frame-v5" not in sql
    manifest = (ROOT / "migrations" / "manifest.txt").read_text()
    assert "0441\tthe_shadow_writer_keeps_the_pick_log.sql" in manifest


def test_dark_frames_stay_founder_only_until_widened():
    from services import take_feedback_policy_v3 as v3
    import inspect
    src = inspect.getsource(v3.dark_enabled)
    assert "TAKE_FEEDBACK_POLICY_V3_FOUNDER_PRINCIPAL_ID" in src
    assert "compare_digest" in src
