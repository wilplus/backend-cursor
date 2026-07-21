"""willab — the Living Transcript (founder decisions 2026-07-20).

The ideal text stops being a stitched selection of best-ranked moments
("very much shorter than what I really said") and becomes the speaker's
FULL transcript with Google-Docs-style tracked changes.

Pinned here, decision by decision:
  #1 the document IS the full transcript of the latest SPOKEN take, in
     speech order, with every piece's character span intact;
  #2 minimum smoothing = fillers + immediate repeats + punctuation ONLY.
     No word is ever silently changed, no false start silently dropped —
     the L1 fence of the whole re-shape;
  #3 changes are span-anchored (strike/propose, bold — possibly HALF a
     sentence — advice), each anchored on an exact substring or dropped;
  flag OFF = byte-for-byte today's behavior.

Run: python3 -m unittest test_living_transcript
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.tracked_changes import build_tracked_changes, verify_changes
from services.transcript_document import (
    build_transcript_document, verify_spans,
)
from services.transcript_smoothing import (
    smooth_verbatim, strip_fillers, tidy_punctuation,
)

ARC = "a1"
T1 = "11111111-1111-4111-8111-111111111111"
S1 = "aaaa1111-aaaa-1111-aaaa-111111111111"
S2 = "bbbb2222-bbbb-2222-bbbb-222222222222"


class SmoothingFenceTests(unittest.TestCase):
    """Decision #2 — the fence: fillers + repeats + punctuation, nothing
    else. Every test here is a trust boundary."""

    def test_fillers_removed(self):
        self.assertEqual(
            smooth_verbatim("um so I uh built the team"),
            "So I built the team.")

    def test_immediate_repeat_collapsed(self):
        self.assertEqual(smooth_verbatim("we we shipped it"),
                         "We shipped it.")

    def test_expressive_repeat_with_punctuation_is_KEPT(self):
        # "no, no, no" is the speaker being emphatic — never a disfluency.
        out = smooth_verbatim("No, no, no. That is not it")
        self.assertTrue(out.startswith("No, no, no."))   # all three kept
        self.assertEqual(smooth_verbatim("very very good"),
                         "Very good.")                    # no punctuation

    def test_real_words_are_never_touched(self):
        # The whole L1 fence: false starts, hedges, filler-ADJACENT real
        # words all survive verbatim.
        src = ("So what I— let me start again. I think, like, you know, "
               "we actually really did the thing")
        out = smooth_verbatim(src)
        for kept in ("So what I—", "let me start again", "like",
                     "you know", "actually really"):
            self.assertIn(kept, out)

    def test_filler_lookalikes_inside_words_survive(self):
        for word in ("umbrella", "uhuru", "summer", "humble", "hummus"):
            self.assertIn(word, smooth_verbatim(f"the {word} matters"))

    def test_sentence_casing_and_terminal_mark(self):
        self.assertEqual(smooth_verbatim("we won. it was close"),
                         "We won. It was close.")

    def test_no_double_terminal(self):
        self.assertEqual(smooth_verbatim("We won!"), "We won!")
        self.assertEqual(smooth_verbatim("Did we win?"), "Did we win?")

    def test_orphaned_punctuation_after_filler_removal(self):
        self.assertEqual(smooth_verbatim("um, we started"), "We started.")

    def test_empty_and_non_string(self):
        for bad in ("", "   ", None, 42):
            self.assertEqual(smooth_verbatim(bad), "")

    def test_word_count_never_grows(self):
        src = "um we we really uh did it"
        self.assertLess(len(smooth_verbatim(src).split()), len(src.split()))

    def test_helpers_are_independent(self):
        self.assertEqual(strip_fillers("um hello").strip(), "hello")
        self.assertEqual(tidy_punctuation("hello  world"), "Hello world.")


class DocumentBuildTests(unittest.TestCase):
    """Decision #1 — the full transcript, in speech order, with spans."""

    class _Db:
        def __init__(self, snips, *, corrections=None, edits=None,
                     sessions=None):
            self._snips = snips
            self._corr = corrections or []
            self._edits = edits or []
            self._sessions = sessions

        def get_arc_sessions(self, arc_id):
            if self._sessions is not None:
                return self._sessions
            return [{"id": T1, "take_index": 1, "recording_kind": "spoken"}]

        def get_snippets_by_session(self, sid):
            return self._snips

        def get_coach_snippet_drafts(self, sid):
            return self._corr

        def get_user_transcript_edits(self, sid):
            return self._edits

    def _snips(self):
        return [
            {"id": S2, "start_offset_ms": 4000,
             "transcript": "and then we uh shipped it"},
            {"id": S1, "start_offset_ms": 0,
             "transcript": "um we started small"},
        ]

    def test_full_text_in_speech_order_with_valid_spans(self):
        doc = build_transcript_document(ARC, database=self._Db(self._snips()))
        self.assertEqual(doc["text"],
                         "We started small. And then we shipped it.")
        self.assertEqual([p["snippet_id"] for p in doc["pieces"]], [S1, S2])
        self.assertTrue(verify_spans(doc))
        self.assertEqual(doc["take_index"], 1)

    def test_every_piece_is_present_nothing_selected_away(self):
        # THE bug this re-shape fixes: no ranking, no top-N — every
        # transcribed piece is in the document.
        snips = [{"id": f"s{i}", "start_offset_ms": i * 1000,
                  "transcript": f"sentence number {i}"} for i in range(12)]
        doc = build_transcript_document(ARC, database=self._Db(snips))
        self.assertEqual(len(doc["pieces"]), 12)
        low = doc["text"].lower()
        for i in range(12):
            self.assertIn(f"sentence number {i}", low)

    def test_coach_correction_wins_then_user_edit_then_raw(self):
        db = self._Db(
            self._snips(),
            corrections=[{"snippet_id": S1,
                          "transcript_corrected": "We started tiny"}],
            edits=[{"snippet_id": S2, "text": "and then we launched"}])
        doc = build_transcript_document(ARC, database=db)
        self.assertIn("We started tiny", doc["text"])
        self.assertIn("And then we launched", doc["text"])

    def test_latest_spoken_take_is_the_document(self):
        sessions = [
            {"id": "t1", "take_index": 1, "recording_kind": "spoken"},
            {"id": "t2", "take_index": 2, "recording_kind": "spoken"},
            {"id": "r1", "take_index": 2, "recording_kind": "read",
             "paired_session_id": "t2"},
        ]

        class _D(self._Db):
            def get_snippets_by_session(self, sid):
                return [{"id": f"{sid}-s", "start_offset_ms": 0,
                         "transcript": f"words from {sid}"}]

        doc = build_transcript_document(
            ARC, database=_D([], sessions=sessions))
        self.assertIn("words from t2", doc["text"].lower())  # not t1/r1
        self.assertNotIn("t1", doc["text"].lower())
        self.assertEqual(doc["take_session_id"], "t2")

    def test_no_takes_or_no_snippets_is_none(self):
        self.assertIsNone(build_transcript_document(
            ARC, database=self._Db([], sessions=[])))
        self.assertIsNone(build_transcript_document(
            ARC, database=self._Db([])))

    def test_broken_db_never_raises(self):
        self.assertIsNone(build_transcript_document(ARC, database=object()))


