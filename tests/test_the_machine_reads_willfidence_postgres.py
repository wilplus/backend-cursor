"""0449: the machine reads willfidence (V4 B1.3, build plan D-ML-8), on the
disposable rehearsal database, over the frame the code builds and the draw
0447 makes.

Pins:
  * the database computes S, W, the four boxes and the Take's line exactly
    as services/willfidence.py does, from the clips and the word signals;
  * every frame block gets one row; random rows are 0447's draw;
  * spread stays empty; an unrateable moment keeps its row and reason;
  * reads that miss a block, add one, name one twice, or carry a value out
    of range or a role off the signed list are refused;
  * a Take with no frame, or no draw, writes nothing; a second call
    writes nothing new;
  * the speaker's line is the same rule over all their random moments;
  * browser roles hold nothing; service_role reads, deletes (the purge) and calls,
    never inserts or updates; the
    file applied twice changes nothing.
"""
from __future__ import annotations

import pathlib
import uuid
from decimal import Decimal

import psycopg2
import psycopg2.errors
import psycopg2.extras
import pytest

from services import willfidence as wf
from tests import test_a_take_draws_its_random_moments_postgres as draw_suite
from tests import test_the_shadow_writer_accepts_the_frame_the_code_builds_postgres as base

DSN = base.DSN
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "the_machine_reads_willfidence.sql"


@pytest.fixture
def cur():
    yield from base.cur.__wrapped__()


def _apply(cur):
    draw_suite._apply(cur)
    cur.execute(draw_suite._body(MIGRATION))


def _drawn_take(cur):
    seed = draw_suite._stored_take(cur)
    draw_suite._draw(cur, seed["take"])
    return seed


def _reads(frame, **override):
    out = []
    for i, block in enumerate(frame["blocks"]):
        row = {"block_id": block["block_id"], "filler": 0.9, "hedging": 0.6,
               "slide_fit": 0.5, "holding_together": 1.0,
               "role": "main_point" if i else "opening"}
        row.update(override)
        out.append(row)
    return out


def _record(cur, take, reads):
    cur.execute("SELECT public.record_v4_willfidence_reads_v1(%s::uuid, %s) AS r",
                (take, psycopg2.extras.Json(reads)))
    return cur.fetchone()["r"]


def _rows(cur, take):
    cur.execute("SELECT * FROM public.v4_willfidence_reads "
                "WHERE take_session_id = %s ORDER BY block_id", (take,))
    return cur.fetchall()


def _snippets(cur, take):
    cur.execute("SELECT id::text AS id, metrics FROM public.snippets "
                "WHERE session_id = %s", (take,))
    return {r["id"]: r for r in cur.fetchall()}


def test_the_database_reads_what_the_code_reads(cur):
    _apply(cur)
    seed = _drawn_take(cur)
    frame = seed["frame"]
    reads = _reads(frame)
    outcome = _record(cur, seed["take"], reads)
    assert outcome["outcome"] == "read"
    rows = {r["block_id"]: r for r in _rows(cur, seed["take"])}
    assert set(rows) == {b["block_id"] for b in frame["blocks"]}
    clips = _snippets(cur, seed["take"])
    cur.execute("SELECT block_id FROM public.v4_random_moments "
                "WHERE take_session_id = %s", (seed["take"],))
    drawn = {r["block_id"] for r in cur.fetchall()}
    for block in frame["blocks"]:
        row = rows[block["block_id"]]
        s = wf.sound([clips[c]["metrics"] for c in block["snippet_ids"]])
        w = wf.partial_w(0.9, 0.6, 0.5, 1.0)
        assert float(row["s"]) == pytest.approx(s)
        assert float(row["w"]) == pytest.approx(w)
        for box, value in wf.boxes(s, w).items():
            assert float(row[box]) == pytest.approx(value)
        assert row["judge_spread"] is None
        assert row["is_random"] is (block["block_id"] in drawn)
        assert row["read_version"] == wf.READ_VERSION
        assert row["unrateable_reason"] is None
    cur.execute("SELECT * FROM public.v4_willfidence_takes "
                "WHERE take_session_id = %s", (seed["take"],))
    take = cur.fetchone()
    expected = wf.summary([
        {"is_random": r["is_random"], "s": float(r["s"]), "w": float(r["w"])}
        for r in rows.values()])
    assert float(take["willfidence"]) == pytest.approx(expected["willfidence"])
    assert take["status"] == expected["status"] == "not_enough_data"
    assert take["random_moments"] == expected["random_moments"] == len(drawn)


def test_an_unrateable_moment_keeps_its_row_and_reason(cur):
    _apply(cur)
    seed = _drawn_take(cur)
    reads = _reads(seed["frame"], filler=None, hedging=None, slide_fit=None,
                   holding_together=None, role=None)
    _record(cur, seed["take"], reads)
    rows = _rows(cur, seed["take"])
    assert all(r["w"] is None and r["willfident"] is None for r in rows)
    assert {r["unrateable_reason"] for r in rows} == {"no_word_signal"}
    cur.execute("SELECT * FROM public.v4_willfidence_takes "
                "WHERE take_session_id = %s", (seed["take"],))
    take = cur.fetchone()
    assert take["willfidence"] is None
    assert take["status"] == "audio_problem"


