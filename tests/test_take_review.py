"""Later-Take Ideal Text review finalization and immutable feedback sets."""
from __future__ import annotations

import unittest

from services.take_feedback_set import (
    claim_feedback_set,
    filter_candidates_to_selected,
    filter_to_selected,
    selected_keys,
)
from services.ideal_text_confirmation import IdealTextUnconfirmedError
from services.take_review import (
    TakeReviewFinalizationError,
    finalize_later_take_review,
)
from services.take_feedback_candidates import (
    current_take_confident_voice_candidate,
)


class _ReviewDb:
    def __init__(self):
        self.session = {
            "id": "take-2",
            "arc_id": "arc-1",
            "user_id": "user-1",
            "take_index": 2,
            "recording_kind": "spoken",
            "paired_session_id": None,
        }
        self.ideal = {
            "arc_id": "arc-1",
            "version": 1,
            "auto_text": "Canonical words",
            "text": "Canonical words",
        }
        self.edit = {"text": "My exact words", "version": 1}
        self.snapshots = {}
        self.suggestions = {}

    def v2_get_session_by_id(self, session_id):
        return self.session if session_id == self.session["id"] else None

    def get_coach_arc_ideal_text(self, arc_id):
        return dict(self.ideal) if arc_id == "arc-1" else None

    @property
    def ideal_text(self):
        # audit Q-A2: production now calls database.ideal_text.<method>();
        # this fake implements those methods directly on itself.
        return self

    def get_user_ideal_edit(self, arc_id, user_id):
        return dict(self.edit) if self.edit else None

    def get_moment_suggestions_by_arc(self, arc_id):
        return self.suggestions

    def finalize_ideal_text_take(
        self, arc_id, owner, session_id, index, moments,
        auto_text=None, document=None,
    ):
        # Mirrors finalize_ideal_text_take_v2: with rebuilt words the new
        # Take wins and the owner edit stays behind; without, v1 exactly.
        self.ideal["version"] = index
        if auto_text:
            self.ideal["auto_text"] = auto_text
            self.ideal["document"] = document
            text = auto_text
        else:
            if self.edit and self.edit["version"] == 1:
                self.edit["version"] = index
            text = self.edit["text"] if self.edit else self.ideal["auto_text"]
        self.snapshots[index] = {
            "arc_id": arc_id,
            "version": index,
            "text": text,
            "moments": moments,
        }
        return {
            "arc_id": arc_id,
            "take_session_id": session_id,
            "take_index": index,
            "version": index,
            "rebuilt": bool(auto_text),
            "text_confirmed": True,
        }

    # Paragraph identity and Slide helper words (take_rebuild).
    parts: list = []
    slide_rows: dict = {}

    def get_ideal_text_parts(self, arc_id, user_id, with_lock=False):
        return [dict(p) for p in self.parts]

    revisions: list = []

    def replace_ideal_text_parts(self, arc_id, user_id, parts,
                                 revision_action=None,
                                 revision_take_session_id=None,
                                 revision_review_version=None):
        # As production does: the helper-word columns carry by Paragraph id
        # across the rewrite (services.db._carried_root, contract 14), and a
        # revision is appended for each Paragraph whose words or lock changed
        # or that is new.
        from services.db import _carried_root
        previous = {str(p.get("id")): p for p in self.parts}
        if revision_action:
            for p in parts:
                before = previous.get(str(p.get("id")))
                if (before is None or before.get("text") != p.get("text")
                        or bool(before.get("locked_at"))
                        != bool(p.get("locked_at"))):
                    self.revisions = self.revisions + [{
                        "part_id": str(p.get("id")),
                        "action": revision_action, "text": p.get("text"),
                        "take_session_id": revision_take_session_id,
                        "review_version": revision_review_version}]
        self.parts = [
            {**dict(p), **_carried_root(previous.get(str(p.get("id"))),
                                        str(p.get("text") or ""))}
            for p in parts]
        return True

    def get_slide_helper_words(self, arc_id, user_id):
        return [dict(r, slide_index=k) for k, rows in self.slide_rows.items()
                for r in rows]

    def replace_slide_helper_words(self, arc_id, user_id, slide, rows):
        self.slide_rows = {**self.slide_rows, slide: list(rows)}
        return True

    def get_ideal_text_version(self, arc_id, version):
        return self.snapshots.get(version)


