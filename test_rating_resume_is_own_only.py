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

Run: python3 -m unittest test_rating_resume_is_own_only
"""
from __future__ import annotations

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).parent
DB_SRC = (ROOT / "services" / "db.py").read_text()
COACH_SRC = (ROOT / "routes" / "v2" / "coach.py").read_text()


def _function(source: str, name: str) -> ast.FunctionDef:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


class TestTheReaderIsRaterScoped(unittest.TestCase):

    def test_the_reader_exists_and_takes_a_rater(self):
        fn = _function(DB_SRC, "get_own_state_ratings_for_session")
        args = [a.arg for a in fn.args.args]
        self.assertIn("rater_id", args,
                      "a reader without a rater cannot be own-only")

    def test_it_filters_on_rater_id(self):
        """The scope has to be in the QUERY. Filtering in Python after
        fetching everyone's rows would still ship them over the wire."""
        fn = _function(DB_SRC, "get_own_state_ratings_for_session")
        body = ast.get_source_segment(DB_SRC, fn) or ""
        self.assertIn('.eq("rater_id"', body)
        self.assertIn('.eq("session_id"', body)

    def test_no_rater_means_no_rows(self):
        """Fail CLOSED. A caller that forgot the rater gets nothing, not
        everyone — the safe default is the one that cannot anchor."""
        fn = _function(DB_SRC, "get_own_state_ratings_for_session")
        body = ast.get_source_segment(DB_SRC, fn) or ""
        self.assertIn("if not session_id or not rater_id:", body)
        guard = body[body.index("if not session_id or not rater_id:"):]
        self.assertIn("return {}", guard[:120])

    def test_it_does_not_select_the_note(self):
        """Only what the card needs to restore its own controls. Another
        rater's free text is the most anchoring thing on the row, and the
        narrow projection is what stops it ever being in the payload."""
        fn = _function(DB_SRC, "get_own_state_ratings_for_session")
        body = ast.get_source_segment(DB_SRC, fn) or ""
        select = body[body.index(".select("):]
        select = select[:select.index(")") + 1]
        self.assertIn("snippet_id", select)
        self.assertIn("value", select)
        self.assertIn("unrateable", select)
        self.assertNotIn("note", select)


class TestTheReviewReadPassesTheRater(unittest.TestCase):

    def test_the_state_map_accepts_a_rater(self):
        fn = _function(COACH_SRC, "_coach_state_map")
        self.assertIn("rater_id", [a.arg for a in fn.args.args])

    def test_the_rater_defaults_to_none(self):
        """Every existing caller keeps working AND keeps showing nothing —
        the resume is opt-in per call site, so adding a new surface cannot
        leak ratings by inheriting a default."""
        fn = _function(COACH_SRC, "_coach_state_map")
        self.assertEqual(len(fn.args.defaults), 1)
        self.assertIsNone(fn.args.defaults[0].value)

    def test_the_map_only_reads_ratings_when_given_a_rater(self):
        body = ast.get_source_segment(COACH_SRC, _function(
            COACH_SRC, "_coach_state_map")) or ""
        self.assertIn("if rater_id else {}", body)

    def test_the_review_read_passes_the_authenticated_user(self):
        """The rater is the CALLER, never a parameter a client could set —
        a client-supplied rater id would let one coach read another's."""
        self.assertIn(
            "_coach_state_map(\n            session_id, "
            'rater_id=getattr(request, "user_id", None))',
            COACH_SRC)

    def test_the_rating_is_two_fields_not_three_values(self):
        """`unrateable` stays separate from `value` on the wire for the same
        reason it is separate everywhere else: an abstention is a judgment
        about the RATER, not a third answer about the moment."""
        body = ast.get_source_segment(COACH_SRC, _function(
            COACH_SRC, "_coach_state_map")) or ""
        self.assertIn('"rating_value"', body)
        self.assertIn('"rating_unrateable"', body)


if __name__ == "__main__":
    unittest.main()
