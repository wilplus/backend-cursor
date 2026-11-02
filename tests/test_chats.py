"""
STORY    As the founder, I want my own chats with a colleague and a customer,
         apart from my chat with Will, where I answer with one of three emoji,
         so that I can see the chats between people working before anyone
         else is in them.
OUTCOME
  O1  Without the ring row (chats, ring 6) every route answers 404 and
      nothing is written.
  O2  The demo makes Sarah's customer chat and Ariel's colleague chat once,
      however often it is asked; the list names each chat for the other
      person, with their line and the last thing said.
  O3  In my chat I read what was said, oldest first, mine marked; I send 👍,
      👀 or 🙏 with its meaning kept as a label (N311), and anything else is
      refused.
  O4  Someone not in a chat can neither read it nor send to it.
PROVES   O1 -> ChatsTest::test_without_the_ring_every_route_is_not_found
         O2 -> ChatsTest::test_the_demo_is_made_once_and_listed
         O3 -> ChatsTest::test_a_member_reads_and_sends_one_of_three_emoji
         O4 -> ChatsTest::test_someone_not_in_the_chat_is_refused
WHY      The chats between people, first slice (founder 2026-10-31, N298 to
         N316; the three emoji N311).
"""
from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from services.db import db

ME = "11111111-1111-4111-8111-111111111111"
SOMEONE = "22222222-2222-4222-8222-222222222222"


class _Query:
    """One PostgREST call on an in-memory table: filters, order, limit."""

    def __init__(self, store: "_Store", name: str):
        self.store, self.name = store, name
        self.filters: list = []
        self.sort: tuple | None = None
        self.cap: int | None = None
        self.write: tuple | None = None

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters.append(lambda r: r.get(column) == value)
        return self

    def in_(self, column, values):
        self.filters.append(lambda r: r.get(column) in set(values))
        return self

    def order(self, column, desc=False):
        self.sort = (column, desc)
        return self

    def limit(self, n):
        self.cap = n
        return self

    def insert(self, payload):
        self.write = ("insert", payload if isinstance(payload, list) else [payload])
        return self

    def delete(self):
        self.write = ("delete", None)
        return self

    def execute(self):
        rows = self.store.tables.setdefault(self.name, [])
        if self.write and self.write[0] == "insert":
            made = [self.store.defaults(self.name, r) for r in self.write[1]]
            rows.extend(made)
            return _Result([dict(r) for r in made])
        hits = [r for r in rows if all(f(r) for f in self.filters)]
        if self.write:
            self.store.tables[self.name] = [r for r in rows if r not in hits]
            return _Result(hits)
        if self.sort:
            hits.sort(key=lambda r: r[self.sort[0]], reverse=self.sort[1])
        return _Result([dict(r) for r in hits[:self.cap]])


class _Result:
    def __init__(self, rows):
        self.data = rows


class _Store:
    """The three chat tables in memory, standing in for db.client."""

    def __init__(self):
        self.tables: dict[str, list[dict]] = {}
        self.clock = datetime.now(timezone.utc)

    def table(self, name):
        return _Query(self, name)

    def defaults(self, name, row):
        self.clock += timedelta(minutes=1)
        made = {"id": str(uuid.uuid4()), "created_at": self.clock.isoformat(), **row}
        if name == "chat_messages":
            made.setdefault("meta", {})
        return made

    def count(self, name):
        return len(self.tables.get(name, []))


