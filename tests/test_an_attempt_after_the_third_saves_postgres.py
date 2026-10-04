"""0417 on a real database: a fourth (and tenth) practice attempt saves;
an attempt numbered 0 is still refused.

F1 Repair Plan Phase 4; founder lock 2026-09-30, D2 ("attempt 10 works like
attempt 1"). Every write happens inside a transaction that is rolled back.
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


def _practice(cur) -> str:
    practice = str(uuid.uuid4())
    cur.execute("""
        INSERT INTO public.confident_voice_practice
            (id, owner_user_id, take_session_id)
        VALUES (%s, gen_random_uuid(), gen_random_uuid())""", (practice,))
    return practice


def _attempt(cur, practice: str, index: int) -> None:
    cur.execute("""
        INSERT INTO public.confident_voice_practice_attempt
            (id, practice_id, attempt_index)
        VALUES (gen_random_uuid(), %s, %s)""", (practice, index))


def test_attempts_four_and_ten_save(cur):
    practice = _practice(cur)
    for index in (1, 2, 3, 4, 10):
        _attempt(cur, practice, index)
    cur.execute("""SELECT array_agg(attempt_index ORDER BY attempt_index)
                     FROM public.confident_voice_practice_attempt
                    WHERE practice_id = %s""", (practice,))
    assert cur.fetchone()[0] == [1, 2, 3, 4, 10]


def test_attempt_zero_is_still_refused(cur):
    practice = _practice(cur)
    with pytest.raises(psycopg2.errors.CheckViolation):
        _attempt(cur, practice, 0)


def test_no_upper_bound_remains(cur):
    cur.execute("""
        SELECT count(*) FROM pg_constraint
         WHERE conrelid = 'public.confident_voice_practice_attempt'::regclass
           AND contype = 'c'
           AND pg_get_constraintdef(oid) ~ 'attempt_index\\s*<=\\s*3'""")
    assert cur.fetchone()[0] == 0
