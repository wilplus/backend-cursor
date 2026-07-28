"""willab — the LLM/ASR cost ledger (token-pricing Phase 0).

services/llm_usage.py + services/llm_pricing.py: one row per model call, so
the ×7 price multiplier in docs/PRICING-TOKENS-PLAN.md stops being an estimate.

WHAT THIS PINS DOWN:
  * the CONTRACT that makes it safe on the F1 live loop — the writer never
    raises, whatever the database does. Every take fires ~10 calls through it;
    an exception here would break recording, which is the one thing
    instrumentation must never do;
  * the self-disabling breaker, which is what lets this ship BEFORE the
    migration runs in prod (a missing table costs one warning, not one
    exception per model call forever);
  * the longest-prefix model match. A dated snapshot id like
    'gpt-4o-mini-2024-07-18' must price as gpt-4o-mini, NOT gpt-4o — a naive
    startswith over dict order overcharges by 16× and would silently inflate
    every cost estimate built on this table;
  * that a missing usage field costs precision, never the row — a NULL cost
    reads as 'free' in every rollup, which is the one wrong answer;
  * that no prompt or completion text can reach the table.

Run: python3 -m unittest test_llm_usage
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock

_ORIG_SERVICES_DB = None


def setUpModule():
    global _ORIG_SERVICES_DB
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    # RESTORE the saved original — a bare pop would let the next module build a
    # second DatabaseService singleton and silently miss patches.
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)


class _Usage:
    def __init__(self, prompt_tokens=None, completion_tokens=None):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _Response:
    def __init__(self, usage=None):
        self.usage = usage


class PricingTests(unittest.TestCase):
    def test_known_models_price_as_listed(self):
        from services.llm_pricing import cost_for_chat
        # 1M in + 1M out at gpt-4o-mini list = 0.15 + 0.60
        self.assertAlmostEqual(
            cost_for_chat("gpt-4o-mini", 1_000_000, 1_000_000), 0.75, places=6)
        self.assertAlmostEqual(
            cost_for_chat("gpt-4o", 1_000_000, 1_000_000), 12.50, places=6)

    def test_dated_snapshot_resolves_to_its_family_not_a_prefix_sibling(self):
        """THE trap: 'gpt-4o-mini-2024-07-18' startswith 'gpt-4o' too."""
        from services.llm_pricing import cost_for_chat, is_known_model
        mini = cost_for_chat("gpt-4o-mini-2024-07-18", 1_000_000, 0)
        self.assertAlmostEqual(mini, 0.15, places=6)
        # ...and emphatically NOT the gpt-4o rate, which is 16.7× higher.
        self.assertNotAlmostEqual(mini, 2.50, places=6)
        self.assertTrue(is_known_model("gpt-4o-2024-11-20"))

    def test_unknown_model_falls_back_rather_than_returning_none(self):
        from services.llm_pricing import cost_for_chat, is_known_model
        self.assertFalse(is_known_model("some-future-model"))
        # A NULL cost reads as "free" in a SUM; a wrong-but-present number is
        # visibly wrong and gets fixed.
        self.assertIsNotNone(cost_for_chat("some-future-model", 1000, 100))

    def test_one_missing_count_still_yields_a_cost(self):
        from services.llm_pricing import cost_for_chat
        self.assertAlmostEqual(
            cost_for_chat("gpt-4o-mini", 1_000_000, None), 0.15, places=6)
        self.assertIsNone(cost_for_chat("gpt-4o-mini", None, None))

    def test_audio_priced_per_minute(self):
        from services.llm_pricing import cost_for_audio
        self.assertAlmostEqual(cost_for_audio(60), 0.006, places=6)
        self.assertAlmostEqual(cost_for_audio(50), 0.005, places=4)
        self.assertIsNone(cost_for_audio(0))
        self.assertIsNone(cost_for_audio(None))

    def test_garbage_input_never_raises(self):
        from services.llm_pricing import cost_for_chat, cost_for_audio
        for bad in (None, "", "abc", object(), True, float("nan")):
            cost_for_chat("gpt-4o-mini", bad, bad)
            cost_for_audio(bad)


class _WriterCase(unittest.TestCase):
    """Base: fresh module state + a captured fake supabase client per test."""

    def setUp(self):
        import services.llm_usage as lu
        self.lu = lu
        lu.reset_breaker()
        self.rows: list = []
        self.fail_with: Exception | None = None

        table = MagicMock()

        def _insert(payload):
            if self.fail_with is not None:
                raise self.fail_with
            self.rows.append(payload)
            return MagicMock(execute=MagicMock(return_value=MagicMock(data=[payload])))

        table.insert.side_effect = _insert
        client = MagicMock()
        client.table.return_value = table
        sys.modules["services.db"].db = MagicMock(client=client)

    def tearDown(self):
        self.lu.reset_breaker()


class WriterContractTests(_WriterCase):
    def test_chat_usage_writes_the_expected_row(self):
        self.lu.record_chat_usage(
            surface="say_it_stronger", model="gpt-4o-mini",
            tokens_in=1500, tokens_out=900,
            user_id="u1", session_id="s1", arc_id="a1")
        self.assertEqual(len(self.rows), 1)
        row = self.rows[0]
        self.assertEqual(row["surface"], "say_it_stronger")
        self.assertEqual(row["tokens_in"], 1500)
        self.assertEqual(row["tokens_out"], 900)
        self.assertEqual(row["user_id"], "u1")
        self.assertEqual(row["session_id"], "s1")
        self.assertAlmostEqual(row["cost_usd"], 0.000765, places=6)
        self.assertIn("price_version", row)

    def test_audio_usage_records_seconds_not_tokens(self):
        self.lu.record_audio_usage(surface="whisper_spoken", seconds=50.0,
                                   session_id="s1")
        row = self.rows[0]
        self.assertAlmostEqual(row["audio_seconds"], 50.0)
        self.assertNotIn("tokens_in", row)
        self.assertNotIn("tokens_out", row)
        self.assertAlmostEqual(row["cost_usd"], 0.005, places=4)

    def test_no_prompt_or_completion_text_can_reach_the_table(self):
        """The table is a cost ledger, not a transcript store."""
        self.lu.record_chat_usage(
            surface="master_doc_rag", model="gpt-4o-mini",
            tokens_in=9000, tokens_out=600, user_id="u1")
        allowed = {
            "surface", "model", "tokens_in", "tokens_out", "audio_seconds",
            "cost_usd", "price_version", "user_id", "session_id", "arc_id",
        }
        self.assertTrue(set(self.rows[0]).issubset(allowed),
                        f"unexpected columns: {set(self.rows[0]) - allowed}")

    def test_response_helper_reads_usage_off_the_sdk_object(self):
        self.lu.record_response_usage(
            _Response(_Usage(1200, 300)),
            surface="stickiness_topics", model="gpt-4o-mini")
        self.assertEqual(self.rows[0]["tokens_in"], 1200)
        self.assertEqual(self.rows[0]["tokens_out"], 300)

    def test_response_without_usage_still_records_the_call(self):
        """OpenAI omits `usage` on some paths. We paid regardless — the row
        must exist so the CALL COUNT stays honest even when cost is unknown."""
        self.lu.record_response_usage(
            _Response(None), surface="snippet_drafts", model="gpt-4o-mini")
        self.assertEqual(len(self.rows), 1)
        self.assertEqual(self.rows[0]["surface"], "snippet_drafts")

    def test_surfaceless_call_is_dropped(self):
        self.lu.record_chat_usage(surface="", model="gpt-4o-mini",
                                  tokens_in=1, tokens_out=1)
        self.assertEqual(self.rows, [])


class NeverRaisesTests(_WriterCase):
    """THE fence. This runs on the F1 live loop; it may never break a take."""

    def test_database_exception_is_swallowed(self):
        self.fail_with = RuntimeError("relation \"llm_usage\" does not exist")
        self.lu.record_chat_usage(surface="say_it_stronger",
                                  model="gpt-4o-mini",
                                  tokens_in=10, tokens_out=10)  # must not raise

    def test_missing_db_module_is_swallowed(self):
        sys.modules["services.db"].db = None
        self.lu.record_chat_usage(surface="x", model="gpt-4o-mini",
                                  tokens_in=1, tokens_out=1)

    def test_junk_arguments_are_swallowed(self):
        self.lu.record_chat_usage(surface="x", model=None,
                                  tokens_in="lots", tokens_out=object())
        self.lu.record_audio_usage(surface="x", seconds="ages")
        self.lu.record_response_usage(object(), surface="x", model="gpt-4o-mini")

    def test_breaker_opens_after_repeated_failure_and_then_stops_trying(self):
        """Ships before the migration runs: a missing table must cost one
        warning, not an exception per model call forever."""
        self.fail_with = RuntimeError("table missing")
        table = sys.modules["services.db"].db.client.table.return_value
        for _ in range(self.lu._FAILURE_BREAKER):
            self.lu.record_chat_usage(surface="s", model="gpt-4o-mini",
                                      tokens_in=1, tokens_out=1)
        calls_at_trip = table.insert.call_count
        for _ in range(20):
            self.lu.record_chat_usage(surface="s", model="gpt-4o-mini",
                                      tokens_in=1, tokens_out=1)
        self.assertEqual(table.insert.call_count, calls_at_trip,
                         "breaker open but writer still hitting the database")

    def test_breaker_rearms_on_reset(self):
        self.fail_with = RuntimeError("boom")
        for _ in range(self.lu._FAILURE_BREAKER + 2):
            self.lu.record_chat_usage(surface="s", model="gpt-4o-mini",
                                      tokens_in=1, tokens_out=1)
        self.lu.reset_breaker()
        self.fail_with = None
        self.lu.record_chat_usage(surface="s", model="gpt-4o-mini",
                                  tokens_in=1, tokens_out=1)
        self.assertEqual(len(self.rows), 1)

    def test_a_success_clears_the_failure_run(self):
        """Transient blips must not accumulate into a trip across a long
        pipeline — only CONSECUTIVE failures count."""
        for _ in range(self.lu._FAILURE_BREAKER - 1):
            self.fail_with = RuntimeError("blip")
            self.lu.record_chat_usage(surface="s", model="gpt-4o-mini",
                                      tokens_in=1, tokens_out=1)
            self.fail_with = None
            self.lu.record_chat_usage(surface="s", model="gpt-4o-mini",
                                      tokens_in=1, tokens_out=1)
        self.assertFalse(self.lu._breaker_open)


class ChatCompleteHookTests(_WriterCase):
    """services/llm.py is THE hook covering ~15 surfaces. What it records, and
    — the easy bug — when it records relative to its own early exits."""

    def _patch_openai(self, content: str, prompt=1200, completion=300):
        from unittest.mock import patch
        msg = MagicMock(content=content)
        resp = MagicMock(choices=[MagicMock(message=msg)],
                         usage=_Usage(prompt, completion))
        svc = MagicMock()
        svc.client.chat.completions.create.return_value = resp
        mod = types.ModuleType("services.openai_service")
        mod.OpenAIService = MagicMock(return_value=svc)
        return patch.dict(sys.modules, {"services.openai_service": mod})

    def _spec(self):
        from services.llm_config import LLMSpec
        return LLMSpec(model="gpt-4o-mini", temperature=0.3, max_tokens=100)

    def test_records_on_the_happy_path(self):
        from services.llm import chat_complete
        with self._patch_openai("hello"):
            res = chat_complete(spec=self._spec(), system="s", user="u",
                                surface="say_it_stronger", user_id="u1",
                                session_id="sess1", arc_id="arc1")
        self.assertIsNotNone(res)
        self.assertEqual(len(self.rows), 1)
        self.assertEqual(self.rows[0]["surface"], "say_it_stronger")
        self.assertEqual(self.rows[0]["session_id"], "sess1")
        self.assertEqual(self.rows[0]["arc_id"], "arc1")

    def test_an_empty_completion_is_still_recorded(self):
        """We were billed for it. Dropping these rows would bias measured cost
        DOWNWARD exactly where the model is misbehaving — and chat_complete
        returns None on empty, so the row is the only trace left."""
        from services.llm import chat_complete
        with self._patch_openai("   "):
            res = chat_complete(spec=self._spec(), system="s", user="u",
                                surface="moment_suggestion")
        self.assertIsNone(res, "empty response should still return None")
        self.assertEqual(len(self.rows), 1,
                         "paid-for empty completion was not recorded")
        self.assertEqual(self.rows[0]["tokens_in"], 1200)

    def test_ledger_failure_never_breaks_the_llm_call(self):
        """The fence, end to end: the take pipeline runs through here."""
        from services.llm import chat_complete
        self.fail_with = RuntimeError("llm_usage exploded")
        with self._patch_openai("still fine"):
            res = chat_complete(spec=self._spec(), system="s", user="u",
                                surface="say_it_stronger")
        self.assertIsNotNone(res)
        self.assertEqual(res.text, "still fine")


class KillSwitchTests(_WriterCase):
    def test_flag_off_writes_nothing(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {"LLM_USAGE_ENABLED": "0"}):
            self.lu.record_chat_usage(surface="s", model="gpt-4o-mini",
                                      tokens_in=1, tokens_out=1)
        self.assertEqual(self.rows, [])

    def test_default_is_on(self):
        import os
        from unittest.mock import patch
        env = {k: v for k, v in os.environ.items() if k != "LLM_USAGE_ENABLED"}
        with patch.dict(os.environ, env, clear=True):
            self.lu.record_chat_usage(surface="s", model="gpt-4o-mini",
                                      tokens_in=1, tokens_out=1)
        self.assertEqual(len(self.rows), 1)


if __name__ == "__main__":
    unittest.main()
