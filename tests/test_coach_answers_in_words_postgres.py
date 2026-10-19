"""A coach answers in words too, executed on a disposable database (0402).
Founder 2026-09-30, C2 to C5. Pins:
  * resolve_exercise_coach_request_v2 records a line or a clearer version
    with its answer, once, and shares it like an exercise;
  * words and an exercise never mix on one resolution; no_safe_match takes
    neither; v1 still resolves an exercise as before;
  * feedback_pairs keeps only a differing (draft, final) with its coach, one
    per (surface, request), and reaches no browser role;
  * coach_moment_error_event takes a naming keyed by the moment alone;
  * a Take word is a pair's home (0477, N79): one current pair per word and
    kind, the latest version supersedes the older, the same words again
    change nothing, and the migration recovers each word's pair once.
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


def _row(db, sql, args=()):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, args)
        got = cur.fetchone()
        return dict(got) if got else None


def _request(db):
    return _row(db,
                "SELECT * FROM public.request_exercise_from_coach_v1("
                "%s, %s, %s, 'nothing_spotted', 'near_confident', "
                "%s::text[], %s::jsonb)",
                (str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()),
                 [], psycopg2.extras.Json({"signals": {}})))


def _resolve_v2(db, request_id, resolution, *, exercise_id=None, version=None,
                share=False, answer=None):
    return _row(db,
                "SELECT * FROM public.resolve_exercise_coach_request_v2("
                "%s, 'coach-1', %s, %s, %s, %s, %s)",
                (request_id, resolution, exercise_id, version, share, answer))


def _refused(db, code, fn, *args, **kwargs):
    with pytest.raises(psycopg2.Error) as caught:
        fn(db, *args, **kwargs)
    assert code in str(caught.value)


def test_a_line_is_answered_once_and_shared(db):
    req = _request(db)
    done = _resolve_v2(db, req["id"], "line_written",
                       answer="  You let the number land.  ", share=True)
    assert done["resolution"] == "line_written"
    assert done["answer_text"] == "You let the number land."
    assert done["resolved_exercise_id"] is None
    assert done["shared_at"] is not None
    again = _resolve_v2(db, req["id"], "line_written",
                        answer="You let the number land.")
    assert again["shared_at"] == done["shared_at"]
    _refused(db, "EXERCISE_COACH_REQUEST_ALREADY_RESOLVED", _resolve_v2,
             req["id"], "line_written", answer="Different words.")
    _refused(db, "EXERCISE_COACH_REQUEST_ALREADY_RESOLVED", _resolve_v2,
             req["id"], "version_written", answer="You let the number land.")


def _word_pair(db, word, final, *, draft="Slow down.", kind="final", surface="coach_take_word"):
    return _row(db, "SELECT * FROM public.record_take_word_pair_v1(%s::jsonb)",
                (psycopg2.extras.Json({
                    "surface": surface, "final_kind": kind, "take_word_id": word,
                    "draft_text": draft, "final_text": final, "coach_id": "coach-1",
                    "take_session_id": str(uuid.uuid4())}),))


def _current(db, word):
    return _row(db, "SELECT count(*) FILTER (WHERE superseded_at IS NULL) AS current, "
                    "count(*) AS kept FROM public.feedback_pairs WHERE take_word_id = %s",
                (word,))


def test_a_take_word_pair_is_kept_and_the_latest_teaches(db):
    word = str(uuid.uuid4())
    first = _word_pair(db, word, "Slow down at the number.")
    assert first["take_word_id"] == word and first["superseded_at"] is None
    # The same words saved again change nothing.
    assert _word_pair(db, word, "Slow  down at the number. ")["id"] == first["id"]
    assert _current(db, word) == {"current": 1, "kept": 1}
    # An edit supersedes; nothing is deleted.
    latest = _word_pair(db, word, "Pause before the number.")
    assert latest["id"] != first["id"]
    assert _current(db, word) == {"current": 1, "kept": 2}
    assert _row(db, "SELECT superseded_at FROM public.feedback_pairs WHERE id = %s",
                (first["id"],))["superseded_at"] is not None
    # The video's transcript is its own current pair.
    _word_pair(db, word, "Pause, then the number.", kind="transcript")
    assert _current(db, word) == {"current": 2, "kept": 3}
    # Only the Take-word surface takes a Take word as its home, and never none.
    _refused(db, "TAKE_WORD_PAIR_INPUT_INVALID", _word_pair, word, "x", surface="praise_line")
    with pytest.raises(psycopg2.errors.CheckViolation):
        with db.cursor() as cur:
            cur.execute("INSERT INTO public.feedback_pairs (surface, draft_text, final_text, "
                        "coach_id) VALUES ('coach_take_word', 'a', 'b', 'coach-1')")
    for role in ("anon", "authenticated"):
        if _row(db, "SELECT 1 AS yes FROM pg_roles WHERE rolname = %s", (role,)):
            assert _row(db, "SELECT has_function_privilege(%s, "
                            "'public.record_take_word_pair_v1(jsonb)', 'EXECUTE') AS can",
                        (role,))["can"] is False


def test_the_migration_recovers_each_word_s_pair_once(db):
    user = str(uuid.uuid4())
    principal = _row(db, "INSERT INTO public.owner_principals (id, user_id) "
                         "VALUES (gen_random_uuid(), %s) RETURNING id", (user,))["id"]
    take = str(uuid.uuid4())
    with db.cursor() as cur:
        cur.execute("INSERT INTO public.v2_sessions (id, arc_id, user_id, take_index) "
                    "VALUES (%s, 'arc-w', %s, 1)", (take, user))
        prompt = psycopg2.extras.Json({"passage_text": "the words spoken here",
                                       "prompt_context": {"prompt": "coach_word_drafts"}})
        # Drafted, then edited: recovered. Written, then drafted: not.
        for coach, drafted, written in (("coach-a", "now() - interval '2 min'", "now()"),
                                        ("coach-b", "now()", "now() - interval '2 min'")):
            cur.execute(
                "INSERT INTO public.coach_take_words (take_session_id, coach_id, text, "
                "draft_text, draft_prompt, drafted_at, updated_at) "
                f"VALUES (%s, %s, 'Pause before the number.', 'Slow down.', %s, "
                f"{drafted}, {written})", (take, coach, prompt))
    sql = (pathlib.Path(__file__).resolve().parents[1]
           / "migrations/a_take_word_pair_has_a_home.sql").read_text()
    body = "\n".join(line for line in sql.splitlines()
                     if line.strip() not in ("BEGIN;", "COMMIT;"))
    with db.cursor() as cur:
        cur.execute(body)
        cur.execute(body)
    rows = []
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT coach_id, final_kind, owner_principal_id, consent_state, "
                    "releasable, passage_text FROM public.feedback_pairs "
                    "WHERE take_session_id = %s", (take,))
        rows = [dict(r) for r in cur.fetchall()]
    assert rows == [{"coach_id": "coach-a", "final_kind": "final",
                     "owner_principal_id": principal, "consent_state": "unknown",
                     "releasable": False, "passage_text": "the words spoken here"}]

