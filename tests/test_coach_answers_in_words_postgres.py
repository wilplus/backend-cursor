"""
STORY    As a coach, I want to answer a speaker's request with a written line
         or clearer version, recorded once and shared, so that the speaker
         gets words from me.
OUTCOME
  O1  A line is recorded once, trimmed, and shared; the same answer again is
      a no-op; a different answer is refused (ALREADY_RESOLVED).
  O2  Words and an exercise never mix on one answer: either way round is
      refused (INPUT_INVALID) and the request stays unanswered.
  O3  feedback_pairs keeps a (draft, final) only when they differ, and one
      per (surface, request).
  O4  A Take word is a pair's home: one current pair per word and kind, the
      latest version supersedes the older (a version that is no pair
      retires it), the same words again write nothing, only the Take-word
      surface takes a word as its home, and no browser role may write one.
  O5  The migration recovers each word's pair once, only where the draft
      came before the final, with consent left closed.
  O6  Every draft keeps its prompt: the app keeps each draft in
      coach_draft_history and may only settle it afterwards, never rewrite
      what was drafted or sent; an answer draft hangs on its request; no
      browser role reaches the table.
PROVES   O1 -> test_a_line_is_answered_once_and_shared
         O2 -> test_words_and_an_exercise_never_mix
         O3 -> test_a_pair_is_kept_only_when_the_coach_changed_the_draft
         O4 -> test_a_take_word_pair_is_kept_and_the_latest_teaches
         O5 -> test_the_migration_recovers_each_word_s_pair_once
         O6 -> test_every_draft_is_kept_as_it_was_sent_and_only_settled
WHY      Migration 0402 (founder 2026-09-30, C2 to C5); O4 and O5 migration
         0478 (founder 2026-10-19, N79). Runs only on a disposable database
         whose name starts with willab_confident_moment_. O6 migration 0479
         (founder 2026-10-19, N79).
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


def test_words_and_an_exercise_never_mix(db):
    req = _request(db)
    _refused(db, "EXERCISE_COACH_REQUEST_INPUT_INVALID", _resolve_v2,
             req["id"], "line_written", answer="You let it land.",
             exercise_id="ex-1", version=1)
    _refused(db, "EXERCISE_COACH_REQUEST_INPUT_INVALID", _resolve_v2,
             req["id"], "exercise_chosen", answer="You let it land.",
             exercise_id="ex-1", version=1)
    still = _row(db, "SELECT resolution, answer_text, resolved_exercise_id "
                     "FROM public.exercise_coach_requests WHERE id = %s", (req["id"],))
    assert still == {"resolution": None, "answer_text": None, "resolved_exercise_id": None}


def _pair(db, request_id, draft, final):
    return _row(db, "INSERT INTO public.feedback_pairs "
                    "(surface, draft_text, final_text, coach_id, request_id) "
                    "VALUES ('clearer_version', %s, %s, 'coach-1', %s) RETURNING id",
                (draft, final, request_id))


def test_a_pair_is_kept_only_when_the_coach_changed_the_draft(db):
    req = _request(db)
    with pytest.raises(psycopg2.errors.CheckViolation):
        _pair(db, req["id"], "Say it slower.", "  Say it slower. ")
    assert _pair(db, req["id"], "Say it slower.", "Let the number land.")["id"]
    with pytest.raises(psycopg2.errors.UniqueViolation):
        _pair(db, req["id"], "Say it slower.", "Another final.")
    pairs = _row(db, "SELECT count(*) AS n FROM public.feedback_pairs "
                     "WHERE request_id = %s", (req["id"],))
    assert pairs["n"] == 1


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
    # The same words saved again write nothing new.
    assert _word_pair(db, word, "Slow  down at the number. ")["id"] is None
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
    # A latest version that is no pair (the draft kept as it was) retires the
    # older pair: an outdated version never keeps teaching.
    assert _word_pair(db, word, "Slow down.")["id"] is None
    assert _current(db, word) == {"current": 1, "kept": 3}
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


DRAFTS = "public.coach_draft_history"


def _keep_draft(cur, request_id, take, **over):
    """As services.db.insert_coach_draft writes it, as service_role."""
    row = {"surface": "praise_line", "prompt_family": "coach_answer_drafts",
           "coach_id": "coach-1", "owner_user_id": "speaker-1", "take_session_id": take,
           "request_id": request_id, "draft_text": "You let the number land.",
           "prompt_sha256": "a" * 64,
           "prompt_inputs": psycopg2.extras.Json({"passage_text": "and that is why",
                                                  "kind": "praise", "spotted": ["Rushing"],
                                                  "spotted_tags": ["rushing"], "notes": None}),
           **over}
    cur.execute(f"INSERT INTO {DRAFTS} ({', '.join(row)}) "
                f"VALUES ({', '.join(['%s'] * len(row))}) RETURNING id", tuple(row.values()))
    return cur.fetchone()[0]


def test_every_draft_is_kept_as_it_was_sent_and_only_settled(db):
    req = _request(db)
    take = req["take_session_id"]
    with db.cursor() as cur:
        cur.execute("SET ROLE service_role")
        try:
            first = _keep_draft(cur, req["id"], take)
            second = _keep_draft(cur, req["id"], take, draft_text="The pause worked.")
            # The coach saved the second as written: the one later write.
            cur.execute(f"UPDATE {DRAFTS} SET settled_at = now(), final_unchanged = true "
                        "WHERE id = %s", (second,))
            for column, value in (("draft_text", "rewritten"), ("prompt_sha256", "b" * 64),
                                  ("prompt_inputs", psycopg2.extras.Json({}))):
                with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                    cur.execute(f"UPDATE {DRAFTS} SET {column} = %s WHERE id = %s",
                                (value, first))
            # An answer draft hangs on its request; a Take word's on the Take.
            with pytest.raises(psycopg2.errors.CheckViolation):
                _keep_draft(cur, None, take)
            with pytest.raises(psycopg2.errors.CheckViolation):
                _keep_draft(cur, req["id"], take, surface="coach_take_word",
                            prompt_family="coach_word_drafts")
        finally:
            cur.execute("RESET ROLE")
    kept = []
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT id, draft_text, final_unchanged, settled_at IS NOT NULL AS settled "
                    f"FROM {DRAFTS} WHERE request_id = %s ORDER BY drafted_at, draft_text DESC",
                    (req["id"],))
        kept = [dict(r) for r in cur.fetchall()]
    assert [(k["draft_text"], k["settled"], k["final_unchanged"]) for k in kept] == [
        ("You let the number land.", False, None), ("The pause worked.", True, True)]
    assert _row(db, "SELECT relrowsecurity AS rls FROM pg_class WHERE oid = %s::regclass",
                (DRAFTS,))["rls"] is True
    for role in ("anon", "authenticated"):
        if _row(db, "SELECT 1 AS yes FROM pg_roles WHERE rolname = %s", (role,)):
            assert _row(db, "SELECT has_table_privilege(%s, %s, 'SELECT') AS can",
                        (role, DRAFTS))["can"] is False
