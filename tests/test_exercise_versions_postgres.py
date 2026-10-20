"""
STORY    As a coach, I want each exercise version stored once and unchangeable,
         so that a speaker's practice always points at the exact text and
         video they saw.
OUTCOME
  O1  A re-record returns the first row unchanged; a new version gets its
      own row.
  O2  Only the transcript may arrive later, exactly once; any other change
      to a stored version is refused.
  O3  Browser roles reach neither the table nor the writer functions.
PROVES   O1 -> test_a_version_is_written_once_with_the_three_texts_and_the_lineage
         O2 -> test_only_the_transcript_arrives_later_and_only_once
         O3 -> test_browser_roles_reach_nothing
WHY      Founder 2026-09-29, decision 4 (0399).
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


def _transcript(db, exercise, version, status, transcript):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM public.set_exercise_version_transcript_v1("
                    "%s, %s, %s, %s::jsonb, 'en')",
                    (exercise, version, status,
                     None if transcript is None else psycopg2.extras.Json(transcript)))
        return dict(cur.fetchone())


def test_only_the_transcript_arrives_later_and_only_once(db):
    exercise = f"ex-{uuid.uuid4().hex[:8]}"
    first = _record(db, _row(exercise))
    done = _transcript(db, exercise, 1, "done", {"text": "Say the last word."})
    assert done["id"] == first["id"]
    assert (done["transcript_status"], done["transcript"]) == (
        "done", {"text": "Say the last word."})
    assert done["title"] == first["title"]
    with pytest.raises(psycopg2.Error, match="EXERCISE_VERSION_NOT_PENDING"):
        _transcript(db, exercise, 1, "done", {"text": "Something else."})
    with db.cursor() as cur:
        with pytest.raises(psycopg2.Error, match="EXERCISE_VERSION_IMMUTABLE"):
            cur.execute("UPDATE public.diagnostic_exercise_version "
                        "SET title = 'Changed' WHERE id = %s", (first["id"],))


def test_browser_roles_reach_nothing(db):
    functions = ("public.record_exercise_version_v1(jsonb)",
                 "public.set_exercise_version_transcript_v1("
                 "text, integer, text, jsonb, text)")
    with db.cursor() as cur:
        for role in ("anon", "authenticated"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                cur.execute("SELECT has_table_privilege(%s, "
                            "'public.diagnostic_exercise_version', %s)",
                            (role, privilege))
                assert cur.fetchone()[0] is False, (role, privilege)
            for function in functions:
                cur.execute("SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                            (role, function))
                assert cur.fetchone()[0] is False, (role, function)
