"""
STORY    As someone who knows a field, I want to set up a chat with Will from
         a blank start, one decision per screen, and open it; and as a person
         who comes to it, I want to get back what that host chose (N612 to
         N618; the locked prototype docs/design/the-blank-setup-2026-11-10/,
         its stories FIRST-* and VIS-*; the contract in backend PR #1893).
OUTCOME  One test per story, on the public routes; the story id leads each
         test's docstring.
PROVES   FIRST-02 -> SetupTest::test_will_asks_what_you_do_and_works_out_the_choices
         FIRST-03 -> SetupTest::test_one_decision_per_screen_keep_or_change
         FIRST-04 -> SetupTest::test_what_people_send_several_ticked
         FIRST-05 -> SetupTest::test_they_get_back_an_answer_unless_will_suggests_otherwise
         FIRST-06 -> SetupTest::test_the_hello_questions_and_taps_pass_the_hosts_checks
         FIRST-07 -> SetupTest::test_a_model_is_one_question_with_three_answers
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

    def test_who_answers_is_three_plain_choices(self):
        """FIRST-09, FIRST-22: "I draft, you send" first, then "Only you"
        and "I answer at once"; one tap chooses."""
        recipe = self._start().get_json()["recipe"]
        self.assertEqual(recipe["who"], "shadow")
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
             "recipe": {"input": "image", "question": "Is the skin red?", "scale": ["Yes", "Somewhat", "No"]}},
            {"id": "m2", "owner_id": PIOTR, "owner_name": "Piotr", "visibility": "private",
             "status": "live", "price_units": 300, "recipe": {"question": "Hidden?"}}]
        with patch("services.token_prices.display_unit", lambda: 100):
            models = self.client.get("/v2/chats/setup/models", headers=self._as(TOMEK)).get_json()["models"]
        self.assertEqual(models, [{"model_id": "m1", "q": "Is the skin red?", "opts": ["Yes", "Somewhat", "No"],
                                   "by": "Piotr", "price": 3, "needs": "photo", "fits": False}])

    def test_two_ways_use_one_or_train_your_own(self):
        """FIRST-18: the way is kept; a used model carries its owner and
        price, the host's own has none."""
        self._start()
        self.assertEqual(self._put("way", "use").get_json()["recipe"]["way"], "use")
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
        used = {**self._model("Is the skin red?"), "own": False, "model_id": "m1", "by": "Piotr", "price": 3}
        cost = self._put("models", [used, self._model()]).get_json()["cost"]
        self.assertEqual(cost, {"lines": [{"q": "Is the skin red?", "by": "Piotr", "price": 3},
                                          {"q": "Is this a dry scalp?", "by": None, "price": 0}],
                                "per_send": 3, "month": 3 * 10 * 2 * 30, "nothing": False})
        self.assertEqual(self._put("cost", {"people": 0, "sends": 1}).status_code, 400)

    def test_health_law_or_money_is_yes_until_the_host_says_no(self):
        """FIRST-15: one yes-or-no; in doubt, yes."""
        self.assertTrue(self._start().get_json()["recipe"]["sensitive"])
        self.assertFalse(self._put("sensitive", False).get_json()["recipe"]["sensitive"])
        self.assertEqual(self._put("sensitive", "maybe").status_code, 400)

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
                               "link": link})
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
        for part, value in parts.items():
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
        """FIRST-11: Not yet keeps it saved, and nobody meets it; Yes opens it."""
        chat = self._host(live=False)
        self.assertIsNone(self.client.get(f"/v2/chats/{chat}/host", headers=self._as(PIOTR)).get_json()["host"])
        self._put("live", True)
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
