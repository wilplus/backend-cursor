"""Deterministic output guards for the Lounge bot (RULE A + RULE K).

These test the POST-GENERATION floor in services/master_doc_rag.py —
the code that enforces the construct-prohibition (B1/AC-9) and the
library-dump prohibition (RULE K) on the model's OUTPUT, independent of
whether the prompt rule held. The guards are driven through
`answer_question` with the model call stubbed: NO LLM, NO network — this
is the part of the probe's guarantee that can run keyless in CI.

master_doc_rag imports services.will_voice (pure) + services.db lazily,
so a db stub keeps it import-safe in the lean env (same pattern as
test_library_bot_context — stub in setUpModule, RESTORE in tearDown).

Run: python3 -m unittest tests.test_master_doc_output_guards
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

    def test_flag_on_by_default(self):
        # founder 2026-06-25 — the router is now the DEFAULT (category decision
        # tree). A falsey env value forces the legacy mega-prompt path.
        import os
        from services.master_doc_rag import _router_enabled
        old = os.environ.pop("LOUNGE_ROUTER_ENABLED", None)
        try:
            self.assertTrue(_router_enabled())
        finally:
            if old is not None:
                os.environ["LOUNGE_ROUTER_ENABLED"] = old

    def test_flag_reads_env(self):
        import os
        from services.master_doc_rag import _router_enabled
        old = os.environ.get("LOUNGE_ROUTER_ENABLED")
        try:
            for v in ("1", "true", "YES", "on", "anything"):
                os.environ["LOUNGE_ROUTER_ENABLED"] = v
                self.assertTrue(_router_enabled(), v)
            for v in ("0", "false", "no", "off", "OFF"):
                os.environ["LOUNGE_ROUTER_ENABLED"] = v
                self.assertFalse(_router_enabled(), v)
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
        grounded = _build_lane_prompt("product_faq", "")
        self.assertIn("MASTER DOCUMENT", grounded)
        # an action lane stays focused — no full document
        action = _build_lane_prompt("record_intent", "")
        self.assertNotIn("MASTER DOCUMENT", action)

    def test_positive_moment_recall_routes_to_voice_album_without_collection(self):
        from services.master_doc_rag import _build_lane_prompt
        out = _build_lane_prompt("library_recall", "")
        self.assertIn("Voice Album", out)
        self.assertNotIn("LIBRARIAN", out)
        # The name is pinned verbatim in every language, and the lane never
        # offers the model the retired collection's name to reuse.
        self.assertIn('exactly "Voice Album"', out)
        self.assertIn("never translated", out)
        self.assertNotIn("Strong Sides", out)

    def test_navigation_names_stay_english_in_every_language(self):
        # Founder 2026-09-26: menu and button names are never translated.
        from services.master_doc_rag import _SYSTEM_PROMPT, _build_lane_prompt
        for prompt in (_SYSTEM_PROMPT, _build_lane_prompt("product_faq", "")):
            self.assertIn("stay in English exactly as", " ".join(prompt.split()))

    def test_mega_prompt_never_offers_the_retired_collection_name(self):
        from services.master_doc_rag import _SYSTEM_PROMPT
        self.assertIn('exactly "Voice Album"', _SYSTEM_PROMPT)
        self.assertNotIn("Strong Sides", _SYSTEM_PROMPT)

    def test_record_lane_points_to_official_recording(self):
        from services.master_doc_rag import _LANE_BODIES
        body = _LANE_BODIES["record_intent"]
        # record intent → point at the always-present button, no record_again
        self.assertIn("official recording", body.lower())
        self.assertNotIn("record_again", body)


class DeliverableHonestyPinTests(unittest.TestCase):
    """Founder 2026-07-17: the persona must promise what the product
    delivers (the ideal text of your own talk + your strongest moments),
    never immediate charisma / a confidence transformation / an anxiety
    cure. String-presence pins on BOTH personas (the mega-prompt and the
    router's product_faq lane) so a prompt trim can't silently drop the
    constraint."""

    @staticmethod
    def _flat(text):
        # The prompt literals concatenate with per-line indentation —
        # normalize runs of whitespace so pins can cross line joins.
        return " ".join(text.lower().split())

    def test_mega_prompt_carries_the_deliverable_framing(self):
        from services.master_doc_rag import _SYSTEM_PROMPT
        low = self._flat(_SYSTEM_PROMPT)
        self.assertIn("ideal text of their own talk", low)
        self.assertIn("strongest moments", low)
        self.assertIn("never promise immediate charisma", low)
        self.assertIn("journey", low)

    def test_router_faq_lane_carries_the_deliverable_framing(self):
        from services.master_doc_rag import _LANE_BODIES
        low = self._flat(_LANE_BODIES["product_faq"])
        self.assertIn("ideal text of their own talk", low)
        self.assertIn("strongest moments", low)
        self.assertIn("never promise immediate charisma", low)


if __name__ == "__main__":
    unittest.main()
