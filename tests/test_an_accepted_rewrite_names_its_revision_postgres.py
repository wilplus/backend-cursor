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
import uuid

import psycopg2
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

WRITER = ("public.compare_and_set_user_ideal_edit_v1"
          "(uuid,text,integer,bigint,text,text,jsonb,text)")

INSERT = """
    INSERT INTO public.ideal_text_part_revision
        (arc_id, user_id, part_id, action, text, provenance)
    VALUES (%s, %s, %s, %s, 'Accepted words.', %s) RETURNING id"""


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


def _ids():
    return str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())


def test_an_earlier_revision_reads_unnamed(cur):
    cur.execute("""SELECT is_nullable, data_type FROM information_schema.columns
                    WHERE table_schema='public'
                      AND table_name='ideal_text_part_revision'
                      AND column_name='provenance'""")
    assert cur.fetchone() == ("YES", "text")
    arc, user, part = _ids()
    cur.execute("""INSERT INTO public.ideal_text_part_revision
                       (arc_id, user_id, part_id, action, text)
                   VALUES (%s, %s, %s, 'user_edit', 'Words.')
                   RETURNING provenance""", (arc, user, part))
    assert cur.fetchone() == (None,)


def test_the_name_is_allowed_only_on_a_text_revision(cur):
    # The v2 shape constraint governs the owner_part_* actions; this checks
    # the name alone, so an action outside that family stands in for "not a
    # text change" and the v2 columns are not needed.
    for action in ("lock", "unlock", "root_set", "take_rewrite", "user_edit"):
        arc, user, part = _ids()
        cur.execute("SAVEPOINT s")
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute(INSERT, (arc, user, part, action, "accepted_rewrite"))
        cur.execute("ROLLBACK TO SAVEPOINT s")


def test_no_other_name_is_allowed(cur):
    arc, user, part = _ids()
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute(INSERT, (arc, user, part, "user_edit", "coach_edit"))


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
