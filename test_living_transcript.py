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

from services.tracked_changes import (
    build_tracked_changes, key_phrases_from_say_it_stronger, verify_changes,
)
from services.transcript_document import (
    build_transcript_document, paragraph_spans, relocate_pieces, verify_spans,
)
from services.transcript_smoothing import (
    finalize_document, hesitations_for, smooth_piece, strip_fillers,
    tidy_piece,
)


def smooth_verbatim(text, language="en"):
    """Test helper: the piece pass followed by the DOCUMENT finish — the
    two are deliberately separate in production (a piece is often
    mid-sentence, so it must not gain a full stop of its own)."""
    return finalize_document(smooth_piece(text, language))

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
        self.assertEqual(strip_fillers("um hello", "en").strip(), "hello")
        self.assertEqual(tidy_piece("hello  world"), "hello world")

    def test_a_piece_never_gains_its_own_sentence(self):
        # THE architectural fence (review finding): pieces are cut on
        # slide advances and hard caps, so most are mid-sentence. A piece
        # must never gain a terminal mark or an initial capital of its
        # own — a document made of three cut pieces reads as ONE
        # sentence, exactly as it was spoken.
        pieces = ["the thing about the U.S. market is",
                  "that it never really", "stops moving"]
        doc = finalize_document(
            " ".join(smooth_piece(p, "en") for p in pieces))
        self.assertEqual(
            doc, "The thing about the U.S. market is that it never "
                 "really stops moving.")

    def test_language_aware_hesitations_never_delete_real_words(self):
        # "um" is a real word in German and Portuguese — deleting it
        # there removes the speaker's words (L1 breach, review finding).
        self.assertEqual(smooth_verbatim("Es geht um Geld und um Zeit",
                                         "de"),
                         "Es geht um Geld und um Zeit.")
        self.assertEqual(smooth_verbatim("um problema muito grande", "pt"),
                         "Um problema muito grande.")
        # …and an UNKNOWN language uses the intersection-safe set.
        self.assertIn("um", smooth_verbatim("es geht um Geld uh ja", None))
        # English still loses its fillers.
        self.assertEqual(smooth_verbatim("um so I uh built it", "en"),
                         "So I built it.")
        self.assertNotIn("um", hesitations_for(None))

    def test_abbreviations_do_not_trigger_capitals(self):
        for src, want in (
                ("the U.S. market is huge. we won",
                 "The U.S. market is huge. We won."),
                ("I asked Dr. smith about it",
                 "I asked Dr. smith about it.")):
            self.assertEqual(finalize_document(src), want)

    def test_dangling_punctuation_is_not_double_terminated(self):
        self.assertEqual(finalize_document("we tried it, tested it,"),
                         "We tried it, tested it.")
        self.assertEqual(finalize_document('he said "we win"'),
                         'He said "we win".')


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
            {"id": S2, "start_offset_ms": 4000, "language": "en",
             "transcript": "and then we uh shipped it"},
            {"id": S1, "start_offset_ms": 0, "language": "en",
             "transcript": "um we started small"},
        ]

    def test_full_text_in_speech_order_with_valid_spans(self):
        doc = build_transcript_document(ARC, database=self._Db(self._snips()))
        # ONE flowing sentence: the pieces are mid-sentence cuts, so no
        # fabricated full stop at the seam (review finding).
        self.assertEqual(doc["text"],
                         "We started small and then we shipped it.")
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
        self.assertIn("and then we launched", doc["text"])

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
    # Pieces carry their CHARACTER SPAN — build_tracked_changes anchors on
    # it, never on a text search (the mis-anchor defect the review found).
    PIECES = [{"snippet_id": S1, "text": "We started small.",
               "take_session_id": T1, "start": 0, "end": 17},
              {"snippet_id": S2, "text": "And then we shipped it fast.",
               "take_session_id": T1, "start": 18, "end": 46}]

    def _changes(self, sugs, **kw):
        return build_tracked_changes(self.DOC, self.PIECES, sugs, **kw)

    def test_polish_replace_anchors_on_the_changed_words_only(self):
        sugs = {S2: {"kind": "replace", "trigger": "polish",
                     "replacement_text": "And then we launched it fast.",
                     "why": "Tighter."}}
        c = self._changes(sugs)[0]
        self.assertEqual(c["kind"], "replace")
        self.assertEqual(c["source"], "polish")
        # FE contract ask #2 (2026-07-21): a replace/bold carries its
        # take's session so the FE can call suggestion-feedback (which
        # requires session_id) — without it the change is a dead button.
        self.assertEqual(c["take_session_id"], T1)
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

    def test_emphasis_narrows_to_the_key_phrase_span(self):
        # T3 (founder 2026-07-23): emphasis bolds only the say-it-stronger
        # key phrase, not the whole fragment.
        sugs = {S2: {"kind": "emphasize", "why": "It lands."}}
        kp = {S2: ["shipped it fast"]}
        c = build_tracked_changes(self.DOC, self.PIECES, sugs,
                                  key_phrases_by_snippet=kp)[0]
        self.assertEqual(c["kind"], "bold")
        self.assertEqual(c["quote"], "shipped it fast")   # not the piece
        self.assertLess(len(c["quote"]),
                        len("And then we shipped it fast."))
        self.assertEqual(self.DOC[c["span"]["start"]:c["span"]["end"]],
                         c["quote"])
        self.assertTrue(verify_changes(self.DOC, [c]))

    def test_emphasis_without_key_phrase_falls_back_to_fragment(self):
        # No say-it-stronger signal → the whole fragment (today's
        # behavior), never a guessed span.
        sugs = {S2: {"kind": "emphasize", "why": "It lands."}}
        c = build_tracked_changes(self.DOC, self.PIECES, sugs,
                                  key_phrases_by_snippet={})[0]
        self.assertEqual(c["quote"], "And then we shipped it fast.")

    def test_emphasis_key_phrase_must_be_in_the_window(self):
        # A key phrase from ANOTHER fragment never bleeds in.
        sugs = {S2: {"kind": "emphasize", "why": "It lands."}}
        kp = {S2: ["started small"]}   # belongs to S1's window, not S2's
        c = build_tracked_changes(self.DOC, self.PIECES, sugs,
                                  key_phrases_by_snippet=kp)[0]
        self.assertEqual(c["quote"], "And then we shipped it fast.")

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

    def test_missing_piece_text_drops_the_change(self):
        # The piece was edited/baked away — never point at wrong words.
        pieces = [{"snippet_id": S1, "text": "words that are not there",
                   "start": 0, "end": 24}]
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



