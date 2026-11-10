"""
STORY    As the founder, I want the model pipes tight before the launchpad
         opens to anyone else, so that no teacher can teach a model what it
         is tested on, no newcomer is let in on another newcomer's word, a
         withdrawn training yes reaches every model, counts are whole, and a
         private example stays private (N615 item 2).
OUTCOME
  O1  (PIPE-01) An answer on an exam example, or on an example the teacher
      added themself, is refused and nothing is stored.
  O2  (PIPE-02) Two new teachers who answer the same examples alike are not
      admitted on each other's answers: a newcomer is measured against
      trusted teachers and known answers only.
  O3  (PIPE-03) A speaker whose Takes are examples in more than twenty models
      turns the training yes off: at the next run their examples leave
      every model.
PROVES   O1 -> ModelPipesTest::test_an_exam_example_or_your_own_cannot_be_answered
         O2 -> ModelPipesTest::test_a_newcomer_is_measured_against_trusted_teachers_only
         O3 -> SweepTest::test_turning_the_training_yes_off_reaches_every_model
WHY      The audit of the launchpad's code (N615); the build's stories
         PIPE-01 to PIPE-09 (docs/design/the-blank-setup-2026-11-10).
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from tests.test_chats import _Store
from tests.test_model_launchpad_routes import ARTUR, KASIA, MARTA, SPEAK, ModelRoutesTest

EXAM = "e5000000-0000-4000-8000-0000000000ee"


class ModelPipesTest(ModelRoutesTest):
    def _answer(self, model, example, answer="Yes"):
        return self._post(f"/v2/models/{model}/examples/{example}/answer", {"step": "rate", "answer": answer})

    def _answers_on(self, example):
        return [a for a in self.store.tables["ai_model_answers"] if a["example_id"] == example]

    def test_an_exam_example_or_your_own_cannot_be_answered(self):
        self.store.tables["ai_model_examples"].append({
            "id": EXAM, "model_id": SPEAK, "source": "takes", "private": False, "snippet_id": "clip-9",
            "in_exam": True, "known_answer": None, "speaker_id": KASIA, "added_by": None, "content": {}})
        self.assertEqual(self._post(f"/v2/models/{SPEAK}/enter").status_code, 200)
        exam = self._answer(SPEAK, EXAM)
        self.assertGreaterEqual(exam.status_code, 400)
        self.assertEqual(self._answers_on(EXAM), [])
        added = self._post(f"/v2/models/{SPEAK}/examples", {"text": "A pause before the ask."}).get_json()
        mine = self._answer(SPEAK, added["example_id"])
        self.assertGreaterEqual(mine.status_code, 400)
        self.assertEqual(self._answers_on(added["example_id"]), [])
        self.who = KASIA                                  # another teacher may answer it
        self._post(f"/v2/models/{SPEAK}/enter")
        self.assertEqual(self._answer(SPEAK, added["example_id"]).status_code, 200)
        self.assertEqual([a["teacher_id"] for a in self._answers_on(added["example_id"])], [KASIA])

    def test_a_newcomer_is_measured_against_trusted_teachers_only(self):
        scale = ["Yes", "In-between", "No"]
        known = [f"e6000000-0000-4000-8000-{i:012d}" for i in range(10)]
        fresh = [f"e7000000-0000-4000-8000-{i:012d}" for i in range(30)]
        for i, eid in enumerate(known + fresh):
            self.store.tables["ai_model_examples"].append({
                "id": eid, "model_id": SPEAK, "source": "teacher", "private": False, "snippet_id": None,
                "in_exam": False, "speaker_id": None, "added_by": None, "content": {"text": f"case {i}"},
                "known_answer": scale[i % 3] if eid in known else None})

        def teach(who):
            self.who = who
            self._post(f"/v2/models/{SPEAK}/enter")
            for i, eid in enumerate(known):               # half of the known clips right
                self._answer(SPEAK, eid, scale[i % 3] if i % 2 == 0 else scale[(i + 1) % 3])
            for i, eid in enumerate(fresh):               # the two newcomers agree on every new one
                self._answer(SPEAK, eid, scale[(i * 7) % 3])

        teach(KASIA)
        teach(MARTA)
        self.who = KASIA                                  # Kasia's trust, read again after Marta's answers
        self._answer(SPEAK, fresh[0], scale[0])
        status = {t["user_id"]: t.get("trust_status") for t in self.store.tables["ai_model_teachers"]
                  if t["model_id"] == SPEAK}
        self.assertNotEqual(status[MARTA], "counts")
        self.assertNotEqual(status[KASIA], "counts")


class SweepTest(unittest.TestCase):
    def test_turning_the_training_yes_off_reaches_every_model(self):
        from services import model_examples_from_takes as gather
        store = _Store()
        gone, stays = "aaaa0000-0000-4000-8000-000000000001", "aaaa0000-0000-4000-8000-000000000002"
        models = [f"bbbb0000-0000-4000-8000-{i:012d}" for i in range(25)]
        store.tables["ai_models"] = [{"id": m, "owner_id": ARTUR, "status": "learning",
                                      "recipe": {"input": "voice"}} for m in models]
        store.tables["ai_model_examples"] = [
            {"id": f"{m}-{who}", "model_id": m, "source": "takes", "speaker_id": who, "snippet_id": f"{m}{who}",
             "in_exam": False} for m in models for who in (gone, stays)]

        class Database:
            client = store

        def may_teach(_db, speaker):
            return {"ok": speaker == stays, "granted_at": "2026-01-01"}

        with patch.object(gather, "speaker_may_teach", may_teach):
            gather.sweep(database=Database(), limit=20)
        left = {(e["model_id"], e["speaker_id"]) for e in store.tables["ai_model_examples"]}
        self.assertEqual({w for _, w in left}, {stays})
        self.assertEqual(len(left), 25)
