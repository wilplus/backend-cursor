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

from services import feedback_catalogue as fc
from services import take_feedback_manager as tfm
from services.say_it_stronger import _GUARD_CONSTRUCT_RE

TAKE, SNIP = "take-1", "snip-1"


def _proposed(lane, kind, key):
    return next(line[3] for line in fc.PROPOSED_LINES
                if line[:3] == (lane, kind, key))


def _candidates(text):
    return [(0, len(text), text)]


def _fallback_rewrite(text):
    return tfm._fallback_rewrite(_candidates(text), take=TAKE, snippet_id=SNIP)


class TheDraftTests(unittest.TestCase):


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


if __name__ == "__main__":
    unittest.main()
