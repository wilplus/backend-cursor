"""
STORY    As a speaker, I want my Ideal Text to be my full latest Take with
         only fillers, repeats and punctuation smoothed, and feedback
         anchored on exact words, so that the text is what I said.
OUTCOME
  O1  The document is the full transcript of the LATEST spoken Take, in
      speech order, each piece's span slicing exactly its words; the flag
      no longer swaps in a shorter best-of text (Never-5).
  O2  Only hesitations, immediate repeats and punctuation/casing change
      silently; false starts, expressive repeats and real words stay
      (Never-5: no word silently changed). A full stop goes in between two
      pieces only where the speaker paused clearly and the next begins a
      sentence with a capital (N126).
  O3  Every change is anchored on an exact substring of the served text
      or dropped; a bold that cannot narrow is dropped, not widened.
  O4  A piece is never lost when its words change after a bake or a lock:
      it keeps its order and falls back to its paragraph.
  O5  What reaches the speaker carries no internal vocabulary, no score
      and no cue key the screen has no signed words for (Never-1, Never-4).
PROVES   O1 -> test_document_is_the_full_latest_take_in_speech_order,
               test_flag_on_and_off_persist_the_same_full_transcript
         O2 -> test_only_fillers_repeats_and_punctuation_change_silently,
               test_a_full_stop_goes_in_only_where_the_speaker_paused
         O3 -> test_key_phrases_from_say_it_stronger_extraction,
               test_delivery_and_structural_are_advice_with_device,
               test_the_confident_voice_card_obeys_the_same_rule,
               test_coarse_relocation_does_not_invent_feedback_or_exact_styling,
               test_flag_on_serves_anchored_changes,
               test_a_piece_whose_slide_is_not_in_this_document_is_DROPPED
         O4 -> test_a_run_of_changed_pieces_keeps_every_one_in_order,
               test_a_locked_paragraph_keeps_every_new_piece,
               test_located_pieces_keep_word_grain_beside_a_coarse_neighbour
         O5 -> test_ac9_no_internal_vocabulary_or_scores,
               test_an_UNKNOWN_key_never_reaches_a_user_payload
WHY      Founder decisions 2026-07-20 #1-#3 (the Living Transcript re-shape).
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from config import Config
from services.tracked_changes import (
    build_tracked_changes,
    key_phrases_from_say_it_stronger,
)
from services.transcript_document import (
    build_transcript_document,
    relocate_pieces,
    verify_spans,
)

ARC = "a1"
T1 = "11111111-1111-4111-8111-111111111111"
S1 = "aaaa1111-aaaa-1111-aaaa-111111111111"
S2 = "bbbb2222-bbbb-2222-bbbb-222222222222"


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

        @property
        def takes(self):
            # audit Q-A2: production now calls db.takes.<method>();
            # this fake implements those methods directly on itself.
            return self

        def get_snippets_by_session(self, sid):
            return self._snips

        def get_coach_snippet_drafts(self, sid):
            return self._corr

        def get_user_transcript_edits(self, sid):
            return self._edits

    def _snips(self):
        return [
            {"id": S2, "start_offset_ms": 4000, "language": "en",
             "transcript": "and then we uh shipped it"},
            {"id": S1, "start_offset_ms": 0, "language": "en",
             "transcript": "um we started small"},
        ]

    def test_document_is_the_full_latest_take_in_speech_order(self):
        older = "99999999-9999-4999-8999-999999999999"
        db = self._Db(self._snips(), sessions=[
            {"id": T1, "take_index": 2, "recording_kind": "spoken"},
            {"id": older, "take_index": 1, "recording_kind": "spoken"}])
        doc = build_transcript_document(ARC, database=db)
        self.assertEqual(doc["take_session_id"], T1)
        self.assertEqual(doc["text"],
                         "We started small and then we shipped it.")
        self.assertEqual([p["snippet_id"] for p in doc["pieces"]], [S1, S2])
        for p in doc["pieces"]:
            self.assertEqual(doc["text"][p["start"]:p["end"]], p["text"])

    def test_only_fillers_repeats_and_punctuation_change_silently(self):
        said = ("um so we we started smal- small, no, no, no, "
                "like uh basically from scratch")
        db = self._Db([{"id": S1, "start_offset_ms": 0, "language": "en",
                        "transcript": said}])
        doc = build_transcript_document(ARC, database=db)
        self.assertEqual(
            doc["text"],
            "So we started smal- small, no, no, no, like basically "
            "from scratch.")

    def test_a_full_stop_goes_in_only_where_the_speaker_paused(self):
        def doc(second: str, start_ms: int, language: str = "en") -> str:
            snips = [
                {"id": S1, "start_offset_ms": 0, "duration_ms": 2000,
                 "language": language, "transcript": "Startup is just a job"},
                {"id": S2, "start_offset_ms": start_ms, "duration_ms": 2000,
                 "language": language, "transcript": second},
            ]
            built = build_transcript_document(ARC, database=self._Db(snips))
            for p in built["pieces"]:  # the mark sits outside every span
                self.assertEqual(built["text"][p["start"]:p["end"]], p["text"])
            self.assertEqual(built["pieces"][0]["text"], "Startup is just a job")
            return built["text"]

        # The founder's Take 4: a clear pause, then a capital.
        self.assertEqual(doc("It's a job we love", 2800),
                         "Startup is just a job. It's a job we love.")
        # No clear pause, a lowercase word, the pronoun I, German nouns,
        # or a pause that cannot be measured: nothing goes in.
        self.assertEqual(doc("It's a job we love", 2200),
                         "Startup is just a job It's a job we love.")
        self.assertEqual(doc("and we love it", 2800),
                         "Startup is just a job and we love it.")
        self.assertEqual(doc("I love it", 2800),
                         "Startup is just a job I love it.")
        self.assertEqual(doc("Arbeit ist alles", 2800, "de"),
                         "Startup is just a job Arbeit ist alles.")
        self.assertEqual(doc("It's a job we love", None),  # type: ignore[arg-type]
                         "Startup is just a job It's a job we love.")


class TrackedChangeTests(unittest.TestCase):
    """Decision #3 — span-anchored strike/propose/bold/advice."""

    DOC = "We started small. And then we shipped it fast."
    # Pieces carry their CHARACTER SPAN — build_tracked_changes anchors on
    # it, never on a text search (the mis-anchor defect the review found).
    PIECES = [{"snippet_id": S1, "text": "We started small.",
               "take_session_id": T1, "start": 0, "end": 17},
              {"snippet_id": S2, "text": "And then we shipped it fast.",
               "take_session_id": T1, "start": 18, "end": 46}]

    def _changes(self, sugs, **kw):
        return build_tracked_changes(self.DOC, self.PIECES, sugs, **kw)


    def test_key_phrases_from_say_it_stronger_extraction(self):
        out = key_phrases_from_say_it_stronger(
            {"upgrades": [{"upgrade": "we crushed it"},
                          {"upgrade": "We Crushed It"},   # dupe, case-ins
                          {"upgrade": "x" * 80},          # too long
                          {"not_a_dict": True} if False else {}]})
        self.assertEqual(out, ["we crushed it"])
        self.assertEqual(key_phrases_from_say_it_stronger(None), [])

    def test_delivery_and_structural_are_advice_with_device(self):
        for kind, dev, src in (("delivery", "pace_fast", "delivery"),
                               ("structure", "contrast", "structural")):
            c = self._changes({S1: {"kind": kind, "trigger": dev}})[0]
            self.assertEqual(c["kind"], "advice")
            self.assertEqual(c["source"], src)
            self.assertEqual(c["device"], dev)
            self.assertIsNone(c["why"])


    def test_ac9_no_internal_vocabulary_or_scores(self):
        import json
        sugs = {S1: {"kind": "replace", "trigger": "threat",
                     "replacement_text": "steadier words",
                     "why": "It reads calmer."}}
        changes = self._changes(sugs)
        self.assertEqual(changes[0]["proposed_text"], "steadier words")
        self.assertEqual(changes[0]["why"], "It reads calmer.")
        raw = json.dumps(changes)
        for banned in ("threat", "charisma", "potentiometer", "power_score",
                       "z_score", "stickiness"):
            self.assertNotIn(banned, raw)


