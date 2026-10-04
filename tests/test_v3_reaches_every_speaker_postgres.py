"""0415 on a real database: V3's source gate no longer requires the
allowlist, can be switched back without a deploy, and still refuses a
principal with an open account-wide purge.

Founder 2026-10-03 (N29 answer 1, "Every speaker"); F1 Repair Plan Phase 2.
Every write happens inside a transaction that is rolled back.
"""
from __future__ import annotations

import os
import uuid

import psycopg2
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

GATE = "SELECT public.require_mlc3_service_principal_v1(%s)"


@pytest.fixture
def cur():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cursor:
            yield cursor
    finally:
        conn.rollback()
        conn.close()


def _principal(cur) -> str:
    cur.execute("""
        INSERT INTO public.owner_principals (id, user_id)
        VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id""")
    return str(cur.fetchone()[0])


def _active_contract(cur) -> None:
    cur.execute("""
        UPDATE public.mlc3_service_contracts
           SET state = 'active',
               active_from = clock_timestamp() - interval '1 second',
               retired_at = NULL,
               practice_bucket = 'practice-r2',
               coach_video_bucket = 'coach-r2'
         WHERE contract_version = 'mlc3-first-client-service-v1'""")
    if cur.rowcount != 1:
        pytest.skip("the lane has no first-client service contract row")


def _require_allowlist(cur, on: bool) -> None:
    cur.execute("""
        INSERT INTO public.ring_settings (key, value, changed_by)
        VALUES ('v3_requires_allowlist', %s::jsonb, 'rehearsal')
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        ("true" if on else "false",))


def _refused(cur, principal) -> str:
    cur.execute("SAVEPOINT gate")
    with pytest.raises(psycopg2.Error) as raised:
        cur.execute(GATE, (principal,))
    cur.execute("ROLLBACK TO SAVEPOINT gate")
    return str(raised.value)


def test_the_switch_is_off_unless_set(cur):
    cur.execute("SELECT public.v3_requires_allowlist_v1()")
    assert cur.fetchone()[0] is False
    _require_allowlist(cur, True)
    cur.execute("SELECT public.v3_requires_allowlist_v1()")
    assert cur.fetchone()[0] is True


def test_a_speaker_not_on_the_list_passes(cur):
    _active_contract(cur)
    principal = _principal(cur)
    cur.execute(GATE, (principal,))
    assert cur.fetchone() is not None


def test_the_switch_brings_the_list_back(cur):
    _active_contract(cur)
    principal = _principal(cur)
    _require_allowlist(cur, True)
    assert "MLC3_SERVICE_PRINCIPAL_NOT_ALLOWED" in _refused(cur, principal)


def test_an_open_account_wide_purge_still_refuses(cur):
    _active_contract(cur)
    principal = _principal(cur)
    cur.execute("""
        INSERT INTO public.data_purge_requests (
            acquisition_principal_id, trigger_kind, idempotency_key)
        VALUES (%s, 'account_deletion', %s)""",
        (principal, f"purge-{uuid.uuid4()}"))
    assert "MLC3_SERVICE_PRINCIPAL_NOT_ALLOWED" in _refused(cur, principal)


def test_only_the_definer_path_may_call_the_gate(cur):
    cur.execute("""
        SELECT has_function_privilege('service_role',
            'public.require_mlc3_service_principal_v1(uuid)', 'EXECUTE')""")
    assert cur.fetchone()[0] is False
