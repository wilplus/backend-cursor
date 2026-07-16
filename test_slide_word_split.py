"""Per-slide word-level transcript split (#6). Pure — no network.

Run: python3 -m unittest test_slide_word_split
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
    def test_splits_at_the_click_boundary(self):
        # "hi there" before the click (t<5s), "now go" after → two slides.
        words = [_w("hi", 0.0, 0.5), _w("there", 0.6, 1.0),
                 _w("now", 6.0, 6.4), _w("go", 6.5, 7.0)]
        frags = split_words_by_slides(words, ADV, SLIDES)
        self.assertEqual(len(frags), 2)
        self.assertEqual(frags[0]["slide_index"], 0)
        self.assertEqual(frags[0]["transcript"], "hi there")
        self.assertEqual(frags[1]["slide_index"], 1)
        self.assertEqual(frags[1]["transcript"], "now go")

    def test_fragment_audio_span_from_word_times(self):
        words = [_w("a", 6.0, 6.2), _w("b", 6.8, 7.5)]  # all slide 1
        frags = split_words_by_slides(words, ADV, SLIDES)
        self.assertEqual(len(frags), 1)
        f = frags[0]
        self.assertEqual(f["slide_index"], 1)
        self.assertEqual(f["start_offset_ms"], 6000)
        self.assertEqual(f["duration_ms"], 1500)  # 7.5s - 6.0s

    def test_word_before_first_advance_clamps_to_slide_0(self):
        adv = [{"index": 0, "t_ms": 2000}, {"index": 1, "t_ms": 5000}]
        words = [_w("early", 0.5, 0.9)]  # before the first advance t_ms
        frags = split_words_by_slides(words, adv, SLIDES)
        self.assertEqual(frags[0]["slide_index"], 0)

    def test_three_way_split_back_and_forth(self):
        # slide0 → slide1 → (clicked back? no) — model: index follows timeline.
        adv = [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 3000},
               {"index": 0, "t_ms": 6000}]
        words = [_w("one", 1.0, 1.2), _w("two", 4.0, 4.2), _w("three", 7.0, 7.2)]
        frags = split_words_by_slides(words, adv, [SLIDES[0], SLIDES[1]])
        self.assertEqual([f["slide_index"] for f in frags], [0, 1, 0])

    def test_no_timeline_returns_empty_for_fallback(self):
        words = [_w("hi", 0.0, 0.5)]
        self.assertEqual(split_words_by_slides(words, None, SLIDES), [])
        self.assertEqual(split_words_by_slides(words, [], SLIDES), [])

    def test_no_words_or_slides_returns_empty(self):
        self.assertEqual(split_words_by_slides([], ADV, SLIDES), [])
        self.assertEqual(split_words_by_slides(None, ADV, SLIDES), [])
        self.assertEqual(split_words_by_slides([_w("x", 0, 1)], ADV, []), [])

    def test_index_clamped_into_range(self):
        # advance names a slide index beyond the deck → clamp to last slide.
        adv = [{"index": 9, "t_ms": 0}]
        frags = split_words_by_slides([_w("x", 0, 1)], adv, SLIDES)
        self.assertEqual(frags[0]["slide_index"], 1)  # clamped to len-1

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

    def test_one_entry_per_slide_complete_split(self):
        words = [_w("hi", 0.0, 0.5), _w("there", 0.6, 1.0),
                 _w("now", 6.0, 6.4), _w("go", 6.5, 7.0)]
        out = self._f(words, ADV, SLIDES)
        self.assertEqual([e["index"] for e in out], [0, 1])
        self.assertEqual(out[0]["transcript"], "hi there")
        self.assertEqual(out[1]["transcript"], "now go")

    def test_quiet_first_slide_still_caught(self):
        # The fix: even if the first slide's words weren't a salient snippet,
        # they're bucketed here from the whole-recording word list.
        words = [_w("welcome", 1.0, 1.5),                     # slide 0
                 _w("the", 6.0, 6.2), _w("pitch", 6.3, 6.8)]  # slide 1
        out = self._f(words, ADV, SLIDES)
        self.assertEqual(out[0]["transcript"], "welcome")   # NOT empty/shifted
        self.assertEqual(out[1]["transcript"], "the pitch")

    def test_empty_slide_is_present_with_blank_transcript(self):
        # Nothing said on slide 1 → it still appears, empty (truthful 1:1).
        words = [_w("only", 0.0, 0.5), _w("here", 0.6, 1.0)]  # all slide 0
        out = self._f(words, ADV, SLIDES)
        self.assertEqual(out[0]["transcript"], "only here")
        self.assertEqual(out[1]["transcript"], "")
        self.assertIsNone(out[1]["start_offset_ms"])

    def test_revisited_slide_collects_all_words_in_time_order(self):
        adv = [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 3000},
               {"index": 0, "t_ms": 6000}]
        words = [_w("a", 1.0, 1.2), _w("b", 4.0, 4.2), _w("c", 7.0, 7.2)]
        out = self._f(words, adv, SLIDES)
        self.assertEqual(out[0]["transcript"], "a c")  # both slide-0 visits
        self.assertEqual(out[1]["transcript"], "b")

    def test_span_from_word_times(self):
        words = [_w("x", 6.0, 6.2), _w("y", 6.8, 7.5)]  # slide 1
        out = self._f(words, ADV, SLIDES)
        self.assertEqual(out[1]["start_offset_ms"], 6000)
        self.assertEqual(out[1]["duration_ms"], 1500)

    def test_no_slides_returns_empty(self):
        self.assertEqual(self._f([_w("x", 0, 1)], ADV, []), [])

    def test_no_words_returns_all_empty_slides(self):
        out = self._f([], ADV, SLIDES)
        self.assertEqual([e["transcript"] for e in out], ["", ""])
        self.assertEqual([e["index"] for e in out], [0, 1])


class SliceWordsForWindowTests(unittest.TestCase):
    def test_overlap_window(self):
        words = [_w("a", 0.0, 0.5), _w("b", 1.0, 1.5), _w("c", 3.0, 3.5)]
        # window [800ms, 2000ms] → only "b" overlaps
        got = slice_words_for_window(words, 800, 2000)
        self.assertEqual([w["word"] for w in got], ["b"])

    def test_partial_overlap_included(self):
        words = [_w("edge", 1.9, 2.4)]  # starts before 2000ms end, ends after
        got = slice_words_for_window(words, 0, 2000)
        self.assertEqual(len(got), 1)

    def test_empty_safe(self):
        self.assertEqual(slice_words_for_window(None, 0, 1000), [])
        self.assertEqual(slice_words_for_window([], 0, 1000), [])


class SnapBoundariesToPausesTests(unittest.TestCase):
    """The pure pause-snap helper (clock-offset robustness)."""

    def _snap(self, advances, words, window_ms=1200, min_gap_ms=200):
        from services.slide_word_split import _snap_boundaries_to_pauses
        return _snap_boundaries_to_pauses(
            advances, words, window_ms=window_ms, min_gap_ms=min_gap_ms)

    def test_snaps_boundary_into_the_pause(self):
        # gap 0.9s→1.4s (500ms, midpoint 1150ms); tap logged at 1300ms (offset)
        words = [_w("a", 0.0, 0.4), _w("b", 0.5, 0.9),
                 _w("c", 1.4, 1.8), _w("d", 1.9, 2.3)]
        out = self._snap([{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 1300}], words)
        self.assertEqual(out[1]["t_ms"], 1150)     # snapped to the gap midpoint
        self.assertEqual(out[1]["index"], 1)       # index preserved
        self.assertEqual(out[0]["t_ms"], 0)        # start never moved

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

    def test_two_close_taps_dont_collapse(self):
        # one pause at 1150; two taps at 1300 & 1320 — only the nearer snaps, the
        # other is clamped out (can't reuse the same gap → no reorder/collapse).
        words = [_w("a", 0.0, 0.4), _w("b", 0.5, 0.9),
                 _w("c", 1.4, 1.8), _w("d", 1.9, 2.3)]
        out = self._snap(
            [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 1300},
             {"index": 2, "t_ms": 1320}], words)
        self.assertEqual(out[1]["t_ms"], 1150)
        self.assertEqual(out[2]["t_ms"], 1320)     # clamped, stays put
        self.assertLess(out[1]["t_ms"], out[2]["t_ms"])  # still ordered

    def test_back_nav_preserves_indices(self):
        # forward → back → forward; t_ms monotonic, index non-monotonic
        words = [_w("a", 0.0, 0.4), _w("b", 0.5, 0.9),
                 _w("c", 1.4, 1.8)]
        adv = [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 1300},
               {"index": 0, "t_ms": 9000}]
        out = self._snap(adv, words)
        self.assertEqual([a["index"] for a in out], [0, 1, 0])  # indices intact

    def test_empty_safe(self):
        self.assertEqual(self._snap(None, [_w("a", 0, 1)]), None)
        self.assertEqual(self._snap([{"index": 0, "t_ms": 0}], None),
                         [{"index": 0, "t_ms": 0}])


class PauseSnapIntegrationTests(unittest.TestCase):
    """build_slide_transcripts honours the flag end-to-end and fixes the leak."""

    # tap logged at 2000ms; warm-up makes the new slide's first word "the"
    # appear at 1.85s → without snap it leaks onto slide 0. A 0.9→1.85s pause
    # sits between, so snapping moves the boundary to 1375ms and "the" lands on
    # slide 1.
    WORDS = [_w("we", 0.0, 0.4), _w("begin", 0.5, 0.9),
             _w("the", 1.85, 2.2), _w("pitch", 2.3, 2.7)]
    ADV2 = [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 2000}]

    def _build(self):
        from services.slide_word_split import build_slide_transcripts
        out = build_slide_transcripts(self.WORDS, self.ADV2, SLIDES)
        return {t["index"]: t["transcript"] for t in out}

    def test_flag_off_is_unchanged_and_leaks(self):
        import unittest.mock as mock
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("SLIDE_PAUSE_SNAP_ENABLED", None)
            tx = self._build()
        self.assertEqual(tx[0], "we begin the")   # "the" leaked onto slide 0
        self.assertEqual(tx[1], "pitch")

    def test_flag_on_snaps_and_fixes_the_leak(self):
        import unittest.mock as mock
        with mock.patch.dict("os.environ", {"SLIDE_PAUSE_SNAP_ENABLED": "1"}):
            tx = self._build()
        self.assertEqual(tx[0], "we begin")        # leak fixed
        self.assertEqual(tx[1], "the pitch")


class ChunkWordsByCharsTests(unittest.TestCase):
    """Deckless chunking v2 (founder 2026-07-11): ≤200-char pieces broken at
    word boundaries, each with its audio span from the word timestamps."""

    def _chunk(self, words, max_chars=None):
        from services.slide_word_split import chunk_words_by_chars
        if max_chars is None:
            return chunk_words_by_chars(words)
        return chunk_words_by_chars(words, max_chars)

    def test_empty_safe(self):
        self.assertEqual(self._chunk([]), [])
        self.assertEqual(self._chunk(None), [])

    def test_short_take_is_one_chunk_with_span(self):
        out = self._chunk([_w("we", 0.0, 0.4), _w("ship", 0.5, 0.9)])
        self.assertEqual(out, [{
            "index": 0, "transcript": "we ship",
            "start_offset_ms": 0, "duration_ms": 900,
        }])

    def test_splits_at_char_cap_never_mid_word(self):
        # "alpha beta" = 10 chars; cap 10 → "gamma" starts chunk 2.
        out = self._chunk([
            _w("alpha", 0.0, 0.5), _w("beta", 0.6, 1.0),
            _w("gamma", 1.2, 1.7),
        ], max_chars=10)
        self.assertEqual([c["transcript"] for c in out],
                         ["alpha beta", "gamma"])
        self.assertEqual(out[0]["start_offset_ms"], 0)
        self.assertEqual(out[0]["duration_ms"], 1000)
        self.assertEqual(out[1]["start_offset_ms"], 1200)
        self.assertEqual(out[1]["duration_ms"], 500)

    def test_word_longer_than_cap_gets_own_chunk(self):
        out = self._chunk([
            _w("hi", 0.0, 0.2),
            _w("supercalifragilistic", 0.3, 1.5),
            _w("ok", 1.6, 1.8),
        ], max_chars=10)
        self.assertEqual([c["transcript"] for c in out],
                         ["hi", "supercalifragilistic", "ok"])

    def test_no_text_dropped_or_reordered(self):
        words = [_w(f"w{i}", i * 0.5, i * 0.5 + 0.4) for i in range(120)]
        out = self._chunk(words)
        rebuilt = " ".join(c["transcript"] for c in out)
        self.assertEqual(rebuilt, " ".join(w["word"] for w in words))
        for c in out:
            # unpunctuated input cuts at the HARD cap (300 = 200+100,
            # founder-locked 2026-07-15); sentence-aware behavior is
            # covered in test_pieces_canonical.SentenceAwareChunkTests
            self.assertLessEqual(len(c["transcript"]), 300)
        # spans are monotonic — text and audio can't drift
        starts = [c["start_offset_ms"] for c in out]
        self.assertEqual(starts, sorted(starts))

    def test_out_of_order_words_sorted_by_time(self):
        out = self._chunk([_w("second", 1.0, 1.4), _w("first", 0.0, 0.4)])
        self.assertEqual(out[0]["transcript"], "first second")
        self.assertEqual(out[0]["start_offset_ms"], 0)


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

    def test_short_text_single_chunk(self):
        self.assertEqual(self._chunk("we begin"),
                         [{"index": 0, "transcript": "we begin"}])

    def test_word_boundary_split_and_no_loss(self):
        out = self._chunk("alpha beta gamma", max_chars=10)
        self.assertEqual([c["transcript"] for c in out],
                         ["alpha beta", "gamma"])
        text = " ".join(f"w{i}" for i in range(200))
        out = self._chunk(text)
        self.assertEqual(" ".join(c["transcript"] for c in out), text)
        for c in out:
            # unpunctuated input cuts at the HARD cap (300 = 200+100,
            # founder-locked 2026-07-15); sentence-aware behavior is
            # covered in test_pieces_canonical.SentenceAwareChunkTests
            self.assertLessEqual(len(c["transcript"]), 300)


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

    def test_single_short_entry_keeps_its_span(self):
        stx = [{"index": 0, "transcript": "short take",
                "start_offset_ms": 0, "duration_ms": 8000}]
        out = self._f(stx)
        self.assertEqual(out[0]["duration_ms"], 8000)

    def test_legacy_long_blob_rechunks_without_spans(self):
        blob = " ".join(f"word{i}" for i in range(80))  # >> 200 chars
        stx = [{"index": 0, "transcript": blob,
                "start_offset_ms": 0, "duration_ms": 60000}]
        out = self._f(stx)
        self.assertGreater(len(out), 1)
        self.assertNotIn("start_offset_ms", out[0])  # no fake spans
        self.assertEqual(" ".join(c["transcript"] for c in out), blob)

    def test_empty_safe(self):
        self.assertEqual(self._f([]), [])
        self.assertEqual(self._f(None), [])
        self.assertEqual(self._f([{"index": 0, "transcript": "  "}]), [])


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

    def test_comma_splice_upgrades_to_period(self):
        out = self._split(["you can train yourself to know what to say it,",
                           "can be trained on demand"])
        self.assertIn("say it. Can be trained", self._text(out))

    def test_unpunctuated_runon_gets_period_and_capital(self):
        out = self._split(["i think we should go build this thing right now",
                           "the next take will show it"])
        self.assertIn("right now. The next take", self._text(out))

    def test_short_pause_is_hesitation_not_a_boundary(self):
        groups = ["i think we should go build this thing right now",
                  "the next take will show it"]
        out = self._split(groups, gap_s=0.3)
        self.assertEqual(self._text(out), " ".join(groups))

    def test_short_sentence_left_alone(self):
        groups = ["we ship it,", "tomorrow morning at nine"]
        out = self._split(groups)
        self.assertEqual(self._text(out), " ".join(groups))

    def test_dangling_connective_blocks_the_split(self):
        # A pause after "the" is retrieval hesitation, never a period.
        groups = ["we should really go and think about all of the",
                  "options here"]
        out = self._split(groups)
        self.assertEqual(self._text(out), " ".join(groups))

    def test_existing_sentence_end_resets_not_doubled(self):
        groups = ["we finally did the whole thing everyone wanted done.",
                  "next we scale it"]
        out = self._split(groups)
        self.assertEqual(self._text(out), " ".join(groups))

    def test_period_stays_inside_closing_quote(self):
        out = self._split(['he said this is the best thing you can "say,"',
                           "then we moved on"])
        self.assertIn('"say." Then we', self._text(out))

    def test_words_and_spans_strictly_untouched(self):
        import re as _re
        words = self._stream(
            ["you can train yourself to know what to say it,",
             "can be trained on demand"])
        spans_before = [(w["start"], w["end"]) for w in words]
        norm_before = [_re.sub(r"[\W_]+", "", w["word"]).lower()
                       for w in words]
        from services.slide_word_split import split_runon_sentences
        out = split_runon_sentences(words, min_gap_ms=500, min_chars=40)
        self.assertEqual([(w["start"], w["end"]) for w in out], spans_before)
        self.assertEqual([_re.sub(r"[\W_]+", "", w["word"]).lower()
                          for w in out], norm_before)

    def test_empty_safe(self):
        from services.slide_word_split import split_runon_sentences
        self.assertEqual(split_runon_sentences(None), [])
        self.assertEqual(split_runon_sentences([]), [])

    def test_kill_switch_default_on_env_off(self):
        import unittest.mock as mock
        from services.slide_word_split import runon_split_enabled
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("SENTENCE_BOUNDARY_SPLIT_ENABLED", None)
            self.assertTrue(runon_split_enabled())
        with mock.patch.dict("os.environ",
                             {"SENTENCE_BOUNDARY_SPLIT_ENABLED": "0"}):
            self.assertFalse(runon_split_enabled())

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
