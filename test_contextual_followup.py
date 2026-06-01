"""Unit tests for services.contextual_followup (FIX.1).

Covers the intent-picking truth table + the fallback contract.
LLM call is mocked; the test surface is "given snippet counts +
last transcript, what does the endpoint return?"

Run: python3 -m unittest test_contextual_followup
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# Stub services.db before import so we can run without supabase.
_stub_db_module = types.ModuleType("services.db")
_stub_db_module.db = MagicMock()
sys.modules.setdefault("services.db", _stub_db_module)


def _state(charisma_count=0, stress_count=0, duration_ms=0):
    """Build a completion_state shape matching the gate's contract."""
    return {
        "ready": (
            charisma_count >= 1 and stress_count >= 1 and duration_ms >= 60_000
        ),
        "criteria": {
            "has_charisma": charisma_count >= 1,
            "has_stress":   stress_count >= 1,
            "duration_ok":  duration_ms >= 60_000,
        },
        "current": {
            "charisma_count":    charisma_count,
            "stress_count":      stress_count,
            "total_duration_ms": duration_ms,
            "threshold_seconds": 60,
        },
    }


class IntentPickingTests(unittest.TestCase):
    """The target-intent rule — missing intent has absolute priority,
    then weaker-side deepening, ties default to charisma."""

    def _pick(self, **counts):
        from services.contextual_followup import _pick_target_intent
        return _pick_target_intent(_state(**counts))

    def test_no_snippets_picks_charisma(self):
        self.assertEqual(self._pick(), "charisma")

    def test_only_charisma_picks_stress(self):
        self.assertEqual(self._pick(charisma_count=2), "stress")

    def test_only_stress_picks_charisma(self):
        self.assertEqual(self._pick(stress_count=3), "charisma")

    def test_both_present_picks_weaker_side(self):
        # More stress than charisma → next should be charisma
        self.assertEqual(
            self._pick(charisma_count=1, stress_count=4), "charisma",
        )
        # More charisma than stress → next should be stress
        self.assertEqual(
            self._pick(charisma_count=3, stress_count=1), "stress",
        )

    def test_tie_defaults_to_charisma(self):
        """Tie → charisma (gentler intent; avoids loading the back
        half of a session with stress)."""
        self.assertEqual(
            self._pick(charisma_count=2, stress_count=2), "charisma",
        )

    def test_both_zero_returns_charisma_not_stress(self):
        """Edge case: same as no-snippets, just being explicit."""
        self.assertEqual(self._pick(charisma_count=0, stress_count=0), "charisma")


class TranscriptExtractionTests(unittest.TestCase):

    def _extract(self, turns):
        from services.contextual_followup import _extract_last_transcript
        return _extract_last_transcript(turns)

    def test_returns_last_non_empty_transcript(self):
        out = self._extract([
            {"question": "Q1", "transcript": "early answer"},
            {"question": "Q2", "transcript": "latest answer"},
        ])
        self.assertEqual(out, "latest answer")

    def test_skips_empty_transcripts_walking_back(self):
        out = self._extract([
            {"question": "Q1", "transcript": "early answer"},
            {"question": "Q2", "transcript": ""},  # skip
            {"question": "Q3", "transcript": "   "},  # skip
        ])
        self.assertEqual(out, "early answer")

    def test_empty_input_returns_empty(self):
        self.assertEqual(self._extract(None), "")
        self.assertEqual(self._extract([]), "")

    def test_non_dict_entries_skipped(self):
        out = self._extract([
            "garbage",
            {"question": "Q1", "transcript": "good answer"},
            None,
        ])
        self.assertEqual(out, "good answer")


class SoftOpenerPathTests(unittest.TestCase):
    """No previous_turns (turn 1) → soft_opener source with on-intent
    fallback content."""

    def _generate(self, **kwargs):
        from services import contextual_followup as mod
        with patch.object(
            mod, "_safe_completion_state",
            return_value=_state(**kwargs.pop("counts", {})),
        ):
            return mod.generate_contextual_followup(
                guest_session_id=None,
                previous_turns=None,
            )

    def test_no_session_no_turns_returns_soft_opener(self):
        out = self._generate()
        self.assertEqual(out["source"], "soft_opener")
        self.assertEqual(out["target_intent"], "charisma")
        self.assertTrue(out["question"])  # non-empty
        self.assertEqual(out["bridge_to"], "")

    def test_soft_opener_intent_reflects_state(self):
        """When charisma is present and stress isn't, soft opener
        still targets stress."""
        out = self._generate(counts={"charisma_count": 2})
        self.assertEqual(out["target_intent"], "stress")
        self.assertEqual(out["source"], "soft_opener")

    def test_soft_opener_carries_completion_state(self):
        """FE consumes completion_state from the response to keep
        the gate chips live without a separate call."""
        out = self._generate(counts={"charisma_count": 1, "stress_count": 0})
        self.assertIn("completion_state", out)
        self.assertIn("criteria", out["completion_state"])
        self.assertTrue(out["completion_state"]["criteria"]["has_charisma"])
        self.assertFalse(out["completion_state"]["criteria"]["has_stress"])


