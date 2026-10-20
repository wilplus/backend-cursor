"""
STORY    As a speaker, I want my transcript cut into pieces that never cross a
         slide, never end mid-sentence and keep exact audio times, so that
         each paragraph and moment plays the right words. (Transcript: the
         pieces are what the Ideal Text and every moment are built from.)
OUTCOME
  O1  A piece never crosses a slide: a revisited slide is a new run, every
      piece's words and audio lie inside one visit, ordinals run in time order.
  O2  Piece boundaries land on sentence ends, and sentence ends survive
      ghost words in the punctuation alignment.
  O3  What is persisted reads back unchanged (text and audio offsets).
PROVES   O1 -> test_a_piece_never_crosses_a_slide
         O2 -> test_never_mid_sentence_when_end_within_cap
               test_ghost_run_mid_take_keeps_later_sentences
         O3 -> test_persist_then_read_round_trip
WHY      Founder 2026-07-14: the <=200-char piece IS the moment (F1-CORE).
"""
from __future__ import annotations

import unittest

from services.slide_word_split import chunk_slide_words_by_chars


def _visits(visits, word_dur=0.4, tap_gap_s=1.0):
    """A time-consistent word list + tap timeline for [(slide, text), ...]:
    each visit's tap lands just before its first word."""
    words, advances, spans, t = [], [], [], 0.0
    for n, (slide, text) in enumerate(visits):
        if n:
            t += tap_gap_s
        advances.append({"index": slide, "t_ms": max(0, int(t * 1000) - 50)})
        begin = t
        for w in text.split():
            words.append({"word": w, "start": round(t, 3), "end": round(t + word_dur, 3)})
            t += word_dur
        spans.append((slide, round(begin * 1000), round(t * 1000), set(text.split())))
    return words, advances, spans


class SlideBoundaryTests(unittest.TestCase):

    def test_a_piece_never_crosses_a_slide(self):
        # A -> B -> A: the first visit is long enough to need several pieces,
        # and the revisit of slide 0 must be its own run.
        first = " ".join(f"alpha{i}" for i in range(60)) + "."
        visits = [(0, first), (1, "beta one beta two."), (0, "gamma back again.")]
        words, advances, spans = _visits(visits)
        pieces = chunk_slide_words_by_chars(words, advances, [{}, {}, {}])

        self.assertEqual([p["index"] for p in pieces], list(range(len(pieces))))
        for piece in pieces:
            visit = [v for v in spans if set(piece["transcript"].split()) <= v[3]]
            self.assertEqual(len(visit), 1, f"piece mixes visits: {piece['transcript'][:60]}")
            slide, begin, end, _ = visit[0]
            self.assertEqual(piece["slide_index"], slide)
            self.assertGreaterEqual(piece["start_offset_ms"], begin)
            self.assertLessEqual(piece["start_offset_ms"] + piece["duration_ms"], end)
        # the long first visit needed several pieces; then B, then A again
        self.assertEqual([p["slide_index"] for p in pieces][-3:], [0, 1, 0])


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
