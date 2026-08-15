"""willab — state-generic ternary ratings (SPEC.md v3 §3.2, §6, §17).

services/state_ratings.py.

WHAT THIS PINS DOWN:
  * the INSTRUMENT — yes/no/neutral on one clip, and `unrateable` as a
    SEPARATE control rather than a fourth value. Folding the two would book
    unclear audio as a real middling rating and poison the one class that
    defines the decision boundary;
  * STRICT TYPES — this is training data, so a truthy string is refused
    rather than coerced. A coerced value records a verdict no human gave and
    is indistinguishable from a real one afterwards;
  * the OPERATIONAL-DEFINITION GATE (§1.4) — a state with no written
    definition cannot be asked about, so validation refuses it;
  * LANE derivation — a coach rating an IMPORT is `bootstrap`, not `coach`.
    One rater on a model-proposed candidate is not panel-grade however expert
    the rater, and the distinction cannot be reconstructed later;
  * AGGREGATION — bootstrap is excluded from the panel by default;
    `unrateable` rows are counted but never aggregated;
  * QUALITY — sample size DOMINATES agreement, by decision. A five-rater
    panel at 60% must outweigh a two-rater unanimous one, because the panel
    estimates a population percept and two people agreeing is a small sample,
    not a strong finding.

Run: python3 -m unittest test_state_ratings
"""
from __future__ import annotations

import unittest

from services.state_ratings import (
    LANES,
    PANEL_LANES,
    VALUES,
    aggregate,
    corpus_summary,
    describe_question,
    quality,
    question_for_state,
    resolve_lane,
    validate_rating,
)


def _rating(value=None, lane="coach", unrateable=False, rater="r1"):
    return {"value": value, "lane": lane, "unrateable": unrateable,
            "rater_id": rater}


class TestInstrument(unittest.TestCase):
    def test_three_values_exactly(self):
        self.assertEqual(set(VALUES), {"yes", "no", "neutral"})

    def test_accepts_each_value(self):
        for v in VALUES:
            row, err = validate_rating({"state_id": "confidence", "value": v})
            self.assertIsNone(err, f"{v} rejected: {err}")
            self.assertEqual(row["value"], v)
            self.assertFalse(row["unrateable"])

    def test_rejects_a_fourth_value(self):
        _, err = validate_rating({"state_id": "confidence", "value": "idk"})
        self.assertIsNotNone(err)

    def test_unrateable_is_not_a_value(self):
        """The control carries no answer, and an answer is not a refusal."""
        row, err = validate_rating(
            {"state_id": "confidence", "unrateable": True})
        self.assertIsNone(err)
        self.assertIsNone(row["value"])
        self.assertTrue(row["unrateable"])

    def test_unrateable_with_a_value_is_refused(self):
        _, err = validate_rating({"state_id": "confidence", "value": "yes",
                                  "unrateable": True})
        self.assertIsNotNone(err)

    def test_missing_value_is_refused(self):
        _, err = validate_rating({"state_id": "confidence"})
        self.assertIsNotNone(err)


class TestStrictTypes(unittest.TestCase):
    """Training data: refuse, never coerce."""

    def test_truthy_string_unrateable_refused(self):
        _, err = validate_rating({"state_id": "confidence", "value": "yes",
                                  "unrateable": "true"})
        self.assertIsNotNone(err)

    def test_bool_latency_refused(self):
        _, err = validate_rating({"state_id": "confidence", "value": "yes",
                                  "latency_ms": True})
        self.assertIsNotNone(err)

    def test_negative_latency_refused(self):
        _, err = validate_rating({"state_id": "confidence", "value": "yes",
                                  "latency_ms": -1})
        self.assertIsNotNone(err)

    def test_non_object_body_refused(self):
        for bad in (None, [], "yes", 3):
            _, err = validate_rating(bad)
            self.assertIsNotNone(err)


class TestOperationalDefinitionGate(unittest.TestCase):
    """§1.4 — no written definition, no question."""

    def test_unknown_state_refused(self):
        _, err = validate_rating({"state_id": "vibes", "value": "yes"})
        self.assertIsNotNone(err)
        self.assertIn("operational definition", err)

    def test_confidence_resolves_to_v1(self):
        self.assertEqual(question_for_state("confidence"), "conf-q-v1")

    def test_question_version_is_stamped_on_the_row(self):
        """Unversioned rows cannot be split after a wording change, which
        would silently blend two constructs."""
        row, _ = validate_rating({"state_id": "confidence", "value": "yes"})
        self.assertEqual(row["question_version"], "conf-q-v1")

    def test_question_text_is_single_barrelled(self):
        """'confident AND authoritative' was two constructs in one question."""
        text = describe_question("conf-q-v1")["text"]
        self.assertNotIn(" and ", text.lower())

    def test_retired_version_still_resolves(self):
        """Pre-cutover rows must stay interpretable."""
        self.assertIsNotNone(describe_question("conf-q-v0"))

    def test_saw_model_output_is_always_false(self):
        """I1 — stored so the invariant is auditable, not assumed."""
        row, _ = validate_rating({"state_id": "confidence", "value": "yes",
                                  "saw_model_output": True})
        self.assertFalse(row["saw_model_output"])


