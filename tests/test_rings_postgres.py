"""The rings rule and its RPCs, executed on the released lane (0393).

Every clause of the rule runs against the real ``feature_is_on_v1``, the
Python mirror in services/rings.py is checked against it on the same matrix,
the one-way kill refuses the unkill, the change tables refuse UPDATE and
DELETE, and the service key can read but not write any ring table (R-1).

Every write happens inside a transaction that is rolled back; the lane is
left as it was built. The target must be a disposable local database whose
name starts with ``willab_confident_moment_``.
"""
from __future__ import annotations

import json
import os
import uuid

import psycopg2
import psycopg2.errors
import pytest

from services import rings

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

TABLES = (
    "feature_rings", "principal_rings", "ring_settings", "ring_announcements",
    "ring_announcement_decisions", "feature_ring_changes",
    "principal_ring_changes", "ring_setting_changes",
)
SEEDED_FEATURES = {
    "exercise_service": 3, "exercise_service_ui": 3, "coach_inline_authoring": 4,
    "confident_moment_bundles": 4, "rooting_coverage": 4,
    "canonical_take_rows": 5, "confidence_learning_writes": 5,
}


@pytest.fixture(scope="module")
def conn():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    if not parsed.get("host", "").startswith(
        ("/tmp/willab-", "/private/tmp/willab-")
    ):
        raise RuntimeError("Refusing a database outside the rehearsal socket")
    connection = psycopg2.connect(DSN)
    connection.autocommit = False
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def cur(conn):
    """One rolled-back transaction per test."""
    cursor = conn.cursor()
    try:
        yield cursor
    finally:
        conn.rollback()
        cursor.close()


def _one(cur, sql, params=()):
    cur.execute(sql, params)
    return cur.fetchone()[0]


def _principal(cur):
    """A fresh owner principal (the lane has the table; the FK-free ring row
    would accept any uuid, but a real principal is what production has)."""
    pid = str(uuid.uuid4())
    cur.execute(
        "INSERT INTO public.owner_principals (id, user_id, guest_secret_hash) "
        "VALUES (%s, NULL, %s)", (pid, f"rehearsal-{pid}"),
    )
    return pid


def _set_person(cur, pid, ring, attributes=None):
    return _one(cur, "SELECT public.set_principal_ring_v1(%s::uuid, %s, %s::jsonb, 'test')",
                (pid, ring, json.dumps(attributes) if attributes is not None else None))


def _set_feature(cur, feature, min_ring, rule=None, purpose=None, one_way=False):
    return _one(cur, "SELECT public.set_feature_ring_v1(%s, %s, %s::jsonb, %s, 'note', %s, 'test')",
                (feature, min_ring, json.dumps(rule) if rule is not None else None, purpose, one_way))


def _on(cur, feature, pid):
    return _one(cur, "SELECT public.feature_is_on_v1(%s, %s::uuid)", (feature, pid))


class TestTheLaneCarriesTheMigration:
    def test_every_table_exists(self, cur):
        for table in TABLES:
            assert _one(cur, "SELECT to_regclass(%s) IS NOT NULL", (f"public.{table}",)), table

    def test_the_seed_is_present_and_nobody_is_at_a_canary_ring(self, cur):
        cur.execute("SELECT feature, min_ring, killed FROM public.feature_rings")
        rows = {f: (r, k) for f, r, k in cur.fetchall()}
        for feature, ring in SEEDED_FEATURES.items():
            assert rows[feature][0] == ring, feature
            assert rows[feature][1] is False
        assert _one(cur, "SELECT public.ring_default_v1()") == 2
        assert _one(cur, "SELECT count(*) FROM public.principal_rings WHERE ring >= 4") == 0

    def test_the_confidence_row_is_one_way_and_names_the_phase2_purpose(self, cur):
        cur.execute("SELECT one_way, consent_purpose FROM public.feature_rings "
                    "WHERE feature = 'confidence_learning_writes'")
        assert cur.fetchone() == (True, "pooled_model_improvement")

    def test_announcements_are_placeholders_only(self, cur):
        cur.execute("SELECT title, body FROM public.ring_announcements")
        rows = cur.fetchall()
        assert rows
        for title, body in rows:
            assert title.startswith("[founder copy]") and body.startswith("[founder copy]")


