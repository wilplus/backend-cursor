"""Unit tests for services/manager_engine.py — Appendix H.

Pins the parameters that are DERIVED (so a tune has to argue with a study)
and the invariants that fail silently (a note deleted rather than demoted, two
suppressors compounding into permanent silence, escalation on repetition).

Run: python3 -m unittest test_manager_engine
"""
from __future__ import annotations

import unittest
from dataclasses import replace

from services import manager_engine as me


def _c(dimension="wpm", **kw):
    args = dict(dimension=dimension, grade="A", deviation=1.0, ppv=0.9,
                anchor=(0.0, 1.0))
    args.update(kw)
    return me.Candidate(**args)


def _user(state=me.NOVICE, dims=("wpm",), **kw):
    args = dict(state_by_dimension={d: state for d in dims},
                p_mastery={}, sessions_since_fired={d: 99 for d in dims})
    args.update(kw)
    return me.UserState(**args)


class TestCertaintyFloor(unittest.TestCase):
    """H.2 — 0.70 is Wickens & Dixon's crossover, below which the aid is
    worse than no aid. Not a preference dial."""

    def test_the_floor_is_the_published_crossover(self):
        self.assertEqual(me.PPV_FLOOR, 0.70)
        self.assertEqual(me.PPV_TARGET, 0.85)

    def test_below_the_floor_never_submits(self):
        self.assertFalse(me.may_submit(_c(ppv=0.69)))
        self.assertTrue(me.may_submit(_c(ppv=0.70)))

    def test_a_low_ppv_candidate_is_dropped_with_its_reason(self):
        out = me.arbitrate([_c(ppv=0.4)], _user())
        self.assertEqual(out["selected"], [])
        self.assertIn("ppv", out["rejected"][0][1])


class TestBudget(unittest.TestCase):
    """H.1 — flat, never scaled to recording length."""

    def test_a_novice_gets_exactly_one_at_any_length(self):
        user = _user(me.NOVICE, dims=("a", "b", "c", "d"))
        cands = [_c(f"d{i}", anchor=(i * 10.0, i * 10.0 + 1)) for i in range(4)]
        self.assertEqual(me.budget(user, cands), 1)

    def test_above_novice_caps_at_three_independent(self):
        user = _user(me.APPRENTICE, dims=[f"d{i}" for i in range(6)])
        cands = [_c(f"d{i}", anchor=(i * 10.0, i * 10.0 + 1)) for i in range(6)]
        self.assertEqual(me.budget(user, cands), 2)

    def test_budget_never_drops_below_one(self):
        self.assertEqual(me.budget(_user(me.GRADUATE, dims=("a",)), []), 1)

    def test_an_unknown_dimension_is_treated_as_novice(self):
        """Fail-safe direction under H.0: a dimension with no recorded state
        caps the session at one rather than opening it to three."""
        user = me.UserState()
        self.assertEqual(me.budget(user, [_c("never_seen"), _c("also_new")]), 1)

    def test_fragile_and_graduate_are_not_capped_at_one(self):
        """Founder decision 2026-08-06. The fading arc governs frequency and
        phrasing, not the per-session ceiling — G(state) does the suppressing,
        on priority, and the two mechanisms are separate."""
        for state in (me.APPRENTICE, me.FRAGILE, me.GRADUATE):
            user = _user(state, dims=("d0", "d1", "d2"))
            cands = [_c(f"d{i}", anchor=(i * 10.0, i * 10.0 + 1))
                     for i in range(3)]
            self.assertEqual(me.budget(user, cands), 2, f"{state} was capped")

    def test_the_leading_candidates_state_governs(self):
        """Appendix B makes state PER-DIMENSION, so one has to be picked. The
        leading candidate is the note that will certainly surface, so the
        user's competence at THAT thing is the load signal that matters."""
        user = me.UserState(state_by_dimension={"lead": me.NOVICE,
                                                "other": me.GRADUATE})
        cands = [_c("lead", anchor=(0.0, 1.0)), _c("other", anchor=(9.0, 10.0))]
        self.assertEqual(me.budget(user, cands), 1)

    def test_an_untouched_novice_dimension_does_not_cap_a_graduate(self):
        """The failure mode the founder decision rules out: reading the
        least-advanced dimension anywhere would let one dimension the user
        never sees cap them at a single note forever."""
        user = me.UserState(state_by_dimension={"never_shown": me.NOVICE,
                                                "lead": me.GRADUATE,
                                                "second": me.GRADUATE})
        cands = [_c("lead", anchor=(0.0, 1.0)), _c("second", anchor=(9.0, 10.0))]
        self.assertEqual(me.budget(user, cands), 2)


