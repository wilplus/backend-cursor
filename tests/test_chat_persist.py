"""BE-owned Lounge persistence for /v2/chat/query (#2 — bubbles must never
disappear). The route's contract test, plus the few helper tests the route
cannot show (stubbed db, no network).

Run: python3 -m unittest tests.test_chat_persist
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from services.db import db
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
        from flask import Flask

        import auth
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


if __name__ == "__main__":
    unittest.main()