class TrackedChangeTests(unittest.TestCase):
    """Decision #3 — span-anchored strike/propose/bold/advice."""

    DOC = "We started small. And then we shipped it fast."
    PIECES = [{"snippet_id": S1, "text": "We started small."},
              {"snippet_id": S2, "text": "And then we shipped it fast."}]

    def _changes(self, sugs, **kw):
        return build_tracked_changes(self.DOC, self.PIECES, sugs, **kw)

    def test_polish_replace_anchors_on_the_changed_words_only(self):
        sugs = {S2: {"kind": "replace", "trigger": "polish",
                     "replacement_text": "And then we launched it fast.",
                     "why": "Tighter."}}
        c = self._changes(sugs)[0]
        self.assertEqual(c["kind"], "replace")
        self.assertEqual(c["source"], "polish")
        self.assertEqual(c["quote"], "shipped")       # NOT the whole piece
        self.assertEqual(c["proposed_text"],
                         "And then we launched it fast.")
        self.assertEqual(self.DOC[c["span"]["start"]:c["span"]["end"]],
                         "shipped")
        self.assertTrue(verify_changes(self.DOC, [c]))

    def test_bold_can_cover_half_a_sentence(self):
        # Founder: "bolden only the second part of it".
        sugs = {S2: {"kind": "emphasize", "replacement_text": None,
                     "why": "This is the line that lands."}}
        c = self._changes(sugs)[0]
        self.assertEqual(c["kind"], "bold")
        self.assertIn(c["quote"], self.DOC)
        self.assertTrue(verify_changes(self.DOC, [c]))

    def test_delivery_and_structural_are_advice_with_device(self):
        for kind, dev, src in (("delivery", "pace_fast", "delivery"),
                               ("structure", "contrast", "structural")):
            c = self._changes({S1: {"kind": kind, "trigger": dev}})[0]
            self.assertEqual(c["kind"], "advice")
            self.assertEqual(c["source"], src)
            self.assertEqual(c["device"], dev)
            self.assertIsNone(c["why"])

    def test_missing_piece_text_drops_the_change(self):
        # The piece was edited/baked away — never point at wrong words.
        pieces = [{"snippet_id": S1, "text": "words that are not there"}]
        self.assertEqual(
            build_tracked_changes(self.DOC, pieces,
                                  {S1: {"kind": "emphasize"}}), [])

    def test_applied_change_is_consumed(self):
        sugs = {S1: {"kind": "emphasize"}}
        self.assertEqual(self._changes(sugs, applied=[S1]), [])

    def test_replace_without_proposal_is_dead(self):
        sugs = {S1: {"kind": "replace", "trigger": "wording",
                     "replacement_text": "   "}}
        self.assertEqual(self._changes(sugs), [])

    def test_changes_are_ordered_by_position(self):
        sugs = {S2: {"kind": "emphasize"}, S1: {"kind": "emphasize"}}
        out = self._changes(sugs)
        self.assertEqual([c["id"] for c in out], [S1, S2])

    def test_ac9_no_internal_vocabulary_or_numbers(self):
        import json
        sugs = {S1: {"kind": "replace", "trigger": "threat",
                     "replacement_text": "steadier words",
                     "why": "It reads calmer."}}
        raw = json.dumps(self._changes(sugs))
        for banned in ("threat", "charisma", "potentiometer", "power_score",
                       "z_score", "stickiness"):
            self.assertNotIn(banned, raw)

    def test_empty_inputs(self):
        self.assertEqual(build_tracked_changes("", self.PIECES, {}), [])
        self.assertEqual(build_tracked_changes(self.DOC, [], {}), [])
        self.assertEqual(build_tracked_changes(self.DOC, self.PIECES, {}), [])


