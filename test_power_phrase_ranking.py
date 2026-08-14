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


class TheCharismaTermIsGoneTests(unittest.TestCase):
    """Founder 2026-08-13 / SPEC §7.2 — `_W_D` retired with the construct.

    The old kwargs are not silently ignored, and that is the point of this
    class. A ``direction=`` that quietly evaluated to a no-op would let the
    retired construct be passed from a caller nobody updated, forever, with
    nothing anywhere saying it stopped mattering. TypeError says it once,
    loudly, at the call site."""

    def test_the_retired_kwargs_raise_rather_than_no_op(self):
        for kw in ({"direction": "challenge"}, {"breakthrough": True},
                   {"voice_confidence": 0.5}):
            with self.assertRaises(TypeError, msg=kw):
                power_score(activation=0.5, **kw)

    def test_no_construct_vocabulary_survives_in_the_blend(self):
        import inspect

        from services import power_phrase_ranking as mod
        src = inspect.getsource(mod.power_score)
        for word in ("challenge", "threat", "charisma"):
            self.assertNotIn(word, src.lower(), word)


class ConfidenceTermTests(unittest.TestCase):
    """SPEC §7.2 — confidence enters EXACTLY ONCE (D8), panel or machine."""

    def test_no_confidence_is_byte_for_byte_unchanged(self):
        # The live /strengths path passes none of it → identical to before.
        self.assertEqual(
            power_score(activation=0.5, slide_stickiness=0.3, tag="strong"),
            power_score(activation=0.5, slide_stickiness=0.3, tag="strong",
                        panel_confidence=None, machine_confidence=None),
        )

    def test_an_assured_delivery_outranks_an_unsure_one(self):
        up = power_score(activation=0.5, machine_confidence=0.8)
        down = power_score(activation=0.5, machine_confidence=-0.8)
        self.assertGreater(up, down)

    def test_a_dead_zone_read_is_neutral(self):
        self.assertEqual(
            power_score(activation=0.5, machine_confidence=0.0),
            power_score(activation=0.5),
        )

    def test_the_panel_is_used_INSTEAD_of_the_machine_never_as_well(self):
        """D8's whole content. Summing them would double-count one property
        of one clip — and it would do it silently, since both terms are
        legitimate on their own."""
        from services.power_phrase_ranking import (
            SOURCE_PANEL, confidence_term,
        )
        term, source = confidence_term({"value": 1.0, "quality": 1.0}, 0.9)
        self.assertEqual(source, SOURCE_PANEL)
        panel_only, _ = confidence_term({"value": 1.0, "quality": 1.0}, None)
        self.assertEqual(term, panel_only)

    def test_a_thin_panel_moves_ranking_less_than_a_deep_one(self):
        from services.state_ratings import quality
        thin = power_score(panel_confidence={
            "value": 1.0, "quality": quality(2, 1.0)})
        deep = power_score(panel_confidence={
            "value": 1.0, "quality": quality(10, 1.0)})
        self.assertGreater(deep, thin)

    def test_the_panel_outweighs_the_machine_at_equal_lean(self):
        # A real aggregated human judgment should move the pick further than
        # an estimate standing in for one.
        panel = power_score(panel_confidence={"value": 1.0, "quality": 1.0})
        machine = power_score(machine_confidence=1.0)
        self.assertGreater(panel, machine)


class OrderingOfAuthorityTests(unittest.TestCase):
    """SPEC §7.1 — the invariant that SURVIVES the re-point. Coach verdict
    dominant > quorum bonus > panel > machine. Every one of these is a
    weight-sizing claim the file makes in prose; here it is arithmetic."""

    def test_the_coach_verdict_outweighs_any_confidence_read(self):
        strong = power_score(activation=0.0, tag="strong")
        for conf in ({"panel_confidence": {"value": 1.0, "quality": 1.0}},
                     {"machine_confidence": 1.0}):
            self.assertGreater(strong, power_score(activation=0.0, **conf))

    def test_the_coach_gap_is_wider_than_the_panels_full_swing(self):
        gap = (power_score(tag="strong") - power_score(tag="to_work_on"))
        swing = (power_score(panel_confidence={"value": 1.0, "quality": 1.0})
                 - power_score(panel_confidence={"value": -1.0,
                                                 "quality": 1.0}))
        self.assertGreater(gap, swing)

    def test_the_quorum_bonus_is_GONE_not_ignored(self):
        """Founder verdict, 2026-08-13 evening: `_W_B` deleted outright — a
        ghost of the retired charisma system whose re-pointed quorum no
        production data could satisfy. Same rule as the other retired kwargs:
        a stale caller raises rather than silently no-ops."""
        with self.assertRaises(TypeError):
            power_score(activation=0.3, album_quorum=True)

    def test_no_combination_of_automatic_terms_crosses_the_coach_gap(self):
        """Deleting the bonus is what made §7.1 arithmetically TRUE. The
        audit's counterexample — to_work_on + quorum + positive panel beating
        strong + negative panel — is now impossible: the automatic maximum is
        the full panel swing plus content, strictly under the 4.0 gap."""
        gap = (power_score(tag="strong") - power_score(tag="to_work_on"))
        best_auto = power_score(
            tag="to_work_on", activation=1.0, slide_stickiness=1.0,
            panel_confidence={"value": 1.0, "quality": 1.0})
        worst_human = power_score(
            tag="strong", activation=0.0, slide_stickiness=0.0,
            panel_confidence={"value": -1.0, "quality": 1.0})
        self.assertGreater(gap, 3.0)
        self.assertGreater(worst_human, best_auto - gap)  # coach still decides


if __name__ == "__main__":
    unittest.main()
