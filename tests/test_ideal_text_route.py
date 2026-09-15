"""GET /v2/talks/<talk_id>/ideal-text — ROUTE-level test of the
coach_finalized content gate. (The 402 paywall that used to compose with this
gate was retired with the single-deliverable flag — the ideal text is free
now.) Only the service function was covered before this file — see
test_ideal_text_report.py for the pure build_ideal_text_report mapping tests,
and test_best_presentation.py's CoachFinalizedGateTests for the gate itself.

Run: python3 -m unittest tests.test_ideal_text_route
"""
from __future__ import annotations

import unittest

try:
    from flask import Flask, request
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e


def _sess(sid="s1"):
    return {
        "id": sid, "user_id": "u1", "take_index": 1,
        "intake_context": {
            "topic": "My talk",
            "slides": [{"title": "Slide 1", "body": "p"}],
            "slide_advances": [{"index": 0, "t_ms": 0}],
        },
    }


def _snip(sid):
    return {"id": sid, "start_offset_ms": 0, "duration_ms": 1000,
            "transcript": "a line", "storage_path": f"s3://{sid}",
            "metrics": {"overall_score": 0.5}}


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class TalksRouteIsDeletedTests(unittest.TestCase):
    """/talks/<talk_id>/ideal-text is GONE (founder 2026-08-10: "older
    feedback system should be ripped off") — it had no FE caller and the
    audits product it served is retired. The coach_finalized content gate
    the old composition tests exercised through it stays covered where it
    lives: test_best_presentation.py's CoachFinalizedGateTests (the gate)
    and test_ideal_text_report.py (the pure builder mapping)."""

    def test_the_route_function_is_gone_from_the_aggregator(self):
        # The aggregator itself is gone (audit Q-A3); nothing can re-export it.
        import importlib.util
        self.assertIsNone(importlib.util.find_spec("routes.v2_routes"))

    def test_the_route_function_is_gone_from_its_module(self):
        from routes.v2 import explore_ideal_text
        self.assertFalse(hasattr(explore_ideal_text, "v2_talk_ideal_text"))


if __name__ == "__main__":
    unittest.main()
