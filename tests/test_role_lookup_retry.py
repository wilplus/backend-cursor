"""
STORY    As a coach, I want my coach link to open even when the database
         hiccups for a moment, so that I am not told "not a coach" by mistake.
OUTCOME
  O1  A lookup that fails once and then answers gives the real answer.
  O2  A lookup that fails twice keeps an earlier stored yes; with nothing
      stored it says no, as before.
  O3  "No rows" is an answer and is not retried.
PROVES   O1 -> RoleLookupRetryTest::test_fails_once_then_answers
         O2 -> RoleLookupRetryTest::test_fails_twice_uses_stored_answer_else_no
         O3 -> RoleLookupRetryTest::test_no_rows_is_not_retried
WHY      Founder 2026-11-11: retry the lookup once before answering "not a coach".
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from routes import admin


class _Client:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def table(self, _t):
        return self

    def select(self, *_a):
        return self

    def eq(self, *_a):
        return self

    def execute(self):
        self.calls += 1
        o = self.outcomes.pop(0)
        if isinstance(o, Exception):
            raise o
        return SimpleNamespace(data=o)


class RoleLookupRetryTest(unittest.TestCase):
    def setUp(self):
        admin._role_cache.clear()
        self.app = Flask(__name__)
        p = patch.object(admin.time, "sleep")
        p.start()
        self.addCleanup(p.stop)

    def _is_coach(self, client):
        with self.app.test_request_context(), patch.object(admin, "db", SimpleNamespace(client=client)):
            from flask import request

            request.token_payload = {"email": "c@example.com"}
            return admin.is_coach("u")

    def test_fails_once_then_answers(self):
        c = _Client([RuntimeError("blip"), [{"id": 1}]])
        self.assertTrue(self._is_coach(c))

    def test_fails_twice_uses_stored_answer_else_no(self):
        self.assertFalse(self._is_coach(_Client([RuntimeError("a"), RuntimeError("b")])))
        c = _Client([[{"id": 1}]])
        self.assertTrue(self._is_coach(c))
        with patch.object(admin, "ROLE_TTL_S", -1.0):
            self.assertTrue(self._is_coach(_Client([RuntimeError("a"), RuntimeError("b")])))

    def test_no_rows_is_not_retried(self):
        c = _Client([[]])
        self.assertFalse(self._is_coach(c))
        self.assertEqual(c.calls, 1)


if __name__ == "__main__":
    unittest.main()
