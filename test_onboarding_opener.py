"""Unit tests for the onboarding dad-joke opener (Ticket 2).

Covers:
  - The canonical strings (DAD_JOKE_FRAME, PIVOT_LINE) are immutable
    constants in the right shape — guards against accidental
    rewrites in a future refactor.
  - Bubble builders return the FE-contracted shape.
  - LLM ack failure paths return empty string gracefully.
  - Clamp behavior on oversize ack.

The LLM call itself is NOT exercised end-to-end (needs OpenAI key);
generate_punchline_ack's structural behavior is exercised with the
chat_complete helper mocked.

Run: python3 -m unittest test_onboarding_opener
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# services.db pulls in supabase/postgrest, which aren't in the test
# image, so we stub it — in setUpModule, NOT at import time. A stub
# left in sys.modules at import time leaks into sibling test modules:
# test_homework_regressions decides at import time whether the real
# services.db is importable, and a leaked stub makes it run against
# the fake instead of skipping. tearDownModule restores the state.
def setUpModule():
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    sys.modules.pop("services.db", None)


class ConstantsTests(unittest.TestCase):
    """The canonical strings are load-bearing — every opener flow
    ends with PIVOT_LINE verbatim and every opener flow begins with
    DAD_JOKE_FRAME verbatim. A typo here breaks analytics and the
    brand voice on the user's first interaction with Will."""

    def test_dad_joke_frame_exact_text(self):
        from services.onboarding_opener import DAD_JOKE_FRAME
        self.assertEqual(
            DAD_JOKE_FRAME,
            "Attention, before we begin, let me crack a dad-joke!",
        )

    def test_pivot_line_exact_text(self):
        from services.onboarding_opener import PIVOT_LINE
        self.assertEqual(
            PIVOT_LINE,
            "Okok, nevermind. Let's focus on public speaking — "
            "how can I help you?",
        )

    def test_pivot_line_contains_public_speaking(self):
        """Anti-drift safety net — if a future refactor mutates the
        pivot, this catches the most likely drift mode (someone
        broadening it past public speaking)."""
        from services.onboarding_opener import PIVOT_LINE
        self.assertIn("public speaking", PIVOT_LINE)

    def test_frame_is_string_not_callable(self):
        """Defensive — DAD_JOKE_FRAME is a string constant, not a
        factory. A refactor that turns it into a function would
        silently break every caller that does string formatting."""
        from services.onboarding_opener import DAD_JOKE_FRAME, PIVOT_LINE
        self.assertIsInstance(DAD_JOKE_FRAME, str)
        self.assertIsInstance(PIVOT_LINE, str)


class BubbleBuilderTests(unittest.TestCase):
    """The /start and /next routes consume these builders directly;
    a change to the wire-shape is a FE contract break."""

    def test_setup_message_shape(self):
        from services.onboarding_opener import (
            build_setup_message, DAD_JOKE_FRAME,
        )
        out = build_setup_message({
            "id": "joke-uuid-1",
            "setup": "How do cows stay up to date?",
            "punchline": "ignored at setup stage",
            "emoji": "🐄",
        })
        self.assertEqual(out["stage"], "setup")
        self.assertEqual(out["joke_id"], "joke-uuid-1")
        self.assertEqual(out["frame"], DAD_JOKE_FRAME)
        self.assertEqual(out["setup"], "How do cows stay up to date?")
        # Punchline + emoji NOT in setup bubble — they land in stage 2.
        self.assertNotIn("punchline", out)
        self.assertNotIn("emoji", out)

    def test_punchline_message_shape_with_emoji(self):
        from services.onboarding_opener import build_punchline_message
        out = build_punchline_message(
            {
                "id": "joke-uuid-1",
                "punchline": "They read the moos-paper.",
                "emoji": "🐄",
            },
            ack="Alright:",
        )
        self.assertEqual(out["stage"], "punchline")
        self.assertEqual(out["joke_id"], "joke-uuid-1")
        self.assertEqual(out["ack"], "Alright:")
        # Punchline + emoji join into one string (timing reasons —
        # the emoji is the comic landing).
        self.assertEqual(out["punchline"], "They read the moos-paper. 🐄")

    def test_punchline_message_handles_missing_emoji(self):
        from services.onboarding_opener import build_punchline_message
        out = build_punchline_message(
            {"id": "x", "punchline": "Attire.", "emoji": ""},
            ack="",
        )
        self.assertEqual(out["punchline"], "Attire.")
        self.assertEqual(out["ack"], "")

    def test_punchline_message_ack_optional(self):
        """The /next route falls back to ack='' when the LLM bridge
        fails. The builder must accept that without choking."""
        from services.onboarding_opener import build_punchline_message
        out = build_punchline_message(
            {"id": "x", "punchline": "Attire.", "emoji": "🎩"},
        )
        self.assertEqual(out["ack"], "")

    def test_pivot_message_shape(self):
        from services.onboarding_opener import (
            build_pivot_message, PIVOT_LINE,
        )
        out = build_pivot_message()
        self.assertEqual(out["stage"], "pivot")
        self.assertIsNone(out["joke_id"])
        # The pivot line is delivered VERBATIM — anti-drift assertion.
        self.assertEqual(out["pivot_line"], PIVOT_LINE)
        self.assertTrue(out["done"])

    def test_pivot_message_is_deterministic(self):
        """Same call → same output. No randomness, no time-based
        drift, no per-user variation."""
        from services.onboarding_opener import build_pivot_message
        self.assertEqual(build_pivot_message(), build_pivot_message())


