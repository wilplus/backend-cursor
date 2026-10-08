"""0451: each pick learns whether its paragraph rose (V4 B1.5, build plan
D-ML-10; founder P5, V10b A, V11 B, V12 A), on the disposable rehearsal
database, over two real Takes of one project with their frames, draws and
willfidence reads.

Pins:
  * the map is stored once and must name every frame block, each once;
  * outcomes wait until both Takes are read ('not_ready'), then are written
    once for Take N, one row per moment;
  * a moment bound to a paragraph is measured by that paragraph's moments in
    both Takes (V12 A); without one, by its slide (V10b A backup);
  * 'rose' only above the 0.05 margin (V11 B); V3's picks ride along;
  * a first Take has no previous Take; grants as every V4 table.
"""
from __future__ import annotations

import pathlib
import uuid
from decimal import Decimal

import psycopg2
import psycopg2.errors
import psycopg2.extras
import pytest

from tests import test_a_take_draws_its_random_moments_postgres as draw_suite
from tests import test_the_machine_reads_willfidence_postgres as read_suite
from tests import test_the_shadow_writer_accepts_the_frame_the_code_builds_postgres as base

DSN = base.DSN
pytestmark = pytest.mark.skipif(not DSN, reason="disposable confident-moment rehearsal only")

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "each_pick_learns_if_the_paragraph_rose.sql"
P1 = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def cur():
    yield from base.cur.__wrapped__()


def _apply(cur):
    read_suite._apply(cur)
    cur.execute(draw_suite._body(MIGRATION))


def _take(cur):
    seed = draw_suite._stored_take(cur)
    draw_suite._draw(cur, seed["take"])
    return seed


def _two_takes(cur):
    first, second = _take(cur), _take(cur)
    cur.execute("UPDATE public.v2_sessions SET arc_id = %s, owner_principal_id = %s, "
                "user_id = %s, take_index = 3 WHERE id = %s",
                (first["arc_id"], first["principal"], first["user_id"], second["take"]))
    return first, second


def _map(cur, seed, paragraph=None):
    m = [{"block_id": b["block_id"], "paragraph_id": paragraph}
         for b in seed["frame"]["blocks"]]
    cur.execute("SELECT public.record_v4_moment_paragraphs_v1(%s::uuid, %s) AS r",
                (seed["take"], psycopg2.extras.Json(m)))
    return cur.fetchone()["r"]


def _read(cur, seed, filler):
    return read_suite._record(cur, seed["take"], read_suite._reads(seed["frame"], filler=filler))


def _compute(cur, take):
    cur.execute("SELECT public.compute_v4_pick_outcomes_v1(%s::uuid) AS r", (take,))
    return cur.fetchone()["r"]


def _outcomes(cur, take):
    cur.execute("SELECT * FROM public.v4_pick_outcomes WHERE take_session_id = %s "
                "ORDER BY block_id", (take,))
    return cur.fetchall()


def test_the_map_must_be_the_frames_blocks(cur):
    _apply(cur)
    seed = _take(cur)
    bad = [{"block_id": b["block_id"], "paragraph_id": None} for b in seed["frame"]["blocks"]][1:]
    with pytest.raises(psycopg2.errors.RaiseException, match="DO_NOT_MATCH"):
        cur.execute("SELECT public.record_v4_moment_paragraphs_v1(%s::uuid, %s)",
                    (seed["take"], psycopg2.extras.Json(bad)))
    cur.connection.rollback()
    _apply(cur)
    seed = _take(cur)
    with pytest.raises(psycopg2.errors.RaiseException, match="INVALID"):
        cur.execute("SELECT public.record_v4_moment_paragraphs_v1(%s::uuid, %s)",
                    (seed["take"], psycopg2.extras.Json(
                        [{"block_id": b["block_id"], "paragraph_id": "not-a-uuid"}
                         for b in seed["frame"]["blocks"]])))
    cur.connection.rollback()
    _apply(cur)
    seed = _take(cur)
    assert _map(cur, seed, P1) == {"outcome": "mapped"}
    assert _map(cur, seed, None) == {"outcome": "stored"}


def test_outcomes_wait_for_both_reads_then_land_once(cur):
    _apply(cur)
    first, second = _two_takes(cur)
    _map(cur, first, P1)
    _map(cur, second, P1)
    _read(cur, first, filler=0.0)
    assert _compute(cur, second["take"]) == {"outcome": "not_ready"}
    _read(cur, second, filler=1.0)
    out = _compute(cur, second["take"])
    assert out["outcome"] == "computed" and out["take_session_id"] == first["take"]
    rows = _outcomes(cur, first["take"])
    assert len(rows) == len(first["frame"]["blocks"])
    assert _compute(cur, second["take"]) == {"outcome": "stored"}
    for row in rows:
        assert row["match_level"] == "paragraph" and str(row["paragraph_id"]) == P1
        assert str(row["next_take_session_id"]) == second["take"]
        assert row["rise"] == row["willfidence_after"] - row["willfidence_before"]
        assert row["rise"] > Decimal("0.05") and row["outcome"] == "rose"


def test_without_a_paragraph_the_slide_is_the_backup(cur):
    _apply(cur)
    first, second = _two_takes(cur)
    _map(cur, first, None)
    _map(cur, second, None)
    _read(cur, first, filler=0.9)
    _read(cur, second, filler=0.9)
    _compute(cur, second["take"])
    rows = _outcomes(cur, first["take"])
    assert {r["match_level"] for r in rows} == {"slide"}
    assert {r["outcome"] for r in rows} == {"did_not_rise"}


def test_v3s_picks_ride_along(cur):
    _apply(cur)
    first, second = _two_takes(cur)
    _map(cur, first, None)
    _map(cur, second, None)
    _read(cur, first, filler=0.5)
    _read(cur, second, filler=0.5)
    _compute(cur, second["take"])
    frame = first["frame"]
    rewrite = {a["block_id"] for a in frame["verbal_lanes"]["rewrite_clarity"]["anchors"]}
    exercise = {b["block_id"] for b in frame["blocks"] if b.get("carries_exercise")}
    for row in _outcomes(cur, first["take"]):
        assert ("rewrite" in row["v3_picks"]) == (row["block_id"] in rewrite)
        assert ("exercise" in row["v3_picks"]) == (row["block_id"] in exercise)


def test_a_first_take_has_nothing_to_compare(cur):
    _apply(cur)
    seed = _take(cur)
    cur.execute("UPDATE public.v2_sessions SET take_index = 1 WHERE id = %s", (seed["take"],))
    assert _compute(cur, seed["take"]) == {"outcome": "no_previous_take"}
    assert _compute(cur, str(uuid.uuid4())) == {"outcome": "no_previous_take"}


def test_the_door(cur):
    _apply(cur)
    cur.execute(draw_suite._body(MIGRATION))
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'service_role'")
    if cur.fetchone() is not None:
        for table in ("public.v4_moment_paragraphs", "public.v4_pick_outcomes"):
            for privilege, held in (("SELECT", True), ("DELETE", True),
                                    ("INSERT", False), ("UPDATE", False)):
                cur.execute("SELECT has_table_privilege('service_role', %s, %s) AS p",
                            (table, privilege))
                assert cur.fetchone()["p"] is held, (table, privilege)
    for role in ("anon", "authenticated"):
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        if cur.fetchone() is None:
            continue
        cur.execute("SELECT has_function_privilege(%s, 'public.compute_v4_pick_outcomes_v1(uuid)', "
                    "'EXECUTE') AS p", (role,))
        assert cur.fetchone()["p"] is False
