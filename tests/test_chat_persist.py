"""
STORY    As a speaker, I want every chat turn saved with its buttons, so that
         my chat bubbles never disappear when I reload.
OUTCOME
  O1  POST /v2/chat/query with persist writes my row and the bot's row,
      with the bot's choices in its metadata; posting the same turn again
      writes the same two ids, so the table keeps it once.
  O2  A reload (GET /v2/user/lounge/messages) brings the bot's choices back.
  O3  If saving fails, the turn still answers.
  O4  The bot's reply is saved under my turn even when my browser's clock
      runs ahead of the server's, so a reload keeps the order I saw.
PROVES   O1, O2 -> test_a_turn_is_saved_once_and_its_choices_come_back
         O3     -> test_the_answer_still_comes_when_saving_fails
         O4     -> test_the_reply_is_saved_under_the_turn_it_answers
WHY      Founder #2: bubbles must never disappear; founder 2026-10-20: the
         chat keeps the order it shows. The harness is
         tests/chat_route_fakes.py; what the chat answers is pinned in
         test_chat_answers.py.
"""
from __future__ import annotations

from tests.chat_route_fakes import CHOICE, USER, ChatRouteHarness


class ChatTurnPersistsTests(ChatRouteHarness):
    __test__ = True

    def test_a_turn_is_saved_once_and_its_choices_come_back(self):
        turn = {"question": "replace my deck", "persist": True}
        body = self.post(turn).get_json()
        self.assertEqual(body["suggested_actions"], CHOICE["suggested_actions"])
        user_id, (mine, bot) = self.rows[0]
        self.assertEqual(user_id, USER)
        self.assertEqual((mine["role"], mine["body"]), ("user", "replace my deck"))
        self.assertEqual((bot["role"], bot["body"]), ("bot", CHOICE["answer"]))
        self.assertEqual(bot["metadata"]["suggested_actions"], CHOICE["suggested_actions"])
        self.post(turn)
        self.assertEqual([r["client_id"] for r in self.rows[1][1]],
                         [mine["client_id"], bot["client_id"]])

        # The table hands back what was written, newest first.
        self.thread = list(reversed(self.rows[0][1]))
        # An older-page read: the newest page's live flags are not the subject.
        page = self.client.get("/v2/user/lounge/messages?before=2100-01-01T00:00:00Z",
                               headers={"Authorization": "Bearer t"}).get_json()
        reloaded = [m for m in page["messages"] if m["client_id"] == bot["client_id"]]
        self.assertTrue(reloaded)
        self.assertEqual(reloaded[0]["metadata"]["suggested_actions"],
                         CHOICE["suggested_actions"])

    def test_the_answer_still_comes_when_saving_fails(self):
        self.fail_db = True
        resp = self.post({"question": "what is this?", "persist": True})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["answer"], "It's a voice coach.")
        self.assertEqual(self.rows, [])

    def test_the_reply_is_saved_under_the_turn_it_answers(self):
        from datetime import datetime, timedelta, timezone
        ahead = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        self.post({"question": "what is this?", "persist": True,
                   "client_created_at": ahead})
        mine, bot = self.rows[-1][1]
        self.assertEqual(mine["client_created_at"], ahead)
        self.assertGreater(datetime.fromisoformat(bot["client_created_at"]),
                           datetime.fromisoformat(ahead))
