"""BE-owned Lounge persistence for /v2/chat/query (#2 — bubbles must never
disappear). The route's contract test, plus the few helper tests the route
cannot show (stubbed db, no network).

Run: python3 -m unittest tests.test_chat_persist
"""
from __future__ import annotations

import unittest
import uuid
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

try:
    from routes.v2 import coaching as v2_coaching
    from services.db import db
    from routes.v2.coaching import _parse_chat_request
    _RT_ERR = None
except Exception as e:  # pragma: no cover
    _RT_ERR = e


USER = "9f4e75b8-268b-468d-9111-000000000077"
CHIP = {"intent": "library_recall", "answer": "Tap the button below.",
        "show_record_ui": False, "suggested_action": "trainings"}
CHOICE = {"intent": "replace_pre_take_deck",
          "answer": "Choose what happens next.",
          "suggested_actions": ["replace_pdf", "create_new_project"]}


@unittest.skipIf(_RT_ERR is not None, f"needs app deps: {_RT_ERR}")
class ChatRoutePersistsTheTurnTests(unittest.TestCase):
    """POST /v2/chat/query: a signed-in turn that opts in is written once,
    user row and bot row, with the bot's choices in its metadata so they
    come back on reload (founder #2 — bubbles must never disappear). The
    route's one contract test; the answer itself comes from a deterministic
    intercept, so no model is called."""

    def setUp(self):
        import auth
        from flask import Flask
        from routes.v2 import register_domains
        from routes.v2.blueprint import v2_bp
        from services.rate_limits import limiter

        # Every /v2 route must be attached before the shared blueprint is
        # registered: Flask refuses route additions after that.
        register_domains()

        if hasattr(limiter, "initialized"):
            self.addCleanup(setattr, limiter, "initialized", limiter.initialized)
            limiter.initialized = False
        app = Flask(__name__)
        app.register_blueprint(v2_bp, url_prefix="/v2")
        self.client = app.test_client()

        self.rows = []
        self.contexts = []
        self.histories = []

        def _insert(user_id, messages):
            if self.fail_db:
                raise RuntimeError("db down")
            self.rows.append((user_id, messages))
            return messages

        def _answer(question, history=None, **_kw):
            self.histories.append(history)
            return {"answer": "It's a voice coach."}, {"intent": "faq"}

        def _presentation(question, context=None):
            self.contexts.append(context)
            return CHOICE if "deck" in question else None

        self.fail_db = False
        self._patches = [
            patch.object(auth, "verify_supabase_token",
                         lambda token: {"sub": USER}),
            patch.object(db, "insert_lounge_messages", _insert),
            patch("services.goal_update.handle_goal_update",
                  lambda user_id, question: None),
            patch("services.presentation_change_intent."
                  "handle_presentation_change", _presentation),
            patch("services.chat_intents.detect_chat_intent",
                  lambda question: (
                      CHIP if "trainings" in question
                      else {**CHIP, "answer": "   "} if "blank" in question
                      else None)),
            patch("services.master_doc_rag.answer_question", _answer),
            patch.object(db, "get_user_settings", lambda user_id: {}),
            patch("services.token_account.charge", lambda *a, **k: None),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def post(self, body=None, *, signed_in=True, data=None):
        headers = {"Authorization": "Bearer t"} if signed_in else {}
        if data is not None:
            return self.client.post("/v2/chat/query", data=data,
                                    headers=headers,
                                    content_type="multipart/form-data")
        return self.client.post("/v2/chat/query", json=body, headers=headers)

    def test_a_signed_in_turn_is_written_once_with_its_choices(self):
        cid = str(uuid.uuid4())
        turn = {"question": "show my trainings", "persist": True,
                "client_id": cid, "client_created_at": "2026-06-22T10:00:00Z",
                "presentation_context": {"project_id": "p1"}}
        resp = self.post(turn)
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        user_id, (user_row, bot_row) = self.rows[0]
        self.assertEqual(user_id, USER)
        self.assertEqual(
            (user_row["role"], user_row["kind"], user_row["body"],
             user_row["client_id"], user_row["client_created_at"]),
            ("user", "text", "show my trainings", cid, "2026-06-22T10:00:00Z"))
        self.assertEqual(
            (bot_row["role"], bot_row["kind"], bot_row["body"]),
            ("bot", "text", "Tap the button below."))
        # The chip and the bubbles ride the bot row, so they rehydrate.
        self.assertEqual(bot_row["metadata"], {
            "intent": "library_recall", "suggested_action": "trainings",
            "bubbles": ["Tap the button below."]})
        self.assertTrue(body["persisted"])
        self.assertEqual(body["persisted_client_id"], bot_row["client_id"])
        self.assertEqual(self.contexts[-1], {"project_id": "p1"})

        # Re-posting the same turn lands on the same two rows (idempotent).
        self.post(turn)
        self.assertEqual([r["client_id"] for r in self.rows[1][1]],
                         [cid, bot_row["client_id"]])

        # Without a usable FE id the ids derive from (user, question), so a
        # retry is still one slot; a deliberate choice pair rides too.
        for _ in range(2):
            self.post({"question": "replace my deck", "persist": True,
                       "client_id": "not-a-uuid"})
        first, second = self.rows[2][1], self.rows[3][1]
        self.assertEqual([r["client_id"] for r in first],
                         [r["client_id"] for r in second])
        self.assertNotEqual(first[0]["client_id"], "not-a-uuid")
        self.assertEqual(first[1]["metadata"]["suggested_actions"],
                         ["replace_pdf", "create_new_project"])

    def test_nothing_is_written_unless_a_signed_in_caller_opts_in(self):
        self.assertEqual(self.post({"question": "show my trainings"})
                         .status_code, 200)
        self.post({"question": "show my trainings", "persist": True},
                  signed_in=False)
        self.assertEqual(self.rows, [])
        self.assertEqual(self.post({"question": "  ", "persist": True})
                         .status_code, 400)
        blank = self.post({"question": "blank", "persist": True})
        self.assertFalse(blank.get_json()["persisted"])
        self.assertEqual(self.rows, [])

    def test_a_failed_write_never_fails_the_answer(self):
        self.fail_db = True
        resp = self.post({"question": "show my trainings", "persist": True})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["answer"], "Tap the button below.")
        self.assertFalse(resp.get_json()["persisted"])

    def test_both_transports_carry_the_same_turn_to_the_answer(self):
        self.post(data={"question": "  show my trainings  ", "persist": "yes",
                        "presentation_context": '{"take_count":1}'})
        user_row, _bot_row = self.rows[0][1]
        self.assertEqual(user_row["body"], "show my trainings")
        self.assertEqual(self.contexts[-1], {"take_count": 1})
        # History reaches the answer only as a list, from either transport.
        self.post({"question": "what is this?", "history": "not-a-list"})
        self.post(data={"question": "what is this?",
                        "history": '[{"role":"user","content":"hi"}]'})
        self.assertEqual(self.histories,
                         [None, [{"role": "user", "content": "hi"}]])


