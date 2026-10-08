"""The doors' comments say what the constants say (build plan ML-1b; audit
2026-10-05).

Doors 1 and 2 opened on 2026-10-01 by the founder's sentences (doors 3 and
4 on 2026-10-08, "turn it all ON"), and four
files went on calling them dark or closed. A comment that contradicts the
constant it describes is how a reader trusts a door that is open, or
"opens" one twice. So each file's module docstring is tied to its
constant, both ways: while the door is open in code the docstring may not
call it closed and must say it is open; if a reviewed change closes it
again, this test names the files whose words must change in that change.
"""
from __future__ import annotations

import ast
import pathlib
import unittest

from config import Config

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: (file, the constant its docstring describes, words that claim the door
#: is closed, the words that say it is open).
_CLAIMS = (
    ("routes/v2/training_consent.py", "MLC2_TRAINING_SWITCH_ENABLED",
     ("DARK.", "until P5"), "OPEN since 2026-10-01"),
    ("services/training_consent.py", "MLC2_TRAINING_SWITCH_ENABLED",
     ("DARK.", "until P5", "False until"), "OPEN since 2026-10-01"),
    ("services/pair_consent.py", "MLC2_TRAINING_SWITCH_ENABLED",
     ("closed in code until",), "open since 2026-10-01"),
    ("services/learning_weekly.py", "MLC2_PAIR_RELEASES_ENABLED",
     ("closed today, so the job exports",), "door 2 is\n     open since 2026-10-01"),
    # Doors 3 and 4 opened 2026-10-08 (founder: "turn it all ON").
    ("services/model_training.py", "MLC2_TRAINING_ENABLED",
     ("Built with the door closed.",), "door 3 OPEN since 2026-10-08"),
    ("services/model_promotion.py", "MLC2_PROMOTION_ENABLED",
     ("Built with the door closed.",), "door 4 OPEN since 2026-10-08"),
)


def _docstring(relative: str) -> str:
    source = (ROOT / relative).read_text(encoding="utf-8")
    return ast.get_docstring(ast.parse(source), clean=False) or ""


class DoorCommentTests(unittest.TestCase):
    def test_each_docstring_says_what_its_constant_says(self):
        for relative, constant, closed_words, open_words in _CLAIMS:
            with self.subTest(file=relative, constant=constant):
                text = _docstring(relative)
                is_open = getattr(Config, constant) is True
                if is_open:
                    for words in closed_words:
                        self.assertNotIn(
                            words, text,
                            f"{relative} still calls {constant} closed")
                    self.assertIn(open_words, text,
                                  f"{relative} does not say {constant} is open")
                else:
                    self.assertNotIn(
                        open_words, text,
                        f"{constant} was closed again: {relative} must say so")

    def test_the_open_doors_are_the_ones_the_comments_describe(self):
        # The premise of the claims above: doors 1 and 2 open since
        # 2026-10-01, doors 3 and 4 since 2026-10-08 (founder: "turn it all
        # ON"), for the three existing surfaces (docs/LEARNING-DOORS.md). A
        # change to any of the four constants revisits this file in the
        # same review. The retired DPO lane stays shut.
        self.assertTrue(Config.MLC2_TRAINING_SWITCH_ENABLED)
        self.assertTrue(Config.MLC2_PAIR_RELEASES_ENABLED)
        self.assertTrue(Config.MLC2_TRAINING_ENABLED)
        self.assertTrue(Config.MLC2_PROMOTION_ENABLED)
        self.assertFalse(Config.MLC2_DATASET_RELEASES_ENABLED)
        docs = (ROOT / "docs" / "LEARNING-DOORS.md").read_text(encoding="utf-8")
        for door in ("| 3 · training |", "| 4 · promotion |"):
            row = next(line for line in docs.splitlines() if line.startswith(door))
            self.assertIn("OPEN for all three existing surfaces since 2026-10-08", row)


if __name__ == "__main__":
    unittest.main()
