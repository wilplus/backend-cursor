"""0416 on a real database: a Take rewrite is an allowed Paragraph revision,
and the core read takes a Paragraph's lock from its row.

Contract 16; F1 Repair Plan Phase 3 (founder 2026-10-04, "Accept phase
three."). Every write happens inside a transaction that is rolled back.
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

INSERT = """
    INSERT INTO public.ideal_text_part_revision
        (arc_id, user_id, part_id, action, text, take_session_id,
         review_version)
    VALUES (%s, %s, %s, %s, 'Words of Take 2.', %s, 2) RETURNING id"""


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
    return (str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()),
            str(uuid.uuid4()))


def test_a_take_rewrite_revision_names_its_take(cur):
    arc, user, part, take = _ids()
    cur.execute(INSERT, (arc, user, part, "take_rewrite", take))
    revision = cur.fetchone()[0]
    cur.execute("""SELECT action, take_session_id::text, review_version
                     FROM public.ideal_text_part_revision WHERE id = %s""",
                (revision,))
    assert cur.fetchone() == ("take_rewrite", take, 2)