class PraiseEvidenceTests(unittest.TestCase):
    """THE PRAISE LANE CITES ITS EVIDENCE (founder 2026-08-15): "explain
    using the vocal and verbal cues." The cues ride as KEYS — the FE holds a
    sentence per key, so nothing here can be a number or an unsigned-off
    wording."""

    DOC = "We started small. Then we shipped it fast."
    PIECES = [{"snippet_id": S1, "text": DOC, "take_session_id": T1,
               "start": 0, "end": len(DOC)}]

    def _changes(self, sug):
        return build_tracked_changes(self.DOC, self.PIECES, {S1: sug})


    def test_an_UNKNOWN_key_never_reaches_a_user_payload(self):
        # A row written before the vocabulary existed, or by a future writer,
        # must not put a key the FE has no copy for on screen.
        c = self._changes({"kind": "delivery", "trigger": "impeccable",
                           "cue_keys": ["landed_ending", "vibes", 7, None]})[0]
        self.assertEqual(c["cue_keys"], ["landed_ending"])


class AccentWidthTests(unittest.TestCase):
    """THE ACCENT WIDTH RULE (founder 2026-08-15): "try not to style the
    whole paragraphs or chunks but key few words or a sentence — so
    effectively delete that."

    A bold that cannot narrow is DROPPED. It used to be widened to the whole
    piece, and because the Confident Voice card has no say-it-stronger
    upgrades to narrow with (that lane only proposes upgrades where the
    wording is WEAK, and this card fires on moments delivered well), that
    fallback was the common path, not the edge."""

    # One piece, three sentences — a chunk, which is precisely what must
    # never be accented whole.
    DOC = ("We started small. Then we shipped it fast. "
           "And the customers stayed.")
    PIECES = [{"snippet_id": S1, "text": DOC, "take_session_id": T1,
               "start": 0, "end": len(DOC)}]

    def _changes(self, sug, **kw):
        return build_tracked_changes(self.DOC, self.PIECES, {S1: sug}, **kw)


    def test_the_confident_voice_card_obeys_the_same_rule(self):
        # It is the lane the defect actually shipped on, so it is pinned by
        # name rather than left to the generic case above.
        wide = {"kind": "emphasize", "trigger": "confident", "why": "y"}
        self.assertEqual(self._changes(wide), [])
        c = self._changes({**wide, "emphasis_quote": "the customers stayed"})[0]
        self.assertEqual(c["source"], "confident_voice")
        self.assertEqual(c["quote"], "the customers stayed")


