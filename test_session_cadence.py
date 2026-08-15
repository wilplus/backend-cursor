"""Explore-Session cadence (willab Prompt A §4). Pure beat-selection + spec
integrity + the fire path with a stubbed renderer/db (no LLM, no network).

Run: python3 -m unittest test_session_cadence
"""
from __future__ import annotations

import unittest

import services.session_cadence as sc


class _FakeDB:
    def __init__(self):
        self.inserted = []

    def insert_lounge_messages(self, user_id, messages):
        # Mirror the real upsert-on-(user_id, client_id) idempotency.
        out = []
        for m in messages:
            key = (user_id, m["client_id"])
            if key in [(u, c) for (u, c, _) in self.inserted]:
                continue
            self.inserted.append((user_id, m["client_id"], m))
            out.append({"id": "srv", **m})
        return out


class BeatSelectionTests(unittest.TestCase):
    def test_take_1_invites_chill(self):
        b = sc.select_post_take_beat(1)
        self.assertEqual(b["beat_no"], 1)
        self.assertEqual(b["mode"], "Confidant (chill)")

    def test_take_2_invites_data(self):
        self.assertEqual(sc.select_post_take_beat(2)["beat_no"], 2)

    def test_take_3_spark_gated(self):
        self.assertIsNone(sc.select_post_take_beat(3, spark_enabled=False))
        self.assertEqual(
            sc.select_post_take_beat(3, spark_enabled=True)["beat_no"], 3,
        )

    def test_after_last_planned_take_is_silent(self):
        self.assertIsNone(sc.select_post_take_beat(4))
        self.assertIsNone(sc.select_post_take_beat(4, spark_enabled=True))

    def test_bad_take_index_is_silent(self):
        self.assertIsNone(sc.select_post_take_beat(None))
        self.assertIsNone(sc.select_post_take_beat("garbage"))


class SpecIntegrityTests(unittest.TestCase):
    """The doctrine (§4) — these are the load-bearing fence assertions."""

    def test_beat0_frames_with_fixed_facts_and_goal(self):
        b = sc.BEATS[0]
        self.assertTrue(b["weave_goal"])
        joined = " ".join(b["fixed_facts"]).lower()
        # #2 (2026-06-21): no time promise (the baseline may run under 30 min);
        # just the 3 takes + the reset.
        self.assertNotIn("30 minute", joined)
        self.assertNotIn("30 min", joined)
        # Hard COUNTS survive verbatim in the fixed-fact channel (the renderer
        # preserves them): the 3 takes, the reset, and the 3 setups.
        self.assertIn("3 times", joined)
        self.assertIn("reset", joined)
        self.assertIn("3 different setups", joined)
        # FENCE: the SOFT day-spacing nudge must NOT live in fixed_facts —
        # pinned verbatim it reads as a floor/requirement. It belongs in
        # `intent` (asserted below), where the renderer can voice + soften it.
        self.assertNotIn("different day", joined)

    def test_recording_cadence_nudge_lives_in_translatable_intent(self):
        # founder 2026-06-27 (recording-cadence guidance): 3 different setups +
        # at least one on a different day — back-to-back/same-setup lowers the
        # analysis quality. NUDGE-ONLY: it lives in the translatable BEAT 0
        # intent, framed as an invitation, never gated/pinned as a fact.
        intent = sc.BEATS[0]["intent"].lower()
        self.assertIn("setup", intent)
        self.assertIn("day", intent)

    def test_core_take_beats_stay_invitational(self):
        # The cadence INVITES, never gates/grades — no requirement language and
        # no time promise leaks into the three core-take beats (0, 1, 2). The
        # new spacing nudge is purely relative ("another day"), never an
        # absolute duration commitment (preserves the 2026-06-21 no-time rule).
        for n in (0, 1, 2):
            intent = sc.BEATS[n]["intent"].lower()
            for gate in ("must", "required", "have to", "need to"):
                self.assertNotIn(gate, intent, f"beat {n}: gate word '{gate}'")
            for t in ("30 min", "minute", "hour"):
                self.assertNotIn(t, intent, f"beat {n}: time promise '{t}'")

    def test_spark_beat_carries_full_safety_caveat(self):
        b = sc.BEATS[3]
        self.assertTrue(b.get("spark_only"))
        caveat = b["safety_caveat"].lower()
        # §7 wellbeing fence — every required clause must be present.
        for needle in ("optional", "able", "march", "breath",
                       "skipping", "not medical"):
            self.assertIn(needle, caveat, needle)

    def test_modes_match_the_three_registers(self):
        self.assertIsNone(sc.BEATS[0]["mode"])
        self.assertIn("chill", sc.BEATS[1]["mode"].lower())
        self.assertIn("data", sc.BEATS[2]["mode"].lower())
        self.assertIn("energ", sc.BEATS[3]["mode"].lower())


