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
from tests import test_the_shadow_writer_accepts_the_frame_the_code_builds_postgres as base

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


def _surer(cur, **kw):
    row = {"rater_id": "c1", "rater_role": "coach", "take_session_id": str(uuid.uuid4()),
           "block_id": "b1", "said_text": "I think we grew.", "new_text": "We grew.",
           "varied_quality": "hedging", "version_rule": "surer-pair-v1-lexical",
           "slice": "above", "level": 0.7, "bar": 0.6, "bar_version": "reached-bar-v0-placeholder",
           "week": "2026-W41"}
    row.update(kw)
    cols = list(row)
    cur.execute(f"INSERT INTO public.v4_surer_sheets ({', '.join(cols)}) VALUES "
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


@pytest.mark.parametrize("kw", [
    {"clip_ids": []}, {"clip_ids": ["a", "b", "c", "d"]}, {"v4_snippet_id": "zzz"},
    {"slice": "repick"}, {"slice": "secret"}, {"rater_role": "speaker"},
    {"none_needs_it": False, "answered_at": "2026-10-08"},
    {"answer_snippet_id": "a", "none_needs_it": True, "answered_at": "2026-10-08"},
    {"picker_version": "v5"},
])
def test_a_wrong_pick_sheet_is_refused(cur, kw):
    _apply(cur)
    with pytest.raises(psycopg2.errors.CheckViolation):
        _pick(cur, **kw)


def test_a_rater_is_asked_a_block_once_but_may_repick_it(cur):
    _apply(cur)
    first = _pick(cur)
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _pick(cur, take_session_id=first["take_session_id"])
    cur.connection.rollback()
    _apply(cur)
    first = _pick(cur)
    again = _pick(cur, take_session_id=first["take_session_id"], slice="repick",
                  repick_of=first["id"])
    assert again["repick_of"] == first["id"]


@pytest.mark.parametrize("answer,chosen,rejected", [
    ("yes", "We grew.", "I think we grew."), ("no", "I think we grew.", "We grew."),
    ("cant_tell", None, None),
])
def test_a_surer_answer_carries_its_pair(cur, answer, chosen, rejected):
    _apply(cur)
    sheet = _surer(cur)
    cur.execute("UPDATE public.v4_surer_sheets SET answer = %s, chosen_text = %s, "
                "rejected_text = %s, answered_at = now() WHERE id = %s",
                (answer, chosen, rejected, sheet["id"]))
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute("UPDATE public.v4_surer_sheets SET chosen_text = 'other' WHERE id = %s",
                    (sheet["id"],))


@pytest.mark.parametrize("kw", [
    {"slice": "above", "level": 0.5}, {"slice": "below", "level": 0.7},
    {"slice": "above", "level": None}, {"new_text": "I think we grew."},
    {"varied_quality": "cohesion"}, {"version_rule": "llm"},
])
def test_a_wrong_pair_is_refused(cur, kw):
    _apply(cur)
    with pytest.raises(psycopg2.errors.CheckViolation):
        _surer(cur, **kw)


def test_the_door(cur):
    _apply(cur)
    for role in ("anon", "authenticated"):
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        if cur.fetchone() is None:
            continue
        for table in ("public.v4_moment_pick_sheets", "public.v4_surer_sheets"):
            cur.execute("SELECT has_table_privilege(%s, %s, 'SELECT') AS p", (role, table))
            assert cur.fetchone()["p"] is False
