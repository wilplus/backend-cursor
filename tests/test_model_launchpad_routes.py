"""
STORY    As a person in WillpowerLab, I want the AI models' list, a model's
         page, the door, the one queue and teaching to answer from the
         models' tables through /v2/models, so the launchpad's rules reach me
         as they are written (N528, N563, N566).
OUTCOME
  O1  Without the ring row (ai_models, ring 6) every route is 404.
  O2  The list shows public models with how far each is, and never another
      person's private model; its page is 404 to an outsider.
  O3  "This is my field" makes me a teacher; the queue then holds the
      model's examples without the machine's read, and Pause empties it.
  O4  One answer to a public clip is saved for both models that ask the
      same question, and the other model's different question follows; the
      answer returns nothing of the machine's read.
  O5  The profile lists the models a person started and teaches; an invite
      I put off says so and stays.
PROVES   O1 -> ModelRoutesTest::test_without_the_ring_nothing_is_shown
         O2 -> ModelRoutesTest::test_the_list_and_a_private_page
         O3 -> ModelRoutesTest::test_the_door_the_queue_and_pause
         O4 -> ModelRoutesTest::test_one_answer_counts_for_both_and_the_other_question_follows
         O5 -> ModelRoutesTest::test_the_profile_and_the_invite
WHY      The model launchpad's first tables (migration
         a_person_can_teach_and_start_ai_models), served by
         services/model_launchpad_store.py over services/model_launchpad.py.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.db import db
from tests.test_chats import _Store

ARTUR = "11111111-1111-4111-8111-111111111111"
MARTA = "22222222-2222-4222-8222-222222222222"
KASIA = "33333333-3333-4333-8333-333333333333"
SPEAK = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
INTERVIEW = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
PITCH = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
JUDGE = {"input": "voice", "steps": ["rate"], "question": "Does the speaker sound confident here?",
         "scale": ["Yes", "In-between", "No"]}
ES, EI, EP = ("e5000000-0000-4000-8000-000000000001", "e5000000-0000-4000-8000-000000000002",
              "e5000000-0000-4000-8000-000000000003")
RUSHED = {"input": "voice", "steps": ["rate"], "question": "How rushed does it sound?",
          "scale": ["Calm", "Mostly calm", "Hurried in places", "Rushed", "Racing"]}


class ModelRoutesTest(unittest.TestCase):
    def setUp(self):
        from flask import Flask

        import auth
        from routes.v2 import register_domains
        from routes.v2.blueprint import v2_bp
        from services.rate_limits import limiter

        register_domains()
        if hasattr(limiter, "initialized"):
            self.addCleanup(setattr, limiter, "initialized", limiter.initialized)
            limiter.initialized = False
        app = Flask(__name__)
        app.register_blueprint(v2_bp, url_prefix="/v2")
        self.client = app.test_client()
        self.store = _Store()
        self.who = MARTA
        self.ring = True
        for p in (patch.object(auth, "verify_supabase_token", lambda _t: {"sub": self.who}),
                  patch.object(db, "client", self.store),
                  patch("services.rings.feature_is_on_for_user", lambda *_a, **_k: self.ring)):
            p.start()
            self.addCleanup(p.stop)
        t = self.store.tables
        t["ai_models"] = [
            {"id": SPEAK, "name": "Speaking confidence", "owner_id": ARTUR, "owner_name": "Artur",
             "visibility": "public", "status": "learning", "field": "speaking", "description": "",
             "draft_step": None, "recipe": JUDGE, "targets": {"counted_answers": 10, "exam_cases": 2}},
            {"id": INTERVIEW, "name": "Interview voice", "owner_id": KASIA, "owner_name": "Kasia",
             "visibility": "public", "status": "learning", "field": "", "description": "",
             "draft_step": None, "recipe": JUDGE, "targets": {}},
            {"id": PITCH, "name": "Pitch Coach", "owner_id": KASIA, "owner_name": "Kasia",
             "visibility": "public", "status": "learning", "field": "", "description": "",
             "draft_step": None, "recipe": RUSHED, "targets": {}},
            {"id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd", "name": "Kasia's secret", "owner_id": KASIA,
             "owner_name": "Kasia", "visibility": "private", "status": "learning", "field": "",
             "description": "", "draft_step": None, "recipe": JUDGE, "targets": {}},
        ]
        t["ai_model_teachers"] = [
            {"model_id": SPEAK, "user_id": ARTUR, "role": "owner", "trust_status": "counts",
             "paused_at": None, "company_line": None},
            {"model_id": INTERVIEW, "user_id": MARTA, "role": "contributor", "trust_status": "learning",
             "paused_at": None, "company_line": None},
            {"model_id": PITCH, "user_id": MARTA, "role": "contributor", "trust_status": "learning",
             "paused_at": None, "company_line": None},
        ]
        t["ai_model_answers"] = [{"id": f"x{i}", "model_id": SPEAK, "example_id": "old",
                                  "teacher_id": ARTUR, "step": "rate", "answer": "Yes", "counted": True,
                                  "created_at": "2026-11-01"} for i in range(5)]
        t["ai_model_examples"] = [
            {"id": ES, "model_id": SPEAK, "source": "takes", "private": False, "snippet_id": "clip-1",
             "in_exam": False, "machine": {"label": "yes"}, "sureness": 0.6, "known_answer": None,
             "speaker_id": KASIA, "added_by": None, "kind": None, "content": {}},
            {"id": EI, "model_id": INTERVIEW, "source": "takes", "private": False, "snippet_id": "clip-1",
             "in_exam": False, "machine": None, "sureness": None, "known_answer": None,
             "speaker_id": KASIA, "added_by": None, "kind": None, "content": {}},
            {"id": EP, "model_id": PITCH, "source": "takes", "private": False, "snippet_id": "clip-1",
             "in_exam": False, "machine": None, "sureness": None, "known_answer": None,
             "speaker_id": KASIA, "added_by": None, "kind": None, "content": {}},
            {"id": "x1", "model_id": SPEAK, "in_exam": True, "private": False, "source": "upload"},
        ]

    def _get(self, path):
        return self.client.get(path, headers={"Authorization": "Bearer t"})

    def _post(self, path, body=None):
        return self.client.post(path, json=body or {}, headers={"Authorization": "Bearer t"})

    def test_without_the_ring_nothing_is_shown(self):
        self.ring = False
        for path in ("/v2/models", "/v2/models/queue", "/v2/models/rows", f"/v2/models/{SPEAK}"):
            self.assertEqual(self._get(path).status_code, 404, path)

    def test_the_list_and_a_private_page(self):
        out = self._get("/v2/models").get_json()
        speak = next(m for m in out["models"] if m["name"] == "Speaking confidence")
        self.assertEqual(speak["line"], "50% of the way to its first training · 1 teacher")
        self.assertNotIn("Kasia's secret", [m["name"] for m in out["models"]])
        self.assertEqual(self._get("/v2/models/dddddddd-dddd-4ddd-8ddd-dddddddddddd").status_code, 404)
        page = self._get(f"/v2/models/{SPEAK}").get_json()
        self.assertEqual(page["role"], "public")
        self.assertNotIn("jars", page)

    def test_the_door_the_queue_and_pause(self):
        self.assertEqual(self._post(f"/v2/models/{SPEAK}/enter").status_code, 200)
        q = self._get(f"/v2/models/queue?only={SPEAK}").get_json()
        self.assertEqual([e["id"] for e in q["examples"]], [ES])
        self.assertNotIn("machine", q["examples"][0])
        self.assertNotIn("sureness", q["examples"][0])
        self.assertEqual(q["header"], "1 example is waiting. The ones that help most come first.")
        for mid in (SPEAK, INTERVIEW, PITCH):
            self._post(f"/v2/models/{mid}/pause", {"paused": True})
        empty = self._get("/v2/models/queue").get_json()
        self.assertEqual(empty["empty"]["title"], "Nothing waits for you.")
        rows = self._get("/v2/models/rows").get_json()["rows"]
        self.assertEqual(rows[0], {"name": "Your queue", "line": "0 examples wait · 0 models"})

    def test_one_answer_counts_for_both_and_the_other_question_follows(self):
        self._post(f"/v2/models/{SPEAK}/enter")
        out = self._post(f"/v2/models/{SPEAK}/examples/{ES}/answer", {"step": "rate", "answer": "Yes"}).get_json()
        self.assertEqual(out["note"], "Counts for Speaking confidence and Interview voice: both ask this question")
        self.assertEqual(out["follow"][0]["line"],
                         "Pitch Coach asks something else about the same clip: how rushed does it sound?")
        self.assertIsNone(out["trust"])
        self.assertNotIn("machine", str(out))
        saved = {(a["model_id"], a["example_id"]) for a in self.store.tables["ai_model_answers"]
                 if a["teacher_id"] == MARTA}
        self.assertEqual(saved, {(SPEAK, ES), (INTERVIEW, EI)})

    def test_the_profile_and_the_invite(self):
        self.who = ARTUR
        section = self._get(f"/v2/models/profile/{ARTUR}").get_json()["section"]
        self.assertEqual(section["models"][0]["line"], "You started it · 50% of the way · 1 teacher")
        self.store.tables["ai_model_invites"] = [{"id": "11111111-0000-4000-8000-000000000001",
                                                  "model_id": PITCH, "inviter_id": KASIA,
                                                  "invitee_id": MARTA, "status": "not_now"}]
        self.who = MARTA
        card = self._get("/v2/models/invites/11111111-0000-4000-8000-000000000001").get_json()
        self.assertEqual(card["lines"], ["Kasia invited you to teach Pitch Coach with them.",
                                         "You said not now. The invite stays here; open it whenever you like."])


if __name__ == "__main__":
    unittest.main()
