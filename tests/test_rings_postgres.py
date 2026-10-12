"""The rings rule and its RPCs, executed on the released lane (0394).

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
