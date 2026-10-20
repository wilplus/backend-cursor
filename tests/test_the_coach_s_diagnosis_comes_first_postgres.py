"""
STORY    As a coach, I want to save one current diagnosis per moment and
         change it later with the history kept, so that my judgement is
         recorded faithfully.
OUTCOME
  O1  One current diagnosis per moment and coach; the same diagnosis again
      is a no-op; a change writes the next version and keeps the old one.
  O2  A name said twice (any spacing or case) is one coach-named error; a
      retired library error is refused by name.
  O3  A double tap (two saves at once) returns the same row, never a key
      error.
  O4  Never-2: what a save hands back is only the coach's own diagnosis -
      nothing of the machine's read or the blind answers; browser roles hold
      nothing, and the app writes diagnoses only through the function.
PROVES   O1 -> test_one_current_diagnosis_re_settable_with_the_history_kept
         O2 -> test_names_dedupe_and_retired_errors_are_refused
         O3 -> test_a_double_tap_returns_the_same_row
         O4 -> test_the_save_returns_only_the_coach_s_own_answer
               test_browser_roles_hold_nothing_and_writes_go_through_the_function
WHY      0445; coach panel lock flow 6, N56.1; Q-B7 A, Q-B12 A.
"""
from __future__ import annotations

import os
import threading
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


def _library_error(cur, *, active=True) -> str:
    error_id = f"e_{uuid.uuid4().hex[:10]}"
    cur.execute("INSERT INTO public.speaking_error (error_id, label, definition, asks, "
                "status, active) VALUES (%s, %s, 'd', 'q', 'observed', %s)",
                (error_id, f"Label {error_id}", active))
    return error_id


def _set(cur, take, snippet, coach, kind, error_id=None, new_name=None) -> dict:
    cur.execute("SELECT * FROM public.set_coach_moment_diagnosis_v1(%s, %s, %s, %s, %s, %s)",
                (take, snippet, coach, kind, error_id, new_name))
    return dict(cur.fetchone())


def _history(cur, snippet, coach):
    cur.execute("SELECT version, kind, error_id, named_error_id, superseded_at IS NULL AS current "
                "FROM public.coach_moment_diagnoses WHERE snippet_id = %s AND coach_id = %s "
                "ORDER BY version", (snippet, coach))
    return [dict(r) for r in cur.fetchall()]


def test_one_current_diagnosis_re_settable_with_the_history_kept(db):
    take, snippet, coach = (str(uuid.uuid4()) for _ in range(3))
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        rushing = _library_error(cur)
        first = _set(cur, take, snippet, coach, "error", error_id=rushing)
        assert (first["kind"], first["error_id"], first["version"]) == ("error", rushing, 1)
        # The same diagnosis again changes nothing.
        again = _set(cur, take, snippet, coach, "error", error_id=rushing)
        assert again["id"] == first["id"]
        assert len(_history(cur, snippet, coach)) == 1
        # Q-B12 A: a change replaces the current row and keeps the old one.
        second = _set(cur, take, snippet, coach, "no_error")
        assert (second["kind"], second["version"]) == ("no_error", 2)
        third = _set(cur, take, snippet, coach, "named_error", new_name="  Trailing   off ")
        assert third["kind"] == "named_error" and third["version"] == 3
        history = _history(cur, snippet, coach)
        assert [(h["version"], h["kind"], h["current"]) for h in history] == [
            (1, "error", False), (2, "no_error", False), (3, "named_error", True)]
        # One current row per moment and coach is the table's own key.
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("INSERT INTO public.coach_moment_diagnoses (take_session_id, snippet_id, "
                        "coach_id, kind, version) VALUES (%s, %s, %s, 'no_error', 9)",
                        (take, snippet, coach))
        # Another coach's diagnosis of the same moment is their own.
        other = str(uuid.uuid4())
        mine = _set(cur, take, snippet, other, "error", error_id=rushing)
        assert mine["version"] == 1
        assert len(_history(cur, snippet, coach)) == 3