class TestSuppressionFloor(unittest.TestCase):
    """§8.2 / B.4 — the invariant that fails silently."""

    def test_priority_never_reaches_zero_from_inaction(self):
        user = _user(me.NOVICE)
        for k in range(0, 25):
            p = me.priority(_c(k=k), user)
            self.assertGreater(p, 0.0, f"k={k} zeroed the note")

    def test_an_unacted_note_is_demoted_not_deleted(self):
        user = _user(me.NOVICE)
        fresh = me.priority(_c(k=0), user)
        stale = me.priority(_c(k=1), user)
        self.assertLess(stale, fresh)
        self.assertGreater(stale, 0.0)

    def test_the_floor_is_on_the_product_not_each_factor(self):
        """THE B.4 INVARIANT. R alone floors at 0.20 and G(GRADUATE) is 0.50;
        multiplied that is 0.10, below the 0.15 the product must hold. Two
        suppressors each above their own floor still fall through both."""
        user = _user(me.GRADUATE, dims=("wpm",))
        c = _c(k=99, deviation=1.0)                    # R at its own floor
        self.assertAlmostEqual(me.r_decay(99), 0.20)
        self.assertAlmostEqual(me.g_gate(me.GRADUATE), 0.50)
        self.assertAlmostEqual(me.priority(c, user), me.PRIORITY_FLOOR)

    def test_a_spike_bypasses_both_suppressors_at_full_weight(self):
        """The escape hatch resurfaces a collapse at full weight, not at the
        floor — a graduate who falls apart gets the note back properly."""
        user = _user(me.GRADUATE, dims=("wpm",))
        c = _c(k=99, deviation=4.0, baseline_deviation=1.0)
        self.assertTrue(me.is_spike(c))
        self.assertAlmostEqual(me.priority(c, user), 4.0)

    def test_no_baseline_is_not_a_spike(self):
        """Missing baseline must fail closed, or every first-ever candidate
        would bypass the cooldown."""
        self.assertFalse(me.is_spike(_c(deviation=99.0)))
        self.assertFalse(me.is_spike(_c(deviation=99.0, baseline_deviation=0.0)))


class TestCooldownAndMastery(unittest.TestCase):
    """H.6 — going quiet beats staying on (Winstein & Schmidt 1990)."""

    def test_cannot_fire_on_consecutive_recordings(self):
        user = _user(sessions_since_fired={"wpm": 1})
        self.assertTrue(me.in_cooldown(user, "wpm"))
        user = _user(sessions_since_fired={"wpm": 2})
        self.assertFalse(me.in_cooldown(user, "wpm"))

    def test_mastery_goes_silent(self):
        user = _user(p_mastery={"wpm": 0.95}, sessions_since_fired={"wpm": 99})
        self.assertTrue(me.in_cooldown(user, "wpm"))

    def test_mastery_is_revocable(self):
        """A one-way ratchet strands the user — the same defect as a
        promotion-only progression state (B.3)."""
        user = _user(p_mastery={"wpm": 0.80}, sessions_since_fired={"wpm": 99})
        self.assertFalse(me.in_cooldown(user, "wpm"))

    def test_a_spike_overrides_cooldown(self):
        user = _user(sessions_since_fired={"wpm": 0})
        out = me.arbitrate([_c(deviation=5.0, baseline_deviation=1.0)], user)
        self.assertEqual(len(out["selected"]), 1)

    def test_cooldown_without_a_spike_suppresses(self):
        user = _user(sessions_since_fired={"wpm": 0})
        out = me.arbitrate([_c(deviation=5.0, baseline_deviation=100.0)], user)
        self.assertEqual(out["selected"], [])


