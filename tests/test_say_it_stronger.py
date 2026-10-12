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
