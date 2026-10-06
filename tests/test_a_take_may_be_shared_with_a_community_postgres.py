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
from pathlib import Path

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)
MIGRATION = (Path(__file__).resolve().parents[1] / "migrations"
             / "a_take_may_be_shared_with_a_community.sql")


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


def test_the_tables_and_the_view_exist(db):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT table_name, table_type FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name IN ("
                    "'communities','community_members','take_shares','community_answers',"
                    "'community_clips_live')")
        kinds = {r["table_name"]: r["table_type"] for r in cur.fetchall()}
        assert {k for k in kinds if k != "community_clips_live"} == {
            "communities", "community_members", "take_shares", "community_answers"}
        if "community_clips_live" in kinds:
            assert kinds["community_clips_live"] == "VIEW"
        cur.execute("SELECT relname, relrowsecurity FROM pg_class WHERE relname IN ("
                    "'communities','community_members','take_shares','community_answers')")
        assert all(r["relrowsecurity"] for r in cur.fetchall())


def test_one_general_community_even_when_applied_again(db):
    with db.cursor() as cur:
        cur.execute(MIGRATION.read_text())
        cur.execute("SELECT count(*) FROM public.communities WHERE kind = 'general'")
        assert cur.fetchone()[0] == 1
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("INSERT INTO public.communities (kind) VALUES ('general')")


def test_the_shapes_hold(db):
    with db.cursor() as cur:
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.communities (kind, name) VALUES ('private', 'x')")
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.communities (kind, name, pass_code_digest, created_by) "
                        "VALUES ('general', 'x', 'd', 'o')")
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.communities (kind) VALUES ('secret')")
        digest = uuid.uuid4().hex
        cur.execute("INSERT INTO public.communities (kind, name, pass_code_digest, created_by) "
                    "VALUES ('private', 'A', %s, 'o')", (digest,))
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("INSERT INTO public.communities (kind, name, pass_code_digest, created_by) "
                        "VALUES ('private', 'B', %s, 'p')", (digest,))


def test_the_keys_hold(db):
    take = f"take-{uuid.uuid4().hex[:8]}"
    listener = f"l-{uuid.uuid4().hex[:8]}"
    with db.cursor() as cur:
        community = _private(cur)
        cur.execute("INSERT INTO public.community_members (community_id, user_id, role) "
                    "VALUES (%s, 'o', 'owner')", (community,))
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("INSERT INTO public.community_members (community_id, user_id) "
                        "VALUES (%s, 'o')", (community,))
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.community_members (community_id, user_id, role) "
                        "VALUES (%s, 'p', 'admin')", (community,))
        cur.execute("INSERT INTO public.take_shares (take_session_id, owner_user_id, community_id, "
                    "consent_version) VALUES (%s, 'o', %s, 'v1')", (take, community))
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("INSERT INTO public.take_shares (take_session_id, owner_user_id, "
                        "community_id, consent_version) VALUES (%s, 'o', %s, 'v1')",
                        (take, community))
        with pytest.raises(psycopg2.errors.NotNullViolation):
            cur.execute("INSERT INTO public.take_shares (take_session_id, owner_user_id, "
                        "community_id) VALUES ('t2', 'o', %s)", (community,))
        cur.execute("INSERT INTO public.community_answers (clip_source, community_id, "
                    "listener_user_id, snippet_id, take_session_id, value) "
                    "VALUES ('community', %s, %s, 's1', %s, 'yes')", (community, listener, take))
        with pytest.raises(psycopg2.errors.UniqueViolation):
            cur.execute("INSERT INTO public.community_answers (clip_source, community_id, "
                        "listener_user_id, snippet_id, take_session_id, value) "
                        "VALUES ('community', %s, %s, 's1', %s, 'no')", (community, listener, take))
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.community_answers (clip_source, community_id, "
                        "listener_user_id, snippet_id, take_session_id, value) "
                        "VALUES ('community', %s, %s, 's2', %s, 'maybe')", (community, listener, take))
        cur.execute("INSERT INTO public.community_answers (clip_source, listener_user_id, "
                    "corpus_clip_id, value) VALUES ('corpus', %s, 'c1', 'no')",
                    (listener,))
        # A training answer carries no label of any kind: not an id, not an
        # outcome (GPT's check of 0432, rule 6).
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.community_answers (clip_source, listener_user_id, "
                        "corpus_clip_id, value, label_outcome) VALUES ('corpus', %s, 'c4', 'no', 'x')",
                        (listener,))
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.community_answers (clip_source, listener_user_id, "
                        "corpus_clip_id, snippet_id, value) VALUES ('corpus', %s, 'c2', 's9', 'no')",
                        (listener,))
        with pytest.raises(psycopg2.errors.CheckViolation):
            cur.execute("INSERT INTO public.community_answers (clip_source, listener_user_id, "
                        "corpus_clip_id, value, label_id) VALUES ('corpus', %s, 'c3', 'no', 'x')",
                        (listener,))
        cur.execute("DELETE FROM public.communities WHERE id = %s", (community,))
        cur.execute("SELECT count(*) FROM public.take_shares WHERE take_session_id = %s", (take,))
        assert cur.fetchone()[0] == 0


def test_the_view_reads_with_the_caller_s_rights(db):
    with db.cursor() as probe:
        probe.execute("SELECT to_regclass('public.community_clips_live') IS NOT NULL")
        if not probe.fetchone()[0]:
            pytest.skip("this lane has no snippets; the view waits for it")
        probe.execute("SELECT reloptions FROM pg_class WHERE relname = 'community_clips_live'")
        assert "security_invoker=true" in (probe.fetchone()[0] or [])


def test_browser_roles_get_nothing_on_the_tables_or_the_view(db):
    names = ["communities", "community_members", "take_shares", "community_answers"]
    with db.cursor() as probe:
        probe.execute("SELECT to_regclass('public.community_clips_live') IS NOT NULL")
        if probe.fetchone()[0]:
            names.append("community_clips_live")
        for role in ("anon", "authenticated"):
            probe.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,))
            if not probe.fetchone():
                continue
            for name in names:
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                    probe.execute("SELECT has_table_privilege(%s, %s, %s)",
                                  (role, f"public.{name}", privilege))
                    assert probe.fetchone()[0] is False, (role, name, privilege)
        for name in names:
            probe.execute("SELECT relacl FROM pg_class WHERE oid = %s::regclass",
                          (f"public.{name}",))
            acl = probe.fetchone()[0] or []
            assert not any(str(entry).startswith("=") for entry in acl), (name, acl)


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
