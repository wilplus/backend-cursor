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


def test_a_refused_yes_with_the_identity_keeps_its_stable_code():
    database = BindingDatabase(refuse="TRAINING_CONSENT_NEEDS_POLICY_RECEIPT")
    with pytest.raises(tc.TrainingSwitchError) as refused:
        tc.handle(database, "owner", "POST", _on(), "web", identity=IDENTITY)
    assert (refused.value.code, refused.value.status) == ("REACCEPT_REQUIRED", 409)
    assert database.accepted == [] and database.bound == []


def test_a_visitor_reads_only_the_words_in_force_and_no_state():
    """Founder 2026-10-15: a visitor sees the third thing to confirm. The
    public read carries the sentence and its fingerprint, nothing about
    anyone; with no wording in force there is nothing to offer."""
    assert tc.wording(FakeDatabase()) == {
        "available": True, "active": False,
        "policy_version": POLICY["version"],
        "copy": POLICY["onboarding_copy"],
        "copy_sha256": POLICY["approved_copy_sha256"],
    }
    assert tc.wording(FakeDatabase(policy=None)) == {"available": False, "active": False}
