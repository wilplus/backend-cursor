"""Delivery–content alignment note (founder 2026-07-24 sign-off).

Pure tests of services/delivery_alignment.py — no app / DB / model import
(the model call is injected), so they run in CI. They lock the fences:
  * the flat-delivery GATE (down-lean only; up/neutral/high-arousal excluded),
  * the AC-9 guard on the surfaced line (no digits / construct words),
  * "words must be positive" (negative/neutral content never flagged),
  * one note per take, best-effort, flag-gated default off.

Run: python3 -m unittest test_delivery_alignment
"""
from __future__ import annotations

import os
import unittest

from services import delivery_alignment as da


def _piece(sid, pot=None, transcript="hi there", extra=None):
    m = {}
    if pot is not None:
        m["acoustic_read"] = {"potentiometer": pot}
    if extra:
        m.update(extra)
    return {"id": sid, "transcript": transcript, "metrics": m}


class GateTests(unittest.TestCase):
    def _ids(self, pieces):
        return [p["id"] for p in da.flat_delivery_candidates(pieces)]

    def test_only_down_lean_flattest_first(self):
        # potentiometer <= -0.35 is a candidate; ordered flattest (most
        # negative) first.
        pieces = [
            _piece("up", 0.6),        # charisma/up  → excluded
            _piece("flat", -0.8),     # clearly down → candidate
            _piece("mild", -0.5),     # down         → candidate
            _piece("neutral", -0.1),  # neutral band → excluded
            _piece("boundary", -0.35),  # exactly the boundary → candidate
        ]
        self.assertEqual(self._ids(pieces), ["flat", "mild", "boundary"])

    def test_high_arousal_and_up_are_never_candidates(self):
        # The masked-tension / genuine-excitement (high-arousal, up-lean) case
        # is out of scope by construction — a positive potentiometer never
        # qualifies, so we can never flag it.
        self.assertEqual(self._ids([_piece("a", 0.9), _piece("b", 0.4)]), [])

    def test_excludes_missing_read_and_empty_transcript(self):
        pieces = [
            _piece("no_read", None),                       # no acoustic_read
            _piece("no_text", -0.9, transcript="   "),     # down but no words
            {"id": "no_metrics", "transcript": "hi"},       # no metrics at all
            _piece("ok", -0.7),
        ]
        self.assertEqual(self._ids(pieces), ["ok"])

    def test_malformed_read_never_raises(self):
        pieces = [
            {"id": "bad1", "transcript": "hi", "metrics": {"acoustic_read": None}},
            {"id": "bad2", "transcript": "hi",
             "metrics": {"acoustic_read": {"potentiometer": "x"}}},
            _piece("ok", -0.9),
        ]
        self.assertEqual(self._ids(pieces), ["ok"])

    def test_empty_and_none_safe(self):
        self.assertEqual(da.flat_delivery_candidates([]), [])
        self.assertEqual(da.flat_delivery_candidates(None), [])


class ExtractNoteTests(unittest.TestCase):
    def test_positive_clean_note_passes(self):
        out = da.extract_note({
            "words_positive": True,
            "note": "You called this the best part, yet your voice dipped; worth a re-listen.",
        })
        self.assertIn("worth a re-listen", out)

    def test_words_not_positive_returns_none(self):
        self.assertIsNone(da.extract_note({"words_positive": False, "note": "anything"}))
        self.assertIsNone(da.extract_note({"note": "no flag key"}))

    def test_ac9_digit_is_killed(self):
        self.assertIsNone(da.extract_note(
            {"words_positive": True, "note": "You said it 3 times, worth a re-listen."}))

    def test_ac9_construct_vocab_is_killed(self):
        self.assertIsNone(da.extract_note(
            {"words_positive": True, "note": "Your charisma score dipped here."}))

    def test_empty_or_nonstring_note_returns_none(self):
        self.assertIsNone(da.extract_note({"words_positive": True, "note": "   "}))
        self.assertIsNone(da.extract_note({"words_positive": True, "note": None}))
        self.assertIsNone(da.extract_note("not a dict"))
        self.assertIsNone(da.extract_note(None))


class BuildMessagesTests(unittest.TestCase):
    def test_user_carries_transcript_system_carries_fences(self):
        system, user = da.build_messages("This is the best day ever")
        self.assertIn("This is the best day ever", user)
        # delivery read is words, never a number
        self.assertIn("flat", user.lower())
        # the fence rules are in the system prompt
        self.assertIn("words_positive", system)
        self.assertIn("NEVER a number", system)


