"""
STORY    As a speaker, I want a retry of my Ideal Text to find my recording
         whatever the column is called, so that a retry never fails.
         (Critical path: record -> process -> Ideal Text.)
OUTCOME
  O1  New code writing only `recording_id` fills `recording_1_id`, and old
      code writing only `recording_1_id` fills `recording_id`.
  O2  Changing either name carries over to the other; clearing either name
      clears both.
  O3  The mirror adds no foreign key of its own, so it is never a new way for
      a Take insert to fail.
  O4  Browser roles cannot call the trigger function.
PROVES   O1 -> test_either_name_fills_the_other
         O2 -> test_an_update_or_a_clear_carries_over
         O3 -> test_the_mirror_adds_no_foreign_key
         O4 -> test_browser_roles_cannot_call_the_trigger
WHY      Founder 2026-09-26: the retry read `recording_id` from a row that only
         had `recording_1_id`, so every retry failed under enforce (0383).

Runs on the released rehearsal lane against the real trigger.
"""
from __future__ import annotations

import uuid

import pytest

from tests import test_optional_consent_postgres as base

DSN = base.DSN
db = base.db

pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

TRIGGER_FN = "public.v2_sessions_mirror_recording_id_v1()"


def _recording(db) -> str:
    rid = str(uuid.uuid4())
    with db.cursor() as cur:
        cur.execute("INSERT INTO public.recordings (id) VALUES (%s)", (rid,))
    return rid


def _both(db, sid):
    with db.cursor() as cur:
        cur.execute(
            "SELECT recording_id::text, recording_1_id::text "
            "FROM public.v2_sessions WHERE id = %s", (sid,))
        return cur.fetchone()


def _take(db, column, rid) -> str:
    sid = str(uuid.uuid4())
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO public.v2_sessions "
            f"(id, arc_id, user_id, take_index, {column}) "
            "VALUES (%s, %s, gen_random_uuid(), 1, %s)",
            (sid, f"arc-{sid}", rid))
    return sid


def _set(db, sid, column, value):
    with db.cursor() as cur:
        cur.execute(f"UPDATE public.v2_sessions SET {column} = %s WHERE id = %s",
                    (value, sid))


def test_either_name_fills_the_other(db):
    new_rid = _recording(db)
    assert _both(db, _take(db, "recording_id", new_rid)) == (new_rid, new_rid)
    old_rid = _recording(db)
    assert _both(db, _take(db, "recording_1_id", old_rid)) == (old_rid, old_rid)


def test_an_update_or_a_clear_carries_over(db):
    sid = _take(db, "recording_1_id", _recording(db))
    second, third = _recording(db), _recording(db)

    _set(db, sid, "recording_1_id", second)
    assert _both(db, sid) == (second, second)
    _set(db, sid, "recording_id", third)
    assert _both(db, sid) == (third, third)
    _set(db, sid, "recording_id", None)
    assert _both(db, sid) == (None, None)

    _set(db, sid, "recording_1_id", second)
    _set(db, sid, "recording_1_id", None)
    assert _both(db, sid) == (None, None)


def test_the_mirror_adds_no_foreign_key(db):
    with db.cursor() as cur:
        cur.execute("""
            SELECT count(*) FROM pg_constraint c
              JOIN pg_attribute a ON a.attrelid = c.conrelid
                                 AND a.attnum = ANY (c.conkey)
             WHERE c.conrelid = 'public.v2_sessions'::regclass
               AND c.contype = 'f' AND a.attname = 'recording_id'""")
        assert cur.fetchone()[0] == 0


def test_browser_roles_cannot_call_the_trigger(db):
    with db.cursor() as cur:
        for role in ("anon", "authenticated"):
            cur.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                        (role, TRIGGER_FN))
            assert cur.fetchone()[0] is False, role
