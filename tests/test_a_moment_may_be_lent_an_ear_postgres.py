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