class TestProgressCoupling(unittest.TestCase):
    """H.4 — the slot where the evidence points against intuition."""

    def test_it_never_escalates(self):
        forms = {me.on_unacted(k) for k in range(1, 30)}
        self.assertNotIn("ESCALATE", forms)
        self.assertEqual(forms, {me.REPEAT_AS_IS, me.REFRAME,
                                 me.CHANGE_INTERVENTION_TYPE})

    def test_the_ladder(self):
        self.assertEqual(me.on_unacted(0), me.FIRST_SHOWING)
        self.assertEqual(me.on_unacted(1), me.REPEAT_AS_IS)
        self.assertEqual(me.on_unacted(2), me.REFRAME)
        self.assertEqual(me.on_unacted(3), me.CHANGE_INTERVENTION_TYPE)

    def test_it_never_repeats_verbatim_past_the_exposure_peak(self):
        """Cacioppo & Petty: agreement peaks at ~3 exposures and declines by
        5. Past the peak more exposure actively reduces persuasion."""
        for k in range(3, 20):
            self.assertEqual(me.on_unacted(k), me.CHANGE_INTERVENTION_TYPE)

    def test_the_form_reaches_the_selected_finding(self):
        out = me.arbitrate([_c(k=2)], _user())
        self.assertEqual(out["selected"][0].form, me.REFRAME)


class TestCollisions(unittest.TestCase):
    """H.5 — element interactivity, not a raw count."""

    def test_trading_dimensions_never_both_at_any_distance(self):
        a = _c("concreteness", anchor=(0.0, 1.0), deviation=2.0)
        b = _c("abstraction", anchor=(500.0, 501.0), deviation=1.0)
        user = _user(me.APPRENTICE, dims=("concreteness", "abstraction"))
        out = me.arbitrate([a, b], user)
        self.assertEqual(len(out["selected"]), 1)
        self.assertEqual(out["selected"][0].dimension, "concreteness")

    def test_overlapping_spans_one_wins(self):
        a = _c("d1", anchor=(0.0, 10.0), deviation=1.0)
        b = _c("d2", anchor=(5.0, 15.0), deviation=2.0)
        kept = me.independent_subset([replace(a, priority=1.0),
                                      replace(b, priority=2.0)])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].dimension, "d2")

    def test_touching_spans_do_not_overlap(self):
        a = _c("d1", anchor=(0.0, 10.0))
        b = _c("d2", anchor=(10.0, 20.0))
        self.assertEqual(len(me.independent_subset([a, b])), 2)

    def test_a_transitive_chain_keeps_both_ends(self):
        """A overlaps B, B overlaps C, A and C do not. Pairwise resolution
        would drop B and stop; the greedy pass keeps A and C."""
        a = _c("a", anchor=(0.0, 10.0), deviation=3.0)
        b = _c("b", anchor=(8.0, 18.0), deviation=2.0)
        c = _c("c", anchor=(16.0, 26.0), deviation=1.0)
        scored = [replace(x, priority=x.deviation) for x in (a, b, c)]
        kept = {x.dimension for x in me.independent_subset(scored)}
        self.assertEqual(kept, {"a", "c"})


class TestGradeGate(unittest.TestCase):
    def test_grade_c_can_never_win(self):
        """D18 — C = 0.0 makes the §11.1 routing gate arithmetic, so the gate
        and the formula cannot drift apart."""
        out = me.arbitrate([_c(grade="C", deviation=999.0)], _user())
        self.assertEqual(out["selected"], [])
        self.assertIn("grade C", out["rejected"][0][1])

    def test_grade_weights_are_the_locked_values(self):
        self.assertEqual(me.EFFECT_SIZE, {"A": 1.0, "B": 0.6, "C": 0.0})


