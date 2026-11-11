"""
STORY    As a speaker in my chat with the speaking host, I want to record a
         Take right there, through the same loop as every Take, so that the
         host's chat can do what the pinned speaking chat does; as the host,
         I never get a speaker's Take unless they send it to me.
OUTCOME
  O1  In my chat with the speaking host, whose recipe takes a recording and
      whose walk ends in an Ideal Text, the chat says "takes" (the list
      and the chat), and my Take, once uploaded, is tagged with it: found by
      ``made_in`` and listed once by ``takes_made_in``. The Take is the same
      Take, with its Ideal Text; nothing is copied, and no push goes.
  O2  Tagging again posts nothing new.
  O3  The door is shut, and nothing is written, for someone not on the ring
      row chat_builder, in a chat with anyone but the speaking host, for a
      recipe without a recording or without a saved walk ending in an Ideal
      Text, and for a Take that is not mine; a withdrawn recording consent
      is refused.
  O4  The host's read of the chat does not expose the Take: no tag among
      the messages or as the list's last line, and neither "Open Take" nor
      the audio opens anything through it.
  O5  A Take made in the chat and also sent there with "Send" are two
      messages; the tag never counts as a send ("Last sent").
  O6  Practice after a Take (N648 item 8): a Take made anywhere else is
      offered practice as today; a Take made in the host's chat only while
      the host has "Practice after a Take" on (off by default); a lookup
      that fails answers yes.
  O7  The host's Developer mode does not count a Take recorded in their
      chat among the people who wrote or recorded.
PROVES   O1 -> TakeDoorTest::test_a_take_recorded_in_the_hosts_chat_is_tagged_with_it
         O2 -> TakeDoorTest::test_tagging_again_posts_nothing
         O3 -> TakeDoorTest::test_the_door_is_shut_elsewhere_and_nothing_is_written
         O4 -> TakeDoorTest::test_the_host_never_gets_the_take_through_the_tag
         O5 -> TakeDoorTest::test_a_take_made_here_and_sent_here_are_two_messages
         O6 -> TakeDoorTest::test_practice_follows_the_hosts_switch_for_a_take_made_in_their_chat
              TakeDoorTest::test_a_practice_cannot_be_started_while_the_hosts_switch_is_off
              TakeDoorTest::test_no_exercise_is_offered_while_the_hosts_switch_is_off
         O7 -> TakeDoorTest::test_the_hosts_developer_mode_does_not_count_the_tag
WHY      N642 item 7, N644, N648 item 8 (founder, 11 November 2026): Artur's
         chat, set up by hand, does what the speaking coach does; the loop
         is never copied or broken (Never 3); a Take reaches someone else
         only when its speaker sends it (Privacy 4f). Built on
         tests/test_take_sends.py's in-memory chat tables.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from config import Config
from services import take_door
from tests import test_take_sends as sends
from tests.test_chats import ME, OTHER

HOST = sends.FOUNDER
RECIPE = {"v": 2, "send": ["rec", "text"], "out": "words",
          "walk": {"steps": ["best"], "out": "ideal_text"}}


class TakeDoorTest(unittest.TestCase):
    setUp_chats = sends.TakeSendsTest.setUp_chats
    setUp_sends = sends.TakeSendsTest.setUp
    _get = sends.TakeSendsTest._get
    _post = sends.TakeSendsTest._post
    _chat_with = sends.TakeSendsTest._chat_with
    _take = sends.TakeSendsTest._take
    _send = sends.TakeSendsTest._send
    _people = sends.TakeSendsTest._people
    _messages = sends.TakeSendsTest._messages

    def setUp(self):
        self.setUp_sends()
        self.ring = {ME, HOST}
        for p in (patch.object(Config, "SPEAKING_HOST_USER_ID", HOST, create=True),
                  patch("services.rings.feature_is_on_for_user",
                        lambda _row, user, **_: str(user) in self.ring)):
            p.start()
            self.addCleanup(p.stop)
        self.store.table("people_profiles").insert(
            {"user_id": HOST, "chat_recipe": dict(RECIPE)}).execute()

    def _recipe(self, **change):
        for row in self.store.tables["people_profiles"]:
            if row["user_id"] == HOST:
                row["chat_recipe"] = {**RECIPE, **change}

    def _tag(self, chat, take):
        return self._post(f"/v2/chats/{chat}/take", {"take": take})

    def _speaking(self, chat):
        listed = {c["id"]: c["takes"] for c in self._get("/v2/chats").get_json()["chats"]}
        read = self._get(f"/v2/chats/{chat}/messages").get_json()["takes"]
        self.assertEqual(listed[chat], read)
        return read

    # ── O1 ───────────────────────────────────────────────────────────────

    def test_a_take_recorded_in_the_hosts_chat_is_tagged_with_it(self):
        chat = self._chat_with(HOST, "Artur")
        take = self._take(index=3)
        self.assertTrue(self._speaking(chat))
        sessions = len(self.store.tables["v2_sessions"])

        res = self._tag(chat, take)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["take"], take)
        self.assertEqual(take_door.made_in(sends.db, take), chat)
        self.assertEqual(take_door.takes_made_in(sends.db, chat), [take])
        # The same Take, with its Ideal Text; nothing copied, nobody told.
        self.assertEqual(len(self.store.tables["v2_sessions"]), sessions)
        self.assertEqual(self.store.tables["v2_sessions"][-1]["ideal_text"], "Their Ideal Text")
        self.assertEqual(self.pushes, [])
        # The speaker sees their Take in the chat.
        said = self._get(f"/v2/chats/{chat}/messages").get_json()["messages"]
        self.assertEqual([(m["mine"], m["kind"], m["meta"]) for m in said],
                         [(True, "take", {"made_here": take, "take_index": 3})])

    # ── O2 ───────────────────────────────────────────────────────────────

    def test_tagging_again_posts_nothing(self):
        chat = self._chat_with(HOST, "Artur")
        take = self._take()
        first = self._tag(chat, take).get_json()
        self.assertEqual(self._tag(chat, take).get_json(), first)
        self.assertEqual(len(self._messages()), 1)
        self.assertEqual(take_door.takes_made_in(sends.db, chat), [take])

    # ── O3 ───────────────────────────────────────────────────────────────

    def test_the_door_is_shut_elsewhere_and_nothing_is_written(self):
        chat = self._chat_with(HOST, "Artur")
        elsewhere = self._chat_with(sends.MAYA, "Maya")
        take = self._take()

        def shut(path_chat=chat, what=take):
            res = self._tag(path_chat, what)
            self.assertEqual(res.status_code, 404)
            self.assertEqual(self._messages(), [])

        shut(elsewhere)                          # not the speaking host
        self.assertFalse(self._speaking(elsewhere))
        shut(what=self._take(owner=OTHER))       # not my Take
        self.ring = {HOST}                       # not on the ring
        shut()
        self.assertFalse(self._speaking(chat))
        self.ring = {ME, HOST}
        for change in ({"send": ["text"]},                               # no recording
                       {"walk": {"steps": ["best"], "out": "none"}},     # no Ideal Text
                       {"walk": None}):                                  # walk never saved
            self._recipe(**change)
            shut()
            self.assertFalse(self._speaking(chat))
        self._recipe()
        self.choices["sensitive_information"] = False  # recording consent withdrawn
        res = self._tag(chat, take)
        self.assertEqual((res.status_code, res.get_json()["code"]),
                         (403, "PROCESSING_RECORDING_WITHDRAWN"))
        self.assertEqual(self._messages(), [])

    # ── O4 ───────────────────────────────────────────────────────────────

    def test_the_host_never_gets_the_take_through_the_tag(self):
        chat = self._chat_with(HOST, "Artur")
        take = self._take()
        tagged = self._tag(chat, take).get_json()["message_id"]

        self.who = HOST
        self.assertEqual(self._get(f"/v2/chats/{chat}/messages").get_json()["messages"], [])
        row = next(c for c in self._get("/v2/chats").get_json()["chats"] if c["id"] == chat)
        self.assertIsNone(row["last"])
        self.assertFalse(row["takes"])
        self.assertEqual(self._get(f"/v2/chats/{chat}/messages/{tagged}/take").status_code, 404)
        with patch("services.lab_audio_storage.get_lab_audio_bytes", lambda key, **_: b"OggS"):
            self.assertEqual(self._get(f"/v2/chats/{chat}/messages/{tagged}/audio").status_code, 404)

    # ── O5 ───────────────────────────────────────────────────────────────

    def test_a_take_made_here_and_sent_here_are_two_messages(self):
        chat = self._chat_with(HOST, "Artur")
        maya = self._chat_with(sends.MAYA, "Maya")
        take = self._take()
        self.assertEqual(self._send(take, {"all": False, "user_ids": [sends.MAYA]}).status_code, 200)
        # Takes made in Artur's chat are no send: Maya stays "Last sent".
        self._tag(chat, take)
        self._tag(chat, self._take(index=3))
        self.assertEqual([p["chat_id"] for p in self._people()["people"] if p["last_sent"]], [maya])
        # The same Take sent to Artur too: its own message beside the tag.
        self.assertEqual(self._send(take, {"all": False, "user_ids": [HOST]}).status_code, 200)
        self.assertEqual(len([m for m in self._messages() if m["thread_id"] == chat]), 3)
        # The host hears the Take that was sent, and only that one.
        self.who = HOST
        said = self._get(f"/v2/chats/{chat}/messages").get_json()["messages"]
        self.assertEqual([m["meta"].get("take_index") for m in said], [2])

    # ── O6 ───────────────────────────────────────────────────────────────

    def test_practice_follows_the_hosts_switch_for_a_take_made_in_their_chat(self):
        chat = self._chat_with(HOST, "Artur")
        here, elsewhere = self._take(index=3), self._take(index=4)
        self._tag(chat, here)
        self.assertTrue(take_door.practice_allowed(sends.db, elsewhere))
        self.assertFalse(take_door.practice_allowed(sends.db, here))
        self._recipe(practice=True)
        self.assertTrue(take_door.practice_allowed(sends.db, here))
        self._recipe(practice=False)
        self.assertFalse(take_door.practice_allowed(sends.db, here))
        with patch.object(take_door, "made_in", side_effect=RuntimeError("down")):
            self.assertTrue(take_door.practice_allowed(sends.db, here))

    def test_a_practice_cannot_be_started_while_the_hosts_switch_is_off(self):
        from types import SimpleNamespace

        from services import practice_start
        from services.refusal import Refusal
        db = SimpleNamespace(get_confident_voice_practice_by_moment=lambda *_a: None)
        with patch.object(practice_start, "_owned_moment", return_value=({}, {"id": "t-1"})), \
                patch.object(practice_start, "_answer_gate"), \
                patch.object(practice_start, "_start_kind", return_value=("library", "x", {})), \
                patch.object(take_door, "practice_allowed", return_value=False):
            with self.assertRaises(Refusal) as refused:
                practice_start.start_practice(db, snippet_id="s-1", body={}, user_id="u-1", answer=None)
        self.assertEqual(refused.exception.status, 403)

    def test_no_exercise_is_offered_while_the_hosts_switch_is_off(self):
        """The one place the exercise offer is decided asks the person's yes
        and the host's switch; both must hold."""
        from services.ideal_text_changes import _ChangesRun
        run = object.__new__(_ChangesRun)
        run.db, run.arm_sid = sends.db, "t-1"
        for person, host, offered in ((True, True, True), (True, False, False),
                                      (False, True, False)):
            with patch.object(_ChangesRun, "_practice_permitted", return_value=person), \
                    patch.object(take_door, "practice_allowed", return_value=host):
                self.assertEqual(run._practice_offered(), offered, (person, host))

    # ── O7 ───────────────────────────────────────────────────────────────

    def test_the_hosts_developer_mode_does_not_count_the_tag(self):
        from datetime import datetime, timedelta, timezone

        from services import dev_mode
        chat = self._chat_with(HOST, "Artur")
        for row in self.store.tables["chat_threads"]:
            if row["id"] == chat:
                row["widget_owner_id"] = HOST
        self._tag(chat, self._take())
        since = datetime.now(timezone.utc) - timedelta(days=7)
        self.assertEqual(dev_mode.people_events(sends.db, HOST, since), [])
        self._post(f"/v2/chats/{chat}/messages", {"kind": "emoji", "body": "👍"})
        self.assertEqual([who for _, who in dev_mode.people_events(sends.db, HOST, since)], [ME])


if __name__ == "__main__":
    unittest.main()
