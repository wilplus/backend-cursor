"""
STORY    As a coach, I want to see the machine's exercise pick and its reasons
         only after my blind rating, and never its confidence read, so that I
         judge the speaker myself.
OUTCOME
  O1  The pick names the chosen exercise, the spotted problems by library
      name and every candidate, ranked first in rank order, then excluded;
      it never carries the machine's confidence read or raw measurements.
  O2  Never-2: before my blind rating the practice review refuses and shows
      no pick; after it, the review carries the pick.
PROVES   O1 -> test_the_machine_s_confidence_read_never_reaches_the_coach
         O2 -> test_the_practice_review_shows_the_pick_only_after_the_rating
"""
from __future__ import annotations

import inspect
import json
import unittest
from unittest.mock import patch

from services import exercise_pick_view as view

try:
    from flask import Flask, request

    from routes.v2 import coach as v2_coach
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    _IMPORT_ERROR = e

SID = "22222222-2222-4222-8222-222222222222"
SNIP = "77777777-7777-4777-8777-777777777777"

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

    def test_the_machine_s_confidence_read_never_reaches_the_coach(self):
        pick = view.machine_pick(_Db(ASSIGNMENT), "take-1", "snip-1")
        self.assertEqual(pick["exercise_id"], "second")
        self.assertEqual(pick["spotted"], [{"error_id": "rushing", "label": "Rushing"}])
        self.assertEqual([(c["exercise_id"], c["outcome"]) for c in pick["candidates"]],
                         [("first", "ranked"), ("second", "ranked"),
                          ("elsewhere", "excluded")])
        text = json.dumps(pick)
        for hidden in ("near_confident", "confidence", "0.31", "wpm",
                       "features", "gate", "pattern_distance"):
            self.assertNotIn(hidden, text, hidden)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class PracticeReviewGateTests(unittest.TestCase):

    def _review(self, rating):
        fake = _Db(ASSIGNMENT)
        practice = {"id": "p1", "snippet_id": SNIP, "take_session_id": SID,
                    "exercise_id": "second"}
        with Flask(__name__).test_request_context(method="GET"):
            request.user_id = "coach-1"
            with patch.object(db, "v2_get_session_by_id", return_value={"id": SID}), \
                 patch.object(v2_coach, "_snippet_owner_map", return_value={SNIP: SID}), \
                 patch.object(v2_coach, "_coach_state_map",
                              return_value={SNIP: {"rating_value": rating}}), \
                 patch.object(v2_coach, "_speaker_practice_permitted", return_value=True), \
                 patch.object(db, "get_confident_voice_practice_by_moment",
                              return_value=practice), \
                 patch.object(db, "get_active_diagnostic_exercise", return_value=None), \
                 patch.object(db, "list_confident_voice_practice_attempts", return_value=[]), \
                 patch.object(db, "get_confident_voice_exercise_assignment",
                              fake.get_confident_voice_exercise_assignment), \
                 patch.object(db, "get_exercise_match_trace", fake.get_exercise_match_trace), \
                 patch.object(db, "list_speaking_errors", fake.list_speaking_errors), \
                 patch("services.confident_voice_practice.coach_exercise_order",
                       return_value=[]), \
                 patch.object(v2_coach, "coach_moment_fields", return_value={}):
                resp, status = inspect.unwrap(
                    v2_coach.v2_coach_confident_voice_practice)(SID, SNIP)
                return status, resp.get_json()

    def test_the_practice_review_shows_the_pick_only_after_the_rating(self):
        status, body = self._review(None)
        self.assertEqual((status, body["code"]), (409, "BLIND_RATING_REQUIRED"))
        self.assertNotIn("machine_pick", json.dumps(body))
        self.assertNotIn("second", json.dumps(body))

        status, body = self._review("yes")
        self.assertEqual(status, 200)
        self.assertEqual(body["practice"]["machine_pick"]["exercise_id"], "second")
