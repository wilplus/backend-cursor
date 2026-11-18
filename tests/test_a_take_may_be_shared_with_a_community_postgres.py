"""
STORY    As a speaker, I want a Take I shared to leave the community the
         moment I revoke it or the community closes, so that I stay in
         control of who hears me.
OUTCOME
  O1  A shared Take shows in the community's live list.
  O2  Revoking the share removes it.
  O3  Closing the community removes it.
PROVES   O1, O2, O3 -> test_a_revoked_share_and_a_closed_community_leave_the_live_view
WHY      N52.4 (migration 0432).
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
    try:
        yield conn
    finally:
        conn.close()


def _private(cur, owner):
    cur.execute("INSERT INTO public.communities (kind, name, pass_code_digest, created_by) "
                "VALUES ('private', 'Friends', %s, %s) RETURNING id",
                (uuid.uuid4().hex, owner))
    return cur.fetchone()[0]


def _a_moment(cur):
    """One recorded Take with a clip whose span is inside the recording."""
    take, recording, snippet, owner = (str(uuid.uuid4()) for _ in range(4))
    cur.execute("INSERT INTO public.recordings (id) VALUES (%s)", (recording,))
    cur.execute("INSERT INTO public.v2_sessions (id, arc_id, user_id, take_index, recording_1_id) "
                "VALUES (%s, %s, %s, 1, %s)", (take, str(uuid.uuid4()), owner, recording))
    cur.execute("INSERT INTO public.snippets (id, session_id, recording_id, start_offset_ms, duration_ms) "
                "VALUES (%s, %s, %s, 0, 1000)", (snippet, take, recording))
    return snippet, take, owner


def test_a_revoked_share_and_a_closed_community_leave_the_live_view(db):
    with db.cursor() as cur:
        snip, take, owner = _a_moment(cur)
        community = _private(cur, owner)
        cur.execute("INSERT INTO public.take_shares (take_session_id, owner_user_id, community_id, "
                    "consent_version) VALUES (%s, %s, %s, 'v1')", (take, owner, community))
        cur.execute("SELECT snippet_id, community_kind, owner_user_id FROM public.community_clips_live "
                    "WHERE community_id = %s AND snippet_id = %s", (community, snip))
        assert cur.fetchall() == [(snip, "private", owner)]
        cur.execute("UPDATE public.take_shares SET revoked_at = now() WHERE community_id = %s", (community,))
        cur.execute("SELECT count(*) FROM public.community_clips_live WHERE community_id = %s", (community,))
        assert cur.fetchone()[0] == 0
        cur.execute("UPDATE public.take_shares SET revoked_at = NULL WHERE community_id = %s", (community,))
        cur.execute("UPDATE public.communities SET closed_at = now() WHERE id = %s", (community,))
        cur.execute("SELECT count(*) FROM public.community_clips_live WHERE community_id = %s", (community,))
        assert cur.fetchone()[0] == 0
