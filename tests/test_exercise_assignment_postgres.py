"""
STORY    As the founder, I want each moment's exercise drawn 80/20 once,
         reproducibly and immutably, so that the comparison is trustworthy
         later and harmless to the speaker now.
OUTCOME
  O1  One draw per moment: a later call, even with another pool, returns the
      first row.
  O2  Two or more exercises: every probability is stored (4/5 for the best
      match, the rest shared) and they sum to one.
  O3  One exercise is a deterministic singleton: no seed, no draw.
  O4  Every draw is reproducible from its stored seed, its commitment is the
      seed's hash, the mode and rank follow from the draw, and over many
      moments the split is close to 80/20 (both branches are exercised).
  O5  The row cannot be updated; browser roles reach neither the table nor
      the function, and the server cannot write the table directly.
PROVES   O1 -> test_a_moment_is_drawn_once
         O2 -> test_every_probability_is_stored_and_they_sum_to_one
         O3 -> test_one_exercise_is_a_singleton_without_a_draw
         O4 -> test_draws_are_reproducible_and_split_close_to_80_20
         O5 -> test_the_row_is_immutable_and_browser_roles_reach_nothing
WHY      Founder 2026-09-26: "please do the 80/20 try smth new" (0372).
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


def _recomputed_draw(db, row):
    return _one(db, """
        SELECT ('x' || substr(encode(extensions.digest(
                   %s::bytea || convert_to(%s || ':' || %s || ':exercise-80-20-v1', 'UTF8'),
                   'sha256'), 'hex'), 1, 13))::bit(52)::bigint::numeric
               / 4503599627370496::numeric""",
        (bytes(row["protected_seed"]), row["take_session_id"], row["snippet_id"]))


def test_a_moment_is_drawn_once(db):
    take, snippet = str(uuid.uuid4()), str(uuid.uuid4())
    first = _assign(db, _pool(3), take=take, snippet=snippet)
    again = _assign(db, _pool(5), take=take, snippet=snippet)
    assert again == first
    assert _one(db, "SELECT count(*) FROM public.confident_voice_exercise_assignments "
                    "WHERE take_session_id = %s AND snippet_id = %s",
                (take, snippet)) == 1


def test_every_probability_is_stored_and_they_sum_to_one(db):
    row = _assign(db, _pool(3))
    odds = [Fraction(c["probability_numerator"], c["probability_denominator"])
            for c in row["candidates"]]
    assert odds == [Fraction(4, 5), Fraction(1, 10), Fraction(1, 10)]
    assert sum(odds) == 1
    assert [c["rank"] for c in row["candidates"]] == [1, 2, 3]


def test_one_exercise_is_a_singleton_without_a_draw(db):
    row = _assign(db, _pool(1))
    assert row["selection_mode"] == "deterministic_singleton"
    assert row["selected_exercise_id"] == "ex-1"
    assert (row["protected_seed"], row["seed_commitment_sha256"], row["draw"]) == (
        None, None, None)
    assert [(c["probability_numerator"], c["probability_denominator"])
            for c in row["candidates"]] == [(1, 1)]


def test_draws_are_reproducible_and_split_close_to_80_20(db):
    rows = [_assign(db, _pool(3)) for _ in range(300)]
    for row in rows:
        draw = float(row["draw"])
        if draw < 0.8:
            assert (row["selection_mode"], row["selected_rank"]) == ("top", 1)
        else:
            assert row["selection_mode"] == "exploration"
            assert row["selected_rank"] == 2 + int((draw - 0.8) * 5 * 2)
        assert row["selected_exercise_id"] == f"ex-{row['selected_rank']}"
        assert _recomputed_draw(db, row) == row["draw"]
        assert row["seed_commitment_sha256"] == _one(
            db, "SELECT encode(extensions.digest(%s::bytea, 'sha256'), 'hex')",
            (bytes(row["protected_seed"]),))
    modes = [row["selection_mode"] for row in rows]
    assert {"top", "exploration"} <= set(modes)
    assert 0.70 <= modes.count("top") / len(modes) <= 0.90


def test_the_row_is_immutable_and_browser_roles_reach_nothing(db):
    row = _assign(db, _pool(2))
    with db.cursor() as cur:
        with pytest.raises(psycopg2.Error, match="CV_EXERCISE_ASSIGNMENT_IMMUTABLE"):
            cur.execute("UPDATE public.confident_voice_exercise_assignments "
                        "SET selected_rank = 2 WHERE id = %s", (row["id"],))
    table = "public.confident_voice_exercise_assignments"
    function = ("public.assign_confident_voice_exercise_v1("
                "text, text, text, text, text, jsonb)")
    for role in ("anon", "authenticated"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert _one(db, "SELECT has_table_privilege(%s, %s, %s)",
                        (role, table, privilege)) is False, (role, privilege)
        assert _one(db, "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                    (role, function)) is False, role
    for privilege in ("INSERT", "UPDATE"):
        assert _one(db, "SELECT has_table_privilege('service_role', %s, %s)",
                    (table, privilege)) is False, privilege
