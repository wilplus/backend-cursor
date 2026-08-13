"""The served change list — anchors, grain, and lane precedence.

Run: python3 -m unittest test_tracked_changes
"""
from __future__ import annotations

import unittest

from services import tracked_changes as tc


class AcousticSwapServeTests(unittest.TestCase):
    """Stage 5 — the swap lane's serve contract (founder 2026-08-13)."""

    DOC = "First part words here.\n\nSecond part words here."

    def _piece(self, grain):
        return {"snippet_id": "s1", "start": 24, "end": 47,
                "text": "Second part words here.", "anchor_grain": grain}

    def _sug(self, trigger):
        return {"s1": {"kind": "replace", "trigger": trigger,
                       "replacement_text": "Second part words, better said."}}

    def test_it_gets_its_OWN_source_not_wording(self):
        """The FE labels it 'Delivery' and the anchoring exemption keys on it;
        both need it distinguishable from an ordinary replace, and the internal
        trigger never rides the payload."""
        out = tc.build_tracked_changes(
            self.DOC, [self._piece("word")], self._sug("acoustic_swap"))
        self.assertEqual(out[0]["source"], "acoustic_swap")

    def test_it_SURVIVES_paragraph_grain_where_a_plain_replace_declines(self):
        """THE EXEMPTION, and the one comparison that shows why it is not a
        weakening. A locked chunk is exactly what gets a coarse anchor, so the
        decline would mute this lane precisely where it applies — and unlike an
        ordinary replace, whole-paragraph IS this lane's claim rather than a
        silently widened one."""
        piece = self._piece("paragraph")
        swap = tc.build_tracked_changes(
            self.DOC, [piece], self._sug("acoustic_swap"))
        plain = tc.build_tracked_changes(
            self.DOC, [piece], self._sug(None))
        self.assertEqual(len(swap), 1)
        self.assertEqual(swap[0]["quote"], "Second part words here.")
        self.assertEqual(plain, [])          # the rule still holds elsewhere

    def test_the_internal_trigger_never_rides_the_payload(self):
        out = tc.build_tracked_changes(
            self.DOC, [self._piece("word")], self._sug("acoustic_swap"))
        self.assertNotIn("acoustic_swap", str(out[0].get("why") or ""))
        self.assertNotIn("trigger", out[0])


class LanePrecedenceTests(unittest.TestCase):
    """Corrections > Swap > Style when two lanes want the same words."""

    def _c(self, source, start, end, kind="replace"):
        return {"source": source, "kind": kind,
                "span": {"start": start, "end": end}, "quote": "x"}

    def test_a_correction_beats_a_swap_on_the_same_span(self):
        kept = tc.drop_overlaps([self._c("acoustic_swap", 0, 40),
                                 self._c("wording", 0, 40)])
        self.assertEqual([c["source"] for c in kept], ["wording"])

    def test_a_swap_beats_a_STYLE_bold_it_contains(self):
        """Width alone got this backwards: the swap's span is a whole
        paragraph by construction, so the narrower-wins tie-break handed every
        collision to a 'make this word orange' suggestion."""
        kept = tc.drop_overlaps([self._c("acoustic_swap", 0, 40),
                                 self._c("wording", 0, 8, kind="bold")])
        self.assertEqual([c["source"] for c in kept], ["acoustic_swap"])

    def test_non_overlapping_lanes_all_survive(self):
        kept = tc.drop_overlaps([self._c("acoustic_swap", 0, 20),
                                 self._c("wording", 30, 40)])
        self.assertEqual(len(kept), 2)
