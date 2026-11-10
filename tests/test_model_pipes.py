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
  O4  (PIPE-04) A model with more than a thousand counted answers shows every
      one of them in its counts.
  O5  (PIPE-09) A teacher the owner invites after the model went public is
      never sent, and cannot answer, the examples that were private; a
      teacher invited while it was private still is.
  O6  (PIPE-05) The same people's Takes reach two models: each model sets
      aside its own people for its exam, and a moment sealed in one model's
      exam is neither served to nor answerable by that exam's expert in the
      other model, while another teacher still gets it there.
  O7  The gathering reaches every model over successive runs, not the same
      first twenty every run.
PROVES   O1 -> ModelPipesTest::test_an_exam_example_or_your_own_cannot_be_answered
         O2 -> ModelPipesTest::test_a_newcomer_is_measured_against_trusted_teachers_only
         O3 -> SweepTest::test_turning_the_training_yes_off_reaches_every_model
         O4 -> ModelPipesTest::test_counts_read_every_row
         O5 -> ModelPipesTest::test_invited_after_going_public_does_not_open_private_examples
         O6 -> SweepTest::test_each_models_exam_has_its_own_people
         O6 -> ModelPipesTest::test_a_sealed_moment_is_not_taught_by_its_expert_elsewhere
         O7 -> SweepTest::test_every_model_takes_its_turn_in_the_gathering
WHY      The audit of the launchpad's code (N615); the build's stories
         PIPE-01 to PIPE-09 (docs/design/the-blank-setup-2026-11-10).
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from tests.test_chats import _Query, _Result, _Store
from tests.test_model_launchpad_routes import ARTUR, KASIA, MARTA, SPEAK, ModelRoutesTest

EXAM = "e5000000-0000-4000-8000-0000000000ee"
SECRET = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
SERVER_CAP = 1000


class _CappedQuery(_Query):
    """PostgREST as it answers: at most a thousand rows a read; a range
    reads the page it names."""

    def execute(self):
        out = super().execute()
        return out if self.write else _Result(out.data[:SERVER_CAP])


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


    def test_counts_read_every_row(self):
        self.store.table = lambda name: _CappedQuery(self.store, name)
        self.store.tables["ai_model_answers"] += [
            {"id": f"y{i}", "model_id": SPEAK, "example_id": "old", "teacher_id": ARTUR, "step": "rate",
             "answer": "Yes", "counted": True, "created_at": "2026-11-02"} for i in range(1500)]
        self.who = ARTUR
        page = self._get(f"/v2/models/{SPEAK}").get_json()
        self.assertEqual(page["jars"]["counted_answers"], 1505)
        self.assertEqual(page["own_part"]["answers_counted"], 1505)


    def test_invited_after_going_public_does_not_open_private_examples(self):
        own = "e5000000-0000-4000-8000-000000000009"
        late = "11111111-0000-4000-8000-00000000000a"
        t = self.store.tables
        t["ai_model_examples"].append({"id": own, "model_id": SECRET, "source": "upload", "private": True,
                                       "in_exam": False, "kind": "rerate", "added_by": KASIA, "speaker_id": None,
                                       "snippet_id": None, "known_answer": None,
                                       "content": {"text": "A client's own case."}})
        before = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        t["ai_model_invites"] = [{"id": "11111111-0000-4000-8000-000000000009", "model_id": SECRET,
                                  "inviter_id": KASIA, "invitee_id": ARTUR, "status": "accepted",
                                  "created_at": before}]
        t["ai_model_teachers"].append({"model_id": SECRET, "user_id": ARTUR, "role": "contributor",
                                       "trust_status": "learning", "paused_at": None, "company_line": None})
        self.who = KASIA
        self.assertEqual(self._post(f"/v2/models/{SECRET}/make-public", {"confirm": True}).status_code, 200)
        after = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
        t["ai_model_invites"].append({"id": late, "model_id": SECRET, "inviter_id": KASIA,
                                      "invitee_id": MARTA, "status": "open", "created_at": after})
        self.who = MARTA                                   # invited after it went public
        self.assertEqual(self._post(f"/v2/models/invites/{late}/accept").status_code, 200)
        self.assertNotIn(own, [e["id"] for e in self._get("/v2/models/queue").get_json()["examples"]])
        self.assertEqual(self._answer(SECRET, own).status_code, 404)
        self.who = ARTUR                                   # invited while it was private
        self.assertIn(own, [e["id"] for e in self._get("/v2/models/queue").get_json()["examples"]])

    def test_a_sealed_moment_is_not_taught_by_its_expert_elsewhere(self):
        from tests.test_model_launchpad_routes import INTERVIEW
        twin = "e5000000-0000-4000-8000-00000000007a"
        t = self.store.tables
        t["ai_models"][0]["setup"] = {"exam": {"asked_at": "2026-11-01"}}     # Artur sets SPEAK's exam
        t["ai_model_teachers"].append({"model_id": INTERVIEW, "user_id": ARTUR, "role": "contributor",
                                       "trust_status": "learning", "paused_at": None, "company_line": None})
        t["ai_model_examples"] += [
            {"id": EXAM, "model_id": SPEAK, "source": "takes", "private": False, "snippet_id": "clip-7",
             "in_exam": True, "known_answer": None, "speaker_id": KASIA, "added_by": None, "content": {}},
            {"id": twin, "model_id": INTERVIEW, "source": "takes", "private": False, "snippet_id": "clip-7",
             "in_exam": False, "known_answer": None, "speaker_id": KASIA, "added_by": None, "content": {}}]
        self.who = ARTUR
        served = [(e["id"], e.get("model_id")) for e in self._get("/v2/models/queue").get_json()["examples"]]
        self.assertNotIn(twin, [i for i, _ in served])
        self.assertEqual(self._answer(INTERVIEW, twin).status_code, 404)
        self.assertEqual(self._answers_on(twin), [])
        self.who = MARTA                                   # not an expert of SPEAK's exam
        self.assertIn(twin, [e["id"] for e in self._get("/v2/models/queue").get_json()["examples"]])


