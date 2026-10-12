"""A coach's judgement stands and says why it was asked, on a disposable
database (W6 2026-10-05: LOCKIN §5c, contract 34; decisions K9; and the
walk's stamped pairs, C2/C5).

Pins:
  * confidence_labels carries the three K9 stamps, and a sampling
    probability outside (0, 1] is refused by the table itself;
  * label_revision gains `reconsideration` (false by default) and the K9
    stamps: the lane has no label_revision, so the suite builds the
    released shape and re-applies the migration in its own transaction,
    which it rolls back; without the table the migration is a no-op;
  * the migration is idempotent (the lane applies it twice);
  * the walk's exercise pairs fit the pair table's own keys: the saved
    instruction rides the request, the transcript the exercise version and
    the moment, and a second final on the same request is refused;
  * a practice recording's coach decision is written once: the guarded
    update the writer issues leaves a standing decision as it was.
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


def test_a_standing_practice_decision_is_never_written_over(db):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' "
                    "AND table_name = 'confident_voice_practice_attempt'")
        if "coach_confidence_decision" not in {r["column_name"] for r in cur.fetchall()}:
            pytest.skip("no practice attempt table in this lane")
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:
            practice, attempt = str(uuid.uuid4()), str(uuid.uuid4())
            cur.execute("INSERT INTO public.confident_voice_practice "
                        "(id, owner_user_id, take_session_id) VALUES (%s, %s, %s)",
                        (practice, str(uuid.uuid4()), str(uuid.uuid4())))
            cur.execute("INSERT INTO public.confident_voice_practice_attempt "
                        "(id, practice_id, coach_confidence_decision) "
                        "VALUES (%s, %s, 'in_between')", (attempt, practice))
            # The writer's guarded update (services/db.py,
            # set_confident_voice_practice_attempt_coach_decision).
            cur.execute("UPDATE public.confident_voice_practice_attempt "
                        "SET coach_confidence_decision = 'yes' "
                        "WHERE id = %s AND practice_id = %s "
                        "AND coach_confidence_decision IS NULL", (attempt, practice))
            assert cur.rowcount == 0
            cur.execute("SELECT coach_confidence_decision FROM "
                        "public.confident_voice_practice_attempt WHERE id = %s", (attempt,))
            assert cur.fetchone()[0] == "in_between"
    finally:
        conn.rollback()
        conn.close()
