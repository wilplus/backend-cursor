"""The coach's diagnosis comes first, on a disposable database (0445; coach
panel lock flow 6, N56.1; Q-B7 A, Q-B12 A, N62; build plan D-CP-4).

Pins:
  * both tables exist with RLS on; browser roles and PUBLIC hold nothing on
    them or on the function; service_role reads both, deletes diagnoses,
    calls the function, and cannot write either table by hand;
  * the file applied again changes nothing;
  * a library error, a coach-named error and "no error" each save as one
    current diagnosis; the same diagnosis again is a no-op; a change
    supersedes the current row and writes the next version, so the history
    stays (Q-B12 A);
  * a name said twice (whatever the spacing or case) is one coach-named
    error, "named by a coach" until the founder links it; once linked, the
    diagnosis is the library error;
  * a retired or unknown library error is refused by name; bad input too;
  * a double tap (two saves of one diagnosis at once) waits on the
    moment-and-coach lock and returns the same row, never a key error;
  * a name linked to a library entry the founder has since retired stays
    the coach-named error;
  * the account purge clears named_by (service_role holds UPDATE on that
    column only) and keeps the coach-named error and the diagnoses on it;
  * nothing joins the new tables to the label ledger or the blind "Do you
    hear it?" answers (the shape has no such column).
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
