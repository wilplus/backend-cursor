"""Engine 4 — per-user acoustic pattern miner (deterministic v1). Pure.

Run: python3 -m unittest test_user_patterns
"""
from __future__ import annotations

import re
import unittest

from services.user_patterns import (
    _TEMPLATES, classify_moment, mine_patterns,
)


def _m(cls, **metrics):
    return {"cls": cls, "metrics": metrics}


class ClassifyMomentTests(unittest.TestCase):
    """RE-POINTED 2026-08-14 onto the settled confidence verdict. The old
    inputs were `(coach_label, coach_tag)` over challenge/threat (the retired
    charisma construct, frozen since its control was deleted 2026-08-07) and
    strong/to_work_on (where `strong` was auto-written whenever a note was
    typed). Patterns mined from those described what the coach commented on,
    not what the speaker does."""

    def test_the_settled_verdict_defines_the_class(self):
        self.assertEqual(classify_moment("yes"), "positive")
        self.assertEqual(classify_moment("no"), "negative")

    def test_an_unsettled_panel_says_nothing(self):
        # confidence_verdicts omits unsettled snippets, so the caller passes
        # None. Neutral here means "no finding", never "average".
        self.assertEqual(classify_moment(None), "neutral")
        self.assertEqual(classify_moment(""), "neutral")

    def test_a_settled_AMBIGUOUS_is_a_finding_but_not_a_class(self):
        # The panel agreed it cannot tell. Mining a trait from that would
        # invent a pattern out of the raters' uncertainty.
        self.assertEqual(classify_moment("ambiguous"), "neutral")

    def test_case_is_not_significant(self):
        self.assertEqual(classify_moment("YES"), "positive")
        self.assertEqual(classify_moment(" No "), "negative")

    def test_the_retired_constructs_no_longer_classify_anything(self):
        # challenge/threat/strong must not sneak back in through this door.
        for dead in ("challenge", "threat", "strong", "to_work_on"):
            self.assertEqual(classify_moment(dead), "neutral")


class MinePatternsTests(unittest.TestCase):

    def _corpus(self, pos_pause=0.30, neg_wpm=None, n=6):
        # neutral baseline: pause_ratio 0.15, wpm 120
        moments = [_m("neutral", pause_ratio=0.15, wpm=120) for _ in range(n)]
        moments += [_m("positive", pause_ratio=pos_pause, wpm=120)
                    for _ in range(n)]
        if neg_wpm is not None:
            moments += [_m("negative", pause_ratio=0.15, wpm=neg_wpm)
                        for _ in range(n)]
        return moments

    def test_positive_pause_pattern_found(self):
        out = mine_patterns(self._corpus(pos_pause=0.30))  # +100% vs neutral
        kinds = {(p["kind"], p["feature"]) for p in out}
        self.assertIn(("positive", "pausing"), kinds)
        stmt = next(p["statement"] for p in out
                    if p["feature"] == "pausing" and p["kind"] == "positive")
        self.assertIn("pause", stmt)

    def test_negative_pace_pattern_found(self):
        # good AND bad moments both mined (founder 2026-07-11)
        out = mine_patterns(self._corpus(neg_wpm=170))  # +42% pace on flagged
        kinds = {(p["kind"], p["feature"]) for p in out}
        self.assertIn(("negative", "pace"), kinds)

    def test_below_threshold_is_silence(self):
        out = mine_patterns(self._corpus(pos_pause=0.16))  # +7% — noise
        self.assertEqual([p for p in out if p["feature"] == "pausing"], [])

    def test_thin_class_is_silence(self):
        moments = self._corpus()[:8]  # not enough of anything
        self.assertEqual(mine_patterns(moments), [])

    def test_no_neutral_baseline_is_silence(self):
        moments = [_m("positive", pause_ratio=0.3) for _ in range(10)]
        self.assertEqual(mine_patterns(moments), [])

    def test_cap_and_shape(self):
        moments = [
            _m("neutral", pause_ratio=0.15, wpm=120, f0_sd=25, dynamic_db=8)
            for _ in range(6)
        ] + [
            _m("positive", pause_ratio=0.30, wpm=170, f0_sd=45, dynamic_db=14)
            for _ in range(6)
        ] + [
            _m("negative", pause_ratio=0.05, wpm=60, f0_sd=10, dynamic_db=3)
            for _ in range(6)
        ]
        out = mine_patterns(moments)
        self.assertLessEqual(len(out), 4)
        self.assertLessEqual(len([p for p in out if p["kind"] == "positive"]), 2)
        for p in out:
            self.assertIn(p["kind"], ("positive", "negative"))
            self.assertTrue(p["statement"])

    def test_empty_safe(self):
        self.assertEqual(mine_patterns([]), [])
        self.assertEqual(mine_patterns(None), [])


class TemplateFenceTests(unittest.TestCase):
    def test_no_template_carries_digits_or_construct(self):
        # AC-9: every user-facing statement is qualitative.
        construct = re.compile(
            r"threat|charisma\s+(score|ratio)|stress\s+score|kpi", re.I)
        for stmt in _TEMPLATES.values():
            self.assertNotRegex(stmt, r"\d")
            self.assertIsNone(construct.search(stmt), stmt)

    def test_full_template_matrix(self):
        # 4 features × 2 directions × 2 kinds — no hole a mined delta could
        # fall through silently.
        from services.user_patterns import _FEATURES
        for f in _FEATURES:
            for hi in (True, False):
                for kind in ("positive", "negative"):
                    self.assertIn((f, hi, kind), _TEMPLATES)


if __name__ == "__main__":
    unittest.main()
