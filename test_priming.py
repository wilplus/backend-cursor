"""willab — pre-take mindset-priming manipulation (founder 2026-07-13).

The FE shows a framing panel (threat/challenge/balanced + a phrase) before each
live take and reports it on the upload. The BE logs it per take on the session
row for correlation against the acoustic read, exposes it to the COACH only,
and NEVER surfaces it to the user (AC-9).

Covers: the condition/phrase normalizers (services/priming.py) + the
DatabaseService.set_session_priming persist path (via a fake PostgREST client,
no live DB — mirrors test_arc_unlock's fake-client technique).

Run: python3 -m unittest test_priming
"""
from __future__ import annotations

import unittest

from services.priming import (
    VALID_PRIMING_CONDITIONS,
    normalize_priming_condition,
    normalize_priming_phrase,
)

try:
    from services.db import DatabaseService
    _DB_IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    DatabaseService = None
    _DB_IMPORT_ERROR = e


class ConditionNormalizerTests(unittest.TestCase):
    def test_the_three_conditions(self):
        self.assertEqual(
            VALID_PRIMING_CONDITIONS, ("threat", "challenge", "balanced"))

    def test_valid_values_pass(self):
        for v in ("threat", "challenge", "balanced"):
            self.assertEqual(normalize_priming_condition(v), v)

    def test_case_and_whitespace_normalised(self):
        self.assertEqual(normalize_priming_condition("  Challenge "), "challenge")
        self.assertEqual(normalize_priming_condition("THREAT"), "threat")

    def test_unknown_is_dropped_not_coerced(self):
        # The handoff's explicit case: an invalid condition stores null, never
        # the bad value, never coerced into a known one.
        self.assertIsNone(normalize_priming_condition("foo"))
        self.assertIsNone(normalize_priming_condition("stress"))
        self.assertIsNone(normalize_priming_condition(""))

    def test_non_string_is_none(self):
        for v in (None, 3, {"x": 1}, ["challenge"]):
            self.assertIsNone(normalize_priming_condition(v))


class PhraseNormalizerTests(unittest.TestCase):
    def test_verbatim_trimmed(self):
        self.assertEqual(
            normalize_priming_phrase("  This talk will be graded.  "),
            "This talk will be graded.")

    def test_blank_is_none(self):
        self.assertIsNone(normalize_priming_phrase("   "))
        self.assertIsNone(normalize_priming_phrase(""))
        self.assertIsNone(normalize_priming_phrase(None))

    def test_capped_defensively(self):
        self.assertEqual(len(normalize_priming_phrase("x" * 5000)), 500)

    def test_non_string_is_none(self):
        self.assertIsNone(normalize_priming_phrase(42))


class _FakeSessionsClient:
    """Captures the last v2_sessions update payload; can simulate a
    missing-column error to exercise the graceful-degrade path."""

    def __init__(self, raise_missing_column=False):
        self.raise_missing_column = raise_missing_column
        self.last_update = None
        self.last_eq = None

    def table(self, name):
        assert name == "v2_sessions"
        return self

    def update(self, payload):
        self.last_update = payload
        return self

    def eq(self, col, val):
        self.last_eq = (col, val)
        return self

    def execute(self):
        if self.raise_missing_column:
            raise Exception(
                "column v2_sessions.priming_condition does not exist")
        return type("R", (), {"data": [{"id": "s1"}]})()


@unittest.skipIf(_DB_IMPORT_ERROR is not None, f"needs db deps: {_DB_IMPORT_ERROR}")
class SetSessionPrimingTests(unittest.TestCase):
    def _svc(self, **kw):
        # Bypass __init__ (no live supabase) — same technique as
        # test_arc_unlock.DeductCreditsStrictTests._svc.
        s = DatabaseService.__new__(DatabaseService)
        fake = _FakeSessionsClient(**kw)
        s.client = fake
        return s, fake

    def test_persists_condition_and_phrase(self):
        svc, fake = self._svc()
        ok = svc.set_session_priming("s1", "challenge", "Be graded on this.")
        self.assertTrue(ok)
        self.assertEqual(fake.last_update, {
            "priming_condition": "challenge",
            "priming_phrase": "Be graded on this.",
        })
        self.assertEqual(fake.last_eq, ("id", "s1"))

    def test_noop_when_both_empty(self):
        # Nothing to log (an upload with no priming) → no write at all.
        svc, fake = self._svc()
        self.assertFalse(svc.set_session_priming("s1", None, None))
        self.assertIsNone(fake.last_update)

    def test_condition_only_still_writes(self):
        svc, fake = self._svc()
        self.assertTrue(svc.set_session_priming("s1", "threat", None))
        self.assertEqual(fake.last_update["priming_condition"], "threat")
        self.assertIsNone(fake.last_update["priming_phrase"])

    def test_missing_column_degrades_to_false_not_raise(self):
        # Pre-migration: the column doesn't exist → False, non-fatal (the take
        # is still recorded; this is a SEPARATE write from the feeling capture,
        # so feeling can never be regressed by a priming-column miss).
        svc, _ = self._svc(raise_missing_column=True)
        self.assertFalse(svc.set_session_priming("s1", "challenge", "x"))

    def test_no_session_id_is_false(self):
        svc, fake = self._svc()
        self.assertFalse(svc.set_session_priming("", "challenge", "x"))
        self.assertIsNone(fake.last_update)


if __name__ == "__main__":
    unittest.main()
