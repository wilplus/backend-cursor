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


def test_the_switch_is_open_in_code_since_the_founders_sentence():
    """Door 1 opened 2026-10-01 ("open door 1"). The constant is True; the
    card still waits on a policy row, which `_read` reports as
    available=False until one exists."""
    from config import Config

    assert Config.MLC2_TRAINING_SWITCH_ENABLED is True
    assert tc.switch_enabled() is True


def test_the_route_is_closed_while_the_switch_is_off():
    """The 410 the route gave until 2026-10-01, kept as the contract for a
    closed switch: patched shut here, since the constant is now True."""
    from flask import Flask

    from routes.v2 import training_consent as route

    app = Flask(__name__)
    with app.test_request_context("/v2/user/training-consent", method="POST",
                                  json=_on()):
        with mock.patch.object(route, "handle") as handle, \
                mock.patch.object(route, "switch_enabled", return_value=False):
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


# ── The one consent authority binds the speaker (N48.5 Q27 A; 0430; F-3) ───

IDENTITY = ("i" * 64, "p" * 64)


class BindingDatabase(FakeDatabase):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.accepted: list[dict] = []
        self.bound: list[dict] = []
        self.bind_raises = False

    def accept_mlc2_training_consent(self, **kwargs):
        if self.refuse:
            raise RuntimeError(self.refuse)
        self.accepted.append(kwargs)
        self.active = True
        return {"consent_event_id": "grant-1", "speaker_bound": True}

    def bind_mlc2_training_speaker(self, **kwargs):
        if self.bind_raises:
            raise RuntimeError("database down")
        self.bound.append(kwargs)
        return {"id": "binding-1"}


def test_a_yes_with_the_verified_identity_binds_the_speaker_in_one_call():
    database = BindingDatabase()
    state = tc.handle(database, "owner", "POST", _on(), "web", identity=IDENTITY)
    assert state["active"] is True
    assert database.grants == []  # never the plain writer when the identity is there
    (accepted,) = database.accepted
    assert accepted["identity_hash"] == IDENTITY[0]
    assert accepted["binding_proof_hash"] == IDENTITY[1]
    assert accepted["identity_version"] == "supabase-auth-sub-v1"
    assert accepted["bound_by"] == "authenticated-training-consent-v1"
    assert accepted["affirmative_action"]["control"] == "training_toggle"


def test_a_refused_yes_with_the_identity_keeps_its_stable_code():
    database = BindingDatabase(refuse="TRAINING_CONSENT_NEEDS_POLICY_RECEIPT")
    with pytest.raises(tc.TrainingSwitchError) as refused:
        tc.handle(database, "owner", "POST", _on(), "web", identity=IDENTITY)
    assert (refused.value.code, refused.value.status) == ("REACCEPT_REQUIRED", 409)
    assert database.accepted == [] and database.bound == []


def test_an_earlier_yes_is_bound_when_the_card_reads_the_switch():
    database = BindingDatabase(active=True)
    state = tc.handle(database, "owner", "GET", None, "web", identity=IDENTITY)
    assert state["active"] is True
    (bound,) = database.bound
    assert bound["acquisition_principal_id"] == "owner"
    assert bound["identity_hash"] == IDENTITY[0]


def test_without_a_yes_the_read_binds_nobody():
    database = BindingDatabase(active=False)
    tc.handle(database, "owner", "GET", None, "web", identity=IDENTITY)
    assert database.bound == []


def test_a_failing_binding_never_fails_the_card():
    database = BindingDatabase(active=True)
    database.bind_raises = True
    state = tc.handle(database, "owner", "GET", None, "web", identity=IDENTITY)
    assert state["active"] is True


def test_turning_on_twice_binds_an_unbound_earlier_yes_and_records_no_second_yes():
    database = BindingDatabase(active=True)
    tc.handle(database, "owner", "POST", _on(), "web", identity=IDENTITY)
    assert database.accepted == [] and len(database.bound) == 1


def test_the_route_hands_the_verified_identity_to_the_switch():
    from flask import Flask, request

    from routes.v2 import training_consent as route
    from services.speaker_identity import identity_coordinates

    payload = {"sub": "user-1", "iss": "https://auth.example/auth/v1",
               "email": "Person@Example.com"}
    app = Flask(__name__)
    with app.test_request_context("/v2/user/training-consent", method="GET"):
        request.user_id = "user-1"
        request.token_payload = payload
        with mock.patch.object(route, "handle", return_value={"active": False}) as handle, \
                mock.patch.object(route._repository, "owner_for_user",
                                  return_value=mock.Mock(id="owner-1")):
            response, status = route.v2_user_training_consent.__wrapped__()
    assert status == 200
    assert handle.call_args.kwargs["identity"] == identity_coordinates(payload, "user-1")
    identity, proof = identity_coordinates(payload, "user-1")
    assert len(identity) == len(proof) == 64 and identity != proof
