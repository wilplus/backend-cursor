"""
STORY    As a coach asked to listen to a moment again, I want it shown with
         only its line key and nothing of the speaker's side, so that my
         second listen stays blind.
OUTCOME
  O1  That moment's row carries only its id, its state and the line key,
      with no sign of what the speaker asked.
  O2  It still counts in the "waiting" totals.
PROVES   O1, O2 ->
             QueueTests::test_a_moment_with_an_open_ask_rides_blind_with_only_the_line_key
WHY      Never-rule 2; QG12a A, P26b A, P26c; D-CP-10 (migration 0444).
"""
from __future__ import annotations

import unittest

from services.coach_moments_queue import moments_queue

ALL = lambda _sid: {"s1", "s2"}  # noqa: E731


class QueueTests(unittest.TestCase):
    def test_a_moment_with_an_open_ask_rides_blind_with_only_the_line_key(self):
        rows = [{"id": "t1", "user_id": "u", "review_requested_at": "2026-10-07T10:00", "take_index": 1}]
        ratings = {"t1": {"s1": {"value": "no", "unrateable": False},
                          "s2": {"value": "yes", "unrateable": False}}}
        # The request carries the speaker's side (answer_kind 'ambiguity'):
        # a row with an open ask must not carry it.
        requests = {("t1", "s1"): {"kind": "praise", "answer_kind": "ambiguity",
                                   "resolution": "line_written"},
                    ("t1", "s2"): {"kind": "praise", "resolution": None}}
        out = moments_queue(
            rows, moments_for=lambda r: ["s1", "s2"], reached_for=ALL,
            ratings_for=lambda sid: ratings.get(sid, {}),
            request_for=lambda sid, snip: requests.get((sid, snip)),
            pseudonym_for=lambda uid: "Quiet", rater_id="coach-1",
            listen_again_for=lambda sid: {"s1": "P26c-B"} if sid == "t1" else {})
        take = out[0]["takes"][0]
        self.assertEqual(take["moments"], [
            {"snippet_id": "s1", "state": "listen_again", "line_key": "P26c-B"},
            {"snippet_id": "s2", "state": "answer_it", "kind": "praise"},
        ])
        self.assertEqual(take["waiting"], 2)
        self.assertEqual(out[0]["waiting"], 2)
        leaked = {k for k in take["moments"][0]} - {"snippet_id", "state", "line_key"}
        self.assertEqual(leaked, set())
        self.assertNotIn("ambiguity", str(take["moments"][0]))
