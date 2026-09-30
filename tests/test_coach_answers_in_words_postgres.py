"""A coach answers in words too, executed on a disposable database (0402).
Founder 2026-09-30, C2 to C5. Pins:
  * resolve_exercise_coach_request_v2 records a line or a clearer version
    with its answer, once, and shares it like an exercise;
  * words and an exercise never mix on one resolution; no_safe_match takes
    neither; v1 still resolves an exercise as before;
  * feedback_pairs keeps only a differing (draft, final) with its coach, one
    per (surface, request), and reaches no browser role;
  * coach_moment_error_event takes a naming keyed by the moment alone.
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


def test_words_and_exercises_never_mix(db):
    req = _request(db)
    _refused(db, "EXERCISE_COACH_REQUEST_INPUT_INVALID", _resolve_v2,
             req["id"], "version_written", answer=None)
    _refused(db, "EXERCISE_COACH_REQUEST_INPUT_INVALID", _resolve_v2,
             req["id"], "version_written", answer="   ")
    _refused(db, "EXERCISE_COACH_REQUEST_INPUT_INVALID", _resolve_v2,
             req["id"], "version_written", answer="Clear.", exercise_id="ex-1",
             version=1)
    _refused(db, "EXERCISE_COACH_REQUEST_INPUT_INVALID", _resolve_v2,
             req["id"], "exercise_chosen", exercise_id="ex-1", version=1,
             answer="Clear.")
    _refused(db, "EXERCISE_COACH_REQUEST_INPUT_INVALID", _resolve_v2,
             req["id"], "no_safe_match", answer="Clear.")
    assert _row(db, "SELECT resolution FROM public.exercise_coach_requests "
                    "WHERE id = %s", (req["id"],))["resolution"] is None
    done = _resolve_v2(db, req["id"], "exercise_chosen", exercise_id="ex-1",
                       version=1, share=True)
    assert done["answer_text"] is None and done["resolved_exercise_id"] == "ex-1"


def test_v1_still_resolves_an_exercise(db):
    req = _request(db)
    done = _row(db, "SELECT * FROM public.resolve_exercise_coach_request_v1("
                    "%s, 'coach-1', 'exercise_authored', 'ex-2', 1, false)",
                (req["id"],))
    assert done["resolution"] == "exercise_authored"
    assert done["answer_text"] is None


def test_the_draft_columns_take_a_kept_draft(db):
    req = _request(db)
    _row(db, "UPDATE public.exercise_coach_requests SET draft_surface = "
             "'praise_line', draft_text = 'x', draft_model_version = 'm', "
             "drafted_at = now() WHERE id = %s RETURNING id", (req["id"],))
    with pytest.raises(psycopg2.Error):
        _row(db, "UPDATE public.exercise_coach_requests SET draft_surface = "
                 "'score' WHERE id = %s RETURNING id", (req["id"],))


def test_pairs_keep_only_a_differing_final_once_per_request(db):
    req = _request(db)
    insert = ("INSERT INTO public.feedback_pairs (surface, draft_text, "
              "final_text, coach_id, request_id, take_session_id) "
              "VALUES (%s, %s, %s, 'coach-1', %s, %s) RETURNING id")
    first = _row(db, insert, ("praise_line", "You sounded sure.",
                              "You let the number land.", req["id"],
                              req["take_session_id"]))
    assert first["id"]
    with pytest.raises(psycopg2.Error):  # one per (surface, request)
        _row(db, insert, ("praise_line", "a", "b", req["id"],
                          req["take_session_id"]))
    with pytest.raises(psycopg2.Error):  # the final must differ
        _row(db, insert, ("clearer_version", "Same.", " Same. ", req["id"],
                          req["take_session_id"]))
    with pytest.raises(psycopg2.Error):  # no surface but the three
        _row(db, insert, ("moment_suggestion", "a", "b", req["id"],
                          req["take_session_id"]))
    with pytest.raises(psycopg2.Error):  # a pair has a home
        _row(db, "INSERT INTO public.feedback_pairs (surface, draft_text, "
                 "final_text, coach_id) VALUES ('praise_line', 'a', 'b', 'c') "
                 "RETURNING id")
    exercise = ("INSERT INTO public.feedback_pairs (surface, draft_text, "
                "final_text, final_kind, coach_id, exercise_id, "
                "exercise_version) VALUES ('exercise_script', 'a', %s, %s, "
                "'coach-1', %s, 2) RETURNING id")
    ex = f"ex-{uuid.uuid4()}"
    assert _row(db, exercise, ("b", "final", ex))["id"]
    assert _row(db, exercise, ("c", "transcript", ex))["id"]
    with pytest.raises(psycopg2.Error):  # one final of each kind per version
        _row(db, exercise, ("d", "final", ex))


def test_pairs_reach_no_browser_role(db):
    rls = _row(db, "SELECT relrowsecurity FROM pg_class WHERE oid = "
                   "'public.feedback_pairs'::regclass")
    assert rls["relrowsecurity"] is True
    for role in ("anon", "authenticated"):
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            granted = _row(db, "SELECT has_table_privilege(%s, "
                               "'public.feedback_pairs', %s) AS ok",
                           (role, privilege))["ok"]
            assert granted is False, (role, privilege)
        fn = _row(db, "SELECT has_function_privilege(%s, "
                      "'public.resolve_exercise_coach_request_v2(uuid, text, "
                      "text, text, integer, boolean, text)', 'EXECUTE') AS ok",
                  (role,))["ok"]
        assert fn is False, role


def test_an_error_can_be_named_on_the_moment_itself(db):
    if _row(db, "SELECT to_regclass('public.coach_moment_error_event') AS t")["t"] is None:
        pytest.skip("this lane carries no exercise library, so no error-event table")
    error_id = f"named-{uuid.uuid4().hex[:8]}"
    _row(db, "INSERT INTO public.speaking_error (error_id, label, definition, asks) "
             "VALUES (%s, 'Hedging', 'Softening a claim', 'Does the claim soften?') RETURNING error_id",
         (error_id,))
    snippet, take = str(uuid.uuid4()), str(uuid.uuid4())
    row = _row(db, "INSERT INTO public.coach_moment_error_event (practice_id, "
                   "error_id, coach_id, action, snippet_id, take_session_id) "
                   "VALUES (NULL, %s, NULL, 'named', %s, %s) RETURNING *",
               (error_id, snippet, take))
    assert row["practice_id"] is None and row["snippet_id"] == snippet
    with pytest.raises(psycopg2.Error):  # a practice or a moment, never neither
        _row(db, "INSERT INTO public.coach_moment_error_event (practice_id, "
                 "error_id, coach_id, action) VALUES (NULL, %s, NULL, 'named') "
                 "RETURNING id", (error_id,))
