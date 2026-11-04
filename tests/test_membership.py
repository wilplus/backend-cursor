"""
STORY    As the founder, I want WillpowerLab to be by invitation: a person's
         link is the only way in, and without one a person joins the
         waitlist and I answer by email (N471).
OUTCOME
  O1  While the switch is off, everyone is a member, as before.
  O2  An account from before the switch is a member; a new account is on
      the waitlist, and its first ask sends one email to the founder's
      inbox, which a reply answers; asking again sends no second email.
  O3  A new account that joins through a member's link is let in at once,
      and so is one with a Take from before the switch.
  O4  A waiting account's link opens nothing: the same answer as a wrong
      link.
  O5  After the day's number of people join through one person's link, the
      next one goes to the waitlist and no chat is made.
  O6  A waiting account cannot start a project or record; a guest cannot
      start one either, and no new guest identity is made.
PROVES   O1 -> MembershipTest::test_while_the_switch_is_off_everyone_is_in
         O2 -> MembershipTest::test_a_new_account_waits_and_the_founder_gets_one_email
         O3 -> MembershipTest::test_joining_through_a_members_link_lets_a_new_account_in
         O3 -> MembershipTest::test_a_take_from_before_the_switch_lets_a_guest_in
         O4 -> MembershipTest::test_a_waiting_accounts_link_opens_nothing
         O5 -> MembershipTest::test_past_the_days_joins_the_next_one_waits
         O6 -> MembershipTest::test_only_members_start_a_project_and_guests_do_not
WHY      The founder's decision of 4 November 2026 (N471): members only,
         links as the one way in, the waitlist answered by hand.
"""
from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from services import membership
from services.db import db
from tests.test_chats import _Store

ARTUR = "11111111-1111-4111-8111-111111111111"   # here before the switch
MARIA = "22222222-2222-4222-8222-222222222222"   # new, no link yet
TOMEK = "33333333-3333-4333-8333-333333333333"   # new
SWITCH = datetime(2026, 11, 5, 9, 0, tzinfo=timezone.utc)
MADE = {ARTUR: SWITCH - timedelta(days=30), MARIA: SWITCH + timedelta(hours=1),
        TOMEK: SWITCH + timedelta(hours=2)}
NAMES = {ARTUR: ("Artur Willoński", "artur@example.com"),
         MARIA: ("Maria K.", "maria.k@example.com"),
         TOMEK: ("Tomek Nowak", "tomek@example.com")}


class _Auth:
    """Supabase Auth's admin API for the three accounts, in memory."""

    def __init__(self):
        self.meta = {uid: {"provider": "google"} for uid in MADE}
        self.updates = []
        self.auth = SimpleNamespace(admin=self)

    def get_user_by_id(self, uid):
        name, email = NAMES[uid]
        user = SimpleNamespace(id=uid, email=email, phone="", created_at=MADE[uid].isoformat(),
                               user_metadata={"full_name": name}, app_metadata=dict(self.meta[uid]))
        return SimpleNamespace(user=user)

    def update_user_by_id(self, uid, attributes):
        self.updates.append(uid)
        self.meta[uid] = dict(attributes["app_metadata"])