class TestTheRuleEveryClause:
    def test_unknown_feature_is_off(self, cur):
        pid = _principal(cur)
        _set_person(cur, pid, 99)
        assert _on(cur, "no_such_feature", pid) is False

    def test_missing_person_is_the_default_ring_with_no_attributes(self, cur):
        pid = _principal(cur)  # no principal_rings row
        assert _on(cur, "exercise_service_ui", pid) is False  # default 2 < 3
        _one(cur, "SELECT public.set_ring_default_v1(3, 'test')")
        assert _on(cur, "exercise_service_ui", pid) is True
        _set_feature(cur, "regional", 0, {"region": ["PL"]})
        assert _on(cur, "regional", pid) is False  # no attributes to match

    def test_ring_at_or_above_the_features_ring(self, cur):
        pid = _principal(cur)
        _set_person(cur, pid, 2)
        assert _on(cur, "exercise_service_ui", pid) is False
        _set_person(cur, pid, 3)
        assert _on(cur, "exercise_service_ui", pid) is True
        _set_person(cur, pid, 4)
        assert _on(cur, "exercise_service_ui", pid) is True
        assert _on(cur, "canonical_take_rows", pid) is False  # 5

    def test_a_rule_with_two_keys_is_an_and(self, cur):
        pid = _principal(cur)
        _set_person(cur, pid, 3, {"region": "PL", "plan": "pro", "bucket": 7})
        _set_feature(cur, "regional", 3, {"region": ["PL", "DE"], "plan": ["pro"]})
        assert _on(cur, "regional", pid) is True
        _set_feature(cur, "regional", 3, {"region": ["DE"], "plan": ["pro"]})
        assert _on(cur, "regional", pid) is False
        _set_feature(cur, "regional", 3, {"region": ["PL"], "plan": ["free"]})
        assert _on(cur, "regional", pid) is False
        _set_feature(cur, "regional", 3, {"region": ["PL"], "bucket": ["0", "7"]})
        assert _on(cur, "regional", pid) is True  # text comparison

    def test_killed_is_off_and_unkilled_is_on_again(self, cur):
        pid = _principal(cur)
        _set_person(cur, pid, 3)
        _one(cur, "SELECT public.kill_feature_v1('exercise_service_ui', true, 'test')")
        assert _on(cur, "exercise_service_ui", pid) is False
        _one(cur, "SELECT public.kill_feature_v1('exercise_service_ui', false, 'test')")
        assert _on(cur, "exercise_service_ui", pid) is True

    def test_a_killed_one_way_row_is_off_for_the_highest_ring_and_refuses_unkill(self, cur, conn):
        pid = _principal(cur)
        _set_person(cur, pid, 999)
        _one(cur, "SELECT public.kill_feature_v1('confidence_learning_writes', true, 'test')")
        assert _on(cur, "confidence_learning_writes", pid) is False
        assert _one(cur, "SELECT public.feature_reaches_v1('confidence_learning_writes', %s::uuid)", (pid,)) is False
        cur.execute("SAVEPOINT unkill")
        with pytest.raises(psycopg2.errors.RaiseException, match="RING_ONE_WAY_KILLED"):
            cur.execute("SELECT public.kill_feature_v1('confidence_learning_writes', false, 'test')")
        cur.execute("ROLLBACK TO SAVEPOINT unkill")
        with pytest.raises(psycopg2.errors.RaiseException, match="RING_ONE_WAY_KILLED"):
            cur.execute("SELECT public.set_feature_ring_v1('confidence_learning_writes', 0, NULL, NULL, 'x', true, 'test')")

    def test_consent_required_and_absent_is_off_but_reaches(self, cur):
        pid = _principal(cur)
        _set_person(cur, pid, 3)
        assert _one(cur, "SELECT public.feature_reaches_v1('exercise_service', %s::uuid)", (pid,)) is True
        assert _on(cur, "exercise_service", pid) is False
        # And the highest ring in the world does not substitute for it (L3).
        _set_person(cur, pid, 10_000)
        assert _on(cur, "exercise_service", pid) is False
        assert _on(cur, "confidence_learning_writes", pid) is False


