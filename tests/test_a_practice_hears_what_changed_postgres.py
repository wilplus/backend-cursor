"""A practice hears what changed, on a disposable database (0409, F5).

Pins: the column exists and is nullable; the three tables exist with their
checks and the once-per-Take key; the migration is idempotent (the
rehearsal applies it twice).
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


def _columns(db, table):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s", (table,))
        return {r["column_name"]: r for r in cur.fetchall()}


def test_the_practice_keeps_what_it_heard(db):
    cols = _columns(db, "confident_voice_practice")
    assert (cols["after_practice"]["data_type"], cols["after_practice"]["is_nullable"]) == ("jsonb", "YES")


def test_the_three_tables_exist_with_their_rules(db):
    assert {"coach_id", "passage", "media_url", "media_kind", "published_at"} <= set(_columns(db, "coach_readings"))
    assert {"take_session_id", "step", "shown_at"} <= set(_columns(db, "after_practice_steps"))
    assert {"take_session_id", "clip_kind", "clip_id"} <= set(_columns(db, "bold_voices_plays"))
    take = f"take-{uuid.uuid4().hex[:8]}"
    with db.cursor() as cur:
        cur.execute("INSERT INTO public.after_practice_steps (owner_user_id, take_session_id, step) "
                    "VALUES ('o', %s, 'bold_voices')", (take,))
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("INSERT INTO public.after_practice_steps (owner_user_id, take_session_id, step) "
                        "VALUES ('o', %s, 'bold_voices')", (take,))
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.after_practice_steps (owner_user_id, take_session_id, step) "
                        "VALUES ('o', %s, 'encore')", (take,))
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.coach_readings (coach_id, passage, media_url, media_kind) "
                        "VALUES ('c', 'x', 'https://m/x', 'text')")
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.bold_voices_plays (owner_user_id, take_session_id, clip_kind, clip_id) "
                        "VALUES ('o', %s, 'stranger', 'c')", (take,))
