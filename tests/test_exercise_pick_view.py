"""What the machine picked and why, for the coach after the blind rating (step 6).

Pins:
  * the pick carries the spotted problems by library name, the fit (exact or
    trial), how the 80/20 draw chose, and every candidate — ranked first in
    rank order, then excluded with the reason;
  * the machine's confidence read and the raw measurements are never in it
    (BLIND COACH: routing only, never a verdict on the speaker);
  * a moment with no draw has no pick; a draw from before traces existed
    says so instead of inventing a reason;
  * both coach payloads carry it, and only behind the blind gate.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from services import exercise_pick_view as view

ROOT = pathlib.Path(__file__).resolve().parent.parent

TRACE = {
    "trace_schema": "exercise-match-trace-v1",
    "signal_rules_version": "cv-exercise-signals-v1",
    "observed_tags": ["rushing"],
    "pattern": "near_confident",
    "gate": {"eligible": True, "reason": None, "pace_high": True},
    "features": {"confidence": 0.31, "wpm": 181.0},
    "signals": {"insufficient_pauses": True},
    "candidates": [
        {"exercise_id": "elsewhere", "outcome": "excluded",
         "reason": "targets_nothing_that_fired", "rank": None, "fit": None,
         "main_targets": ["ending_compression"], "secondary_targets": [],
         "pattern_distance": None},
        {"exercise_id": "second", "outcome": "ranked", "reason": None,
         "rank": 2, "fit": "exact", "main_targets": ["rushing"],
         "secondary_targets": [], "pattern_distance": 1},
        {"exercise_id": "first", "outcome": "ranked", "reason": None,
         "rank": 1, "fit": "exact", "main_targets": ["rushing"],
         "secondary_targets": [], "pattern_distance": 0},
    ],
}


class _Db:
    def __init__(self, assignment=None, trace=TRACE):
        self.assignment = assignment
        self.trace = trace

    def get_confident_voice_exercise_assignment(self, _take, _snippet):
        return self.assignment

    def get_exercise_match_trace(self, _assignment_id):
        return {"trace": self.trace} if self.trace is not None else None

    def list_speaking_errors(self):
        return [{"error_id": "rushing", "label": "Rushing"}]


ASSIGNMENT = {"id": "asg-1", "selected_exercise_id": "second",
              "selected_exercise_version": 1, "selection_mode": "exploration",
              "matching_policy_version": "exercise-fit-tier-v1:exact"}


class MachinePickTests(unittest.TestCase):
    def test_the_pick_says_what_and_why(self):
        pick = view.machine_pick(_Db(ASSIGNMENT), "take-1", "snip-1")
        self.assertEqual(pick["exercise_id"], "second")
        self.assertEqual(pick["fit"], "exact")
        self.assertEqual(pick["how_chosen"], "trying_another")
        self.assertTrue(pick["traced"])
        self.assertEqual(pick["spotted"],
                         [{"error_id": "rushing", "label": "Rushing"}])
        self.assertEqual([c["exercise_id"] for c in pick["candidates"]],
                         ["first", "second", "elsewhere"])
        self.assertEqual(pick["candidates"][2]["reason"],
                         "targets_nothing_that_fired")

    def test_the_machine_s_confidence_read_never_reaches_the_coach(self):
        pick = view.machine_pick(_Db(ASSIGNMENT), "take-1", "snip-1")
        text = json.dumps(pick)
        for hidden in ("near_confident", "confidence", "0.31", "wpm",
                       "features", "gate", "pattern_distance"):
            self.assertNotIn(hidden, text, hidden)

    def test_each_draw_mode_has_a_word(self):
        for mode, word in (("top", "best_match"),
                           ("exploration", "trying_another"),
                           ("deterministic_singleton", "only_match")):
            pick = view.machine_pick(
                _Db({**ASSIGNMENT, "selection_mode": mode}), "t", "s")
            self.assertEqual(pick["how_chosen"], word)

    def test_no_draw_no_pick(self):
        self.assertIsNone(view.machine_pick(_Db(None), "t", "s"))

    def test_a_draw_from_before_traces_says_so(self):
        pick = view.machine_pick(_Db(ASSIGNMENT, trace=None), "t", "s")
        self.assertFalse(pick["traced"])
        self.assertEqual(pick["candidates"], [])
        self.assertEqual(pick["spotted"], [])
        self.assertEqual(pick["exercise_id"], "second")

    def test_a_coach_request_explains_why_nothing_fitted(self):
        rows = view.request_candidates({"request_trace": TRACE})
        self.assertEqual(rows[-1]["reason"], "targets_nothing_that_fired")
        self.assertNotIn("0.31", json.dumps(rows))


class WiringTests(unittest.TestCase):
    def test_the_practice_review_carries_it_behind_the_blind_gate(self):
        source = (ROOT / "routes/v2/coach.py").read_text()
        payload = source[source.index("def _coach_practice_payload"):]
        payload = payload[:payload.index("\ndef ")]
        self.assertIn('"machine_pick": _machine_pick(practice)', payload)
        # The only caller of the payload builder is the practice route, whose
        # blind gate runs before it.
        route = source[source.index("def v2_coach_confident_voice_practice"):]
        route = route[:route.index("@v2_bp.route")]
        self.assertLess(route.index("BLIND_RATING_REQUIRED"),
                        route.index("_coach_practice_payload"))

    def test_the_coach_request_carries_its_candidates(self):
        from services import exercise_coach_requests as ecr

        class _ReqDb(_Db):
            def get_confident_voice_exercise_assignment(self, *_a):
                return None

            def list_diagnostic_exercises(self):
                return []

        payload = ecr.coach_request_payload(
            {"id": "r", "take_session_id": "t", "snippet_id": "s",
             "reason": "nothing_targets_it", "observed_tags": ["rushing"],
             "request_trace": TRACE}, _ReqDb())
        self.assertEqual(len(payload["candidates"]), 3)
