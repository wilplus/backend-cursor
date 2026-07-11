"""Unit tests for services/say_it_stronger ("Say It Stronger", founder
2026-07-07) — the pure pieces: session-mean aggregation, qualitative
self-comparison (never a number, never a population claim), the AC-9
output guard, payload cleaning, and the fire-and-forget dispatch safety.

Run: python3 -m unittest test_say_it_stronger
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# services.db pulls in supabase — stub in setUpModule, restore after
# (willab test-stub-isolation convention).
_ORIG_SERVICES_DB = None


def setUpModule():
    global _ORIG_SERVICES_DB
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)


def _snip(sid, wpm=None, pause_ratio=None, f0_sd=None, dynamic_db=None,
          transcript="we should ship it"):
    m = {}
    if wpm is not None:
        m["wpm"] = wpm
    if pause_ratio is not None:
        m["pause_ratio"] = pause_ratio
    if f0_sd is not None:
        m["f0_sd"] = f0_sd
    if dynamic_db is not None:
        m["dynamic_db"] = dynamic_db
    return {"id": sid, "transcript": transcript, "metrics": m}


class AggregateSessionMeansTests(unittest.TestCase):

    def _f(self, snips):
        from services.say_it_stronger import aggregate_session_means
        return aggregate_session_means(snips)

    def test_means_across_snippets(self):
        out = self._f([_snip("a", wpm=100), _snip("b", wpm=140)])
        self.assertEqual(out["pace"], 120.0)

    def test_alias_speech_rate_counts_as_pace(self):
        out = self._f([{"id": "a", "metrics": {"speech_rate": 130}}])
        self.assertEqual(out["pace"], 130.0)

    def test_missing_metrics_skipped(self):
        out = self._f([_snip("a"), _snip("b", pause_ratio=0.2)])
        self.assertNotIn("pace", out)
        self.assertEqual(out["pausing"], 0.2)

    def test_empty_safe(self):
        self.assertEqual(self._f([]), {})
        self.assertEqual(self._f(None), {})


class QualitativeSelfComparisonTests(unittest.TestCase):

    def _f(self, metrics, means):
        from services.say_it_stronger import qualitative_self_comparison
        return qualitative_self_comparison(metrics, means)

    def test_shorter_pauses_than_own_average(self):
        out = self._f({"pause_ratio": 0.10}, {"pausing": 0.20})
        self.assertEqual(out["pausing"], "shorter pauses than your average")

    def test_faster_pace(self):
        out = self._f({"wpm": 160}, {"pace": 120})
        self.assertEqual(out["pace"], "faster than your average")

    def test_within_tolerance_reads_about_average(self):
        out = self._f({"wpm": 122}, {"pace": 120})
        self.assertEqual(out["pace"], "about your average")

    def test_never_contains_a_digit(self):
        out = self._f(
            {"wpm": 160, "pause_ratio": 0.1, "f0_sd": 40, "dynamic_db": 12},
            {"pace": 120, "pausing": 0.2, "pitch_variety": 25, "energy": 8},
        )
        for v in out.values():
            self.assertNotRegex(v, r"\d")

    def test_empty_safe(self):
        self.assertEqual(self._f({}, {}), {})
        self.assertEqual(self._f(None, None), {})
        # zero mean must not divide-by-zero
        self.assertEqual(self._f({"wpm": 100}, {"pace": 0}), {})


class GuardCopyTests(unittest.TestCase):
    """AC-9: user-facing coaching copy — no digits, no construct family."""

    def _g(self, text):
        from services.say_it_stronger import _guard_copy
        return _guard_copy(text)

    def test_clean_copy_passes(self):
        self.assertEqual(
            self._g("Hedging softens your point before it lands."),
            "Hedging softens your point before it lands.",
        )

    def test_digits_rejected(self):
        self.assertIsNone(self._g("Your pause was 0.2s — use silence."))

    def test_construct_vocabulary_rejected(self):
        for bad in ("your threat:challenge read improved",
                    "a higher charisma score here",
                    "the stress classifier flagged this",
                    "watch the KPI"):
            self.assertIsNone(self._g(bad))

    def test_blank_and_non_string_rejected(self):
        self.assertIsNone(self._g("   "))
        self.assertIsNone(self._g(None))
        self.assertIsNone(self._g(42))


class CleanPayloadTests(unittest.TestCase):

    def _c(self, parsed, transcript="sort of like a good point"):
        from services.say_it_stronger import _clean_payload
        return _clean_payload(parsed, transcript)

    def _valid(self, **over):
        base = {
            "already_strong": False,
            "upgrades": [{"original": "sort of like", "upgrade": "sort of",
                          "reason": "One hedge is enough."}],
            "rewrite_your_voice": "Sort of a good point.",
            "rewrite_polished": "That is a good point.",
            "why": "Stacked hedges read as doubt.",
        }
        base.update(over)
        return base

    def test_valid_payload_round_trips(self):
        out = self._c(self._valid())
        self.assertFalse(out["already_strong"])
        self.assertEqual(out["rewrite_your_voice"], "Sort of a good point.")
        self.assertEqual(out["upgrades"][0]["upgrade"], "sort of")
        self.assertEqual(out["why"], "Stacked hedges read as doubt.")
        self.assertEqual(out["version"], 1)

    def test_already_strong_forces_original_and_no_upgrades(self):
        out = self._c(self._valid(
            already_strong=True,
            rewrite_your_voice="something else",
            rewrite_polished="something else",
        ), transcript="We ship on Friday.")
        self.assertTrue(out["already_strong"])
        self.assertEqual(out["rewrite_your_voice"], "We ship on Friday.")
        self.assertEqual(out["rewrite_polished"], "We ship on Friday.")
        self.assertEqual(out["upgrades"], [])

    def test_numeric_why_nulled_but_rewrites_kept(self):
        out = self._c(self._valid(why="Your pause is 0.2s shorter."))
        self.assertIsNone(out["why"])
        self.assertEqual(out["rewrite_polished"], "That is a good point.")

    def test_numeric_reason_dropped_pair_kept(self):
        out = self._c(self._valid(upgrades=[{
            "original": "like", "upgrade": "", "reason": "x",
        }, {
            "original": "sort of like", "upgrade": "sort of",
            "reason": "2x hedging",
        }]))
        self.assertEqual(len(out["upgrades"]), 1)  # blank-upgrade entry dropped
        self.assertIsNone(out["upgrades"][0]["reason"])
        self.assertEqual(out["upgrades"][0]["upgrade"], "sort of")

    def test_upgrades_capped_at_three(self):
        ups = [{"original": f"o{i}", "upgrade": f"u{i}", "reason": "ok"}
               for i in range(5)]
        out = self._c(self._valid(upgrades=ups))
        self.assertEqual(len(out["upgrades"]), 3)

    def test_missing_rewrites_unusable(self):
        self.assertIsNone(self._c(self._valid(rewrite_your_voice="")))
        self.assertIsNone(self._c(self._valid(rewrite_polished="   ")))
        self.assertIsNone(self._c("not a dict"))
        self.assertIsNone(self._c(None))


class GenerateTests(unittest.TestCase):
    """generate_say_it_stronger — LLM plumbed via services.llm.chat_complete."""

    def test_empty_transcript_returns_none_without_llm(self):
        from services.say_it_stronger import generate_say_it_stronger
        self.assertIsNone(generate_say_it_stronger("", {}, {}))
        self.assertIsNone(generate_say_it_stronger("   ", {}, {}))

    def test_llm_failure_returns_none(self):
        from services import say_it_stronger as mod
        with patch("services.llm.chat_complete", return_value=None):
            self.assertIsNone(
                mod.generate_say_it_stronger("we ship it", {}, {}))

    def test_success_stamps_model_and_generated_at(self):
        from services import say_it_stronger as mod
        parsed = {
            "already_strong": False, "upgrades": [],
            "rewrite_your_voice": "We ship it.",
            "rewrite_polished": "We will ship it.",
            "why": "Direct beats hedged.",
        }
        fake = MagicMock()
        fake.parsed = parsed
        fake.text = "{}"
        with patch("services.llm.chat_complete", return_value=fake):
            out = mod.generate_say_it_stronger("we ship it", {}, {})
        self.assertEqual(out["rewrite_polished"], "We will ship it.")
        self.assertIn("model", out)
        self.assertIn("generated_at", out)

    def test_model_never_sees_raw_numbers(self):
        from services import say_it_stronger as mod
        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return None

        with patch("services.llm.chat_complete", side_effect=_capture):
            mod.generate_say_it_stronger(
                "we ship it", {"wpm": 160, "pause_ratio": 0.1},
                {"pace": 120, "pausing": 0.2},
            )
        user_msg = captured.get("user") or ""
        # The transcript may carry digits the SPEAKER said; the voice-read
        # context must not. Assert on the observations line specifically.
        obs_line = next((ln for ln in user_msg.split("\n")
                         if "their own average" in ln.lower()), "")
        self.assertTrue(obs_line)
        self.assertNotRegex(obs_line, r"\d")
        self.assertIn("faster than your average", obs_line)


class DispatchTests(unittest.TestCase):

    def test_no_snippets_is_noop(self):
        from services.say_it_stronger import dispatch_say_it_stronger
        with patch("threading.Thread") as t:
            dispatch_say_it_stronger("s1", [])
        t.assert_not_called()

    def test_dispatch_never_raises(self):
        from services.say_it_stronger import dispatch_say_it_stronger
        with patch("threading.Thread", side_effect=RuntimeError("boom")):
            dispatch_say_it_stronger("s1", [_snip("a")])  # must not raise

    def test_generate_all_persists_and_survives_failures(self):
        from services import say_it_stronger as mod
        from services.db import db
        payload = {"already_strong": True, "upgrades": [],
                   "rewrite_your_voice": "x", "rewrite_polished": "x",
                   "why": None, "version": 1}
        db.set_charisma_snippet_say_it_stronger = MagicMock(return_value=True)
        with patch.object(mod, "generate_say_it_stronger",
                          side_effect=[payload, RuntimeError("llm down")]):
            mod._generate_all("s1", [_snip("a"), _snip("b")])
        db.set_charisma_snippet_say_it_stronger.assert_called_once_with(
            "a", payload)


class L1FenceTests(unittest.TestCase):
    """L1 — the suggestions are a display overlay ONLY. Founder 2026-07-11
    carved out ONE sanctioned read: per-slide ideal-text key_phrases derive
    from the winning pick's upgrades (glance hints beside the text). The
    invariant is therefore BEHAVIORAL: say_it_stronger must never alter the
    composed/selected TEXT itself."""

    def test_compose_text_identical_with_and_without_suggestions(self):
        from services import best_presentation as bp
        sis = {"already_strong": False,
               "upgrades": [{"original": "weak", "upgrade": "strong",
                             "reason": None}],
               "rewrite_your_voice": "REWRITTEN A",
               "rewrite_polished": "REWRITTEN B",
               "why": None, "version": 1}
        base_pick = {"transcript": "the verbatim line",
                     "audio_ref": None, "start_offset_ms": 0,
                     "duration_ms": 1000, "take_index": 1,
                     "breakthrough": False, "note": None}
        slides = [{"title": "S1", "body": ""}]
        orig = bp._render_composition
        bp._render_composition = lambda p, s: None  # verbatim path
        try:
            without = bp.compose_presentation({0: dict(base_pick)}, slides)
            with_sis = bp.compose_presentation(
                {0: {**base_pick, "say_it_stronger": sis}}, slides)
        finally:
            bp._render_composition = orig
        self.assertEqual(without[0]["text"], "the verbatim line")
        self.assertEqual(with_sis[0]["text"], without[0]["text"])
        # the rewrites never leak into any text field
        for s in with_sis:
            self.assertNotIn("REWRITTEN", s["text"])

    def test_ideal_text_report_never_reads_the_raw_field(self):
        # The report consumes the derived key_phrases, never say_it_stronger
        # itself — the raw suggestion object stays off the paid deliverable.
        import pathlib
        src = pathlib.Path("services/ideal_text_report.py").read_text(
            encoding="utf-8")
        self.assertNotIn("say_it_stronger", src)

    def test_selection_never_reads_suggestions(self):
        # Ranking/selection (select_best_per_slide) must not consult the
        # suggestion object — grep its function body only.
        import inspect
        from services import best_presentation as bp
        body = inspect.getsource(bp.select_best_per_slide)
        self.assertNotIn("say_it_stronger", body)


if __name__ == "__main__":
    unittest.main()
