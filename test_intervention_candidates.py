"""The manager engine is the SOLE source of `changes` (founder 2026-08-07).

THE BUG THIS CLOSES. `services/manager_engine.py` is a complete, tested
arbitration policy — the ≤3 budget, collision resolution, the certainty floor,
the three randomisation arms — and it had NO CALLER IN PRODUCTION. Meanwhile
`_tracked_changes_block` concatenated three lanes and served all of them. So
Appendix H's budget was enforced nowhere, and the number of marks on a
student's document was whatever the lanes happened to produce.

WHAT THESE TESTS ARE FOR. Two different failures, and only the first is
obvious:

  1. the budget does not hold — more than three marks reach the screen;
  2. a lane goes ROUND the engine. That one is silent: the payload looks
     normal, the tests for each individual lane still pass, and the only
     symptom is a fourth highlight nobody can account for. So the wiring is
     pinned structurally as well as behaviourally.

AC-9 is checked here rather than assumed: `priority`, `ppv` and `deviation`
are arbitration inputs, and a change dict that carried one of them would put
an internal number on a client-facing schema.

Run: python3 -m unittest test_intervention_candidates
"""
from __future__ import annotations

import ast
import pathlib
import unittest
from unittest.mock import patch

from services import intervention_candidates as ic
from services import manager_engine as me

ROOT = pathlib.Path(__file__).parent


def _change(i, *, source="polish", kind="replace", start=None, end=None):
    start = i * 100 if start is None else start
    end = start + 10 if end is None else end
    return {"id": f"c{i}", "snippet_id": f"s{i}", "take_session_id": "t1",
            "kind": kind, "source": source,
            "span": {"start": start, "end": end}, "quote": "x" * (end - start),
            "proposed_text": "y"}


