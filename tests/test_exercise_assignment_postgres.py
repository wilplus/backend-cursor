"""The 80/20 exercise choice, executed on a disposable database (0372).

Founder 2026-09-26: "please do the 80/20 try smth new". Pins what makes the
draw trustworthy as a comparison later and harmless to the speaker now:

  * one moment is drawn once: every later call returns the first row;
  * two or more exercises: the best match has probability 4/5, each other one
    1/(5(n-1)), the probabilities sum to one and are all stored;
  * one exercise is a deterministic singleton, with no seed and no draw;
  * the draw is reproducible from the stored seed, and the commitment is its
    hash;
  * over many moments the split is close to 80/20;
  * the row cannot be updated, browser roles reach nothing, and the server
    reaches only the function (to write) and the table (to read and erase).
"""
from __future__ import annotations

import os
import uuid

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)


@pytest.fixture(scope="module")
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    try:
        yield conn
    finally:
        conn.close()


def _pool(n):
    return [{"exercise_id": f"ex-{i}", "version": 1} for i in range(1, n + 1)]


def _assign(db, pool, take=None, snippet=None, lane="v3_exercise_block"):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM public.assign_confident_voice_exercise_v1("
            "%s, %s, %s, %s, 'exercise-proximity-service-v1', %s::jsonb)",
            (str(uuid.uuid4()), take or str(uuid.uuid4()),
             snippet or str(uuid.uuid4()), lane,
             psycopg2.extras.Json(pool)))
        return dict(cur.fetchone())


def _one(db, sql, args=()):
    with db.cursor() as cur:
        cur.execute(sql, args)
        row = cur.fetchone()
        return row[0] if row else None


def test_the_draw_decides_top_or_exploration_and_is_reproducible(db):
    row = _assign(db, _pool(3))
    draw = float(row["draw"])
    if draw < 0.8:
        assert (row["selection_mode"], row["selected_rank"]) == ("top", 1)
    else:
        assert row["selection_mode"] == "exploration"
        assert row["selected_rank"] == 2 + int((draw - 0.8) * 5 * 2)
    assert row["selected_exercise_id"] == f"ex-{row['selected_rank']}"
    recomputed = _one(db, """
        SELECT ('x' || substr(encode(extensions.digest(
                   %s::bytea || convert_to(%s || ':' || %s || ':exercise-80-20-v1', 'UTF8'),
                   'sha256'), 'hex'), 1, 13))::bit(52)::bigint::numeric
               / 4503599627370496::numeric""",
        (bytes(row["protected_seed"]), row["take_session_id"], row["snippet_id"]))
    assert recomputed == row["draw"]
    assert row["seed_commitment_sha256"] == _one(
        db, "SELECT encode(extensions.digest(%s::bytea, 'sha256'), 'hex')",
        (bytes(row["protected_seed"]),))
