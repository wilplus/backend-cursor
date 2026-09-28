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


class CoachRevisionPinTests(unittest.TestCase):
    """build_coach_revision_changes, pinned before its split into named
    stages (audit W1, 2026-09-28): the exact change, which accepted row
    wins, and every way a revision is not offered."""

    DOC = "Alpha words here. Beta words here."

    def _accepted(self, sid, current, original, **over):
        row = {"decision": "approved", "source": "user_star",
               "kind": "replace", "snippet_id": sid,
               "replacement_text": current, "display_phrase": original,
               "updated_at": "2026-09-01T00:00:00Z", "version": 1}
        row.update(over)
        return row

    def _build(self, ledger, verdicts, suggestions=None, doc=None,
               pieces=None):
        return build_coach_revision_changes(
            self.DOC if doc is None else doc,
            [{"snippet_id": "b", "take_session_id": "t-b"},
             {"snippet_id": "a", "take_session_id": "t-a"}]
            if pieces is None else pieces,
            suggestions or {}, ledger, verdicts)

    def test_the_exact_change_and_the_order(self):
        out = self._build(
            [self._accepted("b", " Beta words ", "Old beta"),
             self._accepted("a", "Alpha words", "Old alpha")],
            {"a": {"verdict": "wrong_kind", "note": "Yours was right."},
             "b": {"verdict": "keep"}},
            {"b": {"replacement_text_final": " Coach beta ",
                   "why_final": None, "why": "machine why"}})
        self.assertEqual(out, [
            {"id": "coach-revision:a", "snippet_id": "a",
             "take_session_id": "t-a", "kind": "replace",
             "source": "coach_revision", "span": {"start": 0, "end": 11},
             "quote": "Alpha words", "proposed_text": "Old alpha",
             "coach_note": "Yours was right."},
            {"id": "coach-revision:b", "snippet_id": "b",
             "take_session_id": "t-b", "kind": "replace",
             "source": "coach_revision", "span": {"start": 18, "end": 28},
             "quote": "Beta words", "proposed_text": "Coach beta",
             "coach_note": "machine why"},
        ])

    def test_the_latest_accepted_row_per_snippet_wins(self):
        out = self._build(
            [self._accepted("a", "Alpha words", "Old one",
                            updated_at="2026-09-01T00:00:00Z", version=5),
             self._accepted("a", "Beta words", "Old two",
                            updated_at="2026-09-02T00:00:00Z", version=1),
             self._accepted("a", "Alpha words here", "Old three",
                            updated_at="2026-09-02T00:00:00Z", version=0)],
            {"a": {"verdict": "should_not_fire"}})
        self.assertEqual([(c["quote"], c["proposed_text"]) for c in out],
                         [("Beta words", "Old two")])
        self.assertIsNone(out[0]["coach_note"])

    def test_only_approved_user_star_word_changes_count(self):
        verdicts = {"a": {"verdict": "wrong_kind"}}
        for over in ({"decision": "dismissed"}, {"source": "coach"},
                     {"kind": "bold"}, {"snippet_id": None}):
            self.assertEqual(self._build(
                [self._accepted("a", "Alpha words", "Old", **over)],
                verdicts), [], over)
        polish = self._accepted("a", "Alpha words", "Old", kind="polish")
        self.assertEqual(len(self._build([polish], verdicts)), 1)

    def test_no_revision_is_offered(self):
        wrong = {"a": {"verdict": "wrong_kind"}}
        # No served text, or the accepted words are not there exactly once.
        for doc in ("", None, 7):
            self.assertEqual(build_coach_revision_changes(
                doc, [], {}, [self._accepted("a", "Alpha", "x")], wrong), [])
        self.assertEqual(self._build(
            [self._accepted("a", "words here", "Old")], wrong), [])
        self.assertEqual(self._build(
            [self._accepted("a", "Gamma", "Old")], wrong), [])
        self.assertEqual(self._build(
            [self._accepted("a", "   ", "Old")], wrong), [])
        # The revision was itself already decided.
        decided = {"kind": "polish", "target_phrase": "alpha  words",
                   "decision": "dismissed"}
        self.assertEqual(self._build(
            [self._accepted("a", "Alpha words", "Old"),
             dict(decided, target_phrase="alpha words")], wrong), [])
        # A keep with no coach final, an unknown verdict, no verdict.
        for verdicts in ({"a": {"verdict": "keep"}},
                         {"a": {"verdict": "later"}}, {}, {"a": "keep"}):
            self.assertEqual(self._build(
                [self._accepted("a", "Alpha words", "Old")], verdicts), [])
        # Restoring would change nothing, or there is nothing to restore.
        for original in ("Alpha words", "  "):
            self.assertEqual(self._build(
                [self._accepted("a", "Alpha words", original)], wrong), [])

    def test_malformed_inputs_are_read_as_empty(self):
        out = build_coach_revision_changes(
            self.DOC, "not pieces", "not suggestions",
            [self._accepted("a", "Alpha words", "Old"), "not a row"],
            {"a": {"verdict": "wrong_kind"}})
        self.assertEqual(out[0]["take_session_id"], None)
        self.assertEqual(build_coach_revision_changes(
            self.DOC, [], {}, None, None), [])


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