class TestLaneDerivation(unittest.TestCase):
    def test_coach_on_import_is_bootstrap(self):
        self.assertEqual(
            resolve_lane("training_import", is_coach=True), "bootstrap")

    def test_coach_on_a_real_take_is_coach(self):
        self.assertEqual(resolve_lane("audit_upload", is_coach=True), "coach")

    def test_owner_and_peer_split(self):
        self.assertEqual(
            resolve_lane("audit_upload", is_coach=False, is_owner=True),
            "game_owner")
        self.assertEqual(
            resolve_lane("audit_upload", is_coach=False), "game_peer")

    def test_every_derived_lane_is_declared(self):
        for src in ("training_import", "audit_upload", None):
            for coach in (True, False):
                self.assertIn(resolve_lane(src, is_coach=coach), LANES)

    def test_bootstrap_is_not_a_panel_lane(self):
        self.assertNotIn("bootstrap", PANEL_LANES)

    def test_owner_is_not_a_panel_lane(self):
        """SPEC 9.1 — the quorum is model + coach + PEER. The owner is not one
        of the three, and rates their own recording, so admitting the lane
        would count self-assessment as inter-rater agreement."""
        self.assertNotIn("game_owner", PANEL_LANES)

    def test_panel_is_exactly_coach_and_peer(self):
        """Pinned as a set so the constant cannot quietly regrow a lane."""
        self.assertEqual(set(PANEL_LANES), {"coach", "game_peer"})


class TestQuality(unittest.TestCase):
    def test_sample_size_dominates_agreement(self):
        """THE decision: 5 raters at 60% beats 2 unanimous."""
        self.assertGreater(quality(5, 0.6), quality(2, 1.0))

    def test_monotone_in_both_terms(self):
        self.assertGreater(quality(5, 1.0), quality(5, 0.6))
        self.assertGreater(quality(5, 1.0), quality(2, 1.0))

    def test_bounded_open_interval(self):
        for n in (1, 2, 5, 10, 100):
            for a in (0.0, 0.5, 1.0):
                q = quality(n, a)
                self.assertGreater(q, 0.0)
                self.assertLess(q, 1.0)

    def test_agreement_never_zeroes_the_product(self):
        """Ambiguity is a finding (I10), not an absence of one."""
        self.assertGreater(quality(5, 0.0), 0.0)

    def test_single_rater_is_heavily_discounted(self):
        self.assertLess(quality(1, 1.0), 0.4)

    def test_garbage_is_zero_not_an_exception(self):
        for bad in (None, "x", -1):
            self.assertEqual(quality(bad, 1.0), 0.0)


class TestAggregation(unittest.TestCase):
    def test_unanimous_yes(self):
        agg = aggregate([_rating("yes", rater=f"r{i}") for i in range(3)])
        self.assertEqual(agg["value"], 1.0)
        self.assertEqual(agg["agreement"], 1.0)
        self.assertEqual(agg["n_raters"], 3)

    def test_split_lowers_agreement_not_count(self):
        agg = aggregate([_rating("yes"), _rating("no"), _rating("yes")])
        self.assertEqual(agg["n_raters"], 3)
        self.assertAlmostEqual(agg["agreement"], 2 / 3, places=3)

    def test_neutral_is_a_real_class_at_zero(self):
        agg = aggregate([_rating("neutral"), _rating("neutral")])
        self.assertEqual(agg["value"], 0.0)
        self.assertEqual(agg["by_value"]["neutral"], 2)

    def test_bootstrap_excluded_by_default(self):
        """One expert on a model-proposed candidate is not a panel."""
        agg = aggregate([_rating("yes", lane="bootstrap")])
        self.assertIsNone(agg)

    def test_bootstrap_included_only_when_asked(self):
        agg = aggregate([_rating("yes", lane="bootstrap")], lanes=LANES)
        self.assertIsNotNone(agg)
        self.assertEqual(agg["n_raters"], 1)

    def test_unrateable_counted_but_not_aggregated(self):
        agg = aggregate([_rating("yes"), _rating(None, unrateable=True)])
        self.assertEqual(agg["n_raters"], 1)
        self.assertEqual(agg["unrateable_n"], 1)
        self.assertEqual(agg["value"], 1.0)

    def test_all_unrateable_is_no_label(self):
        self.assertIsNone(
            aggregate([_rating(None, unrateable=True) for _ in range(3)]))

    def test_empty_and_garbage_are_none(self):
        self.assertIsNone(aggregate([]))
        self.assertIsNone(aggregate(None))
        self.assertIsNone(aggregate(["nonsense", 3]))

    def test_quality_rides_the_aggregate(self):
        agg = aggregate([_rating("yes", rater=f"r{i}") for i in range(5)])
        self.assertAlmostEqual(agg["quality"], quality(5, 1.0), places=4)


