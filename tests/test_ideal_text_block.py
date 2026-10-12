"""willab — the one-block ideal text (founder 2026-07-15).

services/ideal_text_block.py: the canonical document is never rebuilt by a
later Take, and the anchor parser the served key_moments list derives from.
(The best-of assembly from the arc's picks is removed, N48.3 Q13 A.)

Run: python3 -m unittest tests.test_ideal_text_block
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock

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


SNIP = "11111111-1111-4111-8111-111111111111"
SESS = "22222222-2222-4222-8222-222222222222"


class ExtractKeyMomentsTests(unittest.TestCase):


    def test_legacy_unclosed_marker_still_parses_with_empty_anchor(self):
        from services.ideal_text_block import extract_key_moments
        out = extract_key_moments(f"[[moment:{SNIP}|{SESS}]]no closing tag")
        self.assertEqual(out, [
            {"snippet_id": SNIP, "take_session_id": SESS, "anchor": ""},
        ])


if __name__ == "__main__":
    unittest.main()
