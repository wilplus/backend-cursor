"""The coach's queue of moments (founder 2026-09-30, A1 to A8; P2-6).

Pins: speakers oldest first; one word per moment; the kind rides only after
THIS coach's rating (BLIND COACH); the pseudonym is the queue's own.
"""
from __future__ import annotations

import unittest

from services.coach_moments_queue import moment_state, moments_queue


class StateTests(unittest.TestCase):
    def test_unrated_is_judge_it_and_says_nothing_else(self):
        self.assertEqual(moment_state(None, {"kind": "praise"}), {"state": "judge_it"})
        self.assertEqual(moment_state({"value": "yes", "unrateable": True},
                                      {"kind": "praise"}), {"state": "judge_it"})

    def test_rated_states_carry_the_kind(self):
        rated = {"value": "no", "unrateable": False}
        self.assertEqual(moment_state(rated, None), {"state": "judged"})
        self.assertEqual(moment_state(rated, {"kind": "error", "resolution": None}),
                         {"state": "answer_it", "kind": "error"})
        self.assertEqual(moment_state(rated, {"kind": "praise", "resolution": "line_written"}),
                         {"state": "answered", "kind": "praise"})
        self.assertEqual(moment_state(rated, {"kind": "rewrite", "resolution": "no_safe_match"}),
                         {"state": "nothing_to_add", "kind": "rewrite"})


class QueueTests(unittest.TestCase):
    def test_speakers_oldest_first_takes_under_them(self):
        rows = [
            {"id": "t-b2", "user_id": "u-b", "review_requested_at": "2026-09-30T10:00", "take_index": 2},
            {"id": "t-a1", "user_id": "u-a", "review_requested_at": "2026-09-29T10:00", "take_index": 1},
            {"id": "t-b1", "user_id": "u-b", "review_requested_at": "2026-09-28T10:00", "take_index": 1},
        ]
        ratings = {"t-a1": {"s1": {"value": "yes", "unrateable": False}}}
        requests = {("t-a1", "s1"): {"kind": "praise", "resolution": None}}
        out = moments_queue(
            rows, moments_for=lambda r: ["s1", "s2"] if r["id"] == "t-a1" else ["s3"],
            ratings_for=lambda sid: ratings.get(sid, {}),
            request_for=lambda sid, snip: requests.get((sid, snip)),
            pseudonym_for=lambda uid: f"Quiet {uid}")
        self.assertEqual([s["pseudonym"] for s in out], ["Quiet u-b", "Quiet u-a"])
        self.assertEqual([t["take_index"] for t in out[0]["takes"]], [1, 2])
        a = out[1]["takes"][0]
        self.assertEqual(a["moments"], [
            {"snippet_id": "s1", "state": "answer_it", "kind": "praise"},
            {"snippet_id": "s2", "state": "judge_it"},
        ])
        self.assertEqual(a["waiting"], 2)
        self.assertEqual(out[0]["waiting"], 2)

    def test_no_name_no_id_reaches_the_shape(self):
        out = moments_queue(
            [{"id": "t", "user_id": "u", "created_at": "x"}],
            moments_for=lambda r: [], ratings_for=lambda s: {},
            request_for=lambda s, n: None, pseudonym_for=lambda u: "Calm Heron")
        self.assertEqual(set(out[0]), {"pseudonym", "takes", "waiting"})
        self.assertNotIn("user_id", out[0]["takes"][0])


if __name__ == "__main__":
    unittest.main()
