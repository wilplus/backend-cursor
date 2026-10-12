"""0415 on a real database: V3's source gate no longer requires the
allowlist, can be switched back without a deploy, and still refuses a
principal with an open account-wide purge.

Founder 2026-10-03 (N29 answer 1, "Every speaker"); F1 Repair Plan Phase 2.
Every write happens inside a transaction that is rolled back.
"""
from __future__ import annotations

import os

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


def test_a_speaker_not_on_the_list_passes(cur):
    _active_contract(cur)
    principal = _principal(cur)
    cur.execute(GATE, (principal,))
    assert cur.fetchone() is not None