class TestTheStyleLane(unittest.TestCase):
    """Slice 2 (founder 2026-08-11): a locked part's bold proposals ride
    the STYLE LANE — outside the ≤3 budget, beside the budgeted list,
    still window-clamped, never arm-assigned."""

    def _parts(self):
        # One locked part covering [0, 60), one open covering the rest.
        return [
            {"id": "p0", "ord": 0, "text": "x" * 58,
             "locked_at": "2026-08-11T10:00:00Z"},
            {"id": "p1", "ord": 1, "text": "y" * 400},
        ]

    def test_the_style_lane_costs_the_budget_NOTHING(self):
        """Ruling 4: "Outside". A locked part's bold rides beside the
        budgeted list, so the ≤3 still fills up from the open pool — the
        student loses no content feedback to gain a finishing touch.

        (Parked 2026-08-11 — "for now we will dump the colours and styling
        interventions" — and un-parked 2026-08-12 in the lock-flow review.
        The park was one line, which is why this test's assertion moved and
        nothing else did.)"""
        parts = self._parts()
        style = _change(0, kind="bold", start=0, end=8)
        open_pool = [_change(i, start=100 + i * 60, end=108 + i * 60)
                     for i in range(1, 6)]
        out = ic.select([style] + open_pool, parts=parts)
        self.assertEqual(len(out["changes"]), me.BUDGET_CEILING)
        self.assertEqual([c["id"] for c in out["style_changes"]], ["c0"])
        # The style row is never IN the budgeted list — one row rendering
        # twice is the defect the two lanes exist to keep apart.
        self.assertNotIn("c0", [c["id"] for c in out["changes"]])

    def test_a_locked_bold_ALONE_serves_the_style_lane(self):
        parts = self._parts()
        out = ic.select([_change(0, kind="bold", start=0, end=8)],
                        parts=parts)
        self.assertEqual(out["changes"], [])
        self.assertEqual([c["id"] for c in out["style_changes"]], ["c0"])

    def test_an_OPEN_part_s_bold_is_NOT_the_style_lane(self):
        """The lane is defined by the LOCK, not by the kind. An open
        paragraph's accent is an ordinary budgeted offer and must keep
        competing for a slot — routing it outside the budget would let
        every bold in the document bypass the ≤3."""
        parts = self._parts()
        out = ic.select([_change(0, kind="bold", start=100, end=108)],
                        parts=parts)
        self.assertEqual([c["id"] for c in out["changes"]], ["c0"])
        self.assertNotIn("style_changes", out)

    def test_the_style_lane_keeps_the_accent_window(self):
        """A bold past the intonation ceiling paints sentences on accept —
        lock or no lock — so §F.4 clamps the style lane too. The ceiling
        counts WORDS (Chafe's intonation unit), so the fixture must exceed
        it in words, not characters."""
        parts = self._parts()
        wide = _change(0, kind="bold", start=0, end=58)
        wide["quote"] = "one two three four five six seven eight nine " \
                        "ten eleven twelve thirteen"
        out = ic.select([wide], parts=parts)
        self.assertEqual(out["changes"], [])
        self.assertNotIn("style_changes", out)

    def test_the_style_lane_is_CAPPED_at_three_per_take(self):
        """Founder 2026-08-12: "an uncapped style lane would light up the
        screen like a Christmas tree on a long document" — ≤3 per take.

        The lane rides outside the ≤3 AND outside focus, so without this it
        had no ceiling of any kind: one pill per locked chunk, forever."""
        parts = [{"id": f"p{i}", "ord": i, "text": "x" * 40,
                  "locked_at": "2026-08-11T10:00:00Z"} for i in range(6)]
        text = "\n\n".join("x" * 40 for _ in range(6))
        pool = [_change(i, kind="bold", start=i * 42, end=i * 42 + 8)
                for i in range(6)]
        out = ic.select(pool, parts=parts, served_text=text)
        self.assertEqual(len(out["style_changes"]), ic.STYLE_BUDGET_CEILING)
        # DOCUMENT ORDER decides which survive — the same tie-break the
        # budgeted lane uses, and the only honest one while the engine does
        # not rank these (identical grade / deviation / ppv on every row).
        self.assertEqual([c["id"] for c in out["style_changes"]],
                         ["c0", "c1", "c2"])
        # The funnel witnesses the cut rather than silently shrinking.
        self.assertEqual(out["funnel"]["style_proposed"], 6)
        self.assertEqual(out["funnel"]["style_lane"], 3)

    def test_the_style_lane_is_CAPPED_at_one_per_slide(self):
        """One styling suggestion per slide. Per group FIRST, then the flat
        cap: reversed, three accents on one slide would eat the whole take's
        allowance and slides 2+ would get nothing."""
        parts = [{"id": "p0", "ord": 0, "text": "x" * 40,
                  "locked_at": "2026-08-11T10:00:00Z"},
                 {"id": "p1", "ord": 1, "text": "y" * 40,
                  "locked_at": "2026-08-11T10:00:00Z"}]
        text = ("x" * 40) + "\n\n" + ("y" * 40)
        # Three on slide 0, one on slide 1.
        pool = [_change(0, kind="bold", start=0, end=8),
                _change(1, kind="bold", start=10, end=18),
                _change(2, kind="bold", start=20, end=28),
                _change(3, kind="bold", start=42, end=50)]
        out = ic.select(pool, parts=parts, served_text=text)
        # Slide 0 keeps its first; slide 1's accent is NOT starved by
        # slide 0 having proposed more.
        self.assertEqual([c["id"] for c in out["style_changes"]],
                         ["c0", "c3"])

    def test_a_decided_style_proposal_KEEPS_its_slot(self):
        """Cumulative per take, exactly like the budgeted lane and for the
        founder's own reason (2026-08-10): "each feedback needs to be there;
        full and end to end and waiting; not that it appears once the other
        is accepted." Without this, accepting an accent summons a
        replacement — the trickle the take budget was built to kill."""
        parts = [{"id": f"p{i}", "ord": i, "text": "x" * 40,
                  "locked_at": "2026-08-11T10:00:00Z"} for i in range(6)]
        text = "\n\n".join("x" * 40 for _ in range(6))
        pool = [_change(i, kind="bold", start=i * 42, end=i * 42 + 8)
                for i in range(6)]
        self.assertEqual(
            len(ic.select(pool, parts=parts, served_text=text,
                          style_decided_count=1)["style_changes"]), 2)
        self.assertNotIn("style_changes",
                         ic.select(pool, parts=parts, served_text=text,
                                   style_decided_count=3))

    def test_a_slide_s_spent_style_slot_blocks_another_on_that_slide(self):
        parts = [{"id": "p0", "ord": 0, "text": "x" * 40,
                  "locked_at": "2026-08-11T10:00:00Z"},
                 {"id": "p1", "ord": 1, "text": "y" * 40,
                  "locked_at": "2026-08-11T10:00:00Z"}]
        text = ("x" * 40) + "\n\n" + ("y" * 40)
        pool = [_change(0, kind="bold", start=0, end=8),
                _change(1, kind="bold", start=10, end=18),
                _change(2, kind="bold", start=42, end=50)]
        out = ic.select(pool, parts=parts, served_text=text,
                        style_spent_by_paragraph={0: 1})
        # Slide 0 used its only slot; slide 1 is untouched.
        self.assertEqual([c["id"] for c in out["style_changes"]],
                         ["c2"])

    def test_the_cap_is_pure_and_degrades_on_junk(self):
        rows = [{"span": {"start": i, "end": i + 2}} for i in range(5)]
        self.assertEqual(len(ic.cap_style_lane(rows)), 3)
        self.assertEqual(ic.cap_style_lane(None), [])
        self.assertEqual(ic.cap_style_lane([]), [])
        # A count read that failed must not silence the lane — it degrades
        # to the per-serve cap, the same direction every other ledger miss
        # in this pipeline runs.
        self.assertEqual(len(ic.cap_style_lane(rows, spent_count=None)), 3)
        self.assertEqual(len(ic.cap_style_lane(rows, spent_count="x")), 3)
        self.assertEqual(
            len(ic.cap_style_lane(rows, group_of=lambda c: 0,
                                  spent_by_group="not a dict")), 1)

    def test_the_style_lane_BYPASSES_single_point_focus(self):
        """Founder 2026-08-12: "a finishing touch like a bolded word is
        lightweight enough that it shouldn't be suppressed just because the
        paragraph isn't the main structural focus of the take."

        Focus concentrates the STRUCTURAL work. p0 is locked and NOT the
        focus, so its rewrite is suppressed — and its accent is not."""
        parts = self._parts()
        text = ("x" * 58) + "\n\n" + ("y" * 400)
        style_off_focus = _change(0, kind="bold", start=0, end=8)
        # A rewrite on the OPEN focus part, so the two land on different
        # paragraphs and the content-first rule is not what is being tested.
        on_focus = _change(1, kind="replace", start=100, end=110)
        out = ic.select([style_off_focus, on_focus], parts=parts,
                        served_text=text, focus_part_id="p1")
        self.assertEqual([c["id"] for c in out["changes"]], ["c1"])
        self.assertEqual([c["id"] for c in out["style_changes"]], ["c0"])

    def test_focus_still_suppresses_the_BUDGETED_lane(self):
        """The bypass is scoped to style. A rewrite off the focus part is
        suppressed exactly as before — otherwise the exemption would have
        quietly retired single-point focus."""
        parts = self._parts()
        text = ("x" * 58) + "\n\n" + ("y" * 400)
        off_focus = _change(0, kind="replace", start=0, end=8)
        out = ic.select([off_focus], parts=parts, served_text=text,
                        focus_part_id="p1")
        self.assertEqual(out["changes"], [])
        self.assertNotIn("style_changes", out)
        self.assertEqual(out["funnel"]["after_focus"], 0)

    def test_content_first_is_judged_BEFORE_focus_deletes_the_content(self):
        """THE ORDERING, and it is the rule rather than an accident.

        p0 is locked, carries BOTH a rewrite and an accent, and is not the
        focus. Focus will delete the rewrite. If content-first ran after
        that, p0 would stop looking busy and the accent would surface —
        telling the student "this paragraph is fine, just polish it" about
        the one paragraph the engine actually had a rewrite for."""
        parts = self._parts()
        text = ("x" * 58) + "\n\n" + ("y" * 400)
        style = _change(0, kind="bold", start=0, end=8)
        rewrite = _change(1, kind="replace", start=20, end=30)
        out = ic.select([style, rewrite], parts=parts, served_text=text,
                        focus_part_id="p1")
        self.assertEqual(out["changes"], [])          # focus took the rewrite
        self.assertNotIn("style_changes", out)        # …and it stays quiet

    def test_content_still_wins_the_tap_on_the_same_chunk(self):
        """Founder 2026-08-11: "the style intervention appears if it was
        locked in and no new feedback is queued". A gen-4 re-open and a
        style accent on the SAME locked paragraph would compete for one tap,
        and the rewrite is the one that changes what the speech says."""
        parts = self._parts()
        text = ("x" * 58) + "\n\n" + ("y" * 400)
        style = _change(0, kind="bold", start=0, end=8)
        rewrite = _change(1, kind="replace", start=20, end=30)
        out = ic.select([style, rewrite], parts=parts, served_text=text)
        self.assertEqual([c["id"] for c in out["changes"]], ["c1"])
        self.assertTrue(out["changes"][0]["reopens_locked"])
        self.assertNotIn("style_changes", out)
        # …and it comes back the moment nothing louder is queued.
        back = ic.select([style], parts=parts, served_text=text)
        self.assertEqual([c["id"] for c in back["style_changes"]], ["c0"])


