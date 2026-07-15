"""willab — pieces-canonical core (founder 2026-07-14): the ≤200-char piece
IS the moment.

Covers the F1-CORE cutter (services/slide_word_split.chunk_slide_words_by_chars):
slide boundary FIRST (a piece never crosses a slide), ≤200 chars within the
slide, exact word-derived audio spans, global ordinals — and the drafter's
two-tier budget dispatch (LLM for the budget set, deterministic auto-comment
for the rest, same write-once lane).

Run: python3 -m unittest test_pieces_canonical
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

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

    def test_clean_alignment_takes_segment_form(self):
        out = self._restore(["i", "went", "to", "the", "store"],
                            "I went to the store.")
        self.assertEqual([w["word"] for w in out],
                         ["I", "went", "to", "the", "store."])

    def test_ghost_word_dropped_filler_resyncs(self):
        # THE founder-added edge case: segment says "So, um, I went to the
        # store." but the word array dropped the fillers. Alignment must
        # resync at "I" and the fillers' punctuation must not garble the rest.
        out = self._restore(["i", "went", "to", "the", "store"],
                            "So, um, I went to the store.")
        self.assertEqual([w["word"] for w in out],
                         ["I", "went", "to", "the", "store."])

    def test_mid_sentence_ghost_donates_punctuation_to_previous(self):
        # "well," dropped mid-stream → its comma lands on the previous
        # aligned word; remainder stays aligned.
        out = self._restore(["i", "think", "we", "ship"],
                            "I think, well, we ship!")
        self.assertEqual([w["word"] for w in out],
                         ["I", "think,,", "we", "ship!"])
        # (both the think-comma and the ghost's comma carry — punctuation is
        # never LOST; cosmetic doubling is acceptable and rare)

    def test_array_side_ghost_passes_through(self):
        # The word array has a token the segment text lacks — it passes
        # through raw and alignment continues.
        out = self._restore(["i", "uh", "went", "home"], "I went home.")
        self.assertEqual([w["word"] for w in out],
                         ["I", "uh", "went", "home."])

    def test_unalignable_segment_never_garbles(self):
        # Total mismatch (pathological) → words pass through unpunctuated.
        out = self._restore(["alpha", "beta", "gamma"],
                            "completely different text here entirely.")
        self.assertEqual([w["word"] for w in out],
                         ["alpha", "beta", "gamma"])

    def test_spans_strictly_untouched(self):
        words = self._words(["i", "went"])
        before = [(w["start"], w["end"]) for w in words]
        from services.slide_word_split import restore_punctuation
        out = restore_punctuation(words, [{"text": "I went."}])
        self.assertEqual([(w["start"], w["end"]) for w in out], before)

    def test_no_segments_passthrough(self):
        from services.slide_word_split import restore_punctuation
        words = self._words(["hello", "there"])
        self.assertEqual(restore_punctuation(words, []), words)
        self.assertEqual(restore_punctuation(words, None), words)

    def test_long_ghost_run_recovers_mutual_skip(self):
        # REVIEW-CONFIRMED bug (2026-07-15): a filler run LONGER than the
        # look-ahead window froze the text pointer and stripped punctuation
        # from the whole rest of the take. Mutual skip must recover.
        out = self._restore(["we", "win", "big", "today"],
                            "we uh um er ah win big today.")
        self.assertEqual([w["word"] for w in out],
                         ["we", "win", "big", "today."])

    def test_ghost_run_mid_take_keeps_later_sentences(self):
        # The reviewer's second repro: 4 ghosts mid-stream must not kill the
        # later sentence breaks.
        out = self._restore(
            ["we", "grow", "fast", "and", "then", "we", "scale"],
            "We grow, uh, um, well, like, fast. And then we scale.")
        words = [w["word"] for w in out]
        self.assertEqual(words[-1], "scale.")
        self.assertIn("fast.", words)

    def test_desync_contained_to_one_segment(self):
        # Per-segment anchoring: a pathological first segment must not
        # damage the second (words carry timestamps; segments carry spans).
        from services.slide_word_split import restore_punctuation
        words = (self._words(["xxx", "yyy"], t0=0.0)
                 + self._words(["clean", "sentence"], t0=10.0))
        segs = [
            {"text": "totally different tokens here entirely.",
             "start": 0.0, "end": 9.0},
            {"text": "Clean sentence.", "start": 10.0, "end": 12.0},
        ]
        out = restore_punctuation(words, segs)
        self.assertEqual([w["word"] for w in out][-2:],
                         ["Clean", "sentence."])


class DecklessReadBackTests(unittest.TestCase):
    """REVIEW-CONFIRMED bug (2026-07-15): the read-back legacy-blob probe at
    the 200 target re-split a legit single sentence-extended piece into
    span-less phantom chunks. The probe now uses the HARD cap (300)."""

    def test_single_extended_piece_keeps_its_span(self):
        from services.slide_word_split import deckless_chunks_from_stx
        text = ("word " * 49).strip() + "."       # 245 chars, one sentence
        stx = [{"index": 0, "transcript": text,
                "start_offset_ms": 0, "duration_ms": 12300}]
        chunks = deckless_chunks_from_stx(stx)
        self.assertEqual(len(chunks), 1)          # never re-split
        self.assertEqual(chunks[0]["start_offset_ms"], 0)
        self.assertEqual(chunks[0]["duration_ms"], 12300)
        self.assertEqual(chunks[0]["transcript"], text)

    def test_true_legacy_blob_still_resplits(self):
        from services.slide_word_split import deckless_chunks_from_stx
        blob = " ".join(f"w{i}" for i in range(120))   # ≫300 chars
        stx = [{"index": 0, "transcript": blob,
                "start_offset_ms": 0, "duration_ms": 60000}]
        chunks = deckless_chunks_from_stx(stx)
        self.assertGreater(len(chunks), 1)
        self.assertNotIn("start_offset_ms", chunks[0])  # legacy = span-less

    def test_persist_then_read_round_trip(self):
        # END-TO-END: the persist-time cutter's own output must round-trip
        # through the read-back helper unchanged (the drift the review
        # flagged for edit indexes / card attachment).
        from services.slide_word_split import (
            chunk_words_by_chars, deckless_chunks_from_stx,
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

    def test_closes_at_sentence_end_before_target(self):
        # Sentence end at ~180 chars, next sentence would cross 200 → the
        # piece closes AT the sentence end, never mid-sentence.
        s1 = " ".join(["word"] * 35) + "."          # ~179 chars
        s2 = " ".join(["next"] * 30) + "."
        pieces = self._cut([s1, s2])
        self.assertTrue(pieces[0]["transcript"].endswith("word."))
        self.assertLessEqual(len(pieces[0]["transcript"]), 200)

    def test_extension_window_reaches_first_sentence_end(self):
        # No sentence end before 200; the first one lands at ~230 → the piece
        # EXTENDS past the target and closes there (≤300).
        s1 = " ".join(["alpha"] * 38) + "."          # ~233 chars, one sentence
        s2 = " ".join(["beta"] * 10) + "."
        pieces = self._cut([s1, s2])
        self.assertTrue(pieces[0]["transcript"].endswith("alpha."))
        self.assertGreater(len(pieces[0]["transcript"]), 200)
        self.assertLessEqual(len(pieces[0]["transcript"]), 300)

    def test_run_on_sentence_hard_cuts_before_300(self):
        # A 400-char sentence with no end in the window → word-boundary cut
        # before the hard cap (the escape hatch).
        s1 = " ".join(["run"] * 100) + "."           # ~399 chars
        pieces = self._cut([s1])
        self.assertGreater(len(pieces), 1)
        self.assertLessEqual(len(pieces[0]["transcript"]), 300)

    def test_never_mid_sentence_when_end_within_cap(self):
        # Several short sentences: every piece boundary lands on a sentence
        # end (no piece ends mid-sentence).
        sentences = [(" ".join(["tok"] * 12) + ".") for _ in range(8)]
        pieces = self._cut(sentences)
        for p in pieces[:-1]:
            self.assertTrue(p["transcript"].rstrip().endswith("."),
                            f"mid-sentence cut: …{p['transcript'][-30:]}")

    def test_unpunctuated_degrades_to_hard_cap_cuts(self):
        pieces = self._cut([" ".join(["plain"] * 100)])  # no punctuation
        self.assertGreater(len(pieces), 1)
        for p in pieces:
            self.assertLessEqual(len(p["transcript"]), 300)

    def test_spans_exact_and_ordered(self):
        s = [(" ".join(["tok"] * 12) + ".") for _ in range(6)]
        pieces = self._cut(s)
        for a, b in zip(pieces, pieces[1:]):
            self.assertLessEqual(
                a["start_offset_ms"] + a["duration_ms"],
                b["start_offset_ms"] + 1)


class ChunkSlideWordsTests(unittest.TestCase):

    def _cut(self, text_per_slide, **kw):
        from services.slide_word_split import chunk_slide_words_by_chars
        words, advances = _words(text_per_slide)
        slides = [{"title": f"S{i}"} for i in range(len(text_per_slide))]
        return chunk_slide_words_by_chars(words, advances, slides, **kw)

    def test_pieces_never_cross_slide_boundaries(self):
        long_a = " ".join(["alpha"] * 60)   # ~360 chars → 2+ pieces
        long_b = " ".join(["beta"] * 60)
        pieces = self._cut([long_a, long_b])
        self.assertGreater(len(pieces), 2)
        for p in pieces:
            toks = set(p["transcript"].split())
            # a piece is EITHER all-alpha or all-beta — never mixed
            self.assertTrue(toks <= {"alpha"} or toks <= {"beta"},
                            f"piece crossed a slide: {p['transcript'][:60]}")

    def test_cap_and_exact_spans(self):
        pieces = self._cut([" ".join(["word"] * 100)])  # ~500 chars, 1 slide
        self.assertGreater(len(pieces), 1)
        for p in pieces:
            # Unpunctuated input cuts at the HARD cap (300 = target+100,
            # founder-locked 2026-07-15); punctuated input closes at
            # sentence ends — see SentenceAwareChunkTests.
            self.assertLessEqual(len(p["transcript"]), 300)
            self.assertIsInstance(p["start_offset_ms"], int)
            self.assertIsInstance(p["duration_ms"], int)
            self.assertGreater(p["duration_ms"], 0)
        # spans are ordered and non-overlapping (word-derived)
        for a, b in zip(pieces, pieces[1:]):
            self.assertLessEqual(
                a["start_offset_ms"] + a["duration_ms"],
                b["start_offset_ms"] + 1,   # word end == next start allowed
            )

    def test_global_ordinal_and_slide_index(self):
        pieces = self._cut([" ".join(["a"] * 120), "short one",
                            " ".join(["c"] * 120)])
        self.assertEqual([p["index"] for p in pieces],
                         list(range(len(pieces))))
        # slide_index is non-decreasing (slide order preserved)
        sis = [p["slide_index"] for p in pieces]
        self.assertEqual(sis, sorted(sis))
        self.assertIn(1, sis)   # the short slide still contributed a piece

    def test_slide_revisit_back_nav_never_merges_visits(self):
        # THE review-confirmed F1 breach (2026-07-14): back-navigation
        # A→B→A must yield SEPARATE pieces per visit — a piece's audio span
        # may never swallow another slide's speech. Words: 5 on slide 0,
        # 80 on slide 1, then BACK to slide 0 for 5 more.
        from services.slide_word_split import chunk_slide_words_by_chars
        words, advances = [], [{"index": 0, "t_ms": 0}]
        t = 0.0
        def _speak(text, dur=0.4):
            nonlocal t
            for w in text.split():
                words.append({"word": w, "start": round(t, 3),
                              "end": round(t + dur, 3)})
                t += dur
        _speak("intro words on slide zero")
        advances.append({"index": 1, "t_ms": int(t * 1000) + 50}); t += 1.0
        _speak(" ".join(["middle"] * 80))
        advances.append({"index": 0, "t_ms": int(t * 1000) + 50}); t += 1.0
        _speak("closing back on zero again")
        slides = [{"title": "A"}, {"title": "B"}]
        pieces = chunk_slide_words_by_chars(words, advances, slides)
        # The two slide-0 visits are SEPARATE pieces (no merged span).
        zero_pieces = [p for p in pieces if p["slide_index"] == 0]
        self.assertEqual(len(zero_pieces), 2)
        first, last = zero_pieces[0], zero_pieces[-1]
        self.assertIn("intro", first["transcript"])
        self.assertIn("closing", last["transcript"])
        # Neither slide-0 piece's span may overlap slide 1's speech window.
        b_start = min(p["start_offset_ms"] for p in pieces
                      if p["slide_index"] == 1)
        b_end = max(p["start_offset_ms"] + p["duration_ms"] for p in pieces
                    if p["slide_index"] == 1)
        self.assertLessEqual(first["start_offset_ms"] + first["duration_ms"],
                             b_start)
        self.assertGreaterEqual(last["start_offset_ms"], b_end)
        # Global ordinals are TIME-ordered across the whole take.
        starts = [p["start_offset_ms"] for p in pieces]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual([p["index"] for p in pieces],
                         list(range(len(pieces))))

    def test_silent_slide_contributes_no_piece(self):
        pieces = self._cut(["hello there", "", "goodbye now"])
        self.assertEqual({p["slide_index"] for p in pieces}, {0, 2})

    def test_no_slides_returns_empty(self):
        from services.slide_word_split import chunk_slide_words_by_chars
        self.assertEqual(chunk_slide_words_by_chars([], [], []), [])
        words, advances = _words(["hi"])
        self.assertEqual(
            chunk_slide_words_by_chars(words, advances, None), [])

    def test_agrees_with_slide_transcripts_bucketing(self):
        # The piece cutter and the per-slide transcript view share ONE
        # bucketing — a word can never land on different slides in the two.
        from services.slide_word_split import (
            build_slide_transcripts, chunk_slide_words_by_chars,
        )
        text = ["one two three four", "five six seven", "eight nine"]
        words, advances = _words(text)
        slides = [{"title": f"S{i}"} for i in range(3)]
        stx = build_slide_transcripts(words, advances, slides)
        pieces = chunk_slide_words_by_chars(words, advances, slides)
        per_slide_from_pieces: dict = {}
        for p in pieces:
            per_slide_from_pieces.setdefault(p["slide_index"], []).append(
                p["transcript"])
        for entry in stx:
            joined = " ".join(per_slide_from_pieces.get(entry["index"], []))
            self.assertEqual(entry["transcript"], joined)


class DrafterBudgetTests(unittest.TestCase):
    """dispatch_coach_note_drafts budget: llm_ids → LLM draft; every other
    piece writes NOTHING (its comment is serve-time), and the draft NEVER
    carries a tone word (BLIND COACH — the labeling surface stays free of
    any direction guess, learned or acoustic)."""

    def _run(self, snippets, llm_ids, draft="LLM drafted note."):
        from services import coach_comment_drafter as mod
        from services.db import db
        written = {}
        db.set_charisma_snippet_ai_draft_coach_note = MagicMock(
            side_effect=lambda sid, d: written.setdefault(sid, d) or True)
        with patch.object(mod, "generate_coach_note_draft",
                          return_value=draft), \
             patch.object(mod, "_build_take_comparison", return_value=None):
            mod._draft_all("sess1", snippets, [], None, "topic", llm_ids)
        return written

    def _snips(self):
        return [
            {"id": f"s{i}", "transcript": f"piece {i}",
             "metrics": {"wpm": 100 + i}, "start_offset_ms": i * 1000}
            for i in range(4)
        ]

    def test_budget_only_llm_pieces_write(self):
        written = self._run(self._snips(), llm_ids={"s0", "s2"})
        # ONLY the budget pieces land a draft; non-budget pieces write
        # NOTHING here (their comment is serve-time — keeps the ai_draft /
        # clone corpus at ≤budget rows and publish events bounded).
        self.assertEqual(set(written), {"s0", "s2"})
        self.assertEqual(written["s0"], "LLM drafted note.")

    def test_legacy_none_budget_means_llm_for_all(self):
        written = self._run(self._snips(), llm_ids=None)
        self.assertEqual(set(written.values()), {"LLM drafted note."})
        self.assertEqual(len(written), 4)

    def test_no_tone_clause_ever_reaches_the_draft(self):
        # BLIND COACH: even when the model/acoustics have a strong read, the
        # coach's pre-fill never says "sounded rather ..." — the tone word is
        # a USER-surface-only carve-out.
        written = self._run(self._snips()[:1], llm_ids={"s0"},
                            draft="Nice clear open.")
        self.assertEqual(written["s0"], "Nice clear open.")
        self.assertNotIn("sounded rather", written["s0"])


if __name__ == "__main__":
    unittest.main()
