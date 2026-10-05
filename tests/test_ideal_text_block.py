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


class CanonicalPersistenceTests(unittest.TestCase):

    def test_later_take_never_rebuilds_existing_ideal_text(self):
        from services.ideal_text_block import maybe_assemble_ideal_text

        database = MagicMock()
        database.ideal_text.get_coach_arc_ideal_text.return_value = {
            "auto_text": "The Take 1 Ideal Text",
            "version": 1,
        }

        self.assertTrue(maybe_assemble_ideal_text(
            "arc1", database=database, require_target=False,
        ))
        database.persist_auto_ideal_text.assert_not_called()


class ExtractKeyMomentsTests(unittest.TestCase):

    def test_parses_anchors_from_coach_edited_text(self):
        from services.ideal_text_block import extract_key_moments
        text = (f"Intro here. [[moment:{SNIP}|{SESS}]]the turn[[/moment]] "
                f"and again [[moment:{SNIP}|{SESS}]]dup[[/moment]].")
        out = extract_key_moments(text)
        self.assertEqual(out, [
            # anchor = the moment's inner text (the FE's underline fragment)
            {"snippet_id": SNIP, "take_session_id": SESS, "anchor": "the turn"},
        ])  # deduped

    def test_anchor_is_the_inner_span_verbatim(self):
        from services.ideal_text_block import extract_key_moments
        # inner text carries nested formatting → the anchor keeps it verbatim
        # (a substring of the served text, so the FE's indexOf matches).
        text = f"[[moment:{SNIP}|{SESS}]]This is **the** turn[[/moment]]"
        out = extract_key_moments(text)
        self.assertEqual(out[0]["anchor"], "This is **the** turn")

    def test_legacy_unclosed_marker_still_parses_with_empty_anchor(self):
        from services.ideal_text_block import extract_key_moments
        out = extract_key_moments(f"[[moment:{SNIP}|{SESS}]]no closing tag")
        self.assertEqual(out, [
            {"snippet_id": SNIP, "take_session_id": SESS, "anchor": ""},
        ])

    def test_deleted_anchor_deletes_the_deep_link(self):
        from services.ideal_text_block import extract_key_moments
        self.assertEqual(extract_key_moments("plain coach text, no anchors"),
                         [])
        self.assertEqual(extract_key_moments(None), [])
        self.assertEqual(extract_key_moments(123), [])


if __name__ == "__main__":
    unittest.main()