class TestTheTakeBudget(unittest.TestCase):
    """Founder 2026-08-10: "each feedback needs to be there; full and end
    to end and waiting; not that it appears once the other is accepted."
    `decided_count` is the take's spent budget — the serve only shrinks."""

    def test_decided_count_shrinks_the_serve(self):
        pool = [_change(i) for i in range(10)]
        self.assertEqual(len(ic.select(pool)["changes"]), 2)
        self.assertEqual(len(ic.select(pool, decided_count=1)["changes"]), 1)
        self.assertEqual(len(ic.select(pool, decided_count=2)["changes"]), 0)

    def test_a_spent_take_serves_nothing(self):
        pool = [_change(i) for i in range(10)]
        self.assertEqual(ic.select(pool, decided_count=3)["changes"], [])

    def test_no_new_candidate_appears_behind_an_accept(self):
        """The founder's exact complaint, pinned: decide the first served
        change (it leaves the pool AND spends a slot) — the next serve is
        the ORIGINAL set minus the decided one, never a fresh face."""
        pool = [_change(i) for i in range(10)]
        first = [c["id"] for c in ic.select(pool)["changes"]]
        remaining = [c for c in pool if c["id"] != first[0]]
        second = [c["id"]
                  for c in ic.select(remaining, decided_count=1)["changes"]]
        self.assertEqual(second, first[1:])


class TestTheBudgetHolds(unittest.TestCase):

    def test_ten_non_overlapping_changes_become_the_cap(self):
        out = ic.select([_change(i) for i in range(10)])["changes"]
        self.assertEqual(len(out), me.BUDGET_CEILING)

    def test_the_cap_is_the_appendix_ceiling_not_a_local_number(self):
        """If someone raises BUDGET_CEILING the cap here moves with it. A
        second hardcoded 3 in the adapter would be a copy that can disagree."""
        self.assertEqual(me.BUDGET_CEILING, 2)

    def test_the_budget_spans_LANES_not_each_lane_separately(self):
        """The load limit is on the speaker. Three lanes producing two marks
        each is six marks on one document, which is the exact failure the
        founder named: 'the old lanes bypassing the engine and throwing extra
        highlights onto the screen destroys the Max 3 budget'."""
        changes = ([_change(i, source="polish") for i in range(2)]
                   + [_change(i + 2, source="prior_take") for i in range(2)]
                   + [_change(i + 4, source="new_take") for i in range(2)])
        self.assertEqual(len(ic.select(changes)["changes"]), 2)

    def test_fewer_than_the_budget_all_survive(self):
        out = ic.select([_change(0), _change(1)])["changes"]
        self.assertEqual([c["id"] for c in out], ["c0", "c1"])

    def test_the_novice_cap_is_not_inherited_by_accident(self):
        """`budget()` caps NOVICE at ONE. An empty UserState defaults every
        dimension to NOVICE, so a caller that did not think about state ships
        a budget of 1 — by omission, not decision. LANE_STATE is the declared
        answer; this pins that it is declared."""
        self.assertNotEqual(ic.LANE_STATE, me.NOVICE)
        state = ic.user_state(ic.to_candidates([_change(0)]))
        self.assertEqual(state.state("lane:polish"), ic.LANE_STATE)


