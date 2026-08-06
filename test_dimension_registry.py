"""Unit tests for services/dimension_registry.py — SPEC D31.

The registry is the single source for window <-> benchmark <-> intervention.
These tests pin the properties that make it trustworthy as a source: it agrees
with its own vocabulary, it refuses to answer for dimensions the spec does not
define, and the two rules that protect the tier system (D24 adaptation, G.5
chartability) come out of it rather than out of a caller's memory.

Run: python3 -m unittest test_dimension_registry
"""
from __future__ import annotations

import unittest

from services import dimension_registry as registry


class TestSelfConsistency(unittest.TestCase):
    def test_registry_validates(self):
        """A bad edit fails here rather than reaching a consumer."""
        self.assertEqual(registry.validate(), [])

    def test_every_window_class_is_one_of_the_five(self):
        """Appendix F.1 defines five. There is no sixth, and inventing one is
        exactly the drift this file exists to stop."""
        for d in registry.all_dimensions():
            self.assertIn(d.window_class, registry.WINDOW_CLASSES,
                          f"{d.dimension_id} has a non-F.1 window class")

    def test_hysteresis_is_all_or_nothing(self):
        """Appendix D: every benchmark is a Schmitt trigger. A fire_at with no
        clear_at oscillates on the boundary."""
        for d in registry.all_dimensions():
            self.assertEqual(d.fire_at is None, d.clear_at is None,
                             f"{d.dimension_id} has half a hysteresis pair")


class TestAppendixFAgreement(unittest.TestCase):
    """Spot-checks against Appendix F.4's table. These are the values a
    consumer would otherwise retype from the document."""

    def test_conf_is_the_only_unit_scoped_live_candidate(self):
        self.assertEqual(registry.window_class_of("conf"), "UNIT")
        self.assertEqual(registry.get("conf").min_seconds, 1.6)

    def test_lexical_dimensions_gate_on_tokens_not_seconds(self):
        """F.3's denominator problem: converting tokens to seconds assumes a
        speech rate, so a slow speaker's threshold is silently wrong."""
        for dim_id in ("pronoun_profile", "hedge_booster"):
            d = registry.get(dim_id)
            self.assertEqual(d.min_tokens, 1000)
            self.assertIsNone(d.min_seconds)

    def test_proportional_dimensions_carry_no_seconds(self):
        """F.4: arc/peak/ending is deciles, NEVER fixed seconds."""
        for dim_id in ("arc_peak_ending", "slide_alignment"):
            d = registry.get(dim_id)
            self.assertEqual(d.window_class, "PROPORTIONAL")
            self.assertIsNone(d.min_seconds)

    def test_fillers_is_a_rate_not_a_sum(self):
        """THE correction. session_metrics rolls fillers up as a SUM, which
        scales with session length — a monitor over it would mostly measure
        how long the session was. F.4 (E6) says per minute."""
        self.assertEqual(registry.aggregation_of("fillers"), "per_minute")
        self.assertNotEqual(registry.aggregation_of("fillers"), "sum")


class TestUnitVersusDenominator(unittest.TestCase):
    """`unit` says what the number IS; `denominator` is what rollup() DIVIDES
    BY. Conflating them is how `wpm` came to declare a denominator it never
    applied — the registry answered 'rate' and the code returned a level."""

    RATE_FORMS = ("per_minute", "per_1000_words")

    def test_denominator_appears_only_where_rollup_applies_one(self):
        for d in registry.all_dimensions():
            if d.denominator:
                self.assertIn(d.aggregation, self.RATE_FORMS,
                              f"{d.dimension_id} declares a denominator that "
                              f"rollup() never divides by")

    def test_every_rate_names_what_it_is_per(self):
        for d in registry.all_dimensions():
            if d.aggregation in self.RATE_FORMS:
                self.assertTrue(d.denominator,
                                f"{d.dimension_id} is a rate with no denominator")

    def test_no_two_dimensions_claim_the_same_appendix_row(self):
        """A citation is prose and no test can check it against the document
        — but THIS much is mechanical, and it is the shape the error took:
        `energy` and `dynamic_db` both sat on E2, so one of them was
        inheriting a window it had no claim to."""
        seen = {}
        for d in registry.all_dimensions():
            row = d.appendix_id.rstrip("*")
            self.assertNotIn(row, seen,
                             f"{d.dimension_id} and {seen.get(row)} both claim {row}")
            seen[row] = d.dimension_id

    def test_denominators_are_counts_the_pipeline_can_actually_produce(self):
        """A denominator naming a unit nothing counts writes NULL n_units
        forever, which is a silent hole rather than a visible gap."""
        for d in registry.all_dimensions():
            if d.denominator:
                self.assertIn(d.denominator, ("minutes", "words"),
                              f"{d.dimension_id}: nothing counts "
                              f"{d.denominator!r}")


