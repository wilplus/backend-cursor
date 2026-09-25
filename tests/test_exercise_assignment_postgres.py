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
from fractions import Fraction

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


def test_a_moment_is_drawn_once(db):
    take, snippet = str(uuid.uuid4()), str(uuid.uuid4())
    first = _assign(db, _pool(4), take, snippet)
    # A different pool on replay still returns the first, frozen choice.
    again = _assign(db, _pool(2), take, snippet)
    assert again["id"] == first["id"]
    assert again["selected_exercise_id"] == first["selected_exercise_id"]
    assert _one(db, "SELECT count(*) FROM public.confident_voice_exercise_assignments "
                    "WHERE take_session_id = %s", (take,)) == 1


def test_every_probability_is_stored_and_they_sum_to_one(db):
    row = _assign(db, _pool(4))
    probabilities = [Fraction(c["probability_numerator"], c["probability_denominator"])
                     for c in row["candidates"]]
    assert probabilities == [Fraction(4, 5), Fraction(1, 15), Fraction(1, 15), Fraction(1, 15)]
    assert sum(probabilities) == 1
    assert [c["rank"] for c in row["candidates"]] == [1, 2, 3, 4]
    assert row["candidate_count"] == 4
    assert row["below_minimum_probability"] is False


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


def test_one_exercise_is_a_singleton_and_not_randomized(db):
    row = _assign(db, _pool(1))
    assert row["selection_mode"] == "deterministic_singleton"
    assert row["selected_exercise_id"] == "ex-1"
    assert row["protected_seed"] is None and row["draw"] is None
    assert row["rng_algorithm_version"] == "not_randomized_singleton"
    assert (row["candidates"][0]["probability_numerator"],
            row["candidates"][0]["probability_denominator"]) == (1, 1)


def test_the_split_is_close_to_eighty_twenty(db):
    rows = [_assign(db, _pool(3)) for _ in range(400)]
    top = sum(1 for r in rows if r["selection_mode"] == "top")
    # 400 draws at p = 0.8: sd = 8. Five sd either side fails once in ~10^6.
    assert 280 <= top <= 360
    explored = {r["selected_exercise_id"] for r in rows
                if r["selection_mode"] == "exploration"}
    assert explored == {"ex-2", "ex-3"}


def test_a_very_wide_pool_flags_the_probability_floor(db):
    row = _assign(db, _pool(22))
    assert row["below_minimum_probability"] is True


@pytest.mark.parametrize("pool, code", [
    ([], "CV_EXERCISE_ASSIGNMENT_INPUT_INVALID"),
    ([{"exercise_id": "", "version": 1}], "CV_EXERCISE_ASSIGNMENT_INPUT_INVALID"),
    ([{"exercise_id": "a", "version": 0}], "CV_EXERCISE_ASSIGNMENT_INPUT_INVALID"),
    ([{"exercise_id": "a", "version": 1.5}], "CV_EXERCISE_ASSIGNMENT_INPUT_INVALID"),
    ([{"exercise_id": "a", "version": 1}, {"exercise_id": "a", "version": 2}],
     "CV_EXERCISE_ASSIGNMENT_DUPLICATE_EXERCISE"),
])
def test_a_malformed_pool_is_refused(db, pool, code):
    with pytest.raises(psycopg2.Error, match=code):
        _assign(db, pool)


def test_an_unknown_lane_is_refused(db):
    with pytest.raises(psycopg2.Error, match="CV_EXERCISE_ASSIGNMENT_INPUT_INVALID"):
        _assign(db, _pool(2), lane="made_up")


def test_the_row_cannot_be_changed_but_can_be_erased(db):
    row = _assign(db, _pool(2))
    with pytest.raises(psycopg2.Error, match="CV_EXERCISE_ASSIGNMENT_IMMUTABLE"):
        _one(db, "UPDATE public.confident_voice_exercise_assignments "
                 "SET selected_rank = 1 WHERE id = %s RETURNING 1", (row["id"],))
    _one(db, "DELETE FROM public.confident_voice_exercise_assignments "
             "WHERE id = %s RETURNING 1", (row["id"],))
    assert _one(db, "SELECT count(*) FROM public.confident_voice_exercise_assignments "
                    "WHERE id = %s", (row["id"],)) == 0


def test_who_may_do_what(db):
    call = ("SELECT public.assign_confident_voice_exercise_v1(%s, %s, %s, "
            "'legacy_offer', 'm', %s::jsonb)")
    args = (str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()),
            psycopg2.extras.Json(_pool(2)))
    with db.cursor() as cur:
        for role in ("anon", "authenticated"):
            for sql, params in (
                (call, args),
                ("SELECT 1 FROM public.confident_voice_exercise_assignments LIMIT 1", ()),
            ):
                cur.execute(f"SET ROLE {role}")
                try:
                    with pytest.raises(psycopg2.Error, match="permission denied"):
                        cur.execute(sql, params)
                finally:
                    cur.execute("RESET ROLE")
        cur.execute("SET ROLE service_role")
        try:
            cur.execute(call, args)
            cur.execute("SELECT count(*) FROM public.confident_voice_exercise_assignments")
            with pytest.raises(psycopg2.Error, match="permission denied"):
                cur.execute(
                    "INSERT INTO public.confident_voice_exercise_assignments "
                    "(owner_user_id) VALUES ('x')")
        finally:
            cur.execute("RESET ROLE")