class TestExploration(unittest.TestCase):
    def test_no_roll_means_no_exploration(self):
        user = _user(me.APPRENTICE, dims=("a",))
        cands = [_c(f"d{i}", anchor=(i * 10.0, i * 10.0 + 1),
                    deviation=10.0 - i) for i in range(5)]
        out = me.arbitrate(cands, user)
        self.assertFalse(out["exploration"])

    def test_a_winning_roll_swaps_in_the_next_rank_and_logs_the_road_not_taken(self):
        user = _user(me.APPRENTICE, dims=("a",))
        cands = [_c(f"d{i}", anchor=(i * 10.0, i * 10.0 + 1),
                    deviation=10.0 - i) for i in range(5)]
        out = me.arbitrate(cands, user, roll=lambda: 0.0)
        self.assertTrue(out["exploration"])
        self.assertNotEqual([c.dimension for c in out["selected"]],
                            [c.dimension for c in out["counterfactual"]])
        self.assertTrue(out["selected"][-1].exploration)

    def test_a_losing_roll_does_not_swap(self):
        user = _user(me.APPRENTICE, dims=("a",))
        cands = [_c(f"d{i}", anchor=(i * 10.0, i * 10.0 + 1),
                    deviation=10.0 - i) for i in range(5)]
        out = me.arbitrate(cands, user, roll=lambda: 0.99)
        self.assertFalse(out["exploration"])


class TestArbitrateEndToEnd(unittest.TestCase):
    def test_nothing_in_nothing_out(self):
        out = me.arbitrate([], _user())
        self.assertEqual(out["selected"], [])
        self.assertEqual(out["considered"], 0)

    def test_a_novice_with_five_good_candidates_gets_one(self):
        user = _user(me.NOVICE, dims=("a",))
        cands = [_c(f"d{i}", anchor=(i * 10.0, i * 10.0 + 1),
                    deviation=float(i + 1)) for i in range(5)]
        out = me.arbitrate(cands, user)
        self.assertEqual(len(out["selected"]), 1)
        self.assertEqual(out["selected"][0].dimension, "d4")   # highest priority

    def test_the_order_is_ppv_then_cooldown_then_priority(self):
        """A high-priority candidate below the PPV floor must not survive on
        priority — H.0's asymmetry says the false positive is the expensive
        error, so certainty gates before anything else."""
        loud_but_uncertain = _c("a", deviation=999.0, ppv=0.5,
                                anchor=(0.0, 1.0))
        quiet_but_certain = _c("b", deviation=1.0, ppv=0.95,
                               anchor=(50.0, 51.0))
        out = me.arbitrate([loud_but_uncertain, quiet_but_certain], _user())
        self.assertEqual([c.dimension for c in out["selected"]], ["b"])

    def test_importance_is_injected_not_assumed(self):
        """H.3 — the context modifier defaults to 1.0 and moves only on a
        published moderator. A caller must be able to supply one."""
        user = _user(me.APPRENTICE, dims=("a",))
        cands = [_c("d0", anchor=(0.0, 1.0), deviation=1.0),
                 _c("d1", anchor=(50.0, 51.0), deviation=1.0)]
        out = me.arbitrate(cands, user,
                           importance=lambda d: 5.0 if d == "d1" else 1.0)
        self.assertEqual(out["selected"][0].dimension, "d1")

    def test_every_rejection_carries_a_reason(self):
        user = _user(me.NOVICE, dims=("a",), sessions_since_fired={"x": 0})
        out = me.arbitrate([_c("a", ppv=0.1), _c("x", anchor=(0.0, 1.0)),
                            _c("b", grade="C", anchor=(9.0, 10.0))], user)
        for _, why in out["rejected"]:
            self.assertTrue(why)


