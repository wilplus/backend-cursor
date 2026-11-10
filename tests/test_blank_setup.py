"""
STORY    As someone who knows a field, I want to set up a chat with Will from
         a blank start, one decision per screen, and open it; and as a person
         who comes to it, I want to get back what that host chose (N612 to
         N618; the locked prototype docs/design/the-blank-setup-2026-11-10/,
         its stories FIRST-*, VIS-* and TOK-*; the contract in backend PR #1893; N633
         items 1, 2 and 4).
OUTCOME  One test per story, on the public routes; the story id leads each
         test's docstring.
PROVES   FIRST-02 -> SetupTest::test_will_asks_what_you_do_and_works_out_the_choices
         FIRST-03 -> SetupTest::test_one_decision_per_screen_keep_or_change
         FIRST-04 -> SetupTest::test_what_people_send_several_ticked
         FIRST-05 -> SetupTest::test_they_get_back_an_answer_unless_will_suggests_otherwise
         FIRST-06 -> SetupTest::test_the_hello_questions_and_taps_pass_the_hosts_checks
         FIRST-07 -> SetupTest::test_a_model_is_one_question_with_three_answers
         FIRST-08 -> SetupTest::test_a_model_made_here_is_a_real_model_teach_it_opens
         FIRST-23 -> SetupTest::test_the_host_adds_an_example_and_answers_it_first
         FIRST-09 -> SetupTest::test_who_answers_is_three_plain_choices
         FIRST-10 -> SetupTest::test_sharing_keeps_a_price_in_tokens
         FIRST-11 -> VisitorTest::test_not_yet_keeps_it_saved_and_yes_opens_it
         FIRST-13 -> SetupTest::test_models_you_can_use_are_others_shared_models
         FIRST-14 -> SetupTest::test_what_your_chat_costs_you
         FIRST-15 -> SetupTest::test_health_law_or_money_is_yes_until_the_host_says_no
         FIRST-16 -> SetupTest::test_a_new_host_starts_blank_even_without_a_provider
         FIRST-17 -> SetupTest::test_not_now_leaves_the_chat_without_models
         FIRST-18 -> SetupTest::test_two_ways_use_one_or_train_your_own
         FIRST-20 -> SetupTest::test_test_my_chat_answers_as_my_people_would
         FIRST-21 -> SetupTest::test_to_change_the_chat_tell_will
         FIRST-22 -> SetupTest::test_who_answers_is_three_plain_choices
         VIS-01   -> VisitorTest::test_the_hosts_hello_first_questions_and_taps
         VIS-02   -> VisitorTest::test_the_bar_follows_what_the_host_takes
         VIS-03   -> VisitorTest::test_they_get_back_the_output_the_host_chose
         VIS-04   -> VisitorTest::test_each_models_line_names_whose_model_it_is
         VIS-05   -> VisitorTest::test_was_this_useful_never_blocks_the_next_one
         VIS-06   -> VisitorTest::test_before_the_minimum_the_question_waits_for_the_host
         VIS-07   -> VisitorTest::test_in_a_health_law_or_money_chat_the_model_only_suggests
         TOK-01   -> TokensTest::test_a_host_pays_when_someone_elses_model_runs_in_their_chat
         TOK-01   -> TokensTest::test_the_same_message_delivered_twice_is_charged_once
         TOK-02   -> TokensTest::test_out_of_tokens_the_model_is_skipped_and_the_chat_goes_on
         TOK-02   -> TokensTest::test_with_token_pricing_off_nothing_is_charged_or_skipped
         N630.3   -> TokensTest::test_a_host_pays_the_price_shown_when_they_added_the_model
         FIRST-24 -> LearningTest::test_a_model_still_learning_is_listed_free_and_its_host_teaches_it
         FIRST-24 -> LearningTest::test_it_says_nothing_costs_nothing_and_the_hosts_own_words_teach_it
         FIRST-24 -> LearningTest::test_once_it_passes_the_host_keeps_it_at_the_price_they_see
         VIS-08   -> MeetTest::test_the_hello_shows_once_in_the_chat_they_share
         VIS-08   -> MeetTest::test_each_writes_to_the_others_chat_both_ways
         VIS-08   -> MeetTest::test_without_the_other_persons_open_chat_nothing_changes
WHY      The build succeeds when a stranger sets up a chat with Will and a
         second person gets a useful answer in it (N620).
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tests import test_chat_links as TL
from tests.test_assistants import _ring
from tests.test_chat_links import PIOTR, TOMEK

H = {"Authorization": "Bearer t"}


class _Provider:
    """The provider behind ``chat_complete``: counts the calls and answers
    the test's JSON (or fails)."""

    def __init__(self):
        self.calls: list[str] = []
        self.answer: object = {"answer": "Start with a gentle shampoo, twice a week.",
                               "lines": ["Your scalp looks dry here.", "There are some flakes."]}
        self.fail = False

    def __call__(self, *, spec, system, user, surface, user_id=None, **_):
        del spec, system, user, user_id
        self.calls.append(surface)
        if self.fail:
            raise RuntimeError("no provider")
        return SimpleNamespace(parsed=self.answer, text="")


class _Base(unittest.TestCase):
    setUp_ = TL.ChatLinksTest.setUp
    _as, _link, _join = TL.ChatLinksTest._as, TL.ChatLinksTest._link, TL.ChatLinksTest._join

    def setUp(self):
        self.setUp_()
        self.provider = _Provider()
        for p in (patch("services.rings.feature_is_on_for_user", _ring({TOMEK})),
                  patch("services.llm.chat_complete", self.provider)):
            p.start()
            self.addCleanup(p.stop)

    def _start(self, what="Trichologist", who=TOMEK):
        return self.client.post("/v2/chats/setup/start", json={"what": what}, headers=self._as(who))

    def _put(self, part, value, who=TOMEK):
        return self.client.put(f"/v2/chats/setup/{part}", json={"value": value}, headers=self._as(who))

    def _read(self):
        return self.client.get("/v2/chats/setup", headers=self._as(TOMEK)).get_json()

    def _model(self, q="Is this a dry scalp?"):
        return {"q": q, "opts": ["Yes", "Somewhat", "No"], "says": "Your scalp looks dry here."}