class TestCollisions(unittest.TestCase):

    def test_two_lanes_on_the_same_span_yield_one_mark(self):
        """A polish star and a cross-take offer on the same words would render
        as overlapping strikes. The engine's independent_subset owns this now;
        `drop_overlaps` used to."""
        a = _change(0, source="polish", start=0, end=20)
        b = _change(1, source="prior_take", start=10, end=30)
        out = ic.select([a, b])["changes"]
        self.assertEqual(len(out), 1)

    def test_a_transitive_chain_keeps_both_ends(self):
        """A overlaps B, B overlaps C, A and C do not. A linear
        earliest-wins sweep drops C as well because it only tracks the last
        end; the greedy independent set keeps A and C. This is the behaviour
        difference that makes the engine the right owner of collisions, not
        just a different owner."""
        a = _change(0, start=0, end=20)
        b = _change(1, start=15, end=35)
        c = _change(2, start=30, end=50)
        out = ic.select([a, b, c])["changes"]
        self.assertEqual([x["id"] for x in out], ["c0", "c2"])

    def test_touching_spans_do_not_collide(self):
        out = ic.select([_change(0, start=0, end=10),
                         _change(1, start=10, end=20)])["changes"]
        self.assertEqual(len(out), 2)


class TestOrderAndIdentity(unittest.TestCase):

    def test_survivors_come_back_in_document_order(self):
        """arbitrate() returns them RANKED. The FE renders the document top to
        bottom, so serving the engine's order scatters the marks."""
        out = ic.select([_change(2), _change(0), _change(1)])["changes"]
        self.assertEqual([c["span"]["start"] for c in out], [0, 100])

    def test_the_returned_dicts_are_the_callers_own(self):
        """Mapped back by identity, not rebuilt. A reconstruction would drop
        every field this adapter does not know about — take_index, block_key,
        why_key — and each of those absences is a silently dead control on the
        FE."""
        rows = [_change(0)]
        out = ic.select(rows)["changes"]
        self.assertIs(out[0], rows[0])

    def test_two_lanes_minting_the_same_id_are_still_distinguished(self):
        """`build_tracked_changes` keys on snippet_id and `prior_take` on
        "prior:<snippet_id>", but nothing enforces uniqueness ACROSS lanes.
        Correlating on `id` would collapse two changes into one; `ref` is the
        submission index, unique by construction."""
        a = dict(_change(0, start=0, end=10), id="same")
        b = dict(_change(1, start=50, end=60), id="same")
        out = ic.select([a, b])["changes"]
        self.assertEqual(len(out), 2)
        self.assertIsNot(out[0], out[1])


class TestWhatIsRefused(unittest.TestCase):

    def test_an_undeclared_lane_never_reaches_the_user(self):
        """The gate is the only door, so an unknown source has to die here.
        Admitting it under a guessed key would let a lane nobody decided on
        consume a budget slot."""
        self.assertEqual(ic.select([_change(0, source="mystery")])["changes"],
                         [])

    def test_every_declared_lane_is_admitted(self):
        for src in ic.LANE_SOURCES:
            with self.subTest(src=src):
                out = ic.select([_change(0, source=src)])["changes"]
                self.assertEqual(len(out), 1)

    def test_a_change_with_no_span_is_dropped_not_repaired(self):
        bad = _change(0)
        bad.pop("span")
        self.assertEqual(ic.select([bad, _change(1)])["changes"][0]["id"],
                         "c1")

    def test_a_zero_width_insert_does_not_eat_a_budget_slot(self):
        """`upgrade_changes` anchors candidate block additions at
        {start: len(doc), end: len(doc)} with kind "insert". The FE has always
        dropped those, so they used to cost nothing — behind a budget they
        would win a slot and render as nothing, and the student would see two
        marks where the engine believes it served three."""
        insert = {"id": "block:3", "block_key": 3, "snippet_id": None,
                  "take_session_id": "t1", "kind": "insert",
                  "source": "new_take", "span": {"start": 500, "end": 500},
                  "quote": "", "proposed_text": "a whole new block"}
        out = ic.select([insert, _change(0), _change(1), _change(2)],
                        )["changes"]
        # The zero-width row is refused, so the real changes fill the cap in
        # document order — it never takes a slot ahead of them.
        self.assertEqual([c["id"] for c in out],
                         ["c0", "c1"][:me.BUDGET_CEILING])
        self.assertNotIn("block:3", [c["id"] for c in out])

    def test_failure_serves_NOTHING_rather_than_everything(self):
        """A gatekeeper that fails open is not a gatekeeper. If arbitration
        raises, the unbudgeted list must not be what the student gets."""
        with patch.object(me, "arbitrate", side_effect=RuntimeError("boom")):
            self.assertEqual(ic.select([_change(0)])["changes"], [])

    def test_junk_input_is_survivable(self):
        self.assertEqual(ic.select(None)["changes"], [])
        self.assertEqual(ic.select([None, "nope", 7])["changes"], [])


