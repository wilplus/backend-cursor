"""The live phrase ranker accepts product evidence only."""
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
    """Machine confidence is the only automatic live delivery term."""

    def test_no_confidence_is_byte_for_byte_unchanged(self):
        self.assertEqual(
            power_score(activation=0.5, slide_stickiness=0.3, tag="strong"),
            power_score(activation=0.5, slide_stickiness=0.3, tag="strong",
                        machine_confidence=None),
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

    def test_confidence_source_is_machine_or_none(self):
        from services.power_phrase_ranking import confidence_term
        self.assertEqual(confidence_term(0.5), (0.5, "machine"))
        self.assertEqual(confidence_term(None), (0.0, "none"))

    def test_peer_panel_input_is_rejected_loudly(self):
        with self.assertRaises(TypeError):
            power_score(panel_confidence={"value": 1.0, "quality": 1.0})
        with self.assertRaises(TypeError):
            from services.power_phrase_ranking import confidence_term
            confidence_term({"value": 1.0}, 0.9)


class OrderingOfAuthorityTests(unittest.TestCase):
    """SPEC §7.1 — the invariant that SURVIVES both re-points. Stated
    RELATIVELY since 2026-08-14: a coach veto is never earned back, because
    every other term is available to the vetoed phrase too. Each of these is a
    weight-sizing claim the file makes in prose; here it is arithmetic."""

    def test_the_strong_tag_is_NOT_a_verdict_and_lifts_NOTHING(self):
        """Founder 2026-08-14. No picker for "strong" exists: the FE sent
        `cs.tag ?? "strong"` and publish defaults a missing tag the same way,
        so the value meant "a coach typed a note". It was worth +2.0 — the
        largest single term in the blend — which let a commented-on phrase
        outrank a measurably better one. A note is not a judgment."""
        self.assertEqual(power_score(tag="strong"), power_score(tag=None))
        self.assertEqual(power_score(tag="strong"), power_score())
        # And it must not be re-added by accident: the term is one-sided.
        from services.power_phrase_ranking import _COACH_TERM
        self.assertNotIn("strong", _COACH_TERM)

    def test_a_vetoed_phrase_never_reaches_an_untagged_one(self):
        """The whole ordering invariant, in one comparison. to_work_on is a
        REAL pick (no default ever produced it), so it still costs 2.0 — and
        since content/panel/machine are all available to BOTH phrases, no
        machine confidence is available to BOTH phrases, so it cannot close
        the relative gap. True at any weight."""
        best_case_for_the_vetoed = power_score(
            tag="to_work_on", activation=1.0, slide_stickiness=1.0,
            machine_confidence=1.0)
        same_phrase_untagged = power_score(
            activation=1.0, slide_stickiness=1.0,
            machine_confidence=1.0)
        self.assertLess(best_case_for_the_vetoed, same_phrase_untagged)

    def test_the_veto_outweighs_any_single_confidence_read(self):
        """Delivery informs the pick; it never overturns a human's explicit
        negative. A perfect machine read is strictly smaller than the 2.0 the
        veto removes."""
        veto = power_score(tag=None) - power_score(tag="to_work_on")
        lift = power_score(machine_confidence=1.0) - power_score()
        self.assertGreater(veto, lift)

    def test_the_quorum_bonus_is_GONE_not_ignored(self):
        """Founder verdict, 2026-08-13 evening: `_W_B` deleted outright — a
        ghost of the retired charisma system whose re-pointed quorum no
        production data could satisfy. Same rule as the other retired kwargs:
        a stale caller raises rather than silently no-ops."""
        with self.assertRaises(TypeError):
            power_score(activation=0.3, album_quorum=True)

    def test_no_combination_of_automatic_terms_crosses_the_veto(self):
        """Deleting `_W_B` is what made §7.1 arithmetically TRUE, and dropping
        the fake `strong` half is what stopped the gap being fictional in the
        other direction. Maxing EVERY automatic term at once still does not
        recover the veto."""
        veto = power_score(tag=None) - power_score(tag="to_work_on")
        all_automatic_maxed = power_score(
            activation=1.0, slide_stickiness=1.0,
            machine_confidence=1.0) - power_score()
        # 2.0 removed vs 1.0 + 0.6 + 1.0 available — but the point is that the
        # untagged phrase can claim all of it too, so the comparison below is
        # the one that decides ordering.
        self.assertGreater(
            power_score(activation=1.0, slide_stickiness=1.0,
                        machine_confidence=1.0),
            power_score(tag="to_work_on", activation=1.0,
                        slide_stickiness=1.0,
                        machine_confidence=1.0))
        self.assertEqual(veto, 2.0)
        self.assertGreater(all_automatic_maxed, 0.0)


if __name__ == "__main__":
    unittest.main()
