"""
STORY    As a speaker, I want the most important suggestion to win when two
         want the same words, so that I see a real correction, not a minor
         style tip.
OUTCOME
  O1  On the same words a correction beats a swap, and a swap beats a style
      bold.
  O2  A wording suggestion becomes one change on its own words; bad input
      (a piece whose words are not in the document, an unknown suggestion
      kind, an already-approved moment) builds nothing.
PROVES   O1 -> test_a_correction_beats_a_swap_on_the_same_words
            -> test_a_swap_beats_a_STYLE_bold_it_contains
         O2 -> test_a_wording_suggestion_builds_one_change_and_bad_input_none
WHY      Founder 2026-08-13: span width alone handed every collision to a
         'make this word orange' suggestion.
"""
from __future__ import annotations

import unittest

from services import tracked_changes as tc


class LanePrecedenceTests(unittest.TestCase):
    """Corrections > Swap > Style when two lanes want the same words."""

    def _c(self, source, start, end, kind="replace"):
        return {"source": source, "kind": kind,
                "span": {"start": start, "end": end}, "quote": "x"}

    def test_a_correction_beats_a_swap_on_the_same_words(self):
        kept = tc.drop_overlaps([self._c("acoustic_swap", 0, 8),
                                 self._c("wording", 0, 40)])
        self.assertEqual([c["source"] for c in kept], ["wording"])

    def test_a_swap_beats_a_STYLE_bold_it_contains(self):
        kept = tc.drop_overlaps([self._c("acoustic_swap", 0, 40),
                                 self._c("wording", 0, 8, kind="bold")])
        self.assertEqual([c["source"] for c in kept], ["acoustic_swap"])


class BuildTrackedChangesTests(unittest.TestCase):

    DOC = "We ship fast.\n\nThen we listen closely."
    FIRST = {"snippet_id": "s1", "take_session_id": "t1", "start": 0,
             "end": 13, "text": "We ship fast."}
    WORDING = {"kind": "replace", "replacement_text": "We move fast."}

    def _build(self, suggestions, pieces=None, **kwargs):
        return tc.build_tracked_changes(
            self.DOC, [self.FIRST] if pieces is None else pieces,
            suggestions, **kwargs)

    def test_a_wording_suggestion_builds_one_change_and_bad_input_none(self):
        changes = self._build({"s1": self.WORDING})
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["span"], {"start": 0, "end": 13})
        self.assertEqual(changes[0]["quote"], "We ship fast.")
        self.assertEqual(changes[0]["proposed_text"], "We move fast.")

        self.assertEqual(self._build({"s1": self.WORDING},
                                     pieces=[dict(self.FIRST, text="Other words.")]), [])
        self.assertEqual(self._build({"s1": {"kind": "mystery"}}), [])
        self.assertEqual(self._build({"s1": self.WORDING}, applied=["s1"]), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
