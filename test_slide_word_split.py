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


class ChunkTranscriptByWordsTests(unittest.TestCase):
    """Deckless full-transcript chunking (no click timeline → word-count
    chunks for the FE's single-artificial-slide stacked layout)."""

    def _chunk(self, text, chunk_size=None):
        from services.slide_word_split import chunk_transcript_by_words
        if chunk_size is None:
            return chunk_transcript_by_words(text)
        return chunk_transcript_by_words(text, chunk_size)

    def test_empty_or_blank_returns_empty(self):
        self.assertEqual(self._chunk(""), [])
        self.assertEqual(self._chunk(None), [])
        self.assertEqual(self._chunk("   "), [])

    def test_short_text_is_a_single_chunk(self):
        out = self._chunk("we begin the pitch", chunk_size=50)
        self.assertEqual(out, [{"index": 0, "transcript": "we begin the pitch"}])

    def test_splits_at_exact_chunk_size(self):
        words = [f"w{i}" for i in range(10)]
        out = self._chunk(" ".join(words), chunk_size=4)
        self.assertEqual([c["index"] for c in out], [0, 1, 2])
        self.assertEqual(out[0]["transcript"], "w0 w1 w2 w3")
        self.assertEqual(out[1]["transcript"], "w4 w5 w6 w7")
        self.assertEqual(out[2]["transcript"], "w8 w9")  # trailing remainder

    def test_words_never_reordered_or_dropped(self):
        words = [f"w{i}" for i in range(137)]
        out = self._chunk(" ".join(words), chunk_size=50)
        rebuilt = " ".join(c["transcript"] for c in out)
        self.assertEqual(rebuilt, " ".join(words))

    def test_default_chunk_size_is_fifty(self):
        words = [f"w{i}" for i in range(101)]
        out = self._chunk(" ".join(words))
        self.assertEqual(len(out), 3)  # 50 + 50 + 1

    def test_non_positive_chunk_size_falls_back_to_default(self):
        words = [f"w{i}" for i in range(60)]
        out = self._chunk(" ".join(words), chunk_size=0)
        self.assertEqual(len(out), 2)  # falls back to 50-word default


if __name__ == "__main__":
    unittest.main()
