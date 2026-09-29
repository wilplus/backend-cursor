"""0390 on a disposable database: the coach's answer on a practice recording
takes the speaker's five values and nothing else."""
from __future__ import annotations

import os
import uuid

import psycopg2
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


def _attempt(db):
    practice, attempt = str(uuid.uuid4()), str(uuid.uuid4())
    with db.cursor() as cur:
        cur.execute("INSERT INTO public.confident_voice_practice "
                    "(id, owner_user_id, take_session_id) "
                    "VALUES (%s, gen_random_uuid(), gen_random_uuid())", (practice,))
        cur.execute("INSERT INTO public.confident_voice_practice_attempt "
                    "(id, practice_id) VALUES (%s, %s)", (attempt, practice))
    return attempt


@pytest.mark.parametrize("answer",
                         ["yes", "in_between", "no", "not_sure", "audio_unclear"])
def test_the_five_answers_are_accepted(db, answer):
    attempt = _attempt(db)
    with db.cursor() as cur:
        cur.execute("UPDATE public.confident_voice_practice_attempt "
                    "SET coach_confidence_decision = %s WHERE id = %s",
                    (answer, attempt))
        cur.execute("SELECT coach_confidence_decision FROM "
                    "public.confident_voice_practice_attempt WHERE id = %s", (attempt,))
        assert cur.fetchone()[0] == answer


def test_anything_else_is_refused(db):
    attempt = _attempt(db)
    with pytest.raises(psycopg2.Error):
        with db.cursor() as cur:
            cur.execute("UPDATE public.confident_voice_practice_attempt "
                        "SET coach_confidence_decision = 'maybe' WHERE id = %s",
                        (attempt,))
