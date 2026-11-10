"""
STORY    As a host whose people's answers teach a model, I want it to answer
         from what they settled, not from a general model reading its name;
         to say "sure" only when it has been measured right; to be checked by
         me on examples it never saw before it answers in my chat; and to be
         shared or sold only after an exam the app computes (N615, N616 items
         8, 9, 10 and 23, N620).
OUTCOME
  LEARN-01  Training reads each settled example once and fits one head on
            the settled examples only: never an exam case, another model's
            example or a withdrawn speaker's.
  LEARN-02  The answer comes from the head: one of its three answers, one
            reader call and no chat call; "sure" from the head's measured
            confidence. Without a head, the recipe card answers as before.
  LEARN-03  The owner's check is ten examples the version was not fitted on,
            none of the first 10, the guess first; Keep or Change on each.
  LEARN-04  After the owner's check the model answers in its owner's chat;
            it is not shared for tokens or sold before a passed exam.
  LEARN-05  A version's exam is computed by the app, with the sign test
            against the version before; nobody enters "passed" by hand.
  LEARN-06  No model that reads a photo starts, learns or is offered.
  PIPE-06   A withdrawn person's examples mark every version that learned
            from them to retrain, and the next fit leaves them out.
PROVES   LEARN-01 -> ModelLearnsTest::test_a_head_learns_from_settled_examples_only
         LEARN-02 -> ModelLearnsTest::test_the_answer_comes_from_the_head
         LEARN-03 -> ModelLearnsTest::test_the_owners_check_is_ten_unseen_examples
         LEARN-04 -> ModelLearnsTest::test_two_gates
         LEARN-05 -> ModelLearnsTest::test_the_exam_is_computed_never_entered
         LEARN-06 -> ModelLearnsTest::test_no_photo_model_is_offered
         PIPE-06  -> ModelLearnsTest::test_a_withdrawn_example_marks_its_versions_to_retrain
WHY      services/model_head.py (the rules) and services/model_head_store.py
         (migration a_model_learns_from_its_settled_examples). The reader is
         mocked: no provider call in CI.
"""
from __future__ import annotations

import contextlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services.db import db
from tests.test_model_api_routes import _CappedStore

KASIA = "11111111-1111-4111-8111-111111111111"   # owns Pace coach
MARTA = "22222222-2222-4222-8222-222222222222"   # the exam's second expert
TOMEK = "33333333-3333-4333-8333-333333333333"   # another host
GONE = "55555555-5555-4555-8555-555555555555"    # a speaker who turned the yes off
PACE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
ANSWERS = ["Calm", "Rushed", "Flat"]
RECIPE = {"input": "text", "steps": ["rate"], "question": "How does it sound?", "scale": ANSWERS}
AXIS = {"calm": 0, "rushed": 1, "flat": 2}


def _uid(n: int) -> str:
    return f"eeeeeeee-eeee-4eee-8eee-{n:012d}"


def vector_of(text: str) -> list[float]:
    """The mocked reader: a word's axis, and a little of the rest."""
    v = [0.1, 0.1, 0.1]
    for word, axis in AXIS.items():
        if word in text.lower():
            v[axis] = 1.0
    return v