class SetupTest(_Base):
    def test_will_asks_what_you_do_and_works_out_the_choices(self):
        """FIRST-02: what you type is what every later screen's choices fit;
        a profession the prototype knows costs no provider call."""
        recipe = self._start("trichologist").get_json()["recipe"]
        self.assertEqual(recipe["spec"], "Trichologist")
        self.assertEqual(recipe["hello"], "Hi. Send me a photo of your scalp, and tell me what worries you.")
        self.assertEqual(recipe["suggest"]["send"][0], "photo")
        # "A message" is ticked beside Will's first suggestion (N625 item 1).
        self.assertEqual(recipe["send"], ["photo", "text"])
        self.assertEqual(recipe["questions"], [{"q": "What worries you about your hair?"}])
        self.assertEqual(self.provider.calls, [])
        self.assertFalse(recipe["live"])
        # Without the ring, nothing is there.
        self.assertEqual(self._start(who=PIOTR).status_code, 404)

    def test_a_new_host_starts_blank_even_without_a_provider(self):
        """FIRST-16: nothing from Artur's chat; with no provider answer the
        choices come from rules."""
        self.provider.fail = True
        recipe = self._start("Beekeeper").get_json()["recipe"]
        self.assertEqual(self.provider.calls, ["chat_setup_suggest"])
        self.assertEqual(recipe["line"], "People come to you for help from a beekeeper.")
        self.assertEqual(recipe["hello"], "Hi. Tell me what you need, and I'll help.")
        from services.assistants import starting_questions
        artur = {q["q"] for q in starting_questions()}
        self.assertFalse(artur & {q["q"] for q in recipe["questions"]})

    def test_one_decision_per_screen_keep_or_change(self):
        """FIRST-03: Change shows Will's next suggestion, kept with no new
        call; Keep saves it; typed words come back to the same part."""
        sug = self._start().get_json()["recipe"]["suggest"]
        self.assertEqual(len(sug["line"]), 2)
        res = self._put("line", sug["line"][1])
        self.assertEqual(res.status_code, 200)
        self._put("line", "People come to you when their hair worries them.")
        self.assertEqual(self._read()["recipe"]["line"], "People come to you when their hair worries them.")
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self._put("nevers", True).status_code, 404)

    def test_what_people_send_several_ticked(self):
        """FIRST-04: several ticked; what they tick is how people answer."""
        self._start()
        recipe = self._put("send", ["photo", "text"]).get_json()["recipe"]
        self.assertEqual(recipe["send"], ["photo", "text"])
        self.assertEqual(recipe["answer_with"]["type"], True)
        self.assertEqual(recipe["answer_with"]["record"], False)
        self.assertEqual(self._put("send", []).status_code, 400)
        self.assertEqual(self._put("send", ["fax"]).status_code, 400)

    def test_they_get_back_an_answer_unless_will_suggests_otherwise(self):
        """FIRST-05: where Will's suggestion is an answer, people get an
        answer; a speaking coach's people get their own words, tidied."""
        self.assertEqual(self._start("Trichologist").get_json()["recipe"]["out"], "answer")
        self.assertEqual(self._start("Speaking coach").get_json()["recipe"]["out"], "words")
        self.assertEqual(self._put("out", "todo").get_json()["recipe"]["out"], "todo")
        self.assertEqual(self._put("out", "verdict").status_code, 400)

    def test_the_hello_questions_and_taps_pass_the_hosts_checks(self):
        """FIRST-06: the hello, up to three questions, one to three taps
        ("Type my own" makes one) and "Something else" always there; a score
        or a verdict is refused."""
        self._start()
        self.assertEqual(self._put("hello", "Welcome. Show me.").status_code, 200)
        bad = self._put("hello", "I'll give you a score out of 10.")
        self.assertEqual((bad.status_code, bad.get_json()["code"]), (400, "RECIPE_WORDS"))
        self.assertEqual(self._put("questions", [{"q": "A?"}, {"q": "B?"}, {"q": "C?"}]).status_code, 200)
        self.assertEqual(self._put("questions", [{"q": "A?"}] * 4).status_code, 400)
        self.assertEqual(self._put("taps", ["One", "Two", "Three"]).status_code, 200)
        self.assertEqual(self._put("taps", ["Look at my scalp"]).status_code, 200)
        self.assertEqual(self._put("taps", []).status_code, 400)
        self.assertEqual(self._put("taps", ["A", "B", "C", "D"]).status_code, 400)
        self.assertEqual(self._put("taps", ["One", "Two", "Something else"]).status_code, 400)

    def test_a_model_is_one_question_with_three_answers(self):
        """FIRST-07: one question and exactly three answers."""
        self._start()
        self.assertEqual(self._put("models", [self._model()]).status_code, 200)
        two = {"q": "Is it dry?", "opts": ["Yes", "No"]}
        self.assertEqual(self._put("models", [two]).status_code, 400)
        self.assertEqual(self._put("models", [self._model()] * 4).status_code, 400)

    def test_a_model_made_here_is_a_real_model_teach_it_opens(self):
        """FIRST-07, FIRST-08: the model a host makes gets the real model
        behind it, theirs and private, ready for "Teach it"; kept again, it
        is the same model."""
        def rings(feature, user_id, database=None):
            del database
            return feature in ("chat_builder", "ai_models") and str(user_id) == TOMEK
        with patch("services.rings.feature_is_on_for_user", rings):
            self._start()
            card = self._put("models", [self._model()]).get_json()["recipe"]["models"][0]
            again = self._put("models", [card, self._model("Are there flakes?")]).get_json()["recipe"]["models"]
            self._put("models", [self._model(), again[1]])
            teach = self.client.get(f"/v2/models/{card['model_id']}/setup/first-ten", headers=self._as(TOMEK))
        self.assertEqual(again[0]["model_id"], card["model_id"])
        rows = self.store.tables["ai_models"]
        self.assertEqual(len(rows), 2)
        mine = next(r for r in rows if r["id"] == card["model_id"])
        self.assertEqual((mine["owner_id"], mine["visibility"], mine["status"], mine["recipe"]["scale"]),
                         (TOMEK, "private", "learning", ["Yes", "Somewhat", "No"]))
        self.assertEqual(teach.status_code, 200)
        self.assertNotIn("teaching", teach.get_json()["screen"])
        self.assertEqual(self.provider.calls, [])

    def test_the_host_adds_an_example_and_answers_it_first(self):
        """FIRST-08, FIRST-23: on the model just made in the setup, the host
        adds an example of their own ("Add an example"); it is the first of
        their first ten, and their answer is kept."""
        def rings(feature, user_id, database=None):
            del database
            return feature in ("chat_builder", "ai_models") and str(user_id) == TOMEK
        with patch("services.rings.feature_is_on_for_user", rings):
            self._start()
            mid = self._put("models", [self._model()]).get_json()["recipe"]["models"][0]["model_id"]
            added = self.client.post(f"/v2/models/{mid}/examples", json={"text": "Flakes near the roots."},
                                     headers=self._as(TOMEK))
            first = self.client.get(f"/v2/models/{mid}/setup/first-ten", headers=self._as(TOMEK)).get_json()
            eid = added.get_json()["example_id"]
            answered = self.client.post(f"/v2/models/{mid}/setup/first-ten/{eid}",
                                        json={"step": "rate", "answer": "Yes"}, headers=self._as(TOMEK))
            stranger = self.client.post(f"/v2/models/{mid}/examples", json={"text": "Mine."},
                                        headers=self._as(PIOTR))
        self.assertEqual(added.status_code, 200)
        self.assertIn("teaching", first["screen"])
        self.assertEqual(answered.status_code, 200)
        kept = [a for a in self.store.tables.get("ai_model_answers", []) if a.get("example_id") == eid]
        self.assertEqual([(a["teacher_id"], a["answer"]) for a in kept], [(TOMEK, "Yes")])
        self.assertEqual(stranger.status_code, 404)

    def test_who_answers_is_three_plain_choices(self):
        """FIRST-09, FIRST-22: "I draft, you send" first, then "Only you"
        and "I answer at once"; one tap chooses."""
        recipe = self._start().get_json()["recipe"]
        self.assertEqual(recipe["who"], "shadow")
        self._put("care", False)
        self.assertEqual(self._put("who", "assistant").get_json()["recipe"]["who"], "assistant")
        self.assertEqual(self._put("who", "you").get_json()["recipe"]["who"], "you")
        self.assertEqual(self._put("who", "robot").status_code, 400)
        who = next(p for p in self._read()["parts"] if p["part"] == "who")
        self.assertEqual(who, {"part": "who", "title": "Who answers",
                               "value": "Only you answer. I stay quiet."})

    def test_sharing_keeps_a_price_in_tokens(self):
        """FIRST-10: Yes asks the price per use, in tokens; Not now keeps it
        private."""
        self._start()
        self._put("share", True)
        self.assertEqual(self._put("price", 2).get_json()["recipe"]["price"], 2)
        self.assertEqual(self._put("price", 4).status_code, 400)
        self.assertNotIn("price", self._put("share", False).get_json()["recipe"])

    def test_models_you_can_use_are_others_shared_models(self):
        """FIRST-13: each shared model with its question, three answers,
        owner and price; one that does not fit is greyed out."""
        self._start()
        self._put("send", ["text"])
        self.store.tables["ai_models"] = [
            {"id": "m1", "owner_id": PIOTR, "owner_name": "Piotr", "visibility": "public",
             "status": "live", "price_units": 300,
             "recipe": {"input": "voice", "question": "Is it rushed?", "scale": ["Yes", "Somewhat", "No"]}},
            {"id": "m2", "owner_id": PIOTR, "owner_name": "Piotr", "visibility": "private",
             "status": "live", "price_units": 300, "recipe": {"question": "Hidden?"}}]
        # Shared for tokens only after the exam the app computed passed (LEARN-04).
        self.store.tables["ai_model_versions"] = [
            {"model_id": "m1", "status": "released", "exam": {"computed": True, "passed": True}}]
        with patch("services.token_prices.display_unit", lambda: 100):
            models = self.client.get("/v2/chats/setup/models", headers=self._as(TOMEK)).get_json()["models"]
        self.assertEqual(models, [{"model_id": "m1", "q": "Is it rushed?", "opts": ["Yes", "Somewhat", "No"],
                                   "by": "Piotr", "price": 3, "needs": "rec", "fits": False,
                                   "learning": False}])

    def test_two_ways_use_one_or_train_your_own(self):
        """FIRST-18: the way is kept; a used model carries its owner and
        price, the host's own has none."""
        self._start()
        self.assertEqual(self._put("way", "use").get_json()["recipe"]["way"], "use")
        self.store.tables["ai_models"] = [{"id": "m1", "owner_id": PIOTR, "price_units": 3}]  # Piotr's price
        self.store.tables["ai_model_versions"] = [  # passed its exam: priced, not still learning (N633)
            {"model_id": "m1", "status": "released", "exam": {"computed": True, "passed": True}}]
        used = {**self._model("Is the skin red?"), "own": False, "model_id": "m1", "by": "Piotr", "price": 3}
        recipe = self._put("models", [used, self._model()]).get_json()["recipe"]
        self.assertEqual([m["own"] for m in recipe["models"]], [False, True])
        self.assertEqual(self._put("models", [{**used, "model_id": ""}]).status_code, 400)
        self.assertEqual(self._put("way", "steal").status_code, 400)

    def test_what_your_chat_costs_you(self):
        """FIRST-14: each model's price, Free for the host's own; the month
        follows the typed numbers; only own models cost nothing."""
        self._start()
        self._put("models", [self._model()])
        self.assertTrue(self._put("cost", {"people": 10, "sends": 2}).get_json()["cost"]["nothing"])
        self.store.tables["ai_models"] = [{"id": "m1", "owner_id": PIOTR, "price_units": 3}]  # Piotr's price
        self.store.tables["ai_model_versions"] = [  # passed its exam: priced, not still learning (N633)
            {"model_id": "m1", "status": "released", "exam": {"computed": True, "passed": True}}]
        used = {**self._model("Is the skin red?"), "own": False, "model_id": "m1", "by": "Piotr", "price": 3}
        cost = self._put("models", [used, self._model()]).get_json()["cost"]
        self.assertEqual(cost, {"lines": [{"q": "Is the skin red?", "by": "Piotr", "price": 3},
                                          {"q": "Is this a dry scalp?", "by": None, "price": 0}],
                                "per_send": 3, "month": 3 * 10 * 2 * 30, "nothing": False})
        self.assertEqual(self._put("cost", {"people": 0, "sends": 1}).status_code, 400)

    def test_health_law_or_money_is_yes_until_the_host_says_no(self):
        """FIRST-15: "Is your work about health, law or money?" right after
        what you do; until it is answered, yes; with yes "I answer at once"
        is not offered, and a chat that had it drafts instead (N622 item 1)."""
        self.assertTrue(self._start().get_json()["recipe"]["sensitive"])
        refused = self._put("who", "assistant")
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (400, "RECIPE_INVALID"))
        recipe = self._put("care", False).get_json()["recipe"]
        self.assertEqual((recipe["care"], recipe["sensitive"]), (False, False))
        self.assertEqual(self._put("who", "assistant").status_code, 200)
        recipe = self._put("care", True).get_json()["recipe"]
        self.assertEqual((recipe["care"], recipe["sensitive"], recipe["who"]), (True, True, "shadow"))
        self.assertEqual(self._put("who", "assistant").status_code, 400)
        self.assertEqual(self._put("care", "maybe").status_code, 400)

    def test_not_now_leaves_the_chat_without_models(self):
        """FIRST-17: Not now leaves the chat without models."""
        self._start()
        self._put("smart", True)
        self._put("models", [self._model()])
        recipe = self._put("smart", False).get_json()["recipe"]
        self.assertEqual(recipe["models"], [])
        self.assertEqual(next(p for p in self._read()["parts"] if p["part"] == "models")["value"], "None yet")

    def test_test_my_chat_answers_as_my_people_would(self):
        """FIRST-20: the host sends something and gets the answer and each
        model's line, in one provider call; nothing is kept in a chat."""
        self._start()
        self._put("models", [self._model(), self._model("Are there flakes?")])
        res = self.client.post("/v2/chats/setup/try", json={"body": "My scalp itches."}, headers=self._as(TOMEK))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), {"useful": True, "messages": [
            {"kind": "answer", "body": "Start with a gentle shampoo, twice a week.", "by": "Tomek's assistant"},
            {"kind": "model", "body": "Your scalp looks dry here.", "by": "Tomek's model"},
            {"kind": "model", "body": "There are some flakes.", "by": "Tomek's model"}]})
        self.assertEqual(self.provider.calls, ["chat_reply"])
        self.assertEqual(self.store.tables.get("chat_messages", []), [])
        own = self._read()["own_chat"]
        link = self._link(TOMEK).get_json()
        self.assertEqual(own, {"title": "Tomek", "line": "Hi. Send me a photo of your scalp, and tell me what worries you.",
                               "link": link,
                               "join_line": "People come to Tomek with hair and scalp worries."})
        self.assertEqual(link["path"], f"/c/{link['token']}")

    def test_to_change_the_chat_tell_will(self):
        """FIRST-21: any words open the chat's parts again."""
        self._start()
        res = self.client.post("/v2/chats/setup/edit", json={"said": "I want to edit my chat"},
                               headers=self._as(TOMEK)).get_json()
        self.assertEqual(res["line"], "Here are your chat's parts. Tap one to change it.")
        self.assertEqual([p["title"] for p in res["parts"]],
                         ["Why people come", "They send", "They get back", "Your hello",
                          "First questions", "They can ask", "Your models", "Who answers"])


