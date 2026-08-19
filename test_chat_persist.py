"""BE-owned Lounge persistence for /v2/chat/query (#2 — bubbles must never
disappear). Unit-tests the pure persistence helper with a stubbed db (no
network, no Flask request context).

Run: python3 -m unittest test_chat_persist
"""
from __future__ import annotations

import unittest
import uuid

try:
    from routes import v2_routes as v2
    _RT_ERR = None
except Exception as e:  # pragma: no cover
    v2 = None
    _RT_ERR = e


@unittest.skipIf(_RT_ERR is not None, f"needs app deps: {_RT_ERR}")
class PersistChatTurnTests(unittest.TestCase):
    def setUp(self):
        self.captured = []
        self._orig = getattr(v2.db, "insert_lounge_messages", None)

        def _fake(user_id, messages):
            self.captured.append((user_id, messages))
            return [{"id": "srv", **m} for m in messages]

        v2.db.insert_lounge_messages = _fake

    def tearDown(self):
        if self._orig is not None:
            v2.db.insert_lounge_messages = self._orig

    def test_writes_user_and_bot_rows(self):
        cid = str(uuid.uuid4())
        bot_cid = v2._persist_chat_turn(
            "u1", "what is this?", "It's a voice coach.",
            suggested_action=None, bubbles=["It's a voice coach."],
            intent="faq", user_client_id=cid,
            user_created_at="2026-06-22T10:00:00Z",
        )
        self.assertTrue(bot_cid)
        _, msgs = self.captured[0]
        self.assertEqual(len(msgs), 2)
        user_row, bot_row = msgs
        self.assertEqual(user_row["role"], "user")
        self.assertEqual(user_row["client_id"], cid)        # FE id preserved
        self.assertEqual(user_row["body"], "what is this?")
        self.assertEqual(user_row["client_created_at"], "2026-06-22T10:00:00Z")
        self.assertEqual(bot_row["role"], "bot")
        self.assertEqual(bot_row["kind"], "text")
        self.assertEqual(bot_row["body"], "It's a voice coach.")
        self.assertEqual(bot_row["client_id"], bot_cid)

    def test_chip_rides_in_bot_metadata(self):
        # the contextual chip (the thing that vanished on relogin) reconstructs
        # from the persisted bot row's metadata.
        v2._persist_chat_turn(
            "u1", "show my trainings", "Tap the button below.",
            suggested_action="trainings", bubbles=["Tap the button below."],
            intent="library_recall", user_client_id=str(uuid.uuid4()),
        )
        _, msgs = self.captured[0]
        bot_row = msgs[-1]
        self.assertEqual(bot_row["metadata"]["suggested_action"], "trainings")
        self.assertEqual(bot_row["metadata"]["bubbles"], ["Tap the button below."])

    def test_project_choice_pair_rides_in_bot_metadata(self):
        actions = ["replace_pdf", "create_new_project"]
        v2._persist_chat_turn(
            "u1", "replace my deck", "Choose what happens next.",
            suggested_actions=actions,
            intent="replace_pre_take_deck", user_client_id=str(uuid.uuid4()),
        )
        _, msgs = self.captured[0]
        self.assertEqual(msgs[-1]["metadata"]["suggested_actions"], actions)

    def test_deterministic_ids_idempotent(self):
        # same user id → same user+bot client_ids (re-post is a DB no-op).
        cid = str(uuid.uuid4())
        b1 = v2._persist_chat_turn("u1", "hi", "hello", user_client_id=cid)
        b2 = v2._persist_chat_turn("u1", "hi", "hello", user_client_id=cid)
        self.assertEqual(b1, b2)
        self.assertEqual(self.captured[0][1][0]["client_id"],
                         self.captured[1][1][0]["client_id"])

    def test_bot_id_stable_without_fe_client_id(self):
        # no FE client_id → derive deterministically from (user, question).
        b1 = v2._persist_chat_turn("u1", "same q", "ans one")
        b2 = v2._persist_chat_turn("u1", "same q", "ans two")
        # user-turn id is derived from (user, question) → identical
        self.assertEqual(self.captured[0][1][0]["client_id"],
                         self.captured[1][1][0]["client_id"])
        # bot id derives from the user id → also identical (idempotent slot)
        self.assertEqual(b1, b2)

    def test_empty_answer_skips(self):
        self.assertIsNone(v2._persist_chat_turn("u1", "q", "   "))
        self.assertEqual(self.captured, [])

    def test_no_user_skips(self):
        self.assertIsNone(v2._persist_chat_turn(None, "q", "a"))
        self.assertEqual(self.captured, [])

    def test_db_failure_returns_none(self):
        def _boom(user_id, messages):
            raise RuntimeError("db down")
        v2.db.insert_lounge_messages = _boom
        self.assertIsNone(
            v2._persist_chat_turn("u1", "q", "a", user_client_id=str(uuid.uuid4()))
        )


if __name__ == "__main__":
    unittest.main()
