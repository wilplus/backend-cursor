"""Unit tests for services/say_it_stronger ("Say It Stronger", founder
2026-07-07) — the pure pieces: session-mean aggregation, qualitative
self-comparison (never a number, never a population claim), the AC-9
output guard, payload cleaning, and the fire-and-forget dispatch safety.

Run: python3 -m unittest test_say_it_stronger
"""
from __future__ import annotations

import sys
import threading
import types
import unittest
from unittest.mock import MagicMock, call, patch

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
        # v2 (2026-07-14): upgrades carry scope word|phrase.
        from services.say_it_stronger import _SUGGESTION_VERSION
        self.assertEqual(out["version"], _SUGGESTION_VERSION)

    def test_scope_normalized_word_vs_phrase(self):
        # Model omitted/mangled scope → deterministic fallback from the
        # original text: a space = phrase, single token = word.
        out = self._c(self._valid(upgrades=[
            {"original": "sort of like", "upgrade": "sort of",
             "reason": "r", "scope": "banana"},
            {"original": "good", "upgrade": "compelling", "reason": "r"},
            {"original": "nice", "upgrade": "sharp", "reason": "r",
             "scope": "phrase"},   # model's explicit scope respected
        ]))
        ups = out["upgrades"]
        self.assertEqual(len(ups), 3)
        self.assertEqual(ups[0]["scope"], "phrase")   # fallback: has space
        self.assertEqual(ups[1]["scope"], "word")     # fallback: one token
        self.assertEqual(ups[2]["scope"], "phrase")   # explicit kept

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

    def test_kind_carried_and_defaulted(self):
        out = self._c(self._valid(upgrades=[
            {"original": "like", "upgrade": "for example",
             "reason": "ok", "kind": "filler"},
            {"original": "great", "upgrade": "compelling",
             "reason": "ok", "kind": "overuse"},
            {"original": "a", "upgrade": "b", "reason": "ok"},  # no kind
        ]))
        kinds = [u["kind"] for u in out["upgrades"]]
        self.assertEqual(kinds, ["filler", "overuse", "upgrade"])
        # unknown kind defaults, never round-trips garbage
        out2 = self._c(self._valid(upgrades=[
            {"original": "x", "upgrade": "y", "reason": "ok",
             "kind": "banana"}]))
        self.assertEqual(out2["upgrades"][0]["kind"], "upgrade")

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

    def test_context_reaches_the_prompt(self):
        # Founder 2026-07-11: audience + talk length + the FULL take
        # transcript ride the call so the MODEL judges filler/overuse itself.
        from services import say_it_stronger as mod
        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return None

        with patch("services.llm.chat_complete", side_effect=_capture):
            mod.generate_say_it_stronger(
                "we ship it", {}, {},
                context={"topic": "Q3 pitch", "audience": "investors",
                         "strategic_context": "the board decides the raise",
                         "target_length_seconds": 300, "duration_sec": 420,
                         "full_transcript": "we ship it like basically like"},
            )
        user_msg = captured.get("user") or ""
        self.assertIn("investors", user_msg)
        self.assertIn("Q3 pitch", user_msg)
        self.assertIn("the board decides the raise", user_msg)  # ④ step 5
        self.assertIn("about 5 min", user_msg)      # target
        self.assertIn("about 7 min", user_msg)      # actual
        self.assertIn("we ship it like basically like", user_msg)

    def test_long_full_transcript_capped(self):
        from services import say_it_stronger as mod
        captured = {}

        def _capture(**kwargs):
            captured.update(kwargs)
            return None

        with patch("services.llm.chat_complete", side_effect=_capture):
            mod.generate_say_it_stronger(
                "hi", {}, {},
                context={"full_transcript": "word " * 3000},  # 15k chars
            )
        user_msg = captured.get("user") or ""
        self.assertLess(len(user_msg), 8000)

    def test_no_context_still_works(self):
        from services import say_it_stronger as mod
        with patch("services.llm.chat_complete", return_value=None):
            self.assertIsNone(mod.generate_say_it_stronger("we ship", {}, {}))

    def test_system_prompt_teaches_filler_and_overuse(self):
        from services.say_it_stronger import _SYSTEM_PROMPT
        self.assertIn("FILLER", _SYSTEM_PROMPT)
        self.assertIn("OVERUSE", _SYSTEM_PROMPT.upper())
        self.assertIn("kind='filler'", _SYSTEM_PROMPT)
        self.assertIn("kind='overuse'", _SYSTEM_PROMPT)

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

        def _generate(transcript, *_args, **_kwargs):
            if transcript == "a":
                return payload
            raise RuntimeError("llm down")

        with patch.object(mod, "generate_say_it_stronger",
                          side_effect=_generate):
            mod._generate_all(
                "s1",
                [_snip("a", transcript="a"), _snip("b", transcript="b")],
            )
        db.set_charisma_snippet_say_it_stronger.assert_called_once_with(
            "a", payload)

    def test_generate_all_overlaps_independent_calls_and_writes_in_order(self):
        from services import say_it_stronger as mod
        from services.db import db

        rendezvous = threading.Barrier(2)

        def _generate(transcript, *_args, **_kwargs):
            # This barrier can pass only when both model calls overlap. The
            # former sequential loop would time out here.
            rendezvous.wait(timeout=2)
            return {"transcript": transcript}

        writer = MagicMock(return_value=True)
        with patch.object(mod, "generate_say_it_stronger",
                          side_effect=_generate), \
                patch.object(db, "set_charisma_snippet_say_it_stronger",
                             writer):
            mod._generate_all(
                "s1",
                [_snip("a", transcript="a"), _snip("b", transcript="b")],
            )

        self.assertEqual(
            writer.call_args_list,
            [
                call("a", {"transcript": "a"}),
                call("b", {"transcript": "b"}),
            ],
        )


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