class TestScienceControls(unittest.TestCase):
    """The two arms that CANNOT be retrofitted. Both must run while the data
    accumulates or the accumulated data cannot answer the question."""

    def test_the_rates_are_the_decisions_log_values(self):
        self.assertTrue(0.10 <= me.GAMMA_CONTROL <= 0.15)
        self.assertEqual(me.INTERVENTION_RANDOMISATION, 0.20)

    def test_assignment_is_stable_across_processes(self):
        """THE defect that would silently void the experiment. Python's
        hash() on a str is salted per process, so an assignment built on it
        reshuffles every deploy — a control group that reshuffles is noise
        wearing the shape of a control group, and nothing would report it."""
        a = me._stable_fraction("u1", "wpm", salt="s")
        b = me._stable_fraction("u1", "wpm", salt="s")
        self.assertEqual(a, b)
        self.assertNotEqual(a, me._stable_fraction("u1", "wpm", salt="other"))
        self.assertEqual(a, 0.8404391496629088)    # pinned: a change reshuffles

    def test_control_is_per_pair_not_per_user(self):
        """A control user still gets normal feedback on every OTHER
        dimension — their experience is intact and the comparison is within
        person as well as between people."""
        dims = [f"d{i}" for i in range(6)]
        held = [d for d in dims if me.in_control("u0", d)]
        self.assertEqual(held, ["d0"])          # exactly one of six, not all
        self.assertLess(len(held), len(dims), "a whole user was held out")

    def test_control_is_permanent_not_per_session(self):
        """A per-session flip would put the same pair in and out of control
        and measure a user who sometimes got feedback — neither arm."""
        first = me.in_control("u1", "wpm")
        for _ in range(50):
            self.assertEqual(me.in_control("u1", "wpm"), first)

    def test_roughly_the_right_share_is_held(self):
        n = 20_000
        held = sum(me.in_control(f"u{i}", "wpm") for i in range(n))
        self.assertAlmostEqual(held / n, me.GAMMA_CONTROL, delta=0.015)

    def test_withhold_is_roughly_the_right_share(self):
        n = 20_000
        w = sum(me.is_withheld("u1", "wpm", f"s{i}") for i in range(n))
        self.assertAlmostEqual(w / n, me.INTERVENTION_RANDOMISATION,
                               delta=0.015)

    def test_withhold_varies_across_sessions_for_one_pair(self):
        """The within-subject arm: the SAME pair must produce both treated
        and untreated transitions, or there is nothing to compare."""
        seen = {me.is_withheld("u1", "wpm", f"s{i}") for i in range(200)}
        self.assertEqual(seen, {True, False})

    def test_withhold_is_deterministic_for_one_session(self):
        """A retried scoring pass must reach the same decision, or the arm
        depends on how many times the pipeline happened to run."""
        first = me.is_withheld("u1", "wpm", "s1")
        for _ in range(50):
            self.assertEqual(me.is_withheld("u1", "wpm", "s1"), first)

    def test_a_control_dimension_does_not_consume_a_budget_slot(self):
        """Removed from the POOL, not suppressed at the end. Suppressing
        late would quietly give control users less feedback overall, which
        confounds the comparison the arm exists to make."""
        dims = [f"d{i}" for i in range(6)]
        user = me.UserState(user_id="u0",      # u0 holds d0, per the test above
                            state_by_dimension={d: me.APPRENTICE for d in dims})
        cands = [_c(d, anchor=(i * 10.0, i * 10.0 + 1), deviation=6.0 - i)
                 for i, d in enumerate(dims)]
        out = me.arbitrate(cands, user)
        held = set(out["control_held"])
        self.assertTrue(held, "fixture picked no control dimension")
        self.assertEqual(len(out["selected"]), out["budget"])
        for d in held:
            self.assertNotIn(d, [c.dimension for c in out["selected"]])

    def test_a_withheld_note_consumes_its_slot(self):
        """UNLIKE control. Backfilling with rank 2 would mean the untreated
        condition never occurs and the arm would measure rank 1 vs rank 2 —
        which is what epsilon_explore already measures."""
        dims = [f"x{i}" for i in range(6)]
        user = me.UserState(user_id="u9",
                            state_by_dimension={d: me.APPRENTICE for d in dims})
        cands = [_c(d, anchor=(i * 10.0, i * 10.0 + 1), deviation=6.0 - i)
                 for i, d in enumerate(dims)]
        for i in range(200):
            out = me.arbitrate(cands, user, session_id=f"s{i}")
            if out["withheld"]:
                self.assertLess(len(out["selected"]), out["budget"])
                return
        self.fail("no session withheld in 200 tries")

    def test_the_arms_are_recorded_for_the_analysis(self):
        """An outcome with no arm attached is an observation, and the whole
        point of the controls is that these are not observations."""
        out = me.arbitrate([_c()], _user(), session_id="s1")
        self.assertIn("control_held", out)
        self.assertIn("withheld", out)
        self.assertEqual(out["arms"]["gamma_control"], me.GAMMA_CONTROL)
        self.assertEqual(out["arms"]["control_salt"], me.CONTROL_SALT)

    def test_controls_can_be_disabled_for_a_deterministic_caller(self):
        user = me.UserState(user_id="u1",
                            state_by_dimension={"wpm": me.APPRENTICE})
        out = me.arbitrate([_c()], user, session_id="s1", controls=False)
        self.assertEqual(out["control_held"], [])
        self.assertEqual(out["withheld"], [])

    def test_no_user_id_means_no_arm(self):
        """Fail OPEN on the controls: an anonymous or unattributed candidate
        must not be silently assigned to a control group whose membership
        can never be recovered."""
        self.assertFalse(me.in_control("", "wpm"))
        self.assertFalse(me.is_withheld("", "wpm", "s1"))
        self.assertFalse(me.is_withheld("u1", "wpm", ""))


