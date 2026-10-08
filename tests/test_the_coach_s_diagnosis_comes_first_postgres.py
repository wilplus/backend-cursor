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
import pathlib
import threading
import time
import uuid

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "the_coach_s_diagnosis_comes_first.sql"
SIGNATURE = "public.set_coach_moment_diagnosis_v1(text, text, text, text, text, text)"


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


def _role_exists(cur, role: str) -> bool:
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    return cur.fetchone() is not None


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


def test_the_tables_and_the_function_sit_behind_the_door(db):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for table in ("coach_named_errors", "coach_moment_diagnoses"):
            cur.execute("SELECT relrowsecurity FROM pg_class WHERE relname = %s", (table,))
            assert cur.fetchone()["relrowsecurity"] is True, table
            cur.execute("SELECT count(*) AS n FROM pg_class c, aclexplode(c.relacl) a "
                        "WHERE c.oid = %s::regclass AND a.grantee = 0", (f"public.{table}",))
            assert cur.fetchone()["n"] == 0, table
        cur.execute("SELECT prosecdef, proconfig FROM pg_proc "
                    "WHERE proname = 'set_coach_moment_diagnosis_v1'")
        row = cur.fetchone()
        assert row["prosecdef"] is True
        assert any(c.startswith("search_path=") for c in (row["proconfig"] or []))
        cur.execute("SELECT count(*) AS n FROM pg_proc p, aclexplode(p.proacl) a "
                    "WHERE p.oid = %s::regprocedure AND a.grantee = 0", (SIGNATURE,))
        assert cur.fetchone()["n"] == 0
        for role in ("anon", "authenticated"):
            if not _role_exists(cur, role):
                continue
            for table in ("coach_named_errors", "coach_moment_diagnoses"):
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    cur.execute("SELECT has_table_privilege(%s, %s, %s) AS ok",
                                (role, f"public.{table}", privilege))
                    assert cur.fetchone()["ok"] is False, (role, table, privilege)
            cur.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE') AS ok", (role, SIGNATURE))
            assert cur.fetchone()["ok"] is False, role
        if _role_exists(cur, "service_role"):
            expected = {("coach_named_errors", "SELECT"): True,
                        ("coach_named_errors", "INSERT"): False,
                        ("coach_named_errors", "UPDATE"): False,
                        ("coach_named_errors", "DELETE"): False,
                        ("coach_moment_diagnoses", "SELECT"): True,
                        ("coach_moment_diagnoses", "DELETE"): True,
                        ("coach_moment_diagnoses", "INSERT"): False,
                        ("coach_moment_diagnoses", "UPDATE"): False}
            for (table, privilege), want in expected.items():
                cur.execute("SELECT has_table_privilege('service_role', %s, %s) AS ok",
                            (f"public.{table}", privilege))
                assert cur.fetchone()["ok"] is want, (table, privilege)
            cur.execute("SELECT has_function_privilege('service_role', %s, 'EXECUTE') AS ok",
                        (SIGNATURE,))
            assert cur.fetchone()["ok"] is True
        # By their shape: no label value, no answer, no read, no count.
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'coach_moment_diagnoses'")
        assert {r["column_name"] for r in cur.fetchall()} == {
            "id", "take_session_id", "snippet_id", "coach_id", "kind", "error_id",
            "named_error_id", "version", "created_at", "superseded_at"}


def test_applied_again_the_file_changes_nothing(db):
    take, snippet, coach = (str(uuid.uuid4()) for _ in range(3))
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        _set(cur, take, snippet, coach, "named_error", new_name="trailing off")
        before = _history(cur, snippet, coach)
        cur.execute("SELECT count(*) AS n FROM public.coach_named_errors")
        named_before = cur.fetchone()["n"]
        cur.execute(MIGRATION.read_text())
        assert _history(cur, snippet, coach) == before
        cur.execute("SELECT count(*) AS n FROM public.coach_named_errors")
        assert cur.fetchone()["n"] == named_before


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