class ReasonKeyTests(unittest.TestCase):
    """The reason line rides a KEY; the FE holds the copy (founder 2026-08-07).

    Before this, the star lane emitted only the model's free-text `why`, which
    the FE validates against a closed vocabulary — so it always resolved to
    null and NO reason line ever rendered from this lane. Fixing it by sending
    the free text would have put un-signed-off model prose on a student's
    screen (LIVE LOOP)."""

    DOC = TrackedChangeTests.DOC
    PIECES = TrackedChangeTests.PIECES

    def _key(self, sug, sid=S2):
        c = build_tracked_changes(self.DOC, self.PIECES, {sid: sug})
        return c[0].get("why_key") if c else None

    def test_a_word_change_gets_the_clarity_key(self):
        self.assertEqual(self._key({
            "kind": "replace", "trigger": "polish",
            "replacement_text": "And then we launched it fast."}), "clarity")

    def test_a_say_it_stronger_replace_is_also_a_word_change(self):
        self.assertEqual(self._key({
            "kind": "replace",
            "replacement_text": "And then we launched it fast."}), "clarity")

    def test_an_emphasis_gets_the_emphasis_key(self):
        self.assertEqual(self._key({"kind": "emphasize"}), "emphasis")

    def test_the_split_is_the_layer_boundary_not_the_lane(self):
        """Composition (changes words) vs accentuation (styles words already
        there) — SPEC-parts-locking-and-layers §2. The copy is only true on
        the right side of it: "helps your main point stand out" says nothing
        about a word swap."""
        replace = self._key({"kind": "replace", "replacement_text": "x y z"})
        bold = self._key({"kind": "emphasize"})
        self.assertNotEqual(replace, bold)

    def test_profanity_gets_NO_key(self):
        """Its lead line already carries the whole message ("this might land
        differently than you meant"). A clarity claim on top would be a second
        reason nobody offered."""
        self.assertIsNone(self._key({
            "kind": "replace", "trigger": "profanity",
            "replacement_text": "And then we shipped it fast."}))

    def test_advice_gets_NO_key(self):
        self.assertIsNone(self._key({"kind": "delivery",
                                     "trigger": "pace_fast"}, sid=S1))

    def test_a_comparison_key_never_reaches_this_lane(self):
        """The four SwapWhy keys are all cross-take copy ("This take carried
        more energy…"). There is no second take here, so one arriving would be
        a sentence about something that did not happen."""
        for sug in ({"kind": "replace", "trigger": "polish",
                     "replacement_text": "And then we launched it fast."},
                    {"kind": "emphasize"}):
            self.assertNotIn(self._key(sug),
                             ("energy", "steadiness", "coverage", "overall"))

    def test_the_model_free_text_is_still_not_the_reason(self):
        """`why` stays on the payload (a row carrying a real key works
        unchanged) but it is not what renders — the FE reads why_key first."""
        c = build_tracked_changes(self.DOC, self.PIECES, {S2: {
            "kind": "replace", "trigger": "polish",
            "replacement_text": "And then we launched it fast.",
            "why": "Tighter, and it lands better."}})[0]
        self.assertEqual(c["why"], "Tighter, and it lands better.")
        self.assertEqual(c["why_key"], "clarity")



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