@unittest.skipIf(_RT_ERR is not None, f"needs app deps: {_RT_ERR}")
class ProductActionMetadataTests(unittest.TestCase):
    """Kept as helper tests: no path of /v2/chat/query sets `product_action`
    today, so the route cannot show this validation. If a path starts to,
    move these into the route test."""

    def setUp(self):
        self.captured = []
        patcher = patch.object(
            db, "insert_lounge_messages",
            lambda user_id, messages: self.captured.append(messages))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_structured_product_action_rides_in_bot_metadata(self):
        action = {
            "action": "open_product",
            "product": "life_panel",
            "intent": "start_setup",
            "source": "voice_album_completion",
            "context_transfer": "none",
            "schema_version": 1,
        }
        v2_coaching._persist_chat_turn(
            "u1", "what next?", "Your next step is ready.",
            product_action=action, user_client_id=str(uuid.uuid4()),
        )
        self.assertEqual(self.captured[0][-1]["metadata"]["product_action"],
                         action)

    def test_invalid_product_action_is_not_persisted(self):
        v2_coaching._persist_chat_turn(
            "u1", "what next?", "Your next step is ready.",
            product_action={
                "action": "open_product",
                "product": "life_panel",
                "intent": "start_setup",
                "source": "voice_album_completion",
                "context_transfer": "chat",
                "schema_version": 1,
            },
            user_client_id=str(uuid.uuid4()),
        )
        self.assertNotIn("product_action", self.captured[0][-1]["metadata"])


@unittest.skipIf(_RT_ERR is not None, f"needs app deps: {_RT_ERR}")
class ParseChatRequestTests(unittest.TestCase):
    def test_multipart_transport_preserves_audio_and_context(self):
        req = SimpleNamespace(
            content_type="multipart/form-data; boundary=test",
            form={
                "question": "  rehearse this  ",
                "history": '[{"role":"user","content":"hi"}]',
                "persist": "yes",
                "client_id": "client-1",
                "client_created_at": "created-at",
                "presentation_context": '{"take_count":1}',
                "transcript_source": "server_whisper",
                "audio_duration_sec": "2.5",
            },
            files={"audio_file": BytesIO(b"voice")},
            user_id="u1",
        )

        parsed = _parse_chat_request(req)

        self.assertEqual(parsed["question"], "rehearse this")
        self.assertEqual(len(parsed["history"]), 1)
        self.assertEqual(parsed["presentation_context"], {"take_count": 1})
        # Chat transport is text-only. Voice bytes must enter through the
        # recording boundary where exact audio lineage is established.
        self.assertNotIn("audio_bytes", parsed)
        self.assertNotIn("transcript_source", parsed)
        self.assertNotIn("audio_duration_sec", parsed)
        self.assertTrue(parsed["persist_thread"])


if __name__ == "__main__":
    unittest.main()
