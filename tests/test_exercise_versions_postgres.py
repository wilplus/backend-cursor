"""0399 on a disposable database: a version row is written once, is
immutable but for its transcript's one arrival, and browser roles reach
nothing.

Founder 2026-09-29, decision 4. The target must be a disposable local
database whose name starts with ``willab_confident_moment_``.
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


def _row(exercise_id, version=1, **over):
    base = {"exercise_id": exercise_id, "version": version,
            "title": "Land the ending", "instruction": "Say the last word fully.",
            "acoustic_problem_tags": ["ending_compression"],
            "supported_confidence_patterns": ["near_confident"],
            "matching_criteria": {"primary_problem_tag": "ending_compression"},
            "ai_draft_text": "First draft.", "explanation_video_url": "https://cdn/x.mp4",
            "video_sha256": "a" * 64, "video_bytes": 1234,
            "transcript_status": "pending", "source": "coach_panel",
            "created_by": "coach-1"}
    base.update(over)
    return base


def _record(db, row):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM public.record_exercise_version_v1(%s::jsonb)",
                    (psycopg2.extras.Json(row),))
        return dict(cur.fetchone())


def _settle(db, exercise_id, version, status, transcript=None, language=None):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM public.set_exercise_version_transcript_v1(%s, %s, %s, %s, %s)",
            (exercise_id, version, status,
             psycopg2.extras.Json(transcript) if transcript is not None else None,
             language))
        return dict(cur.fetchone())


def test_a_version_is_written_once_with_the_three_texts_and_the_lineage(db):
    exercise = f"ex-{uuid.uuid4().hex[:8]}"
    first = _record(db, _row(exercise))
    again = _record(db, _row(exercise, title="Changed"))
    assert first["id"] == again["id"]
    assert again["title"] == "Land the ending"
    assert first["ai_draft_text"] == "First draft."
    assert first["acoustic_problem_tags"] == ["ending_compression"]
    assert first["matching_criteria"] == {"primary_problem_tag": "ending_compression"}
    assert first["video_sha256"] == "a" * 64 and first["video_bytes"] == 1234
    assert first["transcript_status"] == "pending" and first["transcript"] is None
    assert first["source"] == "coach_panel" and first["created_by"] == "coach-1"
    second = _record(db, _row(exercise, version=2, instruction="Slower."))
    assert second["version"] == 2 and second["id"] != first["id"]


@pytest.mark.parametrize("bad", [
    {"version": 1, "title": "x", "source": "cms"},
    {"exercise_id": "e", "title": "x", "source": "cms"},
    {"exercise_id": "e", "version": 1, "source": "cms"},
    {"exercise_id": "e", "version": 1, "title": "x"},
    {"exercise_id": "e", "version": 1, "title": "x", "source": "elsewhere"},
    {"exercise_id": "e", "version": 0, "title": "x", "source": "cms"},
    {"exercise_id": "e", "version": 1, "title": "x", "source": "cms",
     "transcript_status": "maybe"},
])
def test_an_incomplete_or_unknown_row_is_refused(db, bad):
    with pytest.raises(psycopg2.Error):
        _record(db, bad)


def test_the_transcript_arrives_once_and_the_row_is_otherwise_immutable(db):
    exercise = f"ex-{uuid.uuid4().hex[:8]}"
    _record(db, _row(exercise))
    settled = _settle(db, exercise, 1, "done", {"transcript": "Land it.", "words": []}, "en")
    assert settled["transcript_status"] == "done"
    assert settled["transcript"]["transcript"] == "Land it."
    assert settled["transcript_language"] == "en"
    with pytest.raises(psycopg2.Error, match="EXERCISE_VERSION_NOT_PENDING"):
        _settle(db, exercise, 1, "failed")
    with pytest.raises(psycopg2.Error, match="EXERCISE_VERSION_NOT_PENDING"):
        _settle(db, exercise, 9, "failed")
    with db.cursor() as cur:
        with pytest.raises(psycopg2.Error, match="EXERCISE_VERSION_IMMUTABLE"):
            cur.execute("UPDATE public.diagnostic_exercise_version SET title = 'x' "
                        "WHERE exercise_id = %s", (exercise,))
        with pytest.raises(psycopg2.Error, match="EXERCISE_VERSION_IMMUTABLE"):
            cur.execute("UPDATE public.diagnostic_exercise_version "
                        "SET transcript_status = 'pending' WHERE exercise_id = %s",
                        (exercise,))


def test_a_missing_authorization_or_a_failure_settles_without_a_transcript(db):
    for status in ("coach_authorization_missing", "failed"):
        exercise = f"ex-{uuid.uuid4().hex[:8]}"
        _record(db, _row(exercise))
        settled = _settle(db, exercise, 1, status)
        assert settled["transcript_status"] == status
        assert settled["transcript"] is None
    exercise = f"ex-{uuid.uuid4().hex[:8]}"
    _record(db, _row(exercise))
    with pytest.raises(psycopg2.Error, match="EXERCISE_VERSION_INPUT_INVALID"):
        _settle(db, exercise, 1, "done")                       # done needs a transcript
    with pytest.raises(psycopg2.Error, match="EXERCISE_VERSION_INPUT_INVALID"):
        _settle(db, exercise, 1, "failed", {"transcript": "x"})  # failed carries none


def test_a_version_not_waiting_for_a_transcript_is_never_updated(db):
    exercise = f"ex-{uuid.uuid4().hex[:8]}"
    _record(db, _row(exercise, transcript_status="not_requested"))
    with pytest.raises(psycopg2.Error, match="EXERCISE_VERSION_NOT_PENDING"):
        _settle(db, exercise, 1, "done", {"transcript": "x"}, "en")


def test_who_may_do_what(db):
    with db.cursor() as cur:
        for role in ("anon", "authenticated"):
            cur.execute("SELECT has_table_privilege(%s, "
                        "'public.diagnostic_exercise_version', 'SELECT')", (role,))
            assert cur.fetchone()[0] is False
            cur.execute("SELECT has_function_privilege(%s, "
                        "'public.record_exercise_version_v1(jsonb)', 'EXECUTE')", (role,))
            assert cur.fetchone()[0] is False
        for privilege, expected in (("SELECT", True), ("DELETE", True),
                                    ("INSERT", False), ("UPDATE", False)):
            cur.execute("SELECT has_table_privilege('service_role', "
                        "'public.diagnostic_exercise_version', %s)", (privilege,))
            assert cur.fetchone()[0] is expected, privilege
