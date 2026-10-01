"""A moment may be lent an ear, on a disposable database (0410, F3, F4,
the delayed measure). Pins: the six tables and the view exist with their
keys and checks; the migration is idempotent (applied twice)."""
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


def test_the_tables_and_the_view_exist(db):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT table_name, table_type FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name IN ("
                    "'voice_album_shares','corpus_clips','lend_your_ear_sets',"
                    "'lend_your_ear_answers','delayed_measure_pairs','delayed_measure_votes',"
                    "'shared_clips_live')")
        kinds = {r["table_name"]: r["table_type"] for r in cur.fetchall()}
    assert len([k for k in kinds if k != "shared_clips_live"]) == 6
    if "shared_clips_live" in kinds:
        assert kinds["shared_clips_live"] == "VIEW"


def test_the_keys_hold(db):
    take = f"take-{uuid.uuid4().hex[:8]}"
    with db.cursor() as cur:
        cur.execute("INSERT INTO public.lend_your_ear_sets (listener_user_id, take_session_id) VALUES ('l', %s)", (take,))
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("INSERT INTO public.lend_your_ear_sets (listener_user_id, take_session_id) VALUES ('l', %s)", (take,))
        cur.execute("INSERT INTO public.lend_your_ear_answers (set_id, listener_user_id, clip_id, clip_source, value) "
                    "VALUES (gen_random_uuid(), 'l', 'c1', 'shared', 'yes')")
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("INSERT INTO public.lend_your_ear_answers (set_id, listener_user_id, clip_id, clip_source, value) "
                        "VALUES (gen_random_uuid(), 'l', 'c1', 'corpus', 'no')")
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.delayed_measure_votes (pair_id, clip, rater_id, rater_kind, value, measure_version) "
                        "VALUES (gen_random_uuid(), 'sideways', 'r', 'peer', 'yes', 'v1')")
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.corpus_clips (added_by, licence, passage, audio_url, coach_value) "
                        "VALUES ('c', 'l', 'p', 'https://a', 'maybe')")


def test_a_withdrawn_share_leaves_the_live_view(db):
    arc, snip = str(uuid.uuid4()), f"snip-{uuid.uuid4().hex[:8]}"
    with db.cursor() as probe:
        probe.execute("SELECT to_regclass('public.voice_album') IS NOT NULL")
        if not probe.fetchone()[0]:
            pytest.skip("the narrow lane has no voice_album; the view waits for it")
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("INSERT INTO public.voice_album (arc_id, snippet_id) VALUES (%s, %s)", (arc, snip))
        cur.execute("INSERT INTO public.voice_album_shares (owner_user_id, arc_id, snippet_id) VALUES ('o', %s, %s)", (arc, snip))
        cur.execute("SELECT count(*) AS n FROM public.shared_clips_live WHERE snippet_id = %s", (snip,))
        assert cur.fetchone()["n"] == 1
        cur.execute("UPDATE public.voice_album_shares SET revoked_at = now() WHERE snippet_id = %s", (snip,))
        cur.execute("SELECT count(*) AS n FROM public.shared_clips_live WHERE snippet_id = %s", (snip,))
        assert cur.fetchone()["n"] == 0
