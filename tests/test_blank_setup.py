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
         N642.1   -> SetupTest::test_a_chat_has_a_name_its_first_name_until_given
         N642.1   -> VisitorTest::test_people_who_come_read_the_chats_name
         N642.3   -> SetupTest::test_live_reads_what_a_person_meets_and_can_be_tried
         N642.3   -> TokensTest::test_my_own_trial_answers_at_once_keeps_nothing_costs_nothing
         N646.1   -> SetupTest::test_a_models_answers_come_from_its_question
         N646.3   -> SetupTest::test_the_answers_can_change_until_an_answer_counted
         N641.1   -> SetupTest::test_the_feedback_walk_is_kept_in_a_chat_that_takes_a_recording
         N641.2   -> SetupTest::test_i_want_this_tells_the_founder_once
         N641.2   -> SetupTest::test_the_ask_is_kept_when_the_mail_cannot_go
         N632.2   -> SetupTest::test_what_the_first_take_said_opens_what_you_do
         N632.3   -> SetupTest::test_a_chat_that_takes_a_recording_is_a_skill_chat
         N632.4   -> SetupTest::test_start_again_begins_blank_and_keeps_only_the_same_model
         N632.6   -> SetupTest::test_not_now_is_never_final
         N634.1   -> SetupTest::test_an_own_model_is_built_on_gpt
         N636.6   -> SetupTest::test_an_own_model_gives_back_a_pick
         N636.6   -> SetupTest::test_a_changed_question_keeps_the_same_model
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
         FIRST-24 -> LearningTest::test_one_that_passes_free_answers_without_a_price_to_accept
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
        """FIRST-07: one question and two or three answers (N646 item 2:
        never one, never four)."""
        self._start()
        self.assertEqual(self._put("models", [self._model()]).status_code, 200)
        self.assertEqual(self._put("models", [{"q": "Is it dry?", "opts": ["Yes"]}]).status_code, 400)
        self.assertEqual(self._put("models", [{"q": "Is it dry?", "opts": ["Yes", "No", "Maybe", "Other"]}])
                         .status_code, 400)
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

    def test_what_the_first_take_said_opens_what_you_do(self):
        """N632 item 2: the field the person's first Take told the app is
        "What do you do?"'s first answer, to keep or change; none heard,
        none given. No provider call."""
        from services.db import db
        with patch.object(db, "get_open_plan", lambda _u: {"facts": {"topic": "hair loss"}}, create=True):
            self.assertEqual(self._read()["spec_guess"], "Hair loss")
        with patch.object(db, "get_open_plan", lambda _u: {"facts": {}}, create=True):
            self.assertIsNone(self._read()["spec_guess"])
        self.assertEqual(self.provider.calls, [])

    def test_a_chat_that_takes_a_recording_is_a_skill_chat(self):
        """N632 item 3: "coached, or a topic" is never asked: a chat whose
        people send a recording is a skill chat, any other a topic chat,
        on every save."""
        self._start("Voice coach")
        fit = self._put("send", ["rec", "text"]).get_json()["recipe"]["fit"]
        self.assertEqual(fit, {"coaches": "skill", "needs": "talking", "topics": [], "skill": "voice coach"})
        fit = self._put("send", ["text"]).get_json()["recipe"]["fit"]
        self.assertEqual(fit, {"coaches": "topic", "needs": "any", "topics": ["Voice coach"]})

    def test_start_again_begins_blank_and_keeps_only_the_same_model(self):
        """N632 item 4: "Start again" begins again from "What do you do?",
        the chat not open, nothing of the old answers kept; the host's own
        model kept again is the same real model, never a second."""
        def rings(feature, user_id, database=None):
            del database
            return feature in ("chat_builder", "ai_models") and str(user_id) == TOMEK
        with patch("services.rings.feature_is_on_for_user", rings):
            self._start()
            card = self._put("models", [self._model()]).get_json()["recipe"]["models"][0]
            self._put("hello", "Hi, show me your scalp.")
            self._put("care", False)
            self._put("live", True)
            again = self._start("Barber").get_json()["recipe"]
            self.assertEqual((again["spec"], again["live"], again["models"]), ("Barber", False, []))
            self.assertNotEqual(again["hello"], "Hi, show me your scalp.")
            self.assertTrue(again["sensitive"])
            kept = self._put("models", [self._model()]).get_json()["recipe"]["models"][0]
        self.assertEqual(kept["model_id"], card["model_id"])
        self.assertEqual(len(self.store.tables["ai_models"]), 1)

    def test_not_now_is_never_final(self):
        """N632 item 6: after "Not now" and with the chat live, every part
        stays changeable: the host turns models on, makes one (it gets its
        real model), shares at a price and changes the rest, and the chat
        stays live; only /live itself closes it."""
        def rings(feature, user_id, database=None):
            del database
            return feature in ("chat_builder", "ai_models") and str(user_id) == TOMEK
        with patch("services.rings.feature_is_on_for_user", rings):
            self._start()
            self._put("smart", False)                            # "Not now"
            self._put("care", False)
            self.assertTrue(self._put("live", True).get_json()["recipe"]["live"])
            for part, value in (("smart", True), ("way", "own"), ("models", [self._model()]),
                                ("share", True), ("price", 3), ("who", "assistant"), ("send", ["rec", "text"]),
                                ("hello", "Hi. Show me your scalp."), ("questions", [{"q": "What worries you?"}]),
                                ("taps", ["Ask for advice"]), ("line", "People come to you about their hair.")):
                got = self._put(part, value)
                self.assertEqual(got.status_code, 200, part)
                recipe = got.get_json()["recipe"]
                self.assertTrue(recipe["live"], part)
            self.assertTrue(recipe["models"][0].get("model_id"))
            self.assertEqual((recipe["smart"], recipe["share"], recipe["price"], recipe["who"]),
                             (True, True, 3, "assistant"))
            self.assertFalse(self._put("live", False).get_json()["recipe"]["live"])

    def test_an_own_model_is_built_on_gpt(self):
        """N634 item 1: an own model's card keeps what it is built on; only
        "gpt" is ready, "claude" and "own" are refused, and a card saved
        with none reads as built on GPT."""
        self._start()
        self.assertEqual(self._put("models", [{**self._model(), "base": "gpt"}]).get_json()
                         ["recipe"]["models"][0]["base"], "gpt")
        for not_ready in ("claude", "own", "llama"):
            got = self._put("models", [{**self._model(), "base": not_ready}])
            self.assertEqual((got.status_code, got.get_json()["code"]), (400, "RECIPE_INVALID"))
        self.assertEqual(self._put("models", [self._model()]).get_json()["recipe"]["models"][0]["base"], "gpt")
        row = next(r for r in self.store.tables["people_profiles"] if r["user_id"] == TOMEK)
        row["chat_recipe"]["models"][0].pop("base")             # a card saved before N634
        self.assertEqual(self._read()["recipe"]["models"][0]["base"], "gpt")

    def test_an_own_model_gives_back_a_pick(self):
        """N636 item 6: an own model's card keeps what it gives back; only
        "pick" is ready, "score" and "answer" are refused, and a card saved
        with none reads as a pick."""
        self._start()
        self.assertEqual(self._put("models", [{**self._model(), "gives": "pick"}]).get_json()
                         ["recipe"]["models"][0]["gives"], "pick")
        for not_ready in ("score", "answer", "essay"):
            got = self._put("models", [{**self._model(), "gives": not_ready}])
            self.assertEqual((got.status_code, got.get_json()["code"]), (400, "RECIPE_INVALID"))
        self.assertEqual(self._put("models", [self._model()]).get_json()["recipe"]["models"][0]["gives"], "pick")
        row = next(r for r in self.store.tables["people_profiles"] if r["user_id"] == TOMEK)
        row["chat_recipe"]["models"][0].pop("gives")            # a card saved before N636
        self.assertEqual(self._read()["recipe"]["models"][0]["gives"], "pick")

    def test_a_models_answers_come_from_its_question(self):
        """N646.1, N646.2: a question that names the things to tell apart
        gives those things, then "Not sure"; a yes-or-no question "Yes",
        "No", "Not sure"; Will's suggestions are fixed the same way, in the
        same one call; never four answers."""
        def rings(feature, user_id, database=None):
            del database
            return feature in ("chat_builder", "ai_models") and str(user_id) == TOMEK

        def answers(q, who=TOMEK):
            return self.client.post("/v2/models/setup/answers", json={"question": q}, headers=self._as(who))
        with patch("services.rings.feature_is_on_for_user", rings):
            self.assertEqual(answers("Is the wood cracked or broken?").get_json(),
                             {"sets": [["Cracked", "Broken", "Not sure"], ["Cracked", "Broken"]]})
            self.assertEqual(answers("Is this a quote, a paraphrase or neither?").get_json()["sets"][0],
                             ["Quote", "Paraphrase", "Neither"])
            plain = answers("Is this a dry scalp?").get_json()["sets"]
            self.assertEqual(plain[0], ["Yes", "No", "Not sure"])
            for got in (plain, answers("Is it red, green, blue or yellow?").get_json()["sets"]):
                self.assertTrue(all(2 <= len(one) <= 3 for one in got) and len(got) <= 3)
            self.assertNotIn(["Yes", "No", "Not sure"], answers("Is the wood cracked or broken?").get_json()["sets"])
            self.assertEqual(answers("").status_code, 400)
            self.provider.answer = {"models": [{"q": "Is the wood cracked or broken?",
                                                "opts": ["Yes", "No", "Not sure"], "says": "It is cracked."}]}
            sug = self._start("Carpenter").get_json()["recipe"]["suggest"]
            self.assertEqual(sug["models"][0]["opts"], ["Cracked", "Broken", "Not sure"])
            self.assertEqual(self.provider.calls, ["chat_setup_suggest"])
            four = {**self._model("Is it red or green?"), "opts": ["Red", "Green", "Blue", "Not sure"]}
            refused = self._put("models", [four])
            self.assertEqual((refused.status_code, refused.get_json()["code"]), (400, "TOO_MANY_ANSWERS"))
            def blocks(answers_given):
                return self.client.post("/v2/models/setup/blocks", headers=self._as(TOMEK),
                                        json={"question": "Is it red or green?", "answers": answers_given})
            self.assertEqual(blocks(four["opts"]).get_json()["code"], "TOO_MANY_ANSWERS")
            for bad in (["Red"], ["Red", "red"], ["Red", ""], ["Red", "x" * 25]):
                self.assertEqual(blocks(bad).get_json()["code"], "BAD_ANSWERS", bad)
            # Two answers are a model too, on both routes.
            two = blocks(["Red", "Green"])
            self.assertEqual(two.status_code, 200)
            made = next(r for r in self.store.tables["ai_models"] if r["id"] == two.get_json()["model_id"])
            self.assertEqual((made["status"], made["recipe"]["scale"]), ("learning", ["Red", "Green"]))
            card = self._put("models", [{**self._model("Is it dry or oily?"), "opts": ["Dry", "Oily"]}])
            self.assertEqual(card.get_json()["recipe"]["models"][0]["opts"], ["Dry", "Oily"])
        self.assertEqual(answers("Is it dry?", PIOTR).status_code, 404)  # no ring

    def test_the_answers_can_change_until_an_answer_counted(self):
        """N646.3, N646.4: the answers change in the setup, on the card or on
        the model's own scale step, and the model keeps what the card says;
        at most three; once an answer counted they may not (409
        ANSWERS_LOCKED)."""
        def rings(feature, user_id, database=None):
            del database
            return feature in ("chat_builder", "ai_models") and str(user_id) == TOMEK
        with patch("services.rings.feature_is_on_for_user", rings):
            self._start()
            card = self._put("models", [{**self._model("Is the wood cracked or broken?"),
                                         "opts": ["Cracked", "Broken", "Not sure"]}]).get_json()["recipe"]["models"][0]
            mid = card["model_id"]
            edited = {**card, "opts": ["Cracked", "Split", "Not sure"]}
            self.assertEqual(self._put("models", [edited]).status_code, 200)
            model = next(r for r in self.store.tables["ai_models"] if r["id"] == mid)
            self.assertEqual(model["recipe"]["scale"], ["Cracked", "Split", "Not sure"])
            def scale(words):
                return self.client.post(f"/v2/models/{mid}/setup/scale", headers=self._as(TOMEK),
                                        json={"scale": [{"t": w, "d": ""} for w in words]})
            too_many = scale(["Cracked", "Split", "Broken", "Not sure"])
            self.assertEqual((too_many.status_code, too_many.get_json()["code"]), (400, "TOO_MANY_ANSWERS"))
            self.store.tables.setdefault("ai_model_answers", []).append(
                {"id": "a1", "model_id": mid, "counted": True, "step": "rate", "answer": "Cracked"})
            locked = self._put("models", [{**edited, "opts": ["Cracked", "Broken", "Not sure"]}])
            self.assertEqual((locked.status_code, locked.get_json()["code"]), (409, "ANSWERS_LOCKED"))
            self.assertEqual(scale(["Cracked", "Broken", "Not sure"]).status_code, 409)
            self.assertEqual(self._put("models", [edited]).status_code, 200)  # unchanged is fine
        self.assertEqual(next(r for r in self.store.tables["ai_models"] if r["id"] == mid)["recipe"]["scale"],
                         ["Cracked", "Split", "Not sure"])

    def test_a_changed_question_keeps_the_same_model(self):
        """N636 item 6: a block changed and the card saved again with its
        model_id keeps that one model; no second model is made."""
        def rings(feature, user_id, database=None):
            del database
            return feature in ("chat_builder", "ai_models") and str(user_id) == TOMEK
        with patch("services.rings.feature_is_on_for_user", rings):
            self._start()
            card = self._put("models", [self._model()]).get_json()["recipe"]["models"][0]
            changed = {**card, "q": "Is the scalp dry?", "opts": ["Yes", "A bit", "No"]}
            again = self._put("models", [changed]).get_json()["recipe"]["models"][0]
        self.assertEqual(again["model_id"], card["model_id"])
        self.assertEqual(len(self.store.tables["ai_models"]), 1)

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
        self.assertEqual(own, {"title": "Tomek", "named": False, "line": "Hi. Send me a photo of your scalp, and tell me what worries you.",
                               "link": link,
                               "join_line": "People come to Tomek with hair and scalp worries.",
                               "about": [], "hello": "Hi. Send me a photo of your scalp, and tell me what worries you.",
                               "taps": ["Look at my scalp", "My hair is falling out", "Which shampoo", "Something else"],
                               "can_try": True})
        self.assertEqual(link["path"], f"/c/{link['token']}")

    def test_to_change_the_chat_tell_will(self):
        """FIRST-21: any words open the chat's parts again."""
        self._start()
        res = self.client.post("/v2/chats/setup/edit", json={"said": "I want to edit my chat"},
                               headers=self._as(TOMEK)).get_json()
        self.assertEqual(res["line"], "Here are your chat's parts. Tap one to change it.")
        self.assertEqual([p["title"] for p in res["parts"]],
                         ["Name", "Why people come", "They send", "They get back", "Your hello",
                          "First questions", "They can ask", "Your models", "Who answers"])

    def test_live_reads_what_a_person_meets_and_can_be_tried(self):
        """N642.3: Live shows the chat as people meet it, the visitor's host
        read's own lines (about, hello, taps with "Something else" last),
        and the switch shows once there is something to try."""
        self.assertFalse(self._read()["can_try"])
        self._start()
        self._put("hello", "Welcome. Show me.")
        self._put("taps", ["One", "Two"])
        read = self._read()
        own = read["own_chat"]
        self.assertTrue(read["can_try"] and own["can_try"])
        self.assertEqual((own["hello"], own["taps"], own["about"]),
                         ("Welcome. Show me.", ["One", "Two", "Something else"], []))
        # The same lines a person who comes reads in the chat's header.
        self._put("live", True)
        chat = self._join(PIOTR, self._link(TOMEK).get_json()["token"]).get_json()["chat"]["id"]
        host = self.client.get(f"/v2/chats/{chat}/host", headers=self._as(PIOTR)).get_json()["host"]
        self.assertEqual((host["hello"], host["taps"], host["about"]), (own["hello"], own["taps"], own["about"]))

    def test_a_chat_has_a_name_its_first_name_until_given(self):
        """N642.1: "Your chat is called:" with three suggestions from the
        first name and what the person does; until a name is given the chat
        is called by the first name; the name is a part, "Name", first; at
        most 40 characters, with the host's word checks."""
        started = self._start().get_json()["recipe"]
        self.assertEqual(started["suggest"]["name"], ["Tomek's chat", "Ask Tomek", "Trichologist with Tomek"])
        read = self._read()
        self.assertIsNone(read["recipe"]["name"])
        self.assertEqual(read["recipe"]["suggest"]["name"], started["suggest"]["name"])
        self.assertEqual(read["parts"][0], {"part": "name", "title": "Name", "value": "Tomek"})
        self.assertEqual((read["own_chat"]["title"], read["own_chat"]["named"]), ("Tomek", False))
        self.assertEqual(self._put("name", "x" * 41).status_code, 400)
        bad = self._put("name", "I'll give you a score out of 10.")
        self.assertEqual((bad.status_code, bad.get_json()["code"]), (400, "RECIPE_WORDS"))
        self.assertEqual(self._put("name", "  Ask   Tomek ").get_json()["recipe"]["name"], "Ask Tomek")
        read = self._read()
        self.assertEqual(read["parts"][0]["value"], "Ask Tomek")
        self.assertEqual((read["own_chat"]["title"], read["own_chat"]["named"]), ("Ask Tomek", True))
        self.assertEqual(read["own_chat"]["join_line"], "People come to Ask Tomek with hair and scalp worries.")

    def test_the_feedback_walk_is_kept_in_a_chat_that_takes_a_recording(self):
        """N641.1: "The feedback walk" holds steps from best, fix, words in
        the host's order, and an Ideal Text or nothing at the end; it is a
        part only in a chat that takes a recording; unsaved, it reads as
        the suggestion; a visitor meets nothing of it."""
        self._start()
        self.assertEqual(self._put("walk", {"steps": ["best"], "out": "none"}).status_code, 400)
        self.assertNotIn("walk", [p["part"] for p in self._read()["parts"]])
        self._put("send", ["rec", "text"])
        read = self._read()
        self.assertNotIn("walk", read["recipe"])
        self.assertEqual(read["recipe"]["suggest"]["walk"], {"steps": ["best", "fix", "words"], "out": "ideal_text"})
        row = [p for p in read["parts"] if p["part"] == "walk"][0]
        self.assertEqual(row, {"part": "walk", "title": "The feedback walk", "saved": False,
                               "value": "Their best moment · One moment to try another way · "
                                        "The helper words · An Ideal Text",
                               "walk": {"steps": ["best", "fix", "words"], "out": "ideal_text"}})
        self.assertEqual([p["part"] for p in read["parts"]][3:5], ["out", "walk"])
        for bad in ({"steps": [], "out": "none"}, {"steps": ["best", "best"], "out": "none"},
                    {"steps": ["score"], "out": "none"}, {"steps": ["fix"], "out": "verdict"}, ["fix"]):
            self.assertEqual(self._put("walk", bad).status_code, 400, bad)
        before = {k: self._read()["recipe"][k] for k in ("answer_with", "welcome", "fit")}
        saved = self._put("walk", {"steps": ["words", "best"], "out": "none", "wanted": True})
        self.assertEqual(saved.get_json()["recipe"]["walk"], {"steps": ["words", "best"], "out": "none"})
        row = [p for p in self._read()["parts"] if p["part"] == "walk"][0]
        self.assertEqual((row["value"], row["walk"], row["saved"]),
                         ("The helper words · Their best moment · Nothing for now",
                          {"steps": ["words", "best"], "out": "none"}, True))
        self.assertEqual({k: self._read()["recipe"][k] for k in before}, before)

    def _want(self):
        return self.client.post("/v2/chats/setup/walk/want", headers=self._as(TOMEK))

    def test_i_want_this_tells_the_founder_once(self):
        """N641.2: "I want this" sends the founder one mail naming the host
        and their walk, keeps the ask, and a second tap sends nothing; no
        number comes back; only for the ring chat_builder."""
        from config import Config
        self._start()
        self._put("send", ["rec"])
        self._put("walk", {"steps": ["fix", "best"], "out": "ideal_text"})
        with patch("services.email_service.send_email_resend") as mail:
            self.assertEqual(self._want().get_json(), {"wanted": True})
            self.assertEqual(self._want().get_json(), {"wanted": True})
        self.assertEqual(mail.call_count, 1)
        sent = mail.call_args.kwargs
        self.assertEqual(sent["to"], Config().ADMIN_EMAIL)
        self.assertIn(TOMEK, sent["text"])
        self.assertIn("One moment to try another way, then Their best moment", sent["text"])
        self.assertIn("An Ideal Text", sent["text"])
        walk = self._read()["recipe"]["walk"]
        self.assertTrue(walk["wanted"] and walk["wanted_at"])
        # Changing the walk afterwards keeps the ask; a third tap sends nothing.
        self._put("walk", {"steps": ["best"], "out": "none"})
        with patch("services.email_service.send_email_resend") as mail:
            self._want()
        self.assertEqual((mail.call_count, self._read()["recipe"]["walk"]["wanted"]), (0, True))
        self.assertEqual(self.client.post("/v2/chats/setup/walk/want", headers=self._as(PIOTR)).status_code, 404)

    def test_the_ask_is_kept_when_the_mail_cannot_go(self):
        """N641.2: no key or a provider error: the ask is kept, the answer
        is the same, the failure is logged."""
        self._start()
        self._put("send", ["rec"])
        with patch("services.email_service.send_email_resend", side_effect=RuntimeError("RESEND_API_KEY")), \
                self.assertLogs("services.chat_recipes", "WARNING"):
            res = self._want()
        self.assertEqual((res.status_code, res.get_json()), (200, {"wanted": True}))
        self.assertTrue(self._read()["recipe"]["walk"]["wanted"])


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

    def test_people_who_come_read_the_chats_name(self):
        """N642.1: the join page, the chat's header and the visitor's row
        carry the chat's name; the person stays the one who invited, whose
        assistant answers and whose model it is; the host's own row still
        names the visitor."""
        chat = self._host(name="Ask Tomek")
        token = self._link(TOMEK).get_json()["token"]
        page = self.client.get(f"/v2/chats/join/{token}").get_json()
        self.assertEqual((page["chat"], page["name"], page["invited"], page["assistant"]),
                         ("Ask Tomek", "Tomek", "Tomek invited you", "Tomek's assistant"))
        self.assertEqual(page["learn"], "People come to Ask Tomek with hair and scalp worries.")
        host = self.client.get(f"/v2/chats/{chat}/host", headers=self._as(PIOTR)).get_json()["host"]
        self.assertEqual((host["name"], host["assistant"], host["models"][0]["by"]),
                         ("Ask Tomek", "Tomek's assistant", "Tomek's model"))
        row = self.client.get("/v2/chats", headers=self._as(PIOTR)).get_json()["chats"][0]
        self.assertEqual(row["title"], "Ask Tomek")
        self.assertEqual(self.client.get("/v2/chats", headers=self._as(TOMEK)).get_json()["chats"][0]["title"],
                         "Piotr")
        # A chat not open to people yet keeps the first name for them.
        self._put("live", False)
        self.assertEqual(self.client.get("/v2/chats", headers=self._as(PIOTR)).get_json()["chats"][0]["title"],
                         "Tomek")

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

    def test_my_own_trial_answers_at_once_keeps_nothing_costs_nothing(self):
        """N642.3: the host's own trial answers at once whatever "Who
        answers" says, before any minimum of answers; it writes no message
        and no "Was this useful?" row; it never charges (no
        pay_for_chat_line), and another person's model answers in it free."""
        self._host(who="assistant", sensitive=False)  # no answers of the host's own yet
        self._put("models", [self._model(), {"q": "Are there flakes?", "opts": ["Yes", "Somewhat", "No"],
                                             "own": False, "model_id": JOB, "by": "Kasia", "price": 3}])
        before = list(self.store.tables.get("chat_messages", []))
        with patch("services.model_api_store.pay_for_chat_line",
                   side_effect=AssertionError("a trial is never charged")):
            for who in ("shadow", "you", "assistant"):
                self._put("who", who)
                res = self.client.post("/v2/chats/setup/try", json={"body": "My scalp itches."},
                                       headers=self._as(TOMEK))
                self.assertEqual(res.status_code, 200, who)
                got = res.get_json()
                self.assertNotIn("waits", got)
                self.assertIn(("There are some flakes.", "Kasia's model"),
                              [(m["body"], m["by"]) for m in got["messages"]], who)
        self.assertEqual(self.store.tables.get("chat_messages", []), before)
        self.assertEqual(self.ledger, [])

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
        def words(value):  # what a person reads: no ids or times, which are random
            if isinstance(value, dict):
                return {k: words(v) for k, v in value.items() if k not in ("id", "created_at", "to")}
            return [words(v) for v in value] if isinstance(value, list) else value
        for never in ("price", "token", "300"):
            self.assertNotIn(never, str(words(sent)))
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

    def test_one_that_passes_free_answers_without_a_price_to_accept(self):
        """FIRST-24: when it passes and Ola's price is 0, Tomek has nothing
        to accept: on the next read it is a used card at 0, it gives its
        line and nothing is charged."""
        chat = self._chat()
        self._passes()
        next(m for m in self.store.tables["ai_models"] if m["id"] == LM)["price_units"] = 0
        self.assertEqual(self._lines(self._send(chat).get_json()["reply"]),
                         [("Your scalp looks dry here.", "Tomek's model"), ("There are some flakes.", "Ola's model")])
        self.assertEqual(self.ledger, [])
        card = self._read()["recipe"]["models"][1]
        self.assertEqual((card.get("learning"), card["price"]), (None, 0))
        self.assertEqual(self._read()["price_changes"], [])


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

