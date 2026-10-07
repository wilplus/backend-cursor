"""A coach is asked to listen again, blind, on a disposable database (0444;
QG12a A, P26b A, N53.4; P26c, N54.1; Q-B8 A, N62; build plan D-CP-10).

Pins:
  * the table exists with RLS on and, by its shape, no column that could
    carry a reason, an answer or a read; browser roles and PUBLIC hold
    nothing on it or on the two functions; service_role reads, deletes and
    calls the functions, and cannot write the table by hand;
  * the file applied again changes nothing;
  * the flag writes one open ask per coach with a blind judgment of record
    on the clip (coach lane, no self-report, no abstention, no peer, no
    anonymous row), none for a coach who has not judged it, none twice
    while one is open; the line key rotates A, B, C, A per coach;
  * the coach's new answer closes their open ask; a later flag opens a new
    one and the closed one stays as history;
  * bad input is refused by name.
"""
from __future__ import annotations

import os
import pathlib
import uuid

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "a_coach_is_asked_to_listen_again.sql"
KEYS = ("P26c-A", "P26c-B", "P26c-C")


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


def _label(cur, snippet_id, rater, *, value="no", lane="coach", self_report=False,
           unrateable=False):
    cur.execute(
        "INSERT INTO public.confidence_labels (snippet_id, rater_id, source, confident, "
        "state_id, value, lane, self_report, unrateable) VALUES (%s, %s, %s, %s, "
        "'confidence', %s, %s, %s, %s)",
        (snippet_id, rater, "coach" if lane == "coach" else "game",
         True if value == "yes" else False if value == "no" else None,
         value, lane, self_report, unrateable))


def _flag(cur, take, snippet) -> int:
    cur.execute("SELECT public.request_coach_listen_again_v1(%s, %s)", (take, snippet))
    return cur.fetchone()[0]


def _heard(cur, snippet, coach) -> int:
    cur.execute("SELECT public.mark_coach_listen_again_heard_v1(%s, %s)", (snippet, coach))
    return cur.fetchone()[0]


def _asks(cur, snippet):
    cur.execute("SELECT coach_id, line_key, heard_at IS NULL AS open "
                "FROM public.coach_listen_again_requests WHERE snippet_id = %s "
                "ORDER BY requested_at, coach_id", (snippet,))
    return [tuple(r) for r in cur.fetchall()]


def test_the_table_carries_no_reason_and_sits_behind_the_door(db):
    with db.cursor() as cur:
        cur.execute("SELECT relrowsecurity FROM pg_class WHERE relname = 'coach_listen_again_requests'")
        assert cur.fetchone() == (True,)
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'coach_listen_again_requests'")
        # By its shape: the Take, the moment, the coach, which signed line,
        # when asked, when heard. No reason, no answer, no read, no kind.
        assert {r[0] for r in cur.fetchall()} == {
            "id", "take_session_id", "snippet_id", "coach_id", "line_key",
            "requested_at", "heard_at"}
        for fn in ("request_coach_listen_again_v1", "mark_coach_listen_again_heard_v1"):
            cur.execute("SELECT prosecdef, proconfig FROM pg_proc WHERE proname = %s", (fn,))
            secdef, config = cur.fetchone()
            assert secdef is True and any(c.startswith("search_path=") for c in (config or [])), fn
        signatures = ("public.request_coach_listen_again_v1(text, text)",
                      "public.mark_coach_listen_again_heard_v1(text, text)")
        for role in ("anon", "authenticated"):
            if not _role_exists(cur, role):
                continue
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                cur.execute("SELECT has_table_privilege(%s, 'public.coach_listen_again_requests', %s)",
                            (role, privilege))
                assert cur.fetchone()[0] is False, (role, privilege)
            for signature in signatures:
                cur.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, signature))
                assert cur.fetchone()[0] is False, (role, signature)
        cur.execute("SELECT count(*) FROM pg_class c, aclexplode(c.relacl) a "
                    "WHERE c.oid = 'public.coach_listen_again_requests'::regclass AND a.grantee = 0")
        assert cur.fetchone()[0] == 0
        for signature in signatures:
            cur.execute("SELECT count(*) FROM pg_proc p, aclexplode(p.proacl) a "
                        "WHERE p.oid = %s::regprocedure AND a.grantee = 0", (signature,))
            assert cur.fetchone()[0] == 0, signature
        if _role_exists(cur, "service_role"):
            for privilege, expected in (("SELECT", True), ("DELETE", True),
                                        ("INSERT", False), ("UPDATE", False)):
                cur.execute("SELECT has_table_privilege('service_role', "
                            "'public.coach_listen_again_requests', %s)", (privilege,))
                assert cur.fetchone()[0] is expected, privilege
            for signature in signatures:
                cur.execute("SELECT has_function_privilege('service_role', %s, 'EXECUTE')",
                            (signature,))
                assert cur.fetchone()[0] is True, signature


def test_applied_again_the_file_changes_nothing(db):
    take, snippet, coach = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    with db.cursor() as cur:
        _label(cur, snippet, coach)
        assert _flag(cur, take, snippet) == 1
        before = _asks(cur, snippet)
        cur.execute("SELECT count(*) FROM public.coach_listen_again_requests")
        rows_before = cur.fetchone()[0]
        cur.execute(MIGRATION.read_text())
        cur.execute("SELECT count(*) FROM public.coach_listen_again_requests")
        assert cur.fetchone()[0] == rows_before
        assert _asks(cur, snippet) == before