class SpanRelocationTests(unittest.TestCase):
    """After a bake/edit the document text changes — pieces re-anchor
    MONOTONICALLY so repeated wording can never steal another piece's
    span (the review's first-occurrence defect)."""

    def test_repeated_wording_keeps_its_own_anchor(self):
        from services.transcript_document import relocate_pieces
        doc = "We win. We build. We win. We ship."
        pieces = [{"snippet_id": "a", "text": "We win."},
                  {"snippet_id": "b", "text": "We build."},
                  {"snippet_id": "c", "text": "We win."},
                  {"snippet_id": "d", "text": "We ship."}]
        out = relocate_pieces(doc, pieces)
        self.assertEqual([(p["start"], p["end"]) for p in out],
                         [(0, 7), (8, 17), (18, 25), (26, 34)])
        for p in out:
            self.assertEqual(doc[p["start"]:p["end"]], p["text"])

    def test_baked_over_piece_keeps_its_own_region_never_a_neighbour_s(self):
        # WAS "…is_dropped_not_mispointed" and asserted the drop. The founder
        # reversed that half on 2026-08-11: dropping the piece the bake landed
        # on costs its slide (the FE zips pieces 1:1 to build the deck) and any
        # coach moment on it. The half this test was really protecting — a
        # piece must NEVER be pointed at another piece's words — is unchanged
        # and asserted below: "a" takes its OWN region, in its new spelling.
        from services.transcript_document import relocate_pieces
        doc = "We started big. Then we shipped."
        pieces = [{"snippet_id": "a", "text": "We started small."},
                  {"snippet_id": "b", "text": "Then we shipped."}]
        out = relocate_pieces(doc, pieces)
        self.assertEqual([p["snippet_id"] for p in out], ["a", "b"])
        self.assertEqual(doc[out[0]["start"]:out[0]["end"]],
                         "We started big.")
        self.assertEqual(out[0]["text"], "We started big.")
        self.assertLessEqual(out[0]["end"], out[1]["start"])
        self.assertEqual(doc[out[1]["start"]:out[1]["end"]],
                         "Then we shipped.")


class OverlapTests(unittest.TestCase):
    """Two lanes may fire on the same words — the FE must never get
    overlapping strikes (review finding)."""

    def test_overlapping_changes_are_dropped_narrowest_first(self):
        from services.tracked_changes import drop_overlaps
        wide = {"id": "w", "span": {"start": 0, "end": 20}, "quote": "x"}
        narrow = {"id": "n", "span": {"start": 0, "end": 5}, "quote": "y"}
        later = {"id": "l", "span": {"start": 25, "end": 30}, "quote": "z"}
        out = drop_overlaps([wide, narrow, later])
        self.assertEqual([c["id"] for c in out], ["n", "l"])

    def test_non_overlapping_all_survive_in_order(self):
        from services.tracked_changes import drop_overlaps
        a = {"id": "a", "span": {"start": 10, "end": 15}}
        b = {"id": "b", "span": {"start": 0, "end": 5}}
        self.assertEqual([c["id"] for c in drop_overlaps([a, b])],
                         ["b", "a"])