class TestTheControlsAreOff(unittest.TestCase):
    """The three randomisations are a real experiment. Live since 2026-08-10
    (founder, Task II) — 12% of (user, lane) pairs permanently receive nothing
    from that lane and 20% of winning notes are suppressed. One env var still
    switches the whole thing off in one place."""

    def test_default_on_since_task_II(self):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("MANAGER_CONTROLS_ENABLED", None)
            self.assertTrue(ic._controls_enabled())

    def test_one_env_var_switches_the_experiment_off(self):
        with patch.dict("os.environ", {"MANAGER_CONTROLS_ENABLED": "0"}):
            self.assertFalse(ic._controls_enabled())

    def test_the_user_id_is_withheld_while_they_are_off(self):
        seen = {}

        def _spy(cands, user, **kw):
            seen["user_id"] = user.user_id
            seen["controls"] = kw.get("controls")
            seen["session_id"] = kw.get("session_id")
            return {"selected": []}

        with patch.dict("os.environ", {"MANAGER_CONTROLS_ENABLED": "0"}), \
                patch.object(me, "arbitrate", side_effect=_spy):
            ic.select([_change(0)], user_id="u1", session_id="sess1")
        # An empty id makes in_control()/is_withheld() return False by
        # construction — the arms cannot fire even if `controls` slipped True.
        self.assertEqual(seen["user_id"], "")
        self.assertFalse(seen["controls"])
        self.assertEqual(seen["session_id"], "")

    def test_flipping_the_flag_passes_the_arm_key_through(self):
        seen = {}

        def _spy(cands, user, **kw):
            seen["user_id"] = user.user_id
            seen["controls"] = kw.get("controls")
            return {"selected": []}

        with patch.dict("os.environ", {"MANAGER_CONTROLS_ENABLED": "1"}), \
                patch.object(me, "arbitrate", side_effect=_spy):
            ic.select([_change(0)], user_id="u1", session_id="sess1")
        self.assertEqual(seen["user_id"], "u1")
        self.assertTrue(seen["controls"])


class TestTheExplorationQuota(unittest.TestCase):
    """The roll must be STABLE, not random — this surface is polled."""

    def test_the_same_user_and_session_always_roll_the_same(self):
        # A fresh random draw per request would re-decide the exploration
        # branch every few seconds, swapping the notes on screen while the
        # student watched, and the experiment would measure how many times the
        # pipeline ran rather than whether rank 1 is the best thing to say.
        r1 = me.exploration_roll("u1", "sess-1")
        r2 = me.exploration_roll("u1", "sess-1")
        self.assertEqual(r1(), r2())
        self.assertEqual(r1(), r1())

    def test_different_sessions_roll_differently(self):
        seen = {me.exploration_roll("u1", f"sess-{i}")()
                for i in range(50)}
        self.assertGreater(len(seen), 1)

    def test_no_stable_key_means_no_exploration(self):
        # arbitrate skips the branch entirely on None: silence over a
        # coin-flip nobody could reproduce (H.0).
        self.assertIsNone(me.exploration_roll("", "sess-1"))
        self.assertIsNone(me.exploration_roll("u1", ""))

    def test_the_roll_is_in_range(self):
        for i in range(200):
            self.assertTrue(0.0 <= me.exploration_roll("u", f"s{i}")() < 1.0)

    def test_select_arms_the_quota_when_controls_are_on(self):
        seen = {}

        def _spy(cands, user, **kw):
            seen["roll"] = kw.get("roll")
            return {"selected": []}

        with patch.dict("os.environ", {"MANAGER_CONTROLS_ENABLED": "1"}), \
                patch.object(me, "arbitrate", side_effect=_spy):
            ic.select([_change(0)], user_id="u1", session_id="sess-1")
        self.assertIsNotNone(seen["roll"])
        self.assertEqual(seen["roll"](), seen["roll"]())

    def test_controls_off_disarms_the_quota_too(self):
        seen = {}

        def _spy(cands, user, **kw):
            seen["roll"] = kw.get("roll")
            return {"selected": []}

        with patch.dict("os.environ", {"MANAGER_CONTROLS_ENABLED": "0"}), \
                patch.object(me, "arbitrate", side_effect=_spy):
            ic.select([_change(0)], user_id="u1", session_id="sess-1")
        self.assertIsNone(seen["roll"])


class TestTheArmsAreKeyedOnLanes(unittest.TestCase):
    """Founder decision (Task II): the experiment's unit is the LANE, not a
    registry dimension — deliberately, since no registry dimension can fire
    (every row still has fire_at = None)."""

    def test_every_arm_row_carries_a_lane_key(self):
        with patch.dict("os.environ", {"MANAGER_CONTROLS_ENABLED": "1"}):
            out = ic.select([_change(0, source="polish"),
                             _change(1, source="prior_take")],
                            user_id="u1", session_id="sess-1")
        rows = me.arm_rows(out["result"], session_id="sess-1", user_id="u1")
        self.assertTrue(rows)
        for r in rows:
            self.assertTrue(r["dimension_id"].startswith(ic.LANE_PREFIX),
                            f"{r['dimension_id']} is not a lane key")

    def test_a_lane_key_can_never_collide_with_a_registry_dimension(self):
        # The prefix is what stops an analyst averaging `polish` next to a
        # real `wpm` in the same column.
        from services import dimension_registry as dr
        for d in dr.all_dimensions():
            self.assertFalse(d.dimension_id.startswith(ic.LANE_PREFIX))

    def test_select_reports_whether_an_experiment_ran(self):
        # The caller gates arm PERSISTENCE on this: rows written with the arms
        # inert would stamp the policy as if an assignment had happened.
        with patch.dict("os.environ", {"MANAGER_CONTROLS_ENABLED": "1"}):
            self.assertTrue(ic.select([_change(0)], user_id="u1",
                                      session_id="s1")["controls"])
        with patch.dict("os.environ", {"MANAGER_CONTROLS_ENABLED": "0"}):
            self.assertFalse(ic.select([_change(0)], user_id="u1",
                                       session_id="s1")["controls"])