class TestPythonMirrorAgreesWithTheDatabase:
    CASES = [
        # (ring or None, attributes, min_ring, rule, killed)
        (None, None, 2, None, False),
        (None, None, 3, None, False),
        (3, {}, 3, None, False),
        (2, {}, 3, None, False),
        (7, {"region": "PL"}, 3, {"region": ["PL", "DE"]}, False),
        (7, {"region": "US"}, 3, {"region": ["PL", "DE"]}, False),
        (7, {"region": "PL"}, 3, {"region": ["PL"], "plan": ["pro"]}, False),
        (7, {"region": "PL", "plan": "pro"}, 3, {"region": ["PL"], "plan": ["pro"]}, False),
        (7, {"bucket": 7}, 3, {"bucket": ["0", "7"]}, False),
        (99, {}, 0, None, True),
        (None, None, 0, {"region": ["PL"]}, False),
    ]

    @pytest.mark.parametrize("case", CASES)
    def test_same_answer(self, cur, case):
        ring, attributes, min_ring, rule, killed = case
        pid = _principal(cur)
        person = None
        if ring is not None:
            _set_person(cur, pid, ring, attributes)
            person = {"ring": ring, "attributes": attributes or {}}
        _set_feature(cur, "mirror_case", min_ring, rule)
        if killed:
            _one(cur, "SELECT public.kill_feature_v1('mirror_case', true, 'test')")
        feature_row = {"feature": "mirror_case", "min_ring": min_ring,
                       "attribute_rule": rule, "consent_purpose": None,
                       "killed": killed, "one_way": False}
        default = _one(cur, "SELECT public.ring_default_v1()")
        assert rings.rule_is_on(feature_row, person, default, True) == _on(cur, "mirror_case", pid)


class TestTheLoginRead:
    def test_features_on_for_carries_the_ring_the_list_and_the_pending_sheet(self, cur):
        pid = _principal(cur)
        _set_person(cur, pid, 3, {"region": "PL"})
        payload = _one(cur, "SELECT public.features_on_for_v1(%s::uuid)", (pid,))
        assert payload["ring"] == 3 and payload["attributes"] == {"region": "PL"}
        assert payload["features_on"] == ["exercise_service_ui"]
        pending = {p["feature"]: p for p in payload["pending_announcements"]}
        assert "exercise_service" in pending  # reaches, consent absent, announced
        assert pending["exercise_service"]["consent_purpose"] == "personalised_practice"
        assert pending["exercise_service"]["title"].startswith("[founder copy]")
        assert "confidence_learning_writes" not in pending  # ring 5, not reached
        for key in ("score", "verdict", "rating"):
            assert key not in json.dumps(payload)

    def test_not_now_silences_until_reannounced_and_creates_no_consent(self, cur):
        pid = _principal(cur)
        _set_person(cur, pid, 3)
        _one(cur, "SELECT public.record_ring_announcement_decision_v1(%s::uuid, 'exercise_service', 'not_now')", (pid,))
        payload = _one(cur, "SELECT public.features_on_for_v1(%s::uuid)", (pid,))
        assert payload["pending_announcements"] == []
        assert _on(cur, "exercise_service", pid) is False
        _one(cur, "SELECT public.record_ring_announcement_decision_v1(%s::uuid, 'exercise_service', 'accepted')", (pid,))
        assert _on(cur, "exercise_service", pid) is False  # an answer is not a consent
        _one(cur, "SELECT public.set_ring_announcement_v1('exercise_service', '[founder copy] t', '[founder copy] b', true, false, 'test')")
        payload = _one(cur, "SELECT public.features_on_for_v1(%s::uuid)", (pid,))
        assert [p["feature"] for p in payload["pending_announcements"]] == ["exercise_service"]

    def test_the_readiness_read_names_eligible_principals_only(self, cur):
        pid = _principal(cur)
        health = _one(cur, "SELECT public.get_ring_confidence_readiness_v1()")
        assert health["eligible_principal_count"] == 0
        _set_person(cur, pid, 5)
        health = _one(cur, "SELECT public.get_ring_confidence_readiness_v1()")
        assert health["eligible_principal_count"] == 1
        assert health["confidence_ring_row_one_way"] is True
        assert health["ring_readiness_contract_version"] == "rings-confidence-readiness-v1"