class KeyMomentPreservationTests(unittest.TestCase):
    """Transcript mode must NOT dark the explanations lane — a
    coach-surfaced piece stays a key moment (review finding: the only
    paid surface became unreachable)."""

    class _Db(DocumentBuildTests._Db):
        def list_ideal_decisions(self, arc_id):
            return []

        def get_coach_snippet_drafts(self, sid):
            return [{"snippet_id": S2, "surfaced": True}]

    def test_surfaced_piece_survives_as_a_key_moment(self):
        from services.ideal_text_block import assemble_transcript_document
        snips = [{"id": S1, "start_offset_ms": 0, "language": "en",
                  "transcript": "we started small"},
                 {"id": S2, "start_offset_ms": 10, "language": "en",
                  "transcript": "and this is the line that lands"}]
        out = assemble_transcript_document(ARC, database=self._Db(snips))
        self.assertEqual([m["snippet_id"] for m in out["key_moments"]],
                         [S2])
        self.assertIn(out["key_moments"][0]["anchor"], out["text"])


class ApprovedChangeBakesTests(unittest.TestCase):
    """The founder's core promise: "when I approve it the crossed text
    disappears and only the new one stays". The ledger bake must reach
    the ASSEMBLED document, and the surviving pieces must re-anchor."""

    class _Db(DocumentBuildTests._Db):
        def __init__(self, snips, rows):
            super().__init__(snips)
            self._rows = rows

        def list_ideal_decisions(self, arc_id):
            return self._rows

    def test_approved_change_is_applied_and_anchors_survive(self):
        from services.ideal_decision_ledger import normalize_phrase
        from services.ideal_text_block import assemble_transcript_document
        from services.transcript_document import verify_spans
        snips = [{"id": S1, "start_offset_ms": 0, "language": "en",
                  "transcript": "we started small"},
                 {"id": S2, "start_offset_ms": 10, "language": "en",
                  "transcript": "and we kept going"}]
        rows = [{"kind": "replace",
                 "target_phrase": normalize_phrase("we started small"),
                 "display_phrase": "We started small",
                 "replacement_text": "We started tiny",
                 "decision": "approved", "source": "user_star"}]
        out = assemble_transcript_document(ARC, database=self._Db(snips, rows))
        self.assertIn("We started tiny", out["text"])
        self.assertNotIn("We started small", out["text"])
        # the untouched piece keeps an exact anchor on the NEW text
        self.assertTrue(verify_spans({"text": out["text"],
                                      "pieces": out["document"]["pieces"]}))


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
      · its coach key moment, when the piece was a surfaced breakthrough —
        the note the founder requires to survive "even on a locked screen".

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

    def test_an_approved_replace_does_not_cost_the_piece_it_changed(self):
        from services.ideal_decision_ledger import normalize_phrase
        from services.ideal_text_block import assemble_transcript_document
        rows = [{"kind": "replace",
                 "target_phrase": normalize_phrase("we started small"),
                 "display_phrase": "We started small",
                 "replacement_text": "We started tiny",
                 "decision": "approved", "source": "user_star"}]
        out = assemble_transcript_document(
            ARC, database=self._Db(self._snips(), rows))
        pieces = out["document"]["pieces"]
        # THE regression: two snippets in, two pieces out. The changed one
        # is still there — pointing at its NEW words.
        self.assertEqual([p["snippet_id"] for p in pieces], [S1, S2])
        self.assertTrue(verify_spans({"text": out["text"], "pieces": pieces}))
        self.assertEqual(pieces[0]["text"], "We started tiny")

    def test_an_approved_emphasis_does_not_cost_the_coach_key_moment(self):
        from services.ideal_decision_ledger import normalize_phrase
        from services.ideal_text_block import assemble_transcript_document
        rows = [{"kind": "emphasize",
                 "target_phrase": normalize_phrase("the line that lands"),
                 "display_phrase": "the line that lands",
                 "decision": "approved", "source": "user_star"}]
        out = assemble_transcript_document(
            ARC, database=self._Db(self._snips(), rows, surfaced=[S2]))
        self.assertIn("{{orange:", out["text"])  # the bake really landed
        pieces = out["document"]["pieces"]
        self.assertEqual([p["snippet_id"] for p in pieces], [S1, S2])
        # The founder's rule: the coach's moment survives the fold, and its
        # anchor still indexes the SERVED text (that is the FE's join).
        self.assertEqual([m["snippet_id"] for m in out["key_moments"]], [S2])
        self.assertIn(out["key_moments"][0]["anchor"], out["text"])
        # …AND the piece it rode in on is genuinely coarse — this test is
        # what caught me trying to make coach moments decline a coarse
        # anchor (2026-08-12), so pin the precondition or the guard is
        # vacuous the next time someone "tightens" it.
        self.assertEqual(pieces[1]["anchor_grain"], "paragraph")

    def test_the_coach_moment_is_the_ONE_lane_that_rides_a_coarse_anchor(self):
        # The asymmetry, asserted on ONE document so both halves are visible
        # at once: the SAME coarse piece keeps its coach moment and loses its
        # emphasis. A moment is per-SNIPPET — one slide's spoken chunk — and
        # the relocation is 1:1, so a paragraph-wide anchor still points at
        # the chunk the coach marked. A bold means "these exact words", and
        # at this grain that would accent the entire chunk.
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
        # Half one — the moment rode it.
        self.assertEqual([m["snippet_id"] for m in out["key_moments"]], [S2])
        # Half two — a bold on the very same piece declines.
        self.assertEqual(
            build_tracked_changes(out["text"], [coarse],
                                  {S2: {"kind": "emphasize", "why": "y"}}),
            [])

    def test_a_piece_whose_words_all_went_is_still_dropped(self):
        # The original intent, kept: a piece with NOTHING left to point at
        # has no region either. Deletion is the student's own edit lane.
        doc = "We started tiny."
        pieces = [{"snippet_id": S1, "text": "We started tiny.",
                   "start": 0, "end": 16},
                  {"snippet_id": S2, "text": "and this is the line",
                   "start": 17, "end": 37}]
        out = relocate_pieces(doc, pieces)
        self.assertEqual([p["snippet_id"] for p in out], [S1])

    def test_repeated_wording_still_cannot_steal_another_anchor(self):
        # The monotonic rule the original fix was written for — unchanged.
        doc = "we win. we win. we win."
        pieces = [{"snippet_id": "a", "text": "we win."},
                  {"snippet_id": "b", "text": "we win."},
                  {"snippet_id": "c", "text": "we win."}]
        out = relocate_pieces(doc, pieces)
        self.assertEqual([(p["start"], p["end"]) for p in out],
                         [(0, 7), (8, 15), (16, 23)])

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

    def test_ZERO_surviving_anchors_drops_rather_than_width_guessing(self):
        # THE ANCHOR GUARD (2026-08-12). Pass 2 is a repair, and the located
        # neighbours are what make it one — they bound the gap. When NOTHING
        # anchors (a take recomposed the text, a coach retyped it, the wrong
        # arc's pieces arrived) the run is the whole list, both bounds are
        # invented, and the pieces get cut at width-proportional positions
        # derived from nothing at all.
        #
        # It passes verify_spans, because the text is re-read from the
        # document — which is exactly what made it dangerous. The FE zips
        # pieces 1:1 to paragraphs for slide attachment and hangs the coach's
        # chip on a piece's words, so the survivors are chips on words the
        # coach never spoke about, indistinguishable from real ones.
        doc = "Completely different words. Nothing here was ever said before."
        pieces = [{"snippet_id": "a", "text": "We started small"},
                  {"snippet_id": "b", "text": "and we kept going."},
                  {"snippet_id": "c", "text": "And then we shipped."}]
        self.assertEqual(relocate_pieces(doc, pieces), [])

    def test_a_SINGLE_piece_may_still_take_the_whole_document(self):
        # The one case that is not a guess: with one piece, "the piece is the
        # document" is a tautology, not an invented split point. Dropping it
        # would cost the slide index on every one-piece arc — the take-1 case.
        doc = "We started tiny."
        out = relocate_pieces(doc, [{"snippet_id": "a",
                                     "text": "We started small"}])
        self.assertEqual([p["snippet_id"] for p in out], ["a"])
        self.assertTrue(verify_spans({"text": doc, "pieces": out}))

    def test_ONE_surviving_anchor_still_repairs_its_neighbours(self):
        # The guard must not overreach into the case it was written to
        # protect: a single real anchor bounds every run beside it, so the
        # baked pieces around it are still located, not dropped.
        doc = "We started tiny and we kept at it. And then we shipped."
        pieces = [{"snippet_id": "a", "text": "We started small"},
                  {"snippet_id": "b", "text": "and we kept going."},
                  {"snippet_id": "c", "text": "And then we shipped."}]
        out = relocate_pieces(doc, pieces)
        self.assertEqual([p["snippet_id"] for p in out], ["a", "b", "c"])

    def test_an_untouched_document_relocates_byte_for_byte(self):
        doc = "We started small and we kept going."
        pieces = [{"snippet_id": "a", "text": "We started small"},
                  {"snippet_id": "b", "text": "and we kept going."}]
        out = relocate_pieces(doc, pieces)
        self.assertEqual([(p["start"], p["end"]) for p in out],
                         [(0, 16), (17, 35)])
        self.assertEqual([p["text"] for p in out],
                         ["We started small", "and we kept going."])


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

    # ── paragraph_spans ────────────────────────────────────────────────
    def test_paragraph_spans_are_the_same_split_the_rest_of_the_app_uses(self):
        doc = "One.\n\nTwo.\n\nThree."
        self.assertEqual(paragraph_spans(doc), [(0, 4), (6, 10), (12, 18)])
        for lo, hi in paragraph_spans(doc):
            self.assertEqual(doc[lo:hi].strip(), doc[lo:hi])

    def test_paragraph_spans_skip_blank_blocks_and_trim_whitespace(self):
        doc = "\n\n  One.  \n\n\n\nTwo.\n\n   \n\n"
        spans = paragraph_spans(doc)
        self.assertEqual([doc[lo:hi] for lo, hi in spans], ["One.", "Two."])

    def test_paragraph_spans_on_junk_is_empty_never_raises(self):
        for junk in (None, 42, "", "   ", {"a": 1}):
            self.assertEqual(paragraph_spans(junk), [])

    # ── the fallback itself ────────────────────────────────────────────
    def test_the_locked_chunk_no_longer_takes_every_piece_with_it(self):
        doc, pieces = self._locked_case()
        # Today's behaviour, unchanged when nobody asks for the fallback:
        # the anchor guard drops all three rather than width-guessing.
        self.assertEqual(relocate_pieces(doc, pieces), [])
        # With the fallback, all three survive — on their paragraphs.
        out = relocate_pieces(doc, pieces, paragraph_fallback=True)
        self.assertEqual([p["snippet_id"] for p in out], ["a", "b", "c"])
        self.assertEqual([p["anchor_grain"] for p in out],
                         ["paragraph"] * 3)
        self.assertTrue(verify_spans({"text": doc, "pieces": out}))

    def test_a_fallback_piece_reads_its_text_back_from_the_document(self):
        # The piece is a REGION; its text must be what the student is
        # actually looking at, or every downstream words-still-there check
        # (verify_spans, build_tracked_changes) would reject it.
        doc, pieces = self._locked_case()
        out = relocate_pieces(doc, pieces, paragraph_fallback=True)
        self.assertEqual([p["text"] for p in out],
                         ["We started small in a garage.",
                          "And then we shipped it fast.",
                          "That is the whole story."])

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

    def test_a_count_mismatch_refuses_the_fallback(self):
        # 1:1 or nothing — the same safe-ahead rule the slide zip follows.
        # Disagreeing about what the paragraphs ARE makes position a guess
        # again, and the guard is right to drop.
        doc = "One paragraph only, but three pieces claim it."
        pieces = [{"snippet_id": "a", "text": "Completely other words."},
                  {"snippet_id": "b", "text": "Nothing here matches."},
                  {"snippet_id": "c", "text": "Nor does this."}]
        self.assertEqual(
            relocate_pieces(doc, pieces, paragraph_fallback=True), [])

    def test_the_fallback_is_opt_in_untouched_callers_are_byte_for_byte(self):
        doc = "We started small and we kept going."
        pieces = [{"snippet_id": "a", "text": "We started small"},
                  {"snippet_id": "b", "text": "and we kept going."}]
        out = relocate_pieces(doc, pieces)
        self.assertEqual([(p["start"], p["end"]) for p in out],
                         [(0, 16), (17, 35)])

    def test_a_gap_shared_span_is_coarse_too(self):
        # Pass 2's width interpolation is LESS precise than a paragraph, so
        # it answers "may I trust this to the word?" the same way.
        doc = "We started tiny and we kept at it. And then we shipped."
        pieces = [{"snippet_id": "a", "text": "We started small"},
                  {"snippet_id": "b", "text": "and we kept going."},
                  {"snippet_id": "c", "text": "And then we shipped."}]
        out = relocate_pieces(doc, pieces)
        by_id = {p["snippet_id"]: p["anchor_grain"] for p in out}
        self.assertEqual(by_id, {"a": "paragraph", "b": "paragraph",
                                 "c": "word"})


