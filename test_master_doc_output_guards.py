"""Deterministic output guards for the Lounge bot (RULE A + RULE K).

These test the POST-GENERATION floor in services/master_doc_rag.py —
the code that enforces the construct-prohibition (B1/AC-9) and the
library-dump prohibition (RULE K) on the model's OUTPUT, independent of
whether the prompt rule held. Pure functions, NO LLM, NO network — this
is the part of the probe's guarantee that can run keyless in CI.

master_doc_rag imports services.will_voice (pure) + services.db lazily,
so a db stub keeps it import-safe in the lean env (same pattern as
test_library_bot_context — stub in setUpModule, RESTORE in tearDown).

Run: python3 -m unittest test_master_doc_output_guards
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock

_ORIG_SERVICES_DB = None
_ORIG_SUPABASE = None


def setUpModule():
    global _ORIG_SERVICES_DB, _ORIG_SUPABASE
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    _ORIG_SUPABASE = sys.modules.get("supabase")
    sys.modules["supabase"] = MagicMock()
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)
    if _ORIG_SUPABASE is not None:
        sys.modules["supabase"] = _ORIG_SUPABASE
    else:
        sys.modules.pop("supabase", None)


class ConstructLeakGuardTests(unittest.TestCase):
    """RULE A / B1 / AC-9 — the retired scoring construct must never
    survive in the output, even if the prompt rule were crowded out."""

    def _guard(self, answer, suggested_action=None, library=None):
        from services.master_doc_rag import _enforce_output_guards
        return _enforce_output_guards(answer, suggested_action, library)

    def test_threat_challenge_ratio_is_replaced(self):
        a, _sa, fired = self._guard(
            "Your Threat:Challenge ratio came out strong this session."
        )
        self.assertEqual(fired, "construct_leak")
        self.assertNotIn("threat", a.lower())
        self.assertIn("Readout", a)

    def test_tc_shorthand_is_replaced(self):
        _a, _sa, fired = self._guard("Your T:C is trending up.")
        self.assertEqual(fired, "construct_leak")

    def test_kpi_is_replaced(self):
        _a, _sa, fired = self._guard("Your KPI for this take is 0.72.")
        self.assertEqual(fired, "construct_leak")

    def test_charisma_score_is_replaced(self):
        _a, _sa, fired = self._guard("Your charisma score went up.")
        self.assertEqual(fired, "construct_leak")

    def test_stress_classifier_is_replaced(self):
        _a, _sa, fired = self._guard(
            "The stress classifier flagged the opening."
        )
        self.assertEqual(fired, "construct_leak")

    # ── False-positive guards: benign prose must pass UNTOUCHED ──

    def test_bare_challenge_is_not_matched(self):
        msg = "Speaking to a big room is a real challenge for most people."
        a, _sa, fired = self._guard(msg)
        self.assertIsNone(fired)
        self.assertEqual(a, msg)

    def test_bare_score_word_is_not_matched(self):
        msg = "Scores of speakers freeze up — you're not alone."
        a, _sa, fired = self._guard(msg)
        self.assertIsNone(fired)
        self.assertEqual(a, msg)

    def test_word_containing_tc_substring_is_not_matched(self):
        # "catch", "watch" etc. contain no standalone t:c token.
        msg = "Catch your breath, watch your pace, and keep going."
        _a, _sa, fired = self._guard(msg)
        self.assertIsNone(fired)

    def test_normal_product_answer_passes_through(self):
        msg = (
            "The system is mostly human-led and scaled by AI — a real "
            "coach listens to your recordings and shapes what's next."
        )
        a, sa, fired = self._guard(msg, suggested_action=None)
        self.assertIsNone(fired)
        self.assertEqual(a, msg)
        self.assertIsNone(sa)


class LibraryDumpGuardTests(unittest.TestCase):
    """RULE K — the bot must bridge to the button, never recite the
    coach-notes library inline."""

    def _guard(self, answer, suggested_action=None, library=None):
        from services.master_doc_rag import _enforce_output_guards
        return _enforce_output_guards(answer, suggested_action, library)

    def test_marker_strong_triggers_bridge(self):
        a, sa, fired = self._guard(
            'Here they are: [strong] coach noted: "great open".'
        )
        self.assertEqual(fired, "library_dump")
        self.assertEqual(sa, "strong_sides")
        self.assertEqual(a, "Sure — tap the button below to open them.")

    def test_marker_coach_noted_triggers_bridge(self):
        _a, _sa, fired = self._guard('coach noted: "watch the drop-off"')
        self.assertEqual(fired, "library_dump")

    def test_verbatim_note_overlap_triggers_bridge(self):
        library = [{
            "tag": "strong",
            "note": "Strongest eight seconds — do more of this.",
            "snippet_ref": {},
        }]
        a, sa, fired = self._guard(
            "You did well! Strongest eight seconds — do more of this.",
            library=library,
        )
        self.assertEqual(fired, "library_dump")
        self.assertEqual(sa, "strong_sides")
        self.assertEqual(a, "Sure — tap the button below to open them.")

    def test_short_note_overlap_does_not_false_positive(self):
        # A sub-threshold note fragment shared incidentally must NOT trip.
        library = [{"tag": "strong", "note": "nice", "snippet_ref": {}}]
        msg = "That's a nice question — here's what the product does."
        a, _sa, fired = self._guard(msg, library=library)
        self.assertIsNone(fired)
        self.assertEqual(a, msg)

    def test_bridge_answer_with_library_present_passes_through(self):
        # The compliant bridge answer must NOT be flagged as a dump even
        # when the library is loaded for this turn.
        library = [{
            "tag": "strong",
            "note": "Strongest eight seconds — do more of this.",
            "snippet_ref": {},
        }]
        msg = "Sure — tap the button below to open them."
        a, sa, fired = self._guard(
            msg, suggested_action="strong_sides", library=library,
        )
        self.assertIsNone(fired)
        self.assertEqual(a, msg)
        self.assertEqual(sa, "strong_sides")

    def test_no_library_benign_answer_passes(self):
        msg = "I can't see any coach notes for you yet — record a take?"
        a, _sa, fired = self._guard(msg, library=None)
        self.assertIsNone(fired)
        self.assertEqual(a, msg)


class GuardPrecedenceTests(unittest.TestCase):
    def _guard(self, answer, suggested_action=None, library=None):
        from services.master_doc_rag import _enforce_output_guards
        return _enforce_output_guards(answer, suggested_action, library)

    def test_construct_leak_takes_precedence_over_dump(self):
        # An answer that both leaks the construct AND dumps the library
        # is replaced by the construct-safe answer (the stronger guard).
        library = [{"tag": "strong", "note": "x" * 30, "snippet_ref": {}}]
        a, _sa, fired = self._guard(
            'coach noted: "your KPI is 0.9"', library=library,
        )
        self.assertEqual(fired, "construct_leak")
        self.assertIn("Readout", a)


class SplitAnswerIntoBubblesTests(unittest.TestCase):
    """P3-1 — server-side chat-bubble splitting for FE #157's bubbles[]."""

    def _split(self, answer):
        from services.master_doc_rag import split_answer_into_bubbles
        return split_answer_into_bubbles(answer)

    def test_empty_returns_empty_list(self):
        self.assertEqual(self._split(""), [])
        self.assertEqual(self._split(None), [])
        self.assertEqual(self._split("   "), [])

    def test_short_one_liner_is_single_bubble(self):
        msg = "Sure — tap the button below to open them."
        self.assertEqual(self._split(msg), [msg])

    def test_blank_lines_are_hard_boundaries(self):
        out = self._split("First paragraph.\n\nSecond paragraph.")
        self.assertEqual(out, ["First paragraph.", "Second paragraph."])

    def test_long_paragraph_splits_on_sentences(self):
        from services.master_doc_rag import _BUBBLE_SOFT_MAX
        # Four sentences, comfortably over the 200-char soft cap as one run.
        s1 = "This is the first sentence and it is fairly wordy on purpose."
        s2 = "Here is a second sentence that also carries a good deal of text."
        s3 = "And a third one to push the paragraph well over the soft cap."
        s4 = "A fourth sentence guarantees we cross the limit and must split."
        para = f"{s1} {s2} {s3} {s4}"
        self.assertGreater(len(para), _BUBBLE_SOFT_MAX)  # precondition
        out = self._split(para)
        self.assertGreater(len(out), 1)
        self.assertTrue(all(len(b) <= _BUBBLE_SOFT_MAX for b in out), out)

    def test_words_are_preserved(self):
        from services.master_doc_rag import split_answer_into_bubbles
        text = ("Alpha beta gamma. " * 30).strip()
        joined = " ".join(split_answer_into_bubbles(text))
        self.assertEqual(joined.split(), text.split())

    def test_never_splits_below_word(self):
        # No bubble is empty or whitespace-only.
        out = self._split("One. Two. Three.\n\n" + ("Long sentence here. " * 20))
        self.assertTrue(all(b.strip() for b in out))


