"""
STORY    As someone who teaches or owns an AI model, I want to put off an
         invite and find it again, accept it, add a case I know well, give a
         spoken answer as its words, and, as the owner, archive my model,
         make it public only after its disclaimer, so
         the launchpad's actions all work from the app (N528 items 3, 5 and
         12, N563 item 4).
OUTCOME
  O1  "Not now" keeps the invite in my list, saying I put it off; accepting
      makes me a teacher of the model; the invite goes through the
      inviter's own chat link, none of its own (N598).
  O2  An example I add is kept as mine, with my answer, and counts once
      another teacher agrees; a spoken answer arrives as its transcript.
  O3  Only the owner archives or makes a model public, and public needs the
      disclaimer's confirm; another person's profile names whose it is and
      each model's id.
  O4  "Record your answer" and "Record one" turn a recording into its words
      only under my processing authorization and recording consent; without
      them nothing is transcribed, and the recording is never kept.
  O5  A person who joins a model after it went public is never sent one of
      its private examples, and cannot answer one; the teacher invited
      while it was private still is.
PROVES   O1 -> ModelActionsTest::test_not_now_keeps_the_invite_and_accept_makes_a_teacher
         O2 -> ModelActionsTest::test_an_added_example_and_a_spoken_answer
         O3 -> ModelActionsTest::test_the_owners_actions_and_the_profile
         O4 -> ModelActionsTest::test_a_recording_becomes_words_only_with_authorization
         O5 -> ModelActionsTest::test_a_private_example_never_reaches_someone_who_joins_after_public
WHY      routes/v2/learning_models.py over services/model_launchpad_store.py,
         for the screens built on #1863's routes.
"""
from __future__ import annotations

import unittest

from tests.test_model_launchpad_routes import ARTUR, KASIA, MARTA, PITCH, SPEAK, ModelRoutesTest

INVITE = "11111111-0000-4000-8000-000000000009"