class TestCorpusSummary(unittest.TestCase):
    def test_flags_a_missing_class(self):
        """Three classes, so chance is 1/3 — a corpus missing a class cannot
        teach the boundary it exists to find."""
        s = corpus_summary([_rating("yes"), _rating("yes"), _rating("no")])
        self.assertEqual(s["classes_present"], 2)
        self.assertEqual(s["by_value"]["neutral"], 0)

    def test_balance_exposes_a_skewed_corpus(self):
        rows = [_rating("yes") for _ in range(9)] + [_rating("no")]
        s = corpus_summary(rows)
        self.assertAlmostEqual(s["balance"]["yes"], 0.9, places=3)

    def test_lanes_are_broken_out(self):
        s = corpus_summary([_rating("yes", lane="bootstrap"),
                            _rating("yes", lane="coach")])
        self.assertEqual(s["by_lane"]["bootstrap"], 1)
        self.assertEqual(s["by_lane"]["coach"], 1)

    def test_unrateable_not_counted_as_answered(self):
        s = corpus_summary([_rating("yes"),
                            _rating(None, unrateable=True)])
        self.assertEqual(s["answered"], 1)
        self.assertEqual(s["unrateable"], 1)

    def test_empty_corpus_has_no_balance(self):
        s = corpus_summary([])
        self.assertIsNone(s["balance"])


if __name__ == "__main__":
    unittest.main()


class AnchoredSelfCheckTests(unittest.TestCase):
    """"Do you agree?" on the Confident Voice card (founder 2026-08-15).

    The card shows the machine's read and THEN asks. That rating is anchored,
    and the corpus has to say so — an anchored label is indistinguishable
    from a blind one once stored, which is why I1 exists."""

    def test_blind_is_the_DEFAULT_not_a_choice(self):
        # A caller that forgets gets the old, stricter behaviour. The only
        # way to record an anchored row is for a route to say so.
        row, err = validate_rating({"state_id": "confidence",
                                    "value": "yes"})
        self.assertIsNone(err)
        self.assertIs(row["saw_model_output"], False)

    def test_the_anchored_surface_RECORDS_it(self):
        row, err = validate_rating({"state_id": "confidence", "value": "yes"},
                                   saw_model_output=True)
        self.assertIsNone(err)
        self.assertIs(row["saw_model_output"], True)

    def test_the_PAYLOAD_can_never_set_it(self):
        # I1's storage half: facts about the rater's SCREEN are stamped
        # server-side, because a client that could describe its own screen
        # could describe it wrongly.
        row, _ = validate_rating({"state_id": "confidence", "value": "yes",
                                  "saw_model_output": True})
        self.assertIs(row["saw_model_output"], False)

    def test_the_owner_lane_still_cannot_reach_quorum(self):
        # Excluded TWICE over — the owner is not a peer (rule 2), and this
        # rating was anchored (I1). Both by constants that already exist.
        from services.label_quorum import QUORUM_LANES
        from services.state_ratings import PANEL_LANES, resolve_lane
        lane = resolve_lane("app", is_coach=False, is_owner=True)
        self.assertEqual(lane, "game_owner")
        self.assertNotIn(lane, PANEL_LANES)
        self.assertNotIn(lane, QUORUM_LANES)

    def test_the_route_stamps_it_rather_than_trusting_the_client(self):
        import inspect

        from routes.v2 import user_sessions as us
        src = inspect.getsource(us.v2_put_confidence_agree)
        self.assertIn("saw_model_output=True", src)
        self.assertIn("self_report=True", src)
        # The machine's proposal is read from storage, never from the body.
        self.assertIn("machine_proposal(snip)", src)
