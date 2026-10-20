"""
STORY    As the founder, I want an "exercise rendered" receipt recorded once,
         only by the owner and only for the drawn exercise, so that learning
         counts only exercises speakers really saw.
OUTCOME
  O1  Repeated confirmations of one moment give one row, the drawn exercise.
  O2  A non-owner, a wrong exercise, or a moment with no draw is refused by
      name and writes nothing.
  O3  The row is immutable, goes when its assignment is erased, and browser
      roles reach neither the table nor the function.
PROVES   O1 -> test_repeated_confirmations_give_one_exposure
         O2 -> test_only_the_owner_and_only_the_selected_exercise
         O3 -> test_the_row_is_immutable_erased_with_its_draw_and_browser_proof
WHY      0387: learning counts only confirmed renders (§3.5 item 5).
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


def _assign(db, owner, take, snippet):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM public.assign_confident_voice_exercise_v1("
            "%s, %s, %s, 'v3_exercise_block', 'exercise-fit-tier-v1:exact', "
            "%s::jsonb)",
            (owner, take, snippet,
             psycopg2.extras.Json([{"exercise_id": "room", "version": 2}])))
        return dict(cur.fetchone())


def _rendered(db, owner, take, snippet, exercise="room"):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM public.record_exercise_rendered_v1(%s, %s, %s, %s)",
                    (owner, take, snippet, exercise))
        return dict(cur.fetchone())


def _ids():
    return str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())


def test_only_the_owner_and_only_the_selected_exercise(db):
    owner, take, snippet = _ids()
    _assign(db, owner, take, snippet)
    with pytest.raises(psycopg2.Error, match="NOT_OWNER"):
        _rendered(db, str(uuid.uuid4()), take, snippet)
    with pytest.raises(psycopg2.Error, match="WRONG_EXERCISE"):
        _rendered(db, owner, take, snippet, exercise="other")
    with pytest.raises(psycopg2.Error, match="EXERCISE_RENDERED_NOT_DRAWN"):
        _rendered(db, owner, take, str(uuid.uuid4()))
    assert _one(db, "SELECT count(*) FROM public.confident_voice_exercise_exposures "
                    "WHERE take_session_id = %s", (take,)) == 0


def _one(db, sql, args):
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()[0]


def test_repeated_confirmations_give_one_exposure(db):
    owner, take, snippet = _ids()
    assigned = _assign(db, owner, take, snippet)
    first = _rendered(db, owner, take, snippet)
    again = _rendered(db, owner, take, snippet)
    assert again == first
    assert (first["assignment_id"], first["exercise_id"], first["exercise_version"]) == (
        assigned["id"], "room", 2)
    assert _one(db, "SELECT count(*) FROM public.confident_voice_exercise_exposures "
                    "WHERE assignment_id = %s", (assigned["id"],)) == 1


def test_the_row_is_immutable_erased_with_its_draw_and_browser_proof(db):
    owner, take, snippet = _ids()
    assigned = _assign(db, owner, take, snippet)
    seen = _rendered(db, owner, take, snippet)
    with db.cursor() as cur:
        with pytest.raises(psycopg2.Error, match="CV_EXERCISE_EXPOSURE_IMMUTABLE"):
            cur.execute("UPDATE public.confident_voice_exercise_exposures "
                        "SET exercise_id = 'other' WHERE id = %s", (seen["id"],))
        cur.execute("DELETE FROM public.confident_voice_exercise_assignments "
                    "WHERE id = %s", (assigned["id"],))
    assert _one(db, "SELECT count(*) FROM public.confident_voice_exercise_exposures "
                    "WHERE id = %s", (seen["id"],)) == 0
    for role in ("anon", "authenticated"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert _one(db, "SELECT has_table_privilege(%s, "
                            "'public.confident_voice_exercise_exposures', %s)",
                        (role, privilege)) is False, (role, privilege)
        assert _one(db, "SELECT has_function_privilege(%s, "
                        "'public.record_exercise_rendered_v1(text, text, text, text)', "
                        "'EXECUTE')", (role,)) is False, role
