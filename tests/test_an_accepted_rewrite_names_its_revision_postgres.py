"""0421 on the released chain: a Paragraph revision may carry one name,
'accepted_rewrite', and only on a revision that changed the text; the
owner-edit writer is installed with the patch that writes it.

Founder 2026-10-05 (decisions log N48.1, "Closing the Gap" Wave 1 step 5;
coach-panel lock C11). The behaviour of the writer -- which revision gets the
name -- is rehearsed against a real owner and project in
tests/test_confident_moment_coaching_bundle_postgres.py
(test_0421_an_accepted_rewrite_names_only_its_own_revision). Every write here
happens inside a transaction that is rolled back.
"""
from __future__ import annotations

import os

import psycopg2
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

WRITER = ("public.compare_and_set_user_ideal_edit_v1"
          "(uuid,text,integer,bigint,text,text,jsonb,text)")


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


def test_the_installed_writer_names_only_the_paragraph_accept_names(cur):
    cur.execute("SELECT pg_get_functiondef(%s::regprocedure)", (WRITER,))
    body = cur.fetchone()[0]
    assert body.count("/* 0421 accepted rewrite provenance */") == 1
    assert "owner_edit_operation_id,revision_contract_version,provenance)" in body
    assert ("NULLIF(current_setting('willab.accepted_rewrite_part',true),'')::uuid "
            "THEN 'accepted_rewrite' END);") in body
    # 0418's guard is still there, once.
    assert body.count("/* 0418 accepted rewrite */") == 1
    cur.execute("SELECT has_function_privilege('anon', %s, 'EXECUTE'),"
                " has_function_privilege('service_role', %s, 'EXECUTE')",
                (WRITER, WRITER))
    assert cur.fetchone() == (False, True)
