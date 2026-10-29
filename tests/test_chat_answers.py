"""
STORY    As a speaker talking to Will in the Lounge, I want answers that use
         what I already told him and take me straight to the right form or
         page, and a chat as private as any other AI chat, so that the chat
         helps me get to my next Take.
OUTCOME
  O1  JSON and form posts carry the same turn (trimmed question, deck
      context, history only as a list) to the answer.
  O2  A visitor who is not signed in gets two answers, then the sign-up
      line without a model call.
  O3  Naming WhatsApp or a phone number opens the number form; with a
      number saved, asking whether it is saved does not.
  O4  A feature with a page (booking) comes with its link.
  O5  Feedback about the app is kept like any turn, with nothing marking it
      for a person to read.
  O6  A reply to the summary after a Take reaches Will with that summary,
      read from the speaker's own thread; the signed fallback is marked as
      the fixed message, so Will knows the specifics are missing.
  O7  When the app sends what is on my screen, Will reads my bubbles in
      the order I see them, cards included, not the stored thread.
  O8  A number I type under the WhatsApp ask opens the form on its code and
      is not saved until the code is typed (N235); one without its country
      code gets the form's own words and the form, and the ask is not asked
      twice.
PROVES   O1 -> test_both_transports_carry_the_same_turn_to_the_answer
         O2 -> test_a_visitor_gets_two_answers_then_the_signup_line
         O3 -> test_the_whatsapp_form_opens_to_add_or_change_a_number
         O4 -> test_a_feature_with_a_page_comes_with_its_link
         O5 -> test_what_a_speaker_tells_will_is_not_marked_for_anyone
         O6 -> test_will_reads_the_summary_he_wrote_after_the_take
         O7 -> test_will_reads_the_screen_in_the_order_it_is_drawn
         O8 -> test_a_number_typed_under_the_whatsapp_ask_answers_it
WHY      Founder 2026-10-14 to 2026-10-18 (cost, WhatsApp, privacy, context);
         2026-10-20 ("the chat should be aware of the order of bubbles it
         displays").
         Split out of test_chat_persist.py; the harness is
         tests/chat_route_fakes.py.
"""
from __future__ import annotations

from unittest.mock import patch

from tests.chat_route_fakes import ChatRouteHarness
from tests.fakes import FakeSupabaseClient

BOOKING = "https://www.willpowerlab.com/book/artur"


class ChatAnswersTests(ChatRouteHarness):
    __test__ = True

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
        body = self.post({"question": "where do I enter my telephone number?",
                          "persist": True}).get_json()
        self.assertEqual(body["offer"], "whatsapp")
        self.card = {"whatsapp_on": False}
        body = self.post({"question": "add my phone number",
                          "persist": True}).get_json()
        self.assertEqual(body["offer"], "whatsapp")

    def test_a_feature_with_a_page_comes_with_its_link(self):
        self.app_action = "booking"
        body = self.post({"question": "can I book a lesson?"}).get_json()
        self.assertTrue(body["answer"].endswith(BOOKING))
        self.assertIn(BOOKING, body["bubbles"])

    def test_what_a_speaker_tells_will_is_not_marked_for_anyone(self):
        self.debug = {"router_intent": "speaker_feedback"}
        self.post({"question": "The walk was too long for me", "persist": True})
        user_row, bot_row = self.rows[-1][1]
        self.assertEqual(bot_row["body"], "It's a voice coach.")
        self.assertIsNone(user_row["metadata"])
        self.assertNotEqual(bot_row["metadata"].get("intent"), "speaker_feedback")

    def test_will_reads_the_summary_he_wrote_after_the_take(self):
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
        self.thread[1] = {**self.thread[1], "body": "Your second take is in 🎉",
                          "metadata": {"summary": True, "written": False, "take_index": 2}}
        self.post({"question": "great, yes!", "persist": True, "client_id": "now"})
        self.assertEqual(self.histories[-1][-1]["content"],
                         "[The app's fixed message after Take 2; the written summary failed]\n"
                         "Your second take is in 🎉")

    def test_will_reads_the_screen_in_the_order_it_is_drawn(self):
        self.thread = [{"client_id": "x", "role": "bot", "kind": "text",
                        "body": "stored, not shown"}]
        screen = [
            {"role": "assistant", "content": "[Ideal Text card: \"ted\", 1.0]"},
            {"role": "assistant", "content": "We have successfully registered your first take"},
            {"role": "assistant", "content": "Want a WhatsApp message when your coach's "
                                             "feedback is in? Add your phone number."},
            {"role": "system", "content": "dropped"},
        ]
        self.post({"question": "what now?", "persist": True, "history": screen,
                   "history_source": "screen"})
        self.assertEqual(self.histories[-1], screen[:3])

    def test_a_number_typed_under_the_whatsapp_ask_answers_it(self):
        from services.chat_app_context import OFFER_PROMPTS
        from services.db import db
        from services.whatsapp_notify import CHECK
        supabase = FakeSupabaseClient()
        p = patch.object(db, "client", supabase)
        p.start()
        self.addCleanup(p.stop)
        self.thread = [  # newest first: the walk went on under the ask
            {"client_id": "h", "role": "bot", "kind": "walk_step",
             "body": "Choose your helper words", "metadata": {"step": "helpers"}},
            {"client_id": "w", "role": "bot", "kind": "text",
             "body": OFFER_PROMPTS["whatsapp"], "metadata": {"offer": "whatsapp"}},
        ]
        bare = self.post({"question": "07700 900461", "persist": True}).get_json()
        self.assertEqual(bare["answer"],
                         "Enter the number with its country code, for example +44 7700 900123.")
        self.assertEqual(bare["offer"], "whatsapp")  # the form opens
        self.assertEqual([r["role"] for r in self.rows[-1][1]], ["user", "bot"])
        self.assertNotIn("user_settings", supabase.tables)
        full = self.post({"question": "+44 7700 900123", "persist": True}).get_json()
        self.assertEqual(full["answer"], CHECK)
        self.assertEqual(full["offer"], "whatsapp")  # the form, on the code step
        self.assertEqual(full["row_metadata"], {"whatsapp": "check", "phone": "+447700900123"})
        self.assertNotIn("user_settings", supabase.tables)  # nothing saved before the code
        self.assertEqual(self.histories, [])  # no model call for either