class AssemblyFlagTests(unittest.TestCase):
    """The document is the full transcript whatever the flag says: the
    flag-off best-of assembly is removed (N48.3 Q13 A)."""

    class _Db(DocumentBuildTests._Db):
        def __init__(self, snips):
            super().__init__(snips)
            self.persisted = []

        def list_ideal_decisions(self, arc_id):
            return []

        def get_moment_suggestions_by_arc(self, arc_id):
            return {}

        def persist_auto_ideal_text(self, arc_id, text, *, take_count=None,
                                    document=None):
            self.persisted.append(text)
            return True

    def _assemble(self, flag):
        import services.ideal_text_block as mod
        snips = [{"id": S1, "start_offset_ms": 0, "language": "en",
                  "transcript": "um we started small"},
                 {"id": S2, "start_offset_ms": 10, "language": "en",
                  "transcript": "and we kept going"}]
        db = self._Db(snips)
        with patch.object(Config, "LIVING_TRANSCRIPT_ENABLED", bool(flag)):
            mod.maybe_assemble_ideal_text(ARC, database=db,
                                          require_target=False)
        return db.persisted

    def test_flag_on_and_off_persist_the_same_full_transcript(self):
        on, off = self._assemble(True), self._assemble(False)
        self.assertEqual(on, ["We started small and we kept going."])
        self.assertEqual(off, on)


