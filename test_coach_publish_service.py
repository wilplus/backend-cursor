from __future__ import annotations

import pytest

from services.coach_publish import (
    PublishReviewCommand,
    PublishReviewError,
    publish_review,
    publish_reviews,
)


SESSION_ID = "11111111-1111-4111-8111-111111111111"
PROJECT_ID = "22222222-2222-4222-8222-222222222222"
OWNER_ID = "33333333-3333-4333-8333-333333333333"
COACH_ID = "44444444-4444-4444-8444-444444444444"
OTHER_COACH_ID = "55555555-5555-4555-8555-555555555555"


def _feedback_item(*, state: str = "reviewed", family: str = "great_formulation") -> dict:
    return {
        "id": "coach:item-1",
        "family": family,
        "message": "The reasoning is specific and evidence-backed.",
        "review_state": state,
        "replacement_text": (
            "A clearer replacement." if family == "rewrite_for_clarity" else None
        ),
        "evidence": {
            "project_id": PROJECT_ID,
            "take_id": SESSION_ID,
            "slide_index": 0,
            "paragraph_index": 1,
            "evidence_span": {
                "start": 10,
                "end": 30,
                "text": "Original exact words.",
            },
            "audio_interval": (
                {"start_ms": 100, "end_ms": 900}
                if family == "confident_voice" else None
            ),
            "piece_id": "66666666-6666-4666-8666-666666666666",
        },
    }


def _command(**overrides) -> PublishReviewCommand:
    payload = {
        "session_id": SESSION_ID,
        "idempotency_key": "publish-attempt-1",
        "overall_message": "A concise overall note.",
        "feedback_items": [_feedback_item()],
        "share_video": False,
    }
    payload.update(overrides)
    return PublishReviewCommand.from_payload(payload)


class FakeDatabase:
    def __init__(self, *, owner_id=OWNER_ID, assigned_to=COACH_ID):
        self.session = {
            "id": SESSION_ID,
            "project_id": PROJECT_ID,
            "arc_id": PROJECT_ID,
            "user_id": owner_id,
            "coach_review_status": "in_review",
            "coach_review_assigned_to": assigned_to,
            "status": "readout_ready",
            "analysis_state": "ready",
        }
        self.published = []

    def v2_get_session_by_id(self, session_id):
        return dict(self.session) if session_id == SESSION_ID else None

    def publish_coach_review_revisions(self, payloads):
        self.published.extend(payloads)
        return [{
            "revision_id": payload["revision_id"],
            "revision_number": 1,
            "published_at": "2026-08-24T10:00:00Z",
            "replayed": False,
            "outbox_id": "77777777-7777-4777-8777-777777777777",
        } for payload in payloads]


def test_payload_requires_complete_final_feedback_snapshot():
    with pytest.raises(PublishReviewError, match="feedback_items"):
        PublishReviewCommand.from_payload({
            "session_id": SESSION_ID,
            "idempotency_key": "attempt",
        })


def test_empty_feedback_is_valid_no_changes_needed():
    command = _command(feedback_items=[])
    assert command.feedback_items == ()


def test_feedback_evidence_must_target_the_exact_take_and_project():
    item = _feedback_item()
    item["evidence"]["take_id"] = OTHER_COACH_ID
    command = _command(feedback_items=[item])
    with pytest.raises(PublishReviewError, match="exact take"):
        publish_review(FakeDatabase(), command, actor_user_id=COACH_ID)


def test_unclaimed_guest_is_rejected_before_any_write():
    database = FakeDatabase(owner_id=None)
    with pytest.raises(PublishReviewError) as caught:
        publish_review(database, _command(), actor_user_id=COACH_ID)
    assert caught.value.code == "UNCLAIMED_GUEST"
    assert database.published == []


def test_only_assigned_coach_can_publish():
    database = FakeDatabase()
    with pytest.raises(PublishReviewError) as caught:
        publish_review(database, _command(), actor_user_id=OTHER_COACH_ID)
    assert caught.value.code == "REVIEW_ASSIGNED_TO_ANOTHER_COACH"
    assert database.published == []


def test_admin_override_requires_a_reason():
    database = FakeDatabase()
    with pytest.raises(PublishReviewError) as caught:
        publish_review(
            database,
            _command(),
            actor_user_id=OTHER_COACH_ID,
            actor_is_admin=True,
        )
    assert caught.value.code == "ADMIN_OVERRIDE_REASON_REQUIRED"


def test_atomic_publish_receives_immutable_snapshot_and_no_processing_status_write():
    database = FakeDatabase()
    result = publish_review(database, _command(), actor_user_id=COACH_ID)
    assert result.revision_number == 1
    assert result.side_effects_pending is True
    saved = database.published[0]
    assert saved["session_id"] == SESSION_ID
    assert saved["actor_user_id"] == COACH_ID
    assert saved["feedback_items"][0]["evidence"]["take_id"] == SESSION_ID
    assert saved["overall_message"] == "A concise overall note."
    assert database.session["status"] == "readout_ready"
    assert database.session["analysis_state"] == "ready"


def test_material_correction_is_delivery_metadata_not_a_text_mutation():
    command = _command(feedback_items=[_feedback_item(
        state="material_correction",
        family="rewrite_for_clarity",
    )])
    database = FakeDatabase()
    publish_review(database, command, actor_user_id=COACH_ID)
    saved = database.published[0]
    assert saved["delivery_payload"]["material_correction_item_ids"] == [
        "coach:item-1"
    ]
    assert saved["feedback_items"][0]["replacement_text"] == (
        "A clearer replacement."
    )


def test_only_exact_confident_voice_clip_is_queued_for_album_reconciliation():
    command = _command(feedback_items=[
        _feedback_item(family="confident_voice"),
        {**_feedback_item(), "id": "coach:item-2"},
    ])
    database = FakeDatabase()
    publish_review(database, command, actor_user_id=COACH_ID)
    assert database.published[0]["delivery_payload"]["voice_album_clip_ids"] == [
        "66666666-6666-4666-8666-666666666666"
    ]


def test_batch_rejects_duplicate_take_before_transaction():
    database = FakeDatabase()
    with pytest.raises(PublishReviewError) as caught:
        publish_reviews(
            database, [_command(), _command()], actor_user_id=COACH_ID,
        )
    assert caught.value.code == "DUPLICATE_TAKE"
    assert database.published == []