class ModelActionsTest(ModelRoutesTest):
    def test_not_now_keeps_the_invite_and_accept_makes_a_teacher(self):
        self.store.tables["ai_model_invites"] = [{"id": INVITE, "model_id": SPEAK, "inviter_id": ARTUR,
                                                  "invitee_id": MARTA, "status": "open"}]
        self.assertEqual(self._post(f"/v2/models/invites/{INVITE}/not-now").get_json()["status"], "not_now")
        mine = self._get("/v2/models/invites").get_json()["invites"]
        self.assertEqual(mine[0]["lines"][-1],
                         "You said not now. The invite stays here; open it whenever you like.")
        self.who = KASIA
        self.assertEqual(self._post(f"/v2/models/invites/{INVITE}/accept").status_code, 404)
        self.who = MARTA
        self.store.tables["chat_links"] = [{"id": "l1", "user_id": ARTUR, "token": "artur-chat",
                                            "display_name": "Artur", "revoked_at": None}]
        self.assertEqual(self._get("/v2/models/invites").get_json()["invites"][0]["chat_link"], "/c/artur-chat")
        accepted = self._post(f"/v2/models/invites/{INVITE}/accept").get_json()
        self.assertEqual(accepted["chat_link"], "/c/artur-chat")      # N598: teach by using their chat
        self.assertIn((SPEAK, MARTA), {(t["model_id"], t["user_id"]) for t in self.store.tables["ai_model_teachers"]})

    def test_an_added_example_and_a_spoken_answer(self):
        self.assertEqual(self._post(f"/v2/models/{PITCH}/examples", {"text": " "}).status_code, 400)
        out = self._post(f"/v2/models/{PITCH}/examples",
                         {"transcript": "A founder rushes the ask at the end.", "step": "rate", "answer": "Rushed"})
        self.assertEqual(out.get_json()["note"], "It counts once another teacher agrees with your answer.")
        added = next(e for e in self.store.tables["ai_model_examples"] if e["id"] == out.get_json()["example_id"])
        self.assertEqual((added["source"], added["added_by"], added["content"]),
                         ("teacher", MARTA, {"text": "A founder rushes the ask at the end."}))
        mine = [a for a in self.store.tables["ai_model_answers"] if a["example_id"] == added["id"]]
        self.assertEqual([a["answer"] for a in mine], ["Rushed"])
        self.who = KASIA
        self._post(f"/v2/models/{PITCH}/examples/{added['id']}/answer",
                   {"step": "words", "transcript": "Slow down before the ask."})
        spoken = [a for a in self.store.tables["ai_model_answers"] if a["teacher_id"] == KASIA]
        self.assertEqual(spoken[0]["answer"], "Slow down before the ask.")

    def test_the_owners_actions_and_the_profile(self):
        self.assertEqual(self._post(f"/v2/models/{PITCH}/archive").status_code, 404)
        self.who = KASIA
        self.assertEqual(self._post(f"/v2/models/{PITCH}/make-public", {}).status_code, 400)
        secret = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
        self.assertEqual(self._post(f"/v2/models/{secret}/make-public", {"confirm": True}).get_json(),
                         {"visibility": "public"})
        self.who = MARTA
        section = self._get(f"/v2/models/profile/{KASIA}").get_json()["section"]
        self.assertEqual(section["user_id"], KASIA)
        self.assertIn(PITCH, [m["id"] for m in section["models"]])
        self.who = KASIA
        self.assertEqual(self._post(f"/v2/models/{PITCH}/archive").get_json(), {"status": "archived"})

    def test_a_private_example_never_reaches_someone_who_joins_after_public(self):
        secret, own = "dddddddd-dddd-4ddd-8ddd-dddddddddddd", "e5000000-0000-4000-8000-000000000009"
        t = self.store.tables
        t["ai_model_examples"].append({"id": own, "model_id": secret, "source": "upload", "private": True,
                                       "in_exam": False, "kind": "rerate", "added_by": KASIA, "speaker_id": None,
                                       "snippet_id": None, "known_answer": None,
                                       "content": {"text": "A client's own case."}})
        t["ai_model_invites"] = [{"id": INVITE, "model_id": secret, "inviter_id": KASIA,
                                  "invitee_id": ARTUR, "status": "accepted"}]
        t["ai_model_teachers"].append({"model_id": secret, "user_id": ARTUR, "role": "contributor",
                                       "trust_status": "learning", "paused_at": None, "company_line": None})
        self.who = KASIA
        self._post(f"/v2/models/{secret}/make-public", {"confirm": True})
        self.who = MARTA                                   # joins at the door, after it went public
        self.assertEqual(self._post(f"/v2/models/{secret}/enter").get_json(), {"joined": True})
        sent = self._get("/v2/models/queue").get_json()["examples"]
        self.assertNotIn(own, [e["id"] for e in sent])
        self.assertFalse(any(e.get("private") for e in sent))
        self.assertEqual(self._post(f"/v2/models/{secret}/examples/{own}/answer",
                                    {"step": "rate", "answer": "Yes"}).status_code, 404)
        self.who = ARTUR                                   # invited while it was private
        self.assertIn(own, [e["id"] for e in self._get("/v2/models/queue").get_json()["examples"]])

    def test_a_recording_becomes_words_only_with_authorization(self):
        import io
        from unittest.mock import patch

        from services.processing_authorization import ProcessingAuthorizationError
        heard = []

        class Transcriber:
            def transcribe_audio(self, audio, filename, **_):
                heard.append(audio)
                return {"text": "Slow down before the ask."}

        class Refusing:
            enforced = False

            def __init__(self, _db):
                pass

            def require_current(self, *_a, **_k):
                raise ProcessingAuthorizationError("PROCESSING_AUTHORIZATION_REQUIRED", "no", 403)

        def post():
            return self.client.post(f"/v2/models/{PITCH}/transcribe", headers={"Authorization": "Bearer t"},
                                    data={"audio": (io.BytesIO(b"OggS spoken"), "voice.webm", "audio/webm")},
                                    content_type="multipart/form-data")
        with patch("routes.v2.voice_notebook._adapter", lambda _u: Transcriber()), \
                patch("services.membership.refusal", lambda *_a: None), \
                patch("routes.v2.processing_authorization._principal_id", lambda: "principal-1"):
            with patch("services.processing_authorization.ProcessingAuthorizationService", Refusing):
                self.assertEqual(post().status_code, 403)
            self.assertEqual(heard, [])
            self.who = KASIA
            out = post()
            self.assertEqual(out.get_json(), {"transcript": "Slow down before the ask."})
            self.who = ARTUR
            self.assertEqual(post().status_code, 404)
        self.assertEqual(len(heard), 1)
        self.assertNotIn(b"OggS spoken", str(self.store.tables).encode())


del ModelRoutesTest

if __name__ == "__main__":
    unittest.main()
