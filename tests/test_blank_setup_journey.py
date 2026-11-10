"""
STORY    As someone who knows a field, I want to set up a chat with Will from
         a blank start and open it, and as a second person I want to join it
         and get an answer, so that the whole journey works end to end, for
         any profession, at a small cost (N619 step 5 "Joined"; N620).
OUTCOME  One test walks the public routes for two professions: setup, the
         link, a visitor who joins, "Only you answer" (no provider call),
         "I draft, you send" (one call, the host sends it), and the
         speaking loop untouched. It prints what the journey cost.
PROVES   JOURNEY -> JourneyTest::test_the_whole_journey_for_a_trichologist
         JOURNEY -> JourneyTest::test_the_whole_journey_for_a_language_teacher
WHY      The build succeeds when a stranger sets up a chat with Will and a
         second person gets a useful answer in it (N620); a visitor's
         message costs at most two provider calls, and one setup at most one.
"""
from __future__ import annotations

from tests.test_blank_setup import PIOTR, TOMEK, _Base

#: Tables of the speaking loop: this journey never writes a row to one.
SPEAKING = ("snippet", "take", "walk", "plan", "practice")


class JourneyTest(_Base):
    def _visitor_send(self, chat, body):
        return self.client.post(f"/v2/chats/{chat}/messages", json={"kind": "text", "body": body},
                                headers=self._as(PIOTR))

    def _walk(self, what):
        """The host's setup, every part kept as Will first suggested it."""
        first = self._start(what).get_json()["recipe"]
        self.assertTrue(first["sensitive"], "health, law or money is yes until answered")
        refused = self._put("who", "assistant")
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (400, "RECIPE_INVALID"))
        self.assertEqual(self._put("care", False).status_code, 200)
        self.assertEqual(self._put("who", "assistant").status_code, 200)
        for part, value in (("line", first["suggest"]["line"][0]), ("send", first["send"]),
                            ("out", first["out"]), ("hello", first["hello"]),
                            ("questions", first["questions"]), ("taps", first["taps"]), ("smart", False)):
            res = self._put(part, value)
            self.assertEqual(res.status_code, 200, (part, res.get_json()))

    def _journey(self, what):
        """One profession, start to finish; returns (setup calls, per-message calls)."""
        # 1-2. A first person sets up the chat.
        self._walk(what)
        self.assertEqual(self._put("who", "you").status_code, 200)
        self.assertEqual(self._put("live", True).status_code, 200)
        setup_calls = len(self.provider.calls)

        # 3. The setup shows their chat, with a link.
        own = self._read()["own_chat"]
        link = self._link(TOMEK).get_json()
        self.assertEqual(own["link"], link)
        self.assertTrue(own["join_line"].startswith("People come to Tomek "), own["join_line"])
        recipe = self._read()["recipe"]

        # 4. A second person joins by the link: hello first, the taps, then a message.
        chat = self._join(PIOTR, link["token"]).get_json()["chat"]["id"]
        first = self.client.get(f"/v2/chats/{chat}/messages", headers=self._as(PIOTR)).get_json()["messages"][0]
        self.assertEqual(first["body"], recipe["hello"])
        host = self.client.get(f"/v2/chats/{chat}/host", headers=self._as(PIOTR)).get_json()["host"]
        self.assertEqual(host["taps"][-1], "Something else")
        self.assertEqual(host["taps"][:-1], recipe["taps"])
        before = len(self.provider.calls)
        res = self._visitor_send(chat, "Can you help me with this?")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["reply"], {"waits": True})  # "you": waits for the host
        self.assertEqual(len(self.provider.calls), before, "who = you makes no provider call")

        # 5. "I draft, you send": one call, nothing for the visitor, the host sends it.
        self.assertEqual(self._put("who", "shadow").status_code, 200)
        before = len(self.provider.calls)
        res = self._visitor_send(chat, "And what should I do first?")
        self.assertEqual(res.get_json()["reply"], {"waits": True})
        per_message = len(self.provider.calls) - before
        seen = self.client.get(f"/v2/chats/{chat}/messages", headers=self._as(PIOTR)).get_json()["messages"]
        self.assertFalse(any("reply" in m["meta"] for m in seen), "the visitor gets nothing yet")
        drafts = self.client.get("/v2/chats/setup/drafts", headers=self._as(TOMEK)).get_json()["drafts"]
        self.assertEqual([d["said"] for d in drafts], ["And what should I do first?"])
        sent = self.client.post(f"/v2/chats/setup/drafts/{drafts[0]['message_id']}/send", json={},
                                headers=self._as(TOMEK))
        self.assertEqual(sent.status_code, 200)
        seen = self.client.get(f"/v2/chats/{chat}/messages", headers=self._as(PIOTR)).get_json()["messages"]
        answer = [m for m in seen if "reply" in m["meta"]]
        self.assertEqual([m["body"] for m in answer], [self.provider.answer["answer"]])
        self.assertEqual(answer[0]["meta"]["reply"]["by"], "host")
        return setup_calls, per_message

    def _speaking_loop_untouched(self):
        rows = {name: rows for name, rows in self.store.tables.items()
                if rows and any(word in name for word in SPEAKING)}
        self.assertEqual(rows, {}, "no Take, walk or plan row came from this journey")

    def test_the_whole_journey_for_a_trichologist(self):
        """JOURNEY: a first person sets up a chat (a trichologist), a second person joins, gets the hello and the
        taps, and is answered: waiting for the host, then from a draft the
        host sends. Costs are printed; the speaking loop is untouched."""
        self._run("trichologist")

    def test_the_whole_journey_for_a_language_teacher(self):
        """JOURNEY: the same, for a profession Will has no built-in choices for."""
        self._run("language teacher")

    def _run(self, what):
        setup, per_message = self._journey(what)
        self._speaking_loop_untouched()
        print(f"journey cost ({what}): setup {setup} calls, per visitor message {per_message} calls")
        self.assertLessEqual(per_message, 2)  # N620
        self.assertLessEqual(setup, 1)  # N620
