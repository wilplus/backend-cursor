"""Unit tests for services/verbal_markers.py — SPEC D20 / D21.

Run: python3 -m unittest test_verbal_markers
"""
from __future__ import annotations

import unittest

from services import verbal_markers as vm


class TestLexicons(unittest.TestCase):
    def test_three_classes_do_not_overlap_on_strict_terms(self):
        """An unambiguous term in two classes would be counted twice and would
        push the certainty signal in two directions at once."""
        strict = {}
        for cls in vm.CLASSES:
            for term, ambiguous in vm.lexicon(cls).items():
                if ambiguous:
                    continue
                self.assertNotIn(term, strict,
                                 f"{term!r} is strict in both {strict.get(term)} "
                                 f"and {cls}")
                strict[term] = cls

    def test_bleached_intensifiers_are_tics_not_boosters(self):
        """D21, and a deliberate departure from Hyland: in speech these are
        semantically empty. Counting a nervous speaker's tics as RAISED
        certainty is backwards."""
        for term in ("basically", "literally"):
            self.assertIn(term, vm.lexicon(vm.TIC))
            self.assertNotIn(term, vm.lexicon(vm.BOOSTER))

    def test_direction_signs_oppose(self):
        self.assertLess(vm.DIRECTION[vm.HEDGE], 0)
        self.assertGreater(vm.DIRECTION[vm.BOOSTER], 0)
        self.assertEqual(vm.DIRECTION[vm.TIC], 0.0)

    def test_unknown_class_returns_empty(self):
        self.assertEqual(vm.lexicon("invented"), {})


class TestCount(unittest.TestCase):
    def test_strict_and_ambiguous_are_separate(self):
        c = vm.count("I think it was like maybe fine")
        self.assertGreaterEqual(c[vm.HEDGE]["strict"], 2)      # i think, maybe
        self.assertGreaterEqual(c[vm.TIC]["ambiguous"], 1)     # like

    def test_ambiguity_is_not_silently_folded_in(self):
        """THE limit of this module. 'like' cannot be disambiguated by regex,
        so it must never land in `strict`."""
        c = vm.count("I like it")
        self.assertEqual(c[vm.TIC]["strict"], 0)
        self.assertEqual(c[vm.TIC]["ambiguous"], 1)
        self.assertEqual(c[vm.TIC]["total"], 1)

    def test_boosters_counted(self):
        c = vm.count("This is definitely and clearly correct, of course")
        self.assertGreaterEqual(c[vm.BOOSTER]["strict"], 3)

    def test_phrases_match_as_phrases(self):
        self.assertEqual(vm.count("sort of")[vm.HEDGE]["strict"], 1)
        self.assertEqual(vm.count("sorting often")[vm.HEDGE]["strict"], 0)

    def test_word_boundaries(self):
        """'um' must not fire inside 'umbrella'."""
        self.assertEqual(vm.count("umbrella")[vm.TIC]["strict"], 0)
        self.assertEqual(vm.count("um, hello")[vm.TIC]["strict"], 1)

    def test_punctuation_and_case_ignored(self):
        self.assertEqual(vm.count("Um... MAYBE?")[vm.TIC]["strict"], 1)
        self.assertEqual(vm.count("Um... MAYBE?")[vm.HEDGE]["strict"], 1)

    def test_empty_and_garbage(self):
        for bad in ("", "   ", None, 42, [], {}):
            c = vm.count(bad)
            self.assertEqual(c["n_words"], 0)
            self.assertEqual(c[vm.HEDGE]["total"], 0)

    def test_word_count(self):
        self.assertEqual(vm.word_count("one two three"), 3)
        self.assertEqual(vm.word_count("don't stop"), 2)
        self.assertEqual(vm.word_count(None), 0)


class TestPrior(unittest.TestCase):
    def test_fit_returns_none_on_too_little(self):
        self.assertIsNone(vm.fit_prior([0.01, 0.02]))

    def test_mean_is_recovered(self):
        rates = [0.02, 0.03, 0.04, 0.02, 0.03, 0.05, 0.01]
        a, b = vm.fit_prior(rates)
        self.assertAlmostEqual(a / (a + b), sum(rates) / len(rates), places=2)

    def test_degenerate_spread_falls_back_weak(self):
        """No spread must not become infinite precision."""
        a, b = vm.fit_prior([0.03] * 8)
        self.assertLess(a + b, 10.0)

    def test_impossible_rates_rejected(self):
        self.assertIsNone(vm.fit_prior([0.0] * 8))
        self.assertIsNone(vm.fit_prior([1.0] * 8))


class TestPosterior(unittest.TestCase):
    def test_short_window_is_wide(self):
        """D20's whole point: a short window yields a WIDE posterior rather
        than an INSUFFICIENT_DATA cliff."""
        prior = (2.0, 98.0)
        short = vm.posterior(1, 20, prior)
        long = vm.posterior(50, 1000, prior)
        self.assertGreater(short["sd"], long["sd"])

    def test_shrinks_toward_the_prior(self):
        """Bias is toward the corpus mean, i.e. toward UNDER-firing — the
        correct error direction when the span IS the intervention."""
        prior = (2.0, 98.0)                       # prior mean 0.02
        p = vm.posterior(5, 20, prior)            # raw ratio 0.25
        self.assertLess(p["mean"], 0.25)
        self.assertGreater(p["mean"], 0.02)

    def test_invalid_inputs(self):
        self.assertIsNone(vm.posterior(1, 0, None))
        self.assertIsNone(vm.posterior(5, 2, None))
        self.assertIsNone(vm.posterior(-1, 10, None))

    def test_works_without_a_prior(self):
        self.assertIsNotNone(vm.posterior(3, 100, None))


class TestDispersion(unittest.TestCase):
    def test_independent_data_is_near_one(self):
        pairs = [(2, 100), (3, 100), (2, 100), (3, 100), (2, 100), (3, 100)]
        phi = vm.dispersion(pairs)
        self.assertLess(phi, 2.0)

    def test_bursty_data_exceeds_one(self):
        """A speaker who wobbles clusters markers; plain binomial understates
        the SE and phi is the correction."""
        pairs = [(0, 100), (0, 100), (20, 100), (0, 100), (0, 100), (20, 100)]
        self.assertGreater(vm.dispersion(pairs), 2.0)

    def test_too_few_pairs(self):
        self.assertIsNone(vm.dispersion([(1, 100)]))


class TestWindow(unittest.TestCase):
    def test_lower_rate_needs_a_bigger_window(self):
        self.assertGreater(vm.window_for_precision(0.01),
                           vm.window_for_precision(0.05))

    def test_the_number_that_started_this(self):
        """1% at 30% relative precision is ~1,100 words — where the figure in
        Appendix F.4 came from."""
        self.assertAlmostEqual(vm.window_for_precision(0.01), 1100, delta=60)

    def test_dispersion_scales_the_window(self):
        self.assertAlmostEqual(vm.window_for_precision(0.02, phi=2.0),
                               2 * vm.window_for_precision(0.02, phi=1.0),
                               delta=2)

    def test_invalid(self):
        self.assertIsNone(vm.window_for_precision(0.0))
        self.assertIsNone(vm.window_for_precision(1.5))


if __name__ == "__main__":
    unittest.main()
