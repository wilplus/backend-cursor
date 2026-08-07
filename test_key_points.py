"""willab — presentation-mode cue sheet (E-1 v1, founder 2026-07-24).

Pins: one verbatim starting-point milestone per master-document block, the
sentence/word cut (a comma is NOT a break), offset-exactness (leading space
skipped so the FE anchors like a tracked change), and junk-safety. L1: the
milestone text is always a verbatim prefix of the block's own words.

Run: python3 -m unittest test_key_points
"""
from __future__ import annotations

import ast
import pathlib
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


class ParagraphFallbackTests(unittest.TestCase):
    """Founder 2026-07-27: blocks are keyed on slide index, so a DECKLESS
    project is ONE block, so the student's whole "Key words" view rendered as
    a single card. Below two blocks we cue per PARAGRAPH — same verbatim
    slice, same offsets."""

    def _doc(self, n):
        return "\n\n".join(
            f"Paragraph number {i} opens the section here. And then it "
            f"continues for a while afterwards." for i in range(n))

    def test_one_block_many_paragraphs_cues_each_paragraph(self):
        served = self._doc(5)
        pieces = [{"block_key": 0, "block_label": "All", "start": 0,
                   "end": len(served), "text": served}]
        kp = build_key_points(pieces, served)
        self.assertEqual(len(kp), 5)
        for e in kp:
            self.assertEqual(served[e["start"]:e["end"]], e["text"])
            self.assertIsNone(e["block_key"])
            self.assertIsNone(e["block_label"])

    def test_cues_are_in_document_order(self):
        served = self._doc(4)
        kp = build_key_points([], served)
        self.assertEqual([e["start"] for e in kp],
                         sorted(e["start"] for e in kp))

    def test_no_pieces_at_all_still_cues(self):
        served = self._doc(3)
        self.assertEqual(len(build_key_points([], served)), 3)

    def test_short_paragraphs_are_skipped(self):
        served = "So.\n\n" + self._doc(1) + "\n\nOk.\n\nRight."
        kp = build_key_points([], served)
        self.assertEqual(len(kp), 1)
        self.assertTrue(kp[0]["text"].startswith("Paragraph number 0"))

    def test_capped_at_twelve(self):
        kp = build_key_points([], self._doc(40))
        self.assertEqual(len(kp), 12)

    def test_single_paragraph_yields_one_cue_not_a_fabrication(self):
        served = self._doc(1)
        kp = build_key_points([], served)
        self.assertEqual(len(kp), 1)
        self.assertEqual(served[kp[0]["start"]:kp[0]["end"]], kp[0]["text"])

    def test_two_or_more_blocks_keep_the_block_path(self):
        served = ("Welcome to the demo today. More words here.\n\n"
                  "The core idea is measured delivery. More words.\n\n"
                  "Thanks for listening everyone. Goodbye now.")
        pieces = [
            {"block_key": 0, "block_label": "Hook", "start": 0,
             "end": 42, "text": served[0:42]},
            {"block_key": 10, "block_label": "Core", "start": 44,
             "end": 90, "text": served[44:90]},
        ]
        kp = build_key_points(pieces, served)
        self.assertEqual([e["block_key"] for e in kp], [0, 10])
        self.assertEqual([e["block_label"] for e in kp], ["Hook", "Core"])

    def test_no_served_text_keeps_the_block_path(self):
        pieces = [_piece(0, 0, "Only one block here. And more text.")]
        kp = build_key_points(pieces)
        self.assertEqual(len(kp), 1)
        self.assertEqual(kp[0]["block_key"], 0)

    def test_fallback_never_shrinks_the_result(self):
        # one block + a served text with a single usable paragraph: the block
        # path already has it, so nothing is lost by falling back
        served = "Only one usable paragraph in this whole document."
        pieces = [{"block_key": 0, "block_label": "Hook", "start": 0,
                   "end": len(served), "text": served}]
        kp = build_key_points(pieces, served)
        self.assertEqual(len(kp), 1)
        self.assertEqual(served[kp[0]["start"]:kp[0]["end"]], kp[0]["text"])

    def test_offsets_survive_leading_whitespace_between_paragraphs(self):
        served = ("First paragraph opens the talk here.\n   \n"
                  "Second one lands a while later on.")
        kp = build_key_points([], served)
        self.assertEqual(len(kp), 2)
        for e in kp:
            self.assertEqual(served[e["start"]:e["end"]], e["text"])

    def test_cue_carries_no_rank_or_score(self):
        # AC-9 / construct fence: a milestone is a cue, never a graded thing
        kp = build_key_points([], self._doc(3))
        for e in kp:
            self.assertEqual(set(e), {"block_key", "block_label", "text",
                                      "start", "end"})


@unittest.skipIf(_V2_ERR is not None, f"needs app deps: {_V2_ERR}")
class KeyPointsAreDeferredTests(unittest.TestCase):
    """The cue sheet is DEFERRED (founder 2026-08-07) — the student GET must
    not carry `key_points` under any flag.

    A highlighted verbatim opening phrase is indistinguishable on screen from
    an intervention that explains nothing, which is how it was read. The
    derivation stays (every test above still runs); only the surface is gone.
    Pinned as a test because "we removed the call site" is exactly the kind of
    deferral that gets undone by a merge nobody noticed."""

    def _run(self):
        served = "Grab attention here. Then the ask lands."
        pieces = [{"block_key": 0, "block_label": "Hook",
                   "start": 0, "end": 20, "text": "Grab attention here."}]
        with patch("services.ideal_text_block._living_transcript_enabled",
                   return_value=True), \
             patch("services.master_document.master_document_enabled",
                   return_value=False), \
             patch("services.transcript_document.build_transcript_document",
                   return_value={"pieces": pieces, "take_session_id": None}), \
             patch("services.transcript_document.relocate_pieces",
                   side_effect=lambda t, p: p), \
             patch("services.tracked_changes.build_tracked_changes",
                   return_value=[]), \
             patch("services.tracked_changes.verify_changes",
                   return_value=True), \
             patch("routes.v2.explore_ideal_text._moment_applied_map", return_value={}), \
             patch("routes.v2.explore_ideal_text._previous_spoken_session", return_value=None), \
             patch.object(v2.db, "get_moment_suggestions_by_arc",
                          return_value={}):
            return v2._tracked_changes_block("a1", served)

    def test_the_cue_sheet_never_reaches_the_student(self):
        self.assertNotIn("key_points", self._run())

    def test_the_flag_is_gone_rather_than_defaulted_off(self):
        """A flag left in place reads as "off for now" and invites a flip.
        The env var no longer does anything, and that has to be visible.

        Checked through the AST: a comment SAYING the flag is retired must not
        register as the flag still being read."""
        self.assertFalse(hasattr(v2, "_key_points_enabled"))
        tree = ast.parse((pathlib.Path(__file__).parent / "routes" / "v2"
                          / "explore_ideal_text.py").read_text())
        read_env = {a.value for n in ast.walk(tree)
                    if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "getenv"
                    for a in n.args if isinstance(a, ast.Constant)}
        self.assertNotIn("KEY_POINTS_ENABLED", read_env)
        called = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        imported = {a.name for n in ast.walk(tree)
                    if isinstance(n, ast.ImportFrom) for a in n.names}
        self.assertNotIn("build_key_points", called | imported)


if __name__ == "__main__":
    unittest.main()
