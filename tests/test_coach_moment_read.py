"""The coach's Read screen, one source (founder 2026-09-30, A2; P2-10).

Pins: the passage, both answers, the request (or None), the named patterns
and the goal come back in words; the route sits behind the blind gate; no
number about the speaker is in the payload.
"""
from __future__ import annotations

import pathlib
import unittest

from services.coach_moment_read import moment_read

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Db:
    def __init__(self, *, request=None, rating=None, reports=None, goal="Sound calm"):
        self.request = request
        self.rating = rating
        self.reports = reports or []
        self.goal = goal

    def get_snippets_by_session(self, _take):
        return [{"id": "snip-1", "transcript": "We, we rebuilt it.", "slide_index": 3}]

    def list_take_feedback_self_reports_by_snippet(self, _snip):
        return self.reports

    def get_own_state_ratings_for_session(self, _take, _rater):
        return {"snip-1": self.rating} if self.rating else {}

    def get_user_profile(self, _uid):
        return {"goal": self.goal}

    def get_exercise_coach_request(self, _take, _snip):
        return self.request

    def list_coach_moment_error_events_for_snippet(self, _snip):
        return [{"error_id": "hedging", "action": "named"}]

    def list_speaking_errors(self, active_only=True):
        return [{"error_id": "hedging", "label": "Hedging"}]

    def get_confident_voice_exercise_assignment(self, _t, _s):
        return None

    def list_diagnostic_exercises(self):
        return []


class ReadTests(unittest.TestCase):
    def test_everything_in_words(self):
        db = _Db(request={"id": "req-1", "take_session_id": "take-1", "snippet_id": "snip-1",
                          "kind": "error", "observed_tags": ["hedging"], "resolution": None},
                 rating={"value": "no", "unrateable": False},
                 reports=[{"feedback_family": "confident_voice", "response": "yes"},
                          {"feedback_family": "confident_voice", "response": "in_between"}])
        out = moment_read(db, take_session_id="take-1", snippet_id="snip-1",
                          rater_id="coach-1", owner_user_id="owner-1")
        self.assertEqual(out["passage"], "We, we rebuilt it.")
        self.assertEqual(out["speaker_answer"], "in_between")
        self.assertEqual(out["coach_answer"], "no")
        self.assertEqual(out["speaker_goal"], "Sound calm")
        self.assertEqual(out["request"]["kind"], "error")
        self.assertEqual(out["request"]["spotted"], [{"error_id": "hedging", "label": "Hedging"}])
        self.assertEqual(out["named_errors"], ["hedging"])

    def test_no_request_is_none_not_an_error(self):
        db = _Db(rating={"value": "yes", "unrateable": True})
        out = moment_read(db, take_session_id="take-1", snippet_id="snip-1",
                          rater_id="coach-1", owner_user_id="owner-1")
        self.assertIsNone(out["request"])
        self.assertEqual(out["coach_answer"], "audio_unclear")
        self.assertIsNone(out["speaker_answer"])

    def test_the_route_is_behind_the_blind_gate(self):
        source = (ROOT / "routes/v2/coach.py").read_text()
        start = source.index("def v2_coach_moment_read")
        body = source[start:source.index("@v2_bp.route", start)]
        self.assertLess(body.index("_moment_gate(session_id, snippet_id)"),
                        body.index("payload = moment_read("))


if __name__ == "__main__":
    unittest.main()
