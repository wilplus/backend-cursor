"""
STORY    As a person in WillpowerLab, I want a profile as on WhatsApp, my
         name, who I am, my About and my photo, that the people I chat with
         see, with the photos and files we shared (N366).
OUTCOME
  O1  My profile starts with my account's name; I change my name, who I am
      and my About, and the person I chat with sees them, my new name as the
      chat's title too.
  O2  An empty name or anything over its limit is refused, and nothing is
      kept.
  O3  My photo is kept and shown to me and to the person I chat with; anyone
      not in a chat with me gets 404; I can take it away.
  O4  Their profile lists the photos and files shared in our chat; mine
      lists what I sent in any chat.
  O5  As a user with no ring at all, I have my profile (N456; was ring 6
      only).
PROVES   O1 -> PeopleProfilesTest::test_i_change_my_name_and_about_and_they_see_it
         O2 -> PeopleProfilesTest::test_an_empty_name_or_too_long_is_refused
         O3 -> PeopleProfilesTest::test_my_photo_is_shown_to_the_person_i_chat_with_only
         O4 -> PeopleProfilesTest::test_the_photos_and_files_we_shared_are_on_the_profiles
         O5 -> PeopleProfilesTest::test_as_a_user_without_any_ring_I_have_my_profile
WHY      A person's profile, as on WhatsApp (founder 2026-11-03, N366; locked
         in docs/LOCKS.md with the prototype "One bar").
"""
from __future__ import annotations

import io
import os
import unittest
from unittest.mock import patch

from services.db import db
from tests.test_chats import _Store

TOMEK = "11111111-1111-4111-8111-111111111111"
PIOTR = "22222222-2222-4222-8222-222222222222"
#: Signed in, in no chat with Tomek.
ANNA = "33333333-3333-4333-8333-333333333333"
NAMES = {TOMEK: ("Tomek Nowak", "tomek@example.com"),
         PIOTR: ("Piotr Kowalski", "piotr@example.com"),
         ANNA: ("Anna", "anna@example.com")}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


class PeopleProfilesTest(unittest.TestCase):
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

        def payload(_token):
            name, email = NAMES[self.who]
            return {"sub": self.who, "email": email, "user_metadata": {"full_name": name}}

        for p in (patch.object(auth, "verify_supabase_token", payload),
                  patch.object(db, "client", self.store),
                  patch.dict(os.environ, {"PLF1_PROCESSING_AUTHORIZATION_MODE": "off"})):
            p.start()
            self.addCleanup(p.stop)

    def _as(self, who):
        self.who = who
        return {"Authorization": "Bearer t"}

    def _chat(self):
        """Tomek and Piotr in one chat, made through Tomek's link."""
        token = self.client.get("/v2/chats/link", headers=self._as(TOMEK)).get_json()["token"]
        return self.client.post(f"/v2/chats/join/{token}", headers=self._as(PIOTR)).get_json()["chat"]["id"]

    def test_i_change_my_name_and_about_and_they_see_it(self):
        chat = self._chat()
        mine = self.client.get("/v2/profile", headers=self._as(TOMEK)).get_json()
        self.assertEqual((mine["name"], mine["role"], mine["about"]), ("Tomek Nowak", None, None))
        saved = self.client.patch("/v2/profile", headers=self._as(TOMEK), json={
            "name": "Tomasz", "role": "AI ambassador · Editorial",
            "about": "I help colleagues use AI in their editing."}).get_json()
        self.assertEqual((saved["name"], saved["role"]), ("Tomasz", "AI ambassador · Editorial"))
        self.assertIsNotNone(saved["about_edited_at"])
        theirs = self.client.get(f"/v2/chats/{chat}/profile", headers=self._as(PIOTR)).get_json()
        self.assertEqual((theirs["name"], theirs["role"], theirs["about"]),
                         ("Tomasz", "AI ambassador · Editorial", "I help colleagues use AI in their editing."))
        self.assertEqual(theirs["user_id"], TOMEK)
        titles = [c["title"] for c in self.client.get("/v2/chats", headers=self._as(PIOTR)).get_json()["chats"]]
        self.assertEqual(titles, ["Tomasz"])

    def test_an_empty_name_or_too_long_is_refused(self):
        for body in ({"name": "  "}, {"role": "x" * 61}, {"about": "x" * 301}):
            res = self.client.patch("/v2/profile", headers=self._as(TOMEK), json=body)
            self.assertEqual((res.status_code, res.get_json()["code"]), (400, "NOT_ALLOWED"))
        self.assertEqual(self.store.count("people_profiles"), 0)

    def test_my_photo_is_shown_to_the_person_i_chat_with_only(self):
        chat = self._chat()
        sent = self.client.put("/v2/profile/photo", headers=self._as(TOMEK),
                               data={"file": (io.BytesIO(PNG), "me.png", "image/png")},
                               content_type="multipart/form-data")
        self.assertEqual(sent.get_json(), {"has_photo": True})
        self.assertEqual(self.client.get("/v2/profile/photo", headers=self._as(TOMEK)).data, PNG)
        self.assertEqual(self.client.get(f"/v2/chats/{chat}/profile/photo", headers=self._as(PIOTR)).data, PNG)
        self.assertEqual(self.client.get(f"/v2/chats/{chat}/profile/photo", headers=self._as(ANNA)).status_code, 404)
        self.client.delete("/v2/profile/photo", headers=self._as(TOMEK))
        self.assertEqual(self.client.get("/v2/profile/photo", headers=self._as(TOMEK)).status_code, 404)

    def test_the_photos_and_files_we_shared_are_on_the_profiles(self):
        chat = self._chat()
        self.client.post(f"/v2/chats/{chat}/photo", headers=self._as(TOMEK),
                         data={"file": (io.BytesIO(PNG), "cut.png", "image/png")},
                         content_type="multipart/form-data")
        self.client.post(f"/v2/chats/{chat}/file", headers=self._as(PIOTR),
                         data={"file": (io.BytesIO(b"%PDF-1"), "Guidelines.pdf", "application/pdf")},
                         content_type="multipart/form-data")
        theirs = self.client.get(f"/v2/chats/{chat}/profile", headers=self._as(PIOTR)).get_json()
        self.assertEqual((len(theirs["photos"]), [f["name"] for f in theirs["files"]]), (1, ["Guidelines.pdf"]))
        mine = self.client.get("/v2/profile", headers=self._as(TOMEK)).get_json()
        self.assertEqual((len(mine["photos"]), mine["files"]), (1, []))

    def test_as_a_user_without_any_ring_I_have_my_profile(self):
        # The rings are never asked: the chats are everyone's (N456).
        def no_ring(*_args, **_kwargs):
            raise AssertionError("the profile asked the rings")
        with patch("services.rings.feature_is_on_for_user", no_ring):
            res = self.client.get("/v2/profile", headers=self._as(TOMEK))
        self.assertEqual(res.status_code, 200)


if __name__ == "__main__":
    unittest.main()
