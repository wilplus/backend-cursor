"""
STORY    As a host, I want one recording to answer everyone who asked me the
         same thing, so that I answer a question once and everyone who asks it,
         now or later, gets my answer in their own chat with me (N584).
OUTCOME
  O1  Questions that ask the same thing gather in one bundle in my queue:
      "Ariel asked: ...", then "2 people asked: ...", each person's question
      with its colour, and "Record one answer"; a different question starts
      its own bundle.
  O2  My one recording goes to everyone in the bundle, each privately in
      their own chat with me, under their own question quoted; nobody gets
      it twice.
  O3  Someone who asks the same thing later gets my answer at once, with its
      colour for how sure the match is.
  O4  Without the chat builder's ring nothing is bundled and the queue is 404.
PROVES   O1 -> BundlesTest::test_questions_that_ask_the_same_thing_gather_in_one_bundle
         O2 -> BundlesTest::test_one_recording_answers_everyone_in_the_bundle
         O3 -> BundlesTest::test_a_later_asker_gets_the_answer_at_once
         O4 -> BundlesTest::test_without_the_ring_nothing_is_bundled
WHY      "how do we bundle the people who have similar questions ... so that I
         can answer it to that whole group with my one recording?" (founder,
         9 November 2026, N584).
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.question_bundles import likeness
from tests import test_chats as TC
from tests.test_chats import ME, OTHER, SOMEONE

THIRD = "44444444-4444-4444-8444-444444444444"
TAKE = "55555555-5555-4555-8555-555555555555"
UM = "How do I stop saying um in meetings?"


def _ring(on_for):
    def check(feature, user_id, database=None):
        del database
        return feature == "chat_builder" and str(user_id) in on_for
    return check


class BundlesTest(unittest.TestCase):
    setUp_ = TC.ChatsTest.setUp
    _get, _post, _voice = TC.ChatsTest._get, TC.ChatsTest._post, TC.ChatsTest._voice

    def setUp(self):
        self.setUp_()
        p = patch("services.rings.feature_is_on_for_user", _ring({ME}))
        p.start()
        self.addCleanup(p.stop)

    def _chat_with(self, who, name):
        thread = self.store.table("chat_threads").insert(
            {"kind": "team", "title": name}).execute().data[0]["id"]
        self.store.table("chat_members").insert([
            {"thread_id": thread, "user_id": ME, "display_name": "Artur"},
            {"thread_id": thread, "user_id": who, "display_name": name}]).execute()
        return thread

    def _ask(self, who, thread, words):
        self.who, self.said = who, words
        self.assertEqual(self._voice(thread).status_code, 200)

    def _queue(self):
        self.who = ME
        return self._get("/v2/chats/bundles").get_json()["bundles"]

    def _answers_in(self, who, thread):
        self.who = who
        return [m for m in self._get(f"/v2/chats/{thread}/messages").get_json()["messages"]
                if (m.get("meta") or {}).get("bundle")]

    def test_questions_that_ask_the_same_thing_gather_in_one_bundle(self):
        ariel, ola = self._chat_with(SOMEONE, "Ariel"), self._chat_with(OTHER, "Ola")
        self._ask(SOMEONE, ariel, UM)
        queue = self._queue()
        self.assertEqual([(b["line"], b["record"]) for b in queue],
                         [(f"Ariel asked: {UM}", "Record one answer")])
        self._ask(OTHER, ola, "How can I stop saying um when I present?")
        self._ask(OTHER, ola, "Which slide template do you use?")
        lines = sorted(b["line"] for b in self._queue())
        self.assertEqual(lines, [f"2 people asked: {UM}",
                                 "Ola asked: Which slide template do you use?"])
        both = next(b for b in self._queue() if b["line"].startswith("2 people"))
        self.assertEqual([(q["name"], q["mark"]) for q in both["questions"]],
                         [("Ariel", "green"), ("Ola", "yellow")])
        self.assertGreaterEqual(likeness(UM, "How can I stop saying um when I present?"), 0.5)

    def test_one_recording_answers_everyone_in_the_bundle(self):
        ariel, ola = self._chat_with(SOMEONE, "Ariel"), self._chat_with(OTHER, "Ola")
        self._ask(SOMEONE, ariel, UM)
        self._ask(OTHER, ola, "How can I stop saying um when I present?")
        self.store.table("recordings").insert({"session_v2_id": TAKE, "user_id": ME,
                                               "storage_path": "lab/a.webm", "duration": 40}).execute()
        bundle = self._queue()[0]["id"]
        self.who = ME
        self.assertEqual(self._post(f"/v2/chats/bundles/{bundle}/answer", {"take": TAKE}).get_json(),
                         {"sent": 2})
        got = self._answers_in(SOMEONE, ariel)
        self.assertEqual([(m["kind"], m["meta"]["quote"]["words"]) for m in got], [("voice", UM)])
        self.assertEqual(self._answers_in(OTHER, ola)[0]["meta"]["quote"]["words"],
                         "How can I stop saying um when I present?")
        self.who = ME
        self.assertEqual(self._post(f"/v2/chats/bundles/{bundle}/answer", {"take": TAKE}).get_json(),
                         {"sent": 0})
        self.assertEqual(self._queue()[0]["record"], None)

    def test_a_later_asker_gets_the_answer_at_once(self):
        ariel = self._chat_with(SOMEONE, "Ariel")
        self._ask(SOMEONE, ariel, UM)
        self.store.table("recordings").insert({"session_v2_id": TAKE, "user_id": ME,
                                               "storage_path": "lab/a.webm", "duration": 40}).execute()
        self.who = ME
        self._post(f"/v2/chats/bundles/{self._queue()[0]['id']}/answer", {"take": TAKE})
        later = self._chat_with(THIRD, "Kasia")
        self._ask(THIRD, later, "How do I stop saying um in my meetings?")
        got = self._answers_in(THIRD, later)
        self.assertEqual([m["meta"]["mark"] for m in got], ["green"])
        self.assertEqual(self._queue()[0]["line"], f"2 people asked: {UM}")

    def test_without_the_ring_nothing_is_bundled(self):
        with patch("services.rings.feature_is_on_for_user", _ring(set())):
            ariel = self._chat_with(SOMEONE, "Ariel")
            self._ask(SOMEONE, ariel, UM)
            self.who = ME
            self.assertEqual(self._get("/v2/chats/bundles").status_code, 404)
        self.assertEqual(self.store.count("question_bundles"), 0)


if __name__ == "__main__":
    unittest.main()
