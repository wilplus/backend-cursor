"""
STORY    As a host, I turn on "Developer mode" under Build and see, in plain
         numbers, how close my chat is to the speaking coach, how each thing
         my chat notices is doing, and how many people came each week; nobody
         else sees any of it (N648 items 1, 2, 3, 5 and 7; the pinned
         prototype docs/design/the-blank-setup-2026-11-10/the-blank-setup.html).
OUTCOME  On the public routes: the host gets their numbers; anyone else 404;
         a week with too few people never shows its count.
PROVES   N648.2 -> DevModeTest::test_the_host_gets_how_close_what_it_notices_and_the_weeks
         N648.3 -> DevModeTest::test_the_host_gets_how_close_what_it_notices_and_the_weeks
         N648.5 -> DevModeTest::test_a_week_of_few_people_is_hidden_in_the_screen_and_the_file
         N648.4 -> DevModeTest::test_what_i_say_and_the_walk_charts
         N648.5 -> DevModeTest::test_what_i_say_and_the_walk_charts
         N648.7 -> DevModeTest::test_anyone_but_the_host_gets_404
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests import test_blank_setup as B
from tests.test_chat_links import PIOTR, TOMEK


def _rings(feature, user_id, database=None):
    del database
    return feature in ("chat_builder", "ai_models") and str(user_id) == TOMEK


class DevModeTest(B._Base):
    _host = B.VisitorTest._host

    def setUp(self):
        super().setUp()
        p = patch("services.rings.feature_is_on_for_user", _rings)
        p.start()
        self.addCleanup(p.stop)

    def _dev(self, who=TOMEK):
        return self.client.get("/v2/chats/setup/dev", headers=self._as(who))

    def _people_in_my_chat(self, chat, weeks_ago, n):
        """``n`` other people each writing once in my chat, ``weeks_ago``."""
        t = self.store.tables
        when = (datetime.now(timezone.utc) - timedelta(weeks=weeks_ago)).isoformat()
        for i in range(n):
            mid = f"m-{weeks_ago}-{i}"
            t["chat_members"].append({"id": mid, "thread_id": chat, "user_id": f"u-{weeks_ago}-{i}",
                                      "display_name": "Someone"})
            t["chat_messages"].append({"id": f"x-{weeks_ago}-{i}", "thread_id": chat, "author_member_id": mid,
                                       "kind": "text", "body": "Hi.", "meta": {}, "created_at": when})

    def test_the_host_gets_how_close_what_it_notices_and_the_weeks(self):
        """N648.2, N648.3: the list is counted from its statuses; each of my
        own models has its level, what it needs, its segments; the people
        who wrote this week are counted."""
        chat = self._host()
        model_id = self._read()["recipe"]["models"][0]["model_id"]
        for i, answer in enumerate(["Yes", "Yes", "No", "No", "Somewhat", "Somewhat", "Yes"]):
            self.store.tables.setdefault("ai_model_examples", []).append(
                {"id": f"e{i}", "model_id": model_id, "source": "teacher", "known_answer": answer,
                 "in_exam": False, "content": "A case."})
        self.store.tables["ai_model_examples"].append(
            {"id": "exam1", "model_id": model_id, "source": "teacher", "known_answer": "Yes", "in_exam": True})
        self._people_in_my_chat(chat, 0, 5)

        res = self._dev()
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual((body["close"]["done"], body["close"]["of"]), (5, 15))
        self.assertEqual(body["close"]["items"][5]["status"], "being_built")
        row = next(r for r in body["notice"] if r["model_id"] == model_id)
        self.assertEqual((row["level_name"], row["next_name"]), ("Still learning", "Learns from cases"))
        self.assertEqual(row["need"], {"step": "settle", "more": 3, "have": 7, "of": 10})
        self.assertEqual((row["pct"], row["segments"], row["examples"]), (70, 7, 8))
        self.assertIsNone(row["experiments"])
        people = next(c for c in body["charts"] if c["name"] == "people")["weeks"]
        self.assertEqual(len(people), 8)
        self.assertEqual(people[-1]["count"], 5)
        self.assertEqual(self.provider.calls, [])

    def test_a_model_checked_by_its_host_needs_the_exam_and_shows_agreement(self):
        """N648.3: past the owner's check, the next level is the exam, and
        how often they agreed is the check's kept of answered."""
        self._host()
        model_id = self._read()["recipe"]["models"][0]["model_id"]
        items = [{"example_id": f"c{i}", "kept": i < 8} for i in range(10)]
        self.store.tables.setdefault("ai_model_versions", []).append(
            {"id": "v1", "model_id": model_id, "number": 1, "status": "draft", "head": {"w": []},
             "owner_check": {"items": items}, "owner_checked_at": "2026-11-10", "exam": None})
        row = next(r for r in self._dev().get_json()["notice"] if r["model_id"] == model_id)
        self.assertEqual(row["level_name"], "Checked by you")
        self.assertEqual(row["need"]["step"], "exam")
        self.assertEqual(row["agreed"], {"a": 8, "b": 10, "from": "check"})

    def test_a_week_of_few_people_is_hidden_in_the_screen_and_the_file(self):
        """N648.5: four people in a week shows "fewer than 5", in the
        screen and in the downloaded file; the file holds weeks and counts
        only, never a person."""
        chat = self._host()
        self._people_in_my_chat(chat, 1, 4)
        people = next(c for c in self._dev().get_json()["charts"] if c["name"] == "people")["weeks"]
        self.assertEqual(people[-2], {"week": people[-2]["week"], "count": None, "fewer_than": 5})
        res = self.client.get("/v2/chats/setup/dev/charts/people.csv", headers=self._as(TOMEK))
        self.assertEqual((res.status_code, res.mimetype), (200, "text/csv"))
        text = res.get_data(as_text=True)
        self.assertEqual(text.splitlines()[0], "week,count")
        self.assertIn("fewer than 5", text)
        self.assertNotIn("u-1-", text)
        self.assertEqual(self.client.get("/v2/chats/setup/dev/charts/nobody.csv",
                                         headers=self._as(TOMEK)).status_code, 404)

    def _walks_in_chats(self, model_id, says, answers, weeks_ago=0):
        """One walk line said in each of len(answers) chats, ``weeks_ago``,
        answered "yes", "no" or None (Skip)."""
        t = self.store.tables
        when = (datetime.now(timezone.utc) - timedelta(weeks=weeks_ago)).isoformat()
        for i, useful in enumerate(answers):
            chat, me = f"w-{weeks_ago}-{i}", f"host-{weeks_ago}-{i}"
            t["chat_members"].append({"id": me, "thread_id": chat, "user_id": TOMEK, "display_name": "Tomek"})
            meta = {"walk_line": {"model_id": model_id, "says": says}, "useful_ask": True,
                    "reply": {"to": f"q-{weeks_ago}-{i}"}}
            if useful:
                meta["useful"] = useful
            t["chat_messages"].append({"id": f"wl-{weeks_ago}-{i}", "thread_id": chat, "author_member_id": me,
                                       "kind": "text", "body": says, "meta": meta, "created_at": when})

    def test_what_i_say_and_the_walk_charts(self):
        """N648.4, N648.5: each line with "Helped a of b" at once and how many
        more answers until 30; walks run and "Did this help?" by week, a week
        of fewer than 5 chats hidden, in the screen and the file."""
        self._host()
        card = self._read()["recipe"]["models"][0]
        self._walks_in_chats(card["model_id"], card["says"], ["yes", "yes", "yes", "no", None])
        self._walks_in_chats(card["model_id"], card["says"], ["yes", "no"], weeks_ago=1)
        body = self._dev().get_json()
        line = next(x for x in body["says"] if x["model_id"] == card["model_id"])
        self.assertEqual((line["helped"], line["more_to_tell"], line["enough_at"]),
                         ({"a": 4, "b": 6}, 24, 30))
        charts = {c["name"]: c["weeks"] for c in body["charts"]}
        self.assertEqual(charts["walks"][-1]["count"], 5)
        self.assertEqual(charts["walks"][-2], {"week": charts["walks"][-2]["week"], "count": None, "fewer_than": 5})
        # Four chats answered this week (one skipped): fewer than 5, hidden.
        self.assertIsNone(charts["helped"][-1]["count"])
        text = self.client.get("/v2/chats/setup/dev/charts/helped.csv", headers=self._as(TOMEK)).get_data(as_text=True)
        self.assertEqual(text.splitlines()[0], "week,count,of")
        self.assertIn("fewer than 5", text)
        for never in ("w-0-", "host-0-", card["says"]):
            self.assertNotIn(never, text)

    def test_anyone_but_the_host_gets_404(self):
        """N648.7: someone in my chat, or anyone without the chat builder,
        gets 404 for the screen and the file; a host with no chat set up too."""
        self.assertEqual(self._dev().status_code, 404)
        self._host()
        self.assertEqual(self._dev(PIOTR).status_code, 404)
        self.assertEqual(self.client.get("/v2/chats/setup/dev/charts/people.csv",
                                         headers=self._as(PIOTR)).status_code, 404)
