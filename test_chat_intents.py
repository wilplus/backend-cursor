"""services.chat_intents — deterministic Lounge-bot intercepts.

Pure (no LLM / no flask), so they run in the lean env. Locks the precedence
and the false-positive guards (normal speaking-nerves stays coachable; whole-
speech writing is NOT caught here).

Run: python3 -m unittest test_chat_intents
"""
from __future__ import annotations

import unittest

from services.chat_intents import detect_chat_intent


class CrisisTests(unittest.TestCase):
    def test_panic_attack_redirects_safely(self):
        r = detect_chat_intent("I'm having a panic attack right now")
        self.assertIsNotNone(r)
        self.assertEqual(r["intent"], "crisis")
        self.assertFalse(r["show_record_ui"])
        self.assertIsNone(r["suggested_action"])
        # empathetic + an emergency pointer, never a record CTA
        self.assertRegex(r["answer"].lower(), r"emergency|professional|trust")

    def test_self_harm_phrases(self):
        for m in ("I feel suicidal", "I want to die before this talk",
                  "I keep thinking about hurting myself"):
            self.assertEqual(detect_chat_intent(m)["intent"], "crisis", m)

    def test_normal_nerves_is_NOT_crisis(self):
        # Ordinary speaking anxiety must stay coachable (→ falls through to LLM).
        for m in ("I panic before presentations",
                  "my voice shakes, what can I do?",
                  "I'm scared of public speaking"):
            self.assertIsNone(detect_chat_intent(m), m)


class RecordIntentTests(unittest.TestCase):
    def test_readiness_gets_the_cta(self):
        r = detect_chat_intent("I want to get better, how do I get started?")
        self.assertEqual(r["intent"], "record_intent")
        self.assertTrue(r["show_record_ui"])
        self.assertEqual(r["suggested_action"], "record_again")

    def test_explicit_record_intent(self):
        for m in ("Can I record here?", "let me record my talk",
                  "I'm ready", "start recording", "record again",
                  "I want to record it now"):
            r = detect_chat_intent(m)
            self.assertEqual(r["intent"], "record_intent", m)
            self.assertTrue(r["show_record_ui"], m)

    def test_product_question_is_NOT_record_intent(self):
        # Questions ABOUT recording aren't readiness — let the LLM answer.
        for m in ("how does recording work?",
                  "what happens to my recording after I send it?"):
            self.assertIsNone(detect_chat_intent(m), m)


class GenerativeTests(unittest.TestCase):
    def test_off_mission_generative_deflects(self):
        for m in ("write me a haiku", "tell me a joke",
                  "write a short story about a dog", "compose a song"):
            r = detect_chat_intent(m)
            self.assertEqual(r["intent"], "generative", m)
            self.assertFalse(r["show_record_ui"], m)

    def test_whole_speech_is_NOT_caught(self):
        # Ghost-writing a speech is declined by the LLM (with nuance), not here.
        for m in ("write me a speech for my wedding",
                  "can you write my presentation?"):
            self.assertIsNone(detect_chat_intent(m), m)


class PrecedenceAndEmptyTests(unittest.TestCase):
    def test_crisis_beats_record(self):
        # "I'm ready" reads as record, but distress wins.
        r = detect_chat_intent("I'm ready to end my life")
        self.assertEqual(r["intent"], "crisis")

    def test_empty_or_none(self):
        self.assertIsNone(detect_chat_intent(""))
        self.assertIsNone(detect_chat_intent("   "))
        self.assertIsNone(detect_chat_intent(None))

    def test_plain_question_passes_through(self):
        self.assertIsNone(detect_chat_intent("what is willab?"))


if __name__ == "__main__":
    unittest.main()
