"""
STORY    As a coach, I want each pick sheet answered with one of its own
         clips, and the machine's picks behind a door only the server opens,
         so that my blind answers are clean.
OUTCOME
  O1  An answer among the sheet's clips is kept; an answer outside them is
      refused by the table itself.
  O2  NEVER-2: a coach's own login (anon, authenticated) cannot read the
      sheets, where the machine's picks are stored; only service_role can
      read and write them.
PROVES   O1 -> test_a_pick_sheet_is_answered_with_one_of_its_clips
         O2 -> test_only_the_service_role_opens_the_door
WHY      0453, V4 B1.8/B1.9, build plan D-ML-13 (BLIND COACH).
"""
from __future__ import annotations

import os
import pathlib
import uuid

import psycopg2
import psycopg2.errors
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="disposable confident-moment rehearsal only")
MIGRATION = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "v4_asks_coaches_two_blind_questions.sql"
TABLES = ("public.v4_moment_pick_sheets", "public.v4_surer_sheets")


@pytest.fixture
def cur():
    """A transaction on the disposable database, rolled back after the test,
    with the migration applied twice (it must be idempotent)."""
    if not psycopg2.extensions.parse_dsn(DSN).get("dbname", "").startswith(
            "willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    conn.autocommit = False
    body = "\n".join(line for line in MIGRATION.read_text().splitlines()
                     if line.strip() not in ("BEGIN;", "COMMIT;"))
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c:
            c.execute(body)
            c.execute(body)
            yield c
    finally:
        conn.rollback()
        conn.close()


def _pick(cur, **kw):
    row = {"rater_id": "c1", "rater_role": "coach", "take_session_id": str(uuid.uuid4()),
           "policy_version": "take-feedback-policy-v3-universal-dark-v3",
           "picker_version": "v4-picker-v1", "block_id": "b1", "clip_ids": ["a", "b", "c"],
           "v4_snippet_id": "a", "v3_snippet_id": "b", "slice": "unsure", "week": "2026-W41"}
    row.update(kw)
    cols = list(row)
    cur.execute(f"INSERT INTO public.v4_moment_pick_sheets ({', '.join(cols)}) VALUES "
                f"({', '.join(['%s'] * len(cols))}) RETURNING *", [row[c] for c in cols])
    return cur.fetchone()


def test_a_pick_sheet_is_answered_with_one_of_its_clips(cur):
    sheet = _pick(cur)
    # An answer outside the clips, on a sheet not yet answered (0457 refuses
    # any change to an answered one before the CHECK is read).
    cur.execute("SAVEPOINT outside")
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute("UPDATE public.v4_moment_pick_sheets SET answer_snippet_id = 'zzz', "
                    "answered_at = now() WHERE id = %s", (sheet["id"],))
    cur.execute("ROLLBACK TO SAVEPOINT outside")
    cur.execute("UPDATE public.v4_moment_pick_sheets SET answer_snippet_id = 'c', "
                "answered_at = now() WHERE id = %s RETURNING answer_snippet_id", (sheet["id"],))
    assert cur.fetchone()["answer_snippet_id"] == "c"


def _can(cur, role: str, sql: str) -> bool:
    cur.execute("SAVEPOINT door")
    try:
        cur.execute(f"SET LOCAL ROLE {role}")
        cur.execute(sql)
        return True
    except psycopg2.errors.InsufficientPrivilege:
        return False
    finally:
        cur.execute("ROLLBACK TO SAVEPOINT door")


def test_only_the_service_role_opens_the_door(cur):
    _pick(cur)
    for table in TABLES:
        read = f"SELECT * FROM {table}"
        for role in ("anon", "authenticated"):
            assert not _can(cur, role, read), (role, table)
        assert _can(cur, "service_role", read), table
    assert _can(cur, "service_role",
                "UPDATE public.v4_moment_pick_sheets SET answer_snippet_id = 'a', "
                "answered_at = now()")