class AnnotateTests(unittest.TestCase):
    """The orchestrator, with an injected chat_fn (no real model)."""

    def _positive(self, note="You lit up on paper here, yet your voice stayed low; give it another pass."):
        return lambda s, u: {"words_positive": True, "note": note}

    def test_stamps_flattest_positive_moment(self):
        calls = []
        def chat(s, u):
            calls.append(u)
            return {"words_positive": True,
                    "note": "The words are a high point; your voice held back, worth a re-listen."}
        pieces = [_piece("mild", -0.5, "great news"), _piece("flat", -0.9, "i am thrilled")]
        note = da.annotate_pieces_with_alignment(pieces, chat_fn=chat)
        self.assertIn("worth a re-listen", note)
        # flattest ("flat") gets the first shot and, being positive, is stamped
        flat = next(p for p in pieces if p["id"] == "flat")
        self.assertEqual(flat["metrics"]["delivery_alignment_note"], note)
        # one note per take → stopped after the first success (one call)
        self.assertEqual(len(calls), 1)
        # the milder piece is untouched
        mild = next(p for p in pieces if p["id"] == "mild")
        self.assertNotIn("delivery_alignment_note", mild["metrics"])

    def test_walks_past_non_positive_words_to_next_candidate(self):
        seq = [{"words_positive": False, "note": ""},
               {"words_positive": True,
                "note": "This reads exciting; your delivery stayed even, take another pass."}]
        def chat(s, u):
            return seq.pop(0)
        pieces = [_piece("flat", -0.9, "the numbers fell again"),  # flattest but negative words
                  _piece("mild", -0.5, "i love this")]
        note = da.annotate_pieces_with_alignment(pieces, chat_fn=chat)
        self.assertIn("take another pass", note)
        mild = next(p for p in pieces if p["id"] == "mild")
        self.assertEqual(mild["metrics"]["delivery_alignment_note"], note)

    def test_caps_model_calls_at_two(self):
        calls = []
        def chat(s, u):
            calls.append(u)
            return {"words_positive": False, "note": ""}
        pieces = [_piece(f"p{i}", -0.9 + i * 0.01, "yay") for i in range(5)]
        note = da.annotate_pieces_with_alignment(pieces, chat_fn=chat)
        self.assertIsNone(note)
        self.assertLessEqual(len(calls), da._MAX_LLM_ATTEMPTS)

    def test_no_flat_candidate_never_calls_model(self):
        calls = []
        def chat(s, u):
            calls.append(u)
            return self._positive()(s, u)
        note = da.annotate_pieces_with_alignment(
            [_piece("up", 0.7, "great"), _piece("neutral", -0.1, "great")], chat_fn=chat)
        self.assertIsNone(note)
        self.assertEqual(calls, [])

    def test_model_failure_is_best_effort(self):
        def chat_none(s, u):
            return None
        def chat_raises(s, u):
            raise RuntimeError("boom")
        pieces = [_piece("flat", -0.9, "i am so happy")]
        self.assertIsNone(da.annotate_pieces_with_alignment(pieces, chat_fn=chat_none))
        self.assertIsNone(da.annotate_pieces_with_alignment(pieces, chat_fn=chat_raises))
        self.assertNotIn("delivery_alignment_note", pieces[0]["metrics"])

    def test_guarded_note_is_not_stamped(self):
        # model returns a positive verdict but a fence-violating line → nothing
        # stamped (silence beats an unguarded line).
        def chat(s, u):
            return {"words_positive": True, "note": "Your stress score was high here."}
        pieces = [_piece("flat", -0.9, "wonderful")]
        self.assertIsNone(da.annotate_pieces_with_alignment(pieces, chat_fn=chat))
        self.assertNotIn("delivery_alignment_note", pieces[0]["metrics"])


class FlagTests(unittest.TestCase):
    def test_default_off_and_env_toggle(self):
        old = os.environ.pop("DELIVERY_ALIGNMENT_ENABLED", None)
        try:
            self.assertFalse(da.delivery_alignment_enabled())
            os.environ["DELIVERY_ALIGNMENT_ENABLED"] = "1"
            self.assertTrue(da.delivery_alignment_enabled())
            os.environ["DELIVERY_ALIGNMENT_ENABLED"] = "false"
            self.assertFalse(da.delivery_alignment_enabled())
        finally:
            os.environ.pop("DELIVERY_ALIGNMENT_ENABLED", None)
            if old is not None:
                os.environ["DELIVERY_ALIGNMENT_ENABLED"] = old


if __name__ == "__main__":
    unittest.main()