class GrainAwareChangeTests(unittest.TestCase):
    """Step 2 of the same founder fix: the fallback keeps feedback FLOWING,
    and the grain tag keeps it HONEST.

    A coarse piece is exact in its own coordinate system but has lost word
    precision. Any change that RE-WRITES or STYLES words must therefore be
    able to point at the exact phrase inside that paragraph — otherwise its
    quote degenerates to the entire paragraph and the student is shown
    "strike all of this" or "bold all of this", a claim nobody made.
    `advice` is the exception on purpose: it alters nothing and its span is
    a pointer at the region the coaching is about."""

    DOC = ("We started small in a garage.\n\n"
           "And then we shipped it fast.")

    def _pieces(self, grain):
        return [{"snippet_id": S1, "take_session_id": T1, "start": 31,
                 "end": 59, "text": "And then we shipped it fast.",
                 "anchor_grain": grain}]

    def _changes(self, sug, grain="paragraph", **kw):
        return build_tracked_changes(self.DOC, self._pieces(grain),
                                     {S1: sug}, **kw)

    def test_the_span_the_test_pins_is_really_the_second_paragraph(self):
        self.assertEqual(self.DOC[31:59], "And then we shipped it fast.")

    # ── the declines ───────────────────────────────────────────────────
    def test_a_whole_paragraph_replace_is_declined(self):
        # "Strike this entire locked chunk, here is one sentence instead."
        sug = {"kind": "replace", "trigger": "prior_take",
               "replacement_text": "A completely different sentence.",
               "why": "Stronger."}
        self.assertEqual(self._changes(sug), [])
        # …and at word grain it is exactly what it always was.
        c = self._changes(sug, grain="word")[0]
        self.assertEqual(c["quote"], "And then we shipped it fast.")

    def test_a_whole_paragraph_bold_is_declined(self):
        # T3's whole-fragment problem, at maximum width.
        sug = {"kind": "emphasize", "why": "This lands."}
        self.assertEqual(self._changes(sug), [])
        self.assertEqual(self._changes(sug, grain="word")[0]["kind"], "bold")

    def test_an_untagged_piece_is_word_grain_nothing_regresses(self):
        # Every piece written before this change carries no tag at all.
        pieces = [{"snippet_id": S1, "take_session_id": T1, "start": 31,
                   "end": 59, "text": "And then we shipped it fast."}]
        out = build_tracked_changes(
            self.DOC, pieces, {S1: {"kind": "emphasize", "why": "y"}})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["quote"], "And then we shipped it fast.")

    # ── what still flows ───────────────────────────────────────────────
    def test_advice_rides_the_paragraph(self):
        # The lane that must NOT go dark: it changes no words, so the
        # paragraph is an honest region for it to point at.
        for kind, source in (("delivery", "delivery"),
                             ("structure", "structural")):
            c = self._changes({"kind": kind, "trigger": "pace"})[0]
            self.assertEqual((c["kind"], c["source"]), ("advice", source))
            self.assertEqual(c["span"], {"start": 31, "end": 59})
            self.assertTrue(verify_changes(self.DOC, [c]))

    def test_a_polish_that_still_narrows_survives_word_exact(self):
        # The founder's own case: he locked the AI's words and re-recorded
        # nearly the same thing, so the polish delta is still a small,
        # exact phrase INSIDE the locked paragraph. Those words really are
        # on screen, so the strike is honest and the change is served.
        sug = {"kind": "replace", "trigger": "polish",
               "replacement_text": "And then we launched it fast.",
               "why": "Tighter."}
        c = self._changes(sug)[0]
        self.assertEqual(c["quote"], "shipped")
        self.assertEqual(self.DOC[c["span"]["start"]:c["span"]["end"]],
                         "shipped")
        self.assertTrue(verify_changes(self.DOC, [c]))

    def test_an_emphasis_that_finds_its_key_phrase_survives(self):
        c = self._changes({"kind": "emphasize", "why": "y"},
                          key_phrases_by_snippet={S1: ["shipped it fast"]})[0]
        self.assertEqual(c["kind"], "bold")
        self.assertEqual(c["quote"], "shipped it fast")
        self.assertTrue(verify_changes(self.DOC, [c]))

    def test_verify_changes_holds_across_every_grain(self):
        for grain in ("word", "paragraph"):
            for sug in ({"kind": "delivery", "trigger": "pace"},
                        {"kind": "replace", "trigger": "polish",
                         "replacement_text": "And then we launched it fast."},
                        {"kind": "emphasize"}):
                out = self._changes(sug, grain=grain)
                self.assertTrue(verify_changes(self.DOC, out))


