"""The owner's own answers on a Take, for the answered bookmark (Q19 A)."""
from __future__ import annotations

from services.owner_feedback_answers import owner_answers


class _Db:
    def __init__(self, owner="u1"):
        self.owner = owner

    def v2_get_session_by_id(self, sid):
        return {"id": sid, "user_id": self.owner}

    def list_take_feedback_self_reports(self, sid, owner):
        return [
            {"feedback_id": "f1", "feedback_family": "confident_voice",
             "response": "no", "created_at": "1"},
            {"feedback_id": "f1", "feedback_family": "confident_voice",
             "response": "in_between", "created_at": "2"},
            {"feedback_id": "f2", "feedback_family": "rewrite_clarity",
             "response": "apply_suggestion", "created_at": "3"},
            {"feedback_id": None, "response": "yes"},
        ]


def test_the_latest_answer_per_item():
    answers = {a["feedback_id"]: a["response"]
               for a in owner_answers(_Db(), "t1", "u1")}
    assert answers == {"f1": "in_between", "f2": "apply_suggestion"}


def test_someone_elses_take_is_refused():
    assert owner_answers(_Db(owner="other"), "t1", "u1") is None
