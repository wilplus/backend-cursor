"""
STORY    As a speaker not on any allowlist, I want V3 feedback to reach me, so
         that every speaker gets the same feedback. (Critical path: feedback.)
OUTCOME
  O1  The V3 source gate lets in a speaker who is on no allowlist.
  O2  The founder can switch the allowlist back on without a deploy, and then
      the same speaker is refused.
  O3  A speaker with an open account-wide deletion is refused (privacy).
PROVES   O1 -> test_a_speaker_not_on_the_list_passes
         O2 -> test_the_allowlist_can_be_switched_back_on
         O3 -> test_a_speaker_being_deleted_is_refused
WHY      Migration 0415 (migrations/v3_reaches_every_speaker.sql; founder
         2026-10-03, N29 answer 1, "Every speaker").

Runs on the rehearsal tier (lane "confident-moment released"). Every write
happens inside a transaction that is rolled back.
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

GATE = "SELECT (public.require_mlc3_service_principal_v1(%s)).contract_version"
CONTRACT = "mlc3-first-client-service-v1"


@pytest.fixture
def cur():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cursor:
            _active_contract(cursor)
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
         WHERE contract_version = %s""", (CONTRACT,))
    if cur.rowcount != 1:
        pytest.skip("the lane has no first-client service contract row")


def _passes(cur, principal) -> bool:
    """True when the gate lets the principal in; False on the refusal."""
    cur.execute("SAVEPOINT gate")
    try:
        cur.execute(GATE, (principal,))
        assert cur.fetchone()[0] == CONTRACT
        cur.execute("RELEASE SAVEPOINT gate")
        return True
    except psycopg2.Error as refused:
        cur.execute("ROLLBACK TO SAVEPOINT gate")
        assert "MLC3_SERVICE_PRINCIPAL_NOT_ALLOWED" in str(refused)
        return False


def test_a_speaker_not_on_the_list_passes(cur):
    assert _passes(cur, _principal(cur)) is True


def test_the_allowlist_can_be_switched_back_on(cur):
    principal = _principal(cur)
    assert _passes(cur, principal) is True
    cur.execute("""
        INSERT INTO public.ring_settings (key, value, changed_by)
        VALUES ('v3_requires_allowlist', 'true'::jsonb, 'founder')
        ON CONFLICT (key) DO UPDATE
           SET value = EXCLUDED.value, changed_by = EXCLUDED.changed_by""")
    assert _passes(cur, principal) is False


def test_a_speaker_being_deleted_is_refused(cur):
    principal = _principal(cur)
    assert _passes(cur, principal) is True
    cur.execute("""
        INSERT INTO public.data_purge_requests (
            acquisition_principal_id, trigger_kind, idempotency_key)
        VALUES (%s, 'account_deletion', %s)""", (principal, str(uuid.uuid4())))
    assert _passes(cur, principal) is False