class TestEveryChangeIsARow:
    def test_writes_append_and_the_change_tables_refuse_mutation(self, cur):
        pid = _principal(cur)
        before = _one(cur, "SELECT count(*) FROM public.principal_ring_changes")
        _set_person(cur, pid, 3)
        _set_person(cur, pid, 4)
        _one(cur, "SELECT public.set_principal_rings_bulk_v1(ARRAY[%s]::uuid[], 5, 'test')", (pid,))
        assert _one(cur, "SELECT count(*) FROM public.principal_ring_changes") == before + 3
        cur.execute("SAVEPOINT mutate")
        with pytest.raises(psycopg2.errors.RaiseException, match="append-only"):
            cur.execute("UPDATE public.principal_ring_changes SET ring = 0 WHERE principal_id = %s", (pid,))
        cur.execute("ROLLBACK TO SAVEPOINT mutate")
        with pytest.raises(psycopg2.errors.RaiseException, match="append-only"):
            cur.execute("DELETE FROM public.feature_ring_changes WHERE feature = 'exercise_service_ui'")
        cur.execute("ROLLBACK TO SAVEPOINT mutate")
        with pytest.raises(psycopg2.errors.RaiseException, match="append-only"):
            cur.execute("UPDATE public.feature_ring_changes SET note = 'x' WHERE feature = 'exercise_service_ui'")
        cur.execute("ROLLBACK TO SAVEPOINT mutate")
        # A person's history goes with the person (the purge's DELETE).
        cur.execute("DELETE FROM public.principal_ring_changes WHERE principal_id = %s", (pid,))
        assert _one(cur, "SELECT count(*) FROM public.principal_ring_changes WHERE principal_id = %s", (pid,)) == 0
        assert _one(cur, "SELECT count(*) FROM public.ring_setting_changes") >= 1


PURGE_DELETES = ("principal_rings", "principal_ring_changes", "ring_announcement_decisions")


class TestServiceRoleReadsAndNeverWrites:
    @pytest.mark.parametrize("table", TABLES)
    def test_select_is_granted_and_writes_are_refused(self, cur, table):
        cur.execute("SAVEPOINT role")
        cur.execute("SET LOCAL ROLE service_role")
        cur.execute(f"SELECT count(*) FROM public.{table}")
        assert cur.fetchone()[0] >= 0
        cur.execute("SAVEPOINT attempt")
        if table in PURGE_DELETES:
            # The purge's door: DELETE, and only DELETE, on the person tables.
            cur.execute(f"DELETE FROM public.{table} WHERE false")
        else:
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute(f"DELETE FROM public.{table} WHERE false")
        cur.execute("ROLLBACK TO SAVEPOINT attempt")
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute(f"UPDATE public.{table} SET changed_at = now() WHERE false"
                        if table not in ("ring_announcement_decisions",)
                        else f"UPDATE public.{table} SET decided_at = now() WHERE false")
        cur.execute("ROLLBACK TO SAVEPOINT attempt")
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            cur.execute(f"INSERT INTO public.{table} SELECT * FROM public.{table} WHERE false")
        cur.execute("ROLLBACK TO SAVEPOINT role")

    def test_the_rpcs_are_executable_by_service_role(self, cur):
        cur.execute("SAVEPOINT role")
        cur.execute("SET LOCAL ROLE service_role")
        assert _one(cur, "SELECT public.ring_default_v1()") == 2
        assert _one(cur, "SELECT public.feature_is_on_v1('exercise_service_ui', %s::uuid)",
                    (str(uuid.uuid4()),)) is False
        cur.execute("ROLLBACK TO SAVEPOINT role")
