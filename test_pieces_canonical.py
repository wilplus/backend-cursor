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
            self.assertLessEqual(len(p["transcript"]), 200)
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
