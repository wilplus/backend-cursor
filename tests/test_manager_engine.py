"""Unit tests for services/manager_engine.py — Appendix H.

Pins the parameters that are DERIVED (so a tune has to argue with a study)
and the invariants that fail silently (a note deleted rather than demoted, two
suppressors compounding into permanent silence, escalation on repetition).

Run: python3 -m unittest tests.test_manager_engine
"""
from __future__ import annotations

import unittest

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


class TestProgressCoupling(unittest.TestCase):
    """H.4 — the slot where the evidence points against intuition."""

    def test_it_never_escalates(self):
        forms = {me.on_unacted(k) for k in range(1, 30)}
        self.assertNotIn("ESCALATE", forms)
        self.assertEqual(forms, {me.REPEAT_AS_IS, me.REFRAME,
                                 me.CHANGE_INTERVENTION_TYPE})


class TestExploration(unittest.TestCase):


    # The exploration trade's own rules (audit W1: the stages arbitrate()
    # was split into are pinned here, not only through the whole call).
    def _five(self):
        return [_c(f"d{i}", anchor=(i * 10.0, i * 10.0 + 1),
                   deviation=10.0 - i) for i in range(5)]

    def test_a_protected_note_never_gives_up_its_slot(self):
        """The Take contract's Confident Voice slot is protected: with every
        selected note protected, there is nothing to trade and exploration
        sits this one out."""
        user = _user(me.APPRENTICE, dims=("a",))
        out = me.arbitrate(
            self._five(), user, roll=lambda: 0.0,
            protected_dimensions=[f"d{i}" for i in range(5)])
        self.assertFalse(out["exploration"])
        self.assertEqual([c.dimension for c in out["selected"]],
                         [c.dimension for c in out["counterfactual"]])

    def test_per_slide_exploration_trades_inside_the_swaps_own_slide(self):
        """Grouped (per slide): the swap takes the slot of the lowest-ranked
        note on ITS slide, so a slide can never go past its cap."""
        user = _user(me.APPRENTICE, dims=("a",))
        out = me.arbitrate(self._five(), user, roll=lambda: 0.0,
                           group_of=lambda c: 0)
        self.assertTrue(out["exploration"])
        chosen = [c.dimension for c in out["counterfactual"]]
        served = [c.dimension for c in out["selected"]]
        self.assertEqual(len(served), len(chosen))
        self.assertNotIn(chosen[-1], served)       # the lowest-ranked gave way
        self.assertEqual(served[:-1], chosen[:-1])
        self.assertTrue(out["selected"][-1].exploration)


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


if __name__ == "__main__":
    unittest.main()


# ── the science arms after the 2026-09-18 ruling (Appendix H.13.4) ──
