"""
STORY    As a speaker sharing a Take with a community, I want the exact
         sharing words I agreed to recorded with my share, and kept after I
         revoke, so that there is proof of what I consented to (consent on
         the critical path).
OUTCOME
  O1  A share stamps the consent (Privacy/Terms) version and the words
      version on one row per Take and community.
  O2  A revocation (fewer communities, or "None") stamps revoked_at and
      keeps both versions.
  O3  Sharing again under newer words re-stamps the same row and makes it
      live again.
  O4  A words version the server does not list (Config.SHARE_WORDS_VERSIONS)
      is refused and no row is written.
PROVES   O1, O2, O3 -> test_the_share_and_revoke_round_trip_keeps_both_versions
         O4 -> test_an_unlisted_words_version_is_refused_and_writes_nothing
WHY      Migration 0443 (CM2 B, N53.2; Q-B6 A, N62). The real
         services.communities.share_take and services.db writers run over a
         thin PostgREST-to-SQL client on the rehearsal tier. The queue
         dropping a revoked Take is pinned in
         test_a_take_may_be_shared_with_a_community_postgres.py.
"""
from __future__ import annotations

import os
import uuid
from typing import Any

import psycopg2
import psycopg2.extras
import pytest
from psycopg2 import sql

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

WORDS = "sharing-screen-2026-10-06"
NEWER_WORDS = "sharing-screen-2026-10-12"


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


# ── the slice of the PostgREST builder the share code uses, as SQL ────────

class _Result:
    def __init__(self, data: Any) -> None:
        self.data = data


class _Query:
    def __init__(self, conn, relation: str) -> None:
        self.conn, self.relation = conn, relation
        self.mode, self.payload, self.conflict = "select", None, None
        self.where: list[sql.Composable] = []
        self.args: list[Any] = []
        self.cap: int | None = None
        self._negate = False

    @property
    def not_(self) -> "_Query":
        self._negate = True
        return self

    def select(self, _columns: str = "*") -> "_Query":
        return self

    def upsert(self, payload: dict, on_conflict: str = "") -> "_Query":
        self.mode, self.payload, self.conflict = "upsert", payload, on_conflict
        return self

    def update(self, payload: dict) -> "_Query":
        self.mode, self.payload = "update", payload
        return self

    def eq(self, column: str, value: Any) -> "_Query":
        return self._filter(sql.SQL("{}::text = %s").format(sql.Identifier(column)),
                            [str(value)])

    def is_(self, column: str, value: str) -> "_Query":
        assert value == "null"
        return self._filter(sql.SQL("{} IS NULL").format(sql.Identifier(column)), [])

    def in_(self, column: str, values: list) -> "_Query":
        return self._filter(sql.SQL("{}::text = ANY(%s)").format(sql.Identifier(column)),
                            [[str(v) for v in values]])

    def limit(self, count: int) -> "_Query":
        self.cap = count
        return self

    def _filter(self, clause: sql.Composable, args: list) -> "_Query":
        if self._negate:
            clause, self._negate = sql.SQL("NOT ({})").format(clause), False
        self.where.append(clause)
        self.args += args
        return self

    def execute(self) -> _Result:
        table = sql.SQL("public.{}").format(sql.Identifier(self.relation))
        where = (sql.SQL(" WHERE ") + sql.SQL(" AND ").join(self.where)
                 if self.where else sql.SQL(""))
        if self.mode == "upsert":
            cols = list(self.payload)
            keys = [k.strip() for k in self.conflict.split(",")]
            query = sql.SQL(
                "INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) DO UPDATE SET {} "
                "RETURNING *").format(
                table, sql.SQL(",").join(map(sql.Identifier, cols)),
                sql.SQL(",").join(sql.Placeholder() * len(cols)),
                sql.SQL(",").join(map(sql.Identifier, keys)),
                sql.SQL(",").join(sql.SQL("{0} = EXCLUDED.{0}").format(sql.Identifier(c))
                                  for c in cols if c not in keys))
            return _Result(self._fetch(query, [self.payload[c] for c in cols]))
        if self.mode == "update":
            assert self.where, "an unfiltered UPDATE never reaches the database"
            cols = list(self.payload)
            query = sql.SQL("UPDATE {} SET {}{} RETURNING *").format(
                table, sql.SQL(",").join(sql.SQL("{} = %s").format(sql.Identifier(c))
                                         for c in cols), where)
            return _Result(self._fetch(query, [self.payload[c] for c in cols] + self.args))
        query = sql.SQL("SELECT * FROM {}{}").format(table, where)
        if self.cap:
            query += sql.SQL(" LIMIT {}").format(sql.Literal(self.cap))
        return _Result(self._fetch(query, self.args))

    def _fetch(self, query, args) -> list[dict]:
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, args)
            return [dict(r) for r in cur.fetchall()]