def test_a_name_said_twice_is_one_coach_named_error_until_the_founder_links_it(db):
    take, coach_a, coach_b = (str(uuid.uuid4()) for _ in range(3))
    name = f"mumbled ending {uuid.uuid4().hex[:6]}"
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        a = _set(cur, take, str(uuid.uuid4()), coach_a, "named_error", new_name=name)
        b = _set(cur, take, str(uuid.uuid4()), coach_b, "named_error",
                 new_name="  " + name.upper() + "  ")
        assert a["named_error_id"] == b["named_error_id"]
        cur.execute("SELECT name, name_key, named_by, speaking_error_id, linked_at "
                    "FROM public.coach_named_errors WHERE id = %s", (a["named_error_id"],))
        row = dict(cur.fetchone())
        # The first coach's words, as said; named by that coach; not linked.
        assert row == {"name": name, "name_key": name.lower(), "named_by": coach_a,
                       "speaking_error_id": None, "linked_at": None}
        # The founder writes the definition and question in admin and links
        # it: from then on the same words are that library error.
        library = _library_error(cur)
        cur.execute("UPDATE public.coach_named_errors SET speaking_error_id = %s, linked_at = now() "
                    "WHERE id = %s", (library, a["named_error_id"]))
        c = _set(cur, take, str(uuid.uuid4()), coach_a, "named_error", new_name=name)
        assert (c["kind"], c["error_id"], c["named_error_id"]) == ("error", library, None)
        # The link is all or nothing.
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("UPDATE public.coach_named_errors SET linked_at = NULL WHERE id = %s",
                        (a["named_error_id"],))
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.coach_named_errors (name, name_key, named_by) "
                        "VALUES ('Shouting', 'wrong key', 'c')")


def test_refusals_are_named(db):
    take, snippet, coach = (str(uuid.uuid4()) for _ in range(3))
    with db.cursor() as cur:
        retired = _library_error(cur, active=False)
        for kind, error_id, name, code in (
                ("error", retired, None, "COACH_DIAGNOSIS_ERROR_NOT_IN_LIBRARY"),
                ("error", "no_such_error", None, "COACH_DIAGNOSIS_ERROR_NOT_IN_LIBRARY"),
                ("error", None, None, "COACH_DIAGNOSIS_INPUT_INVALID"),
                ("error", "x", "and a name", "COACH_DIAGNOSIS_INPUT_INVALID"),
                ("named_error", None, "   ", "COACH_DIAGNOSIS_INPUT_INVALID"),
                ("named_error", None, "x" * 121, "COACH_DIAGNOSIS_INPUT_INVALID"),
                ("no_error", "x", None, "COACH_DIAGNOSIS_INPUT_INVALID"),
                ("praise", None, None, "COACH_DIAGNOSIS_INPUT_INVALID"),
                (None, None, None, "COACH_DIAGNOSIS_INPUT_INVALID")):
            with pytest.raises(psycopg2.errors.RaiseException, match=code):
                cur.execute("SELECT public.set_coach_moment_diagnosis_v1(%s, %s, %s, %s, %s, %s)",
                            (take, snippet, coach, kind, error_id, name))
        with pytest.raises(psycopg2.errors.RaiseException, match="COACH_DIAGNOSIS_INPUT_INVALID"):
            cur.execute("SELECT public.set_coach_moment_diagnosis_v1('', %s, %s, 'no_error', NULL, NULL)",
                        (snippet, coach))
        cur.execute("SELECT count(*) FROM public.coach_moment_diagnoses WHERE snippet_id = %s",
                    (snippet,))
        assert cur.fetchone()[0] == 0


def test_service_role_calls_the_function_and_cannot_write_by_hand(db):
    with db.cursor() as cur:
        if not _role_exists(cur, "service_role"):
            pytest.skip("no service_role on this cluster")
        library = _library_error(cur)
    take, snippet, coach = (str(uuid.uuid4()) for _ in range(3))
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SET ROLE service_role")
            row = _set(cur, take, snippet, coach, "error", error_id=library)
            assert row["kind"] == "error"
            named = _set(cur, take, snippet, coach, "named_error", new_name="swallowed words")
            assert named["version"] == 2
            cur.execute("SELECT name FROM public.coach_named_errors WHERE id = %s",
                        (named["named_error_id"],))
            assert cur.fetchone()["name"] == "swallowed words"
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("INSERT INTO public.coach_moment_diagnoses (take_session_id, "
                            "snippet_id, coach_id, kind, version) VALUES ('t', 's', 'c', 'no_error', 1)")
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("UPDATE public.coach_moment_diagnoses SET kind = 'no_error' "
                            "WHERE snippet_id = %s", (snippet,))
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("INSERT INTO public.coach_named_errors (name, name_key, named_by) "
                            "VALUES ('x', 'x', 'c')")
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("DELETE FROM public.coach_named_errors WHERE id = %s",
                            (named["named_error_id"],))
            cur.execute("DELETE FROM public.coach_moment_diagnoses WHERE snippet_id = %s", (snippet,))
            cur.execute("SELECT count(*) AS n FROM public.coach_moment_diagnoses WHERE snippet_id = %s",
                        (snippet,))
            assert cur.fetchone()["n"] == 0
    finally:
        conn.close()


