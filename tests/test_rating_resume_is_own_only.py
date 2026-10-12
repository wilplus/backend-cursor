"""A coach resumes their OWN rating, and never sees the panel's.

THE AMNESIA THIS FIXES. The coach-review payload carried no rating, so a
snippet the coach had already answered read as unanswered after a reload. That
is not only wasted work: a coach re-rating from scratch gives a SECOND,
non-independent look at the same clip, and the corpus cannot tell the two
apart.

THE RISK THE FIX INTRODUCES, which is why this file exists. The obvious
implementation — "fold in the ratings for this session" — would put OTHER
raters' answers on screen. That anchors the next label and destroys the
independence that makes multi-rater agreement mean anything. It is the same
failure as showing the machine's read next to the label controls, arriving by
a different door.

So the reader is scoped to one rater by construction, and omitting the rater
yields NOTHING rather than everything — a caller that has not thought about
whose answer it is showing gets the safe answer, not the dangerous one.

Run: python3 -m unittest tests.test_rating_resume_is_own_only
"""
from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
COACH_SRC = (ROOT / "routes" / "v2" / "coach.py").read_text()


class TestTheReviewReadPassesTheRater(unittest.TestCase):


    def test_the_review_read_passes_the_authenticated_user(self):
        """The rater is the CALLER, never a parameter a client could set —
        a client-supplied rater id would let one coach read another's."""
        self.assertIn(
            "_coach_state_map(\n            session_id, "
            'rater_id=getattr(request, "user_id", None))',
            COACH_SRC)


if __name__ == "__main__":
    unittest.main()
