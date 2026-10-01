"""The coach panel's learning additions, on a disposable database (0411:
1b, 7, 6a to 6d, 8, task 4). Pins: the four tables exist with their keys
and checks; the additive columns exist; the two widened checks take the
coach's word surfaces; a draft-only Take word row is allowed; the shadow
writer keeps its unit and stores the clip kind; the migration is idempotent
(applied twice by the rehearsal script)."""
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


def test_the_four_tables_exist(db):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name IN ("
                    "'coach_exercise_preference','coach_clip_exposures',"
                    "'error_presence_audit','coach_block_pick')")
        assert len(cur.fetchall()) == 4


def test_the_additive_columns_exist(db):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND ("
                    "(table_name = 'confidence_labels' AND column_name = 'blind') OR "
                    "(table_name = 'verbal_cue_shadow_observations' AND column_name = 'clip_kind') OR "
                    "(table_name = 'coach_take_words' AND column_name IN ('draft_text','transcript')) OR "
                    "(table_name = 'feedback_pairs' AND column_name = 'take_word_id'))")
        assert len(cur.fetchall()) == 5


def test_the_keys_and_checks_hold(db):
    coach, clip = f"c-{uuid.uuid4().hex[:8]}", f"clip-{uuid.uuid4().hex[:8]}"
    with db.cursor() as cur:
        cur.execute("INSERT INTO public.coach_clip_exposures (coach_id, clip_id, via) VALUES (%s, %s, 'moment_read')",
                    (coach, clip))
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("INSERT INTO public.coach_clip_exposures (coach_id, clip_id, via) VALUES (%s, %s, 'audit')",
                        (coach, clip))
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.coach_exercise_preference "
                        "(take_session_id, snippet_id, coach_id, served_exercise_id, draw, action) "
                        "VALUES ('t', 's', %s, 'ex', 'top', 'liked')", (coach,))
        cur.execute("INSERT INTO public.error_presence_audit "
                    "(coach_id, clip_id, error_id, fired_at_sampling, week) VALUES (%s, %s, 'rushing', true, '2026-W40')",
                    (coach, clip))
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("INSERT INTO public.error_presence_audit "
                        "(coach_id, clip_id, error_id, fired_at_sampling, week) VALUES (%s, %s, 'rushing', false, '2026-W41')",
                        (coach, clip))
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("UPDATE public.error_presence_audit SET answer = 'maybe' WHERE coach_id = %s", (coach,))
        cur.execute("INSERT INTO public.coach_block_pick "
                    "(coach_id, take_session_id, block_id, manager_pick_snippet_id, policy_version, week) "
                    "VALUES (%s, 't', 'b1', 's1', 'coach-block-pick-v1', '2026-W40')", (coach,))
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("INSERT INTO public.coach_block_pick "
                        "(coach_id, take_session_id, block_id, manager_pick_snippet_id, policy_version, week) "
                        "VALUES (%s, 't', 'b1', 's2', 'coach-block-pick-v1', '2026-W40')", (coach,))


def test_a_draft_only_take_word_row_is_allowed(db):
    take, coach = f"take-{uuid.uuid4().hex[:8]}", f"c-{uuid.uuid4().hex[:8]}"
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("INSERT INTO public.coach_take_words (take_session_id, coach_id, draft_text) "
                    "VALUES (%s, %s, 'a draft') RETURNING shared_at, text", (take, coach))
        row = cur.fetchone()
        assert row["shared_at"] is None and row["text"] is None
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.coach_take_words (take_session_id, coach_id) VALUES (%s, %s)",
                        (take + "x", coach))


def test_the_shadow_writer_stores_the_clip_kind(db):
    clip = f"att-{uuid.uuid4().hex[:8]}"
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT error_id FROM public.speaking_error WHERE status IN ('shadow','detected') LIMIT 1")
        found = cur.fetchone()
        if not found:
            pytest.skip("no measured error in this lane")
        rows = psycopg2.extras.Json([{
            "take_session_id": "t", "snippet_id": clip, "error_id": found["error_id"],
            "detector_version": "rules-v1", "language": "any", "fired": True,
            "measurements": {"wpm": 190}, "clip_kind": "practice_attempt",
        }])
        cur.execute("SELECT public.record_verbal_cue_shadow_v1(%s) AS n", (rows,))
        assert cur.fetchone()["n"] == 1
        cur.execute("SELECT public.record_verbal_cue_shadow_v1(%s) AS n", (rows,))
        assert cur.fetchone()["n"] == 0
        cur.execute("SELECT clip_kind FROM public.verbal_cue_shadow_observations WHERE snippet_id = %s", (clip,))
        assert cur.fetchone()["clip_kind"] == "practice_attempt"
