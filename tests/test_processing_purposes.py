"""The gate that decides whether a product purpose may serve.

routes/phase2_guard.py's operational_purpose_disabled named a registry purpose
and never read it — it returned 410 unconditionally. Harmless while the answer
could only be no; a liability the moment 0335 made the answer yes, because the
switch and the fact it claimed to reflect were then kept in step by hand.

These tests pin the direction of every failure. A closed door is the answer to
a missing row, an unreadable registry, a phase-2 purpose and an explicit
`operational = false` alike. Only one shape of row opens it.

Run: python3 -m unittest tests.test_processing_purposes
"""
from __future__ import annotations

import unittest

from services.processing_purposes import (
    forget_cached_purposes,
)

PURPOSE = "personalized_exercise_recommendation"
OPEN_ROW = {"id": PURPOSE, "phase": "phase1", "operational": True,
            "authorizes_processing": True}


class _Db:
    def __init__(self, row=OPEN_ROW):
        self.row = row
        self.reads = 0

    def get_processing_purpose(self, purpose_id):
        self.reads += 1
        return self.row


class TheRouteBoundaryTests(unittest.TestCase):
    """The decorator runs the handler only when the registry says yes."""

    def setUp(self):
        forget_cached_purposes()

    def tearDown(self):
        forget_cached_purposes()

    def _call(self, row):
        import flask

        from routes.phase2_guard import operational_purpose_disabled

        ran = []

        @operational_purpose_disabled(PURPOSE)
        def handler():
            ran.append(True)
            return "handler ran", 200

        app = flask.Flask(__name__)
        import services.processing_purposes as pp
        original = pp.purpose_is_operational
        pp.purpose_is_operational = (
            lambda purpose_id, **kw: original(purpose_id, database=_Db(row)))
        try:
            with app.test_request_context("/"):
                result = handler()
        finally:
            pp.purpose_is_operational = original
        return result, ran


    def test_a_shut_registry_row_never_enters_the_handler(self):
        result, ran = self._call({**OPEN_ROW, "operational": False})
        self.assertEqual(ran, [])
        self.assertEqual(result[1], 410)
        self.assertEqual(result[0].get_json()["code"], "PURPOSE_NOT_OPERATIONAL")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
