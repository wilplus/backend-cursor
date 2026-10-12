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

import pytest

from services import v4_random_moments as rm
from tests import (
    test_the_shadow_writer_accepts_the_frame_the_code_builds_postgres as base,
)

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
