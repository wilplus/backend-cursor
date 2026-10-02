"""Phase 0c (founder 2026-10-01, A2): a student's new Take as a bubble in
the coach's Lounge chat, derived at read and dark. Pins: off → 404 and
nothing read; a Take this coach rated a moment of is no bubble; the name
rides only when the names read gives one; newest sent first."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.coach_take_bubbles import bubbles, take_bubbles

ROWS = [
    {"id": "t1", "user_id": "u1", "take_index": 1, "review_requested_at": "2026-10-01T10:00:00Z"},
    {"id": "t2", "user_id": "u2", "take_index": 2, "review_requested_at": "2026-10-01T11:00:00Z"},
    {"id": "t3", "user_id": "u3", "take_index": 1, "review_requested_at": "2026-10-01T09:00:00Z"},
]


def _moments(row):
    return {"t1": ["s1", "s2"], "t2": ["s3"], "t3": None}[row["id"]]


def _ratings(sid):
    return {"s3": {"value": "yes"}} if sid == "t2" else {}


class BubblesTests(unittest.TestCase):
    def test_a_walked_take_is_no_bubble_and_the_order_is_newest_first(self):
        out = bubbles(ROWS, moments_for=_moments, ratings_for=_ratings,
                      pseudonym_for=lambda u: f"P-{u}", names={"u1": "Ada"})
        self.assertEqual([b["session_id"] for b in out], ["t1", "t3"])
        self.assertEqual(out[0]["name"], "Ada")
        self.assertNotIn("name", out[1])
        self.assertEqual(out[0]["first_snippet_id"], "s1")
        self.assertTrue(out[1]["waiting_for_text"])
        self.assertIsNone(out[1]["first_snippet_id"])
        for b in out:
            self.assertNotIn("kind", b)
            self.assertNotIn("score", b)

    def test_off_is_404_and_reads_nothing(self):
        class Db:
            def get_user_proficient_languages(self, _):
                raise AssertionError("read while off")
        with patch("config.Config.COACH_TAKE_BUBBLES_ENABLED", False, create=True):
            status, payload = take_bubbles(Db(), rater_id="c", state_for=lambda *a, **k: {},
                                           matched_rows=lambda r, s, p: r,
                                           moments_for_snips=lambda s: _moments,
                                           pseudonym_for=str)
        self.assertEqual((status, payload["code"]), (404, "NOT_FOUND"))

    def test_on_it_reads_the_queue_through_the_queue_s_own_gates(self):
        class Db:
            def get_user_proficient_languages(self, _):
                return ["en"]
            def list_review_queue(self):
                return ROWS
            def get_snippets_by_sessions(self, ids):
                return {i: [] for i in ids}
            def get_coach_snippet_drafts_by_sessions(self, ids):
                return {}
            def get_own_state_ratings_for_session(self, sid, rater):
                return _ratings(sid)
            def get_student_names(self, ids):
                return {"u1": "Ada"}
        with patch("config.Config.COACH_TAKE_BUBBLES_ENABLED", True, create=True), \
                patch("config.Config.COACH_STUDENTS_ENABLED", True):
            status, payload = take_bubbles(
                Db(), rater_id="c", state_for=lambda *a, **k: {},
                matched_rows=lambda rows, s, p: [r for r in rows if r["id"] != "t3"],
                moments_for_snips=lambda s: _moments, pseudonym_for=lambda u: f"P-{u}")
        self.assertEqual(status, 200)
        self.assertEqual([b["session_id"] for b in payload["bubbles"]], ["t1"])
        self.assertEqual(payload["bubbles"][0]["name"], "Ada")


if __name__ == "__main__":
    unittest.main()
