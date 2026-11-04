"""
STORY    As a speaker, after my Take, I want the page that chose who hears it
         to come back once with someone new who fits what I asked, so that
         the right person can answer; and as that person, I want to hear the
         Take before anyone knows who I am, so that answering is my yes
         (founder, 4 November 2026, N477, N478).
OUTCOME
  O1  With no ring row, nobody is ever suggested: the speaker's routes
      answer 404.
  O2  After a Take, one person is suggested: someone who shares a community
      with the speaker, has no chat with them, and fits what the Take is
      about; shown as a pseudonym and a description, never a name. Asking
      again gives the same one; someone who fits nothing is never chosen.
  O3  Someone already in a chat with the speaker, or still waiting to be
      let in (N471), is never suggested, and nobody is suggested to the
      same speaker twice.
  O4  Send puts Will's card in the suggested person's chat with Will,
      under the speaker's pseudonym; it makes no chat, and the page does
      not come back.
  O5  Not now tells nobody: no card, no chat.
  O6  The one suggested opens the Take (what it is about, its words slide
      by slide) and answers; only then is the chat between the two made,
      with the speaker's Take and the answer in it, under their names.
  O7  Nobody else can open or answer it, and the one suggested cannot
      before it was sent.
PROVES   O1 -> TakeMatchTest::test_with_no_ring_nobody_is_suggested
         O2 -> TakeMatchTest::test_one_new_person_who_fits_is_suggested_as_a_pseudonym
         O3 -> TakeMatchTest::test_nobody_in_a_chat_waiting_or_suggested_before
         O4 -> TakeMatchTest::test_send_reaches_only_the_one_suggested_through_will
         O5 -> TakeMatchTest::test_not_now_tells_nobody
         O6 -> TakeMatchTest::test_the_answer_opens_the_chat_for_both
         O7 -> TakeMatchTest::test_only_the_one_suggested_opens_it_once_sent
WHY      Matching people happens in one place only, after the Take (N477);
         anonymous until the answer, which alone opens the chats (N478).
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from services.db import db
from services.processing_authorization import ProcessingAuthorizationService
from services.project_repository import ProjectRepository
from tests.test_chats import _Store

AMIRA = "11111111-1111-4111-8111-111111111111"
LEA = "22222222-2222-4222-8222-222222222222"
TOMEK = "33333333-3333-4333-8333-333333333333"
TAKE = "44444444-4444-4444-8444-444444444444"
ANSWER = "55555555-5555-4555-8555-555555555555"
TEAM = "66666666-6666-4666-8666-666666666666"
NAMES = {AMIRA: "Amira Haddad", LEA: "Lea Brandt", TOMEK: "Tomek Nowak"}


class TakeMatchTest(unittest.TestCase):
    def setUp(self):
        from flask import Flask

        import auth
        from routes.v2 import register_domains
        from routes.v2.blueprint import v2_bp
        from services.rate_limits import limiter
        from services.canonical_product import OwnerPrincipal

        register_domains()
        if hasattr(limiter, "initialized"):
            self.addCleanup(setattr, limiter, "initialized", limiter.initialized)
            limiter.initialized = False
        app = Flask(__name__)
        app.register_blueprint(v2_bp, url_prefix="/v2")
        self.client = app.test_client()
        self.store = _Store()
        self.who = AMIRA
        self.ring = True
        self.cards: list = []

        def payload(_token):
            return {"sub": self.who, "user_metadata": {"full_name": NAMES[self.who]}}

        for p in (patch.object(auth, "verify_supabase_token", payload),
                  patch.object(db, "client", self.store),
                  patch.object(db, "insert_lounge_messages",
                               lambda user, rows: self.cards.extend((user, r) for r in rows)),
                  patch("services.rings.feature_is_on_for_user",
                        lambda feature, user, **_: self.ring and feature == "take_match"),
                  patch.dict(os.environ, {"PLF1_PROCESSING_AUTHORIZATION_MODE": "off"}),
                  patch.object(ProjectRepository, "owner_for_user",
                               lambda _repo, user: OwnerPrincipal(f"owner-{user}", user, False)),
                  patch.object(ProcessingAuthorizationService, "resolve_acquisition_principal",
                               lambda _service, owner, **_: owner),
                  patch.object(ProcessingAuthorizationService, "consent_choices",
                               lambda _service, _principal: {
                                   "has_receipt": True, "personalised_practice": True,
                                   "sensitive_information": True}),
                  patch.object(ProcessingAuthorizationService, "status",
                               lambda _service, _principal: {
                                   "authorized": True, "pooled_learning_eligible": False})):
            p.start()
            self.addCleanup(p.stop)
        t = self.store.tables
        t["community_members"] = [{"community_id": TEAM, "user_id": u} for u in (AMIRA, LEA, TOMEK)]
        t["people_profiles"] = [
            {"user_id": AMIRA, "name": None, "role": "Account executive",
             "about": "I sell software to banks."},
            {"user_id": LEA, "name": None, "role": "Speaking coach",
             "about": "I help founders open an investor pitch with numbers that stick."},
            {"user_id": TOMEK, "name": None, "role": "Accountant", "about": "Tax returns."}]
        t["v2_sessions"] = [
            {"id": TAKE, "user_id": AMIRA, "created_at": "2026-11-04T10:00:00Z",
             "intake_context": {"topic": "investor pitch"},
             "slide_transcripts": [
                 {"index": 0, "transcript": "Our investor pitch opens with the numbers.",
                  "start_offset_ms": 0},
                 {"index": 1, "transcript": "The numbers that stick are revenue and growth.",
                  "start_offset_ms": 41000}]},
            {"id": ANSWER, "user_id": LEA, "created_at": "2026-11-04T11:00:00Z",
             "intake_context": {}, "slide_transcripts": []}]
        t["recordings"] = [
            {"session_v2_id": TAKE, "user_id": AMIRA, "storage_path": "a/take.webm", "duration": 130},
            {"session_v2_id": ANSWER, "user_id": LEA, "storage_path": "l/answer.webm", "duration": 40}]

    def _as(self, who):
        self.who = who

    def _get(self, path):
        return self.client.get(path, headers={"Authorization": "Bearer t"})

    def _post(self, path, body=None):
        return self.client.post(path, json=body or {}, headers={"Authorization": "Bearer t"})

    def _suggested(self):
        response = self._get(f"/v2/takes/{TAKE}/match")
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["match"]

    def test_with_no_ring_nobody_is_suggested(self):
        self.ring = False
        self.assertEqual(self._get(f"/v2/takes/{TAKE}/match").status_code, 404)
        self.assertEqual(self.store.count("take_matches"), 0)

    def test_one_new_person_who_fits_is_suggested_as_a_pseudonym(self):
        match = self._suggested()
        self.assertEqual(match["role"], "Speaking coach")
        self.assertNotIn("Lea", str(match))
        self.assertTrue(match["pseudonym"])
        row = self.store.tables["take_matches"][0]
        self.assertEqual((row["candidate_id"], row["status"], row["arm"]),
                         (LEA, "offered", "topics"))
        self.assertEqual(self._suggested()["id"], match["id"])
        self.assertEqual(self.store.count("take_matches"), 1)

    def test_nobody_in_a_chat_waiting_or_suggested_before(self):
        self.store.tables["chat_members"] = [{"id": "m1", "thread_id": "t1", "user_id": AMIRA},
                                             {"id": "m2", "thread_id": "t1", "user_id": LEA}]
        self.assertIsNone(self._suggested())
        self.store.tables["chat_members"] = []
        with patch("services.membership.is_member", lambda _db, user, **_: user != LEA):
            self.assertIsNone(self._suggested())
        self.store.tables["take_matches"] = [{"id": "x", "session_id": "older", "speaker_id": AMIRA,
                                              "candidate_id": LEA, "status": "closed"}]
        self.assertIsNone(self._suggested())

    def test_send_reaches_only_the_one_suggested_through_will(self):
        match = self._suggested()
        response = self._post(f"/v2/take-matches/{match['id']}/send")
        self.assertEqual(response.get_json()["match"]["status"], "sent")
        self.assertEqual(len(self.cards), 1)
        to, card = self.cards[0]
        self.assertEqual(to, LEA)
        self.assertNotIn("Amira", str(card))
        self.assertIn("might benefit from your knowledge immensely", card["body"])
        self.assertEqual(card["metadata"]["about"], "investor pitch")
        self.assertEqual(self.store.count("chat_threads"), 0)
        self.assertIsNone(self._suggested())

    def test_not_now_tells_nobody(self):
        match = self._suggested()
        self.assertEqual(self._post(f"/v2/take-matches/{match['id']}/close").status_code, 200)
        self.assertEqual(self.cards, [])
        self.assertEqual(self.store.tables["take_matches"][0]["status"], "closed")
        self.assertEqual(self.store.count("chat_threads"), 0)

    def test_the_answer_opens_the_chat_for_both(self):
        match = self._suggested()
        self._post(f"/v2/take-matches/{match['id']}/send")
        self._as(LEA)
        opened = self._get(f"/v2/take-matches/{match['id']}").get_json()["match"]
        self.assertEqual(opened["about"], "investor pitch")
        self.assertIn("revenue and growth", opened["words"])
        self.assertEqual(opened["slides"], [0, 41000])
        self.assertNotIn("Amira", str(opened))
        self.assertEqual(self.store.count("chat_threads"), 0)
        made = self._post(f"/v2/take-matches/{match['id']}/answer", {"take": ANSWER})
        self.assertEqual(made.status_code, 200, made.get_json())
        thread = made.get_json()["chat"]["id"]
        members = {m["user_id"]: m["display_name"] for m in self.store.tables["chat_members"]}
        self.assertEqual(members, {AMIRA: "Amira", LEA: "Lea"})
        messages = self.store.tables["chat_messages"]
        authors = {m["id"]: m["user_id"] for m in self.store.tables["chat_members"]}
        self.assertEqual([(authors[m["author_member_id"]], m["meta"]["take"]) for m in messages],
                         [(AMIRA, TAKE), (LEA, ANSWER)])
        self._as(AMIRA)
        chats = self._get("/v2/chats").get_json()["chats"]
        self.assertEqual([c["id"] for c in chats], [thread])
        self.assertEqual(self.store.tables["take_matches"][0]["status"], "answered")

    def test_only_the_one_suggested_opens_it_once_sent(self):
        match = self._suggested()
        self._as(LEA)
        self.assertEqual(self._get(f"/v2/take-matches/{match['id']}").status_code, 404)
        self._as(AMIRA)
        self._post(f"/v2/take-matches/{match['id']}/send")
        self._as(TOMEK)
        self.assertEqual(self._get(f"/v2/take-matches/{match['id']}").status_code, 404)
        self.assertEqual(self._post(f"/v2/take-matches/{match['id']}/answer",
                                    {"take": ANSWER}).status_code, 404)
        self.assertEqual(self.store.count("chat_threads"), 0)


if __name__ == "__main__":
    unittest.main()
