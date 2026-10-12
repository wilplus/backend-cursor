"""Per-slide word-level transcript split (#6). Pure — no network.

Run: python3 -m unittest tests.test_slide_word_split
"""
from __future__ import annotations

import unittest

from services.slide_word_split import slice_words_for_window, split_words_by_slides


def _w(word, start, end):
    return {"word": word, "start": start, "end": end}


SLIDES = [{"title": "S1", "body": ""}, {"title": "S2", "body": ""}]
# slide 0 from t=0, slide 1 from t=5s.
ADV = [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 5000}]


class SplitWordsBySlidesTests(unittest.TestCase):

    def test_fragment_audio_span_from_word_times(self):
        words = [_w("a", 6.0, 6.2), _w("b", 6.8, 7.5)]  # all slide 1
        frags = split_words_by_slides(words, ADV, SLIDES)
        self.assertEqual(len(frags), 1)
        f = frags[0]
        self.assertEqual(f["slide_index"], 1)
        self.assertEqual(f["start_offset_ms"], 6000)
        self.assertEqual(f["duration_ms"], 1500)  # 7.5s - 6.0s


    def test_no_words_or_slides_returns_empty(self):
        self.assertEqual(split_words_by_slides([], ADV, SLIDES), [])
        self.assertEqual(split_words_by_slides(None, ADV, SLIDES), [])
        self.assertEqual(split_words_by_slides([_w("x", 0, 1)], ADV, []), [])


    def test_blank_and_malformed_words_skipped(self):
        words = [_w("   ", 0.0, 0.2), "nope", {"word": "ok", "start": 0.3, "end": 0.5}]
        frags = split_words_by_slides(words, ADV, SLIDES)
        self.assertEqual(frags[0]["transcript"], "ok")


class BuildSlideTranscriptsTests(unittest.TestCase):
    """build_slide_transcripts (#A) — COMPLETE per-slide transcript from the
    whole-recording word list, one entry per deck slide."""

    def _f(self, *args, **kw):
        from services.slide_word_split import build_slide_transcripts
        return build_slide_transcripts(*args, **kw)


    def test_empty_slide_is_present_with_blank_transcript(self):
        # Nothing said on slide 1 → it still appears, empty (truthful 1:1).
        words = [_w("only", 0.0, 0.5), _w("here", 0.6, 1.0)]  # all slide 0
        out = self._f(words, ADV, SLIDES)
        self.assertEqual(out[0]["transcript"], "only here")
        self.assertEqual(out[1]["transcript"], "")
        self.assertIsNone(out[1]["start_offset_ms"])


    def test_no_slides_returns_empty(self):
        self.assertEqual(self._f([_w("x", 0, 1)], ADV, []), [])


class SliceWordsForWindowTests(unittest.TestCase):


    def test_empty_safe(self):
        self.assertEqual(slice_words_for_window(None, 0, 1000), [])
        self.assertEqual(slice_words_for_window([], 0, 1000), [])


class SnapBoundariesToPausesTests(unittest.TestCase):
    """The pure pause-snap helper (clock-offset robustness)."""

    def _snap(self, advances, words, window_ms=1200, min_gap_ms=200):
        from services.slide_word_split import _snap_boundaries_to_pauses
        return _snap_boundaries_to_pauses(
            advances, words, window_ms=window_ms, min_gap_ms=min_gap_ms)


    def test_no_snap_when_no_pause_near(self):
        words = [_w("a", 0.0, 0.4), _w("b", 0.5, 0.9),
                 _w("c", 1.4, 1.8), _w("d", 1.9, 2.3)]
        # tap far from the only pause (|1150-5000| > window) → unchanged
        out = self._snap([{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 5000}], words)
        self.assertEqual(out[1]["t_ms"], 5000)

    def test_tiny_gaps_dont_qualify(self):
        # all inter-word gaps < min_gap_ms → no snap (normal speech rhythm)
        words = [_w("a", 0.0, 0.4), _w("b", 0.45, 0.85), _w("c", 0.9, 1.3)]
        out = self._snap([{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 900}], words)
        self.assertEqual(out[1]["t_ms"], 900)


    def test_empty_safe(self):
        self.assertEqual(self._snap(None, [_w("a", 0, 1)]), None)
        self.assertEqual(self._snap([{"index": 0, "t_ms": 0}], None),
                         [{"index": 0, "t_ms": 0}])