class FirePathTests(unittest.TestCase):
    """fire_* with the renderer stubbed — no LLM, no network."""

    def setUp(self):
        self._orig = sc._render_beat
        sc._render_beat = lambda beat, **kw: f"[rendered beat {beat['beat_no']}]"

    def tearDown(self):
        sc._render_beat = self._orig

    def test_fire_post_take_inserts_cadence_bubble(self):
        fake = _FakeDB()
        ok = sc.fire_post_take("u1", "arc1", 1, take_count=1, database=fake)
        self.assertTrue(ok)
        self.assertEqual(len(fake.inserted), 1)
        _, _, msg = fake.inserted[0]
        self.assertEqual(msg["kind"], "cadence")
        self.assertEqual(msg["role"], "bot")
        self.assertEqual(msg["metadata"]["beat"], 1)
        self.assertEqual(msg["metadata"]["arc_id"], "arc1")

    def test_fire_is_idempotent_per_arc_and_beat(self):
        fake = _FakeDB()
        sc.fire_post_take("u1", "arc1", 1, database=fake)
        sc.fire_post_take("u1", "arc1", 1, database=fake)  # re-fire same beat
        self.assertEqual(len(fake.inserted), 1)  # no duplicate

    def test_fire_post_take_silent_after_arc_done(self):
        fake = _FakeDB()
        self.assertFalse(sc.fire_post_take("u1", "arc1", 3, database=fake))
        self.assertEqual(len(fake.inserted), 0)

    def test_fire_arc_start_beat0(self):
        fake = _FakeDB()
        ok = sc.fire_arc_start("u1", "arc1", goal="land my keynote", database=fake)
        self.assertTrue(ok)
        _, _, msg = fake.inserted[0]
        self.assertEqual(msg["metadata"]["beat"], 0)

    def test_no_user_or_arc_is_noop(self):
        fake = _FakeDB()
        self.assertFalse(sc.fire_post_take(None, "arc1", 1, database=fake))
        self.assertFalse(sc.fire_post_take("u1", None, 1, database=fake))
        self.assertFalse(sc.fire_arc_start(None, "arc1", database=fake))
        self.assertEqual(len(fake.inserted), 0)

    def test_render_failure_skips_insert(self):
        sc._render_beat = lambda beat, **kw: None  # render fails → no hardcode
        fake = _FakeDB()
        self.assertFalse(sc.fire_post_take("u1", "arc1", 1, database=fake))
        self.assertEqual(len(fake.inserted), 0)


class BubblesStayShortTests(unittest.TestCase):
    """The bubbles are CHAT, not briefings (founder 2026-08-15).

    The delivered messages had grown to four dense sentences apiece — the
    founder read them back and asked for them shortened. Two things had to
    move together and both are pinned here, because fixing only one does
    nothing: the `intent` is the SOURCE the renderer voices, and the length
    RULE is what caps what the model expands it into. A short intent under a
    "2-4 sentences" rule just gets padded back out."""

    # Generous on purpose — this is a creep guard, not a style straitjacket.
    _MAX_INTENT_WORDS = 55

    def test_every_intent_is_short_enough_to_read_in_one_glance(self):
        for n, beat in sc.BEATS.items():
            words = len(beat["intent"].split())
            self.assertLessEqual(
                words, self._MAX_INTENT_WORDS,
                f"beat {n} intent is {words} words — a chat bubble is read in "
                "one glance; cut what is not the next action",
            )

    @staticmethod
    def _rule_source() -> str:
        """`_render_beat` minus its comments — the strings actually SENT.

        Comments are stripped because the change note above the rule quotes
        the old "2-4 sentences" wording to explain what was wrong with it, and
        a naive substring check flagged that history as the defect. What must
        not carry the old cap is the PROMPT, not the paper trail."""
        import inspect
        return "\n".join(
            line for line in inspect.getsource(sc._render_beat).splitlines()
            if not line.lstrip().startswith("#")
        )

    def test_the_render_rule_asks_for_TWO_sentences(self):
        # The lever that actually caps the OUTPUT. It read "2-4 sentences"
        # and reliably produced four.
        src = self._rule_source()
        self.assertIn("TWO sentences", src)
        for old in ("2–4 sentences", "2-4 sentences"):
            self.assertNotIn(old, src)

    def test_the_safety_caveat_is_EXEMPT_from_the_brevity_rule(self):
        # The wellbeing fence outranks brevity in every language (§7). A
        # length rule that could trim it would be the one shortening that
        # actually costs something.
        src = self._rule_source()
        self.assertIn("exempt", src.lower())
        self.assertIn("never trim that", src)

    def test_shortening_did_not_drop_the_doctrine(self):
        # What the words are allowed to lose is scaffolding, never a fact the
        # protocol carries. Beat 0 still states the varied setup and the
        # day-spacing nudge; the spark beat still carries its caveat.
        intent0 = sc.BEATS[0]["intent"].lower()
        self.assertIn("setup", intent0)
        self.assertIn("day", intent0)
        self.assertIn("baseline", intent0)
        self.assertTrue(sc.BEATS[3]["safety_caveat"])
        for phrase in ("optional", "not medical"):
            self.assertIn(phrase, sc.BEATS[3]["safety_caveat"].lower())


if __name__ == "__main__":
    unittest.main()