class TestMinimumGate(unittest.TestCase):
    def test_the_cycle_gate_applies_to_rates_not_to_levels(self):
        """F.1 scopes the 30 s minimum to pause/disfluency RATES: Henderson's
        planning cycle makes a sub-cycle RATE swing with where the window
        lands. A LEVEL is stable well inside one cycle. Applying the rate gate
        to all six marked good data insufficient — a name match passing as a
        spec match, which is what `spec_mismatch` now stops."""
        gated = {d.dimension_id for d in registry.live_dimensions()
                 if d.min_seconds is not None}
        self.assertEqual(gated, {"wpm", "fillers", "pause_ms"})

    def test_levels_measure_at_snippet_length(self):
        """The whole point of the per-measure fix: an 18 s snippet is enough
        for a mean, so these three now produce a value instead of a hole."""
        for dim_id in ("dynamic_db", "pitch_center", "energy"):
            self.assertTrue(registry.meets_minimum(dim_id, seconds=18.0),
                            f"{dim_id} is a level and must not inherit a rate's gate")

    def test_snippet_length_fails_the_cycle_minimum(self):
        """The finding this registry surfaced on day one, now correctly
        narrowed: a snippet is ~18 s and the RATE measures need 30 s."""
        self.assertFalse(registry.meets_minimum("wpm", seconds=18.0))
        self.assertTrue(registry.meets_minimum("wpm", seconds=45.0))

    def test_a_starred_row_says_what_differs(self):
        """A starred appendix_id means 'our measure is not this row's
        measure', so the row's minimum is an argument about a different
        quantity and must never be inherited in silence."""
        for d in registry.all_dimensions():
            if d.appendix_id.endswith("*"):
                self.assertTrue(d.spec_mismatch,
                                f"{d.dimension_id} is starred with no mismatch")
            if d.spec_mismatch and d.min_seconds is not None:
                self.assertTrue(d.note,
                                f"{d.dimension_id} inherits a gate from a row "
                                f"it does not match, unjustified")

    def test_missing_duration_fails_closed(self):
        self.assertFalse(registry.meets_minimum("wpm", seconds=None))

    def test_token_gate(self):
        self.assertFalse(registry.meets_minimum("pronoun_profile", tokens=200))
        self.assertTrue(registry.meets_minimum("pronoun_profile", tokens=1200))

    def test_unknown_dimension_fails_closed(self):
        """Refusing to measure something the spec does not define is the safe
        direction — the alternative is inventing a window."""
        self.assertFalse(registry.meets_minimum("invented", seconds=9999))
        self.assertIsNone(registry.get("invented"))
        self.assertIsNone(registry.window_class_of("invented"))

    def test_a_dimension_with_no_gate_passes(self):
        self.assertTrue(registry.meets_minimum("arc_peak_ending"))


class TestTheChain(unittest.TestCase):
    """window -> enough data -> threshold -> intervention. The registry exists
    so a feedback engine can walk that chain for any dimension and get a real
    answer at every link. These tests pin where the chain is currently CUT, so
    the gap is a stated fact rather than something a caller discovers by
    getting None back."""

    def test_every_live_dimension_answers_the_data_question(self):
        """Link 1-2. Whatever else is missing, 'do I have enough to measure?'
        must be answerable for everything the pipeline produces."""
        for d in registry.live_dimensions():
            self.assertIn(d.window_class, registry.WINDOW_CLASSES)
            self.assertIsInstance(
                registry.meets_minimum(d.dimension_id, seconds=45.0,
                                       tokens=1500), bool)

    def test_no_live_dimension_can_intervene_yet(self):
        """Link 3-4, AND THE HONEST STATE OF THE WORLD. Not one live
        dimension has a fire_at or an intervention: the registry can say
        'you have enough data', and then nothing downstream can act on it.
        `fired` is None on every telemetry row for exactly this reason.

        This is the outstanding half of D31, not a defect in the wiring. The
        test flips the day a benchmark lands — which is the prompt to give it
        BOTH ends of the chain rather than a bare number."""
        wired = [d.dimension_id for d in registry.live_dimensions()
                 if d.fire_at is not None]
        self.assertEqual(wired, [], "a threshold landed — route its "
                                    "intervention and re-read Appendix G.5")

    def test_nothing_fires_while_switched_off(self):
        """`can_fire` is the single gate the manager engine asks. An OFF
        dimension must not become fireable just because a threshold lands."""
        for d in registry.disabled():
            self.assertFalse(registry.can_fire(d.dimension_id),
                             f"{d.dimension_id} is OFF but can_fire() says yes")

    def test_can_fire_fails_closed_on_an_unknown_id(self):
        self.assertFalse(registry.can_fire("invented"))

    def test_the_off_list_says_why(self):
        """An OFF with no reason decays into one nobody dares reverse."""
        self.assertTrue(registry.disabled(), "the off-list emptied — "
                                             "did a re-enable lose its reason?")
        for d in registry.disabled():
            self.assertTrue(d.disabled_reason,
                            f"{d.dimension_id} is OFF with no reason")

    def test_off_is_not_the_same_state_as_not_built(self):
        """`computed=False` is 'not written yet'; `enabled=False` is 'written
        or writable, and must not fire'. Collapsing them loses the reason."""
        d = registry.get("pronoun_profile")
        self.assertFalse(d.enabled)
        self.assertIn("8.0", d.disabled_reason)   # the band it could not resolve

    def test_a_threshold_and_its_intervention_arrive_together(self):
        """Enforced by validate() in both directions; asserted here so the
        rule is visible in the suite rather than buried in a helper."""
        for d in registry.all_dimensions():
            self.assertEqual(d.fire_at is None, not d.intervention,
                             f"{d.dimension_id}: half a chain")