class VisitorTest(_Base):
    def _host(self, live=True, **parts):
        self._start()
        self._put("send", ["text", "photo"])
        self._put("models", [self._model(), self._model("Are there flakes?")])
        # Health, law or money is answered first (N622 item 1).
        for part, value in sorted(parts.items(), key=lambda kv: kv[0] != "sensitive"):
            self._put(part, value)
        if live:
            self._put("live", True)
        token = self._link(TOMEK).get_json()["token"]
        return self._join(PIOTR, token).get_json()["chat"]["id"]

    def _send(self, chat, body="My scalp itches."):
        return self.client.post(f"/v2/chats/{chat}/messages", json={"kind": "text", "body": body},
                                headers=self._as(PIOTR))

    def _messages(self, chat, who=PIOTR):
        return self.client.get(f"/v2/chats/{chat}/messages", headers=self._as(who)).get_json()["messages"]

    def _answers(self, n):
        """``n`` answers the host gave in their own words, in another chat."""
        self.store.tables.setdefault("chat_members", []).append(
            {"id": "host-elsewhere", "thread_id": "elsewhere", "user_id": TOMEK, "display_name": "Tomek"})
        for i in range(n):
            self.store.tables.setdefault("chat_messages", []).append(
                {"id": f"a{i}", "thread_id": "elsewhere", "author_member_id": "host-elsewhere",
                 "kind": "text", "body": "My answer.", "meta": {"answer_to": f"q{i}"},
                 "created_at": f"2026-11-0{1 + i % 9}T00:00:00+00:00"})

    def test_not_yet_keeps_it_saved_and_yes_opens_it(self):
        """FIRST-11: Not yet keeps it saved, and nobody meets it; Yes opens
        it, and the host's line is what a newcomer reads before joining, as
        "People come to {name} ..." (N622 item 2)."""
        chat = self._host(live=False)
        token = self._link(TOMEK).get_json()["token"]
        self.assertIsNone(self.client.get(f"/v2/chats/{chat}/host", headers=self._as(PIOTR)).get_json()["host"])
        self.assertIsNone(self.client.get(f"/v2/chats/join/{token}").get_json()["learn"])
        self._put("live", True)
        joins = "People come to Tomek with hair and scalp worries."
        self.assertEqual(self.client.get(f"/v2/chats/join/{token}").get_json()["learn"], joins)
        self.assertEqual(self._read()["own_chat"]["join_line"], joins)
        self._put("line", "Hair worries, answered.")
        self.assertEqual(self.client.get(f"/v2/chats/join/{token}").get_json()["learn"], "Hair worries, answered.")
        self.assertEqual(self.client.get(f"/v2/chats/{chat}/host", headers=self._as(PIOTR)).get_json()["host"]["hello"],
                         "Hi. Send me a photo of your scalp, and tell me what worries you.")

    def test_the_hosts_hello_first_questions_and_taps(self):
        """VIS-01: the host's hello is the first line; then their questions;
        their taps with "Something else"."""
        chat = self._host()
        self.assertEqual(self._messages(chat)[0]["body"],
                         "Hi. Send me a photo of your scalp, and tell me what worries you.")
        host = self.client.get(f"/v2/chats/{chat}/host", headers=self._as(PIOTR)).get_json()["host"]
        self.assertEqual(host["questions"], [{"q": "What worries you about your hair?"}])
        self.assertEqual(host["taps"], ["Look at my scalp", "My hair is falling out", "Which shampoo",
                                        "Something else"])

    def test_the_bar_follows_what_the_host_takes(self):
        """VIS-02: what the host ticked is what the bar takes; a host who
        takes only recordings gets no typed message."""
        chat = self._host()
        host = self.client.get(f"/v2/chats/{chat}/host", headers=self._as(PIOTR)).get_json()["host"]
        self.assertEqual(host["send"], ["text", "photo"])
        self.assertEqual(self._send(chat).status_code, 200)
        self._put("send", ["rec"])
        self.assertEqual(self._send(chat).status_code, 400)

    def test_they_get_back_the_output_the_host_chose(self):
        """VIS-03: "I draft, you send": the person gets nothing until the
        host sends it; then the answer is from the host, by name."""
        chat = self._host()
        res = self._send(chat).get_json()
        self.assertEqual(res["reply"], {"waits": True})
        self.assertNotIn("draft", res["message"]["meta"])
        self.assertTrue(all("draft" not in m["meta"] for m in self._messages(chat)))
        drafts = self.client.get("/v2/chats/setup/drafts", headers=self._as(TOMEK)).get_json()["drafts"]
        self.assertEqual(len(drafts), 1)
        self.assertEqual((drafts[0]["from"], drafts[0]["said"], drafts[0]["answer"]),
                         ("Piotr", "My scalp itches.", "Start with a gentle shampoo, twice a week."))
        sent = self.client.post(f"/v2/chats/setup/drafts/{drafts[0]['message_id']}/send", json={},
                                headers=self._as(TOMEK))
        self.assertEqual(sent.status_code, 200)
        answer = [m for m in self._messages(chat) if "reply" in m["meta"]][0]
        self.assertEqual((answer["body"], answer["meta"]["reply"]["by"], answer["meta"]["reply"]["name"]),
                         ("Start with a gentle shampoo, twice a week.", "host", "Tomek"))
        self.assertEqual(self.client.get("/v2/chats/setup/drafts", headers=self._as(TOMEK)).get_json()["drafts"], [])
        self.assertEqual(self.provider.calls, ["chat_reply"])

    def test_each_models_line_names_whose_model_it_is(self):
        """VIS-04: one line per model, in the host's order, each naming whose
        model it is; a line that scores the person is left out."""
        chat = self._host(who="assistant", sensitive=False)
        self._answers(20)
        self.provider.answer = {"answer": "Here is what I'd do first.",
                                "lines": ["Your scalp looks dry here.", "You get 3 out of 10."]}
        reply = self._send(chat).get_json()["reply"]
        lines = [m for m in reply["messages"] if "model_line" in m["meta"]]
        self.assertEqual([(m["body"], m["meta"]["model_line"]["by"]) for m in lines],
                         [("Your scalp looks dry here.", "Tomek's model")])

    def test_was_this_useful_never_blocks_the_next_one(self):
        """VIS-05: Yes, No or Skip kept on the answer; the next message goes
        either way."""
        chat = self._host(who="assistant", sensitive=False)
        self._answers(20)
        last = self._send(chat).get_json()["reply"]["messages"][-1]
        self.assertTrue(last["meta"]["useful_ask"])
        self.assertEqual(self._send(chat, "And the ends?").status_code, 200)
        res = self.client.post(f"/v2/chats/{chat}/messages/{last['id']}/useful", json={"answer": "yes"},
                               headers=self._as(PIOTR))
        self.assertEqual(res.get_json(), {"ok": True})
        kept = next(m for m in self._messages(chat) if m["id"] == last["id"])
        self.assertEqual(kept["meta"]["useful"], "yes")
        self.assertEqual(self.client.post(f"/v2/chats/{chat}/messages/{last['id']}/useful",
                                          json={"answer": "7"}, headers=self._as(PIOTR)).status_code, 400)

    def test_before_the_minimum_the_question_waits_for_the_host(self):
        """VIS-06: with fewer than 20 of the host's own answers nothing is
        answered for the host; from 20, "{name}'s assistant" answers."""
        chat = self._host(who="assistant", sensitive=False)
        self._answers(19)
        self.assertEqual(self._send(chat).get_json()["reply"], {"waits": True})
        self._answers(20)
        reply = self._send(chat, "And now?").get_json()["reply"]
        self.assertEqual(reply["messages"][0]["meta"]["reply"]["name"], "Tomek's assistant")
        self.assertLessEqual(len(self.provider.calls), 2)  # one per message (N620)

    def test_in_a_health_law_or_money_chat_the_model_only_suggests(self):
        """VIS-07: the person gets nothing from a model; the host sees the
        suggestion in their Will."""
        chat = self._host(who="assistant")  # sensitive stays yes
        self._answers(30)
        self.assertEqual(self._send(chat).get_json()["reply"], {"waits": True})
        drafts = self.client.get("/v2/chats/setup/drafts", headers=self._as(TOMEK)).get_json()["drafts"]
        self.assertEqual((len(drafts), drafts[0]["sensitive"]), (1, True))
        self.assertFalse(any("reply" in m["meta"] for m in self._messages(chat)))