class ChunkWordsByCharsTests(unittest.TestCase):
    """Deckless chunking v2 (founder 2026-07-11): ≤200-char pieces broken at
    word boundaries, each with its audio span from the word timestamps."""

    def _chunk(self, words, max_chars=None):
        from services.slide_word_split import chunk_words_by_chars
        if max_chars is None:
            return chunk_words_by_chars(words)
        return chunk_words_by_chars(words, max_chars)


    def test_word_longer_than_cap_gets_own_chunk(self):
        out = self._chunk([
            _w("hi", 0.0, 0.2),
            _w("supercalifragilistic", 0.3, 1.5),
            _w("ok", 1.6, 1.8),
        ], max_chars=10)
        self.assertEqual([c["transcript"] for c in out],
                         ["hi", "supercalifragilistic", "ok"])


class ChunkTranscriptByCharsTests(unittest.TestCase):
    """Text-only fallback for legacy single-blob deckless persists."""

    def _chunk(self, text, max_chars=None):
        from services.slide_word_split import chunk_transcript_by_chars
        if max_chars is None:
            return chunk_transcript_by_chars(text)
        return chunk_transcript_by_chars(text, max_chars)

    def test_empty_or_blank_returns_empty(self):
        self.assertEqual(self._chunk(""), [])
        self.assertEqual(self._chunk(None), [])
        self.assertEqual(self._chunk("   "), [])


class DecklessChunksFromStxTests(unittest.TestCase):
    """The shared canonical chunk list (readout fold + edit-route bound)."""

    def _f(self, stx):
        from services.slide_word_split import deckless_chunks_from_stx
        return deckless_chunks_from_stx(stx)

    def test_new_style_multi_entry_returned_with_spans(self):
        stx = [
            {"index": 0, "transcript": "part one",
             "start_offset_ms": 0, "duration_ms": 3000},
            {"index": 1, "transcript": "part two",
             "start_offset_ms": 3200, "duration_ms": 2500},
        ]
        out = self._f(stx)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[1]["transcript"], "part two")
        self.assertEqual(out[1]["start_offset_ms"], 3200)


    def test_legacy_long_blob_rechunks_without_spans(self):
        blob = " ".join(f"word{i}" for i in range(80))  # >> 200 chars
        stx = [{"index": 0, "transcript": blob,
                "start_offset_ms": 0, "duration_ms": 60000}]
        out = self._f(stx)
        self.assertGreater(len(out), 1)
        self.assertNotIn("start_offset_ms", out[0])  # no fake spans
        self.assertEqual(" ".join(c["transcript"] for c in out), blob)


class SplitRunonSentencesTests(unittest.TestCase):
    """Run-on sentence boundaries (founder BE-1c, 2026-07-16): a real pause
    after an already-long sentence is promoted to a full stop — punctuation +
    casing only, words + spans strictly untouched."""

    def _stream(self, groups, gap_s=0.8):
        """Words at a tight 0.1s rhythm; a ``gap_s`` pause between groups."""
        words, t = [], 0.0
        for gi, group in enumerate(groups):
            if gi:
                t += gap_s
            for tok in group.split():
                words.append({"word": tok, "start": round(t, 2),
                              "end": round(t + 0.3, 2)})
                t = round(t + 0.4, 2)
        return words

    def _split(self, groups, gap_s=0.8, **kw):
        from services.slide_word_split import split_runon_sentences
        kw.setdefault("min_gap_ms", 500)
        kw.setdefault("min_chars", 40)
        return split_runon_sentences(self._stream(groups, gap_s), **kw)

    def _text(self, out):
        return " ".join(w["word"] for w in out)


    def test_empty_safe(self):
        from services.slide_word_split import split_runon_sentences
        self.assertEqual(split_runon_sentences(None), [])
        self.assertEqual(split_runon_sentences([]), [])


    def test_chunker_closes_at_the_promoted_boundary(self):
        # The end-to-end win: the sentence-aware cutter can now close a piece
        # at the promoted period instead of running to the hard cap.
        long_a = ("we spent the whole quarter rebuilding the pipeline and "
                  "the team pushed through every single blocker on the list")
        long_b = ("the next quarter is where all of that work finally starts "
                  "paying off for every customer we have")
        out = self._split([long_a, long_b])
        from services.slide_word_split import chunk_words_by_chars
        pieces = chunk_words_by_chars(out, 110)
        self.assertTrue(pieces[0]["transcript"].endswith("list."))
        self.assertTrue(pieces[1]["transcript"].startswith("The next"))


if __name__ == "__main__":
    unittest.main()
