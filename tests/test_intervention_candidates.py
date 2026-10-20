"""
STORY    As a speaker, I want at most the budgeted number of marks on my
         document, one per span, from known lanes only, and nothing at all if
         arbitration fails, so that the page stays focused and honest.
OUTCOME
  O1  The budget holds: more than BUDGET_CEILING changes in, at most
      BUDGET_CEILING served; overlapping changes serve one mark; a
      zero-width insert never takes a slot.
  O2  Only declared lanes are served; a change with no span is dropped.
  O3  If arbitration fails, nothing is served.
  O4  Never-1 (no numbers to speakers): a served change carries no internal
      number (priority, ppv, deviation) and no funnel.
  O5  Accents on a locked part ride the style lane: outside the budget,
      capped per Take, not suppressed by single-point focus.
  O6  Confident Voice needs playable audio, keeps its reserved slot, is not
      capped by rewrites and is not bound by the accent window; an accent
      past the window is never offered.
  O7  The controls flag passes the arm key through; an empty serve still
      logs where the pool emptied.
PROVES   O1 -> test_the_budget_holds, test_two_lanes_on_the_same_span_yield_one_mark,
               test_a_zero_width_insert_does_not_eat_a_budget_slot
         O2 -> test_an_undeclared_lane_never_reaches_the_user,
               test_every_declared_lane_is_admitted,
               test_a_change_with_no_span_is_dropped_not_repaired
         O3 -> test_failure_serves_NOTHING_rather_than_everything
         O4 -> test_the_funnel_never_reaches_the_client
         O5 -> test_a_decided_style_proposal_KEEPS_its_slot,
               test_the_cap_is_pure_and_degrades_on_junk,
               test_the_style_lane_BYPASSES_single_point_focus
         O6 -> test_confident_voice_without_playable_audio_is_not_surfaced,
               test_confident_voice_reserved_slot_survives_single_point_focus,
               test_notice_is_never_capped_by_the_rewrite_row,
               test_confident_voice_passes_regardless_of_size,
               test_the_ceiling_is_the_shared_constant_not_a_local_number
         O7 -> test_flipping_the_flag_passes_the_arm_key_through,
               test_an_EMPTY_serve_still_reports_where_it_emptied,
               test_an_EMPTY_INPUT_still_writes_a_funnel_line
WHY      2026-08-07: manager_engine had no production caller, so the budget
         was enforced nowhere and every lane's marks reached the page.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from config import Config
from services import intervention_candidates as ic
from services import manager_engine as me


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


class TestCollisions(unittest.TestCase):

    def test_the_budget_holds(self):
        pool = [_change(i) for i in range(me.BUDGET_CEILING + 4)]
        out = ic.select(pool, session_id="s1")["changes"]
        self.assertTrue(out)
        self.assertLessEqual(len(out), me.BUDGET_CEILING)

    def test_two_lanes_on_the_same_span_yield_one_mark(self):
        """A polish star and a cross-take offer on the same words would render
        as overlapping strikes. The engine's independent_subset owns this now;
        `drop_overlaps` used to."""
        a = _change(0, source="polish", start=0, end=20)
        b = _change(1, source="prior_take", start=10, end=30)
        out = ic.select([a, b])["changes"]
        self.assertEqual(len(out), 1)


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
        """`upgrade_changes` (since deleted) anchored candidate block additions at
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


class TestTheControlsAreOff(unittest.TestCase):
    """The three randomisations are a real experiment. Live since 2026-08-10
    (founder, Task II) — 12% of (user, lane) pairs permanently receive nothing
    from that lane and 20% of winning notes are suppressed. One env var still
    switches the whole thing off in one place."""


    def test_flipping_the_flag_passes_the_arm_key_through(self):
        seen = {}

        def _spy(cands, user, **kw):
            seen["user_id"] = user.user_id
            seen["controls"] = kw.get("controls")
            return {"selected": []}

        with patch.object(Config, "MANAGER_CONTROLS_ENABLED", True), \
                patch.object(me, "arbitrate", side_effect=_spy):
            ic.select([_change(0)], user_id="u1", session_id="sess1")
        self.assertEqual(seen["user_id"], "u1")
        self.assertTrue(seen["controls"])


class TestMvpFeedbackContract(unittest.TestCase):

    def test_confident_voice_without_playable_audio_is_not_surfaced(self):
        confident = _change(0, source="confident_voice", kind="bold")
        out = ic.select([confident], mvp_feedback_contract=True)["changes"]
        self.assertEqual(out, [])


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
        praise = _change(2, source="structural", kind="advice",
                         start=0, end=5)
        praise["quote"] = "focus"
        out = ic.select(
            [rewrite, confident, praise],
            served_text=served,
            parts=parts,
            focus_part_id="focus",
            mvp_feedback_contract=True,
        )["changes"]
        self.assertEqual(
            {row["feedback_family"] for row in out},
            {"confident_voice", "rewrite_clarity", "great_formulation"},
        )


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


    def test_the_ceiling_is_the_shared_constant_not_a_local_number(self):
        from services.ideal_text_block import ACCENT_WINDOW_MAX_WORDS
        ok = ic.select([self._accent(0, ACCENT_WINDOW_MAX_WORDS)])["changes"]
        over = ic.select(
            [self._accent(0, ACCENT_WINDOW_MAX_WORDS + 1)])["changes"]
        self.assertEqual(len(ok), 1)
        self.assertEqual(over, [])


    def test_confident_voice_passes_regardless_of_size(self):
        """The star is a badge at the span's end, never a painted wash — the
        window rule does not bind it."""
        c = self._accent(0, 80, kind="advice", trigger="charisma")
        c["device"] = "contrast"
        self.assertEqual(len(ic.select([c])["changes"]), 1)


class TestTheOpsTable(unittest.TestCase):
    """Appendix C, wired live (founder GO 2026-08-10). The closed set is the
    layer that never grows; presentation derives from the TYPE alone; and the
    mix caps stop one lane monopolising the flat budget — the founder's
    "the interventions are only the text rewrites"."""


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
        self.assertTrue(out["changes"])
        for c in out["changes"]:
            self.assertEqual(c["quote"], "x" * 10)
            for internal in ("funnel", "priority", "ppv", "deviation"):
                self.assertNotIn(internal, c)


if __name__ == "__main__":
    unittest.main()
