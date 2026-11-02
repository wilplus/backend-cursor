"""
STORY    As a person in WillpowerLab, I want my own link that I paste into any
         email, so that a colleague who opens it joins me in a chat, and
         nobody else can reach me (N308, N328, N335).
OUTCOME
  O1  My link is made the first time I ask and stays the same after;
      replacing it makes a new one, and the old one opens nothing.
  O2  Before signing in, the join page learns only the first name of whose
      link it is. A wrong link, a replaced one and one whose owner has no
      chats all answer 404, the same answer.
  O3  Joining makes one chat between the two of us, each named for the
      other; opening a link again, from either side, finds the same chat.
  O4  My own link is refused (400 OWN_LINK), and nothing is made.
  O5  Without the ring row (chats, ring 6) my link and joining answer 404,
      and nothing is written.
  O6  In the chat, the one who joined sees whose link they joined through;
      the link's owner does not.
PROVES   O1 -> ChatLinksTest::test_my_link_is_kept_and_a_replaced_one_opens_nothing
         O2 -> ChatLinksTest::test_the_join_page_learns_only_a_first_name
         O3 -> ChatLinksTest::test_joining_makes_one_chat_for_the_two
         O4 -> ChatLinksTest::test_my_own_link_is_refused
         O5 -> ChatLinksTest::test_without_the_ring_nothing_is_written
         O6 -> ChatLinksTest::test_the_one_who_joined_sees_whose_link_it_was
WHY      The join link, the chats' second slice (founder 2026-11-02: "go,
         build the join link slice"); the intimacy rule (N328); joining is
         onboarding (N335 item 1).
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from services.db import db
from tests.test_chats import _Store

TOMEK = "11111111-1111-4111-8111-111111111111"
PIOTR = "22222222-2222-4222-8222-222222222222"
#: Signed in, no ring.
NOBODY = "33333333-3333-4333-8333-333333333333"
NAMES = {TOMEK: ("Tomek Nowak", "tomek@example.com"),
         PIOTR: ("Piotr Kowalski", "piotr@example.com"),
         NOBODY: ("", "anna.k@example.com")}


class ChatLinksTest(unittest.TestCase):
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
        self.who = TOMEK
        self.ring = {TOMEK: True, PIOTR: True, NOBODY: False}

        def payload(_token):
            name, email = NAMES[self.who]
            return {"sub": self.who, "email": email, "user_metadata": {"full_name": name}}

        for p in (patch.object(auth, "verify_supabase_token", payload),
                  patch("services.rings.feature_is_on_for_user",
                        lambda feature, user, database=None:
                        feature == "chats" and self.ring.get(user, False)),
                  patch.object(db, "client", self.store),
                  patch.dict(os.environ, {"PLF1_PROCESSING_AUTHORIZATION_MODE": "off"})):
            p.start()
            self.addCleanup(p.stop)

    def _as(self, who):
        self.who = who
        return {"Authorization": "Bearer t"}

    def _link(self, who):
        return self.client.get("/v2/chats/link", headers=self._as(who))

    def _join(self, who, token):
        return self.client.post(f"/v2/chats/join/{token}", headers=self._as(who))

    def _preview(self, token):
        return self.client.get(f"/v2/chats/join/{token}")

    def test_my_link_is_kept_and_a_replaced_one_opens_nothing(self):
        first = self._link(TOMEK).get_json()
        self.assertEqual(first["path"], f"/c/{first['token']}")
        self.assertGreaterEqual(len(first["token"]), 16)
        self.assertEqual(self._link(TOMEK).get_json(), first)
        renewed = self.client.post("/v2/chats/link", headers=self._as(TOMEK)).get_json()
        self.assertNotEqual(renewed["token"], first["token"])
        self.assertEqual(self._preview(first["token"]).status_code, 404)
        self.assertEqual(self._preview(renewed["token"]).status_code, 200)
        self.assertEqual(self._join(PIOTR, first["token"]).status_code, 404)

    def test_the_join_page_learns_only_a_first_name(self):
        token = self._link(TOMEK).get_json()["token"]
        res = self._preview(token)
        self.assertEqual((res.status_code, res.get_json()), (200, {"name": "Tomek"}))
        self.ring[TOMEK] = False
        wrong = self._preview("x" * 24)
        off = self._preview(token)
        bad = self._preview("not a token!")
        for r in (wrong, off, bad):
            self.assertEqual((r.status_code, r.get_json()["code"]), (404, "NOT_FOUND"))

    def test_joining_makes_one_chat_for_the_two(self):
        token = self._link(TOMEK).get_json()["token"]
        chat = self._join(PIOTR, token).get_json()["chat"]["id"]
        self.assertEqual(self._join(PIOTR, token).get_json()["chat"]["id"], chat)
        # Tomek opening Piotr's link finds the same chat.
        piotr_token = self._link(PIOTR).get_json()["token"]
        self.assertEqual(self._join(TOMEK, piotr_token).get_json()["chat"]["id"], chat)
        self.assertEqual(self.store.count("chat_threads"), 1)
        self.assertEqual(self.store.count("chat_members"), 2)
        piotr_sees = self.client.get("/v2/chats", headers=self._as(PIOTR)).get_json()["chats"]
        tomek_sees = self.client.get("/v2/chats", headers=self._as(TOMEK)).get_json()["chats"]
        self.assertEqual([(c["id"], c["title"]) for c in piotr_sees], [(chat, "Tomek")])
        self.assertEqual([(c["id"], c["title"]) for c in tomek_sees], [(chat, "Piotr")])

    def test_my_own_link_is_refused(self):
        token = self._link(TOMEK).get_json()["token"]
        res = self._join(TOMEK, token)
        self.assertEqual((res.status_code, res.get_json()["code"]), (400, "OWN_LINK"))
        self.assertEqual(self.store.count("chat_threads"), 0)

    def test_without_the_ring_nothing_is_written(self):
        token = self._link(TOMEK).get_json()["token"]
        for res in (self._link(NOBODY), self._join(NOBODY, token),
                    self.client.post("/v2/chats/link", headers=self._as(NOBODY))):
            self.assertEqual((res.status_code, res.get_json()["code"]), (404, "NOT_FOUND"))
        self.assertEqual(self.store.count("chat_links"), 1)
        self.assertEqual(self.store.count("chat_threads"), 0)

    def test_the_one_who_joined_sees_whose_link_it_was(self):
        token = self._link(TOMEK).get_json()["token"]
        chat = self._join(PIOTR, token).get_json()["chat"]["id"]
        joined = self.client.get(f"/v2/chats/{chat}/messages", headers=self._as(PIOTR)).get_json()
        owner = self.client.get(f"/v2/chats/{chat}/messages", headers=self._as(TOMEK)).get_json()
        self.assertEqual((joined["messages"], joined["joined_through"]), ([], "Tomek"))
        self.assertIsNone(owner["joined_through"])


if __name__ == "__main__":
    unittest.main()