class AssemblyFlagTests(unittest.TestCase):
    """Flag OFF must be byte-for-byte today's assembly; flag ON swaps the
    document source and leaves every other lane working."""

    class _Db(DocumentBuildTests._Db):
        def __init__(self, snips):
            super().__init__(snips)
            self.persisted = []

        def list_ideal_decisions(self, arc_id):
            return []

        def get_moment_suggestions_by_arc(self, arc_id):
            return {}

        def persist_auto_ideal_text(self, arc_id, text):
            self.persisted.append(text)
            return True

    def _assemble(self, flag):
        import services.ideal_text_block as mod
        snips = [{"id": S1, "start_offset_ms": 0,
                  "transcript": "um we started small"},
                 {"id": S2, "start_offset_ms": 10,
                  "transcript": "and we kept going"}]
        db = self._Db(snips)
        bp = {"ready": True, "slides": [{
            "text": "just the best line", "verbatim": "just the best line",
            "polished": False, "snippet_id": S1, "session_id": T1,
            "breakthrough": False, "key_phrases": []}]}
        with patch("services.best_presentation.build_best_presentation",
                   return_value=bp), \
             patch.dict("os.environ",
                        {"LIVING_TRANSCRIPT_ENABLED": "1" if flag else "0"}):
            mod.maybe_assemble_ideal_text(ARC, database=db,
                                          require_target=False)
        return db.persisted

    def test_flag_on_persists_the_full_transcript(self):
        out = self._assemble(True)[0]
        self.assertIn("We started small", out)
        self.assertIn("we kept going", out)
        self.assertNotIn("just the best line", out)   # not the selection
        self.assertNotIn("[[moment:", out)            # no anchors on the doc

    def test_flag_off_persists_todays_selection(self):
        out = self._assemble(False)[0]
        self.assertIn("just the best line", out)
        self.assertNotIn("We started small", out)


try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
    _IMPORT_ERROR = e


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ServeChangesTests(unittest.TestCase):
    """The SD GET's `changes` block — present only with the flag ON,
    anchored on the SERVED text, absent (not empty) when off."""

    DOC = "We started small. And then we shipped it fast."

    def _block(self, *, flag, sugs=None, snips=None):
        _snips = snips if snips is not None else [
            {"id": S1, "start_offset_ms": 0,
             "transcript": "We started small."},
            {"id": S2, "start_offset_ms": 10,
             "transcript": "And then we shipped it fast."}]
        with patch.dict("os.environ",
                        {"LIVING_TRANSCRIPT_ENABLED": "1" if flag else "0"}), \
             patch.object(v2.db, "get_arc_sessions",
                          return_value=[{"id": T1, "take_index": 1,
                                         "recording_kind": "spoken"}]), \
             patch.object(v2.db, "get_snippets_by_session",
                          return_value=_snips), \
             patch.object(v2.db, "get_coach_snippet_drafts",
                          return_value=[]), \
             patch.object(v2.db, "get_user_transcript_edits",
                          return_value=[]), \
             patch.object(v2.db, "get_moment_suggestions_by_arc",
                          return_value=(sugs or {})), \
             patch.object(v2.db, "get_suggestion_feedback_by_session",
                          return_value=[]):
            return v2._tracked_changes_block(ARC, self.DOC)

    def test_flag_off_key_is_absent(self):
        self.assertEqual(self._block(flag=False), {})

    def test_flag_on_serves_anchored_changes(self):
        out = self._block(flag=True, sugs={
            S2: {"kind": "replace", "trigger": "polish",
                 "replacement_text": "And then we launched it fast.",
                 "why": "Tighter."}})
        c = out["changes"][0]
        self.assertEqual(c["kind"], "replace")
        self.assertEqual(self.DOC[c["span"]["start"]:c["span"]["end"]],
                         c["quote"])

    def test_no_suggestions_serves_empty_list(self):
        self.assertEqual(self._block(flag=True), {"changes": []})

    def test_broken_document_degrades_to_absent(self):
        with patch.dict("os.environ",
                        {"LIVING_TRANSCRIPT_ENABLED": "1"}), \
             patch.object(v2.db, "get_arc_sessions",
                          side_effect=RuntimeError("boom")):
            self.assertEqual(v2._tracked_changes_block(ARC, self.DOC), {})


if __name__ == "__main__":
    unittest.main()