def test_names_dedupe_and_retired_errors_are_refused(db):
    take, coach = str(uuid.uuid4()), str(uuid.uuid4())
    name = f"Trailing off {uuid.uuid4().hex[:6]}"
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        first = _set(cur, take, str(uuid.uuid4()), coach, "named_error", new_name=name)
        again = _set(cur, take, str(uuid.uuid4()), str(uuid.uuid4()), "named_error",
                     new_name=f"  {name.upper().replace(' ', '   ')} ")
        assert first["named_error_id"] and again["named_error_id"] == first["named_error_id"]
        cur.execute("SELECT count(*) AS n FROM public.coach_named_errors "
                    "WHERE name_key = lower(%s)", (name,))
        assert cur.fetchone()["n"] == 1

        retired = _library_error(cur, active=False)
        snippet = str(uuid.uuid4())
        with pytest.raises(psycopg2.errors.RaiseException,
                           match="COACH_DIAGNOSIS_ERROR_NOT_IN_LIBRARY"):
            _set(cur, take, snippet, coach, "error", error_id=retired)
        assert _history(cur, snippet, coach) == []


def test_a_double_tap_returns_the_same_row(db):
    take, snippet, coach = (str(uuid.uuid4()) for _ in range(3))
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        error_id = _library_error(cur)
    first_tap = psycopg2.connect(DSN)
    second_tap = psycopg2.connect(DSN)
    second_tap.autocommit = True
    out: dict = {}
    try:
        with first_tap.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            out["first"] = _set(cur, take, snippet, coach, "error", error_id=error_id)

        def _second():
            try:
                with second_tap.cursor(
                        cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    out["second"] = _set(cur, take, snippet, coach, "error",
                                         error_id=error_id)
            except Exception as error:  # surfaced below
                out["error"] = error

        waiter = threading.Thread(target=_second)
        waiter.start()
        waiter.join(0.5)
        assert waiter.is_alive(), "the second tap must wait for the first"
        first_tap.commit()
        waiter.join(10)
        assert "error" not in out, out.get("error")
        assert out["second"]["id"] == out["first"]["id"]
    finally:
        first_tap.close()
        second_tap.close()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        assert len(_history(cur, snippet, coach)) == 1


def test_the_save_returns_only_the_coach_s_own_answer(db):
    take, snippet, coach = (str(uuid.uuid4()) for _ in range(3))
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        error_id = _library_error(cur)
        row = _set(cur, take, snippet, coach, "error", error_id=error_id)
    assert row["error_id"] == error_id and row["coach_id"] == coach
    assert set(row) == {"id", "take_session_id", "snippet_id", "coach_id", "kind",
                        "error_id", "named_error_id", "version", "created_at",
                        "superseded_at"}


def test_browser_roles_hold_nothing_and_writes_go_through_the_function(db):
    fn = ("public.set_coach_moment_diagnosis_v1"
          "(text, text, text, text, text, text)")
    with db.cursor() as cur:
        def table(role, name, priv):
            cur.execute("SELECT has_table_privilege(%s, %s, %s)", (role, name, priv))
            return cur.fetchone()[0]

        def call(role):
            cur.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, fn))
            return cur.fetchone()[0]

        for role in ("anon", "authenticated"):
            assert not call(role)
            for name in ("public.coach_moment_diagnoses", "public.coach_named_errors"):
                for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    assert not table(role, name, priv), (role, name, priv)
        assert call("service_role")
        assert table("service_role", "public.coach_moment_diagnoses", "SELECT")
        assert table("service_role", "public.coach_moment_diagnoses", "DELETE")
        for priv in ("INSERT", "UPDATE"):
            assert not table("service_role", "public.coach_moment_diagnoses", priv)
        assert not table("service_role", "public.coach_named_errors", "INSERT")
