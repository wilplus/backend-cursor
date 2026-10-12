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