class ChatsTest(unittest.TestCase):
    def setUp(self):
        from flask import Flask

        import auth
        from routes.v2 import register_domains
        from routes.v2.blueprint import v2_bp
        from services.rate_limits import limiter

        register_domains()
        if hasattr(limiter, "initialized"):
            self.addCleanup(setattr, limiter, "initialized", limiter.initialized)
            limiter.initialized = False
        app = Flask(__name__)
        app.register_blueprint(v2_bp, url_prefix="/v2")
        self.client = app.test_client()
        self.store = _Store()
        self.who = ME
        self.ring = {ME: True, SOMEONE: True}
        for p in (patch.object(auth, "verify_supabase_token", lambda t: {"sub": self.who}),
                  patch("services.rings.feature_is_on_for_user",
                        lambda feature, user, database=None:
                        feature == "chats" and self.ring.get(user, False)),
                  patch.object(db, "client", self.store)):
            p.start()
            self.addCleanup(p.stop)

    def _get(self, path):
        return self.client.get(path, headers={"Authorization": "Bearer t"})

    def _post(self, path, body=None):
        return self.client.post(path, json=body, headers={"Authorization": "Bearer t"})

    def _chat(self, kind):
        chats = self._post("/v2/chats/demo").get_json()["chats"]
        return next(c for c in chats if c["kind"] == kind)

    def test_without_the_ring_every_route_is_not_found(self):
        self.ring[ME] = False
        thread = str(uuid.uuid4())
        for res in (self._get("/v2/chats"), self._post("/v2/chats/demo"),
                    self._get(f"/v2/chats/{thread}/messages"),
                    self._post(f"/v2/chats/{thread}/messages", {"kind": "emoji", "body": "👍"})):
            self.assertEqual((res.status_code, res.get_json()["code"]), (404, "NOT_FOUND"))
        self.assertEqual(self.store.tables, {})

    def test_the_demo_is_made_once_and_listed(self):
        first = self._post("/v2/chats/demo")
        self.assertEqual(first.status_code, 200)
        again = self._post("/v2/chats/demo").get_json()
        self.assertEqual(again, first.get_json())
        self.assertEqual(self._get("/v2/chats").get_json(), again)
        self.assertEqual([self.store.count(t) for t in
                          ("chat_threads", "chat_members", "chat_messages")], [2, 4, 3])
        shown = {c["kind"]: (c["title"], c["subtitle"], c["last"]["kind"], c["last"]["body"])
                 for c in again["chats"]}
        self.assertEqual(shown, {
            "customer": ("Sarah", "Customer · Invita", "text",
                         "Itchy for two months, thinning at the top. I wash every day. "
                         "What should I do?"),
            "team": ("Ariel", "Your colleague · Invita", "emoji", "👍"),
        })

    def test_a_member_reads_and_sends_one_of_three_emoji(self):
        ariel = self._chat("team")["id"]
        said = self._get(f"/v2/chats/{ariel}/messages").get_json()["messages"]
        self.assertEqual([(m["mine"], m["author"], m["kind"], m["body"]) for m in said], [
            (False, "Ariel", "text", "On slide 1: name the treatment and let it land."),
            (False, "Ariel", "emoji", "👍")])

        res = self._post(f"/v2/chats/{ariel}/messages", {"kind": "emoji", "body": "👀"})
        self.assertEqual(res.status_code, 200)
        sent = res.get_json()["message"]
        self.assertEqual((sent["mine"], sent["kind"], sent["body"], sent["meta"]),
                         (True, "emoji", "👀", {"label": "seen"}))
        for wrong in ({"kind": "emoji", "body": "✅"}, {"kind": "text", "body": "Thanks!"},
                      {"kind": "emoji", "body": "👍👍"}, None):
            res = self._post(f"/v2/chats/{ariel}/messages", wrong)
            self.assertEqual((res.status_code, res.get_json()["code"]), (400, "NOT_ALLOWED"))
        now = self._get(f"/v2/chats/{ariel}/messages").get_json()["messages"]
        self.assertEqual([m["body"] for m in now], ["On slide 1: name the treatment and let it land.",
                                                    "👍", "👀"])
        self.assertTrue(now[-1]["mine"])
        listed = {c["id"]: c["last"]["body"] for c in self._get("/v2/chats").get_json()["chats"]}
        self.assertEqual(listed[ariel], "👀")

    def test_someone_not_in_the_chat_is_refused(self):
        sarah = self._chat("customer")["id"]
        self.who = SOMEONE
        self.assertEqual(self._get("/v2/chats").get_json(), {"chats": []})
        for res in (self._get(f"/v2/chats/{sarah}/messages"),
                    self._post(f"/v2/chats/{sarah}/messages", {"kind": "emoji", "body": "🙏"}),
                    self._get("/v2/chats/not-a-chat/messages")):
            self.assertEqual((res.status_code, res.get_json()["code"]), (404, "NOT_FOUND"))
        self.assertEqual(self.store.count("chat_messages"), 3)


if __name__ == "__main__":
    unittest.main()
