"""The /v2/chat/query harness shared by test_chat_persist.py and
test_chat_answers.py: the real blueprint and route, with the model answer,
the intent detectors, the status card, the token charge and the Lounge
table replaced by in-memory fakes (no network, no model call).

`rows` collects every write to the Lounge table; `thread` is what a read of
it returns (newest first, as the database does); set `fail_db` to make every
write raise."""
from __future__ import annotations

import unittest
from unittest.mock import patch

USER = "9f4e75b8-268b-468d-9111-000000000077"
CHIP = {"intent": "library_recall", "answer": "Tap the button below.",
        "show_record_ui": False, "suggested_action": "trainings"}
CHOICE = {"intent": "update_slides",
          "answer": "You can update the slides in this project. "
                    "Your next Take uses them.",
          "suggested_actions": ["update_slides"]}


class ChatRouteHarness(unittest.TestCase):
    __test__ = False

    def setUp(self):
        from flask import Flask

        import auth
        from routes.v2 import register_domains
        from routes.v2.blueprint import v2_bp
        from services.db import db
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

        self.rows, self.contexts, self.histories, self.thread = [], [], [], []
        self.fail_db = False
        self.app_action = None
        self.debug = {"intent": "faq"}
        self.card = {"whatsapp_on": False}

        def _insert(user_id, messages):
            if self.fail_db:
                raise RuntimeError("db down")
            self.rows.append((user_id, messages))
            return messages

        def _answer(question, history=None, **_kw):
            self.histories.append(history)
            return {"answer": "It's a voice coach.",
                    "app_action": self.app_action}, dict(self.debug)

        def _presentation(question, context=None):
            self.contexts.append(context)
            return CHOICE if "deck" in question else None

        patches = [
            patch.object(auth, "verify_supabase_token", lambda token: {"sub": USER}),
            patch.object(db, "insert_lounge_messages", _insert),
            patch("services.goal_update.handle_goal_update",
                  lambda user_id, question: None),
            patch("services.presentation_change_intent.handle_presentation_change",
                  _presentation),
            patch("services.chat_intents.detect_chat_intent",
                  lambda question, history=None: (
                      CHIP if "trainings" in question else None)),
            patch("services.master_doc_rag.answer_question", _answer),
            patch("services.chat_app_context.status_card",
                  lambda database, user_id: self.card),
            patch.object(db, "get_user_settings", lambda user_id: {}),
            patch.object(db, "get_lounge_messages_page",
                         lambda user_id, limit, before=None: list(self.thread)),
            patch("services.token_account.charge", lambda *a, **k: None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def post(self, body=None, *, signed_in=True, data=None):
        headers = {"Authorization": "Bearer t"} if signed_in else {}
        if data is not None:
            return self.client.post("/v2/chat/query", data=data, headers=headers,
                                    content_type="multipart/form-data")
        return self.client.post("/v2/chat/query", json=body, headers=headers)
