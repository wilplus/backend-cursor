"""Later-Take Ideal Text review finalization and immutable feedback sets."""
from __future__ import annotations

import unittest

from services.take_feedback_set import (
    claim_feedback_set,
    filter_candidates_to_selected,
    filter_to_selected,
    selected_keys,
)
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

    def get_user_ideal_edit(self, arc_id, user_id):
        return dict(self.edit) if self.edit else None

    def get_moment_suggestions_by_arc(self, arc_id):
        return self.suggestions

    def finalize_ideal_text_take(
        self, arc_id, owner, session_id, index, moments,
    ):
        self.ideal["version"] = index
        if self.edit and self.edit["version"] == 1:
            self.edit["version"] = index
        self.snapshots[index] = {
            "arc_id": arc_id,
            "version": index,
            "text": self.edit["text"] if self.edit else self.ideal["auto_text"],
            "moments": moments,
        }
        return {
            "arc_id": arc_id,
            "take_session_id": session_id,
            "take_index": index,
            "version": index,
            "text_confirmed": True,
        }

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

    def test_requires_existing_canonical_text(self):
        database = _ReviewDb()
        database.ideal["auto_text"] = ""
        database.ideal["text"] = ""
        with self.assertRaises(TakeReviewFinalizationError):
            finalize_later_take_review(
                database,
                arc_id="arc-1",
                owner_user_id="user-1",
                take_session_id="take-2",
                take_index=2,
            )

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
    def test_three_whole_take_keys_include_confident_voice(self):
        rows = [
            _change("cv", "confident_voice", source="confident_voice", kind="bold"),
            _change("great", "great_formulation", source="structural", kind="advice"),
            _change("rewrite", "rewrite_clarity"),
            _change("fourth", "rewrite_clarity"),
        ]
        keys = selected_keys(rows)
        self.assertEqual([key["id"] for key in keys], ["cv", "great", "rewrite"])

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
