"""The served change list — anchors, grain, and lane precedence.

Run: python3 -m unittest tests.test_tracked_changes
"""
from __future__ import annotations

import unittest

from services import tracked_changes as tc


class LanePrecedenceTests(unittest.TestCase):
    """Corrections > Swap > Style when two lanes want the same words."""

    def _c(self, source, start, end, kind="replace"):
        return {"source": source, "kind": kind,
                "span": {"start": start, "end": end}, "quote": "x"}


    def test_a_swap_beats_a_STYLE_bold_it_contains(self):
        """Width alone got this backwards: the swap's span is a whole
        paragraph by construction, so the narrower-wins tie-break handed every
        collision to a 'make this word orange' suggestion."""
        kept = tc.drop_overlaps([self._c("acoustic_swap", 0, 40),
                                 self._c("wording", 0, 8, kind="bold")])
        self.assertEqual([c["source"] for c in kept], ["acoustic_swap"])


class BuildTrackedChangesPinTests(unittest.TestCase):
    """What build_tracked_changes serves, pinned before its split into named
    stages (audit W1, 2026-09-28): the refusals, one exact entry per lane,
    the cue filter, the fallbacks and the order."""

    DOC = "We ship fast.\n\nThen we listen closely."
    FIRST = {"snippet_id": "s1", "take_session_id": "t1", "start": 0,
             "end": 13, "text": "We ship fast."}
    SECOND = {"snippet_id": "s2", "take_session_id": "t1", "start": 15,
              "end": 38, "text": "Then we listen closely."}

    def _build(self, suggestions, pieces=None, **kwargs):
        return tc.build_tracked_changes(
            self.DOC, [self.FIRST, self.SECOND] if pieces is None else pieces,
            suggestions, **kwargs)

    def test_refusals(self):
        wording = {"kind": "replace", "replacement_text": "We move fast."}
        self.assertEqual(tc.build_tracked_changes(None, [self.FIRST],
                                                  {"s1": wording}), [])
        self.assertEqual(tc.build_tracked_changes("", [self.FIRST],
                                                  {"s1": wording}), [])
        self.assertEqual(self._build({"s1": wording}, pieces=[
            "not a piece",
            dict(self.FIRST, snippet_id=""),
            dict(self.FIRST, start="x"),
            {k: v for k, v in self.FIRST.items() if k != "end"},
            dict(self.FIRST, start=None),
            dict(self.FIRST, text="Other words."),
        ]), [])
        self.assertEqual(self._build({"s1": "not a row"}), [])
        self.assertEqual(self._build({"s1": {"kind": "mystery"}}), [])
        self.assertEqual(self._build({"s1": wording}, applied=["s1"]), [])
        self.assertEqual(self._build(None), [])
        self.assertEqual(self._build(
            {"s1": {"kind": "replace", "replacement_text": "   "}}), [])
