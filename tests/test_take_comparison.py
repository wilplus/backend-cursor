"""
STORY    As a speaker, I never want to see my pitch, pace or pauses as
         numbers, so that feedback stays in words (Never rule 1).
OUTCOME
  O1  The retired take comparison (GET /v2/explore/arc/<id>/take-comparison,
      founder 2026-10-19) answers 410 GONE, reads nothing, sends no
      measurement number, and logs retired_route_called so any caller left
      shows up.
PROVES   O1 -> test_the_retired_comparison_answers_410_with_no_numbers
WHY      It sent raw Hz, wpm and pause milliseconds to the speaker, and no
         frontend called it. services/take_comparison.py has no caller left;
         deleting it is a follow-up.
"""
from __future__ import annotations

import unittest

from flask import Flask, request

from routes.v2 import arcs
from services.db import db
from tests.fakes import swap_attr


class _NoDatabase:
    def __getattr__(self, name):
        raise AssertionError(f"a retired route touched the database: {name}")


def _numbers(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from _numbers(value)
    elif isinstance(node, list):
        for value in node:
            yield from _numbers(value)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        yield node


class RetiredTakeComparisonTests(unittest.TestCase):

    def test_the_retired_comparison_answers_410_with_no_numbers(self):
        app = Flask(__name__)
        with swap_attr(db, "client", _NoDatabase()), \
                self.assertLogs("routes.v2.common", "WARNING") as logs, \
                app.test_request_context(
                    "/v2/explore/arc/arc-1/take-comparison", method="GET"):
            request.user_id = "speaker-1"
            response, status = \
                arcs.v2_explore_arc_take_comparison.__wrapped__("arc-1")
            payload = response.get_json()

        self.assertEqual(status, 410)
        self.assertEqual(payload["code"], "GONE")
        self.assertEqual(list(_numbers(payload)), [])
        [line] = logs.output
        self.assertIn("retired_route_called", line)
        self.assertIn("take-comparison", line)
        self.assertIn("user=speaker-1", line)


if __name__ == "__main__":
    unittest.main()
