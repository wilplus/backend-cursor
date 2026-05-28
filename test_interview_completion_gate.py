"""Unit tests for the session-1 completion gate.

Covers all five acceptance scenarios from the BE handoff for
task 6 (Session-1 completion gate: ≥1 charisma + ≥1 stress + ≥60s).

The gate helper is a pure function over snippet rows once the DB
read returns them, so we stub services.db.db.get_snippets_by_session
to feed deterministic test fixtures.

Run: python3 -m unittest test_interview_completion_gate
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ── Stub heavy deps before importing the module under test ─────────
# services.db pulls in supabase / postgrest etc. that aren't part of
# the test image. We swap the db module for a stub that provides
# the one attribute the gate touches (get_snippets_by_session) so
# the import chain resolves without a venv.
_stub_db_module = types.ModuleType("services.db")
_stub_db_module.db = MagicMock()
sys.modules.setdefault("services.db", _stub_db_module)


class CompletionGateTests(unittest.TestCase):

    def _eval(self, snippets, threshold=60):
        """Call the gate helper with a stubbed DB read."""
        from services import interview_completion_gate as gate
        with patch.object(
            gate.db, "get_snippets_by_session", return_value=snippets,
        ):
            return gate.session_1_completion_state(
                "sid-test", threshold_seconds=threshold,
            )

    # ── Acceptance cases from the handoff ──────────────────────────

    def test_two_charisma_zero_stress_90s_misses_stress(self):
        """Brief case 1: 2 charisma + 0 stress + 90s → incomplete,
        missing=['stress']."""
        snippets = [
            {"question_tone": "charisma", "duration_ms": 45_000},
            {"question_tone": "charisma", "duration_ms": 45_000},
        ]
        out = self._eval(snippets)
        self.assertFalse(out["session_1_complete"])
        self.assertEqual(out["session_1_gate"]["charisma_count"], 2)
        self.assertEqual(out["session_1_gate"]["stress_count"], 0)
        self.assertEqual(out["session_1_gate"]["duration_seconds"], 90.0)
        self.assertEqual(out["session_1_gate"]["missing"], ["stress"])

    def test_one_each_with_enough_audio_passes(self):
        """Brief case 2: 1 charisma + 1 stress + 100s → complete."""
        snippets = [
            {"question_tone": "charisma", "duration_ms": 45_000},
            {"question_tone": "charisma", "duration_ms": 45_000},
            {"question_tone": "stress",   "duration_ms": 10_000},
        ]
        out = self._eval(snippets)
        self.assertTrue(out["session_1_complete"])
        self.assertEqual(out["session_1_gate"]["missing"], [])
        self.assertEqual(out["session_1_gate"]["stress_count"], 1)

    def test_one_each_short_audio_misses_duration(self):
        """Brief case 3: 1 charisma + 1 stress + 25s → incomplete,
        missing=['duration']."""
        snippets = [
            {"question_tone": "charisma", "duration_ms": 10_000},
            {"question_tone": "stress",   "duration_ms": 15_000},
        ]
        out = self._eval(snippets)
        self.assertFalse(out["session_1_complete"])
        self.assertEqual(out["session_1_gate"]["duration_seconds"], 25.0)
        self.assertEqual(out["session_1_gate"]["missing"], ["duration"])

    def test_empty_session_misses_everything(self):
        """Brief case 4: no recordings yet → all zeros, all three
        missing."""
        out = self._eval([])
        self.assertFalse(out["session_1_complete"])
        self.assertEqual(out["session_1_gate"]["charisma_count"], 0)
        self.assertEqual(out["session_1_gate"]["stress_count"], 0)
        self.assertEqual(out["session_1_gate"]["duration_seconds"], 0.0)
        self.assertEqual(
            out["session_1_gate"]["missing"],
            ["charisma", "stress", "duration"],
        )

    # ── Edge cases the gate must not break on ──────────────────────

    def test_threshold_echoes_into_response(self):
        """Field is present so FE never hardcodes 60."""
        out = self._eval([])
        self.assertEqual(
            out["session_1_gate"]["threshold_seconds"], 60,
        )

    def test_threshold_override_respected(self):
        """Test seam — non-60 thresholds compute correctly."""
        snippets = [
            {"question_tone": "charisma", "duration_ms": 20_000},
            {"question_tone": "stress",   "duration_ms": 25_000},
        ]
        # 45s total, threshold raised to 30 → passes
        out = self._eval(snippets, threshold=30)
        self.assertTrue(out["session_1_complete"])
        # Same data, threshold raised to 60 → fails
        out2 = self._eval(snippets, threshold=60)
        self.assertFalse(out2["session_1_complete"])
        self.assertEqual(out2["session_1_gate"]["missing"], ["duration"])

    def test_tone_normalisation_case_insensitive(self):
        """Stray casing on question_tone shouldn't break the count."""
        snippets = [
            {"question_tone": "CHARISMA", "duration_ms": 30_000},
            {"question_tone": "Stress",   "duration_ms": 30_000},
        ]
        out = self._eval(snippets)
        self.assertTrue(out["session_1_complete"])

    def test_ebcp_and_unknown_tones_count_for_duration_not_buckets(self):
        """Per the contract — non-charisma/stress tones contribute
        to the 60s minimum but don't satisfy either tone bucket."""
        snippets = [
            {"question_tone": "ebcp",     "duration_ms": 30_000},
            {"question_tone": "trust",    "duration_ms": 30_000},
            {"question_tone": "charisma", "duration_ms": 5_000},
        ]
        out = self._eval(snippets)
        # 65s total — duration passes, stress still missing.
        self.assertFalse(out["session_1_complete"])
        self.assertEqual(out["session_1_gate"]["charisma_count"], 1)
        self.assertEqual(out["session_1_gate"]["stress_count"], 0)
        self.assertEqual(out["session_1_gate"]["duration_seconds"], 65.0)
        self.assertEqual(out["session_1_gate"]["missing"], ["stress"])

    def test_null_or_negative_duration_skipped(self):
        """A row with missing or zero duration_ms shouldn't poison
        the sum or the count."""
        snippets = [
            {"question_tone": "charisma", "duration_ms": None},
            {"question_tone": "stress",   "duration_ms": 0},
            {"question_tone": "charisma", "duration_ms": 30_000},
            {"question_tone": "stress",   "duration_ms": 35_000},
        ]
        out = self._eval(snippets)
        # 65s real audio, both tones present → complete.
        self.assertTrue(out["session_1_complete"])
        self.assertEqual(out["session_1_gate"]["charisma_count"], 2)
        self.assertEqual(out["session_1_gate"]["stress_count"], 2)

    def test_missing_field_doesnt_crash(self):
        """Defensive — a row without question_tone or duration_ms."""
        snippets = [
            {},                                          # truly empty row
            {"question_tone": "charisma"},               # no duration
            {"duration_ms": 70_000},                     # no tone
            {"question_tone": "stress", "duration_ms": 100},  # ~0.1s
        ]
        out = self._eval(snippets)
        # 70.1s total, charisma=1, stress=1 → complete.
        self.assertTrue(out["session_1_complete"])

    def test_db_read_failure_returns_safe_default(self):
        """A DB exception during snippet load shouldn't crash the
        gate — it should return the 'all missing' shape so the FE
        keeps the recorder open."""
        from services import interview_completion_gate as gate
        with patch.object(
            gate.db, "get_snippets_by_session",
            side_effect=RuntimeError("supabase down"),
        ):
            out = gate.session_1_completion_state("sid-x")
        self.assertFalse(out["session_1_complete"])
        self.assertEqual(
            out["session_1_gate"]["missing"],
            ["charisma", "stress", "duration"],
        )


if __name__ == "__main__":
    unittest.main()