class _SqlClient:
    def __init__(self, conn) -> None:
        self.conn = conn

    def table(self, relation: str) -> _Query:
        return _Query(self.conn, relation)


def _database(conn, owner: str):
    """The real DatabaseService over the database; only the Take lookup is
    answered here (the Take belongs to `owner`)."""
    from services.db import DatabaseService
    service = DatabaseService.__new__(DatabaseService)
    service.client = _SqlClient(conn)
    service.v2_get_session_by_id = lambda _sid: {"user_id": owner}
    return service


@pytest.fixture()
def terms_accepted(monkeypatch):
    """The speaker is on the current Privacy/Terms; that gate is not the
    subject here."""
    import services.lend_your_ear as lend_your_ear
    monkeypatch.setattr(lend_your_ear, "accepted_policy_at_least",
                        lambda _db, _user, _version: True)


def _rows(db, take) -> dict:
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT community_id::text, consent_version, share_words_version, "
                    "revoked_at FROM public.take_shares WHERE take_session_id = %s", (take,))
        return {r["community_id"]: dict(r) for r in cur.fetchall()}


def test_the_share_and_revoke_round_trip_keeps_both_versions(db, terms_accepted):
    from services.communities import share_policy_version, share_take
    owner, take = f"speaker-{uuid.uuid4()}", str(uuid.uuid4())
    database = _database(db, owner)
    policy = share_policy_version()
    general = str(database.get_general_community()["id"])
    with db.cursor() as cur:
        cur.execute("INSERT INTO public.communities (kind, name, pass_code_digest, created_by) "
                    "VALUES ('private', 'Friends', %s, %s) RETURNING id::text",
                    (uuid.uuid4().hex, owner))
        mine = cur.fetchone()[0]
        cur.execute("INSERT INTO public.community_members (community_id, user_id, role) "
                    "VALUES (%s, %s, 'owner')", (mine, owner))
    try:
        # O1: the share stamps both versions on one row per community.
        status, body = share_take(database, owner_user_id=owner, take_session_id=take,
                                  body={"general": True, "community_ids": [mine],
                                        "share_words_version": WORDS})
        assert status == 200 and body["share_words_version"] == WORDS
        rows = _rows(db, take)
        assert set(rows) == {general, mine}
        assert all((r["consent_version"], r["share_words_version"], r["revoked_at"])
                   == (policy, WORDS, None) for r in rows.values())

        # O2: fewer choices withdraw the Take from the rest; versions stay.
        status, _ = share_take(database, owner_user_id=owner, take_session_id=take,
                               body={"community_ids": [mine],
                                     "share_words_version": WORDS})
        assert status == 200
        rows = _rows(db, take)
        assert rows[general]["revoked_at"] is not None
        assert (rows[general]["consent_version"], rows[general]["share_words_version"]) \
            == (policy, WORDS)
        assert rows[mine]["revoked_at"] is None
        # "None": every live row revoked, the versions kept.
        assert share_take(database, owner_user_id=owner, take_session_id=take,
                          body={"none": True})[0] == 200
        rows = _rows(db, take)
        assert all(r["revoked_at"] is not None and r["share_words_version"] == WORDS
                   and r["consent_version"] == policy for r in rows.values())

        # O3: shared again under newer words, the same row is live again,
        # re-stamped; still one row per Take and community.
        assert share_take(database, owner_user_id=owner, take_session_id=take,
                          body={"general": True,
                                "share_words_version": NEWER_WORDS})[0] == 200
        rows = _rows(db, take)
        assert len(rows) == 2
        assert (rows[general]["share_words_version"], rows[general]["revoked_at"]) \
            == (NEWER_WORDS, None)
        assert rows[mine]["share_words_version"] == WORDS
        assert rows[mine]["revoked_at"] is not None
    finally:
        with db.cursor() as cur:
            cur.execute("DELETE FROM public.take_shares WHERE take_session_id = %s", (take,))
            cur.execute("DELETE FROM public.communities WHERE id = %s", (mine,))


def test_an_unlisted_words_version_is_refused_and_writes_nothing(db, terms_accepted):
    from services.communities import share_take, share_words_versions
    owner, take = f"speaker-{uuid.uuid4()}", str(uuid.uuid4())
    unlisted = "sharing-screen-2099-01-01"
    assert unlisted not in share_words_versions()
    status, body = share_take(_database(db, owner), owner_user_id=owner,
                              take_session_id=take,
                              body={"general": True, "share_words_version": unlisted})
    assert (status, body) == (400, {"code": "SHARE_WORDS_VERSION_UNKNOWN"})
    assert _rows(db, take) == {}
