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
            return {"answer": "It's a voice coach.",
                    "app_action": self.app_action}, dict(self.debug)

        def _presentation(question, context=None):
            self.contexts.append(context)
            return CHOICE if "deck" in question else None

        self.fail_db = False
        self.app_action = None
        self.thread = []
        self.debug = {"intent": "faq"}
        self.card = {"whatsapp_on": False}
        self._patches = [
            patch.object(auth, "verify_supabase_token",
                         lambda token: {"sub": USER}),
            patch.object(db, "insert_lounge_messages", _insert),
            patch("services.goal_update.handle_goal_update",
                  lambda user_id, question: None),
            patch("services.presentation_change_intent."
                  "handle_presentation_change", _presentation),
            patch("services.chat_intents.detect_chat_intent",
                  lambda question, history=None: (
                      CHIP if "trainings" in question
                      else {**CHIP, "answer": "   "} if "blank" in question
                      else None)),
            patch("services.master_doc_rag.answer_question", _answer),
            patch("services.chat_app_context.status_card",
                  lambda database, user_id: self.card),
            patch.object(db, "get_user_settings", lambda user_id: {}),
            patch.object(db, "get_lounge_messages_page",
                         lambda user_id, limit, before=None: list(self.thread)),
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

    def test_a_visitor_gets_two_answers_then_the_signup_line(self):
        """Founder 2026-10-14: the chat costs money, so a visitor who is not
        signed in gets two answers; the third turn asks them to sign up,
        without a model call."""
        from services.chat_app_context import SIGNUP_LINE
        two_asked = [{"role": "user", "content": "what is this?"},
                     {"role": "assistant", "content": "A voice coach."},
                     {"role": "user", "content": "how much?"},
                     {"role": "assistant", "content": "See the plans."}]
        second = self.post({"question": "how much?", "history": two_asked[:2]},
                           signed_in=False).get_json()
        self.assertEqual(second["answer"], "It's a voice coach.")
        third = self.post({"question": "and then?", "history": two_asked},
                          signed_in=False).get_json()
        self.assertEqual(third["answer"], SIGNUP_LINE)
        self.assertEqual(len(self.histories), 1)

    def test_the_whatsapp_form_opens_to_add_or_change_a_number(self):
        """Founder 2026-10-14/15: a speaker who names WhatsApp gets the form
        the Lounge already draws, whatever the model chose. With a number
        saved, "Is it saved?" gets an answer and no form; the form comes
        back only to change the number."""
        self.app_action = "whatsapp"
        body = self.post({"question": "can I get alerts on my phone?",
                          "persist": True}).get_json()
        self.assertEqual(body["offer"], "whatsapp")
        self.assertEqual(self.rows[-1][1][-1]["metadata"], {"offer": "whatsapp"})
        self.card = {"whatsapp_on": True}
        body = self.post({"question": "is my WhatsApp saved?", "persist": True}).get_json()
        self.assertNotIn("offer", body)
        self.app_action = None
        body = self.post({"question": "change my WhatsApp number",
                          "persist": True}).get_json()
        self.assertEqual(body["offer"], "whatsapp")

    def test_a_feature_with_a_page_comes_with_its_link(self):
        self.app_action = "booking"
        body = self.post({"question": "can I book a lesson?"}).get_json()
        self.assertTrue(body["answer"].endswith(
            "https://www.willpowerlab.com/book/artur"))
        self.assertIn("https://www.willpowerlab.com/book/artur",
                      body["bubbles"])

    def test_what_a_speaker_tells_will_is_not_marked_for_anyone(self):
        """Founder 2026-10-15: the chat is as private as any other AI chat.
        Feedback about the app is answered and kept in the thread like any
        turn, with nothing that sets it aside for a person to read."""
        self.debug = {"router_intent": "speaker_feedback"}
        self.post({"question": "The walk was too long for me", "persist": True})
        user_row, bot_row = self.rows[-1][1]
        self.assertIsNone(user_row["metadata"])
        self.assertNotEqual(bot_row["metadata"].get("intent"), "speaker_feedback")

    def test_will_reads_the_summary_he_wrote_after_the_take(self):
        """Founder 2026-10-15: "it does not hold the context". A signed-in
        speaker's reply to the summary after a Take reaches Will with that
        summary, read from their own thread; the turn being asked is not
        repeated."""
        self.thread = [  # newest first, as the database returns it
            {"client_id": "now", "role": "user", "kind": "text", "body": "great, yes!"},
            {"client_id": "s", "role": "bot", "kind": "cadence",
             "body": "Churn in Q3, nailed it! How did it go?", "metadata": {"summary": True}},
            {"client_id": "c", "role": "bot", "kind": "transcript_ready", "body": "card"},
            {"client_id": "e", "role": "user", "kind": "text", "body": "hi Will"},
        ]
        self.post({"question": "great, yes!", "persist": True, "client_id": "now"})
        self.assertEqual(self.histories[-1], [
            {"role": "user", "content": "hi Will"},
            {"role": "assistant", "content": "Churn in Q3, nailed it! How did it go?"}])


if __name__ == "__main__":
    unittest.main()
