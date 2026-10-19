"""
STORY    As a speaker, I want my transcript split into one paragraph per slide
         at the moment I changed slide, so that my Ideal Text follows my deck.
         (Critical path: record -> process -> Ideal Text.)
OUTCOME
  O1  Words said before a slide change go to the earlier slide, words after it
      to the later one, with each fragment's audio span taken from its words.
  O2  Every slide of the deck gets its paragraph, even one nothing was said on.
  O3  A talk without a deck is cut into pieces at word boundaries, each piece
      keeps its own audio span, and an old one-blob transcript is re-cut
      without inventing spans.
  O4  A run-on sentence gets a full stop at a real pause, so a piece can end
      there, and not one word is changed.
  O5  The boundary measurement finds the pause a speaker left at a tap, and
      reports a tap they talked straight through.
  O6  A Take with nothing said (no words, no deck, no taps) comes out empty
      from every step of the split, never as an error that stops the loop.
PROVES   O1 -> test_words_on_both_sides_of_a_slide_change_split_there
            -> test_a_fragment_spans_its_own_words
         O2 -> test_words_on_both_sides_of_a_slide_change_split_there
         O3 -> test_a_word_longer_than_the_cap_gets_its_own_piece
            -> test_stored_pieces_come_back_with_their_spans
            -> test_an_old_long_blob_is_recut_without_spans
         O4 -> test_a_run_on_sentence_closes_a_piece_at_the_pause
         O5 -> test_the_boundary_measurement_sees_the_pause_at_a_tap
         O6 -> test_a_take_with_nothing_said_comes_out_empty
WHY      Founder #6 and Part A: words after a mid-snippet click stayed under
         the old slide, and the quiet first slide went missing.
"""
from __future__ import annotations

import unittest

from services.slide_boundary_metrics import boundary_metrics
from services.slide_word_split import (
    apply_clock_offset,
    build_slide_transcripts,
    chunk_transcript_by_chars,
    chunk_words_by_chars,
    deckless_chunks_from_stx,
    slice_words_for_window,
    split_runon_sentences,
    split_words_by_slides,
)


def _w(word, start, end):
    return {"word": word, "start": start, "end": end}


SLIDES = [{"title": "S1", "body": ""}, {"title": "S2", "body": ""},
          {"title": "S3", "body": ""}]
# slide 0 from t=0, slide 1 from t=5 s; slide 2 is never reached.
ADV = [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 5000}]


class PerSlideSplitTests(unittest.TestCase):

    def test_words_on_both_sides_of_a_slide_change_split_there(self):
        words = [_w("we", 3.9, 4.1), _w("grew", 4.2, 4.5), _w(" ", 4.6, 4.7),
                 _w("revenue", 4.8, 4.99), _w("next", 5.0, 5.3),
                 _w("costs", 5.4, 5.9)]
        frags = split_words_by_slides(words, ADV, SLIDES)
        self.assertEqual(
            [(f["slide_index"], f["transcript"]) for f in frags],
            [(0, "we grew revenue"), (1, "next costs")])

        per_slide = build_slide_transcripts(words, ADV, SLIDES)
        self.assertEqual([s["index"] for s in per_slide], [0, 1, 2])
        self.assertEqual([s["transcript"] for s in per_slide],
                         ["we grew revenue", "next costs", ""])
        self.assertEqual(per_slide[1]["start_offset_ms"], 5000)
        self.assertIsNone(per_slide[2]["start_offset_ms"])

    def test_a_fragment_spans_its_own_words(self):
        frags = split_words_by_slides([_w("a", 6.0, 6.2), _w("b", 6.8, 7.5)],
                                      ADV, SLIDES)
        self.assertEqual(len(frags), 1)
        self.assertEqual(frags[0]["slide_index"], 1)
        self.assertEqual(frags[0]["start_offset_ms"], 6000)
        self.assertEqual(frags[0]["duration_ms"], 1500)  # 7.5 s - 6.0 s