KASIA = "11111111-1111-4111-8111-111111111111"
JOB = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
V1 = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


class _Tokens(_Base):
    """The ledger and a model of Kasia's, at her price of 300 a use."""
    _host, _send, _messages, _answers = VisitorTest._host, VisitorTest._send, VisitorTest._messages, \
        VisitorTest._answers

    def setUp(self):
        super().setUp()
        from services.db import db
        from services.token_account import ChargeResult
        from tests.test_model_api_routes import _CappedStore
        self.store = _CappedStore()
        self.balance = {TOMEK: 1000, PIOTR: 1000}
        self.ledger: list[tuple] = []
        self.pricing = True
        self.paid: list[tuple] = []

        def charge(user_id, units, *, ref_id, database=None):
            """The ledger's atomic charge: once per ref, never below zero."""
            if any(r == ref_id for _u, _n, r in self.ledger):
                return ChargeResult(True, 0, self.balance[user_id], "already_charged", "model_answer")
            if self.balance[user_id] < units:
                return ChargeResult(False, 0, self.balance[user_id], "insufficient", "model_answer")
            self.balance[user_id] -= units
            self.ledger.append((user_id, units, ref_id))
            return ChargeResult(True, units, self.balance[user_id], "", "model_answer")

        def grant(user_id, units, *, ref_id, database=None):
            self.paid.append((user_id, units))
            return {"ok": True, "reason": ""}

        for p in (patch.object(db, "client", self.store),
                  patch("services.token_account.enabled", lambda: self.pricing),
                  patch("services.token_account.charge_model_answer", charge),
                  patch("services.token_account.model_earnings_grant", grant),
                  # One shown token is 100 stored units: the card's 3 is Kasia's 300.
                  patch("services.token_prices.display_unit", lambda: 100)):
            p.start()
            self.addCleanup(p.stop)
        t = self.store.tables
        t["ai_models"] = [{"id": JOB, "name": "Scalp check", "owner_id": KASIA, "owner_name": "Kasia",
                           "visibility": "public", "status": "ready", "field": "hair", "description": "",
                           "draft_step": None, "recipe": {"input": "text", "question": "Are there flakes?"},
                           "targets": {}, "price_units": 300}]
        t["ai_model_teachers"] = [{"model_id": JOB, "user_id": KASIA, "role": "owner", "trust_status": "counts"}]
        t["ai_model_versions"] = [{"id": V1, "model_id": JOB, "number": 1, "status": "released",
                                   "base_model": "gpt-4o-mini", "founder_id": KASIA, "created_at": "2026-11-01",
                                   "exam": {"computed": True, "passed": True}, "card": {}}]

    def _lines(self, reply):
        return [(m["body"], m["meta"]["model_line"]["by"]) for m in reply["messages"] if "model_line" in m["meta"]]


