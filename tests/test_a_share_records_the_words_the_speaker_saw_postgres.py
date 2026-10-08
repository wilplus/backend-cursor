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
import pathlib
import uuid

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "a_share_records_the_words_the_speaker_saw.sql"
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


def test_the_column_exists_nullable_and_the_file_applied_again_changes_nothing(db):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'take_shares' "
                    "AND column_name = 'share_words_version'")
        assert dict(cur.fetchone()) == {"data_type": "text", "is_nullable": "YES"}
        take, community = str(uuid.uuid4()), _private(cur)
        _share(cur, take, community)
        cur.execute("SELECT * FROM public.take_shares WHERE take_session_id = %s", (take,))
        before = [dict(r) for r in cur.fetchall()]
        cur.execute(MIGRATION.read_text())
        cur.execute("SELECT * FROM public.take_shares WHERE take_session_id = %s", (take,))
        assert [dict(r) for r in cur.fetchall()] == before
        # A row written before the column (as production's would be) is NULL.
        cur.execute("INSERT INTO public.take_shares (take_session_id, owner_user_id, "
                    "community_id, consent_version) VALUES (%s, 'o', %s, %s) "
                    "RETURNING share_words_version", (str(uuid.uuid4()), community, POLICY))
        assert cur.fetchone()["share_words_version"] is None
        cur.execute("DELETE FROM public.communities WHERE id = %s", (community,))


def test_the_door_is_as_0432_left_it(db):
    with db.cursor() as cur:
        for role in ("anon", "authenticated"):
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            if not cur.fetchone():
                continue
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                cur.execute("SELECT has_table_privilege(%s, 'public.take_shares', %s)",
                            (role, privilege))
                assert cur.fetchone()[0] is False, (role, privilege)
        cur.execute("SELECT count(*) FROM pg_class c, aclexplode(c.relacl) a "
                    "WHERE c.oid = 'public.take_shares'::regclass AND a.grantee = 0")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'service_role'")
        if cur.fetchone():
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                cur.execute("SELECT has_table_privilege('service_role', 'public.take_shares', %s)",
                            (privilege,))
                assert cur.fetchone()[0] is True, privilege
        cur.execute("SELECT relrowsecurity FROM pg_class WHERE relname = 'take_shares'")
        assert cur.fetchone() == (True,)


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


def _a_moment(cur):
    """A snippet to share: an existing one, or a minimal Take with one
    recording and one snippet where the lane's copies take them (the
    released shape needs a session and a recording behind a snippet); None
    when neither is possible."""
    cur.execute("SELECT id::text, session_id::text FROM public.snippets "
                "WHERE session_id IS NOT NULL LIMIT 1")
    row = cur.fetchone()
    if row:
        return row[0], row[1], False
    snip, take, recording = (str(uuid.uuid4()) for _ in range(3))
    try:
        cur.execute("SAVEPOINT moment")
        cur.execute("INSERT INTO public.recordings (id) VALUES (%s)", (recording,))
        cur.execute("INSERT INTO public.v2_sessions (id, arc_id, user_id, take_index) "
                    "VALUES (%s, %s, %s, 1)", (take, str(uuid.uuid4()), str(uuid.uuid4())))
        cur.execute("INSERT INTO public.snippets (id, session_id, recording_id, "
                    "start_offset_ms, duration_ms) VALUES (%s, %s, %s, 0, 3000)",
                    (snip, take, recording))
        cur.execute("RELEASE SAVEPOINT moment")
    except psycopg2.Error:
        cur.execute("ROLLBACK TO SAVEPOINT moment")
        return None
    return snip, take, True