class TestTakeBudgetSpent(unittest.TestCase):
    """Founder 2026-08-10 — the ≤3 is PER TAKE. `budget_spent` subtracts
    already-decided interventions from H.1's cap inside arbitrate, so an
    accept never frees a slot for a fresh note to trickle in behind it:
    "each feedback needs to be there; full and end to end and waiting; not
    that it appears once the other is accepted." """

    def _run(self, spent, n=6, roll=None):
        user = _user(me.APPRENTICE, dims=[f"d{i}" for i in range(n)])
        cands = [_c(f"d{i}", anchor=(i * 10.0, i * 10.0 + 1))
                 for i in range(n)]
        return me.arbitrate(cands, user, controls=False, roll=roll,
                            budget_spent=spent)

    def test_one_decided_serves_two(self):
        self.assertEqual(len(self._run(1)["selected"]), 1)

    def test_three_decided_serves_nothing(self):
        self.assertEqual(self._run(3)["selected"], [])

    def test_overspend_never_goes_negative(self):
        self.assertEqual(self._run(7)["selected"], [])

    def test_the_recorded_budget_is_the_remaining_one(self):
        self.assertEqual(self._run(2)["budget"], 0)

    def test_exploration_cannot_resurrect_a_spent_budget(self):
        """`selected[:-1] + [swap]` over an empty selection would serve one
        note past the take's ceiling — the n > 0 guard is the fence."""
        out = self._run(3, roll=lambda: 0.0)   # a firing roll
        self.assertEqual(out["selected"], [])
        self.assertFalse(out["exploration"])


