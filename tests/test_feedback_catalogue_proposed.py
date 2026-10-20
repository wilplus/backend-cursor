"""
STORY    As the founder, I want the drafted praise lines and rewrite moves to
         stay off until I sign them, and every line to be safe copy, so that
         no unsigned or numeric words reach a speaker.
OUTCOME
  O1  Never-4 (no new words on screen without the founder's OK): while
      PROPOSED_LINES_SIGNED is False, `decorate` serves the speaker's
      feedback rows untouched -- no proposed praise_line or rewrite_move.
  O2  Once signed, the tentative praise gets its tentative line, a filler
      rewrite gets the move its words made, and a line in the table wins
      over the proposed floor.
  O3  Never-1 (no scores or numbers to speakers): every proposed line has no
      digit, no construct word, nothing about feelings or other people.
  O4  Tentative evidence gets tentative words.
PROVES   O1 -> test_unsigned_lines_reach_no_speaker
         O2 -> test_signed_lines_are_the_floor
         O3 -> test_no_number_no_construct_no_feelings_no_one_else
         O4 -> test_tentative_evidence_gets_tentative_words
WHY      Founder 2026-10-05, decisions log N48.6, Q29 A: drafted for signature.
"""
from __future__ import annotations

import re
import unittest
from unittest import mock

from services import feedback_catalogue as fc
from services import take_feedback_manager as tfm
from services.say_it_stronger import _GUARD_CONSTRUCT_RE

TEXT = "So we built the whole thing. It works."


def _proposed(lane, kind, key):
    return next(line[3] for line in fc.PROPOSED_LINES
                if line[:3] == (lane, kind, key))


def _served_rows():
    """The Manager's fallback rewrite and tentative praise for one Take,
    the rows the proposed lines are drafted to decorate."""
    rows = tfm.ensure_required_families(
        TEXT, [], take_session_id="take-1", snippet_id="snip-1")
    by_family = {row["feedback_family"]: row for row in rows}
    return rows, by_family["great_formulation"], by_family["rewrite_clarity"]


class TheDraftTests(unittest.TestCase):

    def test_unsigned_lines_reach_no_speaker(self):
        self.assertIs(fc.PROPOSED_LINES_SIGNED, False)
        self.assertEqual(fc.floor_rows(), [])
        rows, _, _ = _served_rows()
        served = fc.decorate(rows, [])
        self.assertEqual(len(served), 2)  # the feedback itself still serves
        for row in served:
            self.assertNotIn("praise_line", row)
            self.assertNotIn("rewrite_move", row)
            self.assertTrue(row["quote"])

    def test_signed_lines_are_the_floor(self):
        rows, praise, rewrite = _served_rows()
        with mock.patch.object(fc, "PROPOSED_LINES_SIGNED", True):
            served = {r["feedback_family"]: r for r in fc.decorate(rows, [])}
            self.assertEqual(
                served["great_formulation"]["praise_line"],
                _proposed("praise", "device", fc.TENTATIVE_FORMULATION))
            self.assertEqual(
                served["rewrite_clarity"]["rewrite_move"],
                _proposed("rewrite", "move", fc.DROP_THE_FILLER))
            signed = {"lane": "praise", "pattern_kind": "device",
                      "pattern_key": fc.TENTATIVE_FORMULATION,
                      "text": "The founder's own words.", "version": 1}
            [over] = fc.decorate([praise], [signed])
            self.assertEqual(over["praise_line"], "The founder's own words.")
        self.assertEqual(rewrite["why_key"], "clarity_tentative")

    def test_no_number_no_construct_no_feelings_no_one_else(self):
        banned = re.compile(
            r"\b(?:engaging|charisma\w*|stress\w*|threat\w*|challenge\w*|"
            r"score\w*|rank\w*|average|percent\w*|best|worst|perfect\w*|"
            r"feel\w*|felt|nervous|anxious|unsure|hedg\w*|"
            r"people|others?|everyone|anyone)\b", re.IGNORECASE)
        self.assertEqual(len(fc.PROPOSED_LINES), 12)  # nine praise, three moves
        for _, _, key, text in fc.PROPOSED_LINES:
            self.assertTrue(text.strip(), key)
            self.assertFalse(any(ch.isdigit() for ch in text), key)
            self.assertIsNone(_GUARD_CONSTRUCT_RE.search(text), key)
            self.assertIsNone(banned.search(text), f"{key}: {text}")

    def test_tentative_evidence_gets_tentative_words(self):
        self.assertIn("still room to improve",
                      _proposed("praise", "device", fc.TENTATIVE_FORMULATION))
        for move in (fc.DROP_THE_FILLER, fc.SPLIT_THE_CLAUSE):
            self.assertTrue(_proposed("rewrite", "move", move).startswith("Try "))
        # The fallback rows these lines sit on are tentative themselves.
        _, praise, rewrite = _served_rows()
        self.assertTrue(praise["tentative"])
        self.assertTrue(rewrite["tentative"])


if __name__ == "__main__":
    unittest.main()
