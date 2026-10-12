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
from tests import (
    test_the_shadow_writer_accepts_the_frame_the_code_builds_postgres as base,
)

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


def _refused(cur, mutate, match):
    _apply(cur)
    seed, rows = _read_take(cur)
    rows = copy.deepcopy(rows)
    mutate(rows, seed["frame"])
    with pytest.raises((psycopg2.errors.RaiseException, psycopg2.errors.CheckViolation), match=match):
        _record(cur, seed["take"], rows)


def test_a_silent_fallback_is_refused(cur):
    def mutate(rows, frame):
        row = rows[0]
        row.update(fallback=not row["fallback"])
    _refused(cur, mutate, "v4_picks_fallback")