class TestAC9(unittest.TestCase):

    def test_no_arbitration_number_reaches_the_payload(self):
        out = ic.select([_change(0)])["changes"][0]
        for internal in ("priority", "ppv", "deviation", "grade", "arm",
                         "form", "exploration"):
            self.assertNotIn(internal, out)

    def test_the_ppv_is_the_published_floor_and_is_declared_an_assumption(self):
        """0.70 is Wickens & Dixon's crossover. Sitting exactly ON it is the
        weakest claim that still ships — and a lane later MEASURED below it
        then dies automatically, which only works while nobody has quietly
        raised the constant to make something surface."""
        self.assertEqual(ic.LANE_PPV, me.PPV_FLOOR)
        self.assertTrue(me.may_submit(ic.to_candidates([_change(0)])[0]))

    def test_grade_C_would_silence_everything(self):
        """EFFECT_SIZE['C'] is 0.0, so a C-graded candidate has priority
        exactly 0 and can never win. Pinned because 'we have no measured
        effect size' reads like an argument for C."""
        self.assertEqual(me.EFFECT_SIZE["C"], 0.0)
        self.assertGreater(me.EFFECT_SIZE[ic.LANE_GRADE], 0.0)


class TestMvpFeedbackContract(unittest.TestCase):
    def test_surfaces_at_most_one_of_each_approved_family(self):
        confident = _change(0, source="confident_voice", kind="bold")
        confident["snippet_audio_ref"] = "https://audio.example/clip.webm"
        formulation = _change(1, source="wording", kind="bold")
        duplicate_formulation = _change(2, source="wording", kind="bold")
        rewrite = _change(3, source="wording", kind="replace")
        out = ic.select(
            [confident, formulation, duplicate_formulation, rewrite],
            mvp_feedback_contract=True,
        )["changes"]
        self.assertEqual(len(out), 3)
        self.assertEqual(
            {row["feedback_family"] for row in out},
            {"confident_voice", "great_formulation", "rewrite_clarity"},
        )

    def test_confident_voice_without_playable_audio_is_not_surfaced(self):
        confident = _change(0, source="confident_voice", kind="bold")
        out = ic.select([confident], mvp_feedback_contract=True)["changes"]
        self.assertEqual(out, [])

    def test_verbal_feedback_does_not_require_audio(self):
        formulation = _change(0, source="wording", kind="bold")
        rewrite = _change(1, source="wording", kind="replace")
        out = ic.select(
            [formulation, rewrite], mvp_feedback_contract=True
        )["changes"]
        self.assertEqual(
            {row["feedback_family"] for row in out},
            {"great_formulation", "rewrite_clarity"},
        )

    def test_confident_voice_reserved_slot_survives_single_point_focus(self):
        served = "focus words\n\nvoice words"
        parts = [
            {"id": "focus", "ord": 0, "text": "focus words",
             "locked_at": None},
            {"id": "voice", "ord": 1, "text": "voice words",
             "locked_at": None},
        ]
        rewrite = _change(0, source="wording", kind="replace",
                          start=0, end=5)
        rewrite["quote"] = "focus"
        confident = _change(1, source="confident_voice", kind="bold",
                            start=13, end=18)
        confident["quote"] = "voice"
        confident["snippet_audio_ref"] = "https://audio.example/clip.webm"
        out = ic.select(
            [rewrite, confident],
            served_text=served,
            parts=parts,
            focus_part_id="focus",
            mvp_feedback_contract=True,
        )["changes"]
        self.assertEqual(
            {row["feedback_family"] for row in out},
            {"confident_voice", "rewrite_clarity"},
        )