try:
    from flask import Flask, request as _flask_request
    from routes import v2_routes as _v2
    _ROUTE_IMPORT_ERROR = None
except Exception as _e:  # pragma: no cover
    Flask = None
    _flask_request = None
    _v2 = None
    _ROUTE_IMPORT_ERROR = _e


@unittest.skipIf(_ROUTE_IMPORT_ERROR is not None,
                 f"needs app deps: {_ROUTE_IMPORT_ERROR}")
class CoachSayItStrongerRouteTests(unittest.TestCase):
    """PUT /v2/coach/snippets/<id>/say-it-stronger — coach-corrected card."""

    _SNIP = "22222222-2222-4222-8222-222222222222"

    def setUp(self):
        self.app = Flask(__name__)
        self._snippet_row = {"id": self._SNIP, "session_id": "s1",
                             "transcript": "we ship it"}
        self._saved = {}

        def _set_final(sid, payload):
            self._saved[sid] = payload
            return True

        self._p = [
            patch.object(_v2.db, "get_snippet_by_id",
                         lambda sid: self._snippet_row),
            patch.object(_v2.db, "set_charisma_snippet_say_it_stronger_final",
                         _set_final),
        ]
        for p_ in self._p:
            p_.start()

    def tearDown(self):
        for p_ in self._p:
            p_.stop()

    def _card(self, **over):
        base = {"already_strong": False,
                "upgrades": [{"original": "like", "upgrade": "for example",
                              "reason": "One hedge is enough.",
                              "kind": "filler"}],
                "rewrite_your_voice": "We ship it.",
                "rewrite_polished": "We will ship it.",
                "why": "Direct beats hedged."}
        base.update(over)
        return base

    def _call(self, body, snippet_id=None):
        with self.app.test_request_context(json=body):
            _flask_request.user_id = "coach1"
            resp, status = _v2.v2_coach_put_say_it_stronger.__wrapped__(
                snippet_id or self._SNIP)
            return resp.get_json(), status

    def test_valid_card_saves_with_coach_mark(self):
        body, status = self._call(self._card())
        self.assertEqual(status, 200)
        saved = self._saved[self._SNIP]
        self.assertTrue(saved["edited_by_coach"])
        self.assertEqual(saved["upgrades"][0]["kind"], "filler")

    def test_numeric_why_guarded_even_from_coach(self):
        body, status = self._call(self._card(why="pause is 0.2s"))
        self.assertEqual(status, 200)
        self.assertIsNone(self._saved[self._SNIP]["why"])  # AC-9 holds

    def test_invalid_card_400s(self):
        _, status = self._call({"nonsense": True})
        self.assertEqual(status, 400)
        self.assertEqual(self._saved, {})

    def test_unknown_snippet_404s(self):
        self._snippet_row = None
        _, status = self._call(self._card())
        self.assertEqual(status, 404)

    def test_bad_uuid_400s(self):
        _, status = self._call(self._card(), snippet_id="nope")
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
