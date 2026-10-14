"""Unit tests for services/say_it_stronger ("Say It Stronger", founder
2026-07-07) — the pure pieces: session-mean aggregation, qualitative
self-comparison (never a number, never a population claim), the AC-9
output guard, payload cleaning, and the fire-and-forget dispatch safety.

Run: python3 -m unittest tests.test_say_it_stronger
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock

# services.db pulls in supabase — stub in setUpModule, restore after
# (willab test-stub-isolation convention).
_ORIG_SERVICES_DB = None


def setUpModule():
    global _ORIG_SERVICES_DB
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)


class CardsSurviveTheJobTests(unittest.TestCase):
    """The RQ work horse exits the moment the job returns, taking a daemon
    thread with it. The dispatch registers its thread so the job can wait,
    bounded, for the cards to land (founder 2026-10-14, the wait)."""

    def test_the_job_can_wait_for_the_cards(self):
        import threading
        from unittest.mock import patch
        import services.say_it_stronger as sis

        done = threading.Event()
        with patch.object(sis, "_generate_all",
                          lambda *a, **k: done.set()):
            sis.dispatch_say_it_stronger(
                "sess-wait", [{"id": "s1", "transcript": "x"}])
            self.assertTrue(sis.wait_for_cards("sess-wait", timeout=5))
        self.assertTrue(done.is_set())
        # Nothing left to wait for is not a failure.
        self.assertTrue(sis.wait_for_cards("sess-wait"))


class GuardCopyTests(unittest.TestCase):
    """AC-9: user-facing coaching copy — no digits, no construct family."""

    def _g(self, text):
        from services.say_it_stronger import _guard_copy
        return _guard_copy(text)


    def test_construct_vocabulary_rejected(self):
        for bad in ("your threat:challenge read improved",
                    "a higher charisma score here",
                    "the stress classifier flagged this",
                    "watch the KPI"):
            self.assertIsNone(self._g(bad))


try:
    from flask import Flask
    from flask import request as _flask_request

    _ROUTE_IMPORT_ERROR = None
except Exception as _e:  # pragma: no cover
    Flask = None
    _flask_request = None
    _ROUTE_IMPORT_ERROR = _e


if __name__ == "__main__":
    unittest.main()