class TokensTest(_Tokens):
    """Tokens in a chat (TOK-01, TOK-02): Tomek's chat has his own model and
    Kasia's, at her price of 300 a use."""

    def _chat(self):
        chat = self._host(who="assistant", sensitive=False)
        self._put("models", [self._model(), {"q": "Are there flakes?", "opts": ["Yes", "Somewhat", "No"],
                                             "own": False, "model_id": JOB, "by": "Kasia", "price": 3}])
        self._answers(20)
        return chat

    def test_a_host_pays_when_someone_elses_model_runs_in_their_chat(self):
        """TOK-01: Kasia's model's line costs Tomek her price, once; Piotr,
        who wrote, pays nothing and sees no price; Tomek's own model is
        free; Kasia is credited as for the API, in tokens."""
        chat = self._chat()
        sent = self._send(chat).get_json()
        self.assertEqual(self._lines(sent["reply"]), [("Your scalp looks dry here.", "Tomek's model"),
                                                       ("There are some flakes.", "Kasia's model")])
        self.assertEqual([(u, n) for u, n, _r in self.ledger], [(TOMEK, 300)])
        self.assertEqual(self.balance[PIOTR], 1000)
        for never in ("price", "token", "300"):
            self.assertNotIn(never, str(sent))
        self.assertLessEqual(len(self.provider.calls), 2)  # N620: the charge is no provider call
        from services import model_api_store as store
        from tests.test_model_api_routes import ModelApiTest
        last = ModelApiTest._last_month()
        for c in self.store.tables["ai_model_calls"]:
            c["created_at"] = f"{last}-15T10:00:00+00:00"
        from services.db import db
        store.pay_month(db, last, pay=True)
        self.assertEqual([u for u, _n in self.paid], [KASIA])

    def test_the_same_message_delivered_twice_is_charged_once(self):
        """TOK-01 (N620 step 4): the same message delivered again charges
        nothing more and credits nobody twice."""
        from services import chat_replies
        from services.db import db
        chat = self._chat()
        message = self._send(chat).get_json()["message"]
        again = chat_replies.on_question(db, TOMEK, PIOTR, chat, message["id"], "My scalp itches.")
        self.assertIn(("There are some flakes.", "Kasia's model"), self._lines(again))
        self.assertEqual([(u, n) for u, n, _r in self.ledger], [(TOMEK, 300)])
        self.assertEqual(len(self.store.tables["ai_model_calls"]), 1)

    def test_out_of_tokens_the_model_is_skipped_and_the_chat_goes_on(self):
        """TOK-02: with too few tokens Kasia's line is left out, the rest is
        sent, nothing is charged, and Tomek's setup says which model, once
        a day."""
        chat = self._chat()
        self.balance[TOMEK] = 100
        reply = self._send(chat).get_json()["reply"]
        self.assertEqual(reply["messages"][0]["body"], "Start with a gentle shampoo, twice a week.")
        self.assertEqual(self._lines(reply), [("Your scalp looks dry here.", "Tomek's model")])
        self.assertEqual(self._send(chat, "And the ends?").status_code, 200)
        self.assertEqual(self.ledger, [])
        skipped = self._read()["skipped_models"]
        self.assertEqual([(s["model_id"], s["q"], s["by"]) for s in skipped], [(JOB, "Are there flakes?", "Kasia")])
        marks = [r for r in self.store.tables["token_ledger"] if r["action"] == "model_skipped"]
        self.assertEqual((len(marks), marks[0]["delta"]), (1, 0))

    def test_a_host_pays_the_price_shown_when_they_added_the_model(self):
        """N630 item 3: Kasia raises her price; Tomek still pays the 3 he
        agreed to, and his setup says it changed. He keeps the model only at
        her new price (no other number), and then pays that; dropping it
        ends the difference too. Kasia is credited what Tomek pays."""
        chat = self._chat()
        self.store.tables["ai_models"][0]["price_units"] = 500
        self._send(chat)
        self.assertEqual([(u, n) for u, n, _r in self.ledger], [(TOMEK, 300)])
        self.assertEqual(self.store.tables["ai_model_calls"][0]["price_units"], 300)
        self.assertEqual(self._read()["price_changes"],
                         [{"model_id": JOB, "q": "Are there flakes?", "by": "Kasia", "was": 3, "now": 5}])
        kasias = {"q": "Are there flakes?", "opts": ["Yes", "Somewhat", "No"], "own": False,
                  "model_id": JOB, "by": "Kasia"}
        self.assertEqual(self._put("models", [self._model(), {**kasias, "price": 4}]).status_code, 400)
        self.assertEqual(self._put("models", [self._model(), {**kasias, "price": 3}]).status_code, 200)  # kept
        self.assertEqual(self._put("models", [self._model(), {**kasias, "price": 5}]).status_code, 200)
        self.assertEqual(self._read()["price_changes"], [])
        self._send(chat, "And the ends?")
        self.assertEqual([n for _u, n, _r in self.ledger], [300, 500])
        self.store.tables["ai_models"][0]["price_units"] = 700
        self._put("models", [self._model()])                     # dropped
        self.assertEqual(self._read()["price_changes"], [])
        self.assertEqual(self._put("models", [self._model(), {**kasias, "price": 5}]).status_code, 400)

    def test_with_token_pricing_off_nothing_is_charged_or_skipped(self):
        """TOKEN_PRICING_ENABLED off: every line as before, nothing charged,
        nothing skipped."""
        self.pricing = False
        chat = self._chat()
        self.balance[TOMEK] = 0
        reply = self._send(chat).get_json()["reply"]
        self.assertEqual(len(self._lines(reply)), 2)
        self.assertEqual((self.ledger, self._read()["skipped_models"]), ([], []))


