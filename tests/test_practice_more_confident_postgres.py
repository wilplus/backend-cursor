"""Did the coach-judged practice attempt sound more confident? (0388)

On a disposable database. Pins the rule exercise-more-confident-v1: helped
only when the attempt's confidence composite is higher than the original's
AND the coach said Yes; either No is not_helped; a missing score or a missing
coach answer is pending. Also: one row per practice, recomputed in place when
the coach revises; it goes with its practice; it can never be a label or reach
a user; browser roles reach nothing.
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


def _practice(db, original, attempt, coach, before="no"):
    """A practice whose coach rated the original `before` (blind) and the
    attempt `coach`. before=None: no blind rating; "unrateable": abstained."""
    practice_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
    snippet, rater = str(uuid.uuid4()), str(uuid.uuid4())
    snapshot = {} if original is None else {"confidence": original}
    metrics = {} if attempt is None else {"confidence": attempt}
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO public.confident_voice_practice "
            "(id, owner_user_id, take_session_id, acoustic_evidence, snippet_id) "
            "VALUES (%s, gen_random_uuid(), gen_random_uuid(), %s, %s)",
            (practice_id, psycopg2.extras.Json({"snapshot": snapshot}), snippet))
        cur.execute(
            "INSERT INTO public.confident_voice_practice_attempt "
            "(id, practice_id, acoustic_metrics, coach_confidence_decision, "
            "coach_confidence_decided_by) VALUES (%s, %s, %s, %s, %s)",
            (attempt_id, practice_id, psycopg2.extras.Json(metrics), coach, rater))
        if before is not None:
            cur.execute(
                "INSERT INTO public.confidence_labels "
                "(snippet_id, rater_id, value, unrateable) VALUES (%s, %s, %s, %s)",
                (snippet, rater, None if before == "unrateable" else before,
                 before == "unrateable"))
    return practice_id, attempt_id


def _record(db, practice_id, attempt_id):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM public.record_practice_more_confident_v1(%s, %s)",
                    (practice_id, attempt_id))
        return dict(cur.fetchone())


def test_it_can_never_be_a_label_or_serve_a_user(db):
    practice_id, attempt_id = _practice(db, 0.1, 0.2, "yes")
    _record(db, practice_id, attempt_id)
    for column in ("is_label", "serves_user"):
        with pytest.raises(psycopg2.Error):
            with db.cursor() as cur:
                cur.execute(f"UPDATE public.practice_more_confident_outcomes "
                            f"SET {column} = true WHERE practice_id = %s",
                            (practice_id,))
