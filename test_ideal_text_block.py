"""willab — the one-block ideal text (founder 2026-07-15).

services/ideal_text_block.py: auto-assembly from the arc's picks (bold
openings + [[moment:…]] anchors) and the anchor parser the served
key_moments list derives from.

Run: python3 -m unittest test_ideal_text_block
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

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


def _bp(ready=True, slides=None):
    return {
        "ready": ready,
        "slides": slides if slides is not None else [
            {"index": 0, "text": "We open with the mission and the team.",
             "key_phrases": ["the mission"], "breakthrough": False,
             "snippet_id": "s0", "session_id": "t0"},
            {"index": 1, "text": "This quarter we tripled throughput.",
             "key_phrases": [], "breakthrough": True,
             "snippet_id": SNIP, "session_id": SESS},
            {"index": 2, "text": "", "key_phrases": [],
             "breakthrough": False, "snippet_id": None, "session_id": None},
        ],
    }


class AssembleTests(unittest.TestCase):

    def _run(self, bp):
        from services import ideal_text_block as mod
        with patch("services.best_presentation.build_best_presentation",
                   return_value=bp):
            return mod.assemble_ideal_text_block("arc1")

    def test_bolds_openings_and_anchors_breakthroughs(self):
        out = self._run(_bp())
        self.assertTrue(out["ready"])
        text = out["text"]
        self.assertIn("**the mission**", text)                # bold opening
        self.assertIn(f"[[moment:{SNIP}|{SESS}]]", text)      # anchor opens
        self.assertIn("[[/moment]]", text)
        self.assertEqual(out["key_moments"], [
            {"snippet_id": SNIP, "take_session_id": SESS},
        ])
        # the empty slide contributed nothing
        self.assertNotIn("\n\n\n", text)

    def test_not_ready_below_three_takes(self):
        out = self._run(_bp(ready=False))
        self.assertFalse(out["ready"])
        self.assertEqual(out["text"], "")
        self.assertEqual(out["key_moments"], [])

    def test_no_anchor_without_ids(self):
        bp = _bp(slides=[{"index": 0, "text": "Great line.",
                          "key_phrases": [], "breakthrough": True,
                          "snippet_id": None, "session_id": None}])
        out = self._run(bp)
        self.assertNotIn("[[moment:", out["text"])
        self.assertEqual(out["key_moments"], [])


class ExtractKeyMomentsTests(unittest.TestCase):

    def test_parses_anchors_from_coach_edited_text(self):
        from services.ideal_text_block import extract_key_moments
        text = (f"Intro here. [[moment:{SNIP}|{SESS}]]the turn[[/moment]] "
                f"and again [[moment:{SNIP}|{SESS}]]dup[[/moment]].")
        out = extract_key_moments(text)
        self.assertEqual(out, [
            {"snippet_id": SNIP, "take_session_id": SESS},
        ])  # deduped

    def test_deleted_anchor_deletes_the_deep_link(self):
        from services.ideal_text_block import extract_key_moments
        self.assertEqual(extract_key_moments("plain coach text, no anchors"),
                         [])
        self.assertEqual(extract_key_moments(None), [])
        self.assertEqual(extract_key_moments(123), [])


if __name__ == "__main__":
    unittest.main()
