"""Coach-adjusted power_score (willab Phase 4, 2026-06-15).

Pure function, no DB. The coach tag is the DOMINANT term (the human gate);
activation + slide_stickiness order within a tag; untagged smooths to acoustic.

Run: python3 -m unittest test_power_phrase_ranking
"""
from __future__ import annotations

import unittest

from services.power_phrase_ranking import power_score


class PowerScoreTests(unittest.TestCase):
    def test_strong_outranks_to_work_on_regardless_of_acoustics(self):
        # a weak-acoustics STRONG moment still beats a strong-acoustics
        # to_work_on one — the human verdict dominates.
        strong = power_score(activation=0.0, slide_stickiness=0.0, tag="strong")
        bad = power_score(activation=1.0, slide_stickiness=1.0, tag="to_work_on")
        self.assertGreater(strong, bad)

    def test_within_tag_activation_orders(self):
        hi = power_score(activation=0.9, slide_stickiness=0.0, tag="strong")
        lo = power_score(activation=0.2, slide_stickiness=0.0, tag="strong")
        self.assertGreater(hi, lo)

    def test_slide_stickiness_breaks_ties(self):
        covered = power_score(activation=0.5, slide_stickiness=0.9, tag="strong")
        bare = power_score(activation=0.5, slide_stickiness=0.0, tag="strong")
        self.assertGreater(covered, bare)

    def test_untagged_falls_back_to_acoustics(self):
        # no coach verdict → coach term 0 → ordered purely by activation
        a = power_score(activation=0.8, tag=None)
        b = power_score(activation=0.3, tag=None)
        self.assertGreater(a, b)
        self.assertEqual(power_score(tag=None), 0.0)

    def test_rank_proxy_when_no_overall_score(self):
        # activation absent → derive from rank (1/rank): rank 1 beats rank 5
        r1 = power_score(activation=None, tag="strong", rank=1)
        r5 = power_score(activation=None, tag="strong", rank=5)
        self.assertGreater(r1, r5)

    def test_overall_score_preferred_over_rank(self):
        # when both present, the activation (overall_score) is used directly
        s = power_score(activation=0.95, tag="strong", rank=9)
        self.assertGreater(s, power_score(activation=0.1, tag="strong", rank=1))

    def test_bool_and_none_are_not_numeric(self):
        # a stray bool/None must not crash or count as a value
        self.assertEqual(
            power_score(activation=True, slide_stickiness=None, tag="strong"),
            power_score(activation=0.0, slide_stickiness=0.0, tag="strong"),
        )


if __name__ == "__main__":
    unittest.main()
