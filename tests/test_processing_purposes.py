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
    CACHE_TTL_SECONDS,
    forget_cached_purposes,
    purpose_is_operational,
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


class WhatOpensTheDoorTests(unittest.TestCase):
    def setUp(self):
        forget_cached_purposes()

    def tearDown(self):
        forget_cached_purposes()

    def test_a_phase1_operational_authorizing_row_opens_it(self):
        self.assertTrue(purpose_is_operational(PURPOSE, database=_Db()))

    def test_every_other_shape_of_row_keeps_it_shut(self):
        for row in (
            None,                                            # unreadable/missing
            {},                                              # empty
            {**OPEN_ROW, "phase": "phase2"},                 # still phase 2
            {**OPEN_ROW, "operational": False},              # the emergency stop
            {**OPEN_ROW, "authorizes_processing": False},    # cannot authorize
            {**OPEN_ROW, "operational": "yes"},              # not a real boolean
            {**OPEN_ROW, "operational": 1},                  # 1 == True in Python
            "not a row", 7, [],
        ):
            forget_cached_purposes()
            self.assertFalse(
                purpose_is_operational(PURPOSE, database=_Db(row)), row)

    def test_an_empty_purpose_id_never_reads_anything(self):
        db = _Db()
        self.assertFalse(purpose_is_operational("", database=db))
        self.assertEqual(db.reads, 0)


class TheCacheTests(unittest.TestCase):
    def setUp(self):
        forget_cached_purposes()

    def tearDown(self):
        forget_cached_purposes()

    def test_it_does_not_read_the_registry_on_every_request(self):
        db = _Db()
        for _ in range(5):
            purpose_is_operational(PURPOSE, database=db, now=100.0)
        self.assertEqual(db.reads, 1)

    def test_turning_it_off_takes_effect_without_a_deploy(self):
        # Flipping the row to false is the emergency stop. It must be felt
        # within the TTL, not at the next release.
        db = _Db()
        self.assertTrue(purpose_is_operational(PURPOSE, database=db, now=100.0))
        db.row = {**OPEN_ROW, "operational": False}
        later = 100.0 + CACHE_TTL_SECONDS + 1
        self.assertFalse(purpose_is_operational(PURPOSE, database=db, now=later))

    def test_a_failed_read_is_never_cached(self):
        # A registry blip closes the door for THAT request. Caching the failure
        # would latch the feature off for the rest of the TTL over one hiccup.
        db = _Db(None)
        self.assertFalse(purpose_is_operational(PURPOSE, database=db, now=100.0))
        db.row = OPEN_ROW
        self.assertTrue(purpose_is_operational(PURPOSE, database=db, now=100.0))


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

    def test_an_open_registry_row_reaches_the_handler(self):
        result, ran = self._call(OPEN_ROW)
        self.assertEqual(ran, [True])
        self.assertEqual(result, ("handler ran", 200))

    def test_a_shut_registry_row_never_enters_the_handler(self):
        result, ran = self._call({**OPEN_ROW, "operational": False})
        self.assertEqual(ran, [])
        self.assertEqual(result[1], 410)
        self.assertEqual(result[0].get_json()["code"], "PURPOSE_NOT_OPERATIONAL")

    def test_an_unreadable_registry_never_enters_the_handler(self):
        result, ran = self._call(None)
        self.assertEqual(ran, [])
        self.assertEqual(result[1], 410)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