class TakeReviewFinalizationTests(unittest.TestCase):
    def test_advances_review_without_losing_owner_text(self):
        database = _ReviewDb()
        result = finalize_later_take_review(
            database,
            arc_id="arc-1",
            owner_user_id="user-1",
            take_session_id="take-2",
            take_index=2,
        )
        self.assertEqual(result["version"], 2)
        self.assertEqual(result["current_version"], 2)
        self.assertEqual(database.edit, {"text": "My exact words", "version": 2})
        self.assertEqual(database.snapshots[2]["text"], "My exact words")
        self.assertEqual(database.ideal["auto_text"], "Canonical words")

    def test_requires_exact_take_provenance(self):
        database = _ReviewDb()
        database.session["arc_id"] = "another-arc"
        with self.assertRaises(TakeReviewFinalizationError):
            finalize_later_take_review(
                database,
                arc_id="arc-1",
                owner_user_id="user-1",
                take_session_id="take-2",
                take_index=2,
            )

    def test_a_missing_document_here_is_a_CREATION_failure_now(self):
        """WHAT THIS REFUSAL MEANS CHANGED (Option A, founder 2026-09-22).

        It used to mean "a later Take may not have an Ideal Text", and it
        was a dead end: only Take 1 could ever create one. The worker now
        builds the document in this same run whenever the Project has none,
        so reaching here with nothing means that build did not stick.

        The type is what unsticks the screen. `TakeReviewFinalizationError`
        is an ordinary RuntimeError to the queue, so it burned three
        attempts re-running the whole pipeline — re-transcribing the audio
        each time — for a fault no retry can fix, and the Take sat on
        "processing" throughout. That is exactly what the founder found on a
        Project eleven days after its Take 1 failed.
        `IdealTextUnconfirmedError` is terminal everywhere: never retried,
        writes `failed_ideal_text_unconfirmed`, and shows the one true
        sentence with a retry that rebuilds only the document.
        """
        database = _ReviewDb()
        database.ideal["auto_text"] = ""
        database.ideal["text"] = ""
        with self.assertRaises(IdealTextUnconfirmedError):
            finalize_later_take_review(
                database,
                arc_id="arc-1",
                owner_user_id="user-1",
                take_session_id="take-2",
                take_index=2,
            )

    def test_it_is_not_reported_as_an_ordinary_finalization_fault(self):
        # The two are deliberately different outcomes, so a test that only
        # asked "did it raise" would not notice the type going back.
        database = _ReviewDb()
        database.ideal["auto_text"] = ""
        database.ideal["text"] = ""
        try:
            finalize_later_take_review(
                database, arc_id="arc-1", owner_user_id="user-1",
                take_session_id="take-2", take_index=2,
            )
        except IdealTextUnconfirmedError as raised:
            self.assertNotIsInstance(raised, TakeReviewFinalizationError)
            self.assertEqual(raised.arc_id, "arc-1")
        else:  # pragma: no cover - the assertion above owns the outcome
            self.fail("a missing document must not pass finalization")

    def test_success_requires_snapshot_readback(self):
        database = _ReviewDb()
        database.get_ideal_text_version = lambda _arc, _version: None
        with self.assertRaisesRegex(
                TakeReviewFinalizationError, "snapshot was not observable"):
            finalize_later_take_review(
                database,
                arc_id="arc-1",
                owner_user_id="user-1",
                take_session_id="take-2",
                take_index=2,
            )


def _change(item_id, family, *, source="wording", kind="replace"):
    return {
        "id": item_id,
        "snippet_id": item_id,
        "take_session_id": "take-2",
        "kind": kind,
        "source": source,
        "feedback_family": family,
    }


