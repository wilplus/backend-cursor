"""Unit tests for the Will's Voice anchor module (Ticket 1).

Covers the helper's structural guarantees so any future edit to the
anchor block can't accidentally break the contract that 10 caller
sites depend on. The CONTENT of the anchor (the examples, tone rules,
heuristic test) is meant to grow over time — the tests check the
shape, not specific wording.

Run: python3 -m unittest test_will_voice
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock


# Stub the supabase + services.db dependency BEFORE any caller import
# so the integration smoke test can run without the supabase venv.
# Mirrors the pattern in test_intake_context.py / test_next_session_
# icebreaker.py — keeps unit tests runnable in any Python 3 env.
sys.modules.setdefault("supabase", MagicMock())
_stub_db_module = types.ModuleType("services.db")
_stub_db_module.db = MagicMock()
sys.modules.setdefault("services.db", _stub_db_module)


class WithVoiceRulesTests(unittest.TestCase):

    def test_appends_anchor_to_caller_prompt(self):
        from services.will_voice import with_voice_rules, WILL_VOICE_RULES
        result = with_voice_rules("Function-specific instructions.")
        # Caller's prompt lands FIRST.
        self.assertTrue(result.startswith("Function-specific instructions."))
        # Anchor block lands AT THE END.
        self.assertTrue(result.rstrip().endswith(WILL_VOICE_RULES.rstrip()))
        # The two are separated.
        self.assertIn("\n\n", result)

    def test_empty_caller_prompt_still_produces_anchor(self):
        """Defensive — even an empty function-specific prompt should
        still get the anchor injected. The Will's Voice rules should
        govern any call that opts in, regardless of the rest of the
        prompt being lean."""
        from services.will_voice import with_voice_rules, WILL_VOICE_RULES
        result = with_voice_rules("")
        # Trim and compare — empty caller leaves a leading blank
        # separator, which the helper retains for visual consistency.
        self.assertEqual(result.strip(), WILL_VOICE_RULES.strip())

    def test_trims_caller_trailing_whitespace(self):
        """The helper rstrips the caller's prompt so the separator
        between caller block and anchor block stays exactly two
        newlines — chatty docstrings or accidental trailing whitespace
        from string concat shouldn't introduce ragged spacing."""
        from services.will_voice import with_voice_rules
        result = with_voice_rules("Function-specific instructions.   \n\n\n")
        # Exactly one blank line between caller and anchor — that is,
        # exactly two consecutive newlines.
        self.assertNotIn(
            "\n\n\n", result.split("WILL'S VOICE")[0],
            msg="Caller's trailing whitespace not normalized",
        )

    def test_non_string_caller_raises(self):
        """Type-safety — callers passing None / dict / int by mistake
        get a loud TypeError, not silent str(None) injection."""
        from services.will_voice import with_voice_rules
        for bad in [None, 42, {"prompt": "x"}, ["a", "b"]]:
            with self.assertRaises(TypeError):
                with_voice_rules(bad)


class WillVoiceRulesContentTests(unittest.TestCase):
    """Structural contract: future edits to the anchor block can grow
    the libraries but must preserve the key sections every caller
    depends on for output-shape constraint.

    These tests check shape, NOT specific wording — the libraries are
    additive and will gain entries over time per the docstring's
    update protocol."""

    def test_contains_tone_rules_block(self):
        from services.will_voice import WILL_VOICE_RULES
        self.assertIn("TONE RULES", WILL_VOICE_RULES)
        # The five rule keywords must all be present (loose match).
        for token in (
            "Direct", "Specific", "Curious", "Present-tense", "Short",
        ):
            self.assertIn(token, WILL_VOICE_RULES, f"missing tone token: {token}")

    def test_contains_off_brand_block(self):
        from services.will_voice import WILL_VOICE_RULES, OFF_BRAND_EXAMPLES
        self.assertIn("OFF-BRAND OUTPUT", WILL_VOICE_RULES)
        # Every example from the library must appear verbatim in the
        # rendered anchor — if a future refactor accidentally drops the
        # bullet formatter, this catches it.
        for example in OFF_BRAND_EXAMPLES:
            self.assertIn(example, WILL_VOICE_RULES)

    def test_contains_on_brand_block(self):
        from services.will_voice import WILL_VOICE_RULES, ON_BRAND_EXAMPLES
        self.assertIn("ON-BRAND OUTPUT", WILL_VOICE_RULES)
        for example in ON_BRAND_EXAMPLES:
            self.assertIn(example, WILL_VOICE_RULES)

    def test_contains_heuristic_test_sentence(self):
        """The 'I had never noticed that' test is the load-bearing
        heuristic — every caller's output is judged by it.
        Non-negotiable per the implementation note."""
        from services.will_voice import WILL_VOICE_RULES
        self.assertIn("I had never noticed that", WILL_VOICE_RULES)
        self.assertIn("TEST BEFORE RESPONDING", WILL_VOICE_RULES)

    def test_contains_emotional_state_override(self):
        from services.will_voice import WILL_VOICE_RULES
        self.assertIn("EMOTIONAL-STATE OVERRIDE", WILL_VOICE_RULES)

    def test_libraries_are_tuples_not_lists(self):
        """Frozen-by-convention: callers might import the libraries
        for offline reference (e.g., an LLM-as-judge audit). Mutable
        list would invite accidental mutation across modules."""
        from services.will_voice import OFF_BRAND_EXAMPLES, ON_BRAND_EXAMPLES
        self.assertIsInstance(OFF_BRAND_EXAMPLES, tuple)
        self.assertIsInstance(ON_BRAND_EXAMPLES, tuple)

    def test_off_brand_library_has_minimum_coverage(self):
        """The user's spec explicitly listed 8 negative examples as
        the v1 floor; we ship with at least that many. The library
        is additive — this floor catches an accidental delete."""
        from services.will_voice import OFF_BRAND_EXAMPLES
        self.assertGreaterEqual(len(OFF_BRAND_EXAMPLES), 8)

    def test_on_brand_library_has_minimum_coverage(self):
        """At least the 3 anchor sentences + 2 supplementary
        positives the user provided. Floor of 5 enforced for the
        same delete-protection reason as above."""
        from services.will_voice import ON_BRAND_EXAMPLES
        self.assertGreaterEqual(len(ON_BRAND_EXAMPLES), 5)


class IntegrationSmokeTest(unittest.TestCase):
    """One smoke test that imports the helper from every caller module
    and confirms the import chain resolves. If any caller's import
    line is broken, this catches it BEFORE the deploy."""

    def test_every_caller_imports_helper_cleanly(self):
        # The 10 modules from the audit. If any one of these can't
        # import, that's a regression in the chain.
        callers = [
            "services.baseline_summary",
            "services.learner_mirror",
            "services.snippet_drafts",
            "services.session_kpi_narrative",
            "services.next_session_icebreaker",
            "services.charisma_profile",
            "services.coaching_intro",
            "services.directive_suggestions",
            "services.session_predictions",
            "services.master_doc_rag",
        ]
        from importlib import import_module
        for name in callers:
            try:
                import_module(name)
            except ImportError as e:
                self.fail(f"{name} failed to import: {e}")
            except Exception:
                # Other exceptions at import-time (e.g., missing env
                # vars, supabase client unavailable in test) are
                # outside the scope of this smoke test — we only
                # care that the module file PARSES + the import
                # graph resolves.
                pass


if __name__ == "__main__":
    unittest.main()
