"""0447: a Take draws its random moments (V4 B1.2, build plan D-ML-7;
founder V2 A, V3 A), on the disposable rehearsal database.

The Take, the frame and the frame writer are the 0431/0441 suite's own, so
the draw is tested on the frame the code really builds and stores.

Pins:
  * the database draws ceil(n/5) of the frame's blocks, exactly the ones
    services.v4_random_moments.draw_moments draws for the same seed;
  * a second call draws nothing new and returns the stored draw; the same
    Take drawn again from scratch draws the same moments;
  * the draw is stored apart from the frame: the frame (and its pick log)
    is unchanged, and the draw table holds no pick;
  * a Take with no frame gets 'no_frame'; nothing is stored;
  * the table's own checks refuse a wrong count, rank or version;
  * browser roles hold nothing; service_role may read and delete (the purge)
    and call the writer, never insert or update; the file applied twice changes nothing.
"""
from __future__ import annotations

import pathlib
import uuid

import psycopg2
import psycopg2.errors
import psycopg2.extras
import pytest

from services import v4_random_moments as rm
from tests import test_the_shadow_writer_accepts_the_frame_the_code_builds_postgres as base

DSN = base.DSN
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "a_take_draws_its_random_moments.sql"


@pytest.fixture
def cur():
    yield from base.cur.__wrapped__()


def _body(path: pathlib.Path) -> str:
    return "\n".join(line for line in path.read_text().splitlines()
                     if line.strip() not in ("BEGIN;", "COMMIT;"))


def _apply(cur):
    cur.execute(base._migration_body())
    cur.execute(_body(MIGRATION))


def _stored_take(cur):
    seed = base._seed_take(cur)
    assert base._write(cur, seed, seed["frame"])["outcome"] == "stored"
    return seed


def _draw(cur, take):
    cur.execute("SELECT public.draw_v4_random_moments_v1(%s::uuid) AS r", (take,))
    return cur.fetchone()["r"]


def _rows(cur, take):
    cur.execute("SELECT * FROM public.v4_random_moments WHERE take_session_id = %s "
                "ORDER BY draw_rank", (take,))
    return cur.fetchall()


def test_the_database_draws_what_the_code_draws(cur):
    _apply(cur)
    seed = _stored_take(cur)
    frame = seed["frame"]
    blocks = [b["block_id"] for b in frame["blocks"]]
    outcome = _draw(cur, seed["take"])
    assert outcome["outcome"] == "drawn"
    assert outcome["moments"] == len(blocks)
    rows = _rows(cur, seed["take"])
    expected = rm.draw_moments(frame["pick_log"]["seed"], blocks)
    assert [r["block_id"] for r in rows] == expected
    assert len(rows) == rm.draw_size(len(blocks))
    for rank, row in enumerate(rows, 1):
        assert row["draw_rank"] == rank
        assert row["moments_in_take"] == len(blocks)
        assert row["drawn_count"] == len(rows)
        assert row["seed"] == frame["pick_log"]["seed"]
        assert row["frame_hash"] == frame["frame_hash"]
        assert row["draw_version"] == rm.DRAW_VERSION
        assert str(row["acquisition_principal_id"]) == seed["principal"]
    slides = {b["block_id"]: b["slide_index"] for b in frame["blocks"]}
    assert all(r["slide_index"] == slides[r["block_id"]] for r in rows)


def test_many_moments_draw_twenty_percent_rounded_up(cur):
    """A frame with many blocks: the database and the code agree on which."""
    _apply(cur)
    seed = _stored_take(cur)
    # Widen the stored frame's blocks in place (the frame table refuses
    # UPDATE, so the trigger is lifted inside this rolled-back transaction).
    blocks = [{"block_id": f"speech-block:{i:020d}", "slide_index": i % 3}
              for i in range(23)]
    cur.execute("ALTER TABLE public.take_feedback_policy_v3_shadow_frames "
                "DISABLE TRIGGER USER")
    cur.execute("UPDATE public.take_feedback_policy_v3_shadow_frames "
                "SET frame = jsonb_set(frame, '{blocks}', %s) "
                "WHERE take_session_id = %s",
                (psycopg2.extras.Json(blocks), seed["take"]))
    assert _draw(cur, seed["take"])["drawn"] == 5
    expected = rm.draw_moments(seed["frame"]["pick_log"]["seed"],
                               [b["block_id"] for b in blocks])
    assert [r["block_id"] for r in _rows(cur, seed["take"])] == expected


