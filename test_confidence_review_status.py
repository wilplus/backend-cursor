from unittest.mock import patch

from routes.v2.explore_ideal_text import _confidence_review_status_map


class FakeDB:
    def __init__(self, *, owner="yes", coach=None, rereview=None):
        self.owner = owner
        self.coach = coach
        self.rereview = rereview

    def list_owner_voice_album_routes(self, arc_id):
        return [{"snippet_id": "clip-1", "response": self.owner}]

    def get_confidence_labels_by_snippet_ids(self, snippet_ids):
        if self.coach is None:
            return {}
        return {
            "clip-1": [{
                "lane": "coach",
                "state_id": "confidence",
                "self_report": False,
                "unrateable": False,
                "value": self.coach,
            }]
        }

    def get_confidence_rereview(self, snippet_id):
        return self.rereview


MOMENTS = [{"snippet_id": "clip-1"}]


def statuses(database):
    with patch("routes.v2.explore_ideal_text.db", database):
        return _confidence_review_status_map("arc-1", MOMENTS)


def test_owner_yes_waits_for_first_coach_review():
    assert statuses(FakeDB()) == {"clip-1": "pending_coach_review"}


def test_owner_yes_and_coach_yes_is_reviewed():
    assert statuses(FakeDB(coach="yes")) == {"clip-1": "coach_reviewed"}


def test_first_coach_no_remains_pending_until_explicit_rereview():
    assert statuses(FakeDB(coach="no", rereview={"status": "pending"})) == {
        "clip-1": "pending_coach_review"
    }


def test_confirmed_second_no_is_visible_as_not_confirmed():
    assert statuses(FakeDB(
        coach="no", rereview={"status": "confirmed_no"},
    )) == {"clip-1": "not_confirmed"}


def test_owner_no_and_coach_no_stays_silent():
    assert statuses(FakeDB(owner="no", coach="no")) == {}