class FeedbackSetTests(unittest.TestCase):
    def test_every_served_item_is_keyed_not_just_the_first_three(self):
        """THE CAP WAS V2's BUDGET, AND IT SILENTLY ATE V3's SET (0347).

        `selected_keys` used to stop at `MAX_FEEDBACK_PER_TAKE`, so a fourth
        item was dropped before it could be frozen. V3 routinely serves six
        to ten — one relative-best Confident Voice item per valid 75-word
        block, plus praise, rewrites and exercises anchored per block (24f) — so
        the truncation alone would have made the freeze a partial record of
        what the speaker saw, and every answer to a dropped item would still
        have been refused.

        The keys are now a faithful record of the served selection. The
        BUDGET is the Manager's (L2); `MAX_SELECTED_KEYS` above is a storage
        ceiling against a fault, not a product rule, and sits far above any
        real Take.
        """
        rows = [
            _change("cv", "confident_voice", source="confident_voice", kind="bold"),
            _change("great", "great_formulation", source="structural", kind="advice"),
            _change("rewrite", "rewrite_clarity"),
            _change("fourth", "rewrite_clarity"),
        ]
        keys = selected_keys(rows)
        self.assertEqual(
            [key["id"] for key in keys],
            ["cv", "great", "rewrite", "fourth"],
        )

    def test_a_set_is_claimable_when_it_carries_confident_voice(self):
        """The one V2 requirement that survived.

        Confident Voice is the evaluation this product exists to make, and
        it must never be silently replaced by a third rewrite — the reason
        the old three-family rule existed. 24b guarantees V3 produces one per
        valid block, so keeping it costs V3 nothing.
        """
        from services.take_feedback_set import is_claimable_set

        v3_shaped = selected_keys([
            _change("cv-1", "confident_voice", source="confident_voice", kind="bold"),
            _change("cv-2", "confident_voice", source="confident_voice", kind="bold"),
            _change("cv-3", "confident_voice", source="confident_voice", kind="bold"),
            _change("praise", "great_formulation", source="structural", kind="advice"),
            _change("rewrite", "rewrite_clarity"),
        ])
        self.assertTrue(is_claimable_set(v3_shaped))

        # V2's own shape still claims — this widened the rule, it did not
        # swap one narrow rule for another.
        self.assertTrue(is_claimable_set(selected_keys([
            _change("cv", "confident_voice", source="confident_voice", kind="bold"),
            _change("great", "great_formulation", source="structural", kind="advice"),
            _change("rewrite", "rewrite_clarity"),
        ])))

        # No Confident Voice item: the Take's evaluation is missing, and a
        # set that froze anyway would record a screen the product never
        # meant to show.
        self.assertFalse(is_claimable_set(selected_keys([
            _change("great", "great_formulation", source="structural", kind="advice"),
            _change("rewrite", "rewrite_clarity"),
        ])))
        self.assertFalse(is_claimable_set([]))

    def test_decided_member_disappears_without_replacement(self):
        frozen = selected_keys([
            _change("cv", "confident_voice", source="confident_voice", kind="bold"),
            _change("rewrite-1", "rewrite_clarity"),
            _change("great", "great_formulation", source="structural", kind="advice"),
        ])
        current = [
            _change("cv", "confident_voice", source="confident_voice", kind="bold"),
            # rewrite-1 was accepted and is gone; rewrite-2 must not trickle in.
            _change("rewrite-2", "rewrite_clarity"),
            _change("great", "great_formulation", source="structural", kind="advice"),
        ]
        self.assertEqual(
            [row["id"] for row in filter_candidates_to_selected(current, frozen)],
            ["cv", "great"],
        )
        self.assertEqual(
            [row["id"] for row in filter_to_selected(current, frozen)],
            ["cv", "great"],
        )

    def test_claim_refuses_rewrite_only_set(self):
        class _Db:
            def claim_ideal_text_feedback_set(self, *args, **kwargs):
                raise AssertionError("database must not be called")

        self.assertIsNone(claim_feedback_set(
            _Db(),
            arc_id="arc-1",
            owner_user_id="user-1",
            take_session_id="take-2",
            take_index=2,
            review_version=2,
            changes=[_change("rewrite", "rewrite_clarity")],
        ))