class TestArmRows(unittest.TestCase):
    """PM-8 — the experiment's record. Running the controls without this is
    strictly WORSE than not running them: users pay the cost in withheld
    feedback and no causal claim is recoverable."""

    def _rows(self, dims=("d0", "d1", "d2", "d3"), user="u0", session="s1",
              **kw):
        state = {d: me.APPRENTICE for d in dims}
        user_state = me.UserState(user_id=user, state_by_dimension=state)
        cands = [_c(d, anchor=(i * 10.0, i * 10.0 + 1), deviation=4.0 - i)
                 for i, d in enumerate(dims)]
        out = me.arbitrate(cands, user_state, session_id=session, **kw)
        return out, me.arm_rows(out, session_id=session, user_id=user)

    def test_every_considered_dimension_gets_exactly_one_row(self):
        """Per-note would give the untreated arms no rows at all and record
        only the treatment group."""
        dims = ("d0", "d1", "d2", "d3")
        _, rows = self._rows(dims)
        self.assertEqual(sorted(r["dimension_id"] for r in rows), sorted(dims))

    def test_surfaced_agrees_with_the_arm(self):
        """Mirrors ck_intervention_arms_surfaced_agrees. Without it the
        withheld arm can be corrupted into the treated one by a caller bug
        and the comparison still looks populated."""
        _, rows = self._rows()
        for r in rows:
            self.assertEqual(r["surfaced"],
                             r["arm"] in (me.ARM_TREATED, me.ARM_EXPLORE))

    def test_control_records_unknown_not_false(self):
        """The holdout is removed BEFORE ranking, so whether it would have
        won is genuinely unknown. Writing False would assert something never
        tested."""
        _, rows = self._rows(dims=("d0", "d1", "d2", "d3", "d4", "d5"))
        control = [r for r in rows if r["arm"] == me.ARM_CONTROL]
        self.assertTrue(control, "fixture produced no control row")
        for r in control:
            self.assertIsNone(r["would_have_surfaced"])
            self.assertFalse(r["surfaced"])

    def test_a_withheld_note_is_recorded_as_having_won(self):
        """The within-subject untreated condition, and the only evidence it
        occurred at all."""
        for i in range(200):
            out, rows = self._rows(session=f"s{i}")
            withheld = [r for r in rows if r["arm"] == me.ARM_WITHHELD]
            if withheld:
                for r in withheld:
                    self.assertTrue(r["would_have_surfaced"])
                    self.assertFalse(r["surfaced"])
                return
        self.fail("no session withheld in 200 tries")

    def test_the_policy_is_stamped_on_every_row(self):
        """Assignment is a pure function of (salt, user_id, dimension), so
        rows either side of a salt change belong to two different
        experiments. Reading the constants at analysis time would silently
        re-interpret old rows under a new policy."""
        _, rows = self._rows()
        for r in rows:
            self.assertEqual(r["control_salt"], me.CONTROL_SALT)
            self.assertEqual(r["withhold_salt"], me.WITHHOLD_SALT)
            self.assertEqual(r["gamma"], me.GAMMA_CONTROL)
            self.assertEqual(r["withhold_rate"], me.INTERVENTION_RANDOMISATION)

    def test_the_arm_shares_come_out_near_the_configured_rates(self):
        """The health check the table exists for: an EMPTY CONTROL ARM means
        the controls are running and the record is not."""
        seen = {}
        for i in range(400):
            _, rows = self._rows(user=f"u{i}", session=f"s{i}")
            for r in rows:
                seen[r["arm"]] = seen.get(r["arm"], 0) + 1
        total = sum(seen.values())
        self.assertGreater(seen.get(me.ARM_CONTROL, 0) / total, 0.05)
        self.assertIn(me.ARM_WITHHELD, seen)
        self.assertIn(me.ARM_TREATED, seen)

    def test_an_empty_arbitration_writes_nothing(self):
        out = me.arbitrate([], _user(), session_id="s1")
        self.assertEqual(me.arm_rows(out, session_id="s1", user_id="u1"), [])

    def test_no_user_id_still_records_the_row(self):
        """Fails open on the ARM, not on the record: an unattributed
        candidate gets no arm assignment, but its consideration is still
        evidence and must not vanish."""
        out = me.arbitrate([_c()], me.UserState(state_by_dimension={}),
                           session_id="s1")
        rows = me.arm_rows(out, session_id="s1", user_id="")
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["user_id"])


class TestArmRowsDedup(unittest.TestCase):

    def test_two_same_lane_winners_produce_one_row(self):
        """Two lane:polish winners in one serve would otherwise emit two
        rows with the same (session_id, dimension_id) key inside a single
        upsert — Postgres rejects the whole statement (21000: row affected
        twice), the writer's best-effort except swallows it, and the serve
        is recorded as ZERO rows. First winner carries the lane's row, the
        same rule as the withheld/control/rejected loops."""
        result = {"selected": [_c("lane:polish"), _c("lane:polish")],
                  "withheld": [], "control_held": [], "rejected": [],
                  "arms": {}}
        rows = me.arm_rows(result, session_id="s1", user_id="u1")
        self.assertEqual(
            [r["dimension_id"] for r in rows], ["lane:polish"])


class TestStatesAndConstants(unittest.TestCase):
    def test_fragile_is_a_real_state_and_does_not_fade(self):
        """B.2.1 — FRAGILE performs well and cannot tell why, so fading
        produces regression the user will not detect."""
        self.assertIn(me.FRAGILE, me.STATES)
        self.assertEqual(me.g_gate(me.FRAGILE), 1.0)

    def test_every_state_has_a_gate(self):
        for s in me.STATES:
            self.assertIn(s, me.G_BY_STATE)

    def test_an_unknown_state_does_not_suppress(self):
        """Failing open on the SUPPRESSOR is the safe direction — failing
        closed would silence a dimension because of a typo."""
        self.assertEqual(me.g_gate("MISTYPED"), 1.0)


if __name__ == "__main__":
    unittest.main()
