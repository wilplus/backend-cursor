"""Goal-update intercept (willab Prompt A §6 C4). Pure pre-gate + the
orchestration with a stubbed classifier/db (no LLM, no network).

Run: python3 -m unittest test_goal_update
"""
from __future__ import annotations

import unittest

import services.goal_update as gu


class PreGateTests(unittest.TestCase):
    def test_explicit_goal_change_passes(self):
        for msg in (
            "change my goal to landing my keynote",
            "set my goal: speak slower under pressure",
            "make my new goal more confident openings",
            "update my goal to closing bigger deals",
        ):
            self.assertTrue(gu._looks_like_goal_change(msg), msg)

    def test_multilingual_change_passes(self):
        self.assertTrue(gu._looks_like_goal_change("zmień mój cel na pewność siebie"))
        self.assertTrue(gu._looks_like_goal_change("cambia mi meta a hablar más lento"))

    def test_normal_chat_does_not_pass(self):
        for msg in (
            "what's my strongest line?",
            "how did my last recording go?",
            "show me my strong sides",
            "I want to record again",
        ):
            self.assertFalse(gu._looks_like_goal_change(msg), msg)

    def test_empty_is_false(self):
        self.assertFalse(gu._looks_like_goal_change(""))
        self.assertFalse(gu._looks_like_goal_change(None))


class _FakeDB:
    def __init__(self, profile=None, set_ok=True):
        self._profile = profile if profile is not None else {"domain": "sales", "goal": "old goal"}
        self._set_ok = set_ok
        self.set_calls = []

    def get_user_profile(self, user_id):
        return dict(self._profile)

    def update_user_goal(self, user_id, new_goal, previous_goal):
        self.set_calls.append({
            "user_id": user_id, "new_goal": new_goal,
            "previous_goal": previous_goal,
        })
        return self._set_ok


class HandleTests(unittest.TestCase):
    def setUp(self):
        self._orig = gu._classify_goal_update

    def tearDown(self):
        gu._classify_goal_update = self._orig

    def test_skips_llm_when_pregate_fails(self):
        called = {"n": 0}
        def _spy(*a, **k):
            called["n"] += 1
            return {"is_goal_update": True, "new_goal": "x", "confirmation": "ok"}
        gu._classify_goal_update = _spy
        fake = _FakeDB()
        # No goal/change tokens → pre-gate stops before the LLM.
        self.assertIsNone(gu.handle_goal_update("u1", "how did I do?", database=fake))
        self.assertEqual(called["n"], 0)
        self.assertEqual(fake.set_calls, [])

    def test_persists_and_confirms_on_update(self):
        gu._classify_goal_update = lambda m, **k: {
            "is_goal_update": True,
            "new_goal": "land my keynote",
            "confirmation": "Got it — your goal is now landing your keynote. Ready when you are.",
        }
        fake = _FakeDB(profile={"domain": "speaking", "goal": "old"})
        out = gu.handle_goal_update("u1", "change my goal to land my keynote", database=fake)
        self.assertIsNotNone(out)
        self.assertEqual(out["new_goal"], "land my keynote")
        self.assertIn("keynote", out["answer"])
        # The OLD goal is recorded as previous (coach sees old→new).
        self.assertEqual(out["previous_goal"], "old")
        self.assertEqual(len(fake.set_calls), 1)
        self.assertEqual(fake.set_calls[0]["previous_goal"], "old")
        self.assertEqual(fake.set_calls[0]["new_goal"], "land my keynote")

    def test_classifier_says_no_falls_through(self):
        gu._classify_goal_update = lambda m, **k: {
            "is_goal_update": False, "new_goal": "", "confirmation": "",
        }
        fake = _FakeDB()
        # Pre-gate passes (has goal+change words) but the LLM says it's not.
        self.assertIsNone(
            gu.handle_goal_update("u1", "what's a good goal to set?", database=fake)
        )
        self.assertEqual(fake.set_calls, [])

    def test_empty_new_goal_falls_through(self):
        gu._classify_goal_update = lambda m, **k: {
            "is_goal_update": True, "new_goal": "   ", "confirmation": "x",
        }
        fake = _FakeDB()
        self.assertIsNone(
            gu.handle_goal_update("u1", "change my goal", database=fake)
        )
        self.assertEqual(fake.set_calls, [])

    def test_persist_failure_falls_through(self):
        gu._classify_goal_update = lambda m, **k: {
            "is_goal_update": True, "new_goal": "x", "confirmation": "ok",
        }
        fake = _FakeDB(set_ok=False)
        self.assertIsNone(
            gu.handle_goal_update("u1", "set my goal to x", database=fake)
        )

    def test_classifier_failure_falls_through(self):
        gu._classify_goal_update = lambda m, **k: None
        fake = _FakeDB()
        self.assertIsNone(
            gu.handle_goal_update("u1", "change my goal to x", database=fake)
        )
        self.assertEqual(fake.set_calls, [])

    def test_anonymous_is_noop(self):
        gu._classify_goal_update = lambda m, **k: {
            "is_goal_update": True, "new_goal": "x", "confirmation": "ok",
        }
        fake = _FakeDB()
        self.assertIsNone(gu.handle_goal_update(None, "change my goal to x", database=fake))
        self.assertEqual(fake.set_calls, [])


if __name__ == "__main__":
    unittest.main()
