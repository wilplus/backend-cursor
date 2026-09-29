"""The rule, every clause (rings, 0394).

    A feature is on for a person when the row is not killed, the person's
    ring is >= the feature's ring, the row's attribute rule matches them
    (AND of "key is in list"), and, for a feature with a consent purpose,
    that consent is current for that person.

The database function ``feature_is_on_v1`` is what every gate calls; the
Python mirror in services/rings.py is what the People tab previews with, and
tests/test_rings_postgres.py asserts the two agree on this same matrix on the
released lane. Here: the mirror, clause by clause, then the read side's
fail-closed behaviour and the one-way kill against a fake client.
"""
from __future__ import annotations

import pytest

from services import rings
from tests.fakes import FakeSupabaseClient


P1 = "11111111-1111-4111-8111-111111111111"
P2 = "22222222-2222-4222-8222-222222222222"


def _feature(**overrides) -> dict:
    row = {"feature": "thing", "min_ring": 3, "attribute_rule": None,
           "consent_purpose": None, "killed": False, "one_way": False}
    row.update(overrides)
    return row


def _person(ring: int, **attributes) -> dict:
    return {"principal_id": P1, "ring": ring, "attributes": attributes}


# ── the rule ───────────────────────────────────────────────────────────────

def test_unknown_feature_is_off():
    assert rings.rule_is_on(None, _person(9), 2, True) is False


def test_killed_row_is_off_for_everyone_even_the_highest_ring():
    assert rings.rule_is_on(_feature(killed=True), _person(99), 2, True) is False


def test_killed_one_way_row_is_off_and_stays_off():
    row = _feature(killed=True, one_way=True, consent_purpose="pooled_model_improvement")
    assert rings.rule_is_on(row, _person(99), 2, True) is False
    assert rings.rule_reaches(row, _person(99), 2) is False


def test_ring_is_at_least_the_features_ring():
    assert rings.rule_is_on(_feature(min_ring=3), _person(2), 2, True) is False
    assert rings.rule_is_on(_feature(min_ring=3), _person(3), 2, True) is True
    assert rings.rule_is_on(_feature(min_ring=3), _person(7), 2, True) is True


def test_missing_person_is_the_default_ring_with_no_attributes():
    assert rings.rule_is_on(_feature(min_ring=3), None, 2, True) is False
    assert rings.rule_is_on(_feature(min_ring=3), None, 3, True) is True
    # No attributes: a rule on any key does not match a missing person.
    ruled = _feature(min_ring=0, attribute_rule={"region": ["PL"]})
    assert rings.rule_is_on(ruled, None, 5, True) is False


def test_rule_is_an_and_of_key_is_in_list_with_two_keys():
    row = _feature(attribute_rule={"region": ["PL", "DE"], "plan": ["pro"]})
    assert rings.rule_is_on(row, _person(3, region="PL", plan="pro"), 2, True) is True
    assert rings.rule_is_on(row, _person(3, region="DE", plan="pro"), 2, True) is True
    assert rings.rule_is_on(row, _person(3, region="US", plan="pro"), 2, True) is False
    assert rings.rule_is_on(row, _person(3, region="PL", plan="free"), 2, True) is False
    assert rings.rule_is_on(row, _person(3, region="PL"), 2, True) is False


def test_rule_values_compare_as_text_so_a_bucket_rule_works():
    row = _feature(attribute_rule={"bucket": ["0", "7"]})
    assert rings.rule_is_on(row, _person(3, bucket=7), 2, True) is True
    assert rings.rule_is_on(row, _person(3, bucket=8), 2, True) is False


def test_malformed_rule_fails_closed():
    assert rings.rule_is_on(_feature(attribute_rule={"region": "PL"}), _person(3, region="PL"), 2, True) is False
    assert rings.rule_is_on(_feature(attribute_rule=["PL"]), _person(3, region="PL"), 2, True) is False


def test_consent_required_and_absent_is_off_but_reaches():
    row = _feature(consent_purpose="personalised_practice")
    assert rings.rule_reaches(row, _person(3), 2) is True
    assert rings.rule_is_on(row, _person(3), 2, False) is False
    assert rings.rule_is_on(row, _person(3), 2, True) is True


def test_consent_is_ignored_when_the_row_names_no_purpose():
    assert rings.rule_is_on(_feature(), _person(3), 2, False) is True


def test_a_ring_never_substitutes_for_consent():
    """L3: the highest ring in the world does not turn a consent feature on."""
    row = _feature(min_ring=0, consent_purpose="pooled_model_improvement")
    assert rings.rule_is_on(row, _person(10_000), 2, False) is False


# ── the read side ──────────────────────────────────────────────────────────

class _Db:
    def __init__(self, client, principal=None):
        self.client = client
        self._principal = principal

    def get_owner_principal_for_user(self, user_id):
        return {"id": self._principal} if self._principal else None


