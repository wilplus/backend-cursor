"""
STORY    As a coach, I want my answer on a practice recording limited to the
         speaker's five values, so that coach and speaker answers can be
         compared.
OUTCOME
  O1  yes, in_between, no, not_sure and audio_unclear are stored.
  O2  Any other value (e.g. "maybe") is refused and the stored answer stays.
PROVES   O1 -> test_the_five_answers_are_accepted
         O2 -> test_any_other_answer_is_refused
WHY      Migration 0390. Runs only on a disposable database whose name starts
         with willab_confident_moment_.
"""
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


def test_any_other_answer_is_refused(db):
    attempt = _attempt(db)
    with db.cursor() as cur:
        cur.execute("UPDATE public.confident_voice_practice_attempt "
                    "SET coach_confidence_decision = 'yes' WHERE id = %s", (attempt,))
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("UPDATE public.confident_voice_practice_attempt "
                        "SET coach_confidence_decision = 'maybe' WHERE id = %s", (attempt,))
        cur.execute("SELECT coach_confidence_decision FROM "
                    "public.confident_voice_practice_attempt WHERE id = %s", (attempt,))
        assert cur.fetchone()[0] == "yes"