def test_a_moment_without_a_sound_read_is_no_sound_read(cur):
    _apply(cur)
    seed = _drawn_take(cur)
    cur.execute("UPDATE public.snippets SET metrics = '{}'::jsonb "
                "WHERE session_id = %s", (seed["take"],))
    _record(cur, seed["take"], _reads(seed["frame"]))
    rows = _rows(cur, seed["take"])
    assert {r["unrateable_reason"] for r in rows} == {"no_sound_read"}
    assert all(r["s"] is None and r["sound_clips"] == 0 for r in rows)


@pytest.mark.parametrize("mutate", [
    lambda r: r.pop(),
    lambda r: r.append(dict(r[0])),
    lambda r: r.append({**r[0], "block_id": "speech-block:other"}),
    lambda r: r[0].update(filler=1.5),
    lambda r: r[0].update(hedging=-0.1),
    lambda r: r[0].update(slide_fit=0.3),
    lambda r: r[0].update(holding_together=0.75),
    lambda r: r[0].update(role="keynote"),
    lambda r: r[0].update(filler="0.5"),
    lambda r: r[0].update(block_id=None),
])
def test_bad_reads_are_refused(cur, mutate):
    _apply(cur)
    seed = _drawn_take(cur)
    reads = _reads(seed["frame"])
    mutate(reads)
    with pytest.raises(psycopg2.errors.RaiseException, match="V4_WILLFIDENCE"):
        _record(cur, seed["take"], reads)


def test_no_frame_or_no_draw_writes_nothing(cur):
    _apply(cur)
    assert _record(cur, str(uuid.uuid4()), []) == {"outcome": "no_frame"}
    seed = draw_suite._stored_take(cur)
    assert _record(cur, seed["take"], _reads(seed["frame"])) == {"outcome": "no_draw"}
    assert _rows(cur, seed["take"]) == []


def test_a_second_call_writes_nothing_new(cur):
    _apply(cur)
    seed = _drawn_take(cur)
    _record(cur, seed["take"], _reads(seed["frame"]))
    before = _rows(cur, seed["take"])
    again = _record(cur, seed["take"], _reads(seed["frame"], filler=0.0))
    assert again["outcome"] == "stored"
    assert _rows(cur, seed["take"]) == before


def test_the_speaker_line_is_the_same_rule(cur):
    _apply(cur)
    seed = _drawn_take(cur)
    _record(cur, seed["take"], _reads(seed["frame"]))
    cur.execute("SELECT public.v4_speaker_willfidence_v1(%s::uuid) AS r",
                (seed["principal"],))
    line = cur.fetchone()["r"]
    rows = _rows(cur, seed["take"])
    expected = wf.summary([
        {"is_random": r["is_random"], "s": float(r["s"]), "w": float(r["w"])}
        for r in rows])
    assert line["rated_random_moments"] == expected["rated_random_moments"]
    assert line["willfidence"] == pytest.approx(expected["willfidence"])
    assert line["status"] == expected["status"]
    cur.execute("SELECT public.v4_speaker_willfidence_v1(%s::uuid) AS r",
                (str(uuid.uuid4()),))
    assert cur.fetchone()["r"]["status"] == "not_enough_data"


def test_the_table_checks_the_boxes(cur):
    _apply(cur)
    seed = _drawn_take(cur)
    _record(cur, seed["take"], _reads(seed["frame"]))
    row = dict(_rows(cur, seed["take"])[0])
    cur.execute("DELETE FROM public.v4_willfidence_reads WHERE take_session_id = %s",
                (seed["take"],))
    row["willfident"] = Decimal(row["willfident"]) + Decimal("0.01")
    columns = [c for c in row if c != "created_at"]
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute(
            f"INSERT INTO public.v4_willfidence_reads ({', '.join(columns)}) "
            f"VALUES ({', '.join(['%s'] * len(columns))})",
            [row[c] for c in columns])


def test_the_door_and_idempotency(cur):
    _apply(cur)
    cur.execute(draw_suite._body(MIGRATION))
    objects = [("public.v4_willfidence_reads", "t"), ("public.v4_willfidence_takes", "t"),
               ("public.record_v4_willfidence_reads_v1(uuid, jsonb)", "f"),
               ("public.v4_speaker_willfidence_v1(uuid)", "f")]
    for role in ("anon", "authenticated"):
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        if cur.fetchone() is None:
            continue
        for name, kind in objects:
            if kind == "t":
                cur.execute("SELECT has_table_privilege(%s, %s, 'SELECT') AS p", (role, name))
            else:
                cur.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE') AS p", (role, name))
            assert cur.fetchone()["p"] is False, (role, name)
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'service_role'")
    if cur.fetchone() is not None:
        for table in ("public.v4_willfidence_reads", "public.v4_willfidence_takes"):
            for privilege, held in (("SELECT", True), ("INSERT", False),
                                    ("UPDATE", False), ("DELETE", True)):
                cur.execute("SELECT has_table_privilege('service_role', %s, %s) AS p",
                            (table, privilege))
                assert cur.fetchone()["p"] is held, (table, privilege)
