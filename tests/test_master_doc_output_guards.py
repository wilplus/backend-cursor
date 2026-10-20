"""
STORY    As a speaker, I want the Lounge chat bot never to tell me about scores,
         ratios, KPIs or retired collections, whatever the AI model wrote, so
         that what I read is in words and points me to the right place.
OUTCOME
  O1  An answer that mentions a score, ratio, KPI or classifier is replaced by
      a safe answer in words.
  O2  An answer that recreates the retired "Strong Sides" collection (in any
      language) is replaced by a pointer to Voice Album.
  O3  Ordinary answers pass through untouched.
PROVES   O1 -> ChatAnswerGuardTests::test_every_answer_leaves_through_the_guards
         O2 -> ChatAnswerGuardTests::test_every_answer_leaves_through_the_guards
         O3 -> ChatAnswerGuardTests::test_every_answer_leaves_through_the_guards
WHY      Never-rule 1 (RULE A / AC-9) and RULE K; no AI call is made in the test.
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


# A construct leak is replaced by the construct-safe answer; a recreated or
# named retired collection is replaced by the Voice Album bridge; benign
# prose passes untouched. Each row: (model output, guard expected or None).
_GUARD_CASES = (
    # RULE A / B1 / AC-9 — the retired scoring construct never survives.
    ("Your Threat:Challenge ratio came out strong this session.",
     "construct_leak"),
    ("Your T:C is trending up.", "construct_leak"),
    ("Your KPI for this take is 0.72.", "construct_leak"),
    ("Your charisma score went up.", "construct_leak"),
    ("The stress classifier flagged the opening.", "construct_leak"),
    # Both at once: the stronger guard (the construct) wins.
    ('coach noted: "your KPI is 0.9"', "construct_leak"),
    # RULE K — the retired Strong Sides collection is never recreated.
    ('Here they are: [strong] coach noted: "great open".',
     "retired_collection_dump"),
    ('coach noted: "watch the drop-off"', "retired_collection_dump"),
    ("Your best moments: [strong] the open, [strong] the close.",
     "retired_collection_dump"),
    # MDR-14 (2026-09-25): a Polish answer coined a "Strong Sides" collection.
    ('Twoje mocne strony są zebrane w kolekcji "Strong Sides", '
     "którą znajdziesz w menu.", "retired_collection_dump"),
    # False positives: benign prose passes UNTOUCHED.
    ("Speaking to a big room is a real challenge for most people.", None),
    ("Scores of speakers freeze up — you're not alone.", None),
    ("Catch your breath, watch your pace, and keep going.", None),
    ("The system is mostly human-led and scaled by AI — a real coach "
     "listens to your recordings and shapes what's next.", None),
    ("Your strong sides live in Voice Album in the menu.", None),
    ("I can't see any coach notes for you yet — record a take?", None),
)


class ChatAnswerGuardTests(unittest.TestCase):
    """The deterministic floor on what the Lounge bot SAYS, through
    `answer_question`, whatever the model returned (founder 2026-10-12: one
    contract test in place of fifteen tests of `_enforce_output_guards`)."""

    def test_every_answer_leaves_through_the_guards(self):
        import json
        import os
        from unittest.mock import patch

        from services.master_doc_rag import answer_question

        class _Response:
            def __init__(self, text):
                self.text = text

        for output, guard in _GUARD_CASES:
            with self.subTest(output=output), \
                    patch.dict(os.environ, {"LOUNGE_ROUTER_ENABLED": "0"}), \
                    patch("services.llm.chat_complete",
                          lambda **_kw: _Response(json.dumps({
                              "answer": output, "show_record_ui": False,
                              "suggested_action": "trainings"}))):
                payload, debug = answer_question("tell me about my talk")
            answer = payload["answer"]
            self.assertEqual(debug.get("output_guard"), guard)
            if guard is None:
                self.assertEqual(answer, output)
                self.assertEqual(payload["suggested_action"], "trainings")
            elif guard == "construct_leak":
                self.assertIn("Readout", answer)
                for leaked in ("threat", "t:c", "kpi", "charisma",
                               "classifier", "coach noted"):
                    self.assertNotIn(leaked, answer.lower())
            else:
                self.assertEqual(answer, "Your confirmed confident moments "
                                         "are in Voice Album in the menu.")
                self.assertIsNone(payload["suggested_action"])


if __name__ == "__main__":
    unittest.main()
