"""
STORY    I want to ask Artur for private feedback on the exact Take.
OUTCOME  I can see both offers, send once, and only Artur can open the review.
PROVES   test_direct_request_offers_the_exact_take_without_sending
         test_private_email_keeps_a_stable_delivery_key_on_retry
         test_private_inbox_is_confined_to_the_assigned_reviewer
WHY      N688, private access and an explicit handoff.
"""
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from services import human_coach_offer, human_coach_reviews as reviews


def test_direct_request_offers_the_exact_take_without_sending(monkeypatch):
    user, project, take, artur = [str(uuid4()) for _ in range(4)]
    db = Mock()
    monkeypatch.setattr(reviews, "email_available", lambda: True)
    monkeypatch.setattr(reviews, "reviewer", lambda database: artur)
    owns_project = Mock()
    owns_take = Mock()
    monkeypatch.setattr(reviews, "require_project", owns_project)
    monkeypatch.setattr(reviews, "preview", owns_take)
    monkeypatch.setattr(human_coach_offer.calendar, "settings", lambda: {})
    assert human_coach_offer.explicit_request("Could I speak with Artur?")
    assert not human_coach_offer.explicit_request("I don't want to book a call.")
    result = human_coach_offer.offer(db, user, "Could I speak with Artur?", project=project, take=take)
    assert result["row_metadata"]["human_coach_handoff"] == {
        "project_id": project, "take_session_id": take, "book": True, "send": True,
    }
    owns_take.assert_called_once_with(db, user, project, take)


def test_private_email_keeps_a_stable_delivery_key_on_retry(monkeypatch):
    from services import email_service, lab_send

    user, take, review_id = [str(uuid4()) for _ in range(3)]
    adapter = SimpleNamespace(authorization=Mock())
    permit = Mock(return_value=(adapter, "permit"))
    outbound = Mock(return_value={"sent": True, "resend_response": {"id": "email-1"}})
    monkeypatch.setattr(email_service, "send_email_resend", outbound)
    monkeypatch.setattr(lab_send, "_authorize_coach_delivery", permit)
    request = {"id": review_id, "note": "Please listen to the <opening>."}
    for _ in range(2):
        assert reviews._email(None, user, {"id": take}, request) == "email-1"
    first, retry = (call.kwargs for call in outbound.call_args_list)
    assert first == retry
    assert first["to"] == reviews.Config.ADMIN_EMAIL
    assert first["idempotency_key"] == f"private-take-review:{review_id}"
    assert "&lt;opening&gt;" in first["html"]
    assert permit.call_args.kwargs["provider"] == "resend"


def test_private_inbox_is_confined_to_the_assigned_reviewer():
    foreign, review_id = str(uuid4()), str(uuid4())
    db = Mock()
    query = db.client.table.return_value.select.return_value
    query.eq.return_value = query
    query.limit.return_value.execute.return_value.data = []
    with pytest.raises(reviews.HandoffError) as blocked:
        reviews.inbox(db, foreign, review_id)
    assert blocked.value.status == 404
    query.eq.assert_any_call("recipient_user_id", foreign)
    db.client.table.assert_called_once_with(reviews.TABLE)