class TestNothingBypassesTheGate(unittest.TestCase):
    """The structural half. A lane added later must not be able to append to
    the served list after the gate has run — that failure is invisible in the
    payload and every per-lane test would still pass.

    Read through the AST, never the source text. A comment EXPLAINING the
    fence would otherwise trip it, which is a mistake this repo has now made
    three times."""

    SERVE = ROOT / "routes" / "v2" / "explore_ideal_text.py"

    def _fn(self):
        tree = ast.parse(self.SERVE.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) \
                    and node.name == "_tracked_changes_block":
                return node
        raise AssertionError("_tracked_changes_block not found")

    def _gate_line(self, fn):
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "_select":
                return node.lineno
        raise AssertionError("the gate is not called at all")

    def test_the_serve_path_imports_and_calls_the_gate(self):
        fn = self._fn()
        imported = any(
            isinstance(n, ast.ImportFrom)
            and n.module == "services.intervention_candidates"
            and any(a.name == "select" for a in n.names)
            for n in ast.walk(fn))
        self.assertTrue(imported, "the gate is not imported")
        self.assertGreater(self._gate_line(fn), 0)

    def test_nothing_extends_changes_after_the_gate(self):
        """Every lane's `changes.extend(...)` must sit ABOVE the `_select`
        call. One below it is a lane serving straight to the user."""
        fn = self._fn()
        gate = self._gate_line(fn)
        for node in ast.walk(fn):
            appends = (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("extend", "append")
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "changes"
            ) or (
                isinstance(node, ast.AugAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "changes"
            )
            if appends:
                self.assertLess(
                    node.lineno, gate,
                    f"line {node.lineno} adds to `changes` after the gate")

    def test_the_old_unbudgeted_sweep_is_gone(self):
        """`drop_overlaps` resolved collisions BEFORE any budget existed.
        Leaving it in front of the gate would hide candidates from the engine;
        leaving it after would be a second, disagreeing owner of the same
        rule. The function still EXISTS (other callers, its own tests) — it
        just may not run on the serve path."""
        fn = self._fn()
        names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
        imported = {a.name for n in ast.walk(fn)
                    if isinstance(n, ast.ImportFrom) for a in n.names}
        self.assertNotIn("drop_overlaps", names | imported)



class TestTheWindowGate(unittest.TestCase):
    """SPEC-APPENDIX-F §F.4 (founder 2026-08-10): accents are UNIT-window
    interventions. An accent-class offer whose quote runs past the ceiling
    would paint sentences on accept — the founder's screenshot — so it never
    becomes an offer, and the budget never spends a slot on it."""

    def _accent(self, i, words, *, kind="bold", trigger=None):
        c = _change(i, kind=kind)
        c["quote"] = " ".join(["word"] * words)
        if trigger:
            c["trigger"] = trigger
        return c

    def test_an_oversize_accent_never_becomes_an_offer(self):
        out = ic.select([self._accent(0, 40)])["changes"]
        self.assertEqual(out, [])

    def test_a_unit_sized_accent_passes(self):
        out = ic.select([self._accent(0, 8)])["changes"]
        self.assertEqual(len(out), 1)

    def test_the_ceiling_is_the_shared_constant_not_a_local_number(self):
        from services.ideal_text_block import ACCENT_WINDOW_MAX_WORDS
        ok = ic.select([self._accent(0, ACCENT_WINDOW_MAX_WORDS)])["changes"]
        over = ic.select(
            [self._accent(0, ACCENT_WINDOW_MAX_WORDS + 1)])["changes"]
        self.assertEqual(len(ok), 1)
        self.assertEqual(over, [])

    def test_composition_is_not_windowed(self):
        """A block upgrade is legitimately block-sized: the window rule is
        about PAINT, and composition paints a diff, not a wash."""
        c = _change(0, kind="replace")
        c["quote"] = " ".join(["word"] * 80)
        self.assertEqual(len(ic.select([c])["changes"]), 1)

    def test_confident_voice_passes_regardless_of_size(self):
        """The star is a badge at the span's end, never a painted wash — the
        window rule does not bind it."""
        c = self._accent(0, 80, kind="advice", trigger="charisma")
        c["device"] = "contrast"
        self.assertEqual(len(ic.select([c])["changes"]), 1)

    def test_an_unmeasurable_accent_is_dropped_not_guessed(self):
        c = self._accent(0, 8)
        del c["quote"]
        self.assertEqual(ic.select([c])["changes"], [])




class TestTheOpsTable(unittest.TestCase):
    """Appendix C, wired live (founder GO 2026-08-10). The closed set is the
    layer that never grows; presentation derives from the TYPE alone; and the
    mix caps stop one lane monopolising the flat budget — the founder's
    "the interventions are only the text rewrites"."""

    def test_the_C2_mapping_is_pinned(self):
        cases = [
            ({"kind": "replace"}, "REWRITE"),
            ({"kind": "replace", "source": "new_take"}, "REWRITE"),
            ({"kind": "insert"}, "ADD"),
            ({"kind": "bold"}, "EMPHASISE"),
            ({"kind": "advice", "device": "contrast"}, "EMPHASISE"),
            ({"kind": "advice", "trigger": "charisma"}, "NOTICE"),
        ]
        for change, want in cases:
            self.assertEqual(ic.intervention_type_of(change), want, change)

    def test_presentation_derives_from_type_never_from_lane(self):
        """C.4's one rule. Two changes of the same type from different lanes
        must render identically."""
        a = ic.visual_of({"kind": "replace", "source": "new_take"})
        b = ic.visual_of({"kind": "replace", "source": "polish"})
        self.assertEqual(a, b)
        self.assertEqual(ic.visual_of({"kind": "bold"}), "bold")
        self.assertEqual(
            ic.visual_of({"kind": "advice", "trigger": "charisma"}), "star")
        self.assertEqual(ic.visual_of({"kind": "insert"}), "underline")

    def test_rewrites_cannot_eat_the_whole_budget(self):
        """Five block rewrites + one metric emphasise: the pool caps REWRITE
        at 2, so the emphasise ALWAYS survives to the served three."""
        rewrites = [_change(i, kind="replace") for i in range(5)]
        accent = _change(9, kind="bold")
        accent["quote"] = "land these words"
        out = ic.select(rewrites + [accent])["changes"]
        kinds = [c["kind"] for c in out]
        self.assertIn("bold", kinds)
        self.assertLessEqual(kinds.count("replace"), 2)
        self.assertLessEqual(len(out), 3)

    def test_within_the_cap_document_order_still_decides(self):
        """The kept rewrites are the FIRST in document order — the same
        tie-break the engine itself uses, so capping changes WHICH lanes mix,
        never which rewrite wins among rewrites."""
        rewrites = [_change(i, kind="replace") for i in range(4)]
        accent = _change(9, kind="bold")
        accent["quote"] = "short phrase"
        kept = ic.filter_by_type_caps(rewrites + [accent])
        self.assertEqual([c["id"] for c in kept], ["c0", "c9"])

    def test_an_all_rewrite_pool_is_NOT_rationed(self):
        """A cap reserves space for a mix; with nothing to mix, serving two
        of an available three would starve the student for no benefit."""
        rewrites = [_change(i, kind="replace") for i in range(5)]
        self.assertEqual(len(ic.filter_by_type_caps(rewrites)), 5)
        self.assertEqual(len(ic.select(rewrites)["changes"]),
                         me.BUDGET_CEILING)

    def test_uncapped_types_pass_freely(self):
        accents = []
        for i in range(4):
            a = _change(i, kind="bold")
            a["quote"] = "short phrase here"
            accents.append(a)
        self.assertEqual(len(ic.filter_by_type_caps(accents)), 4)

    def test_notice_is_never_capped_by_the_rewrite_row(self):
        """Confident Voice is NOTICE — its own row. A wall of rewrites must
        not silence the badge."""
        rewrites = [_change(i, kind="replace") for i in range(5)]
        cv = _change(8, kind="advice")
        cv["trigger"] = "charisma"
        cv["device"] = "contrast"
        kept = ic.filter_by_type_caps(rewrites + [cv])
        self.assertIn("c8", [c["id"] for c in kept])


class TestTheFunnel(unittest.TestCase):
    """Eight gates stand between a stored suggestion and the screen, and every
    one of them drops SILENTLY.

    "Five suggestion rows in the table, one note on the page" cost a night of
    database queries to narrow, and the answer was never recoverable from the
    outside: a pool emptied by the PPV floor and a pool emptied by cooldown
    looked identical. arbitrate() had computed the reason for every rejection
    the whole time and the caller discarded it."""

    def test_the_funnel_counts_every_stage(self):
        out = ic.select([_change(i) for i in range(5)], session_id="s1")
        f = out["funnel"]
        for stage in ("in", "after_layer", "after_window", "after_type_caps",
                      "arbitrated", "served"):
            self.assertIn(stage, f)
        self.assertEqual(f["in"], 5)
        self.assertEqual(f["served"], len(out["changes"]))

    def test_it_names_WHY_the_rest_went(self):
        out = ic.select([_change(i) for i in range(5)], session_id="s1")
        # Five candidates, a cap of two: the other three lost the budget, and
        # the funnel says so in those words rather than leaving a subtraction
        # for the reader to do.
        self.assertEqual(out["funnel"]["rejected"].get("budget"),
                         5 - me.BUDGET_CEILING)

    def test_an_EMPTY_serve_still_reports_where_it_emptied(self):
        # The case that matters most: nothing on screen, and the funnel is
        # the only witness to which gate did it.
        #
        # A locked part now RELEASES almost everything: a rewrite and its
        # advice re-open the chunk (gen-4), and a bold rides the style lane
        # (gen-3, un-parked 2026-08-12). What the layer filter still empties
        # on is a kind NO LAYER CLASSIFIES — nobody decided the phase rules
        # for it, so defaulting it in would let an unnamed lane touch locked
        # text. That is the honest fixture for "the pool emptied HERE".
        locked = [{"id": "p0", "ord": 0, "text": "x" * 200,
                   "locked_at": "2026-08-11T10:00:00Z"}]
        out = ic.select([_change(0, kind="teleport", start=0, end=10)],
                        parts=locked, session_id="s1")
        self.assertEqual(out["changes"], [])
        self.assertNotIn("style_changes", out)
        self.assertEqual(out["funnel"]["in"], 1)
        self.assertEqual(out["funnel"]["after_layer"], 0)

    def test_required_confident_voice_is_not_randomly_held_out(self):
        cv = _change(0, source="confident_voice", kind="bold",
                     start=0, end=8)
        cv["quote"] = "confident"
        cv["snippet_audio_ref"] = "signed://take-2-snippet"
        rewrite = _change(1, start=100, end=110)
        with patch.object(ic, "_controls_enabled", return_value=True), \
             patch.object(me, "in_control", return_value=True), \
             patch.object(me, "is_withheld", return_value=True):
            out = ic.select(
                [cv, rewrite],
                user_id="u1",
                session_id="take-2",
                mvp_feedback_contract=True,
            )
        self.assertEqual([row["id"] for row in out["changes"]], ["c0"])
        self.assertEqual(
            out["result"]["protected"],
            ["lane:feedback:confident_voice"],
        )
        # Required product behavior is outside the experiment, so no fake
        # TREATED arm is written for it.
        arm_dimensions = {
            row["dimension_id"] for row in me.arm_rows(
                out["result"], session_id="take-2", user_id="u1")
        }
        self.assertNotIn("lane:feedback:confident_voice", arm_dimensions)

    def test_an_EMPTY_INPUT_still_writes_a_funnel_line(self, ):
        """FOUNDER INCIDENT 2026-08-12. This branch used to return silently.

        He recorded eleven takes, saw no feedback, searched the web log for
        `intervention funnel`, and found lines belonging to a DIFFERENT
        session — because his own arc had produced no line to find. An
        instrument that goes quiet exactly when the thing it measures is at
        zero sends you looking downstream at a serving layer that was
        working fine. `in: 0` says the problem is UPSTREAM of the gate, and
        that is a different investigation from every drop below it."""
        with self.assertLogs("services.intervention_candidates",
                             level="INFO") as caught:
            out = ic.select([], session_id="s1")
        self.assertEqual(out["changes"], [])
        self.assertEqual(out["funnel"], {"in": 0})
        self.assertTrue(any("intervention funnel" in m and "s1" in m
                            for m in caught.output), caught.output)

    def test_the_funnel_never_reaches_the_client(self):
        # AC-9 is about what a USER sees. The funnel carries rejection reasons
        # with PPV numbers in them and belongs in a server log — the change
        # dicts must stay exactly what they were.
        out = ic.select([_change(i) for i in range(3)], session_id="s1")
        for c in out["changes"]:
            self.assertNotIn("funnel", c)
            self.assertNotIn("priority", c)
            self.assertNotIn("ppv", c)


if __name__ == "__main__":
    unittest.main()