class CurrentTakeConfidentVoiceTests(unittest.TestCase):
    P1 = "We started small and listened."
    P2 = "Then we shipped it fast."
    TEXT = P1 + "\n\n" + P2
    CANONICAL = [
        {
            "snippet_id": "old-1", "take_session_id": "take-1",
            "slide_index": 0, "start": 0, "end": len(P1),
            "text": P1,
        },
        {
            "snippet_id": "old-2", "take_session_id": "take-1",
            "slide_index": 1, "start": len(P1) + 2,
            "end": len(P1) + 2 + len(P2),
            "text": P2,
        },
    ]

    def test_anchors_exact_shared_words_but_keeps_current_take_provenance(self):
        take = {
            "take_session_id": "take-2",
            "pieces": [{
                "snippet_id": "new-2", "take_session_id": "take-2",
                "slide_index": 1,
                "text": "This time we shipped it fast and stayed calm.",
            }],
        }
        suggestions = {"new-2": {
            "kind": "emphasize", "trigger": "confidence_review",
            "emphasis_quote": "shipped it fast", "why": "neutral",
        }}
        change, evidence = current_take_confident_voice_candidate(
            self.TEXT,
            canonical_pieces=self.CANONICAL,
            take_document=take,
            suggestions=suggestions,
        )
        self.assertEqual(change["take_session_id"], "take-2")
        self.assertEqual(change["quote"], "shipped it fast")
        self.assertEqual(change["anchor_role"], "spoken_phrase")
        self.assertEqual(change["why_key"], "confident_voice")
        self.assertEqual(evidence["slide_index"], 1)
        self.assertEqual(evidence["take_session_id"], "take-2")
        self.assertEqual(
            self.TEXT[change["span"]["start"]:change["span"]["end"]],
            change["quote"],
        )

    def test_no_shared_word_uses_explicit_slide_route_not_fake_praise(self):
        take = {
            "take_session_id": "take-2",
            "pieces": [{
                "snippet_id": "new-2", "take_session_id": "take-2",
                "slide_index": 1, "text": "Completely different wording.",
            }],
        }
        suggestions = {"new-2": {
            "kind": "emphasize", "trigger": "confidence_review",
            "why": "Possible confident moment for review.",
        }}
        change, evidence = current_take_confident_voice_candidate(
            self.TEXT,
            canonical_pieces=self.CANONICAL,
            take_document=take,
            suggestions=suggestions,
        )
        self.assertEqual(change["anchor_role"], "slide_route")
        self.assertEqual(change["take_session_id"], "take-2")
        self.assertEqual(evidence["slide_index"], 1)
        self.assertNotIn("incredibly", change["why"].lower())

    def test_no_detector_candidate_adds_a_separate_neutral_evaluation(self):
        take = {
            "take_session_id": "take-2",
            "pieces": [{
                "snippet_id": "new-2", "take_session_id": "take-2",
                "slide_index": 1, "text": "Completely different wording.",
            }],
        }
        change, evidence = current_take_confident_voice_candidate(
            self.TEXT,
            canonical_pieces=self.CANONICAL,
            take_document=take,
            # A wording candidate may already own this snippet's persisted
            # suggestion row. The Confident Voice evaluation is derived as a
            # separate Manager candidate and must not overwrite that row.
            suggestions={"new-2": {
                "kind": "replace", "trigger": "stickiness",
                "replacement_text": "A clearer line.",
            }},
        )
        self.assertEqual(change["id"], "confident-voice:new-2")
        self.assertEqual(change["source"], "confident_voice")
        self.assertEqual(change["why"], "Possible confident moment for review.")
        self.assertEqual(change["anchor_role"], "slide_route")
        self.assertEqual(evidence["take_session_id"], "take-2")

    def test_answered_confident_voice_is_not_reoffered(self):
        take = {
            "take_session_id": "take-2",
            "pieces": [{
                "snippet_id": "new-2", "take_session_id": "take-2",
                "slide_index": 1, "text": "A moment already reviewed.",
            }],
        }
        change, evidence = current_take_confident_voice_candidate(
            self.TEXT,
            canonical_pieces=self.CANONICAL,
            take_document=take,
            suggestions={},
            excluded_snippet_ids={"new-2"},
        )
        self.assertIsNone(change)
        self.assertIsNone(evidence)

    def test_deckless_take_uses_unlinked_talk_section_without_guessing_slide(self):
        text = "One continuous talk section."
        take = {
            "take_session_id": "take-2",
            "pieces": [{
                "snippet_id": "new-deckless",
                "take_session_id": "take-2",
                "slide_index": None,
                "text": "Different spoken wording.",
            }],
        }
        canonical = [{
            "snippet_id": "old-deckless",
            "take_session_id": "take-1",
            "slide_index": None,
            "start": 0,
            "end": len(text),
            "text": text,
        }]
        change, evidence = current_take_confident_voice_candidate(
            text,
            canonical_pieces=canonical,
            take_document=take,
            suggestions={},
        )
        self.assertEqual(change["id"], "confident-voice:new-deckless")
        self.assertIsNone(evidence["slide_index"])
        self.assertEqual(evidence["take_session_id"], "take-2")

    def test_refuses_to_guess_a_different_slide(self):
        take = {
            "take_session_id": "take-2",
            "pieces": [{
                "snippet_id": "new-3", "take_session_id": "take-2",
                "slide_index": 9, "text": "A moment on an unknown slide.",
            }],
        }
        change, evidence = current_take_confident_voice_candidate(
            self.TEXT,
            canonical_pieces=self.CANONICAL,
            take_document=take,
            suggestions={"new-3": {
                "kind": "emphasize", "trigger": "confidence_review",
            }},
        )
        self.assertIsNone(change)
        self.assertIsNone(evidence)


