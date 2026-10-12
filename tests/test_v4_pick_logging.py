"""V4 Phase 1, B1.1: the dark frame logs every pick (build plan D-ML-6).

Every candidate V3 weighed is logged with its chance of being picked, the
Take's seed and the policy version. The serving frame never carries it
(AC-9).
"""
from __future__ import annotations

import json

from services.take_feedback_policy_v3 import (
    build_service_candidate_frame,
)
from tests.test_take_feedback_policy_v3 import _frame


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
