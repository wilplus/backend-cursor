"""GET /v2/talks/<talk_id>/ideal-text — ROUTE-level test of the
coach_finalized content gate. (The 402 paywall that used to compose with this
gate was retired with the single-deliverable flag — the ideal text is free
now.) The report builder and the Best Presentation builder it read are
removed too (N48.3 Q13 A).

Run: python3 -m unittest tests.test_ideal_text_route
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask, request
    from routes.v2 import arcs as v2_arcs
    from services.db import db
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
    audits product it served is retired. Its builder and the Best
    Presentation builder behind it are removed (N48.3 Q13 A)."""

    def test_the_route_function_is_gone_from_the_aggregator(self):
        # The aggregator itself is gone (audit Q-A3); nothing can re-export it.
        import importlib.util
        self.assertIsNone(importlib.util.find_spec("routes.v2_routes"))

    def test_the_route_function_is_gone_from_its_module(self):
        from routes.v2 import explore_ideal_text
        self.assertFalse(hasattr(explore_ideal_text, "v2_talk_ideal_text"))


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ArcProgressCoachFinalizedTests(unittest.TestCase):
    """Backlog 4.2 (B8): the cheap progress poll carries coach_finalized so
    the FE can show "waiting for the coach to assemble" at 3/3."""

    def setUp(self):
        self.app = Flask(__name__)
        deck = {"slides": [{"title": "S1", "body": ""},
                           {"title": "S2", "body": ""}]}
        self._sessions = [
            {"id": f"s{i}", "user_id": "u1", "take_index": i + 1,
             "intake_context": dict(deck)}
            for i in range(3)
        ]
        self._coach_edits = {}
        self._p = [
            # 2026-07-16: the guest-capable progress route reads
            # db.get_arc_sessions directly (no _arc_owned_by_caller).
            patch.object(db.takes, "get_arc_sessions",
                         lambda arc_id: list(self._sessions)),
            patch.object(db, "get_coach_best_presentation_edits",
                         lambda arc_id: dict(self._coach_edits)),
        ]
        for p_ in self._p:
            p_.start()

    def tearDown(self):
        for p_ in self._p:
            p_.stop()

    def _call(self):
        with self.app.test_request_context():
            request.user_id = "u1"
            resp, status = v2_arcs.v2_explore_arc_progress.__wrapped__("a1")
            return resp.get_json(), status

    def test_not_finalized_until_every_slide_corrected(self):
        self._coach_edits = {0: "corrected one"}  # 1 of 2 slides
        body, status = self._call()
        self.assertEqual(status, 200)
        self.assertEqual(body["takes_done"], 3)
        self.assertFalse(body["coach_finalized"])

    def test_finalized_when_all_slides_corrected(self):
        self._coach_edits = {0: "one", 1: "two"}
        body, _ = self._call()
        self.assertTrue(body["coach_finalized"])

    def test_deckless_arc_never_finalized(self):
        for s in self._sessions:
            s["intake_context"] = {"topic": "t"}
        self._coach_edits = {0: "x"}
        body, _ = self._call()
        self.assertFalse(body["coach_finalized"])


if __name__ == "__main__":
    unittest.main()
