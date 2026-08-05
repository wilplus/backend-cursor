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
        self.assertIsNone(vm.fit_prior([(1, 100), (2, 100)]))

    def test_pooled_rate_is_recovered(self):
        pairs = [(2, 100), (3, 100), (4, 100), (2, 100), (3, 100),
                 (5, 100), (1, 100)]
        a, b = vm.fit_prior(pairs)
        pooled = sum(m for m, _ in pairs) / sum(w for _, w in pairs)
        self.assertAlmostEqual(a / (a + b), pooled, places=3)

    def test_short_noisy_documents_do_not_drag_the_mean_up(self):
        """THE defect this signature exists to prevent.

        Measured on real transcripts, the unweighted mean of per-document
        rates ran 3.6x the pooled rate for TIC (8.40 vs 2.31 per 1,000 words),
        because a 40-word snippet with two marks counted the same as a
        2,000-word talk with two. Plugging that in would pull every posterior
        toward a rate the corpus does not show.
        """
        pairs = [(2, 20)] * 5 + [(10, 2000)]      # 5 tiny hot docs, 1 big cool
        unweighted = sum(m / w for m, w in pairs) / len(pairs)   # ~0.084
        pooled = sum(m for m, _ in pairs) / sum(w for _, w in pairs)  # ~0.0095
        self.assertGreater(unweighted, 5 * pooled)   # the bias is real

        a, b = vm.fit_prior(pairs)
        self.assertAlmostEqual(a / (a + b), pooled, places=3)
        self.assertLess(a / (a + b), unweighted / 2)

    def test_degenerate_spread_falls_back_weak(self):
        """No spread must not become infinite precision."""
        a, b = vm.fit_prior([(3, 100)] * 8)
        self.assertLess(a + b, 10.0)

    def test_impossible_rates_rejected(self):
        self.assertIsNone(vm.fit_prior([(0, 100)] * 8))
        self.assertIsNone(vm.fit_prior([(100, 100)] * 8))

    def test_malformed_pairs_dropped(self):
        pairs = [(2, 100), (5, 0), (200, 100), (3, 100), (2, 100),
                 (4, 100), (3, 100)]
        self.assertIsNotNone(vm.fit_prior(pairs))


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


class TestWithinSpeakerDispersion(unittest.TestCase):
    def test_pooled_sees_between_speaker_spread_and_within_does_not(self):
        """THE correction. Two speakers with different base rates, each
        perfectly steady. Pooled phi reads that as overdispersion; it is not —
        it is a fact about the population, and it has no bearing on how much
        text you need from ONE person."""
        groups = {"A": [(6, 100)] * 20, "B": [(1, 100)] * 20}
        pooled = vm.dispersion(groups["A"] + groups["B"])
        within = vm.dispersion_within(groups)
        self.assertGreater(pooled, 1.5)
        self.assertLess(within, 0.5)

    def test_genuine_within_speaker_burstiness_is_caught(self):
        groups = {"A": [(0, 100), (0, 100), (12, 100), (0, 100), (12, 100)] * 3}
        self.assertGreater(vm.dispersion_within(groups), 2.0)

    def test_singleton_groups_contribute_nothing(self):
        """One document per speaker carries no within-speaker spread."""
        self.assertIsNone(vm.dispersion_within({"A": [(1, 100)],
                                                "B": [(2, 100)]}))

    def test_empty(self):
        self.assertIsNone(vm.dispersion_within({}))


class TestSparsityGuard(unittest.TestCase):
    def test_expected_marks_reports_the_regime(self):
        """Measured corpus: 75-word documents at 7.5 marks/1,000 give 0.57
        expected per document, far below the ~5 chi-square wants. The number
        has to travel WITH phi or someone acts on a window built from noise."""
        pairs = [(1, 75)] * 100 + [(0, 75)] * 119
        exp = vm.expected_marks_per_doc(pairs)
        self.assertLess(exp, 1.0)

    def test_dense_documents_clear_the_bar(self):
        self.assertGreater(vm.expected_marks_per_doc([(10, 1000)] * 20), 5.0)

    def test_empty(self):
        self.assertIsNone(vm.expected_marks_per_doc([]))
