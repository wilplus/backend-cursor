"""
STORY    As the founder, I want the feature-ring preview to follow the same
         rule as the database, a broken read to close the door, and a
         one-way kill to stay killed, so that what I see in the People tab
         is what people get and no ring ever stands in for consent.
OUTCOME
  O1  Each clause decides: not killed, ring >= the feature's ring, every
      attribute in its allowed list; a person with no row has the default
      ring and no attributes.
  O2  A feature with a consent purpose is on only while that consent is
      current; the highest ring does not replace it.
  O3  The gate's read says yes when the database says yes, and a failed
      read or an invalid principal answers no.
  O4  Killing a one-way row is felt at once by the confidence writer (no
      wait for its cache), and the database's refusal of the unkill
      reaches the panel as 409.
PROVES   O1 -> test_each_clause_of_the_rule_decides
         O2 -> test_a_ring_never_substitutes_for_consent
         O3 -> test_the_gate_read_follows_the_database_and_fails_closed
         O4 -> test_a_one_way_kill_is_felt_at_once_and_cannot_be_undone
WHY      Rings 0394. The database rule itself is proved on the released lane
         (tests/test_rings_postgres.py); this is the Python side.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services import rings

P1 = "11111111-1111-4111-8111-111111111111"


def _feature(**overrides) -> dict:
    row = {"feature": "thing", "min_ring": 3, "attribute_rule": None,
           "consent_purpose": None, "killed": False, "one_way": False}
    row.update(overrides)
    return row


def _person(ring: int, **attributes) -> dict:
    return {"principal_id": P1, "ring": ring, "attributes": attributes}


@pytest.mark.parametrize("feature,person,default_ring,on", [
    (_feature(), _person(3), 2, True),                       # ring == feature ring
    (_feature(), _person(2), 2, False),                      # ring below
    (_feature(killed=True), _person(9), 2, False),           # killed
    (_feature(), None, 3, True),                             # no row: default ring
    (_feature(), None, 2, False),
    (_feature(attribute_rule={"region": ["pl", "de"]}), _person(3, region="pl"), 2, True),
    (_feature(attribute_rule={"region": ["pl", "de"]}), _person(3, region="fr"), 2, False),
    (_feature(attribute_rule={"region": ["pl"]}), _person(3), 2, False),  # key missing
    (_feature(attribute_rule={"region": ["pl"], "plan": ["paid"]}),
     _person(3, region="pl", plan="free"), 2, False),         # AND of clauses
    (None, _person(9), 2, False),                            # unknown feature
])
def test_each_clause_of_the_rule_decides(feature, person, default_ring, on):
    assert rings.rule_is_on(feature, person, default_ring, False) is on


def test_a_ring_never_substitutes_for_consent():
    row = _feature(min_ring=0, consent_purpose="pooled_model_improvement")
    assert rings.rule_is_on(row, _person(10_000), 2, False) is False
    assert rings.rule_is_on(row, _person(0), 2, True) is True


class _Database:
    """The app database's client: RPCs answered by name, one table."""

    def __init__(self, rpcs=None, feature_rows=()):
        self.rpcs = rpcs or {}
        self.feature_rows = list(feature_rows)
        self.calls: list = []
        self.client = self

    def rpc(self, name, params):
        self.calls.append(name)
        answer = self.rpcs[name]
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(execute=lambda: SimpleNamespace(
            data=answer(params) if callable(answer) else answer))

    def table(self, _name):
        rows = self.feature_rows
        query = SimpleNamespace()
        query.select = query.eq = query.limit = lambda *_a: query
        query.execute = lambda: SimpleNamespace(data=[dict(r) for r in rows])
        return query


def test_the_gate_read_follows_the_database_and_fails_closed():
    assert rings.feature_is_on(
        "thing", P1, database=_Database({"feature_is_on_v1": True})) is True
    assert rings.feature_is_on(
        "thing", P1, database=_Database({"feature_is_on_v1": False})) is False
    assert rings.feature_is_on(
        "thing", P1,
        database=_Database({"feature_is_on_v1": ConnectionError("down")})) is False
    never_asked = _Database({"feature_is_on_v1": True})
    assert rings.feature_is_on("thing", "not-a-uuid", database=never_asked) is False
    assert never_asked.calls == []


def test_a_one_way_kill_is_felt_at_once_and_cannot_be_undone():
    row = _feature(feature=rings.CONFIDENCE_LEARNING_WRITES, one_way=True)
    database = _Database(feature_rows=[row])
    rings.forget_writer_kill_cache()
    try:
        assert rings.confidence_writer_killed(database=database, now=100.0) is False

        def kill(_params):
            row["killed"] = True
            return dict(row)

        database.rpcs["kill_feature_v1"] = kill
        rings.kill_feature(rings.CONFIDENCE_LEARNING_WRITES, True,
                           changed_by="founder", database=database)
        # Same instant: the cached "not killed" must not survive the kill.
        assert rings.confidence_writer_killed(database=database, now=100.0) is True

        database.rpcs["kill_feature_v1"] = RuntimeError("RING_ONE_WAY_KILLED")
        with pytest.raises(rings.RingsError) as refused:
            rings.kill_feature(rings.CONFIDENCE_LEARNING_WRITES, False,
                               changed_by="founder", database=database)
        assert (refused.value.code, refused.value.status) == ("RING_ONE_WAY_KILLED", 409)
    finally:
        rings.forget_writer_kill_cache()
