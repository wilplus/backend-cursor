"""
STORY    As the founder, I want features switched on per person by ring in
         the database, with a one-way kill and change history that cannot be
         edited, so that rollouts are safe and auditable.
OUTCOME
  O1  A person at or above the feature's ring has it; below does not.
  O2  An ordinary kill turns it off and the unkill turns it back on.
  O3  The Python preview (services/rings.rule_reaches) agrees with the
      database on ring, attribute rule, default ring and kill.
  O4  A killed one-way feature refuses the unkill.
  O5  The change tables refuse UPDATE and DELETE.
  O6  The service key can read every ring table but write none.
PROVES   O1 -> test_ring_at_or_above_the_features_ring
         O2 -> test_killed_is_off_and_unkilled_is_on_again
         O3 -> test_the_python_preview_agrees_with_the_database
         O4 -> test_a_one_way_kill_is_never_undone
         O5 -> test_the_change_history_cannot_be_edited
         O6 -> test_the_service_key_reads_but_never_writes_ring_tables
WHY      0394 (a_feature_reaches_a_person_by_ring.sql), R-1. Runs on the
         released lane; every write is rolled back.
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


def _on(cur, feature, pid):
    return _one(cur, "SELECT public.feature_is_on_v1(%s, %s::uuid)", (feature, pid))


def _refused(cur, sql, params=(), match=""):
    cur.execute("SAVEPOINT refused")
    with pytest.raises(psycopg2.Error) as error:
        cur.execute(sql, params)
    cur.execute("ROLLBACK TO SAVEPOINT refused")
    assert match in str(error.value)


def _probe_feature(cur, min_ring, rule=None, one_way=False):
    feature = f"probe_{uuid.uuid4().hex[:10]}"
    _one(cur, "SELECT public.set_feature_ring_v1(%s, %s, %s::jsonb, NULL, 'test', %s, 'test')",
         (feature, min_ring, json.dumps(rule) if rule is not None else None, one_way))
    return feature


def _row(cur, sql, params):
    cur.execute(sql, params)
    found = cur.fetchone()
    return dict(zip([c.name for c in cur.description], found)) if found else None


class TestTheRuleEveryClause:

    def test_ring_at_or_above_the_features_ring(self, cur):
        pid = _principal(cur)
        _set_person(cur, pid, 2)
        assert _on(cur, "exercise_service_ui", pid) is False
        _set_person(cur, pid, 3)
        assert _on(cur, "exercise_service_ui", pid) is True
        _set_person(cur, pid, 4)
        assert _on(cur, "exercise_service_ui", pid) is True
        assert _on(cur, "canonical_take_rows", pid) is False  # 5

    def test_killed_is_off_and_unkilled_is_on_again(self, cur):
        pid = _principal(cur)
        _set_person(cur, pid, 3)
        _one(cur, "SELECT public.kill_feature_v1('exercise_service_ui', true, 'test')")
        assert _on(cur, "exercise_service_ui", pid) is False
        _one(cur, "SELECT public.kill_feature_v1('exercise_service_ui', false, 'test')")
        assert _on(cur, "exercise_service_ui", pid) is True

    def test_the_python_preview_agrees_with_the_database(self, cur):
        default = _one(cur, "SELECT public.ring_default_v1()")
        plain = _probe_feature(cur, 3)
        ruled = _probe_feature(cur, 2, {"country": ["de", "at"]})
        killed = _probe_feature(cur, 0)
        _one(cur, "SELECT public.kill_feature_v1(%s, true, 'test')", (killed,))
        people = [None, (2, None), (3, None), (4, {"country": "de"}),
                  (4, {"country": "fr"}), (1, {"country": "de"})]
        checked = []
        for person in people:
            pid = _principal(cur)
            if person is not None:
                _set_person(cur, pid, person[0], person[1])
            person_row = _row(cur, "SELECT ring, attributes FROM public.principal_rings "
                                   "WHERE principal_id = %s", (pid,))
            for feature in (plain, ruled, killed):
                feature_row = _row(cur, "SELECT * FROM public.feature_rings "
                                        "WHERE feature = %s", (feature,))
                database = _on(cur, feature, pid)
                assert rings.rule_reaches(feature_row, person_row, default) is database, (
                    feature_row, person_row)
                checked.append(database)
        assert True in checked and False in checked


class TestTheSafetyRails:

    def test_a_one_way_kill_is_never_undone(self, cur):
        feature = _probe_feature(cur, 0, one_way=True)
        _one(cur, "SELECT public.kill_feature_v1(%s, true, 'test')", (feature,))
        _refused(cur, "SELECT public.kill_feature_v1(%s, false, 'test')", (feature,),
                 "RING_ONE_WAY_KILLED")
        assert _one(cur, "SELECT killed FROM public.feature_rings WHERE feature = %s",
                    (feature,)) is True

    def test_the_change_history_cannot_be_edited(self, cur):
        feature = _probe_feature(cur, 1)
        pid = _principal(cur)
        _set_person(cur, pid, 3)
        for table, key, value in (("feature_ring_changes", "feature", feature),
                                  ("principal_ring_changes", "principal_id", pid)):
            assert _one(cur, f"SELECT count(*) FROM public.{table} WHERE {key} = %s",
                        (value,)) >= 1
            _refused(cur, f"UPDATE public.{table} SET changed_by = 'x' WHERE {key} = %s",
                     (value,), "append-only")
        _refused(cur, "DELETE FROM public.feature_ring_changes WHERE feature = %s",
                 (feature,), "append-only")

    def test_the_service_key_reads_but_never_writes_ring_tables(self, cur):
        cur.execute("SET LOCAL ROLE service_role")
        for table in TABLES:
            cur.execute(f"SELECT count(*) FROM public.{table}")
            _refused(cur, f"INSERT INTO public.{table} DEFAULT VALUES", (),
                     "permission denied")
            _refused(cur, f"UPDATE public.{table} SET changed_by = changed_by"
                     if table != "ring_announcement_decisions" else
                     f"UPDATE public.{table} SET principal_id = principal_id", (),
                     "permission denied")
