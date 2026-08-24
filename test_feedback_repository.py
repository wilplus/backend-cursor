from unittest.mock import patch

import pytest

from services.feedback_repository import (
    FeedbackContractError,
    FeedbackRepository,
    serialize_feedback_item,
)


class FakeDatabase:
    def __init__(self, *, family, duration_ms=900, replacement=None):
        self.session = {"id": "take-1", "project_id": "project-1"}
        self.family = family
        self.duration_ms = duration_ms
        self.replacement = replacement

    def v2_get_session_by_id(self, take_id):
        return self.session if take_id == "take-1" else None

    def get_coach_snippet_drafts(self, take_id):
        return [{
            "snippet_id": "snippet-1",
            "surfaced": True,
            "feedback_family": self.family,
            "review_state": "reviewed",
            "note": "Specific evidence-backed explanation.",
            "transcript_corrected": self.replacement,
        }]

    def get_snippet_by_id(self, snippet_id):
        return {
            "id": snippet_id,
            "session_id": "take-1",
            "start_offset_ms": 100,
            "duration_ms": self.duration_ms,
        }

    def upsert_coach_snippet_draft(self, *args, **kwargs):
        return {"saved": True}


class EmptyFeedbackDatabase(FakeDatabase):
    def __init__(self):
        super().__init__(family="great_formulation")

    def get_coach_snippet_drafts(self, take_id):
        return [{
            "snippet_id": "snippet-1",
            "surfaced": True,
            "feedback_family": "great_formulation",
            "review_state": "reviewed",
            "note": "   ",
        }]


DOCUMENT = {
    "pieces": [{
        "snippet_id": "snippet-1",
        "slide_index": 0,
        "start": 0,
        "end": 12,
        "text": "Clear words.",
    }],
    "paragraphs": [{"start": 0, "end": 12}],
}


def _items(database):
    with patch(
        "services.transcript_document.build_transcript_document",
        return_value=DOCUMENT,
    ):
        return FeedbackRepository(database).surfaced_items("take-1")


def test_great_formulation_needs_text_span_but_not_audio():
    item = _items(FakeDatabase(
        family="great_formulation",
        duration_ms=None,
    ))[0]
    payload = serialize_feedback_item(item)
    assert payload["family"] == "great_formulation"
    assert payload["evidence"]["audio_interval"] is None
    assert payload["evidence"]["evidence_span"]["text"] == "Clear words."


def test_confident_voice_requires_audio_interval():
    with pytest.raises(FeedbackContractError, match="playable audio"):
        _items(FakeDatabase(family="confident_voice", duration_ms=None))


def test_rewrite_requires_proposed_replacement():
    with pytest.raises(FeedbackContractError, match="replacement"):
        _items(FakeDatabase(family="rewrite_for_clarity", replacement=None))


def test_rewrite_keeps_original_span_and_proposal_separate():
    item = _items(FakeDatabase(
        family="rewrite_for_clarity",
        replacement="A clearer sentence.",
    ))[0]
    assert item.evidence.evidence_span["text"] == "Clear words."
    assert item.replacement_text == "A clearer sentence."


def test_empty_feedback_is_valid_no_changes_needed_result():
    database = EmptyFeedbackDatabase()
    assert FeedbackRepository(database).surfaced_items("take-1") == []
    assert FeedbackRepository(database).publish(
        "take-1", actor_user_id="coach-1",
    ) == []


def test_published_readout_exposes_empty_result_and_separate_coach_review():
    from services import lab_recording
    from services.db import db

    session = {
        "id": "take-1",
        "project_id": "project-1",
        "results_published_at": "2026-08-24T08:00:00Z",
        "coach_overall_message": "No changes needed.",
        "coach_video_ref": "https://cdn.example/coach.mp4",
    }
    with patch.object(db, "get_snippets_by_session", return_value=[]), \
         patch.object(db, "v2_get_session_by_id", return_value=session), \
         patch.object(db, "get_coach_snippet_drafts", return_value=[]), \
         patch(
             "services.lab_recording.prepare_readout_snippets",
             return_value=([], {}),
         ), \
         patch("services.lab_recording.attach_readout_context"):
        readout = lab_recording.build_readout_from_session("take-1")

    assert readout["feedback_items"] == []
    assert readout["coach_review"] == {
        "overall_message": "No changes needed.",
        "video_ref": "https://cdn.example/coach.mp4",
    }
    assert "insights_payload" not in readout