class DecklessTests(unittest.TestCase):

    def test_a_word_longer_than_the_cap_gets_its_own_piece(self):
        out = chunk_words_by_chars([
            _w("hi", 0.0, 0.2),
            _w("supercalifragilistic", 0.3, 1.5),
            _w("ok", 1.6, 1.8),
        ], max_chars=10)
        self.assertEqual([c["transcript"] for c in out],
                         ["hi", "supercalifragilistic", "ok"])

    def test_stored_pieces_come_back_with_their_spans(self):
        out = deckless_chunks_from_stx([
            {"index": 0, "transcript": "part one",
             "start_offset_ms": 0, "duration_ms": 3000},
            {"index": 1, "transcript": "part two",
             "start_offset_ms": 3200, "duration_ms": 2500},
        ])
        self.assertEqual([(c["transcript"], c["start_offset_ms"]) for c in out],
                         [("part one", 0), ("part two", 3200)])

    def test_an_old_long_blob_is_recut_without_spans(self):
        blob = " ".join(f"word{i}" for i in range(80))  # >> 300 chars
        out = deckless_chunks_from_stx([{"index": 0, "transcript": blob,
                                         "start_offset_ms": 0,
                                         "duration_ms": 60000}])
        self.assertGreater(len(out), 1)
        self.assertNotIn("start_offset_ms", out[0])  # no invented spans
        self.assertEqual(" ".join(c["transcript"] for c in out), blob)


class RunOnSentenceTests(unittest.TestCase):

    def test_a_run_on_sentence_closes_a_piece_at_the_pause(self):
        long_a = ("we spent the whole quarter rebuilding the pipeline and "
                  "the team pushed through every single blocker on the list")
        long_b = ("the next quarter is where all of that work finally starts "
                  "paying off for every customer we have")
        words, t = [], 0.0
        for gi, group in enumerate((long_a, long_b)):
            if gi:
                t += 0.8                      # a real pause between them
            for tok in group.split():
                words.append({"word": tok, "start": round(t, 2),
                              "end": round(t + 0.3, 2)})
                t = round(t + 0.4, 2)

        out = split_runon_sentences(words, min_gap_ms=500, min_chars=40)
        # Punctuation and casing only: the words and their times are kept.
        self.assertEqual([w["word"].strip(".").lower() for w in out],
                         [w["word"] for w in words])
        self.assertEqual([(w["start"], w["end"]) for w in out],
                         [(w["start"], w["end"]) for w in words])

        pieces = chunk_words_by_chars(out, 110)
        self.assertTrue(pieces[0]["transcript"].endswith("list."))
        self.assertTrue(pieces[1]["transcript"].startswith("The next"))


class BoundaryMeasurementTests(unittest.TestCase):

    def test_the_boundary_measurement_sees_the_pause_at_a_tap(self):
        # A 600 ms pause around 4.0-4.6 s next to the 4.5 s tap; the 9 s tap
        # falls in unbroken speech.
        words = [_w("a", 3.0, 3.5), _w("b", 3.6, 4.0), _w("c", 4.6, 5.0),
                 _w("d", 8.0, 8.4), _w("e", 8.45, 8.85), _w("f", 8.9, 9.3),
                 _w("g", 9.35, 9.7)]
        adv = [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 4500},
               {"index": 2, "t_ms": 9000}]
        m = boundary_metrics(words, adv, SLIDES)
        self.assertEqual(m["boundaries_total"], 2)
        self.assertEqual(m["boundaries_moved"], 1)      # snapped into the pause
        self.assertEqual(m["boundaries_no_pause"], 1)   # talked through it
        self.assertEqual(m["shift_ms_max"], 200)         # 4500 -> 4300

        # Speech with no real pause anywhere: nothing can move.
        steady = [_w(t, i * 0.4, i * 0.4 + 0.35) for i, t in enumerate("abcdef")]
        m = boundary_metrics(steady, [{"index": 0, "t_ms": 0},
                                      {"index": 1, "t_ms": 1000}], SLIDES)
        self.assertEqual((m["boundaries_moved"], m["boundaries_no_pause"]), (0, 1))


class NothingSaidTests(unittest.TestCase):
    """One case for the defensive guards: a silent Take, or one with no deck,
    must flow through as empty output (CLAUDE.md Never 3: the loop never
    breaks)."""

    def test_a_take_with_nothing_said_comes_out_empty(self):
        self.assertEqual(split_words_by_slides([], ADV, SLIDES), [])
        self.assertEqual(build_slide_transcripts([_w("x", 0, 1)], ADV, []), [])
        self.assertEqual(slice_words_for_window(None, 0, 1000), [])
        self.assertEqual(split_runon_sentences(None), [])
        self.assertEqual(chunk_words_by_chars([]), [])
        self.assertEqual(chunk_transcript_by_chars("   "), [])
        self.assertEqual(deckless_chunks_from_stx([]), [])
        self.assertEqual(apply_clock_offset([], 300), [])


if __name__ == "__main__":
    unittest.main()
