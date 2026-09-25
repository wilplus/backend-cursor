"""The training switch and its two sweeps (P5 packet §4, items 6-8). DARK.

  * the route answers 410 while the code constant is False, and it is False;
  * turning on records exactly the training toggle's own act, on the wording
    and policy version the database holds, and nothing when already on;
  * a stale wording or policy version is refused before the database;
  * the database's refusals reach the client as stable codes;
  * turning off records the withdrawal and always queues the erasure;
  * the due-copy sweep erases for every person with due copies;
  * the late coach-label sweep is dark, and once on copies a label only for
    a copied moment that has none yet, under the grant it was copied under.

Run: python3 -m pytest tests/test_training_switch.py
"""
from __future__ import annotations

from unittest import mock

import pytest

from services import training_consent as tc
from services import training_corpus as corpus

POLICY = {
    "version": "training-v1",
    "onboarding_copy": "Help improve WillpowerLab",
    "approved_copy_sha256": "c" * 64,
    "terms_version": "terms-3.2",
    "privacy_policy_version": "privacy-3.2",
}


class FakeDatabase:
    def __init__(self, *, policy=POLICY, active=False, refuse=None):
        self.policy = policy
        self.active = active
        self.refuse = refuse
        self.grants: list[dict] = []
        self.withdrawals: list[dict] = []

    def get_active_training_consent_policy(self):
        return self.policy

    def get_mlc2_training_consent_status(self, owner_id):
        if self.active:
            return {"active": True, "grant_event_id": "grant-1"}
        return {"active": False}

    def record_mlc2_training_consent_grant(self, **kwargs):
        if self.refuse:
            raise RuntimeError(self.refuse)
        self.grants.append(kwargs)
        self.active = True
        return {"id": "grant-1"}

    def record_mlc2_training_consent_withdrawal(self, **kwargs):
        self.withdrawals.append(kwargs)
        self.active = False
        return {"id": "withdraw-1"}


def _on(**over):
    body = {"accepted": True, "policy_version": POLICY["version"],
            "copy_sha256": POLICY["approved_copy_sha256"],
            "idempotency_key": "k-1"}
    body.update(over)
    return body


def test_the_switch_is_off_in_code():
    from config import Config

    assert Config.MLC2_TRAINING_SWITCH_ENABLED is False
    assert tc.switch_enabled() is False


def test_the_route_is_closed_while_the_switch_is_off():
    from flask import Flask

    from routes.v2 import training_consent as route

    app = Flask(__name__)
    with app.test_request_context("/v2/user/training-consent", method="POST",
                                  json=_on()):
        with mock.patch.object(route, "handle") as handle:
            response, status = route.v2_user_training_consent.__wrapped__()
    assert status == 410
    assert response.get_json() == {"code": "TRAINING_SWITCH_DISABLED"}
    handle.assert_not_called()


def test_without_a_training_policy_there_is_nothing_to_turn_on():
    database = FakeDatabase(policy=None)
    assert tc.handle(database, "owner", "GET", None, "web") == {
        "available": False, "active": False}
    with pytest.raises(tc.TrainingSwitchError) as refused:
        tc.handle(database, "owner", "POST", _on(), "web")
    assert refused.value.code == "TRAINING_NOT_AVAILABLE"
    assert database.grants == []


def test_the_read_carries_the_wording_the_database_holds():
    state = tc.handle(FakeDatabase(), "owner", "GET", None, "web")
    assert state == {
        "available": True, "active": False, "policy_version": "training-v1",
        "copy": "Help improve WillpowerLab", "copy_sha256": "c" * 64,
    }


def test_turning_on_records_the_toggles_own_act():
    database = FakeDatabase()
    state = tc.handle(database, "owner", "POST", _on(), "web")
    assert state["active"] is True
    (grant,) = database.grants
    assert grant["affirmative_action"] == {
        "accepted": True, "control": "training_toggle",
        "copy_sha256": "c" * 64, "preselected": False,
    }
    assert grant["consent_policy_version"] == "training-v1"
    assert grant["terms_version"] == "terms-3.2"
    assert grant["privacy_policy_version"] == "privacy-3.2"
    assert grant["source_route"] == "/v2/user/training-consent"


def test_turning_on_twice_records_one_yes():
    database = FakeDatabase(active=True)
    tc.handle(database, "owner", "POST", _on(), "web")
    assert database.grants == []


