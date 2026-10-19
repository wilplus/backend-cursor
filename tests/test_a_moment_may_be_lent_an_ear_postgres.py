"""
STORY    As a speaker, I want a clip I shared for listening to vanish from the
         shared list as soon as I withdraw it, so that I control who hears me.
OUTCOME
  O1  A share with revoked_at set leaves shared_clips_live at once.
PROVES   O1 -> test_a_withdrawn_share_leaves_the_live_view
WHY      Migration 0410 (F3). The Voice Album share switch is RETIRED
         (services/lend_your_ear.py docstring): the app no longer writes
         voice_album_shares, so the revocation is written here by hand, and
         the view's one reader (delayed_measure.clips_for_listener) has no
         caller. The live sharing path is pinned in
         test_a_take_may_be_shared_with_a_community_postgres.py. Candidate
         for deletion together with its lane entry in
         scripts/rehearsal_tier.sh.
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
