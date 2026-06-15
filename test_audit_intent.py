"""Audit chat intercept (willab Prompt C §5). Pure pre-gate + the
orchestration with a stubbed renderer/db (no LLM, no network).

Run: python3 -m unittest test_audit_intent
"""
from __future__ import annotations

import unittest

import services.audit_intent as ai


class PreGateTests(unittest.TestCase):
    def test_audit_requests_pass(self):
        for msg in (
            "can I see my audit?",
            "where's my audit",
            "show me the audit",
            "pokaż mój audyt",          # pl
            "quiero ver mi auditoría",  # es (audit prefix)
        ):
            self.assertTrue(ai._looks_like_audit_request(msg), msg)

    def test_normal_chat_does_not_pass(self):
        for msg in (
            "what's my strongest line?",
            "how did my recording go?",
            "I want to record again",
        ):
            self.assertFalse(ai._looks_like_audit_request(msg), msg)

    def test_empty_is_false(self):
        self.assertFalse(ai._looks_like_audit_request(""))
        self.assertFalse(ai._looks_like_audit_request(None))


class _FakeDB:
    def __init__(self, audits):
        self._audits = audits

    def list_user_audits(self, user_id):
        return list(self._audits)


class HandleTests(unittest.TestCase):
    def setUp(self):
        self._orig = ai._render_pointer
        # Deterministic stub — no LLM.
        ai._render_pointer = lambda name, msg: f"Here's your {name} 👇"

    def tearDown(self):
        ai._render_pointer = self._orig

    def test_skips_when_pregate_fails(self):
        called = {"n": 0}
        def _spy(n, m):
            called["n"] += 1
            return "x"
        ai._render_pointer = _spy
        fake = _FakeDB([{"id": "a1", "name": "Audit"}])
        self.assertIsNone(ai.handle_audit_intent("u1", "how did I do?", database=fake))
        self.assertEqual(called["n"], 0)

    def test_surfaces_button_when_user_has_audit(self):
        fake = _FakeDB([{"id": "a1", "name": "Speaking Impact Audit"}])
        out = ai.handle_audit_intent("u1", "show me my audit", database=fake)
        self.assertIsNotNone(out)
        self.assertEqual(out["suggested_action"], "audit")
        self.assertIn("Speaking Impact Audit", out["answer"])

    def test_no_audit_falls_through(self):
        fake = _FakeDB([])
        self.assertIsNone(ai.handle_audit_intent("u1", "where's my audit", database=fake))

    def test_render_failure_falls_back_to_name(self):
        ai._render_pointer = lambda name, msg: None  # render fails
        fake = _FakeDB([{"id": "a1", "name": "My Audit"}])
        out = ai.handle_audit_intent("u1", "audit please", database=fake)
        self.assertEqual(out["suggested_action"], "audit")
        self.assertEqual(out["answer"], "My Audit")  # name fallback

    def test_anonymous_is_noop(self):
        fake = _FakeDB([{"id": "a1", "name": "Audit"}])
        self.assertIsNone(ai.handle_audit_intent(None, "my audit", database=fake))

    def test_no_explanation_in_answer(self):
        # The bubble must not explain what an audit is (founder rule). With the
        # stub, the answer is just the pointer line — assert it's short.
        fake = _FakeDB([{"id": "a1", "name": "Audit"}])
        out = ai.handle_audit_intent("u1", "my audit", database=fake)
        self.assertLessEqual(len(out["answer"]), 80)


if __name__ == "__main__":
    unittest.main()