@pytest.mark.parametrize("body, code", [
    (_on(accepted=False), "EXPLICIT_CONSENT_REQUIRED"),
    (_on(accepted="true"), "EXPLICIT_CONSENT_REQUIRED"),
    (_on(copy_sha256="d" * 64), "TRAINING_COPY_CHANGED"),
    (_on(policy_version="training-v0"), "TRAINING_COPY_CHANGED"),
    (_on(idempotency_key=""), "INVALID_INPUT"),
    (_on(idempotency_key="k" * 201), "INVALID_INPUT"),
])
def test_a_yes_that_is_not_explicit_or_not_current_is_refused(body, code):
    database = FakeDatabase()
    with pytest.raises(tc.TrainingSwitchError) as refused:
        tc.handle(database, "owner", "POST", body, "web")
    assert refused.value.code == code
    assert database.grants == []


@pytest.mark.parametrize("raised, code, status", [
    ("TRAINING_CONSENT_NEEDS_POLICY_RECEIPT", "REACCEPT_REQUIRED", 409),
    ("TRAINING_CONSENT_DOES_NOT_MATCH_APPROVAL", "TRAINING_COPY_CHANGED", 409),
    ("something else", "TRAINING_SWITCH_FAILED", 500),
])
def test_database_refusals_become_stable_codes(raised, code, status):
    with pytest.raises(tc.TrainingSwitchError) as refused:
        tc.handle(FakeDatabase(refuse=raised), "owner", "POST", _on(), "web")
    assert (refused.value.code, refused.value.status) == (code, status)


def test_turning_off_withdraws_and_queues_the_erasure():
    database = FakeDatabase(active=True)
    with mock.patch.object(corpus, "enqueue_corpus_purge") as purge:
        state = tc.handle(database, "owner", "DELETE",
                          {"idempotency_key": "k-2"}, "web")
    assert state["active"] is False
    (withdrawal,) = database.withdrawals
    assert withdrawal["grant_event_id"] == "grant-1"
    assert withdrawal["affirmative_action"]["control"] == "training_toggle"
    purge.assert_called_once_with("owner")


def test_turning_off_when_already_off_still_queues_the_erasure():
    database = FakeDatabase(active=False)
    with mock.patch.object(corpus, "enqueue_corpus_purge") as purge:
        tc.handle(database, "owner", "DELETE", {"idempotency_key": "k-3"}, "web")
    assert database.withdrawals == []
    purge.assert_called_once_with("owner")


def test_the_due_copy_sweep_erases_for_every_person_with_due_copies():
    database = mock.Mock()
    database.list_principals_with_due_training_copies.return_value = ["a", "b"]
    with mock.patch.object(corpus, "purge_due_copies",
                           side_effect=[{"erased": 2, "failed": 0},
                                        {"erased": 0, "failed": 1}]) as purge:
        result = corpus.sweep_due_training_copies(database=database, limit=5)
    assert result == {"people": 2, "erased": 2, "failed": 1}
    assert [call.args[0] for call in purge.call_args_list] == ["a", "b"]
    database.list_principals_with_due_training_copies.assert_called_once_with(5)


def test_the_late_label_sweep_is_dark():
    database = mock.Mock()
    assert corpus.sweep_late_coach_labels(database=database) == {
        "status": "disabled"}
    database.list_training_moments.assert_not_called()


def _moment(snippet, kind, grant="grant-1"):
    suffix = {"transcript_span": "transcript",
              "coach_label": "coach_label:yes"}[kind]
    return {"acquisition_principal_id": "p", "training_grant_event_id": grant,
            "source_project_id": "proj", "source_take_id": "take",
            "source_ref": f"snippet:{snippet}:{suffix}", "item_kind": kind}


def test_the_late_label_sweep_copies_only_missing_labels():
    database = mock.Mock()
    database.list_training_moments.return_value = [
        _moment("s1", "transcript_span"),
        _moment("s2", "transcript_span"),
        _moment("s2", "coach_label"),
        # Copied under an earlier grant that was withdrawn and re-given: the
        # label is looked for under the moment's own grant.
        _moment("s3", "transcript_span", grant="grant-2"),
        _moment("s3", "coach_label"),
    ]
    with mock.patch.object(corpus, "copy_enabled", return_value=True), \
            mock.patch.object(corpus, "_copy_coach_label",
                              return_value=True) as copy:
        result = corpus.sweep_late_coach_labels(database=database)
    assert result == {"status": "swept", "labels": 2}
    copied = [(call.args[1]["training_grant_event_id"], call.args[2])
              for call in copy.call_args_list]
    assert copied == [("grant-1", "s1"), ("grant-2", "s3")]
