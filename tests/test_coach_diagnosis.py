"""The coach's diagnosis comes first (coach panel lock flow 6; Q-B7 A;
Q-B12 A; D-CP-4; migration 0445): the list's order, the body, the writes,
the gate and the walls. The database half is
tests/test_the_coach_s_diagnosis_comes_first_postgres.py."""
from __future__ import annotations

import inspect
import unittest


class WallsTests(unittest.TestCase):
    def test_the_route_sits_behind_the_blind_gate_and_inside_the_fence(self):
        from routes.v2 import coach
        source = inspect.getsource(coach.v2_coach_moment_diagnosis)
        self.assertLess(source.index("_moment_gate(session_id, snippet_id)"),
                        source.index("review("))
        self.assertIn('methods=["GET", "PUT"]', source)
        self.assertNotIn("db.", source.split("from services.coach_diagnosis import review")[0]
                         .replace("_moment_gate", ""))
