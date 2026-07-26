"""Congruence delivery star (founder 2026-07-24 sign-off).

Pure tests of services/delivery_alignment.py — no app / DB / model import
(the DB + model call are injected), so they run in CI. They lock the fences:
  * the low-arousal GATE (arousal_z ≤ threshold; high/neutral excluded — so the
    valence-confusable high-arousal case is never flagged),
  * the positive-content gate (upbeat words only),
  * device 'congruence' persisted as a delivery star (kind='delivery'), and a
    member of the closed DELIVERY_DEVICES set so the serve layer can render it,
  * one per take, best-effort, flag-gated default off.

Run: python3 -m unittest test_delivery_alignment
"""
from __future__ import annotations

import os
import unittest

from services import delivery_alignment as da

# The baseline arousal_z is z-scored against: {feature: (mean, sd)}.
BASE = {"wpm": (140.0, 20.0), "dynamic_db": (12.0, 4.0),
        "f0_sd": (30.0, 10.0), "pause_ratio": (0.2, 0.1)}


def _flat():     # below-norm arousal cues (slow/soft/flat/paused) → low arousal_z
    return {"wpm": 100.0, "dynamic_db": 6.0, "f0_sd": 15.0, "pause_ratio": 0.4}


def _deep():     # even flatter → lower arousal_z (sorts first)
    return {"wpm": 80.0, "dynamic_db": 3.0, "f0_sd": 8.0, "pause_ratio": 0.6}


def _hot():      # above-norm (fast/loud/mobile/un-paused) → high arousal_z
    return {"wpm": 180.0, "dynamic_db": 18.0, "f0_sd": 45.0, "pause_ratio": 0.1}


def _neutral():  # at the norm → arousal_z ≈ 0
    return {"wpm": 140.0, "dynamic_db": 12.0, "f0_sd": 30.0, "pause_ratio": 0.2}


class FakeDB:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def upsert_moment_suggestion(self, snip_id, arc_id, kind, replacement, why, device):
        self.calls.append((snip_id, arc_id, kind, replacement, why, device))
        return self.ok


class CongruenceCandidateTests(unittest.TestCase):
    def _ids(self, unstarred, baseline=BASE):
        return [sid for _az, sid, _t in da.congruence_candidates(unstarred, baseline)]

    def test_only_low_arousal_qualifies(self):
        unstarred = [
            ("hot", "great news", _hot()),        # high arousal → excluded
            ("flat", "i am thrilled", _flat()),   # low arousal  → candidate
            ("neutral", "ok then", _neutral()),   # at norm      → excluded
        ]
        self.assertEqual(self._ids(unstarred), ["flat"])

    def test_ordered_flattest_first(self):
        unstarred = [("mild", "yay", _flat()), ("deep", "yay", _deep())]
        self.assertEqual(self._ids(unstarred), ["deep", "mild"])

    def test_high_arousal_never_a_candidate(self):
        # the masked-tension / genuine-excitement case is out of scope by
        # construction — a high arousal read can never become a congruence star.
        self.assertEqual(self._ids([("a", "hi", _hot()), ("b", "hi", _hot())]), [])

    def test_excludes_empty_transcript_and_missing_baseline(self):
        self.assertEqual(self._ids([("flat", "   ", _flat())]), [])
        self.assertEqual(da.congruence_candidates([("flat", "hi", _flat())], None), [])
        self.assertEqual(da.congruence_candidates([], BASE), [])

    def test_malformed_items_never_raise(self):
        self.assertEqual(self._ids([("bad",), None, ("flat", "hi", _flat())]), ["flat"])


class SentimentTests(unittest.TestCase):
    def test_words_positive_is_strict(self):
        self.assertTrue(da.words_positive({"words_positive": True}))
        self.assertFalse(da.words_positive({"words_positive": False}))
        self.assertFalse(da.words_positive({}))
        self.assertFalse(da.words_positive(None))
        self.assertFalse(da.words_positive("nope"))

    def test_messages_carry_transcript(self):
        system, user = da.build_sentiment_messages("best day ever")
        self.assertIn("best day ever", user)
        self.assertIn("words_positive", system)