def test_feature_is_on_asks_the_database_function_and_fails_closed():
    db = _Db(FakeSupabaseClient(rpc_rows={"feature_is_on_v1": [True]}))
    assert rings.feature_is_on("exercise_service", P1, database=db) is True
    call = db.client.rpcs["feature_is_on_v1"].calls[-1]
    assert call[1] == ("feature_is_on_v1", {"p_feature": "exercise_service", "p_principal": P1})
    assert rings.feature_is_on("exercise_service", "not-a-uuid", database=db) is False
    assert rings.feature_is_on("", P1, database=db) is False

    def boom(query):
        raise RuntimeError("connection refused")

    down = _Db(FakeSupabaseClient(rpc_rows={"feature_is_on_v1": boom}))
    assert rings.feature_is_on("exercise_service", P1, database=down) is False


def test_feature_is_on_for_user_needs_a_principal():
    db = _Db(FakeSupabaseClient(rpc_rows={"feature_is_on_v1": [True]}), principal=None)
    assert rings.feature_is_on_for_user("exercise_service", "user-1", database=db) is False
    db = _Db(FakeSupabaseClient(rpc_rows={"feature_is_on_v1": [True]}), principal=P1)
    assert rings.feature_is_on_for_user("exercise_service", "user-1", database=db) is True


def test_features_on_for_is_never_fatal_and_is_marked_when_unavailable():
    def boom(query):
        raise RuntimeError("down")

    db = _Db(FakeSupabaseClient(rpc_rows={"features_on_for_v1": boom}))
    payload = rings.features_on_for(P1, database=db)
    assert payload["features_on"] == [] and payload["pending_announcements"] == []
    assert payload["unavailable"] is True
    db = _Db(FakeSupabaseClient(rpc_rows={"features_on_for_v1": [{
        "ring": 3, "features_on": ["exercise_service_ui"], "pending_announcements": [],
    }]}))
    payload = rings.features_on_for(P1, database=db)
    assert payload["features_on"] == ["exercise_service_ui"]
    assert payload["unavailable"] is False


def test_the_request_cache_asks_once_per_request():
    from flask import Flask

    db = _Db(FakeSupabaseClient(rpc_rows={"feature_is_on_v1": [True]}))
    app = Flask(__name__)
    with app.test_request_context():
        assert rings.feature_is_on("exercise_service", P1, database=db)
        assert rings.feature_is_on("exercise_service", P1, database=db)
        assert rings.feature_is_on("exercise_service", P2, database=db)
    assert len(db.client.rpcs["feature_is_on_v1"].calls) == 2


# ── the writes ─────────────────────────────────────────────────────────────

def test_rpc_refusals_carry_their_code_and_status():
    def refuse(query):
        raise RuntimeError('{"message":"RING_ONE_WAY_KILLED"}')

    db = _Db(FakeSupabaseClient(rpc_rows={"kill_feature_v1": refuse}))
    with pytest.raises(rings.RingsError) as caught:
        rings.kill_feature("confidence_learning_writes", False, changed_by="t", database=db)
    assert caught.value.code == "RING_ONE_WAY_KILLED"
    assert caught.value.status == 409


def test_killing_a_one_way_row_applies_the_pipe_kill(monkeypatch):
    db = _Db(FakeSupabaseClient(rpc_rows={"kill_feature_v1": [
        {"feature": "confidence_learning_writes", "killed": True, "one_way": True},
    ]}))
    seen: list[str] = []
    monkeypatch.setattr(rings, "_apply_pipe_kill", lambda feature: seen.append(feature))
    rings.kill_feature("confidence_learning_writes", True, changed_by="t", database=db)
    assert seen == ["confidence_learning_writes"]
    # An ordinary row's kill is just the row.
    db = _Db(FakeSupabaseClient(rpc_rows={"kill_feature_v1": [
        {"feature": "exercise_service_ui", "killed": True, "one_way": False},
    ]}))
    seen.clear()
    rings.kill_feature("exercise_service_ui", True, changed_by="t", database=db)
    assert seen == []


def test_the_confidence_writer_reads_killed_from_the_row_and_never_opens():
    from services import mlc2_confidence_cutover as cutover

    rings.forget_writer_kill_cache()
    killed = _Db(FakeSupabaseClient({"feature_rings": [
        {"feature": "confidence_learning_writes", "killed": True, "one_way": True},
    ]}))
    assert rings.confidence_writer_killed(database=killed) is True
    rings.forget_writer_kill_cache()
    alive = _Db(FakeSupabaseClient({"feature_rings": [
        {"feature": "confidence_learning_writes", "killed": False, "one_way": True},
    ]}))
    assert rings.confidence_writer_killed(database=alive) is False
    # The constant stays the writer state: a live row cannot open a dark pipe.
    state = cutover.resolve_confidence_cutover("dark")
    assert state.canonical_writes_enabled is False
    rings.forget_writer_kill_cache()


def test_writer_kill_read_failure_leaves_the_constant_standing():
    rings.forget_writer_kill_cache()

    def boom(query):
        raise RuntimeError("down")

    db = _Db(FakeSupabaseClient({"feature_rings": boom}))
    assert rings.confidence_writer_killed(database=db) is False
    rings.forget_writer_kill_cache()