class RouterScaffoldTests(unittest.TestCase):
    """Part B — deterministic checks on the two-stage router scaffold
    (flag, lane prompts, classifier schema). No LLM."""

    def test_flag_off_by_default(self):
        import os
        from services.master_doc_rag import _router_enabled
        old = os.environ.pop("LOUNGE_ROUTER_ENABLED", None)
        try:
            self.assertFalse(_router_enabled())
        finally:
            if old is not None:
                os.environ["LOUNGE_ROUTER_ENABLED"] = old

    def test_flag_reads_env(self):
        import os
        from services.master_doc_rag import _router_enabled
        old = os.environ.get("LOUNGE_ROUTER_ENABLED")
        try:
            for v in ("1", "true", "YES", "on"):
                os.environ["LOUNGE_ROUTER_ENABLED"] = v
                self.assertTrue(_router_enabled(), v)
            os.environ["LOUNGE_ROUTER_ENABLED"] = "0"
            self.assertFalse(_router_enabled())
        finally:
            if old is None:
                os.environ.pop("LOUNGE_ROUTER_ENABLED", None)
            else:
                os.environ["LOUNGE_ROUTER_ENABLED"] = old

    def test_every_intent_has_a_lane_body(self):
        from services.master_doc_rag import _INTENTS, _LANE_BODIES
        for intent in _INTENTS:
            self.assertIn(intent, _LANE_BODIES, intent)

    def test_classifier_schema_enum_matches_intents(self):
        from services.master_doc_rag import _INTENTS, _CLASSIFIER_SCHEMA
        enum = _CLASSIFIER_SCHEMA["schema"]["properties"]["intent"]["enum"]
        self.assertEqual(set(enum), set(_INTENTS))

    def test_grounded_lane_splices_master_doc(self):
        from services.master_doc_rag import _build_lane_prompt
        grounded = _build_lane_prompt("product_faq", None, "")
        self.assertIn("MASTER DOCUMENT", grounded)
        # an action lane stays focused — no full document
        action = _build_lane_prompt("record_intent", None, "")
        self.assertNotIn("MASTER DOCUMENT", action)

    def test_library_recall_lane_includes_library(self):
        from services.master_doc_rag import _build_lane_prompt
        out = _build_lane_prompt(
            "library_recall",
            [{"tag": "strong", "note": "great open", "snippet_ref": {}}],
            "",
        )
        # the librarian guardrail rides along with the library block
        self.assertIn("LIBRARIAN", out)

    def test_record_lane_body_sets_record_again(self):
        from services.master_doc_rag import _LANE_BODIES
        self.assertIn("record_again", _LANE_BODIES["record_intent"])
        self.assertIn("show_record_ui", _LANE_BODIES["record_intent"])


if __name__ == "__main__":
    unittest.main()