if __name__ == "__main__":
    unittest.main()


def _two_slide_document():
    text = "Slide one words.\n\nSlide two words."
    return text, {
        "pieces": [],
        "paragraphs": [
            {"slide_index": 0, "start": 0, "end": 16},
            {"slide_index": 1, "start": 18, "end": 34},
        ],
    }


class EveryTakeRewritesTheSlidesItSpoke(unittest.TestCase):
    """Contract 8-9 (founder 2026-09-25): Take 2 rebuilds the Slides it spoke
    from what was said, keeps the others, and supersedes the owner edit."""

    def _run(self, database, new_doc):
        from unittest import mock

        with mock.patch(
                "services.transcript_document.build_transcript_document",
                return_value=new_doc), \
                mock.patch(
                    "services.ideal_text_core_snapshot.publish_for_arc"):
            return finalize_later_take_review(
                database, arc_id="arc-1", owner_user_id="user-1",
                take_session_id="take-2", take_index=2)

    def test_the_spoken_slide_is_rebuilt_and_the_other_is_kept(self):
        database = _ReviewDb()
        old_text, old_doc = _two_slide_document()
        database.ideal.update(auto_text=old_text, text=old_text,
                              document=old_doc)
        database.parts = [
            {"id": "p-one", "ord": 0, "text": "Slide one words.",
             "locked_at": "2026-09-25T10:00:00Z",
             "root_phrase": "one words", "root_start": 6, "root_end": 15,
             "root_selected_at": "2026-09-25T10:00:00Z"},
            {"id": "p-two", "ord": 1, "text": "Slide two words."},
        ]
        new_text = "Take two says slide two differently."
        self._run(database, {
            "text": new_text, "pieces": [],
            "paragraphs": [{"slide_index": 1, "start": 0,
                            "end": len(new_text)}],
            "take_session_id": "take-2", "take_index": 2,
        })
        merged = "Slide one words.\n\n" + new_text
        self.assertEqual(database.ideal["auto_text"], merged)
        self.assertEqual(database.snapshots[2]["text"], merged)
        # Q5 A: the owner edit is not carried; it stays at its version.
        self.assertEqual(database.edit["version"], 1)
        # Identity: the untouched Paragraph keeps its id; slide two reuses
        # its old id for its new words.
        self.assertEqual([(p["id"], p["text"]) for p in database.parts],
                         [("p-one", "Slide one words."), ("p-two", new_text)])
        # Q12 A: the locked Paragraph-level helper words moved to the Slide.
        self.assertEqual(
            [r["phrase"] for r in database.slide_rows.get(0, [])],
            ["one words"])

    def test_each_paragraph_the_take_rewrote_records_that_take(self):
        """Contract 16; Phase 3: a Take rewrite appends a `take_rewrite`
        revision naming the Take and its version for each Paragraph whose
        words it changed. The Slide it did not speak gets none, and its lock
        and helper words stay."""
        database = _ReviewDb()
        old_text, old_doc = _two_slide_document()
        database.ideal.update(auto_text=old_text, text=old_text,
                              document=old_doc)
        database.parts = [
            {"id": "p-one", "ord": 0, "text": "Slide one words.",
             "locked_at": "2026-10-04T10:00:00Z"},
            {"id": "p-two", "ord": 1, "text": "Slide two words.",
             "locked_at": "2026-10-04T10:00:00Z"},
        ]
        new_text = "Take two says slide two differently."
        self._run(database, {
            "text": new_text, "pieces": [],
            "paragraphs": [{"slide_index": 1, "start": 0,
                            "end": len(new_text)}],
            "take_session_id": "take-2", "take_index": 2,
        })
        self.assertEqual(database.revisions, [{
            "part_id": "p-two", "action": "take_rewrite", "text": new_text,
            "take_session_id": "take-2", "review_version": 2}])
        # The lock rides the rewrite (contract 14): both stay locked.
        self.assertEqual([bool(p.get("locked_at")) for p in database.parts],
                         [True, True])

    def test_a_whole_take_rewrite_records_every_paragraph(self):
        """An unprovable old document follows the Take whole: every
        Paragraph it now has is this Take's, so each records it."""
        database = _ReviewDb()
        database.parts = [{"id": "p-old", "ord": 0, "text": "Old words."}]
        with self.assertLogs("services.take_rebuild", "WARNING"):
            self._run(database, {
                "text": "Anything.", "pieces": [],
                "paragraphs": [{"slide_index": 0, "start": 0, "end": 9}],
            })
        self.assertEqual(
            [(r["action"], r["text"], r["take_session_id"],
              r["review_version"]) for r in database.revisions],
            [("take_rewrite", "Anything.", "take-2", 2)])

    def test_helper_words_survive_an_edit_between_takes(self):
        """Founder lock 2026-09-30, B1: pick words on Take 1, edit another
        paragraph with the pencil, record Take 2 — the words are still on
        their Paragraph. The edit rewrote the stored rows' words while the
        machine text stayed, and until this the rebuild answered that
        mismatch with fresh ids for every Paragraph."""
        database = _ReviewDb()
        old_text, old_doc = _two_slide_document()
        database.ideal.update(auto_text=old_text, text=old_text,
                              document=old_doc)
        database.edit = {"text": "Slide one words.\n\nSlide two, edited.",
                         "version": 1}
        database.parts = [
            {"id": "p-one", "ord": 0, "text": "Slide one words.",
             "locked_at": "2026-09-30T10:00:00Z",
             "root_phrase": "one words", "root_start": 6, "root_end": 15,
             "root_selected_at": "2026-09-30T10:00:00Z"},
            {"id": "p-two", "ord": 1, "text": "Slide two, edited."},
        ]
        new_text = "Take two says slide two differently."
        self._run(database, {
            "text": new_text, "pieces": [],
            "paragraphs": [{"slide_index": 1, "start": 0,
                            "end": len(new_text)}],
            "take_session_id": "take-2", "take_index": 2,
        })
        self.assertEqual([(p["id"], p["text"]) for p in database.parts],
                         [("p-one", "Slide one words."), ("p-two", new_text)])
        one = database.parts[0]
        self.assertEqual(one["locked_at"], "2026-09-30T10:00:00Z")
        self.assertEqual(one["root_phrase"], "one words")
        self.assertEqual((one["root_start"], one["root_end"]), (6, 15))
        self.assertEqual(
            [r["phrase"] for r in database.slide_rows.get(0, [])],
            ["one words"])

    def test_an_unspoken_slide_keeps_the_words_the_speaker_reads(self):
        """L1, contract 8, N29: a Slide Take 2 did not speak keeps its LAST
        version, which is the served text: here the owner's edit on Slide
        one and an accepted rewrite (N35.4 / N40, written through the same
        owner-edit writer) on its locked Paragraph. The document, the
        version snapshot and the Paragraph row all carry those words; the
        Paragraph keeps its id, lock and helper words, and gets no Take
        revision, because no Take spoke it. Until 2026-10-05 Take 2 put
        Take 1's machine words back."""
        database = _ReviewDb()
        old_text, old_doc = _two_slide_document()
        database.ideal.update(auto_text=old_text, text=old_text,
                              document=old_doc)
        accepted = "Slide one words, accepted."
        database.edit = {"text": f"{accepted}\n\nSlide two, edited.",
                         "version": 1}
        database.parts = [
            {"id": "p-one", "ord": 0, "text": accepted,
             "locked_at": "2026-10-05T10:00:00Z", "root_phrase": "one words",
             "root_start": 6, "root_end": 15,
             "root_selected_at": "2026-10-05T10:00:00Z"},
            {"id": "p-two", "ord": 1, "text": "Slide two, edited."},
        ]
        new_text = "Take two says slide two differently."
        self._run(database, {
            "text": new_text, "pieces": [],
            "paragraphs": [{"slide_index": 1, "start": 0,
                            "end": len(new_text)}],
            "take_session_id": "take-2", "take_index": 2,
        })
        merged = f"{accepted}\n\n{new_text}"
        self.assertEqual(database.ideal["auto_text"], merged)
        self.assertEqual(database.snapshots[2]["text"], merged)
        self.assertEqual(
            [p["slide_index"] for p in database.ideal["document"]["paragraphs"]],
            [0, 1])
        self.assertEqual([(p["id"], p["text"]) for p in database.parts],
                         [("p-one", accepted), ("p-two", new_text)])
        one = database.parts[0]
        self.assertEqual(one["locked_at"], "2026-10-05T10:00:00Z")
        self.assertEqual(one["root_phrase"], "one words")
        self.assertEqual([r["part_id"] for r in database.revisions],
                         ["p-two"])
        # The owner edit stays at its version: it reads back as prior_edit.
        self.assertEqual(database.edit["version"], 1)

    def test_an_unreadable_edit_never_stops_the_rebuild(self):
        """LIVE LOOP: if the served text cannot be read, the rebuild is
        still planned; its unspoken Slide keeps the machine words, and that
        is counted under one fixed name."""
        from unittest import mock

        from services.take_rebuild import plan_rebuild

        database = _ReviewDb()
        old_text, old_doc = _two_slide_document()
        database.ideal.update(auto_text=old_text, text=old_text,
                              document=old_doc)

        def broken(arc_id, user_id):
            raise RuntimeError("edit store down")

        database.get_user_ideal_edit = broken
        new_text = "Take two says slide two differently."
        new_doc = {"text": new_text, "pieces": [],
                   "paragraphs": [{"slide_index": 1, "start": 0,
                                   "end": len(new_text)}]}
        with mock.patch(
                "services.transcript_document.build_transcript_document",
                return_value=new_doc), \
                self.assertLogs("services.take_rebuild", "WARNING") as logs:
            rebuild = plan_rebuild(database, "arc-1", "take-2", "user-1")
        self.assertIsNotNone(rebuild)
        self.assertEqual(rebuild.text, f"Slide one words.\n\n{new_text}")
        self.assertTrue(any("take_rebuild_unspoken_kept_machine_words" in line
                            for line in logs.output))

    def test_an_unprovable_document_follows_the_take(self):
        """F1 Repair Plan Phase 3 (contract 8, N29 answer 3). An old document
        with no Slide provenance cannot be merged by Slide; it used to stay
        exactly as it was. Now the Take's own words become the whole text,
        and the previous version stays in the versions table."""
        database = _ReviewDb()  # no `document`: nothing to merge by Slide
        with self.assertLogs("services.take_rebuild", "WARNING") as logs:
            result = self._run(database, {
                "text": "Anything.", "pieces": [],
                "paragraphs": [{"slide_index": 0, "start": 0, "end": 9}],
            })
        self.assertEqual(result["version"], 2)
        self.assertEqual(database.ideal["auto_text"], "Anything.")
        self.assertTrue(any("take_rebuild_followed_whole_take" in line
                            for line in logs.output))
