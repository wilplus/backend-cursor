"""
STORY    As a speaker, I want my training switch to record exactly what I agreed
         to or withdrew, so that my choice is honoured and erasure follows.
         (Critical path: consent.)
OUTCOME
  O1  Turning on records my own act (the training toggle, not preselected)
      on the wording and policy the database holds now, binds my speaker
      identity with it, and records nothing more when already on.
  O2  A yes on stale wording is refused before the database: nothing recorded.
  O3  The database's refusals reach me as stable codes, nothing recorded.
  O4  Turning off records the withdrawal of my grant and queues the erasure.
  O5  A visitor reads only the wording in force, with no state about anyone;
      with no wording in force there is nothing to offer.
PROVES   O1 -> test_turning_on_records_the_toggle_on_the_wording_in_force
         O2 -> test_a_yes_on_stale_wording_is_refused_before_the_database
         O3 -> test_a_refused_yes_with_the_identity_keeps_its_stable_code
         O4 -> test_turning_off_withdraws_and_queues_the_erasure
         O5 -> test_a_visitor_reads_only_the_words_in_force_and_no_state
WHY      The switch is OPEN (door 1, founder 2026-10-01; code switch removed
         2026-10-12), so the route always answers: there is no dark state left.

Covers the Python caller only (services/training_consent.py over a fake
database). The SQL refusals O3 maps (0373/0430) are not proven here, and no
rehearsal-tier test asserts the database's own refusal of other wording.
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
IDENTITY = ("i" * 64, "p" * 64)


class FakeDatabase:
    def __init__(self, *, policy=POLICY, active=False, refuse=None):
        self.policy = policy
        self.active = active
        self.refuse = refuse
        self.accepted: list[dict] = []
        self.bound: list[dict] = []
        self.withdrawals: list[dict] = []

    def get_active_training_consent_policy(self):
        return self.policy

    def get_mlc2_training_consent_status(self, owner_id):
        if self.active:
            return {"active": True, "grant_event_id": "grant-1"}
        return {"active": False}

    def accept_mlc2_training_consent(self, **kwargs):
        if self.refuse:
            raise RuntimeError(self.refuse)
        self.accepted.append(kwargs)
        self.active = True
        return {"consent_event_id": "grant-1", "speaker_bound": True}

    def bind_mlc2_training_speaker(self, **kwargs):
        self.bound.append(kwargs)
        return {"id": "binding-1"}

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


def test_turning_on_records_the_toggle_on_the_wording_in_force():
    database = FakeDatabase()
    state = tc.handle(database, "owner", "POST", _on(), "web", identity=IDENTITY)
    assert state["active"] is True
    (grant,) = database.accepted
    assert grant["acquisition_principal_id"] == "owner"
    assert grant["consent_policy_version"] == POLICY["version"]
    assert grant["affirmative_action"] == {
        "accepted": True, "control": "training_toggle",
        "copy_sha256": POLICY["approved_copy_sha256"], "preselected": False,
    }
    assert (grant["identity_hash"], grant["binding_proof_hash"]) == IDENTITY
    # Already on: no second yes is recorded.
    tc.handle(database, "owner", "POST", _on(idempotency_key="k-2"), "web",
              identity=IDENTITY)
    assert len(database.accepted) == 1


def test_a_yes_on_stale_wording_is_refused_before_the_database():
    database = FakeDatabase()
    with pytest.raises(tc.TrainingSwitchError) as refused:
        tc.handle(database, "owner", "POST", _on(copy_sha256="d" * 64), "web",
                  identity=IDENTITY)
    assert (refused.value.code, refused.value.status) == ("TRAINING_COPY_CHANGED", 409)
    assert database.accepted == [] and database.active is False


def test_a_refused_yes_with_the_identity_keeps_its_stable_code():
    database = FakeDatabase(refuse="TRAINING_CONSENT_NEEDS_POLICY_RECEIPT")
    with pytest.raises(tc.TrainingSwitchError) as refused:
        tc.handle(database, "owner", "POST", _on(), "web", identity=IDENTITY)
    assert (refused.value.code, refused.value.status) == ("REACCEPT_REQUIRED", 409)
    assert database.accepted == [] and database.bound == []


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


def test_a_visitor_reads_only_the_words_in_force_and_no_state():
    """Founder 2026-10-15: a visitor sees the third thing to confirm."""
    assert tc.wording(FakeDatabase()) == {
        "available": True, "active": False,
        "policy_version": POLICY["version"],
        "copy": POLICY["onboarding_copy"],
        "copy_sha256": POLICY["approved_copy_sha256"],
    }
    assert tc.wording(FakeDatabase(policy=None)) == {"available": False, "active": False}