def test_the_flag_asks_every_coach_of_record_once_and_only_them(db):
    take, snippet = str(uuid.uuid4()), str(uuid.uuid4())
    coach_a, coach_b = sorted(str(uuid.uuid4()) for _ in range(2))
    with db.cursor() as cur:
        _label(cur, snippet, coach_a, value="yes")
        _label(cur, snippet, coach_b, value="not_sure")
        # Never asked: the speaker on their own clip, a peer, an Audio-unclear
        # abstention, an anonymous row.
        _label(cur, snippet, str(uuid.uuid4()), value="yes", self_report=True)
        _label(cur, snippet, str(uuid.uuid4()), value="yes", lane="game_peer")
        _label(cur, snippet, str(uuid.uuid4()), value="audio_unclear", unrateable=True)
        cur.execute("INSERT INTO public.confidence_labels (snippet_id, rater_id, source, "
                    "confident, state_id, value, lane) VALUES (%s, NULL, 'coach', true, "
                    "'confidence', 'yes', 'coach')", (snippet,))
        assert _flag(cur, take, snippet) == 2
        assert _asks(cur, snippet) == [(coach_a, "P26c-A", True), (coach_b, "P26c-A", True)]
        # Flagged again while both are open: nothing new.
        assert _flag(cur, take, snippet) == 0
        assert len(_asks(cur, snippet)) == 2
        # A clip nobody judged yet: nothing to add (it is still in the queue).
        assert _flag(cur, take, str(uuid.uuid4())) == 0


def test_the_line_rotates_per_coach_and_a_heard_ask_stays_as_history(db):
    coach = str(uuid.uuid4())
    take = str(uuid.uuid4())
    snippets = [str(uuid.uuid4()) for _ in range(4)]
    with db.cursor() as cur:
        for snippet in snippets:
            _label(cur, snippet, coach)
            assert _flag(cur, take, snippet) == 1
        cur.execute("SELECT line_key FROM public.coach_listen_again_requests "
                    "WHERE coach_id = %s ORDER BY requested_at", (coach,))
        assert [r[0] for r in cur.fetchall()] == ["P26c-A", "P26c-B", "P26c-C", "P26c-A"]
        # The new blind answer closes the open ask; closing again closes none.
        assert _heard(cur, snippets[0], coach) == 1
        assert _heard(cur, snippets[0], coach) == 0
        assert _asks(cur, snippets[0]) == [(coach, "P26c-A", False)]
        # A later disagreement opens a new ask; the heard one stays.
        assert _flag(cur, take, snippets[0]) == 1
        asks = _asks(cur, snippets[0])
        assert len(asks) == 2 and [a[2] for a in asks] == [False, True]
        assert asks[1][1] == "P26c-B"  # the rotation counts every ask so far
        cur.execute("SELECT count(*) FROM public.coach_listen_again_requests "
                    "WHERE coach_id = %s AND heard_at IS NULL", (coach,))
        assert cur.fetchone()[0] == 4
        # One open ask per moment and coach is the table's own key.
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("INSERT INTO public.coach_listen_again_requests (take_session_id, "
                        "snippet_id, coach_id, line_key) VALUES (%s, %s, %s, 'P26c-C')",
                        (take, snippets[0], coach))
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.coach_listen_again_requests (take_session_id, "
                        "snippet_id, coach_id, line_key) VALUES (%s, %s, %s, 'because')",
                        (take, str(uuid.uuid4()), coach))


def test_bad_input_is_refused_by_name(db):
    with db.cursor() as cur:
        for take, snippet in (("", str(uuid.uuid4())), (str(uuid.uuid4()), ""),
                              (str(uuid.uuid4()), "not-a-uuid"), (None, str(uuid.uuid4()))):
            with pytest.raises(psycopg2.errors.RaiseException, match="COACH_LISTEN_AGAIN_INPUT_INVALID"):
                cur.execute("SELECT public.request_coach_listen_again_v1(%s, %s)", (take, snippet))
        with pytest.raises(psycopg2.errors.RaiseException, match="COACH_LISTEN_AGAIN_INPUT_INVALID"):
            cur.execute("SELECT public.mark_coach_listen_again_heard_v1('', 'c')")


def test_service_role_calls_the_functions_and_cannot_write_by_hand(db):
    with db.cursor() as cur:
        if not _role_exists(cur, "service_role"):
            pytest.skip("no service_role on this cluster")
    take, snippet, coach = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    with db.cursor() as cur:
        _label(cur, snippet, coach)
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SET ROLE service_role")
            assert _flag(cur, take, snippet) == 1
            cur.execute("SELECT line_key FROM public.coach_listen_again_requests "
                        "WHERE snippet_id = %s AND coach_id = %s AND heard_at IS NULL",
                        (snippet, coach))
            assert cur.fetchone() == ("P26c-A",)
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("INSERT INTO public.coach_listen_again_requests (take_session_id, "
                            "snippet_id, coach_id, line_key) VALUES (%s, %s, 'x', 'P26c-A')",
                            (take, str(uuid.uuid4())))
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("UPDATE public.coach_listen_again_requests SET heard_at = now() "
                            "WHERE snippet_id = %s", (snippet,))
            assert _heard(cur, snippet, coach) == 1
            cur.execute("DELETE FROM public.coach_listen_again_requests WHERE snippet_id = %s",
                        (snippet,))
            cur.execute("SELECT count(*) FROM public.coach_listen_again_requests "
                        "WHERE snippet_id = %s", (snippet,))
            assert cur.fetchone() == (0,)
    finally:
        conn.close()
