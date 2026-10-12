"""willab — pieces-canonical core (founder 2026-07-14): the ≤200-char piece
IS the moment.

Covers the F1-CORE cutter (services/slide_word_split.chunk_slide_words_by_chars):
slide boundary FIRST (a piece never crosses a slide), ≤200 chars within the
slide, exact word-derived audio spans, global ordinals — and the drafter's
two-tier budget dispatch (LLM for the budget set, deterministic auto-comment
for the rest, same write-once lane).

Run: python3 -m unittest tests.test_pieces_canonical
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
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)


def _words(text_per_slide, word_dur=0.4, tap_gap_s=1.0):
    """Build a time-consistent whisper word list + tap timeline: each slide's
    tap lands after the previous slide's last word, then its words follow —
    one every `word_dur`s (no overlap between slides, like real speech)."""
    words, advances = [], []
    t = 0.0
    for i, text in enumerate(text_per_slide):
        if i > 0:
            t += tap_gap_s
            advances.append({"index": i, "t_ms": int(t * 1000) - 50})
        for w in text.split():
            words.append({"word": w, "start": round(t, 3),
                          "end": round(t + word_dur, 3)})
            t += word_dur
        if not text.split():
            t += tap_gap_s  # silent slide still occupies a beat
    advances.insert(0, {"index": 0, "t_ms": 0})
    return words, advances


class RestorePunctuationTests(unittest.TestCase):
    """BE-1a (founder 2026-07-15): deterministic segment→word punctuation
    alignment, ghost-word-proof."""

    def _words(self, tokens, t0=0.0, dur=0.4):
        return [{"word": w, "start": round(t0 + i * dur, 2),
                 "end": round(t0 + i * dur + dur, 2)}
                for i, w in enumerate(tokens)]

    def _restore(self, word_tokens, seg_text):
        from services.slide_word_split import restore_punctuation
        words = self._words(word_tokens)
        segs = [{"text": seg_text, "start": 0, "end": 99}]
        return restore_punctuation(words, segs)


        # (both the think-comma and the ghost's comma carry — punctuation is
        # never LOST; cosmetic doubling is acceptable and rare)


    def test_ghost_run_mid_take_keeps_later_sentences(self):
        # The reviewer's second repro: 4 ghosts mid-stream must not kill the
        # later sentence breaks.
        out = self._restore(
            ["we", "grow", "fast", "and", "then", "we", "scale"],
            "We grow, uh, um, well, like, fast. And then we scale.")
        words = [w["word"] for w in out]
        self.assertEqual(words[-1], "scale.")
        self.assertIn("fast.", words)


class DecklessReadBackTests(unittest.TestCase):
    """REVIEW-CONFIRMED bug (2026-07-15): the read-back legacy-blob probe at
    the 200 target re-split a legit single sentence-extended piece into
    span-less phantom chunks. The probe now uses the HARD cap (300)."""


    def test_persist_then_read_round_trip(self):
        # END-TO-END: the persist-time cutter's own output must round-trip
        # through the read-back helper unchanged (the drift the review
        # flagged for edit indexes / card attachment).
        from services.slide_word_split import (
            chunk_words_by_chars,
            deckless_chunks_from_stx,
        )
        words, t = [], 0.0
        for i in range(48):
            w = "tok" + ("." if i == 47 else "")
            words.append({"word": w, "start": round(t, 2),
                          "end": round(t + 0.3, 2)})
            t += 0.3
        persisted = chunk_words_by_chars(words)   # one ~235-char piece
        read_back = deckless_chunks_from_stx(persisted)
        self.assertEqual(len(read_back), len(persisted))
        for a, b in zip(persisted, read_back):
            self.assertEqual(a["transcript"], b["transcript"])
            self.assertEqual(a["start_offset_ms"], b["start_offset_ms"])


class SentenceAwareChunkTests(unittest.TestCase):
    """BE-1b (founder 2026-07-15): pieces never end mid-sentence; target 200,
    sentence extension to the 300 hard cap (founder-locked '300')."""

    def _words_from_sentences(self, sentences, dur=0.3):
        words, t = [], 0.0
        for s in sentences:
            for w in s.split():
                words.append({"word": w, "start": round(t, 2),
                              "end": round(t + dur, 2)})
                t += dur
        return words

    def _cut(self, sentences, max_chars=200):
        from services.slide_word_split import chunk_words_by_chars
        return chunk_words_by_chars(
            self._words_from_sentences(sentences), max_chars)


    def test_never_mid_sentence_when_end_within_cap(self):
        # Several short sentences: every piece boundary lands on a sentence
        # end (no piece ends mid-sentence).
        sentences = [(" ".join(["tok"] * 12) + ".") for _ in range(8)]
        pieces = self._cut(sentences)
        for p in pieces[:-1]:
            self.assertTrue(p["transcript"].rstrip().endswith("."),
                            f"mid-sentence cut: …{p['transcript'][-30:]}")


if __name__ == "__main__":
    unittest.main()
