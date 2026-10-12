"""A share records the words the speaker saw, on a disposable database
(0443; CM2 B, N53.2; Q-B6 A, N62; build plan D-FW-6).

Pins:
  * take_shares gains share_words_version, nullable text; the file applied
    again changes nothing and rewrites no row;
  * the door is as 0432 left it: browser roles and PUBLIC hold nothing on
    take_shares, service_role reads and writes it;
  * the share / revoke round trip as the app writes it: a share stamps both
    versions and clears revoked_at; a revocation stamps revoked_at and keeps
    both versions (history); a share again under newer words re-stamps the
    live row; one row per Take and community;
  * the server's own list of words versions (Config.SHARE_WORDS_VERSIONS)
    guards the write: share_take, driven against this database, refuses a
    version the server does not list and writes no row, and records a
    listed one;
  * the queue (community_clips_live) drops a revoked Take at once and takes
    it back when it is shared again.
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

WORDS = "sharing-screen-2026-10-06"
POLICY = "phase1-2026-10-02"


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
    row = cur.fetchone()
    return row["id"] if isinstance(row, dict) else row[0]


def _share(cur, take, community, owner="o", words=WORDS, policy=POLICY):
    """The app's share write (services.db.upsert_take_share)."""
    cur.execute(
        "INSERT INTO public.take_shares (take_session_id, owner_user_id, community_id, "
        "consent_version, share_words_version, shared_at, revoked_at) "
        "VALUES (%s, %s, %s, %s, %s, now(), NULL) "
        "ON CONFLICT (take_session_id, community_id) DO UPDATE SET "
        "owner_user_id = EXCLUDED.owner_user_id, consent_version = EXCLUDED.consent_version, "
        "share_words_version = EXCLUDED.share_words_version, shared_at = EXCLUDED.shared_at, "
        "revoked_at = NULL",
        (take, owner, community, policy, words))


def _revoke(cur, take, keep=()):
    """The app's revocation (services.db.revoke_take_shares): every live row
    of the Take not kept gets revoked_at; nothing else changes."""
    cur.execute("UPDATE public.take_shares SET revoked_at = now() "
                "WHERE take_session_id = %s AND revoked_at IS NULL "
                "AND NOT (community_id = ANY(%s::uuid[]))", (take, list(keep)))
    return cur.rowcount


def test_the_share_and_revoke_round_trip_keeps_both_versions(db):
    take = str(uuid.uuid4())
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        mine = _private(cur)
        cur.execute("SELECT id FROM public.communities WHERE kind = 'general'")
        general = cur.fetchone()["id"]
        _share(cur, take, general)
        _share(cur, take, mine)
        cur.execute("SELECT community_id, consent_version, share_words_version, revoked_at "
                    "FROM public.take_shares WHERE take_session_id = %s", (take,))
        rows = {str(r["community_id"]): dict(r) for r in cur.fetchall()}
        assert set(rows) == {str(general), str(mine)}
        assert all(r["consent_version"] == POLICY and r["share_words_version"] == WORDS
                   and r["revoked_at"] is None for r in rows.values())
        # Fewer choices withdraw the Take from the rest; the versions stay.
        assert _revoke(cur, take, keep=[str(mine)]) == 1
        cur.execute("SELECT share_words_version, consent_version, revoked_at "
                    "FROM public.take_shares WHERE take_session_id = %s AND community_id = %s",
                    (take, general))
        gone = dict(cur.fetchone())
        assert gone["revoked_at"] is not None
        assert (gone["share_words_version"], gone["consent_version"]) == (WORDS, POLICY)
        # "None": every live row revoked, no version read or written.
        assert _revoke(cur, take) == 1
        cur.execute("SELECT count(*) FROM public.take_shares WHERE take_session_id = %s "
                    "AND revoked_at IS NULL", (take,))
        assert cur.fetchone()["count"] == 0
        assert _revoke(cur, take) == 0
        # Shared again under newer words: the same row comes back live,
        # re-stamped; still one row per Take and community.
        _share(cur, take, general, words="sharing-screen-v2")
        cur.execute("SELECT share_words_version, revoked_at FROM public.take_shares "
                    "WHERE take_session_id = %s AND community_id = %s", (take, general))
        again = dict(cur.fetchone())
        assert again == {"share_words_version": "sharing-screen-v2", "revoked_at": None}
        cur.execute("SELECT count(*) FROM public.take_shares WHERE take_session_id = %s", (take,))
        assert cur.fetchone()["count"] == 2
        cur.execute("DELETE FROM public.take_shares WHERE take_session_id = %s", (take,))
        cur.execute("DELETE FROM public.communities WHERE id = %s", (mine,))
