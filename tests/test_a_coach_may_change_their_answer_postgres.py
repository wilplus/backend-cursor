"""A coach may change their answer, on a disposable database (0446; coach
panel lock flows 7 and 12; Q-B12 A, N62; build plan D-CP-7).

Pins:
  * the history table exists with RLS on; browser roles and PUBLIC hold
    nothing on it or on the v3 resolver; service_role reads and deletes the
    history, calls the resolver, and cannot write the history by hand;
  * the file applied again changes nothing; the guard trigger is v2;
  * the first answer is written as before; the same answer again is a no-op
    that may add the share; a DIFFERENT answer by the same coach replaces the
    row's answer, resets the share to this call's, and moves the old answer
    (words, exercise, video, share) into the history as version 1, 2, ...;
  * another coach's different answer is still ALREADY_RESOLVED;
  * the guard still refuses a hand UPDATE of a set resolution, a hand unset
    of a share, and any change to what was requested; the door is only the
    resolver's, in its own transaction;
  * a changed answer that goes from shared to unshared leaves shared_at NULL
    (a withdrawn share), and from words to an exercise respects the row's
    shape checks.
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
MIGRATION = ROOT / "migrations" / "a_coach_may_change_their_answer.sql"
HISTORY = "public.exercise_coach_request_answer_versions"
RESOLVER = "public.resolve_exercise_coach_request_v3(uuid, text, text, text, integer, boolean, text)"


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


def _row(db, sql, args):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, args)
        return dict(cur.fetchone())


def _request(db):
    return _row(db,
                "SELECT * FROM public.request_exercise_from_coach_v1("
                "%s, %s, %s, 'nothing_targets_it', 'near_confident', %s::text[], %s::jsonb)",
                (str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()), ["rushing"],
                 psycopg2.extras.Json({"signals": {"insufficient_pauses": True}})))


def _resolve(db, request_id, coach, resolution, *, exercise_id=None, version=None,
             share=False, text=None):
    return _row(db, f"SELECT * FROM {RESOLVER.split('(')[0]}(%s, %s, %s, %s, %s, %s, %s)",
                (request_id, coach, resolution, exercise_id, version, share, text))


def _history(db, request_id):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM {HISTORY} WHERE request_id = %s ORDER BY version",
                    (request_id,))
        return [dict(r) for r in cur.fetchall()]


def _role_exists(cur, role):
    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
    return cur.fetchone() is not None


def test_the_history_and_the_resolver_sit_behind_the_door_and_the_guard_is_v2(db):
    with db.cursor() as cur:
        cur.execute("SELECT relrowsecurity FROM pg_class "
                    "WHERE relname = 'exercise_coach_request_answer_versions'")
        assert cur.fetchone() == (True,)
        cur.execute("SELECT tgfoid::regproc::text FROM pg_trigger WHERE tgname = "
                    "'exercise_coach_request_guard' AND tgrelid = "
                    "'public.exercise_coach_requests'::regclass")
        assert cur.fetchone() == ("guard_exercise_coach_request_update_v2",)
        cur.execute("SELECT prosecdef, proconfig FROM pg_proc "
                    "WHERE proname = 'resolve_exercise_coach_request_v3'")
        secdef, config = cur.fetchone()
        assert secdef is True and any(c.startswith("search_path=") for c in (config or []))
        cur.execute(f"SELECT count(*) FROM pg_class c, aclexplode(c.relacl) a "
                    f"WHERE c.oid = '{HISTORY}'::regclass AND a.grantee = 0")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM pg_proc p, aclexplode(p.proacl) a "
                    "WHERE p.oid = %s::regprocedure AND a.grantee = 0", (RESOLVER,))
        assert cur.fetchone()[0] == 0
        for role in ("anon", "authenticated"):
            if not _role_exists(cur, role):
                continue
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                cur.execute("SELECT has_table_privilege(%s, %s, %s)", (role, HISTORY, privilege))
                assert cur.fetchone()[0] is False, (role, privilege)
            cur.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, RESOLVER))
            assert cur.fetchone()[0] is False, role
        if _role_exists(cur, "service_role"):
            for privilege, want in (("SELECT", True), ("DELETE", True),
                                    ("INSERT", False), ("UPDATE", False)):
                cur.execute("SELECT has_table_privilege('service_role', %s, %s)",
                            (HISTORY, privilege))
                assert cur.fetchone()[0] is want, privilege
            cur.execute("SELECT has_function_privilege('service_role', %s, 'EXECUTE')", (RESOLVER,))
            assert cur.fetchone()[0] is True


def test_applied_again_the_file_changes_nothing(db):
    request = _request(db)
    _resolve(db, request["id"], "coach-1", "line_written", text="Well said.")
    _resolve(db, request["id"], "coach-1", "note_written", text="A note.")
    before = (_history(db, request["id"]),
              _row(db, "SELECT * FROM public.exercise_coach_requests WHERE id = %s",
                   (request["id"],)))
    with db.cursor() as cur:
        cur.execute(MIGRATION.read_text())
    after = (_history(db, request["id"]),
             _row(db, "SELECT * FROM public.exercise_coach_requests WHERE id = %s",
                  (request["id"],)))
    assert after == before


def test_the_same_coach_changes_the_answer_and_every_earlier_one_stays(db):
    request = _request(db)
    first = _resolve(db, request["id"], "coach-1", "line_written", text="Well said.", share=True)
    assert (first["resolution"], first["answer_text"]) == ("line_written", "Well said.")
    assert first["shared_at"] is not None
    # The same answer again: nothing changes.
    again = _resolve(db, request["id"], "coach-1", "line_written", text="Well said.", share=True)
    assert (again["resolved_at"], again["shared_at"]) == (first["resolved_at"], first["shared_at"])
    assert _history(db, request["id"]) == []
    # The coach adds a video to the answer they have (the app's seam).
    with db.cursor() as cur:
        cur.execute("UPDATE public.exercise_coach_requests SET answer_video_ref = 'v/1.mp4' "
                    "WHERE id = %s", (request["id"],))
    # Q-B12 A: new words replace the card; the old answer, whole, is version 1.
    second = _resolve(db, request["id"], "coach-1", "version_written",
                      text="We think timing matters.", share=True)
    assert (second["resolution"], second["answer_text"]) == ("version_written",
                                                             "We think timing matters.")
    assert second["resolved_at"] > first["resolved_at"]
    assert second["shared_at"] is not None and second["shared_at"] > first["shared_at"]
    history = _history(db, request["id"])
    assert len(history) == 1
    old = history[0]
    assert (old["version"], old["resolution"], old["answer_text"], old["answer_video_ref"],
            old["resolved_by"], old["superseded_by"]) == (
        1, "line_written", "Well said.", "v/1.mp4", "coach-1", "coach-1")
    assert old["resolved_at"] == first["resolved_at"] and old["shared_at"] == first["shared_at"]
    assert (old["take_session_id"], old["snippet_id"]) == (request["take_session_id"],
                                                             request["snippet_id"])
    # Changed again, this time not shared: the share is withdrawn with the
    # answer it belonged to, and the card goes.
    third = _resolve(db, request["id"], "coach-1", "no_safe_match")
    assert third["resolution"] == "no_safe_match" and third["shared_at"] is None
    assert third["answer_text"] is None and third["resolved_exercise_id"] is None
    history = _history(db, request["id"])
    assert [h["version"] for h in history] == [1, 2]
    assert (history[1]["resolution"], history[1]["shared_at"] is not None) == ("version_written", True)
    # And to an exercise, shared: the row's shape checks hold through it.
    fourth = _resolve(db, request["id"], "coach-1", "exercise_chosen",
                      exercise_id="ex-1", version=2, share=True)
    assert (fourth["resolved_exercise_id"], fourth["resolved_exercise_version"]) == ("ex-1", 2)
    assert fourth["shared_at"] is not None and fourth["answer_text"] is None
    assert [h["version"] for h in _history(db, request["id"])] == [1, 2, 3]


def test_another_coach_s_different_answer_is_still_refused(db):
    request = _request(db)
    _resolve(db, request["id"], "coach-1", "line_written", text="Well said.")
    with pytest.raises(psycopg2.Error, match="ALREADY_RESOLVED"):
        _resolve(db, request["id"], "coach-2", "line_written", text="Other words.")
    with pytest.raises(psycopg2.Error, match="ALREADY_RESOLVED"):
        _resolve(db, request["id"], "coach-2", "no_safe_match")
    # The same answer by another coach is the same no-op as before, and may
    # carry the share (the words are the words).
    same = _resolve(db, request["id"], "coach-2", "line_written", text="Well said.", share=True)
    assert same["resolved_by"] == "coach-1" and same["shared_at"] is not None
    assert _history(db, request["id"]) == []


def test_the_guard_s_door_is_only_the_resolver_s(db):
    request = _request(db)
    _resolve(db, request["id"], "coach-1", "line_written", text="Well said.", share=True)
    with db.cursor() as cur:
        with pytest.raises(psycopg2.Error, match="ALREADY_RESOLVED"):
            cur.execute("UPDATE public.exercise_coach_requests SET resolution = 'note_written' "
                        "WHERE id = %s", (request["id"],))
        with pytest.raises(psycopg2.Error, match="ALREADY_SHARED"):
            cur.execute("UPDATE public.exercise_coach_requests SET shared_at = NULL "
                        "WHERE id = %s", (request["id"],))
        with pytest.raises(psycopg2.Error, match="IMMUTABLE"):
            cur.execute("UPDATE public.exercise_coach_requests SET reason = 'nothing_spotted' "
                        "WHERE id = %s", (request["id"],))
        # The setting outside the resolver's transaction opens nothing:
        # set_config(..., true) dies with the transaction that set it, and a
        # name that is not this row's id opens nothing either.
        cur.execute("SELECT set_config('willab.coach_answer_change', %s, false)",
                    (str(uuid.uuid4()),))
        with pytest.raises(psycopg2.Error, match="ALREADY_RESOLVED"):
            cur.execute("UPDATE public.exercise_coach_requests SET resolution = 'note_written' "
                        "WHERE id = %s", (request["id"],))
        cur.execute("SELECT set_config('willab.coach_answer_change', '', false)")
    # Nothing was written to the history by hand.
    assert _history(db, request["id"]) == []
    with db.cursor() as cur:
        with pytest.raises(psycopg2.Error, match="INPUT_INVALID"):
            cur.execute(f"SELECT {RESOLVER.split('(')[0]}(%s, 'coach-1', 'line_written', "
                        "NULL, NULL, false, NULL)", (request["id"],))
        with pytest.raises(psycopg2.Error, match="NOT_FOUND"):
            cur.execute(f"SELECT {RESOLVER.split('(')[0]}(%s, 'coach-1', 'no_safe_match', "
                        "NULL, NULL, false, NULL)", (str(uuid.uuid4()),))


def test_service_role_resolves_and_cannot_write_the_history_by_hand(db):
    with db.cursor() as cur:
        if not _role_exists(cur, "service_role"):
            pytest.skip("no service_role on this cluster")
    request = _request(db)
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SET ROLE service_role")
            cur.execute(f"SELECT * FROM {RESOLVER.split('(')[0]}(%s, 'coach-1', 'line_written', "
                        "NULL, NULL, true, 'Well said.')", (request["id"],))
            cur.execute(f"SELECT * FROM {RESOLVER.split('(')[0]}(%s, 'coach-1', 'note_written', "
                        "NULL, NULL, false, 'A note.')", (request["id"],))
            assert dict(cur.fetchone())["shared_at"] is None
            cur.execute(f"SELECT count(*) AS n FROM {HISTORY} WHERE request_id = %s", (request["id"],))
            assert cur.fetchone()["n"] == 1
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute(f"INSERT INTO {HISTORY} (request_id, take_session_id, snippet_id, "
                            "version, resolution, resolved_by, resolved_at, superseded_by) "
                            "VALUES (%s, 't', 's', 9, 'no_safe_match', 'c', now(), 'c')",
                            (request["id"],))
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute(f"UPDATE {HISTORY} SET answer_text = 'x' WHERE request_id = %s",
                            (request["id"],))
            cur.execute(f"DELETE FROM {HISTORY} WHERE request_id = %s", (request["id"],))
            cur.execute(f"SELECT count(*) AS n FROM {HISTORY} WHERE request_id = %s", (request["id"],))
            assert cur.fetchone()["n"] == 0
    finally:
        conn.close()
