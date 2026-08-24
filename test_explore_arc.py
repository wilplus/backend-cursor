"""Explore-session arc resolution (willab Prompt A §3). Pure, no DB.

Run: python3 -m unittest test_explore_arc
"""
from __future__ import annotations

import unittest
import uuid

from services.explore_arc import resolve_arc


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

if __name__ == "__main__":
    unittest.main()
