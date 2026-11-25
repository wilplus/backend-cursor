"""
STORY    As a speaker, I want every chat of my own to be the same kind of chat,
         in one flat list, each holding what I wrote there, so that I decide
         what a chat is by how I use it (founder, N700).
OUTCOME
  O1  A message written in a chat stays in it; a message written before
      N700 is read into its project's chat (by its project, or by its Take),
      else into the chat that carries on its old section.
  O2  Will's unprompted message (no chat, no Take) goes to the chat the
      speaker used last; the speaker's own words and a Take's rows keep
      their place.
  O3  A chat turn sent from one of the speaker's own chats names it and
      makes it the chat used last; a chat that is not theirs names none.
  O4  A page of messages says, row by row, the chat each belongs to; with no
      own chats yet it is left as it was.
PROVES   O1 -> test_a_message_belongs_to_its_chat_and_older_ones_find_theirs
         O2 -> test_will_s_unprompted_message_goes_to_the_chat_used_last
         O3 -> test_a_turn_names_only_the_speaker_s_own_chat
         O4 -> test_a_page_says_each_row_s_chat
"""
from __future__ import annotations

import unittest
from unittest import mock

from services import own_chats

COACH = {"id": "chat-coach", "legacy_place": "speaking", "arc_id": None}
PRINCIPLES = {"id": "chat-principles", "legacy_place": "principles", "arc_id": None}
TALK = {"id": "chat-talk", "legacy_place": None, "arc_id": "arc-1"}
NEW = {"id": "chat-new", "legacy_place": None, "arc_id": None}
CHATS = [COACH, PRINCIPLES, TALK, NEW]


def _row(role="user", kind="text", **meta):
    return {"role": role, "kind": kind, "body": "x", "metadata": meta}


class OwnChats(unittest.TestCase):
    def test_a_message_belongs_to_its_chat_and_older_ones_find_theirs(self):
        of = lambda row, takes=None: own_chats.chat_of_row(row, CHATS, takes)  # noqa: E731
        self.assertEqual(of(_row(chat_id="chat-new")), "chat-new")
        self.assertIsNone(of(_row(chat_id="someone-elses")))
        self.assertEqual(of(_row(role="bot", kind="walk_step", arc_id="arc-1")), "chat-talk")
        self.assertEqual(of(_row(role="bot", kind="walk_step", take_session_id="take-9"),
                            {"take-9": "arc-1"}), "chat-talk")
        self.assertEqual(of(_row(place="speaking")), "chat-coach")
        self.assertEqual(of(_row(role="bot", offer="sunday_note")), "chat-coach")

    def test_will_s_unprompted_message_goes_to_the_chat_used_last(self):
        rows = [
            _row(role="bot", kind="text", offer="your_why_ask"),
            _row(role="user", kind="text"),
            _row(role="bot", kind="walk_step", take_session_id="take-9"),
            _row(role="bot", kind="text", chat_id="chat-talk"),
        ]
        with mock.patch.object(own_chats, "last_used", lambda _db, _user: "chat-new"):
            out = own_chats.stamp_unplaced(object(), "user-1", rows)
        self.assertEqual(out[0]["metadata"]["chat_id"], "chat-new")
        self.assertNotIn("chat_id", out[1]["metadata"])
        self.assertNotIn("chat_id", out[2]["metadata"])
        self.assertEqual(out[3]["metadata"]["chat_id"], "chat-talk")
        with mock.patch.object(own_chats, "last_used", lambda _db, _user: None):
            self.assertEqual(own_chats.stamp_unplaced(object(), "user-1", rows[:1]), rows[:1])

    def test_a_turn_names_only_the_speaker_s_own_chat(self):
        from routes.v2 import coaching

        touched = []
        with mock.patch.object(own_chats, "owned", lambda _db, user, chat: chat == "chat-new" and user == "user-1"), \
                mock.patch.object(own_chats, "touch", lambda _db, user, chat: touched.append(chat)):
            self.assertEqual(coaching._own_chat_scope({"own_chat": "chat-new"}, "user-1"), {"chat_id": "chat-new"})
            self.assertEqual(coaching._own_chat_scope({"own_chat": "chat-other"}, "user-1"), {})
            self.assertEqual(coaching._own_chat_scope({"own_chat": None}, "user-1"), {})
        self.assertEqual(touched, ["chat-new"])
        self.assertEqual(coaching._with_own_chat({"arc_id": "arc-1"}, {"chat_id": "c"}),
                         {"arc_id": "arc-1", "chat_id": "c"})
        self.assertIsNone(coaching._with_own_chat(None, {}))

    def test_a_page_says_each_row_s_chat(self):
        page = [_row(chat_id="chat-new"), _row(role="bot", kind="walk_step", arc_id="arc-1"), _row(place="speaking")]
        own_chats.label_page(page, CHATS)
        self.assertEqual([m["own_chat_id"] for m in page], ["chat-new", "chat-talk", "chat-coach"])
        bare = [_row(place="speaking")]
        own_chats.label_page(bare, [])
        self.assertNotIn("own_chat_id", bare[0])


if __name__ == "__main__":
    unittest.main()
