"""Paid Audits — Ideal-Text report mapping (BE chunk A7). Pure.

Run: python3 -m unittest test_ideal_text_report
"""
from __future__ import annotations

import unittest
from unittest import mock

from services.ideal_text_report import build_ideal_text_report


_FAKE_BP = {
    "ready": True,
    "name": "Booksy pitch",
    "coach_reviewed": True,
    "presentation_ref": "s3://decks/booksy.pdf",
    "progress": {"takes_done": 3, "takes_target": 3, "takes_remaining": 0, "ready": True},
    "slides": [
        {"index": 0, "title": "Opening", "body": "the hook",
         "text": "We are raising two million dollars.", "take_index": 2,
         "breakthrough": True},
        {"index": 1, "title": "Market", "body": "the size",
         "text": "The market is forty billion.", "take_index": 1,
         "breakthrough": False},
    ],
}


class IdealTextReportTests(unittest.TestCase):
    def _build(self, bp=None):
        with mock.patch(
            "services.best_presentation.build_best_presentation",
            return_value=(bp if bp is not None else _FAKE_BP),
        ):
            return build_ideal_text_report("arc1")

    def test_top_level_fields(self):
        out = self._build()
        self.assertEqual(out["talkId"], "arc1")
        self.assertEqual(out["talkTitle"], "Booksy pitch")
        self.assertTrue(out["ready"])
        self.assertTrue(out["coachReviewed"])
        self.assertEqual(out["presentationRef"], "s3://decks/booksy.pdf")

    def test_slide_mapping_verbatim_text(self):
        out = self._build()
        s0 = out["slides"][0]
        self.assertEqual(s0["index"], 0)
        self.assertEqual(s0["label"], "Opening")
        # L1: idealText is the verbatim selected take text, not re-summarised.
        self.assertEqual(s0["idealText"], "We are raising two million dollars.")
        self.assertEqual(s0["takeRoute"], "/audit/arc1/take/2")
        self.assertIsNone(s0["thumbnailUrl"])
        self.assertTrue(s0["breakthrough"])

    def test_take_route_uses_each_slides_winning_take(self):
        out = self._build()
        self.assertEqual(out["slides"][1]["takeRoute"], "/audit/arc1/take/1")

    def test_not_ready_arc_still_maps(self):
        bp = dict(_FAKE_BP, ready=False, name=None, slides=[])
        out = self._build(bp)
        self.assertFalse(out["ready"])
        self.assertIsNone(out["talkTitle"])
        self.assertEqual(out["slides"], [])


if __name__ == "__main__":
    unittest.main()
