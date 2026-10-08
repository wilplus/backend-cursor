"""The proposed praise lines and rewrite moves (founder 2026-10-05,
decisions log N48.6, Q29 A: "the nine praise lines and three rewrite moves
are drafted by the session for the founder's signature").

What this pins down:

  * OFF IS TODAY. `PROPOSED_LINES_SIGNED` is False in the source; the floor
    is empty; `decorate` and the page's catalogue stage behave exactly as
    before, including a rewrite move filed in the table under a move key,
    which stays unserved until the founder signs;
  * THE DRAFT IS WHAT THE SHEET SAYS: nine praise lines (one per delivery
    cue the backend can name, the confident read, the Manager's tentative
    fallback) and three moves, keyed to patterns the code really emits;
  * EVERY LINE IS SPEAKABLE COPY: a valid catalogue line, no digit (AC-9),
    no retired construct word, nothing about feelings or other people, and
    tentative words where the evidence is tentative;
  * ON, the lines are the floor (E3): each cue row gets its line, the
    tentative fallback keeps tentative words instead of the confident read's
    line, a version in the table wins over the floor, and each rewrite the
    Manager's own rules write gets the move its words made.

Run: python3 -m pytest tests/test_feedback_catalogue_proposed.py
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from services import feedback_catalogue as fc
from services import take_feedback_manager as tfm
from services.delivery_cues import CUE_KEYS
from services.ideal_text_changes import _ChangesRun
from services.say_it_stronger import _GUARD_CONSTRUCT_RE

ROOT = Path(__file__).resolve().parent.parent
SIGNED = patch.object(fc, "PROPOSED_LINES_SIGNED", True)

TAKE, SNIP = "take-1", "snip-1"


def _proposed(lane, kind, key):
    return next(line[3] for line in fc.PROPOSED_LINES
                if line[:3] == (lane, kind, key))


def _candidates(text):
    return [(0, len(text), text)]


def _fallback_praise(text="We built it."):
    return tfm._fallback_praise(_candidates(text), take=TAKE, snippet_id=SNIP)


def _fallback_rewrite(text):
    return tfm._fallback_rewrite(_candidates(text), take=TAKE, snippet_id=SNIP)


def _structural_rewrite(text="I don't want. A script is not the point."):
    rows = tfm.evidence_backed_rewrite_candidates(
        text, take_session_id=TAKE, snippet_id=SNIP)
    assert rows, "the structural rule found nothing to repair"
    return rows[0]


def _cue_praise(*cues):
    return {"feedback_family": "great_formulation", "device": "impeccable",
            "source": "delivery", "cue_keys": list(cues), "quote": "We did it."}


def _polish_rewrite():
    return {"feedback_family": "rewrite_clarity", "kind": "replace",
            "source": "polish", "why_key": "clarity",
            "quote": "We did it fast.", "proposed_text": "We moved quickly."}


class _Db:
    def __init__(self, rows=None):
        self.rows = rows or []

    def list_feedback_catalogue(self, active_only=True):
        return list(self.rows)


def _page_stage(changes, rows=None):
    """The page's catalogue stage on a stand-in run: only the three
    attributes `_ChangesRun._catalogue` reads."""
    run = SimpleNamespace(db=_Db(rows), arc_id="arc-1", changes=changes)
    _ChangesRun._catalogue(run)
    return run.changes


class OffIsTodayTests(unittest.TestCase):
    def test_the_switch_is_off_in_the_source(self):
        source = (ROOT / "services" / "feedback_catalogue.py").read_text()
        self.assertIn("\nPROPOSED_LINES_SIGNED = False\n", source)
        self.assertFalse(fc.proposed_lines_signed())

    def test_the_floor_is_empty(self):
        self.assertEqual(fc.floor_rows(), [])

    def test_decorate_without_a_table_is_untouched(self):
        rows = [_fallback_praise(), _fallback_rewrite("So we built the whole thing."),
                _cue_praise("wide_range"), _structural_rewrite()]
        out = fc.decorate(rows, [])
        self.assertEqual(out, rows)
        for before, after in zip(rows, out):
            self.assertIs(before, after)

    def test_a_move_key_in_the_table_is_not_served_until_signed(self):
        table = [{"lane": "rewrite", "pattern_kind": "move",
                  "pattern_key": fc.DROP_THE_FILLER, "text": "Drop it.",
                  "version": 1, "active": True}]
        row = _fallback_rewrite("So we built the whole thing in a week.")
        self.assertEqual(fc.move_of(row), fc.DROP_THE_FILLER)
        self.assertNotIn("rewrite_move", fc.decorate([row], table)[0])

    def test_the_page_stage_does_not_decorate_without_a_table(self):
        rows = [_fallback_praise()]
        with patch.object(fc, "decorate", side_effect=AssertionError("called")):
            self.assertIs(_page_stage(rows), rows)


class TheDraftTests(unittest.TestCase):
    def test_nine_praise_lines_and_three_moves(self):
        praise = [p for p in fc.PROPOSED_LINES if p[0] == "praise"]
        moves = [p for p in fc.PROPOSED_LINES if p[0] == "rewrite"]
        self.assertEqual((len(praise), len(moves)), (9, 3))
        keys = [(lane, kind, key) for lane, kind, key, _ in fc.PROPOSED_LINES]
        self.assertEqual(len(set(keys)), len(keys))

    def test_one_line_per_cue_the_backend_can_name(self):
        cues = {key for lane, kind, key, _ in fc.PROPOSED_LINES
                if (lane, kind) == ("praise", "cue")}
        self.assertEqual(cues, set(CUE_KEYS))

    def test_the_read_and_the_fallback_device_are_the_ones_served(self):
        self.assertIn(("praise", "read", fc.CONFIDENT_READ),
                      [p[:3] for p in fc.PROPOSED_LINES])
        # The device key is the one the Manager's tentative praise carries.
        fallback = _fallback_praise()
        self.assertEqual(fallback["device"], fc.TENTATIVE_FORMULATION)
        self.assertTrue(fallback["tentative"])
        self.assertIn(("praise", "device", fallback["device"]),
                      [p[:3] for p in fc.PROPOSED_LINES])

    def test_the_moves_are_the_three_the_coach_panel_files(self):
        moves = [key for lane, _, key, _ in fc.PROPOSED_LINES
                 if lane == "rewrite"]
        self.assertEqual(tuple(moves), fc.REWRITE_MOVES)

    def test_every_line_is_a_valid_catalogue_line(self):
        for lane, kind, key, text in fc.PROPOSED_LINES:
            row = fc.validate_line({"lane": lane, "pattern_kind": kind,
                                    "pattern_key": key, "text": text})
            self.assertEqual(row["text"], text)

    def test_no_number_no_construct_no_feelings_no_one_else(self):
        banned = re.compile(
            r"\b(?:engaging|charisma\w*|stress\w*|threat\w*|challenge\w*|"
            r"score\w*|rank\w*|average|percent\w*|best|worst|perfect\w*|"
            r"feel\w*|felt|nervous|anxious|unsure|hedg\w*|"
            r"people|others?|everyone|anyone)\b", re.IGNORECASE)
        for _, _, key, text in fc.PROPOSED_LINES:
            self.assertFalse(any(ch.isdigit() for ch in text), key)
            self.assertIsNone(_GUARD_CONSTRUCT_RE.search(text), key)
            self.assertIsNone(banned.search(text), f"{key}: {text}")

    def test_tentative_evidence_gets_tentative_words(self):
        self.assertIn("still room to improve",
                      _proposed("praise", "device", fc.TENTATIVE_FORMULATION))
        for move in (fc.DROP_THE_FILLER, fc.SPLIT_THE_CLAUSE):
            self.assertTrue(_proposed("rewrite", "move", move).startswith("Try "))
        # The fallback rewrite these two moves sit on is tentative itself.
        self.assertTrue(_fallback_rewrite("So we built the whole thing.")["tentative"])


class SignedTests(unittest.TestCase):
    def setUp(self):
        SIGNED.start()
        self.addCleanup(SIGNED.stop)

    def test_the_floor_sits_beneath_every_table_version(self):
        rows = fc.floor_rows()
        self.assertEqual(len(rows), len(fc.PROPOSED_LINES))
        self.assertTrue(all(row["version"] == 0 and row["active"] for row in rows))

    def test_each_cue_row_gets_its_own_line(self):
        for cue in CUE_KEYS:
            out = fc.decorate([_cue_praise(cue)], [])[0]
            self.assertEqual(out["praise_line"], _proposed("praise", "cue", cue))

    def test_the_strongest_named_cue_speaks(self):
        out = fc.decorate([_cue_praise("landed_ending", "wide_range")], [])[0]
        self.assertEqual(out["praise_line"],
                         _proposed("praise", "cue", "landed_ending"))

    def test_a_structural_praise_takes_the_confident_read_line(self):
        row = {"feedback_family": "great_formulation", "device": "contrast",
               "source": "structural", "quote": "Not louder, clearer."}
        self.assertEqual(fc.decorate([row], [])[0]["praise_line"],
                         _proposed("praise", "read", fc.CONFIDENT_READ))

    def test_the_tentative_fallback_keeps_tentative_words(self):
        # The defect this line exists for (W2 P1-4): with only a confident
        # read line, the fallback would be relabelled with it and lose its
        # tentative wording on the sheet.
        out = fc.decorate([_fallback_praise()], [])[0]
        self.assertEqual(out["praise_line"],
                         _proposed("praise", "device", fc.TENTATIVE_FORMULATION))
        self.assertNotEqual(out["praise_line"],
                            _proposed("praise", "read", fc.CONFIDENT_READ))

    def test_a_signed_table_version_wins_over_the_floor(self):
        table = [{"lane": "praise", "pattern_kind": "cue",
                  "pattern_key": "wide_range", "text": "A coach's own line.",
                  "version": 1, "active": True}]
        out = fc.decorate([_cue_praise("wide_range")], table)[0]
        self.assertEqual(out["praise_line"], "A coach's own line.")

    def test_each_managers_rewrite_gets_the_move_its_words_made(self):
        cases = [
            (_fallback_rewrite("So we built the whole thing in a week."),
             fc.DROP_THE_FILLER),
            (_fallback_rewrite(
                "We built the whole thing in a week, and it worked for every team."),
             fc.SPLIT_THE_CLAUSE),
            (_structural_rewrite(), fc.REPAIR_THE_STRUCTURE),
        ]
        for row, move in cases:
            self.assertEqual(fc.move_of(row), move, row["proposed_text"])
            out = fc.decorate([row], [])[0]
            self.assertEqual(out["rewrite_move"], _proposed("rewrite", "move", move))

    def test_a_rewrite_that_changes_the_words_made_no_move(self):
        row = _polish_rewrite()
        self.assertIsNone(fc.move_of(row))
        self.assertNotIn("rewrite_move", fc.decorate([row], [])[0])
        # Its reason's line, where one exists, still serves.
        table = [{"lane": "rewrite", "pattern_kind": "move",
                  "pattern_key": "clarity", "text": "Say it plainly.",
                  "version": 1, "active": True}]
        self.assertEqual(fc.decorate([row], table)[0]["rewrite_move"],
                         "Say it plainly.")

    def test_nothing_else_on_a_row_changes(self):
        row = _cue_praise("kept_moving")
        out = fc.decorate([row, {"feedback_family": "confident_voice"}], [])
        self.assertEqual({k: v for k, v in out[0].items() if k != "praise_line"}, row)
        self.assertNotIn("praise_line", out[1])
        self.assertNotIn("praise_line", row)

    def test_the_page_stage_decorates_from_the_floor_alone(self):
        out = _page_stage([_fallback_praise()])
        self.assertEqual(out[0]["praise_line"],
                         _proposed("praise", "device", fc.TENTATIVE_FORMULATION))


class MoveOfTests(unittest.TestCase):
    def test_not_a_rewrite_or_no_words(self):
        self.assertIsNone(fc.move_of(_cue_praise("wide_range")))
        self.assertIsNone(fc.move_of({"feedback_family": "rewrite_clarity"}))
        self.assertIsNone(fc.move_of({"feedback_family": "rewrite_clarity",
                                      "quote": "Same.", "proposed_text": "Same."}))
        self.assertIsNone(fc.move_of("not a row"))

    def test_same_words_same_sentences_is_no_move(self):
        row = {"feedback_family": "rewrite_clarity", "kind": "replace",
               "quote": "We did it, fast.", "proposed_text": "We did it fast."}
        self.assertIsNone(fc.move_of(row))


if __name__ == "__main__":
    unittest.main()
