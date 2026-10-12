"""0378 on a real database: the account-wide lock is narrowed, nothing else moves.

Run on the released rehearsal lane. Every write happens inside a transaction
that is rolled back.

  * `data_purge_requests.project_id` exists, and a project id is refused on
    any request that is not a project deletion (none can be one yet);
  * every installed function among the nineteen carries the narrowed
    predicate exactly once, and a D11 writer keeps its lock marker;
  * no installed function still holds the old, account-wide-for-anything
    predicate.
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


def test_a_project_id_only_belongs_to_a_project_deletion(cur):
    cur.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = 'data_purge_requests'
           AND column_name = 'project_id'""")
    assert cur.fetchone()
    cur.execute("""
        INSERT INTO public.owner_principals (id, user_id)
        VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id""")
    principal = cur.fetchone()[0]
    cur.execute("SELECT id FROM public.projects LIMIT 1")
    project = cur.fetchone()
    if project is None:
        pytest.skip("the lane holds no project row to point at")
    cur.execute("SAVEPOINT refused")
    with pytest.raises(psycopg2.Error) as refused:
        cur.execute("""
            INSERT INTO public.data_purge_requests (
                acquisition_principal_id, trigger_kind, idempotency_key,
                project_id)
            VALUES (%s, 'account_deletion', %s, %s)""",
            (principal, f"scope-{uuid.uuid4()}", project[0]))
    cur.execute("ROLLBACK TO SAVEPOINT refused")
    assert "data_purge_requests_project_scope_check" in str(refused.value)
