"""
STORY    As a speaker, I want "Say It Stronger" cards compared only with my
         own past and never with numbers, and delivered even when the job
         ends, so that I get words I can act on, not scores.
OUTCOME
  O1  The job can wait for the cards, so they land before the worker exits.
  O2  Never-1: a card's coaching copy with a digit ("3 times better") or an
      internal term is dropped; the speaker's rewrites and plain-word copy
      are kept.
  O3  The model is told how this moment compares with the speaker's OWN
      average, in words only - never the raw measurement.
PROVES   O1 -> test_the_job_can_wait_for_the_cards
         O2 -> test_numbers_and_internal_terms_never_reach_the_card
         O3 -> test_the_comparison_is_in_words_against_my_own_average
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


TRANSCRIPT = "We think this could maybe help our customers a lot"


def _model_answer(**overrides):
    answer = {
        "already_strong": False,
        "upgrades": [
            {"original": "maybe", "upgrade": "will",
             "reason": "This lands 3 times better", "kind": "upgrade",
             "scope": "word"},
            {"original": "a lot", "upgrade": "every day",
             "reason": "Concrete words make the promise real",
             "kind": "upgrade", "scope": "phrase"},
            {"original": "We think", "upgrade": "We know",
             "reason": "your charisma score rises here", "kind": "upgrade",
             "scope": "phrase"},
        ],
        "rewrite_your_voice": "This will help our customers every day",
        "rewrite_polished": "This helps our customers every single day",
        "why": "Certain words carry your point further",
    }
    answer.update(overrides)
    return answer


def _generate(answer, metrics=None, means=None):
    import services.llm as llm
    from services.say_it_stronger import generate_say_it_stronger

    sent = {}

    def _chat(**kwargs):
        sent.update(kwargs)
        return types.SimpleNamespace(parsed=answer, text="", model="m")

    with patch.object(llm, "chat_complete", _chat):
        card = generate_say_it_stronger(TRANSCRIPT, metrics, means)
    return card, sent


class CardsSurviveTheJobTests(unittest.TestCase):
    """The RQ work horse exits the moment the job returns, taking a daemon
    thread with it (founder 2026-10-14, the wait)."""

    def test_the_job_can_wait_for_the_cards(self):
        import threading

        import services.say_it_stronger as sis

        done = threading.Event()
        with patch.object(sis, "_generate_all",
                          lambda *a, **k: done.set()):
            sis.dispatch_say_it_stronger(
                "sess-wait", [{"id": "s1", "transcript": "x"}])
            self.assertTrue(sis.wait_for_cards("sess-wait", timeout=5))
        self.assertTrue(done.is_set())
        # Nothing left to wait for is not a failure.
        self.assertTrue(sis.wait_for_cards("sess-wait"))


class NeverANumberTests(unittest.TestCase):
    def test_numbers_and_internal_terms_never_reach_the_card(self):
        card, _ = _generate(_model_answer())
        self.assertIsNotNone(card)
        reasons = {u["original"]: u["reason"] for u in card["upgrades"]}
        # The pairs stay; only the offending copy goes.
        self.assertEqual(set(reasons), {"maybe", "a lot", "We think"})
        self.assertIsNone(reasons["maybe"])       # "3 times better"
        self.assertIsNone(reasons["We think"])    # internal "charisma score"
        self.assertEqual(reasons["a lot"],
                         "Concrete words make the promise real")
        self.assertEqual(card["why"], "Certain words carry your point further")
        self.assertEqual(card["rewrite_your_voice"],
                         "This will help our customers every day")

        card, _ = _generate(_model_answer(why="Pause 2 seconds before this"))
        self.assertIsNone(card["why"])

    def test_the_comparison_is_in_words_against_my_own_average(self):
        means = {"pace": 140.0, "pausing": 0.2}
        _, sent = _generate(_model_answer(),
                            metrics={"wpm": 187.3, "pause_ratio": 0.21},
                            means=means)
        prompt = sent["user"]
        self.assertIn("pace: faster than your average", prompt)
        self.assertIn("pausing: about your average", prompt)
        for raw in ("187", "140", "0.21", "0.2"):
            self.assertNotIn(raw, prompt)


if __name__ == "__main__":
    unittest.main()