OLA = "33333333-3333-4333-8333-333333333333"
LM = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"


class LearningTest(_Tokens):
    """N633 item 1: Ola's model is still learning (no passed exam); Tomek,
    with the chat builder and the AI models, adds it to his chat."""

    def setUp(self):
        super().setUp()
        def rings(feature, user_id, database=None):
            del database
            return feature in ("chat_builder", "ai_models") and str(user_id) == TOMEK
        p = patch("services.rings.feature_is_on_for_user", rings)
        p.start()
        self.addCleanup(p.stop)
        t = self.store.tables
        t["ai_models"].append({"id": LM, "name": "Flakes", "owner_id": OLA, "owner_name": "Ola",
                               "visibility": "public", "status": "learning", "field": "hair",
                               "description": "", "draft_step": None, "targets": {}, "price_units": 300,
                               "recipe": {"input": "text", "question": "Are there flakes?",
                                          "scale": ["Yes", "Somewhat", "No"]}})
        t["ai_model_teachers"].append({"model_id": LM, "user_id": OLA, "role": "owner", "trust_status": "counts"})
        self.olas = {"q": "Are there flakes?", "opts": ["Yes", "Somewhat", "No"], "own": False,
                     "model_id": LM, "by": "Ola"}

    def _chat(self):
        chat = self._host(who="assistant", sensitive=False)
        self._answers(20)
        self.assertEqual(self._put("models", [self._model(), {**self.olas, "price": 0}]).status_code, 200)
        return chat

    def _passes(self):
        self.store.tables["ai_model_versions"].append(
            {"id": "v-lm", "model_id": LM, "number": 1, "status": "released", "base_model": "gpt-4o-mini",
             "founder_id": OLA, "created_at": "2026-11-09", "exam": {"computed": True, "passed": True},
             "card": {}})

    def test_a_model_still_learning_is_listed_free_and_its_host_teaches_it(self):
        """FIRST-24: "Models you can use" lists it as learning, at 0; added,
        it is free (any price is refused) and Tomek joins its teachers. A
        host without the AI models is offered none still learning."""
        self._start()
        listed = {m["model_id"]: m for m in self.client.get(
            "/v2/chats/setup/models", headers=self._as(TOMEK)).get_json()["models"]}
        self.assertEqual((listed[LM]["learning"], listed[LM]["price"]), (True, 0))
        self.assertEqual(self._put("models", [{**self.olas, "price": 3}]).status_code, 400)
        card = self._put("models", [{**self.olas, "price": 0}]).get_json()["recipe"]["models"][0]
        self.assertEqual((card["learning"], card["price"]), (True, 0))
        self.assertIn((LM, TOMEK, "contributor"), [(r["model_id"], r["user_id"], r["role"])
                                                   for r in self.store.tables["ai_model_teachers"]])
        self.assertEqual(self._read()["cost"]["per_send"], 0)
        with patch("services.rings.feature_is_on_for_user", _ring({TOMEK})):
            listed = self.client.get("/v2/chats/setup/models", headers=self._as(TOMEK)).get_json()["models"]
        self.assertNotIn(LM, [m["model_id"] for m in listed])

    def test_it_says_nothing_costs_nothing_and_the_hosts_own_words_teach_it(self):
        """FIRST-24: a person who writes gets no line of it and Tomek pays
        nothing; a draft Tomek changes before sending becomes its example,
        in his words only (never what the person sent), as does a question
        he answers by typing; a draft sent unchanged teaches nothing."""
        chat = self._chat()
        self._put("who", "shadow")
        self.assertEqual(self._send(chat).get_json()["reply"], {"waits": True})
        self.assertEqual(self.ledger, [])
        drafts = self.client.get("/v2/chats/setup/drafts", headers=self._as(TOMEK)).get_json()["drafts"]
        self.assertEqual([x["by"] for x in drafts[0]["lines"]], ["Tomek's model"])
        self.client.post(f"/v2/chats/setup/drafts/{drafts[0]['message_id']}/send",
                         json={"body": "Wash it gently, twice a week."}, headers=self._as(TOMEK))
        self._send(chat, "And the ends?")
        later = self.client.get("/v2/chats/setup/drafts", headers=self._as(TOMEK)).get_json()["drafts"]
        self.client.post(f"/v2/chats/setup/drafts/{later[0]['message_id']}/send", json={},
                         headers=self._as(TOMEK))
        self._put("who", "you")
        asked = self._send(chat, "Is it the water?").get_json()["message"]["id"]
        self.client.post(f"/v2/chats/{chat}/messages", json={"kind": "text", "body": "Maybe, try filtered.",
                                                             "to": asked}, headers=self._as(TOMEK))
        made = [e for e in self.store.tables.get("ai_model_examples", []) if e["model_id"] == LM]
        self.assertEqual([(e["source"], e["added_by"], e["content"]) for e in made],
                         [("teacher", TOMEK, {"text": "Wash it gently, twice a week."}),
                          ("teacher", TOMEK, {"text": "Maybe, try filtered."})])
        host = self.client.get(f"/v2/chats/{chat}/host", headers=self._as(PIOTR)).get_json()["host"]
        self.assertEqual([m["by"] for m in host["models"]], ["Tomek's model"])

    def test_once_it_passes_the_host_keeps_it_at_the_price_they_see(self):
        """FIRST-24, N630 item 3: when it passes, its price shows as a change
        from 0; until Tomek keeps it, it gives no line and costs nothing.
        Kept at Ola's price, it answers and he pays that."""
        chat = self._chat()
        self._passes()
        self.assertEqual(self._read()["price_changes"],
                         [{"model_id": LM, "q": "Are there flakes?", "by": "Ola", "was": 0, "now": 3}])
        self.assertEqual(self._lines(self._send(chat).get_json()["reply"]),
                         [("Your scalp looks dry here.", "Tomek's model")])
        self.assertEqual(self.ledger, [])
        self.assertEqual(self._put("models", [self._model(), {**self.olas, "price": 3}]).status_code, 200)
        self.assertEqual(self._read()["price_changes"], [])
        self.assertIn(("There are some flakes.", "Ola's model"),
                      self._lines(self._send(chat, "And the ends?").get_json()["reply"]))
        self.assertEqual([(u, n) for u, n, _r in self.ledger], [(TOMEK, 300)])


