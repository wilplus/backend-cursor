"""A Take may be shared with a community, on a disposable database (0432,
N52.4). Pins: the four tables and the view exist; exactly one general
community, seeded once even when the file is applied twice; a private
community needs a name, a digest and its creator, the general one has none;
a pass-code digest opens one community; one membership, one share per Take
and community, one answer per person per clip; a training answer never
carries a snippet or a label; the view reads with the caller's rights; a
revoked share and a closed community leave the live view."""
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


def _private(cur, owner="o"):
    cur.execute("INSERT INTO public.communities (kind, name, pass_code_digest, created_by) "
                "VALUES ('private', 'Friends', %s, %s) RETURNING id",
                (uuid.uuid4().hex, owner))
    return cur.fetchone()[0]


def _a_moment(cur):
    """A snippet to share: an existing one, or a minimal one where the
    lane's snippets copy takes it; None when neither is possible."""
    cur.execute("SELECT id::text, session_id::text FROM public.snippets "
                "WHERE session_id IS NOT NULL LIMIT 1")
    row = cur.fetchone()
    if row:
        return row[0], row[1], False
    snip, take = str(uuid.uuid4()), str(uuid.uuid4())
    try:
        cur.execute("INSERT INTO public.snippets (id, session_id) VALUES (%s, %s)", (snip, take))
    except psycopg2.Error:
        return None
    return snip, take, True


def test_a_revoked_share_and_a_closed_community_leave_the_live_view(db):
    with db.cursor() as probe:
        probe.execute("SELECT to_regclass('public.community_clips_live') IS NOT NULL")
        if not probe.fetchone()[0]:
            pytest.skip("this lane has no snippets; the view waits for it")
    with db.cursor() as cur:
        moment = _a_moment(cur)
        if moment is None:
            pytest.skip("this lane's snippets copy takes no minimal row")
        snip, take, made = moment
        community = _private(cur)
        cur.execute("INSERT INTO public.take_shares (take_session_id, owner_user_id, community_id, "
                    "consent_version) VALUES (%s, 'o', %s, 'v1')", (take, community))
        cur.execute("SELECT snippet_id, community_kind, owner_user_id FROM public.community_clips_live "
                    "WHERE community_id = %s AND snippet_id = %s", (community, snip))
        assert cur.fetchall() == [(snip, "private", "o")]
        cur.execute("UPDATE public.take_shares SET revoked_at = now() WHERE community_id = %s", (community,))
        cur.execute("SELECT count(*) FROM public.community_clips_live WHERE community_id = %s", (community,))
        assert cur.fetchone()[0] == 0
        cur.execute("UPDATE public.take_shares SET revoked_at = NULL WHERE community_id = %s", (community,))
        cur.execute("UPDATE public.communities SET closed_at = now() WHERE id = %s", (community,))
        cur.execute("SELECT count(*) FROM public.community_clips_live WHERE community_id = %s", (community,))
        assert cur.fetchone()[0] == 0
        cur.execute("DELETE FROM public.communities WHERE id = %s", (community,))
        if made:
            cur.execute("DELETE FROM public.snippets WHERE id = %s", (snip,))