def test_a_second_call_returns_the_stored_draw(cur):
    _apply(cur)
    seed = _stored_take(cur)
    first = _draw(cur, seed["take"])
    before = _rows(cur, seed["take"])
    again = _draw(cur, seed["take"])
    assert again["outcome"] == "stored"
    assert again["drawn"] == first["drawn"]
    assert _rows(cur, seed["take"]) == before


def test_the_same_take_drawn_again_draws_the_same_moments(cur):
    _apply(cur)
    seed = _stored_take(cur)
    _draw(cur, seed["take"])
    first = [r["block_id"] for r in _rows(cur, seed["take"])]
    cur.execute("DELETE FROM public.v4_random_moments WHERE take_session_id = %s",
                (seed["take"],))
    _draw(cur, seed["take"])
    assert [r["block_id"] for r in _rows(cur, seed["take"])] == first


def test_the_draw_leaves_the_frame_and_its_picks_alone(cur):
    _apply(cur)
    seed = _stored_take(cur)
    _draw(cur, seed["take"])
    cur.execute("SELECT frame FROM public.take_feedback_policy_v3_shadow_frames "
                "WHERE take_session_id = %s", (seed["take"],))
    assert cur.fetchone()["frame"] == seed["frame"]
    cur.execute("SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'v4_random_moments'")
    columns = {r["column_name"] for r in cur.fetchall()}
    assert not columns & {"candidate_id", "pick_probability", "selected",
                          "score", "lane"}


def test_a_take_without_a_frame_draws_nothing(cur):
    _apply(cur)
    take = str(uuid.uuid4())
    assert _draw(cur, take) == {"outcome": "no_frame"}
    assert _rows(cur, take) == []


@pytest.mark.parametrize("change", [
    {"drawn_count": 2},
    {"draw_rank": 0},
    {"draw_version": "v4-random-draw-v0"},
    {"seed": "-1"},
    {"block_id": ""},
])
def test_the_table_refuses_a_wrong_row(cur, change):
    _apply(cur)
    seed = _stored_take(cur)
    _draw(cur, seed["take"])
    row = dict(_rows(cur, seed["take"])[0])
    row.update(block_id=row["block_id"] + "-copy", draw_rank=row["drawn_count"])
    cur.execute("DELETE FROM public.v4_random_moments WHERE take_session_id = %s",
                (seed["take"],))
    row.update(change)
    columns = [c for c in row if c != "created_at"]
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute(
            f"INSERT INTO public.v4_random_moments ({', '.join(columns)}) "
            f"VALUES ({', '.join(['%s'] * len(columns))})",
            [row[c] for c in columns])


def test_the_door_and_idempotency(cur):
    _apply(cur)
    cur.execute(_body(MIGRATION))
    for role in ("anon", "authenticated"):
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
        if cur.fetchone() is None:
            continue
        cur.execute("SELECT has_table_privilege(%s, 'public.v4_random_moments', "
                    "'SELECT') AS t, has_function_privilege(%s, "
                    "'public.draw_v4_random_moments_v1(uuid)', 'EXECUTE') AS f",
                    (role, role))
        assert cur.fetchone() == {"t": False, "f": False}
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'service_role'")
    if cur.fetchone() is not None:
        for privilege, held in (("SELECT", True), ("INSERT", False),
                                ("UPDATE", False), ("DELETE", True)):
            cur.execute("SELECT has_table_privilege('service_role', "
                        "'public.v4_random_moments', %s) AS p", (privilege,))
            assert cur.fetchone()["p"] is held, privilege
    cur.execute("SELECT relrowsecurity FROM pg_class "
                "WHERE oid = 'public.v4_random_moments'::regclass")
    assert cur.fetchone()["relrowsecurity"] is True