class TestChartability(unittest.TestCase):
    def test_corpus_rel_is_never_chartable(self):
        """Appendix G.5: the fire rate is pinned by construction, so the chart
        can never signal while looking perfectly healthy."""
        for d in registry.all_dimensions():
            if d.tier == "CORPUS_REL":
                self.assertFalse(registry.is_chartable(d.dimension_id))

    def test_nothing_is_chartable_today(self):
        """Honest state of the world: no dimension has a fire_at in code, so
        the p-chart legitimately has zero rows. That is correct, not broken —
        and this test starts failing the day a real benchmark lands, which is
        the reminder to re-read G.5 before charting it."""
        chartable = [d.dimension_id for d in registry.all_dimensions()
                     if registry.is_chartable(d.dimension_id)]
        self.assertEqual(chartable, [])

    def test_unknown_is_not_chartable(self):
        self.assertFalse(registry.is_chartable("invented"))


class TestAdaptation(unittest.TestCase):
    def test_measured_tiers_never_adapt(self):
        """D24 — an ability-shifted T1 is no longer the literature-measured
        value while still being labelled T1."""
        for d in registry.all_dimensions():
            if d.tier in ("T1", "T2"):
                self.assertFalse(registry.adapts(d.dimension_id),
                                 f"{d.dimension_id} is {d.tier} and must not adapt")

    def test_t3_and_corpus_rel_adapt(self):
        self.assertTrue(registry.adapts("wpm"))       # CORPUS_REL

    def test_unknown_does_not_adapt(self):
        self.assertFalse(registry.adapts("invented"))


class TestLiveSet(unittest.TestCase):
    def test_six_live_dimensions(self):
        live = {d.dimension_id for d in registry.live_dimensions()}
        self.assertEqual(live, {"wpm", "fillers", "pause_ms", "dynamic_db",
                                "pitch_center", "energy"})

    def test_live_is_a_strict_subset(self):
        """Specified-but-not-built is the normal state, and it must stay
        visible: a monitor over a measure nobody produces reports STABLE
        forever, which is indistinguishable from working."""
        self.assertLess(len(registry.live_dimensions()),
                        len(registry.all_dimensions()))

    def test_every_live_dimension_is_wired_in_session_metrics(self):
        """The registry and the plumbing must not drift apart: a dimension
        marked live with nowhere to read it from is a silent no-op.

        Reads the SOURCE rather than importing it — services.session_metrics
        pulls in services.db and therefore the supabase client, which this
        pure-unit suite must not require.
        """
        import pathlib
        import re
        source = (pathlib.Path(__file__).parent
                  / "services" / "session_metrics.py").read_text()
        block = re.search(r"_SNIPPET_FIELDS\s*=\s*\{(.*?)\n\}", source,
                          re.DOTALL)
        self.assertIsNotNone(block, "_SNIPPET_FIELDS not found")
        wired = set(re.findall(r'"([a-z_]+)":\s*\(', block.group(1)))
        for d in registry.live_dimensions():
            self.assertIn(d.dimension_id, wired,
                          f"{d.dimension_id} is live but has no snippet field")


class TestImmutability(unittest.TestCase):
    def test_a_consumer_cannot_edit_the_spec(self):
        d = registry.get("wpm")
        with self.assertRaises(Exception):
            d.window_class = "SESSION"      # frozen dataclass


if __name__ == "__main__":
    unittest.main()
