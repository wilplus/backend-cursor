"""The coach's blind gate opens on any saved answer (founder 2026-09-29).

Until today only Yes and No counted, so a coach who answered In-between,
Not sure or Audio unclear never saw that moment's practice or its exercise
request. The fence itself is unchanged: the answer must be saved first.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    from routes.v2.coach import _blind_rating_saved
    _IMPORT_ERROR = None
except Exception as error:  # noqa: BLE001 — the source test below still runs
    _blind_rating_saved = None
    _IMPORT_ERROR = error


class SourceTests(unittest.TestCase):
    def test_both_gates_use_the_one_key(self):
        source = (ROOT / "routes/v2/coach.py").read_text()
        for name in ("def v2_coach_confident_voice_practice",
                     "def v2_coach_exercise_request"):
            start = source.index(name)
            route = source[start:source.index("@v2_bp.route", start)]
            self.assertIn("_blind_rating_saved(", route)
            self.assertNotIn('rating_value") not in ("yes", "no")', route)


@unittest.skipIf(_IMPORT_ERROR is not None, f"coach routes unavailable: {_IMPORT_ERROR}")
class KeyTests(unittest.TestCase):
    def test_any_of_the_five_saved_answers_opens_the_door(self):
        for value in ("yes", "no", "in_between", "not_sure"):
            self.assertTrue(_blind_rating_saved(
                {"rating_value": value, "rating_unrateable": False}), value)
        # Audio unclear is stored as the abstention flag, not as a value.
        self.assertTrue(_blind_rating_saved(
            {"rating_value": None, "rating_unrateable": True}))

    def test_no_answer_keeps_it_shut(self):
        self.assertFalse(_blind_rating_saved(None))
        self.assertFalse(_blind_rating_saved({}))
        self.assertFalse(_blind_rating_saved(
            {"rating_value": None, "rating_unrateable": False}))