class MembershipTest(unittest.TestCase):
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
        self.auth = _Auth()
        self.sent = []
        self.who = ARTUR

        def payload(_token):
            name, email = NAMES[self.who]
            return {"sub": self.who, "email": email, "user_metadata": {"full_name": name}}

        def send(**kwargs):
            self.sent.append(kwargs)
            return {"id": "e1"}

        for p in (patch.object(auth, "verify_supabase_token", payload),
                  patch.object(db, "client", self.store),
                  patch("services.db.new_client", lambda: self.auth),
                  patch("services.email_service.send_email_resend", send),
                  patch.object(membership, "_staff", lambda _uid: False),
                  patch.dict(os.environ, {"PLF1_PROCESSING_AUTHORIZATION_MODE": "off",
                                          "INVITE_ONLY_SINCE": SWITCH.isoformat(),
                                          "INVITE_LINK_DAILY_LIMIT": "2"})):
            p.start()
            self.addCleanup(p.stop)
        membership.forget()
        self.addCleanup(membership.forget)

    def _as(self, who):
        self.who = who
        return {"Authorization": "Bearer t"}

    def _access(self, who):
        return self.client.get("/v2/me/access", headers=self._as(who)).get_json()

    def _link(self, who):
        return self.client.get("/v2/chats/link", headers=self._as(who)).get_json()["token"]

    def _join(self, who, token):
        return self.client.post(f"/v2/chats/join/{token}", headers=self._as(who))

    def test_while_the_switch_is_off_everyone_is_in(self):
        with patch.dict(os.environ, {"INVITE_ONLY_SINCE": ""}):
            self.assertEqual(self._access(MARIA), {"member": True, "invite_only": False})
        self.assertEqual(self.sent, [])

    def test_a_new_account_waits_and_the_founder_gets_one_email(self):
        self.assertEqual(self._access(ARTUR), {"member": True, "invite_only": True})
        self.assertEqual(self._access(MARIA), {"member": False, "invite_only": True})
        self.assertEqual(len(self.sent), 1)
        email = self.sent[0]
        self.assertEqual(email["to"], "contact@willpowerlab.com")
        self.assertEqual(email["subject"], "Maria K. wants to join WillpowerLab")
        self.assertEqual(email["headers"], {"Reply-To": "maria.k@example.com"})
        self.assertIn("To let Maria K. in, reply with your link.", email["text"])
        self.assertIn("with Google", email["text"])
        membership.forget()
        self.assertFalse(self._access(MARIA)["member"])
        self.assertEqual(len(self.sent), 1)

    def test_joining_through_a_members_link_lets_a_new_account_in(self):
        self.assertFalse(self._access(MARIA)["member"])
        res = self._join(MARIA, self._link(ARTUR))
        self.assertEqual(res.status_code, 200)
        self.assertIn("chat", res.get_json())
        self.assertTrue(self._access(MARIA)["member"])
        membership.forget()
        self.assertTrue(self._access(MARIA)["member"])

    def test_a_take_from_before_the_switch_lets_a_guest_in(self):
        self.store.table("v2_sessions").insert(
            {"user_id": MARIA, "created_at": (SWITCH - timedelta(days=1)).isoformat()}).execute()
        self.assertTrue(self._access(MARIA)["member"])
        self.assertEqual(self.sent, [])

    def test_a_waiting_accounts_link_opens_nothing(self):
        res = self._join(TOMEK, self._link(MARIA))
        self.assertEqual((res.status_code, res.get_json()["code"]), (404, "NOT_FOUND"))
        self.assertEqual(self.store.count("chat_threads"), 0)

    def test_past_the_days_joins_the_next_one_waits(self):
        token = self._link(ARTUR)
        third = "44444444-4444-4444-8444-444444444444"
        MADE[third], NAMES[third] = SWITCH + timedelta(hours=3), ("Ola", "ola@example.com")
        self.auth.meta[third] = {"provider": "email"}
        self.addCleanup(MADE.pop, third)
        self.addCleanup(NAMES.pop, third)
        self.assertIn("chat", self._join(MARIA, token).get_json())
        self.assertIn("chat", self._join(TOMEK, token).get_json())
        res = self._join(third, token)
        self.assertEqual((res.status_code, res.get_json()), (200, {"waitlist": True}))
        self.assertEqual(self.store.count("chat_threads"), 2)
        self.assertFalse(self._access(third)["member"])

    def test_only_members_start_a_project_and_guests_do_not(self):
        waiting = self.client.post("/v2/projects", headers=self._as(MARIA), json={"display_name": "Talk"})
        self.assertEqual((waiting.status_code, waiting.get_json()["code"]), (403, "WAITLIST"))
        guest = self.client.post("/v2/projects", json={"display_name": "Talk"})
        self.assertEqual((guest.status_code, guest.get_json()["code"]), (401, "INVITE_ONLY"))
        minted = self.client.post("/v2/processing-authorization/principal")
        self.assertEqual((minted.status_code, minted.get_json()["code"]), (401, "INVITE_ONLY"))


if __name__ == "__main__":
    unittest.main()