class LLMPathTests(unittest.TestCase):
    """When previous_turns has a transcript, the LLM gets called.
    Mocking lets us assert the wrapper contract."""

    def test_llm_success_returns_contextual_llm_source(self):
        from services import contextual_followup as mod
        with patch.object(
            mod, "_safe_completion_state",
            return_value=_state(charisma_count=1),  # need stress
        ), patch.object(
            mod, "_llm_generate_bridge_question",
            return_value={
                "question":  "What's the hardest part of those climbs?",
                "bridge_to": "user mentioned cycling",
            },
        ):
            out = mod.generate_contextual_followup(
                guest_session_id="sid-1",
                previous_turns=[
                    {"question": "Tell me about you",
                     "transcript": "I ride my bike to clear my head"},
                ],
            )
        self.assertEqual(out["source"], "contextual_llm")
        self.assertEqual(out["target_intent"], "stress")
        self.assertEqual(out["question"], "What's the hardest part of those climbs?")
        self.assertEqual(out["bridge_to"], "user mentioned cycling")

    def test_llm_failure_falls_back_with_tagged_source(self):
        """Per FE handoff Q3: fallback ships with explicit source
        tag so we can audit fallback rate."""
        from services import contextual_followup as mod
        with patch.object(
            mod, "_safe_completion_state",
            return_value=_state(charisma_count=2),  # need stress
        ), patch.object(
            mod, "_llm_generate_bridge_question",
            return_value=None,  # LLM down
        ):
            out = mod.generate_contextual_followup(
                guest_session_id="sid-1",
                previous_turns=[
                    {"question": "X", "transcript": "real answer"},
                ],
            )
        self.assertEqual(out["source"], "contextual_llm_fallback")
        self.assertEqual(out["target_intent"], "stress")
        self.assertTrue(out["question"])  # fallback content present
        self.assertEqual(out["bridge_to"], "")

    def test_llm_returns_empty_question_falls_back(self):
        """Schema-valid but content-empty LLM response → fallback."""
        from services import contextual_followup as mod
        with patch.object(
            mod, "_safe_completion_state",
            return_value=_state(),
        ), patch.object(
            mod, "_llm_generate_bridge_question",
            return_value=None,
        ):
            out = mod.generate_contextual_followup(
                guest_session_id="sid-1",
                previous_turns=[{"transcript": "anything"}],
            )
        self.assertEqual(out["source"], "contextual_llm_fallback")


class HistoryFormatterTests(unittest.TestCase):

    def _fmt(self, turns):
        from services.contextual_followup import _format_history_for_prompt
        return _format_history_for_prompt(turns)

    def test_empty_history_renders_placeholder(self):
        self.assertIn("none yet", self._fmt([]))
        self.assertIn("none yet", self._fmt(None))

    def test_caps_at_last_3_turns(self):
        """Prevents token blow-up on a 10-turn session."""
        many = [
            {"question": f"Q{i}", "transcript": f"A{i}"}
            for i in range(10)
        ]
        out = self._fmt(many)
        # First few turns must be absent; only last 3 present.
        self.assertNotIn("Q0", out)
        self.assertNotIn("Q5", out)
        self.assertIn("A9", out)  # last user answer present

    def test_truncates_long_transcripts(self):
        """Defense against a chatty user blowing the token budget."""
        out = self._fmt([{
            "question": "x", "transcript": "X" * 1000,
        }])
        # Should contain the ellipsis marker, not the full 1000-char run
        self.assertIn("…", out)
        self.assertLess(len(out), 1500)


class CompletionStateSafetyTests(unittest.TestCase):

    def test_none_session_id_returns_empty_state(self):
        from services.contextual_followup import _safe_completion_state
        state = _safe_completion_state(None, 60)
        self.assertFalse(state["ready"])
        self.assertEqual(state["current"]["charisma_count"], 0)
        self.assertEqual(state["current"]["threshold_seconds"], 60)

    def test_gate_lookup_failure_returns_empty_state(self):
        """A DB hiccup must not bubble — return empty default so
        the caller can still pick an intent + ship a question."""
        from services import contextual_followup as mod
        with patch(
            "services.interview_completion_gate.completion_state",
            side_effect=Exception("supabase down"),
        ):
            state = mod._safe_completion_state("sid-1", 60)
        self.assertFalse(state["ready"])
        self.assertEqual(state["current"]["charisma_count"], 0)


if __name__ == "__main__":
    unittest.main()