class MeetTest(_Base):
    """N633 item 2: Tomek joined through Piotr's link; later Tomek opens his
    own chat. Piotr meets it in the chat the two already share."""

    def setUp(self):
        super().setUp()
        p = patch("services.rings.feature_is_on_for_user", _ring({TOMEK, PIOTR}))
        p.start()
        self.addCleanup(p.stop)

    def _open(self, who, **parts):
        self._start(who=who)
        self._put("send", ["text"], who=who)
        for part, value in parts.items():
            self._put(part, value, who=who)
        self._put("live", True, who=who)

    def _messages(self, chat, who):
        return self.client.get(f"/v2/chats/{chat}/messages", headers=self._as(who)).get_json()["messages"]

    def _hellos(self, chat, who):
        return [m for m in self.store.tables["chat_messages"] if m["thread_id"] == chat
                and "welcome" in (m.get("meta") or {}) and m["author_member_id"] == self._member(chat, who)]

    def _member(self, chat, who):
        return next(m["id"] for m in self.store.tables["chat_members"]
                    if m["thread_id"] == chat and m["user_id"] == who)

    def _send(self, chat, who, body="My scalp itches."):
        return self.client.post(f"/v2/chats/{chat}/messages", json={"kind": "text", "body": body},
                                headers=self._as(who))

    def _drafts(self, who):
        return self.client.get("/v2/chats/setup/drafts", headers=self._as(who)).get_json()["drafts"]

    def test_the_hello_shows_once_in_the_chat_they_share(self):
        """VIS-08: nothing while Tomek's chat is not open, nor when Tomek
        reads his own chat; Piotr's first read after it opens writes
        Tomek's hello, once; GET /host gives Piotr Tomek's taps."""
        chat = self._join(TOMEK, self._link(PIOTR).get_json()["token"]).get_json()["chat"]["id"]
        self._start(who=TOMEK)
        self._messages(chat, PIOTR)
        self._put("live", True)
        self._messages(chat, TOMEK)
        self.assertEqual(self._hellos(chat, TOMEK), [])
        shown = self._messages(chat, PIOTR)
        self._messages(chat, PIOTR)
        self.assertEqual(len(self._hellos(chat, TOMEK)), 1)
        self.assertEqual(shown[-1]["body"], self._read()["recipe"]["hello"])
        host = self.client.get(f"/v2/chats/{chat}/host", headers=self._as(PIOTR)).get_json()["host"]
        self.assertEqual(host["taps"][-1], "Something else")

    def test_each_writes_to_the_others_chat_both_ways(self):
        """VIS-08: Piotr's words are answered by Tomek's chat as a
        visitor's (here drafted for Tomek); Tomek's words in the same chat
        are never answered by his own chat, and go to Piotr's chat once
        Piotr's is open too, whose hello was written when Tomek joined."""
        self._open(PIOTR)
        chat = self._join(TOMEK, self._link(PIOTR).get_json()["token"]).get_json()["chat"]["id"]
        self._open(TOMEK)
        self._messages(chat, PIOTR)
        self._messages(chat, TOMEK)
        self.assertEqual((len(self._hellos(chat, PIOTR)), len(self._hellos(chat, TOMEK))), (1, 1))
        self.assertEqual(self._send(chat, PIOTR).get_json()["reply"], {"waits": True})
        self.assertEqual(self._send(chat, TOMEK, "Thanks, and you?").get_json()["reply"], {"waits": True})
        self.assertEqual([d["said"] for d in self._drafts(TOMEK)], ["My scalp itches."])
        self.assertEqual([d["said"] for d in self._drafts(PIOTR)], ["Thanks, and you?"])

    def test_without_the_other_persons_open_chat_nothing_changes(self):
        """VIS-08: Tomek's words to Piotr, who has no chat of his own, are
        answered by nobody's chat, as before."""
        chat = self._join(TOMEK, self._link(PIOTR).get_json()["token"]).get_json()["chat"]["id"]
        self._open(TOMEK)
        self._messages(chat, PIOTR)
        sent = self._send(chat, TOMEK, "Hello?").get_json()
        self.assertNotIn("reply", sent)
        self.assertEqual(self._drafts(TOMEK), [])

