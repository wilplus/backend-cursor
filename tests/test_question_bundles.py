"""
STORY    As a host, I want one recording to answer everyone who asked me the
         same thing, so that I answer a question once and everyone who asks it,
         now or later, gets my answer in their own chat with me (N584).
OUTCOME
  O1  Questions that ask the same thing gather in one card in Will's chat
      (N602): "2 people asked", the question large, "Ariel and Ola", "See
      who asked" and "Record one answer"; "See who asked" opens "Who asked",
      each person's own words, name and where they asked ("in your chat",
      "on your website"), then "Split them up"; a different question starts
      its own card.
  O2  My one recording goes to everyone in the bundle, each privately in
      their own chat with me, under their own question quoted; nobody gets
      it twice.
  O3  Someone who asks the same thing later joins the bundle and waits for
      me: my assistant sends nothing by itself yet (N606). The card is back
      with "Record one answer", and my next recording reaches only them.
  O4  Without the chat builder's ring nothing is bundled and the queue is 404.
  O5  My own voice replies in my chats are never bundled as questions.
  O6  My recorded answer reaches each asker's iPhone like any answer.
  O7  "Record one answer" asks my recording consent again: withdrawn, nothing
      is sent.
  O8  When an asker's account is erased, their words leave the bundle: it
      reads as the next question, and nothing of theirs is kept.
PROVES   O1 -> BundlesTest::test_questions_that_ask_the_same_thing_gather_in_one_bundle
         O2 -> BundlesTest::test_one_recording_answers_everyone_in_the_bundle
         O3 -> BundlesTest::test_a_later_asker_waits_for_me
         O4 -> BundlesTest::test_without_the_ring_nothing_is_bundled
         O1 -> BundlesTest::test_the_card_names_two_and_how_many_more_and_where_they_asked
         O5 -> BundlesTest::test_my_own_replies_are_never_bundled
         O6 -> BundlesTest::test_a_later_asker_waits_for_me
         O7 -> BundlesTest::test_one_answer_asks_my_recording_consent_again
         O8 -> BundlesTest::test_an_erased_askers_words_leave_the_bundle
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

    def _chat_with(self, who, name, website=False):
        if website:
            # A website visitor's chat with me (N591 item 1).
            thread = self.store.table("chat_threads").insert(
                {"kind": "team", "title": name, "widget_owner_id": ME}).execute().data[0]["id"]
            self.store.table("chat_members").insert([
                {"thread_id": thread, "user_id": ME, "display_name": "Artur"},
                {"thread_id": thread, "user_id": who, "display_name": name}]).execute()
            return thread
        # A chat made through my link: I am its host (N578 item 1).
        if not self.store.tables.get("chat_links"):
            self.store.table("chat_links").insert({"user_id": ME, "token": "t" * 24,
                                                   "display_name": "Artur"}).execute()
        link = self.store.tables["chat_links"][0]["id"]
        thread = self.store.table("chat_threads").insert(
            {"kind": "team", "title": name, "link_id": link}).execute().data[0]["id"]
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
        self.assertEqual([(b["title"], b["question"], b["record"]) for b in queue],
                         [("Ariel asked", UM, "Record one answer")])
        self._ask(OTHER, ola, "How can I stop saying um when I present?")
        self._ask(OTHER, ola, "Which slide template do you use?")
        cards = sorted((b["title"], b["question"]) for b in self._queue())
        self.assertEqual(cards, [("2 people asked", UM),
                                 ("Ola asked", "Which slide template do you use?")])
        both = next(b for b in self._queue() if b["title"] == "2 people asked")
        self.assertEqual((both["who"], both["see"], both["record"]),
                         ("Ariel and Ola", "See who asked", "Record one answer"))
        self.assertNotIn("questions", both)
        sheet = self._get(f"/v2/chats/bundles/{both['id']}").get_json()
        self.assertEqual((sheet["title"], sheet["split"]), ("Who asked", "Split them up"))
        self.assertEqual([(p["name"], p["words"], p["where"], p["mark"]) for p in sheet["people"]],
                         [("Ariel", UM, "in your chat", "green"),
                          ("Ola", "How can I stop saying um when I present?", "in your chat", "yellow")])
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

    def test_a_later_asker_waits_for_me(self):
        ariel = self._chat_with(SOMEONE, "Ariel")
        self._ask(SOMEONE, ariel, UM)
        self.store.table("recordings").insert({"session_v2_id": TAKE, "user_id": ME,
                                               "storage_path": "lab/a.webm", "duration": 40}).execute()
        bundle = self._queue()[0]["id"]
        self.who = ME
        self._post(f"/v2/chats/bundles/{bundle}/answer", {"take": TAKE})
        later = self._chat_with(THIRD, "Kasia")
        self._ask(THIRD, later, "How do I stop saying um in my meetings?")
        self.assertEqual(self._answers_in(THIRD, later), [])  # N606: nothing by itself
        card = self._queue()[0]
        self.assertEqual((card["title"], card["answered"], card["record"]),
                         ("2 people asked", False, "Record one answer"))
        self.who = ME
        with patch("services.push_devices.push_later") as push:
            self.assertEqual(self._post(f"/v2/chats/bundles/{bundle}/answer",
                                        {"take": TAKE}).get_json(), {"sent": 1})
        self.assertIn(THIRD, [c.args[1] for c in push.call_args_list])
        self.assertEqual([m["meta"]["mark"] for m in self._answers_in(THIRD, later)], ["green"])
        self.assertEqual(len(self._answers_in(SOMEONE, ariel)), 1)

    def test_the_card_names_two_and_how_many_more_and_where_they_asked(self):
        people = [(SOMEONE, "Ariel", False), (OTHER, "Ola", False), (THIRD, "Kasia", True),
                  ("66666666-6666-4666-8666-666666666666", "Lena", False)]
        for who, name, website in people:
            self._ask(who, self._chat_with(who, name, website), UM)
        card = self._queue()[0]
        self.assertEqual((card["title"], card["who"]), ("4 people asked", "Ariel, Ola and 2 more"))
        sheet = self._get(f"/v2/chats/bundles/{card['id']}").get_json()
        self.assertEqual([(p["name"], p["where"]) for p in sheet["people"]],
                         [("Ariel", "in your chat"), ("Ola", "in your chat"),
                          ("Kasia", "on your website"), ("Lena", "in your chat")])

    def test_my_own_replies_are_never_bundled(self):
        ariel = self._chat_with(SOMEONE, "Ariel")
        self._ask(ME, ariel, "How do I stop saying um in meetings? Good question, here is how.")
        self.assertEqual(self._queue(), [])

    def test_one_answer_asks_my_recording_consent_again(self):
        ariel = self._chat_with(SOMEONE, "Ariel")
        self._ask(SOMEONE, ariel, UM)
        self.store.table("recordings").insert({"session_v2_id": TAKE, "user_id": ME,
                                               "storage_path": "lab/a.webm", "duration": 40}).execute()
        bundle = self._queue()[0]["id"]
        self.choices["sensitive_information"] = False
        res = self._post(f"/v2/chats/bundles/{bundle}/answer", {"take": TAKE})
        self.assertEqual((res.status_code, res.get_json()["code"]), (403, "PROCESSING_RECORDING_WITHDRAWN"))
        self.assertEqual(self._answers_in(SOMEONE, ariel), [])

    def test_an_erased_askers_words_leave_the_bundle(self):
        from services.data_purge_registry import dependency_by_code
        ariel, ola = self._chat_with(SOMEONE, "Ariel"), self._chat_with(OTHER, "Ola")
        self._ask(SOMEONE, ariel, UM)
        self._ask(OTHER, ola, "How can I stop saying um when I present?")
        # The purge deletes the asker's rows by the registry's selector.
        dep = dependency_by_code("question_bundle_askers")
        self.assertEqual((dep.relation, dep.selector_column, dep.disposition),
                         ("question_bundle_askers", "asker_id", "delete"))
        rows = self.store.tables["question_bundle_askers"]
        self.store.tables["question_bundle_askers"] = [r for r in rows if r["asker_id"] != SOMEONE]
        self.assertEqual([(b["title"], b["question"]) for b in self._queue()],
                         [("Ola asked", "How can I stop saying um when I present?")])
        self.assertNotIn(UM, repr(self.store.tables["question_bundles"]))

    def test_without_the_ring_nothing_is_bundled(self):
        with patch("services.rings.feature_is_on_for_user", _ring(set())):
            ariel = self._chat_with(SOMEONE, "Ariel")
            self._ask(SOMEONE, ariel, UM)
            self.who = ME
            self.assertEqual(self._get("/v2/chats/bundles").status_code, 404)
        self.assertEqual(self.store.count("question_bundles"), 0)


if __name__ == "__main__":
    unittest.main()
