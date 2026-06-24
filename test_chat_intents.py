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


class NoRecordInterceptTests(unittest.TestCase):
    def test_record_or_readiness_falls_through_to_the_llm(self):
        # Deliberately NO record-CTA intercept (pulled 2026-06-21). Record /
        # readiness intent is the LLM's RULE I: point to the always-present
        # "Start official recording" button — no mic, no suggested_action. So
        # none of these are intercepted here.
        for m in ("I want to get better, how do I get started?",
                  "Can I record here?", "let me record my talk",
                  "I'm ready", "start recording", "record again",
                  "how does recording work?"):
            self.assertIsNone(detect_chat_intent(m), m)


class GenerativeTests(unittest.TestCase):
    def test_off_mission_generative_deflects(self):
        # jokes are no longer here — they RETURN now (DadJokeTests).
        for m in ("write me a haiku", "write a short story about a dog",
                  "compose a song", "recite a poem"):
            r = detect_chat_intent(m)
            self.assertEqual(r["intent"], "generative", m)
            self.assertFalse(r["show_record_ui"], m)

    def test_whole_speech_is_NOT_caught(self):
        # Ghost-writing a speech is declined by the LLM (with nuance), not here.
        for m in ("write me a speech for my wedding",
                  "can you write my presentation?"):
            self.assertIsNone(detect_chat_intent(m), m)


class DadJokeTests(unittest.TestCase):
    def test_joke_requests_return_a_dad_joke(self):
        from services.dad_jokes import DAD_JOKES
        for m in ("tell me a joke", "got a dad joke?", "a bad joke please",
                  "crack a joke", "make me laugh", "another joke",
                  "yes, give me that bad joke"):
            r = detect_chat_intent(m)
            self.assertEqual(r["intent"], "dad_joke", m)
            self.assertIn(r["answer"], DAD_JOKES, m)
            self.assertFalse(r["show_record_ui"], m)
            self.assertIsNone(r["suggested_action"], m)

    def test_dad_joke_beats_generative(self):
        # precedence: a "joke" request returns, it does NOT deflect.
        self.assertEqual(detect_chat_intent("write me a joke")["intent"],
                         "dad_joke")


class PrecedenceAndEmptyTests(unittest.TestCase):
    def test_distress_with_ready_phrasing_is_crisis(self):
        # "I'm ready" is no longer a record trigger; distress still fires.
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
