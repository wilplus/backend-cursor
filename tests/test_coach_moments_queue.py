"""The coach's queue of moments (founder 2026-09-30, A1 to A8; P2-6).

Pins: speakers oldest first; one word per moment; the kind rides only after
THIS coach's rating (BLIND COACH); the pseudonym is the queue's own.
"""
from __future__ import annotations

import unittest

from services.coach_moments_queue import (
    moment_state, moments_queue, reached_moments,
)

ALL = lambda _sid: {"s1", "s2", "s3"}  # noqa: E731 -- every moment reached


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
            reached_for=ALL, ratings_for=lambda sid: ratings.get(sid, {}),
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
            moments_for=lambda r: [], reached_for=ALL, ratings_for=lambda s: {},
            request_for=lambda s, n: None, pseudonym_for=lambda u: "Calm Heron")
        self.assertEqual(set(out[0]), {"pseudonym", "takes", "waiting", "waiting_for_text"})
        self.assertNotIn("user_id", out[0]["takes"][0])

    def test_a_take_whose_bookmarks_are_not_frozen_rides_as_waiting_for_text(self):
        # Founder 2026-10-01 (A1): never silently absent. `moments_for` says
        # None for "not frozen yet" and [] for "frozen, nothing bookmarked".
        out = moments_queue(
            [{"id": "t-new", "user_id": "u", "created_at": "2026-10-01T09:00"},
             {"id": "t-old", "user_id": "u", "created_at": "2026-09-30T09:00"}],
            moments_for=lambda r: None if r["id"] == "t-new" else [],
            reached_for=ALL, ratings_for=lambda s: {}, request_for=lambda s, n: None,
            pseudonym_for=lambda u: "Calm Otter")
        takes = {t["session_id"]: t for t in out[0]["takes"]}
        self.assertTrue(takes["t-new"]["waiting_for_text"])
        self.assertEqual(takes["t-new"]["moments"], [])
        self.assertEqual(takes["t-new"]["waiting"], 0)
        self.assertFalse(takes["t-old"]["waiting_for_text"])
        self.assertEqual(out[0]["waiting_for_text"], 1)



class ReachedTests(unittest.TestCase):
    """N48.2, Q1 A (audit D9): only moments the speaker was shown or
    answered reach the coach's queue."""

    def test_opened_skipped_answered_and_requested_count_nothing_else(self):
        reached = reached_moments(
            [{"take_session_id": "t", "snippet_id": "s-open", "event": "opened"},
             {"take_session_id": "t", "snippet_id": "s-skip", "event": "skipped"},
             {"take_session_id": "t", "snippet_id": "s-odd", "event": "rendered"},
             {"take_session_id": "t", "snippet_id": None, "event": "opened"},
             "junk"],
            [{"take_session_id": "t", "snippet_id": "s-answered"},
             {"take_session_id": "u", "snippet_id": "s-other-take"}],
            [("t", "s-requested"), "junk"])
        self.assertEqual(reached["t"], {"s-open", "s-skip", "s-answered", "s-requested"})
        self.assertEqual(reached["u"], {"s-other-take"})

    def test_a_bookmark_that_never_reached_the_speaker_is_not_listed(self):
        out = moments_queue(
            [{"id": "t", "user_id": "u", "created_at": "x"}],
            moments_for=lambda r: ["s-met", "s-frozen-only", "s-answered"],
            reached_for=lambda sid: {"s-met", "s-answered"} if sid == "t" else set(),
            ratings_for=lambda s: {}, request_for=lambda s, n: None,
            pseudonym_for=lambda u: "Calm Heron")
        take = out[0]["takes"][0]
        self.assertEqual([m["snippet_id"] for m in take["moments"]],
                         ["s-met", "s-answered"])
        self.assertEqual(take["waiting"], 2)

    def test_reach_is_per_take_never_borrowed_from_another(self):
        out = moments_queue(
            [{"id": "t1", "user_id": "u", "created_at": "1"},
             {"id": "t2", "user_id": "u", "created_at": "2"}],
            moments_for=lambda r: ["s"],
            reached_for=lambda sid: {"s"} if sid == "t1" else set(),
            ratings_for=lambda s: {}, request_for=lambda s, n: None,
            pseudonym_for=lambda u: "Calm Heron")
        takes = {t["session_id"]: t for t in out[0]["takes"]}
        self.assertEqual(len(takes["t1"]["moments"]), 1)
        self.assertEqual(takes["t2"]["moments"], [])

    def test_no_answer_value_can_travel(self):
        # BLIND COACH: the reach read is existence only. An answer row that
        # carries a response still contributes nothing but its ids, and the
        # listed moment says only "judge_it".
        reached = reached_moments(
            [], [{"take_session_id": "t", "snippet_id": "s", "response": "no"}])
        out = moments_queue(
            [{"id": "t", "user_id": "u", "created_at": "x"}],
            moments_for=lambda r: ["s"], reached_for=lambda sid: reached.get(sid, set()),
            ratings_for=lambda s: {}, request_for=lambda s, n: None,
            pseudonym_for=lambda u: "Calm Heron")
        self.assertEqual(out[0]["takes"][0]["moments"],
                         [{"snippet_id": "s", "state": "judge_it"}])
        self.assertNotIn("no", str(out))


if __name__ == "__main__":
    unittest.main()
