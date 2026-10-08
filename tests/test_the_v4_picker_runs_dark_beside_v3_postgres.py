"""0452: the V4 picker runs dark beside V3 (V4 B1.6, build plan D-ML-12), on
the disposable rehearsal database: the picker's rows for a real Take (frame,
draw, willfidence read) are stored, and every rule the database proves
refuses a row that breaks it.
"""
from __future__ import annotations

import copy
import pathlib

import psycopg2
import psycopg2.errors
import psycopg2.extras
import pytest

from services import v4_picker as vp
from tests import test_a_take_draws_its_random_moments_postgres as draw_suite
from tests import test_each_pick_learns_if_the_paragraph_rose_postgres as outcome_suite
from tests import test_the_machine_reads_willfidence_postgres as read_suite
from tests import test_the_shadow_writer_accepts_the_frame_the_code_builds_postgres as base

DSN = base.DSN
pytestmark = pytest.mark.skipif(not DSN, reason="disposable confident-moment rehearsal only")

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "the_v4_picker_runs_dark_beside_v3.sql"


@pytest.fixture
def cur():
    yield from base.cur.__wrapped__()


def _apply(cur):
    outcome_suite._apply(cur)
    cur.execute(draw_suite._body(MIGRATION))


def _read_take(cur):
    seed = outcome_suite._take(cur)
    read_suite._record(cur, seed["take"], read_suite._reads(seed["frame"]))
    cur.execute("SELECT id::text AS id, metrics, transcript FROM public.snippets "
                "WHERE session_id = %s", (seed["take"],))
    snippets = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT block_id, s, w, willfident, role FROM public.v4_willfidence_reads "
                "WHERE take_session_id = %s", (seed["take"],))
    reads = [{k: (float(v) if hasattr(v, "as_tuple") else v) for k, v in r.items()}
             for r in cur.fetchall()]
    return seed, vp.pick_take(seed["frame"], snippets, reads)


def _record(cur, take, rows):
    cur.execute("SELECT public.record_v4_picks_v1(%s::uuid, %s) AS r",
                (take, psycopg2.extras.Json(rows)))
    return cur.fetchone()["r"]


def test_the_pickers_rows_are_stored_once(cur):
    _apply(cur)
    seed, rows = _read_take(cur)
    assert _record(cur, seed["take"], rows) == {"outcome": "picked", "blocks": len(rows)}
    assert _record(cur, seed["take"], rows) == {"outcome": "stored"}
    cur.execute("SELECT blocks, fallback_blocks FROM public.v4_pick_takes WHERE take_session_id = %s",
                (seed["take"],))
    line = cur.fetchone()
    assert line["blocks"] == len(rows)
    assert line["fallback_blocks"] == sum(1 for r in rows if r["fallback"])


def test_no_read_no_picks(cur):
    _apply(cur)
    seed = outcome_suite._take(cur)
    assert _record(cur, seed["take"], []) == {"outcome": "no_read"}


def _refused(cur, mutate, match):
    _apply(cur)
    seed, rows = _read_take(cur)
    rows = copy.deepcopy(rows)
    mutate(rows, seed["frame"])
    with pytest.raises((psycopg2.errors.RaiseException, psycopg2.errors.CheckViolation), match=match):
        _record(cur, seed["take"], rows)


def _band(frame, confident):
    return next(b["block_id"] for b in frame["blocks"]
                if (b.get("delivery_band") in ("delivery_signal_high", "delivery_signal_mid_high"))
                == confident and b.get("delivery_band"))


def test_praise_on_a_weak_block_is_refused(cur):
    def mutate(rows, frame):
        weak = _band(frame, False)
        next(r for r in rows if r["block_id"] == weak).update(v4_kind="praise")
    _refused(cur, mutate, "NOT_ALLOWED")


def test_a_role_the_read_did_not_give_is_refused(cur):
    def mutate(rows, frame):
        rows[0].update(role="aside", importance=0.2)
    _refused(cur, mutate, "NOT_ALLOWED")


def test_a_missing_block_is_refused(cur):
    _refused(cur, lambda rows, frame: rows.pop(), "DO_NOT_MATCH")


def test_a_wrong_rank_is_refused(cur):
    def mutate(rows, frame):
        row = next(r for r in rows if r["rank_score"] is not None)
        row["rank_score"] = row["rank_score"] + 0.01
    _refused(cur, mutate, "v4_picks_rank")


def test_a_silent_fallback_is_refused(cur):
    def mutate(rows, frame):
        row = rows[0]
        row.update(fallback=not row["fallback"])
    _refused(cur, mutate, "v4_picks_fallback")


def test_the_door(cur):
    _apply(cur)
    cur.execute(draw_suite._body(MIGRATION))
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'service_role'")
    if cur.fetchone() is not None:
        for privilege, held in (("SELECT", True), ("DELETE", True), ("INSERT", False)):
            cur.execute("SELECT has_table_privilege('service_role', 'public.v4_picks', %s) AS p",
                        (privilege,))
            assert cur.fetchone()["p"] is held