class RelocateAfterBakeTests(unittest.TestCase):
    """FOUNDER-CRITICAL (2026-08-11): baking a change must not COST a piece.

    `relocate_pieces` re-anchors by an exact find of each piece's words and
    dropped the ones it could not find — but a bake CHANGES those words
    (a polish/replace swaps the phrase, an emphasis wraps {{orange:…}}
    around it). So the very piece the student just accepted a change on
    was the one that disappeared, and with it:

      · its slide index — the FE zips pieces 1:1 against the document's
        paragraphs to build the per-slide deck, so a short list collapses
        the whole deck into one untitled section (the 1:1 north star);
      · its slide identity and exact paragraph provenance.

    A piece is a REGION of the document, not a string that must still
    exist verbatim. These tests pin that."""

    class _Db(DocumentBuildTests._Db):
        def __init__(self, snips, rows, *, surfaced=()):
            super().__init__(snips)
            self._rows = rows
            self._surfaced = list(surfaced)

        def list_ideal_decisions(self, arc_id):
            return self._rows

        def get_coach_snippet_drafts(self, sid):
            return [{"snippet_id": s, "surfaced": True}
                    for s in self._surfaced]

    def _snips(self):
        return [{"id": S1, "start_offset_ms": 0, "language": "en",
                 "transcript": "we started small"},
                {"id": S2, "start_offset_ms": 10, "language": "en",
                 "transcript": "and this is the line that lands"}]


    def test_coarse_relocation_does_not_invent_feedback_or_exact_styling(self):
        from services.ideal_decision_ledger import normalize_phrase
        from services.ideal_text_block import assemble_transcript_document
        rows = [{"kind": "emphasize",
                 "target_phrase": normalize_phrase("the line that lands"),
                 "display_phrase": "the line that lands",
                 "decision": "approved", "source": "user_star"}]
        out = assemble_transcript_document(
            ARC, database=self._Db(self._snips(), rows, surfaced=[S2]))
        coarse = out["document"]["pieces"][1]
        self.assertEqual(coarse["anchor_grain"], "paragraph")
        self.assertEqual(out["key_moments"], [])
        # A bold on the coarse piece declines because it requires exact words.
        self.assertEqual(
            build_tracked_changes(out["text"], [coarse],
                                  {S2: {"kind": "emphasize", "why": "y"}}),
            [])


    def test_a_run_of_changed_pieces_keeps_every_one_in_order(self):
        # Two ADJACENT pieces both baked: neither may be dropped, the
        # spans stay ordered, non-overlapping, and inside the document.
        doc = "We started tiny and we kept at it. And then we shipped."
        pieces = [{"snippet_id": "a", "text": "We started small"},
                  {"snippet_id": "b", "text": "and we kept going."},
                  {"snippet_id": "c", "text": "And then we shipped."}]
        out = relocate_pieces(doc, pieces)
        self.assertEqual([p["snippet_id"] for p in out], ["a", "b", "c"])
        self.assertTrue(verify_spans({"text": doc, "pieces": out}))
        for prev, nxt in zip(out, out[1:]):
            self.assertLessEqual(prev["end"], nxt["start"])
        self.assertGreaterEqual(out[0]["start"], 0)
        self.assertLessEqual(out[-1]["end"], len(doc))


class ParagraphGrainFallbackTests(unittest.TestCase):
    """FOUNDER-CRITICAL (2026-08-12): a locked chunk took the whole feedback
    engine dark.

    Founder, after locking a chunk and recording again: "i did not get any
    feedback on this take, like zero ... there it is locked but no
    suggestions". And on the cause: "I actually didn't manually edit the
    text at all; I just locked the exact words the AI generated on the
    previous take. However ... because I recorded a *new* take, the new
    transcript didn't 100%% match the *old* locked text. This is definitely
    a structural flaw. If a chunk is locked (edited or not), the AI
    shouldn't drop the new feedback entirely just because the cross-take
    words shifted."

    `compose_locked` serves the LOCKED paragraph while the pieces come from
    the NEW take, so no piece is found, the anchor guard fires, and every
    downstream lane — tracked changes, slide zip, coach moments — receives
    an empty list. The fallback anchors those pieces to their PARAGRAPH,
    which `compose_locked` literally built the document out of, and tags
    them so that consumers needing word precision can decline."""

    def _locked_case(self):
        """The founder's case, minimally: three paragraphs, the middle one
        locked to the previous take's wording, all three pieces from the
        new take. Not one of them occurs in the served text."""
        doc = ("We started small in a garage.\n\n"
               "And then we shipped it fast.\n\n"
               "That is the whole story.")
        pieces = [{"snippet_id": "a", "take_session_id": T1,
                   "text": "We started off small in a garage."},
                  {"snippet_id": "b", "take_session_id": T1,
                   "text": "And then we shipped the thing really fast."},
                  {"snippet_id": "c", "take_session_id": T1,
                   "text": "That is basically the whole story."}]
        return doc, pieces

    def test_a_locked_paragraph_keeps_every_new_piece(self):
        doc, pieces = self._locked_case()
        out = relocate_pieces(doc, pieces, paragraph_fallback=True)
        self.assertEqual([p["snippet_id"] for p in out], ["a", "b", "c"])
        self.assertEqual([p["anchor_grain"] for p in out], ["paragraph"] * 3)
        self.assertEqual([doc[p["start"]:p["end"]] for p in out],
                         doc.split("\n\n"))

    def test_located_pieces_keep_word_grain_beside_a_coarse_neighbour(self):
        # Only the locked paragraph is coarse. The precision tag is
        # per-piece, so the other two keep every word-precise lane.
        doc = ("We started small.\n\n"
               "And then we shipped it fast.\n\n"
               "That is the whole story.")
        pieces = [{"snippet_id": "a", "text": "We started small."},
                  {"snippet_id": "b", "text": "And then we launched it."},
                  {"snippet_id": "c", "text": "That is the whole story."}]
        out = relocate_pieces(doc, pieces, paragraph_fallback=True)
        self.assertEqual([p["anchor_grain"] for p in out],
                         ["word", "paragraph", "word"])
        self.assertTrue(verify_spans({"text": doc, "pieces": out}))