class LLMAckTests(unittest.TestCase):
    """generate_punchline_ack is best-effort — every failure path
    returns "" so the caller can ship the canonical punchline alone."""

    def test_empty_user_reply_short_circuits(self):
        from services.onboarding_opener import generate_punchline_ack
        # No LLM call should fire for empty input — we don't even
        # need to mock chat_complete, because the function returns
        # before importing it.
        self.assertEqual(generate_punchline_ack(""), "")
        self.assertEqual(generate_punchline_ack("   "), "")
        self.assertEqual(generate_punchline_ack("\n\t"), "")

    def test_llm_unavailable_returns_empty_string(self):
        from services import onboarding_opener as mod

        # Patch chat_complete to return None (simulates LLM down /
        # client unavailable). The function should return "" without
        # raising.
        with patch(
            "services.llm.chat_complete", return_value=None,
        ):
            out = mod.generate_punchline_ack("I don't know")
        self.assertEqual(out, "")

    def test_oversize_ack_clamped(self):
        """Defensive — the LLM occasionally exceeds maxLength
        despite the spec. Clamp at MAX_ACK_LEN with an ellipsis."""
        from services import onboarding_opener as mod

        overflow = "A" * 200  # way over MAX_ACK_LEN=80
        fake_result = MagicMock()
        fake_result.parsed = {"ack": overflow}
        fake_result.text = '{"ack": "' + overflow + '"}'
        with patch(
            "services.llm.chat_complete", return_value=fake_result,
        ):
            out = mod.generate_punchline_ack("here goes")
        self.assertLessEqual(len(out), mod.MAX_ACK_LEN)
        self.assertTrue(out.endswith("…"))

    def test_well_formed_ack_returned_as_is(self):
        from services import onboarding_opener as mod

        fake_result = MagicMock()
        fake_result.parsed = {"ack": "Alright:"}
        fake_result.text = '{"ack": "Alright:"}'
        with patch(
            "services.llm.chat_complete", return_value=fake_result,
        ):
            out = mod.generate_punchline_ack("idk")
        self.assertEqual(out, "Alright:")

    def test_malformed_llm_output_returns_empty(self):
        from services import onboarding_opener as mod

        # parsed is not a dict (e.g., LLM returned a string instead
        # of the {"ack": "..."} object the schema demands).
        fake_result = MagicMock()
        fake_result.parsed = "not a dict"
        fake_result.text = "not a dict"
        with patch(
            "services.llm.chat_complete", return_value=fake_result,
        ):
            out = mod.generate_punchline_ack("idk")
        self.assertEqual(out, "")


class PickRandomJokeTests(unittest.TestCase):
    """pick_random_joke is a thin wrapper around db.get_random_dad_
    joke — guard the failure-mode contract (None → silent skip)."""

    def test_db_failure_returns_none(self):
        from services import onboarding_opener as mod
        from services.db import db

        # Replace the attribute outright so the call raises.
        with patch.object(
            db, "get_random_dad_joke",
            side_effect=Exception("supabase down"),
        ):
            out = mod.pick_random_joke()
        self.assertIsNone(out)

    def test_returns_db_payload_unchanged(self):
        from services import onboarding_opener as mod
        from services.db import db

        joke = {
            "id": "x",
            "setup": "Setup?",
            "punchline": "Punchline.",
            "emoji": "🐄",
        }
        with patch.object(
            db, "get_random_dad_joke", return_value=joke,
        ):
            out = mod.pick_random_joke()
        self.assertEqual(out, joke)

    def test_returns_none_when_table_empty(self):
        from services import onboarding_opener as mod
        from services.db import db

        with patch.object(
            db, "get_random_dad_joke", return_value=None,
        ):
            out = mod.pick_random_joke()
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