def test_a_double_tap_returns_the_same_row(db):
    take, snippet, coach = (str(uuid.uuid4()) for _ in range(3))
    first = psycopg2.connect(DSN)
    second = psycopg2.connect(DSN)
    second.autocommit = True
    result: dict = {}
    try:
        with first.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            row = _set(cur, take, snippet, coach, "no_error")

        def tap():
            try:
                with second.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as c2:
                    result["row"] = _set(c2, take, snippet, coach, "no_error")
            except Exception as e:  # noqa: BLE001 -- reported below
                result["error"] = e

        t = threading.Thread(target=tap)
        t.start()
        deadline, waiting = time.time() + 10, False
        with db.cursor() as probe:
            while time.time() < deadline and not waiting:
                probe.execute("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                              "AND NOT granted")
                waiting = probe.fetchone()[0] > 0
                if not waiting:
                    time.sleep(0.05)
        assert waiting, "the second save did not wait for the first"
        first.commit()
        t.join(10)
        assert not t.is_alive()
        assert "error" not in result, result.get("error")
        assert result["row"]["id"] == row["id"]
        with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            assert [h["version"] for h in _history(cur, snippet, coach)] == [1]
    finally:
        first.close()
        second.close()


def test_a_name_linked_to_a_retired_entry_stays_the_coach_named_error(db):
    take, coach = str(uuid.uuid4()), str(uuid.uuid4())
    name = f"rushed close {uuid.uuid4().hex[:6]}"
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        a = _set(cur, take, str(uuid.uuid4()), coach, "named_error", new_name=name)
        retired = _library_error(cur, active=False)
        cur.execute("UPDATE public.coach_named_errors SET speaking_error_id = %s, "
                    "linked_at = now() WHERE id = %s", (retired, a["named_error_id"]))
        b = _set(cur, take, str(uuid.uuid4()), coach, "named_error", new_name=name)
        assert (b["kind"], b["error_id"], b["named_error_id"]) == (
            "named_error", None, a["named_error_id"])


def test_the_purge_clears_named_by_and_keeps_the_named_error(db):
    take, coach, other = (str(uuid.uuid4()) for _ in range(3))
    name = f"dropped tail {uuid.uuid4().hex[:6]}"
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        a = _set(cur, take, str(uuid.uuid4()), coach, "named_error", new_name=name)
        b = _set(cur, take, str(uuid.uuid4()), other, "named_error", new_name=name)
        cur.execute("SELECT is_nullable FROM information_schema.columns WHERE "
                    "table_schema = 'public' AND table_name = 'coach_named_errors' "
                    "AND column_name = 'named_by'")
        assert cur.fetchone()["is_nullable"] == "YES"
    has_service = False
    with db.cursor() as cur:
        has_service = _role_exists(cur, "service_role")
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            if has_service:
                cur.execute("SET ROLE service_role")
                cur.execute("SELECT has_column_privilege('service_role', "
                            "'public.coach_named_errors', 'named_by', 'UPDATE'), "
                            "has_column_privilege('service_role', "
                            "'public.coach_named_errors', 'name', 'UPDATE'), "
                            "has_column_privilege('service_role', "
                            "'public.coach_named_errors', 'speaking_error_id', 'UPDATE')")
                assert cur.fetchone() == (True, False, False)
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                    cur.execute("UPDATE public.coach_named_errors SET name = 'x' "
                                "WHERE named_by = %s", (coach,))
            # The purge's step (data_purge_registry coach_named_errors_named_by,
            # clears_selector): the selector set to NULL for the deleted coach.
            cur.execute("UPDATE public.coach_named_errors SET named_by = NULL "
                        "WHERE named_by = %s", (coach,))
            assert cur.rowcount == 1
            cur.execute("SELECT count(*) FROM public.coach_named_errors WHERE named_by = %s",
                        (coach,))
            assert cur.fetchone() == (0,)
    finally:
        conn.close()
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT name, named_by FROM public.coach_named_errors WHERE id = %s",
                    (a["named_error_id"],))
        assert dict(cur.fetchone()) == {"name": name, "named_by": None}
        # The other coach's diagnosis still points at it, and the same words
        # said again still find it.
        cur.execute("SELECT named_error_id FROM public.coach_moment_diagnoses WHERE id = %s",
                    (b["id"],))
        assert cur.fetchone()["named_error_id"] == a["named_error_id"]
        c = _set(cur, take, str(uuid.uuid4()), other, "named_error", new_name=name)
        assert c["named_error_id"] == a["named_error_id"]
