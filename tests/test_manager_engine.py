"""
STORY    As the founder, I want the feedback arbitration's experiment honest
         (protected Confident Voice slot, per-slide exploration, withheld
         notes recorded as having won), so that we can later learn what
         feedback helps.
OUTCOME
  O1  A protected note never gives up its slot to exploration or withholding.
  O2  Exploration trades only inside the swapped note's own slide.
  O3  Every withheld note is logged as would_have_surfaced, not surfaced.
  O4  Take 1 is never withheld from (science arms, 2026-09-18 ruling).
  O5  A note shown again and again unacted is never escalated.
PROVES   O1 -> test_a_protected_note_never_gives_up_its_slot,
               test_a_withheld_note_is_recorded_as_having_won
         O2 -> test_per_slide_exploration_trades_inside_the_swaps_own_slide
         O3 -> test_a_withheld_note_is_recorded_as_having_won
         O4 -> test_take_one_is_never_withheld_from
         O5 -> test_a_repeated_unacted_note_is_reframed_never_escalated
WHY      Appendix H (H.4, H.7, H.13.4); PM-8 the experiment's record.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

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


def _four(**kw):
    return [_c(d, anchor=(i * 10.0, i * 10.0 + 1), deviation=4.0 - i, **kw)
            for i, d in enumerate(("d0", "d1", "d2", "d3"))]


class TestProgressCoupling(unittest.TestCase):
    """H.4 — the slot where the evidence points against intuition."""

    def test_a_repeated_unacted_note_is_reframed_never_escalated(self):
        user = _user(me.APPRENTICE, dims=("wpm",))
        forms = []
        for k in (1, 2, 5, 29):
            out = me.arbitrate([_c("wpm", k=k)], user, controls=False)
            forms.append(out["selected"][0].form)
        self.assertEqual(forms, [me.REPEAT_AS_IS, me.REFRAME,
                                 me.CHANGE_INTERVENTION_TYPE,
                                 me.CHANGE_INTERVENTION_TYPE])


class TestExploration(unittest.TestCase):

    def _five(self):
        return [_c(f"d{i}", anchor=(i * 10.0, i * 10.0 + 1),
                   deviation=10.0 - i) for i in range(5)]

    def test_a_protected_note_never_gives_up_its_slot(self):
        """With every selected note protected there is nothing to trade, and
        exploration sits this one out."""
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
    """PM-8 — the experiment's record. Withholding without this row is
    strictly worse than not running the arm."""

    def _arbitrate(self, *, take_index, protected=()):
        user = me.UserState(user_id="u0", state_by_dimension={
            d: me.APPRENTICE for d in ("d0", "d1", "d2", "d3")})
        # Rate 1.0: every eligible winner is withheld, so the case is
        # deterministic rather than a hunt for a session that hashes low.
        with patch.object(me, "INTERVENTION_RANDOMISATION", 1.0):
            out = me.arbitrate(_four(), user, session_id="s1",
                               take_index=take_index,
                               protected_dimensions=list(protected))
        return out, me.arm_rows(out, session_id="s1", user_id="u0")

    def test_a_withheld_note_is_recorded_as_having_won(self):
        out, rows = self._arbitrate(take_index=2, protected=("d0",))
        withheld = [r for r in rows if r["arm"] == me.ARM_WITHHELD]
        self.assertTrue(withheld)
        self.assertEqual({r["dimension_id"] for r in withheld},
                         set(out["withheld"]))
        for r in withheld:
            self.assertTrue(r["would_have_surfaced"])
            self.assertFalse(r["surfaced"])
        # The protected note is still shown, never withheld.
        self.assertEqual([c.dimension for c in out["selected"]], ["d0"])

    def test_take_one_is_never_withheld_from(self):
        out, rows = self._arbitrate(take_index=1)
        self.assertFalse(out["withheld"])
        self.assertTrue(out["selected"])
        self.assertNotIn(me.ARM_WITHHELD, {r["arm"] for r in rows})


if __name__ == "__main__":
    unittest.main()
