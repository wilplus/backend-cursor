"""Explore-session arc resolution (willab Prompt A §3). Pure, no DB.

Run: python3 -m unittest test_explore_arc
"""
from __future__ import annotations

import unittest
import uuid

from services.explore_arc import resolve_arc, validate_project_intent


class ResolveArcTests(unittest.TestCase):
    def test_always_on_mints_even_without_explore_flag(self):
        # No opt-in anymore: a fresh recording ALWAYS starts an arc at take 1,
        # regardless of the explore_session flag (None/False/"" all mint).
        for flag in (None, False, "", True, "1"):
            arc_id, ti = resolve_arc(flag, None, None)
            self.assertIsNotNone(arc_id, flag)
            self.assertEqual(ti, 1, flag)
            uuid.UUID(arc_id)  # valid uuid

    def test_subsequent_take_carries_arc_and_index(self):
        aid = str(uuid.uuid4())
        self.assertEqual(resolve_arc(True, aid, 2), (aid, 2))
        self.assertEqual(resolve_arc(False, aid, "3"), (aid, 3))

    def test_arc_without_take_index_defaults_to_1(self):
        aid = str(uuid.uuid4())
        self.assertEqual(resolve_arc(True, aid, None), (aid, 1))
        self.assertEqual(resolve_arc(True, aid, "garbage"), (aid, 1))

    def test_take_index_floored_at_1(self):
        aid = str(uuid.uuid4())
        self.assertEqual(resolve_arc(True, aid, 0), (aid, 1))
        self.assertEqual(resolve_arc(True, aid, -5), (aid, 1))

    def test_arc_id_whitespace_stripped(self):
        aid = str(uuid.uuid4())
        out_id, _ = resolve_arc(True, f"  {aid}  ", 2)
        self.assertEqual(out_id, aid)

    def test_two_mints_are_distinct(self):
        a, _ = resolve_arc(True, None, None)
        b, _ = resolve_arc(True, None, None)
        self.assertNotEqual(a, b)


class ProjectIntentTests(unittest.TestCase):
    def test_new_requires_a_clean_identity_slate(self):
        self.assertEqual(validate_project_intent("new", None, None),
                         ("new", None))
        aid = str(uuid.uuid4())
        for arc_id, selected in ((aid, None), (None, aid), (aid, aid)):
            intent, error = validate_project_intent(
                "new", arc_id, selected)
            self.assertIsNone(intent)
            self.assertIn("cannot carry", error)

    def test_continue_requires_one_matching_selected_project(self):
        aid = str(uuid.uuid4())
        self.assertEqual(validate_project_intent("continue", aid, aid),
                         ("continue", None))
        self.assertEqual(validate_project_intent("continue", None, aid),
                         ("continue", None))

        intent, error = validate_project_intent("continue", None, None)
        self.assertIsNone(intent)
        self.assertIn("requires continue_arc_id", error)

        intent, error = validate_project_intent(
            "continue", aid, str(uuid.uuid4()))
        self.assertIsNone(intent)
        self.assertIn("same project", error)

    def test_legacy_omission_remains_backward_compatible(self):
        self.assertEqual(validate_project_intent(
            None, str(uuid.uuid4()), None), (None, None))

    def test_unknown_intent_is_rejected(self):
        intent, error = validate_project_intent("guess", None, None)
        self.assertIsNone(intent)
        self.assertIn("new", error)


if __name__ == "__main__":
    unittest.main()