class GenerateCongruenceTests(unittest.TestCase):
    def test_stars_flattest_positive_moment_once(self):
        db = FakeDB()
        calls = []

        def chat(s, u):
            calls.append(u)
            return {"words_positive": True}

        unstarred = [("mild", "great", _flat()), ("deep", "i love this", _deep())]
        out = da.generate_congruence_stars(db, "arc1", unstarred, BASE, chat_fn=chat)
        self.assertEqual(out, ["deep"])            # flattest wins
        self.assertEqual(len(calls), 1)            # one per take → stop at first
        self.assertEqual(
            db.calls[0], ("deep", "arc1", "delivery", None, None, "congruence"))

    def test_walks_past_negative_words(self):
        db = FakeDB()
        seq = [{"words_positive": False}, {"words_positive": True}]
        unstarred = [("deep", "the deal collapsed", _deep()),
                     ("mild", "i love this", _flat())]
        out = da.generate_congruence_stars(
            db, "arc1", unstarred, BASE, chat_fn=lambda s, u: seq.pop(0))
        self.assertEqual(out, ["mild"])
        self.assertEqual(db.calls[-1][5], "congruence")

    def test_caps_model_calls(self):
        db = FakeDB()
        calls = []

        def chat(s, u):
            calls.append(u)
            return {"words_positive": False}

        unstarred = [(f"p{i}", "yay",
                      {"wpm": 80.0 - i, "dynamic_db": 3.0, "f0_sd": 8.0,
                       "pause_ratio": 0.6}) for i in range(5)]
        out = da.generate_congruence_stars(db, "arc1", unstarred, BASE, chat_fn=chat)
        self.assertEqual(out, [])
        self.assertLessEqual(len(calls), da._MAX_LLM_ATTEMPTS)
        self.assertEqual(db.calls, [])

    def test_no_low_arousal_never_calls_model(self):
        db = FakeDB()
        calls = []

        def chat(s, u):
            calls.append(u)
            return {"words_positive": True}

        out = da.generate_congruence_stars(
            db, "arc1", [("hot", "great", _hot())], BASE, chat_fn=chat)
        self.assertEqual(out, [])
        self.assertEqual(calls, [])

    def test_best_effort_on_db_and_model_failure(self):
        unstarred = [("flat", "wonderful", _flat())]
        # write failed → nothing starred
        self.assertEqual(da.generate_congruence_stars(
            FakeDB(ok=False), "arc1", unstarred, BASE,
            chat_fn=lambda s, u: {"words_positive": True}), [])

        def boom(s, u):
            raise RuntimeError("x")

        # model raised → caught, nothing starred
        self.assertEqual(da.generate_congruence_stars(
            FakeDB(), "arc1", unstarred, BASE, chat_fn=boom), [])

    def test_guards_missing_arc_unstarred_or_baseline(self):
        f = [("f", "hi", _flat())]
        self.assertEqual(da.generate_congruence_stars(FakeDB(), None, f, BASE), [])
        self.assertEqual(da.generate_congruence_stars(FakeDB(), "arc1", [], BASE), [])
        self.assertEqual(da.generate_congruence_stars(FakeDB(), "arc1", f, None), [])


class FlagAndDeviceTests(unittest.TestCase):
    def test_flag_default_off_and_toggle(self):
        old = os.environ.pop("DELIVERY_ALIGNMENT_ENABLED", None)
        try:
            self.assertFalse(da.delivery_alignment_enabled())
            os.environ["DELIVERY_ALIGNMENT_ENABLED"] = "1"
            self.assertTrue(da.delivery_alignment_enabled())
            os.environ["DELIVERY_ALIGNMENT_ENABLED"] = "false"
            self.assertFalse(da.delivery_alignment_enabled())
        finally:
            os.environ.pop("DELIVERY_ALIGNMENT_ENABLED", None)
            if old is not None:
                os.environ["DELIVERY_ALIGNMENT_ENABLED"] = old

    def test_congruence_is_a_known_delivery_device(self):
        # the serve layer renders a delivery star ONLY when its device is in
        # this closed set — congruence must be a member or the star never shows.
        from services.delivery_stars import DELIVERY_DEVICES
        self.assertIn("congruence", DELIVERY_DEVICES)


if __name__ == "__main__":
    unittest.main()