class ApprovalKeyRegressionTests(unittest.TestCase):
    """Founder bug 2026-07-22: "the system does not accept my approval".

    The approval SAVED but did nothing: the ledger was keyed on the RAW
    snippet transcript while the document holds the SMOOTHED text, so the
    bake could never locate the phrase. The key must be the phrase AS IT
    APPEARS IN THE DOCUMENT."""

    RAW = "um we started small in a tiny room"

    def _doc_and_piece(self):
        from services.transcript_smoothing import (
            finalize_document, smooth_piece,
        )
        piece = smooth_piece(self.RAW, "en")
        return finalize_document(piece), piece

    def _row(self, key):
        from services.ideal_decision_ledger import normalize_phrase
        return {"kind": "replace", "target_phrase": normalize_phrase(key),
                "display_phrase": key,
                "replacement_text": "We started in a garage",
                "decision": "approved", "source": "user_star"}

    def test_document_phrase_key_applies_the_approval(self):
        from services.ideal_decision_ledger import bake_piece
        doc, piece = self._doc_and_piece()
        self.assertIn("We started in a garage",
                      bake_piece(doc, [self._row(piece)]))

    def test_raw_transcript_key_is_the_regression(self):
        # Pins WHY the fix is needed: the raw words are not in the
        # document, so a raw-keyed row is inert.
        from services.ideal_decision_ledger import bake_piece
        doc, _ = self._doc_and_piece()
        self.assertEqual(bake_piece(doc, [self._row(self.RAW)]), doc)

    def test_full_loop_approval_changes_the_assembled_document(self):
        # End to end: approve -> ledger row -> next assembly shows it.
        from services.ideal_text_block import assemble_transcript_document
        from services.transcript_document import build_transcript_document

        class _Db(DocumentBuildTests._Db):
            rows = []

            def list_ideal_decisions(self, arc_id):
                return self.rows

        snips = [{"id": S1, "start_offset_ms": 0, "language": "en",
                  "transcript": self.RAW}]
        db = _Db(snips)
        # what the serve layer showed the user
        piece = build_transcript_document(ARC, database=db)["pieces"][0]
        # what the feedback endpoint now records (document phrase, NOT raw)
        db.rows = [self._row(piece["text"])]
        out = assemble_transcript_document(ARC, database=db)
        self.assertIn("We started in a garage", out["text"])
        self.assertNotIn("tiny room", out["text"])


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