def test_the_queue_drops_a_revoked_take_and_takes_it_back_when_shared_again(db):
    with db.cursor() as probe:
        probe.execute("SELECT to_regclass('public.community_clips_live') IS NOT NULL")
        if not probe.fetchone()[0]:
            pytest.skip("this lane has no snippets; the view waits for it")
    db.autocommit = False
    try:
        with db.cursor() as cur:
            moment = _a_moment(cur)
        db.commit()
    finally:
        db.autocommit = True
    if moment is None:
        pytest.skip("this lane's snippets copy takes no minimal row")
    snip, take, made = moment
    with db.cursor() as cur:
        community = _private(cur)
        _share(cur, take, community)
        cur.execute("SELECT snippet_id FROM public.community_clips_live "
                    "WHERE community_id = %s AND snippet_id = %s", (community, snip))
        assert cur.fetchall() == [(snip,)]
        # The view carries the moment, never the words or the policy version.
        cur.execute("SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'community_clips_live'")
        columns = {r[0] for r in cur.fetchall()}
        assert not {"share_words_version", "consent_version"} & columns
        _revoke(cur, take)
        cur.execute("SELECT count(*) FROM public.community_clips_live WHERE community_id = %s",
                    (community,))
        assert cur.fetchone()[0] == 0
        _share(cur, take, community, words="sharing-screen-v2")
        cur.execute("SELECT count(*) FROM public.community_clips_live WHERE community_id = %s "
                    "AND snippet_id = %s", (community, snip))
        assert cur.fetchone()[0] == 1
        cur.execute("DELETE FROM public.communities WHERE id = %s", (community,))
        if made:
            cur.execute("DELETE FROM public.snippets WHERE id = %s", (snip,))
            cur.execute("DELETE FROM public.v2_sessions WHERE id = %s", (take,))


class _PgShares:
    """The few reads and writes share_take makes, on this database, with
    the app's own SQL for the share and the revocation."""

    def __init__(self, conn, take, owner):
        self.conn, self.take, self.owner = conn, take, owner

    def v2_get_session_by_id(self, take_id):
        return {"id": take_id, "user_id": self.owner} if take_id == self.take else None

    def get_general_community(self):
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT id::text AS id, kind FROM public.communities "
                        "WHERE kind = 'general'")
            return dict(cur.fetchone())

    def list_community_memberships(self, _user_id):
        return []

    def get_communities_by_ids(self, _ids):
        return []

    def upsert_take_share(self, *, take_session_id, owner_user_id, community_id,
                          consent_version, share_words_version):
        with self.conn.cursor() as cur:
            _share(cur, take_session_id, community_id, owner=owner_user_id,
                   words=share_words_version, policy=consent_version)

    def revoke_take_shares(self, take, keep_community_ids):
        with self.conn.cursor() as cur:
            return _revoke(cur, take, keep_community_ids)


def test_an_unknown_words_version_writes_no_row_and_a_listed_one_is_recorded(db):
    from unittest.mock import patch

    from config import Config
    from services import communities as cm

    take, owner = str(uuid.uuid4()), str(uuid.uuid4())
    adapter = _PgShares(db, take, owner)
    with patch.object(Config, "COMMUNITIES_ENABLED", True), \
            patch.object(Config, "COMMUNITY_SHARE_POLICY_VERSION", POLICY), \
            patch("services.lend_your_ear.accepted_policy_at_least", return_value=True):
        status, payload = cm.share_take(
            adapter, owner_user_id=owner, take_session_id=take,
            body={"general": True, "share_words_version": "sharing-screen-v9"})
        assert (status, payload) == (400, {"code": "SHARE_WORDS_VERSION_UNKNOWN"})
        with db.cursor() as cur:
            cur.execute("SELECT count(*) FROM public.take_shares WHERE take_session_id = %s",
                        (take,))
            assert cur.fetchone()[0] == 0
        assert WORDS in Config.SHARE_WORDS_VERSIONS
        status, payload = cm.share_take(
            adapter, owner_user_id=owner, take_session_id=take,
            body={"general": True, "share_words_version": WORDS})
        assert status == 200 and payload["share_words_version"] == WORDS
    with db.cursor() as cur:
        cur.execute("SELECT share_words_version, consent_version, revoked_at "
                    "FROM public.take_shares WHERE take_session_id = %s", (take,))
        assert cur.fetchall() == [(WORDS, POLICY, None)]
        cur.execute("DELETE FROM public.take_shares WHERE take_session_id = %s", (take,))
