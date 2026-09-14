"""Machine-immediate → coach-superseded feedback invariants."""
from __future__ import annotations

import unittest

from services.star_verdicts import (
    filter_user_suggestions, released_user_verdicts,
)
from services.tracked_changes import build_coach_revision_changes
from services.voice_album_routing import (
    routing_response_from_rating, validate_owner_voice_album_route,
)


SID = "11111111-2222-3333-4444-555555555555"
TAKE = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _suggestion(**over):
    row = {
        "snippet_id": SID,
        "kind": "replace",
        "replacement_text": "Coach final words",
        "replacement_text_draft": "Machine accepted words",
        "replacement_text_final": "Coach final words",
        "why": "Clearer for the audience.",
        "why_final": "Clearer for the audience.",
    }
    row.update(over)
    return row


def _accepted(**over):
    row = {
        "decision": "approved",
        "source": "user_star",
        "kind": "replace",
        "snippet_id": SID,
        "target_phrase": "original words",
        "display_phrase": "Original words",
        "replacement_text": "Machine accepted words",
        "version": 1,
    }
    row.update(over)
    return row


PIECES = [{"snippet_id": SID, "take_session_id": TAKE}]


class ImmediateFeedbackTests(unittest.TestCase):
    def test_unjudged_machine_feedback_remains_immediately_eligible(self):
        rows = {SID: _suggestion()}
        self.assertEqual(filter_user_suggestions(rows, {}), rows)

    def test_coach_rejection_suppresses_only_the_pending_machine_offer(self):
        rows = {SID: _suggestion()}
        verdicts = {SID: {"verdict": "should_not_fire"}}
        self.assertEqual(filter_user_suggestions(rows, verdicts), {})

    def test_keep_preserves_the_pending_offer(self):
        rows = {SID: _suggestion()}
        verdicts = {SID: {"verdict": "keep"}}
        self.assertEqual(filter_user_suggestions(rows, verdicts), rows)


class CoachReleaseBoundaryTests(unittest.TestCase):
    def test_unpublished_coach_verdict_stays_private(self):
        verdicts = {SID: {"verdict": "should_not_fire"}}
        pieces = [{"snippet_id": SID, "take_session_id": TAKE}]
        sessions = [{"id": TAKE, "results_published_at": None}]
        self.assertEqual(released_user_verdicts(verdicts, pieces, sessions), {})

    def test_published_coach_verdict_can_supersede(self):
        verdicts = {SID: {"verdict": "should_not_fire"}}
        pieces = [{"snippet_id": SID, "take_session_id": TAKE}]
        sessions = [{"id": TAKE,
                     "results_published_at": "2026-08-17T10:00:00Z"}]
        self.assertEqual(
            released_user_verdicts(verdicts, pieces, sessions), verdicts)


class AcceptedTextSupersessionTests(unittest.TestCase):
    def test_coach_correction_is_a_fresh_proposal_against_accepted_words(self):
        text = "Opening. Machine accepted words. Closing."
        out = build_coach_revision_changes(
            text, PIECES, {SID: _suggestion()}, [_accepted()],
            {SID: {"verdict": "keep"}},
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source"], "coach_revision")
        self.assertEqual(out[0]["quote"], "Machine accepted words")
        self.assertEqual(out[0]["proposed_text"], "Coach final words")
        self.assertEqual(text[out[0]["span"]["start"]:
                              out[0]["span"]["end"]], out[0]["quote"])
        self.assertEqual(text, "Opening. Machine accepted words. Closing.")

    def test_rejection_after_acceptance_proposes_restoring_original(self):
        out = build_coach_revision_changes(
            "Machine accepted words", PIECES, {SID: _suggestion()},
            [_accepted()],
            {SID: {"verdict": "should_not_fire", "note": "Keep your line."}},
        )
        self.assertEqual(out[0]["proposed_text"], "Original words")
        self.assertEqual(out[0]["coach_note"], "Keep your line.")

    def test_unjudged_coach_edit_never_supersedes_accepted_text(self):
        out = build_coach_revision_changes(
            "Machine accepted words", PIECES, {SID: _suggestion()},
            [_accepted()], {},
        )
        self.assertEqual(out, [])

    def test_a_decided_coach_revision_is_not_reoffered(self):
        second = {
            "decision": "dismissed", "source": "user_star",
            "kind": "replace", "snippet_id": SID,
            "target_phrase": "machine accepted words",
            "display_phrase": "Machine accepted words",
            "replacement_text": "Coach final words",
        }
        out = build_coach_revision_changes(
            "Machine accepted words", PIECES, {SID: _suggestion()},
            [_accepted(), second], {SID: {"verdict": "keep"}},
        )
        self.assertEqual(out, [])


class VoiceAlbumRoutingTests(unittest.TestCase):
    def test_legacy_boolean_contract_maps_to_routing(self):
        row, err = validate_owner_voice_album_route({"ai_correct": True})
        self.assertIsNone(err)
        self.assertEqual(row["response"], "yes")
        self.assertIs(row["ai_correct"], True)
        for invalid in ("true", 1, None):
            row, err = validate_owner_voice_album_route({"ai_correct": invalid})
            self.assertIsNone(row)
            self.assertIn("ai_correct", err)

    def test_current_instrument_maps_without_creating_a_label(self):
        for payload, expected in [
            ({"value": "yes"}, "yes"),
            ({"value": "no"}, "no"),
            ({"value": "neutral"}, "neutral"),
            ({"unrateable": True}, "unrateable"),
        ]:
            response, err = routing_response_from_rating(payload)
            self.assertIsNone(err)
            self.assertEqual(response, expected)

    def test_module_has_no_training_or_quorum_imports(self):
        from pathlib import Path
        source = Path("services/voice_album_routing.py").read_text()
        for banned in ("state_ratings", "training_labels", "learning_serve",
                       "ml_dpo", "label_quorum"):
            self.assertNotIn(f"import {banned}", source)


if __name__ == "__main__":
    unittest.main()