try:
    from flask import Flask, request

    from routes.v2 import explore_ideal_text as v2_explore_ideal_text
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ServeChangesTests(unittest.TestCase):
    """The SD GET's `changes` block — present only with the flag ON,
    anchored on the SERVED text, absent (not empty) when off."""

    DOC = "We started small. And then we shipped it fast."

    def _block(self, *, flag, sugs=None, snips=None):
        _snips = snips if snips is not None else [
            {"id": S1, "start_offset_ms": 0,
             "transcript": "We started small.",
             "metrics": {"piece": {"slide_index": 0}}},
            {"id": S2, "start_offset_ms": 10,
             "transcript": "And then we shipped it fast.",
             "metrics": {"piece": {"slide_index": 0}}}]
        with patch.object(Config, "LIVING_TRANSCRIPT_ENABLED", bool(flag)), \
             patch.object(db.takes, "get_arc_sessions",
                          return_value=[{"id": T1, "take_index": 1,
                                         "recording_kind": "spoken"}]), \
             patch.object(db, "get_snippets_by_session",
                          return_value=_snips), \
             patch.object(db, "get_coach_snippet_drafts",
                          return_value=[]), \
             patch.object(db, "get_user_transcript_edits",
                          return_value=[]), \
             patch.object(db, "get_moment_suggestions_by_arc",
                          return_value=(sugs or {})), \
             patch.object(db, "get_suggestion_feedback_by_session",
                          return_value=[]), \
             patch.object(db, "v2_get_session_by_id", return_value={}):
            return v2_explore_ideal_text._tracked_changes_block(ARC, self.DOC)


    def test_flag_on_serves_anchored_changes(self):
        out = self._block(flag=True, sugs={
            S2: {"kind": "replace", "trigger": "polish",
                 "replacement_text": "And then we launched it fast.",
                 "why": "Tighter."}})
        c = out["changes"][0]
        self.assertEqual(c["kind"], "replace")
        self.assertEqual(self.DOC[c["span"]["start"]:c["span"]["end"]],
                         c["quote"])



class SameSlideRoutingTests(unittest.TestCase):
    """Feedback survives the Ideal Text being a REWRITE of what was said.

    PRODUCTION, 2026-09-17, founder's own arc. The worker generated and
    stored four suggestions for a take (`moment_suggestion: seen=5
    stored=4`). Not one reached the screen, because the read path logged:

        relocate_pieces: NO anchor survived — dropping 5 pieces rather
        than width-guessing them across 1045 chars. No paragraph fallback
        available: fallback=True paragraphs=8 pieces=5

    The spoken sentences are not in the Ideal Text verbatim — it is a
    rewrite of them — so text anchoring finds nothing, and the paragraph
    fallback needs the counts to match, which a rewrite breaks. The join
    that makes the mapping provable existed and was not being read: which
    SLIDE each paragraph is about.
    """

    # Eight paragraphs of Ideal Text across three slides, none of them the
    # words anyone actually spoke — the shape that broke.
    DOC = "\n\n".join(f"Rewritten paragraph number {i}." for i in range(8))
    PARAGRAPH_PROVENANCE = [
        {"slide_index": 0}, {"slide_index": 0}, {"slide_index": 0},
        {"slide_index": 1}, {"slide_index": 1},
        {"slide_index": 2}, {"slide_index": 2}, {"slide_index": 2},
    ]

    def _regions(self):
        from services.transcript_document import slide_regions
        return slide_regions(self.DOC, self.PARAGRAPH_PROVENANCE)


    def test_a_piece_whose_slide_is_not_in_this_document_is_DROPPED(self):
        from services.transcript_document import relocate_pieces
        pieces = [
            {"snippet_id": "a", "text": "Said on a slide that is here.",
             "slide_index": 1},
            {"snippet_id": "b", "text": "Said on slide nine.",
             "slide_index": 9},
            {"snippet_id": "c", "text": "Said on no slide at all.",
             "slide_index": None},
        ]
        out = relocate_pieces(self.DOC, pieces, paragraph_fallback=True,
                              slide_regions=self._regions())
        self.assertEqual([p["snippet_id"] for p in out], ["a"])


if __name__ == "__main__":
    unittest.main()