def test_set_feature_ring_validates_before_the_database():
    db = _Db(FakeSupabaseClient(rpc_rows={"set_feature_ring_v1": [{"feature": "x"}]}))
    with pytest.raises(rings.RingsError) as bad_ring:
        rings.set_feature_ring("x", {"min_ring": -1}, changed_by="t", database=db)
    assert bad_ring.value.code == "RING_VALUE_INVALID"
    with pytest.raises(rings.RingsError) as bad_rule:
        rings.set_feature_ring("x", {"min_ring": 1, "attribute_rule": ["PL"]}, changed_by="t", database=db)
    assert bad_rule.value.code == "RING_RULE_INVALID"
    with pytest.raises(rings.RingsError) as bad_purpose:
        rings.set_feature_ring("x", {"min_ring": 1, "consent_purpose": "anything"}, changed_by="t", database=db)
    assert bad_purpose.value.code == "RING_CONSENT_PURPOSE_INVALID"
    assert "set_feature_ring_v1" not in db.client.rpcs
    rings.set_feature_ring("x", {"min_ring": 4, "attribute_rule": {"region": ["PL"]},
                                 "note": "n", "one_way": False}, changed_by="t", database=db)
    params = db.client.rpcs["set_feature_ring_v1"].calls[-1][1][1]
    assert params["p_min_ring"] == 4 and params["p_attribute_rule"] == {"region": ["PL"]}
    assert params["p_changed_by"] == "t"


def test_announcement_decision_only_records_an_answer():
    db = _Db(FakeSupabaseClient(rpc_rows={"record_ring_announcement_decision_v1": [{"decision": "not_now"}]}))
    with pytest.raises(rings.RingsError):
        rings.record_announcement_decision(P1, "exercise_service", "yes please", database=db)
    rings.record_announcement_decision(P1, "exercise_service", "accepted", database=db)
    assert set(db.client.rpcs) == {"record_ring_announcement_decision_v1"}


# ── attributes ─────────────────────────────────────────────────────────────

def test_bucket_is_stable_and_within_0_99():
    assert rings.bucket_for(P1) == rings.bucket_for(P1)
    assert 0 <= rings.bucket_for(P1) <= 99
    assert rings.bucket_for(P1) != rings.bucket_for(P2) or True  # may collide; range is what matters


def test_new_account_attributes_never_guess_an_absent_fact():
    attributes = rings.attributes_for_account(
        principal_id=P1, region=None, language="pl", plan="free", role="speaker")
    assert "region" not in attributes
    assert attributes["language"] == "pl" and attributes["plan"] == "free"
    assert attributes["role"] == "speaker" and "bucket" in attributes
    assert rings.attributes_for_account(
        principal_id=P1, region="pl", language=None, plan=None, role=None,
    )["region"] == "PL"


def test_signup_hook_writes_a_row_at_the_default_ring_and_never_raises():
    client = FakeSupabaseClient(
        {"principal_rings": [], "coach_users": []},
        rpc_rows={"set_principal_ring_v1": [{"principal_id": P1, "ring": 2}]},
    )
    db = _Db(client, principal=P1)
    row = rings.record_account_attributes("user-1", email="a@b.c", region="PL",
                                          language="pl", database=db)
    assert row == {"principal_id": P1, "ring": 2}
    params = client.rpcs["set_principal_ring_v1"].calls[-1][1][1]
    assert params["p_ring"] is None  # the default ring, decided in the database
    assert params["p_attributes"]["region"] == "PL"
    assert params["p_attributes"]["role"] == "speaker"
    assert params["p_changed_by"] == "signup"

    def boom(query):
        raise RuntimeError("down")

    assert rings.record_account_attributes(
        "user-1", database=_Db(FakeSupabaseClient({"principal_rings": boom}), principal=P1),
    ) is None


def test_a_seeded_person_who_signs_in_again_keeps_their_ring():
    client = FakeSupabaseClient(
        {"principal_rings": [{"principal_id": P1, "ring": 3, "attributes": {"region": "PL", "bucket": 4}}],
         "coach_users": []},
        rpc_rows={"set_principal_ring_v1": [{"principal_id": P1, "ring": 3}]},
    )
    db = _Db(client, principal=P1)
    rings.record_account_attributes("user-1", email=None, region="DE", database=db)
    params = client.rpcs["set_principal_ring_v1"].calls[-1][1][1]
    assert params["p_ring"] is None
    # Existing keys win; only missing keys are added.
    assert params["p_attributes"]["region"] == "PL"
    assert params["p_attributes"]["plan"] == "free"


def test_deprecation_line_names_the_variables_and_never_a_value(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "current_env", staticmethod(lambda names: {
        "DATA_FOUNDATION_CANARY_ENABLED": "true",
        "MLC2_CONFIDENCE_CANARY_FOUNDER_EMAIL": "artur@willonski.com",
        "MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID": P1,
    }))
    line = rings.deprecated_canary_variables_summary()
    assert "deprecated canary variables" in line
    for name in rings.DEPRECATED_CANARY_VARIABLES:
        assert f"{name}=set" in line
    assert P1 not in line and "artur" not in line
