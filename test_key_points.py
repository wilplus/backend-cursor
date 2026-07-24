"""willab — presentation-mode cue sheet (E-1 v1, founder 2026-07-24).

Pins: one verbatim starting-point milestone per master-document block, the
sentence/word cut (a comma is NOT a break), offset-exactness (leading space
skipped so the FE anchors like a tracked change), and junk-safety. L1: the
milestone text is always a verbatim prefix of the block's own words.

Run: python3 -m unittest test_key_points
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.key_points import _opening_clause, build_key_points

try:
    from routes import v2_routes as v2
    _V2_ERR = None
except Exception as e:  # pragma: no cover
    v2 = None
    _V2_ERR = e


def _piece(block_key, start, text, label=None):
    return {"block_key": block_key, "block_label": label,
            "start": start, "end": start + len(text), "text": text}


class OpeningClauseTests(unittest.TestCase):
    def test_cuts_at_sentence_end(self):
        self.assertEqual(
            _opening_clause("Welcome everyone to the demo. And more."),
            "Welcome everyone to the demo")

    def test_comma_is_not_a_break(self):
        # a short comma'd phrase stays whole (under the cap, no sentence end)
        self.assertEqual(
            _opening_clause("First, second and third"),
            "First, second and third")

    def test_long_opening_trims_to_word_boundary_within_cap(self):
        s = ("the core idea is that we measure real delivery not vibes "
             "across every take")
        out = _opening_clause(s)
        self.assertLessEqual(len(out), 48)
        self.assertTrue(s.startswith(out))          # verbatim prefix
        self.assertFalse(out.endswith(" "))         # clean word boundary

    def test_empty_and_short(self):
        self.assertEqual(_opening_clause(""), "")
        self.assertEqual(_opening_clause("Short"), "Short")


class BuildKeyPointsTests(unittest.TestCase):
    def _kp(self):
        pieces = [
            _piece(0, 0, "Welcome everyone to the demo. And more.", "Hook"),
            _piece(0, 50, "second piece of the same block"),   # ignored
            _piece(10, 103, "The core idea is that we measure delivery, "
                            "not vibes, across many takes.", "Core"),
            _piece(20, 200, "Thanks.", "Closer"),
            _piece(30, 300, "   "),                             # empty → skip
        ]
        return build_key_points(pieces), pieces

    def test_one_milestone_per_block_in_order(self):
        kp, _ = self._kp()
        self.assertEqual([e["block_key"] for e in kp], [0, 10, 20])
        self.assertEqual([e["block_label"] for e in kp],
                         ["Hook", "Core", "Closer"])

    def test_first_block_verbatim_and_anchored(self):
        kp, _ = self._kp()
        e = kp[0]
        self.assertEqual(e["text"], "Welcome everyone to the demo")
        self.assertEqual(e["start"], 0)
        self.assertEqual(e["end"], len(e["text"]))

    def test_first_piece_by_start_wins_the_block(self):
        kp, _ = self._kp()
        # block 0 has two pieces (start 0 and 50); the start-0 one is the cue
        self.assertTrue(kp[0]["text"].startswith("Welcome"))

    def test_offset_skips_leading_whitespace_and_stays_verbatim(self):
        # leading spaces on the raw text must not shift the anchor
        pieces = [_piece(0, 100, "   Hello there, friends. Rest.")]
        e = build_key_points(pieces)[0]
        self.assertEqual(e["start"], 103)                # 100 + 3 spaces
        self.assertEqual(e["text"], "Hello there, friends")
        self.assertEqual(e["end"], 103 + len(e["text"]))

    def test_long_block_capped(self):
        kp, _ = self._kp()
        core = kp[1]
        self.assertLessEqual(len(core["text"]), 48)
        self.assertTrue(core["text"].startswith("The core idea"))

    def test_served_text_is_the_l1_source(self):
        # served_text wins over a stale piece.text, and offsets index into it
        served = "XXXXX Grab their attention first. Then the ask."
        pieces = [{"block_key": 0, "block_label": "Hook",
                   "start": 6, "end": 32, "text": "STALE PIECE TEXT"}]
        e = build_key_points(pieces, served)[0]
        self.assertEqual(served[e["start"]:e["end"]], e["text"])  # verbatim
        self.assertTrue(e["text"].startswith("Grab their attention"))
        self.assertNotIn("STALE", e["text"])

    def test_junk_is_safe(self):
        self.assertEqual(build_key_points(None), [])
        self.assertEqual(build_key_points("nope"), [])
        self.assertEqual(build_key_points([1, "x", None]), [])
        self.assertEqual(build_key_points([{}]), [])       # no text → skip


@unittest.skipIf(_V2_ERR is not None, f"needs app deps: {_V2_ERR}")
class KeyPointsServeWiringTests(unittest.TestCase):
    """The SD `_tracked_changes_block` surfaces `key_points` when the flag is
    on, and omits the key entirely when off (the FE is unaffected)."""

    def _run(self, *, flag):
        served = "Grab attention here. Then the ask lands."
        pieces = [{"block_key": 0, "block_label": "Hook",
                   "start": 0, "end": 20, "text": "Grab attention here."}]
        with patch.object(v2, "_key_points_enabled", return_value=flag), \
             patch("services.ideal_text_block._living_transcript_enabled",
                   return_value=True), \
             patch("services.master_document.master_document_enabled",
                   return_value=False), \
             patch("services.transcript_document.build_transcript_document",
                   return_value={"pieces": pieces, "take_session_id": None}), \
             patch("services.transcript_document.relocate_pieces",
                   side_effect=lambda t, p: p), \
             patch("services.tracked_changes.build_tracked_changes",
                   return_value=[]), \
             patch("services.tracked_changes.drop_overlaps",
                   side_effect=lambda c: c), \
             patch("services.tracked_changes.verify_changes",
                   return_value=True), \
             patch.object(v2, "_moment_applied_map", return_value={}), \
             patch.object(v2, "_previous_spoken_session", return_value=None), \
             patch.object(v2.db, "get_moment_suggestions_by_arc",
                          return_value={}):
            return v2._tracked_changes_block("a1", served)

    def test_flag_on_serves_the_cue_sheet(self):
        out = self._run(flag=True)
        self.assertIn("key_points", out)
        self.assertEqual(out["key_points"][0]["text"], "Grab attention here")
        self.assertEqual(out["key_points"][0]["block_label"], "Hook")

    def test_flag_off_omits_the_key(self):
        self.assertNotIn("key_points", self._run(flag=False))


if __name__ == "__main__":
    unittest.main()
