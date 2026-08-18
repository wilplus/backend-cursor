from unittest.mock import patch

from services.confidence_review_policy import reconcile_confidence_review


class FakeDB:
    def __init__(self, owner="yes", rereview=None):
        self.owner = owner
        self.rereview = rereview
        self.messages = []

    def list_owner_voice_album_routes(self, arc_id):
        return [{"snippet_id": "clip-1", "response": self.owner}]

    def get_confidence_rereview(self, snippet_id):
        return self.rereview

    def upsert_confidence_rereview(self, **row):
        self.rereview = {**row, "status": "pending"}
        return True

    def resolve_confidence_rereview(
        self, snippet_id, *, confirmed_no=False, coach_note=None,
    ):
        self.rereview = (
            {"snippet_id": snippet_id, "status": "confirmed_no",
             "coach_note": coach_note}
            if confirmed_no else None
        )
        return True

    def insert_lounge_messages(self, user_id, messages):
        self.messages.extend(messages)
        return messages


SESSION = {"id": "take-1", "arc_id": "arc-1", "user_id": "owner-1"}


def reconcile(db, **kwargs):
    return reconcile_confidence_review(
        db, snippet_id="clip-1", session=SESSION,
        owner_user_id="owner-1", **kwargs)


def test_first_user_yes_coach_no_requests_rereview():
    db = FakeDB()
    assert reconcile(db, coach_value="no", coach_write=True) == \
        "pending_rereview"
    assert db.rereview["status"] == "pending"
    assert db.messages == []


def test_owner_retry_cannot_confirm_a_coach_no():
    db = FakeDB(rereview={"status": "pending"})
    assert reconcile(db, coach_value="no") == "pending_rereview"
    assert db.rereview["status"] == "pending"
    assert db.messages == []


def test_explicit_second_listen_confirms_no_and_notifies_once():
    db = FakeDB(rereview={"status": "pending"})
    assert reconcile(
        db, coach_value="no", coach_note="The ending softened.",
        coach_write=True, is_rereview=True,
    ) == "not_confirmed"
    assert db.rereview["status"] == "confirmed_no"
    assert db.messages[0]["metadata"]["confidence_material_correction"] is True
    assert "The ending softened." in db.messages[0]["body"]


def test_user_no_coach_no_is_silent():
    db = FakeDB(owner="no", rereview={"status": "pending"})
    assert reconcile(db, coach_value="no", coach_write=True) == "silent"
    assert db.rereview is None
    assert db.messages == []


def test_rereview_yes_resolves_and_refreshes_album():
    db = FakeDB(rereview={"status": "pending"})
    with patch("services.voice_album.refresh_voice_album") as refresh, \
            patch("services.arc_notifications.fire_voice_album_ready") as intro:
        assert reconcile(
            db, coach_value="yes", coach_write=True, is_rereview=True,
        ) == "coach_reviewed"
    assert db.rereview is None
    refresh.assert_called_once_with("arc-1", database=db)
    intro.assert_called_once_with(db, "owner-1", "arc-1")
