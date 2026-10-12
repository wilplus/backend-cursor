"""0453: V4 asks coaches two blind questions (V4 B1.8/B1.9, build plan
D-ML-13), on the disposable rehearsal database: the tables' own checks hold
each sheet to its versions, slices and answer shapes, and the door is the
service role's alone."""
from __future__ import annotations

import pathlib
import uuid

import psycopg2
import psycopg2.errors
import pytest

from tests import test_a_take_draws_its_random_moments_postgres as draw_suite
from tests import (
    test_the_shadow_writer_accepts_the_frame_the_code_builds_postgres as base,
)

DSN = base.DSN
pytestmark = pytest.mark.skipif(not DSN, reason="disposable confident-moment rehearsal only")
MIGRATION = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "v4_asks_coaches_two_blind_questions.sql"


@pytest.fixture
def cur():
    yield from base.cur.__wrapped__()


def _apply(cur):
    cur.execute(draw_suite._body(MIGRATION))
    cur.execute(draw_suite._body(MIGRATION))


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


def test_a_pick_sheet_is_answered_once_with_one_of_its_clips(cur):
    _apply(cur)
    sheet = _pick(cur)
    cur.execute("UPDATE public.v4_moment_pick_sheets SET answer_snippet_id = 'a', "
                "answered_at = now() WHERE id = %s", (sheet["id"],))
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute("UPDATE public.v4_moment_pick_sheets SET answer_snippet_id = 'zzz' "
                    "WHERE id = %s", (sheet["id"],))