class SweepTest(unittest.TestCase):
    def test_each_models_exam_has_its_own_people(self):
        from services import model_examples_from_takes as gather
        store = _Store()
        a, b = "bbbb0000-0000-4000-8000-0000000000a1", "bbbb0000-0000-4000-8000-0000000000b2"
        store.tables["ai_models"] = [{"id": m, "owner_id": ARTUR, "status": "learning",
                                      "recipe": {"input": "voice"}} for m in (a, b)]
        store.tables["ai_model_examples"] = []
        speakers = [f"aaaa0000-0000-4000-8000-{i:012d}" for i in range(60)]
        takes = [{"speaker_id": s, "take_id": f"take-{s}"} for s in speakers]

        class Database:
            client = store

        with patch.object(gather, "speaker_may_teach", lambda _d, _s: {"ok": True, "granted_at": "2026-01-01"}), \
                patch.object(gather, "_received_takes", lambda _d, _o: takes), \
                patch.object(gather, "_recorded_at", lambda _d, _t: "2026-02-01"), \
                patch.object(gather, "_moments", lambda _d, take: [{"id": f"{take}-m", "transcript": "Hello."}]):
            gather.sweep(database=Database())

        def exam_people(model):
            return {e["speaker_id"] for e in store.tables["ai_model_examples"]
                    if e["model_id"] == model and e["in_exam"]}
        self.assertTrue(exam_people(a) and exam_people(b))
        self.assertNotEqual(exam_people(a), exam_people(b))
        self.assertTrue(exam_people(a) - exam_people(b))


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

    def test_every_model_takes_its_turn_in_the_gathering(self):
        from services import model_examples_from_takes as gather
        store = _Store()
        models = [f"bbbb0000-0000-4000-8000-{i:012d}" for i in range(25)]
        store.tables["ai_models"] = [{"id": m, "owner_id": ARTUR, "status": "learning",
                                      "recipe": {"input": "voice"}} for m in models]
        store.tables["ai_model_examples"] = []
        reached: list[str] = []

        class Database:
            client = store

        with patch.object(gather, "gather_for_model",
                          lambda _d, m: reached.append(m["id"]) or {"added": 0, "removed": 0}):
            gather.sweep(database=Database(), limit=20)
            gather.sweep(database=Database(), limit=20)
        self.assertEqual(set(reached), set(models))
