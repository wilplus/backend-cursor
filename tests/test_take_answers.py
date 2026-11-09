"""
STORY    As a speaker who sent a Take to my coach and to others, I want their
         answers gathered under my Take, so that I see my coach's answer and
         the best of the others in one place, and only I see the gathering
         (N587 items 3 to 5, N588 item 4).
OUTCOME
  O1  Under my Take, one bubble shows my coach's answer and the best other
      answer under each heading, with the names of everyone who answered;
      all of them open under "On your speaking" and "On the matter", each
      with the way into that person's chat.
  O2  Someone who has not answered is not listed; a Take I never sent is 404,
      and so is anyone else's Take.
PROVES   O1 -> TakeAnswersTest::test_the_answers_gather_under_my_take
         O2 -> TakeAnswersTest::test_only_answers_to_my_own_sent_take
WHY      "if you send them the request and they all answered, you should be
         able to receive all of them" (founder, 9 November 2026, N587).
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from tests import test_chats as TC
from tests.test_chats import ME, OTHER, SOMEONE

THIRD = "44444444-4444-4444-8444-444444444444"
TAKE = "55555555-5555-4555-8555-555555555555"


def _ring(feature, user_id, database=None):
    del database
    return feature == "chat_builder" and str(user_id) == ME


class TakeAnswersTest(unittest.TestCase):
    setUp_ = TC.ChatsTest.setUp
    _get = TC.ChatsTest._get

    def setUp(self):
        self.setUp_()
        p = patch("services.rings.feature_is_on_for_user", _ring)
        p.start()
        self.addCleanup(p.stop)
        self.store.table("people_profiles").insert(
            {"user_id": OTHER, "chat_recipe": {"fit": {"coaches": "topic", "needs": "any",
                                                       "topics": ["programming"]}}}).execute()

    def _chat(self, who, name):
        thread = self.store.table("chat_threads").insert(
            {"kind": "team", "title": name}).execute().data[0]["id"]
        rows = self.store.table("chat_members").insert([
            {"thread_id": thread, "user_id": ME, "display_name": "Kasia"},
            {"thread_id": thread, "user_id": who, "display_name": name}]).execute().data
        return thread, {r["user_id"]: r["id"] for r in rows}

    def _write(self, thread, member, kind, meta=None):
        self.store.table("chat_messages").insert({"thread_id": thread, "author_member_id": member,
                                                  "kind": kind, "body": "", "meta": meta or {}}).execute()

    def _sent(self, who, name, answers=True):
        thread, members = self._chat(who, name)
        self._write(thread, members[ME], "take", {"take_session_id": TAKE})
        if answers:
            self._write(thread, members[who], "voice", {"duration_ms": 3000})
        return thread

    def test_the_answers_gather_under_my_take(self):
        artur = self._sent(SOMEONE, "Artur Wilk")
        ola = self._sent(OTHER, "Ola")
        ariel = self._sent(THIRD, "Ariel")
        got = self._get(f"/v2/user/takes/{TAKE}/answers").get_json()
        self.assertEqual([(a["name"], a["chat"]) for a in got["bubble"]["shown"]],
                         [("Artur", artur), ("Ariel", ariel), ("Ola", ola)])
        self.assertEqual(got["bubble"]["faces"], ["Artur", "Ola", "Ariel"])
        self.assertEqual([(g["title"], [a["name"] for a in g["answers"]]) for g in got["groups"]],
                         [("On your speaking", ["Artur", "Ariel"]), ("On the matter", ["Ola"])])

    def test_only_answers_to_my_own_sent_take(self):
        self._sent(SOMEONE, "Artur")
        self._sent(OTHER, "Ola", answers=False)
        got = self._get(f"/v2/user/takes/{TAKE}/answers").get_json()
        self.assertEqual(got["bubble"]["faces"], ["Artur"])
        other_take = "66666666-6666-4666-8666-666666666666"
        self.assertEqual(self._get(f"/v2/user/takes/{other_take}/answers").status_code, 404)
        self.who = SOMEONE
        with patch("services.rings.feature_is_on_for_user", lambda *a, **k: True):
            self.assertEqual(self._get(f"/v2/user/takes/{TAKE}/answers").status_code, 404)


if __name__ == "__main__":
    unittest.main()
