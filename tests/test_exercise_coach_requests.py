"""A coach hears when no exercise fits (founder 2026-09-28; contract 35b/35f).

Pins:
  * a bookmark with no fitting exercise records one coach request when the
    speaker's judgement is saved (founder 2026-09-29; until then V3's one
    exercise item did, at read time), with why (nothing spotted / nothing
    targets what was spotted), and the item is still served now — nobody
    waits on the coach;
  * a request that can't be written never costs the feedback;
  * an exercise the coach SHARED for that exact moment is what the item then
    carries, and the practice can start on it; one not shared, or edited
    since, is not served;
  * the coach resolves once, only after their blind rating, and only an
    exercise can be shared.
"""
from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class RouteTests(unittest.TestCase):
    def test_the_request_is_behind_the_blind_gate_and_the_speaker_s_yes(self):
        source = (ROOT / "routes/v2/coach.py").read_text()
        start = source.index("def v2_coach_exercise_request")
        route = source[start:source.index("@v2_bp.route", start)]
        gate = route.index("BLIND_RATING_REQUIRED")
        self.assertLess(gate, route.index("review("))
        self.assertLess(route.index("_speaker_practice_permitted"),
                        route.index("review("))
        head = source[source.rindex("@v2_bp.route", 0, start):start]
        self.assertIn(
            '@operational_purpose_disabled("personalized_exercise_recommendation")',
            head)


# ── THE COACH'S PICK COUNTS (founder 2026-09-29, decision 3; 0398) ────────
#
# A coach-shared exercise gets the same rows a machine pick gets, under the
# coach policy name: an assignment and a trace when it is first served, the
# render receipt when the card is on screen, and the practice links to that
# assignment. Nothing about the coach's choice is folded into the draw.