class ModelLearnsTest(unittest.TestCase):
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
        self.store = _CappedStore()
        self.who = KASIA
        self.read: list[str] = []
        self.chats: list[str] = []
        self.withdrawn: set[str] = {GONE}

        def reader(texts, *, surface):
            self.read.extend(texts)
            return [vector_of(t) for t in texts]

        def chat(**kw):
            self.chats.append(kw.get("system", ""))
            return SimpleNamespace(parsed={"answer": "Rushed", "confidence": 0.9, "lines": ["It sounds rushed."]},
                                   text="")

        def may_teach(_db, speaker):
            return {"ok": speaker not in self.withdrawn, "granted_at": "2026-01-01"}

        for p in (patch.object(auth, "verify_supabase_token", lambda _t: {"sub": self.who}),
                  patch.object(db, "client", self.store),
                  patch("services.rings.feature_is_on_for_user", lambda *_a, **_k: True),
                  patch("services.model_head_store.read", reader),
                  patch("services.llm.chat_complete", chat),
                  patch("services.model_examples_from_takes.speaker_may_teach", may_teach),
                  patch("routes.v2.processing_authorization.user_provider_scope",
                        lambda *_a, **_k: contextlib.nullcontext()),
                  patch("services.model_setup_store.with_people",
                        lambda _db, _m: {"exam": {"experts": [KASIA, MARTA]}})):
            p.start()
            self.addCleanup(p.stop)
        t = self.store.tables
        t["ai_models"] = [
            {"id": PACE, "name": "Pace coach", "owner_id": KASIA, "owner_name": "Kasia", "visibility": "public",
             "status": "learning", "field": "talks", "description": "", "draft_step": None, "recipe": RECIPE,
             "targets": {"exam": 3}, "price_units": 300,
             "setup": {"first_ten": [{"example_id": _uid(1)}, {"example_id": _uid(2)}]}},
            {"id": OTHER, "name": "Other coach", "owner_id": TOMEK, "owner_name": "Tomek", "visibility": "public",
             "status": "learning", "field": "talks", "description": "", "draft_step": None, "recipe": RECIPE,
             "targets": {}, "price_units": None, "setup": {}},
        ]
        t["ai_model_teachers"] = [
            {"model_id": PACE, "user_id": KASIA, "role": "owner", "trust_status": "counts"},
            {"model_id": PACE, "user_id": MARTA, "role": "contributor", "trust_status": "counts"}]
        ex = []
        for n in range(1, 16):           # 15 settled, five of each answer
            word = ANSWERS[n % 3]
            ex.append({"id": _uid(n), "model_id": PACE, "source": "business", "private": True,
                       "content": {"text": f"{word.lower()} talk {n}"}, "known_answer": word, "in_exam": False})
        for n in range(20, 32):          # 12 unsettled, for the owner's check
            ex.append({"id": _uid(n), "model_id": PACE, "source": "business", "private": True,
                       "content": {"text": f"{ANSWERS[n % 3].lower()} new {n}"}, "known_answer": None,
                       "in_exam": False})
        for n in range(40, 43):          # the sealed exam
            ex.append({"id": _uid(n), "model_id": PACE, "source": "takes", "speaker_id": MARTA,
                       "content": {"text": f"{ANSWERS[n % 3].lower()} exam {n}"}, "known_answer": None,
                       "in_exam": True})
        ex.append({"id": _uid(50), "model_id": OTHER, "source": "business", "private": True,
                   "content": {"text": "calm other"}, "known_answer": "Calm", "in_exam": False})
        ex.append({"id": _uid(60), "model_id": PACE, "source": "takes", "speaker_id": GONE,
                   "content": {"text": "flat withdrawn"}, "known_answer": "Flat", "in_exam": False})
        t["ai_model_examples"] = ex
        t["ai_model_answers"] = [
            {"id": f"x{n}{who[:2]}", "example_id": _uid(n), "model_id": PACE, "teacher_id": who, "step": "rate",
             "answer": ANSWERS[n % 3], "counted": False}
            for n in range(40, 43) for who in (KASIA, MARTA)]

    def _get(self, path):
        return self.client.get(path, headers={"Authorization": "Bearer t"})

    def _post(self, path, body=None):
        return self.client.post(path, json=body or {}, headers={"Authorization": "Bearer t"})

    def _fit(self):
        from services import model_head_store
        return model_head_store.sweep(database=db)

    def _version(self, number=1):
        return next(v for v in self.store.tables["ai_model_versions"]
                    if v["model_id"] == PACE and v["number"] == number)

    def test_a_head_learns_from_settled_examples_only(self):
        self.assertEqual(self._fit()["fitted"], 1)
        v = self._version()
        self.assertEqual(sorted(v["example_ids"]), sorted(_uid(n) for n in range(1, 16)))
        for never in (_uid(40), _uid(50), _uid(60)):   # exam, another model's, withdrawn
            self.assertNotIn(never, v["example_ids"])
        self.assertNotIn("calm other", self.read)
        self.assertNotIn("flat withdrawn", self.read)
        self.assertEqual(v["head"]["answers"], ANSWERS)
        # Read once: a second fit reads nothing it read before.
        before = list(self.read)
        self.store.tables["ai_models"][0]["retrain_at"] = "2026-11-10T00:00:00+00:00"
        self.assertEqual(self._fit()["fitted"], 1)
        self.assertEqual(self.read, before)

    def test_the_answer_comes_from_the_head(self):
        tried = self._post(f"/v2/models/{PACE}/try", {"message": "a rushed opening"}).get_json()
        self.assertEqual(len(self.chats), 1)            # no head yet: the recipe card answers
        self._fit()
        self.chats.clear()
        self.read.clear()
        tried = self._post(f"/v2/models/{PACE}/try", {"message": "a rushed opening"}).get_json()
        self.assertEqual(self.chats, [])                # no chat call
        self.assertEqual(self.read, ["a rushed opening"])  # one reader call
        self.assertTrue(tried["sure"])
        self.assertEqual(tried["text"], "Rushed")
        from services import model_head
        v = self._version()
        self.assertFalse(model_head.is_sure({"levels": [{"at": 0.0, "n": 10, "right": 6}]}, 0.99))
        self.assertIn(model_head.answer(v, vector_of("flat voice"))["answer"], ANSWERS)

    def test_the_owners_check_is_ten_unseen_examples(self):
        self.assertEqual(self._get(f"/v2/models/{PACE}/check").status_code, 404)   # no head yet
        self._fit()
        check = self._get(f"/v2/models/{PACE}/check").get_json()
        ids = [i["example_id"] for i in check["items"]]
        self.assertEqual(len(ids), 10)
        fitted = set(self._version()["example_ids"])
        for i in check["items"]:
            self.assertNotIn(i["example_id"], fitted | {_uid(1), _uid(2), _uid(40), _uid(41), _uid(42)})
            self.assertIn(i["guess"], ANSWERS)
            self.assertNotIn("known_answer", i["example"])
        self.assertEqual(self._get(f"/v2/models/{PACE}/check").get_json()["items"], check["items"])  # once
        changed = self._post(f"/v2/models/{PACE}/check",
                             {"example_id": ids[0], "keep": False, "answer": "Flat"}).get_json()
        self.assertEqual((changed["items"][0]["kept"], changed["items"][0]["answer"]), (False, "Flat"))
        self.assertEqual(self._post(f"/v2/models/{PACE}/check",
                                    {"example_id": ids[1], "keep": False, "answer": "Loud"}).status_code, 400)
        self.who = MARTA
        self.assertEqual(self._get(f"/v2/models/{PACE}/check").status_code, 404)   # the owner's alone

    def test_two_gates(self):
        from services import model_head_store
        self._fit()
        own = [{"q": "How does it sound?", "opts": ANSWERS, "model_id": PACE}]
        self.assertEqual(model_head_store.chat_answers(db, KASIA, own, "a calm close"), {})
        self.assertFalse(self._get(f"/v2/models/{PACE}/learning").get_json()["gates"]["owner_chat"])
        for item in self._get(f"/v2/models/{PACE}/check").get_json()["items"]:
            self._post(f"/v2/models/{PACE}/check", {"example_id": item["example_id"], "keep": True})
        gates = self._get(f"/v2/models/{PACE}/learning").get_json()["gates"]
        self.assertTrue(gates["owner_chat"])
        self.read.clear()
        self.assertEqual(model_head_store.chat_answers(db, KASIA, own, "a calm close"), {0: {"answer": "Calm"}})
        self.assertEqual(len(self.read), 1)             # one reader call for the chat's models
        # Another host may not use it, and nobody buys it, before a passed exam.
        self._version()["exam"] = {"computed": True, "passed": False}
        self.assertEqual(model_head_store.chat_answers(db, TOMEK, own, "a calm close"), {})
        self.assertFalse(self._get(f"/v2/models/{PACE}/learning").get_json()["gates"]["share"])
        self.who = TOMEK
        self.assertIsNotNone(self._get(f"/v2/models/{PACE}/use").get_json().get("refused"))

    def test_the_exam_is_computed_never_entered(self):
        from services import model_api_store
        from services.chats import ChatsError
        with self.assertRaises(ChatsError) as refused:
            model_api_store.admin_version(db, PACE, {"exam": {"passed": True}, "status": "passed"})
        self.assertEqual(refused.exception.code, "EXAM_IS_COMPUTED")
        self.assertEqual(model_api_store.admin_version(db, PACE, {}), {"queued": True})
        self._fit()
        v = self._version()
        self.assertTrue(v["exam"]["computed"])
        self.assertEqual((v["exam"]["cases"], v["exam"]["as_good_in_ten"]), (3, 10))
        self.assertTrue(v["exam"]["passed"])
        self.assertEqual(v["status"], "passed")
        # The next version is compared case by case with this one.
        self.store.tables["ai_models"][0]["retrain_at"] = "2026-11-10T00:00:00+00:00"
        self._fit()
        self.assertEqual(self._version(2)["exam"]["same"], 3)
        from services.model_head import exam_result
        worse = exam_result([{"example_id": str(i), "truth": "Calm", "guess": "Flat"} for i in range(14)], 14,
                            {"right": {str(i): True for i in range(14)}})
        self.assertFalse(worse["passed"])
        self.assertEqual(worse["worse"], 14)

    def test_no_photo_model_is_offered(self):
        from services import model_head_store
        from services import model_setup as S
        photo = {**RECIPE, "input": "image"}
        self.store.tables["ai_models"][0]["recipe"] = photo
        self.assertEqual(self._fit()["fitted"], 0)
        self.assertFalse(S.can_start({"name": "Skin check", "input": "image", "parts": {"pick": True}}))
        self.assertTrue(S.can_start({"name": "Skin check", "input": "text", "parts": {"pick": True}}))
        self.assertEqual(model_head_store.chat_answers(db, KASIA, [{"model_id": PACE}], "a photo"), {})
        from services.chat_recipes import shared_models
        self.store.tables["ai_models"][0].update({"price_units": 300})
        self.store.tables["ai_model_versions"] = [
            {"model_id": PACE, "status": "released", "exam": {"computed": True, "passed": True}}]
        with patch("services.chat_recipes.mine", lambda *_a: {"send": ["photo"]}):
            self.assertEqual(shared_models(db, TOMEK), {"models": []})

    def test_a_withdrawn_example_marks_its_versions_to_retrain(self):
        from services.model_examples_from_takes import let_go_everywhere
        self.withdrawn = set()
        self._fit()
        self.assertIn(_uid(60), self._version()["example_ids"])
        self.withdrawn = {GONE}
        self.assertEqual(let_go_everywhere(db), 1)
        self.assertTrue(self._version()["retrain_at"])
        self._fit()
        self.assertNotIn(_uid(60), self._version(2)["example_ids"])


if __name__ == "__main__":
    unittest.main()
