"""
STORY    As the founder, I want the model pipes tight before the launchpad
         opens to anyone else, so that no teacher can teach a model what it
         is tested on, no newcomer is let in on another newcomer's word, a
         withdrawn training yes reaches every model, counts are whole, and a
         private example stays private (N615 item 2).
OUTCOME
  O1  (PIPE-01) An answer on an exam example, or on an example the teacher
      added themself, is refused and nothing is stored.
PROVES   O1 -> ModelPipesTest::test_an_exam_example_or_your_own_cannot_be_answered
WHY      The audit of the launchpad's code (N615); the build's stories
         PIPE-01 to PIPE-09 (docs/design/the-blank-setup-2026-11-10).
"""
from __future__ import annotations

from tests.test_model_launchpad_routes import KASIA, SPEAK, ModelRoutesTest

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
