"""v2_sessions.recording_id mirrors recording_1_id (0383, safe rename step 1).

Founder 2026-09-26: the Ideal Text retry read `recording_id` from the Take
row, which only had `recording_1_id`, so every retry failed under enforce.
0383 adds the new name without removing the old one. Pinned here, against
the real trigger:

  * old code writing only `recording_1_id` still fills `recording_id`;
  * new code writing only `recording_id` still fills `recording_1_id`;
  * an update to either column carries over to the other;
  * clearing either name clears both;
  * the mirror adds no constraint of its own (no foreign key);
  * browser roles cannot call the trigger function.
"""
from __future__ import annotations

import uuid

import pytest

from tests import test_optional_consent_postgres as base

DSN = base.DSN
_one = base._one
db = base.db

pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)


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


def test_old_code_writing_recording_1_id_fills_recording_id(db):
    rid = _recording(db)
    sid = _take(db, "recording_1_id", rid)
    assert _both(db, sid) == (rid, rid)


def test_new_code_writing_recording_id_fills_recording_1_id(db):
    rid = _recording(db)
    sid = _take(db, "recording_id", rid)
    assert _both(db, sid) == (rid, rid)


def test_an_update_to_either_name_carries_over(db):
    first, second, third = _recording(db), _recording(db), _recording(db)
    sid = _take(db, "recording_1_id", first)
    with db.cursor() as cur:
        cur.execute("UPDATE public.v2_sessions SET recording_1_id = %s "
                    "WHERE id = %s", (second, sid))
    assert _both(db, sid) == (second, second)
    with db.cursor() as cur:
        cur.execute("UPDATE public.v2_sessions SET recording_id = %s "
                    "WHERE id = %s", (third, sid))
    assert _both(db, sid) == (third, third)


def test_clearing_either_name_clears_both(db):
    rid = _recording(db)
    sid = _take(db, "recording_id", rid)
    with db.cursor() as cur:
        cur.execute("UPDATE public.v2_sessions SET recording_1_id = NULL "
                    "WHERE id = %s", (sid,))
    assert _both(db, sid) == (None, None)


def test_the_mirror_adds_no_constraint_of_its_own(db):
    """No foreign key on recording_id: the mirror must accept whatever
    recording_1_id accepts, or copying across becomes a new way for a Take
    write to fail (the narrow lane's fixtures write unconstrained ids)."""
    constraints = _one(db, """
        SELECT count(*)
          FROM pg_constraint c
          JOIN pg_attribute a
            ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
         WHERE c.conrelid = 'public.v2_sessions'::regclass
           AND a.attname = 'recording_id'""")
    assert constraints == 0


def test_browser_roles_cannot_call_the_trigger_function(db):
    for role in ("anon", "authenticated"):
        has = _one(db, """
            SELECT has_function_privilege(
                %s, 'public.v2_sessions_mirror_recording_id_v1()', 'EXECUTE')""",
            (role,))
        assert has is False
