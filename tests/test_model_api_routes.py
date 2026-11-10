"""
STORY    As a business, I want to read a model's card, try it, take a free
         test key that I see only once, and call its API, paying in tokens
         only for the answers I use and never more than my monthly limit;
         as a model's founder, I want to set its price above what an answer
         costs, with the split shown live; and as a teacher, I want my share
         of each version and my earnings paid in tokens (N528, N531, N566,
         N577, N583).
OUTCOME
  O1  Without the ring row (ai_models) the card, the terms and keys are 404.
  O2  A ready model's card says "Good at", "Not so good at", "Not for",
      "When it isn’t sure" and "Version", with "Use it in your business" and
      "Try it"; a model not for sale says "trying it · not for sale yet",
      and when it is not sure it says "I’m not sure about this one, so I
      won’t guess." with "Not sure · a coach will answer".
  O3  "Create a key" shows the key once ("This is a test key: free for 100
      answers. You see it only once."); only its hash is stored; the code
      comes in "JavaScript", "Python" and "curl"; the key answers 100 free
      answers and then stops.
  O4  A live key pays the model's price in tokens, split as N577 sets it;
      it gets no answer when the tokens are not charged, and it stops before
      an answer that would pass its monthly limit.
  O5  A business's unsure questions reach the teachers, names removed, only
      once the business allows it.
  O6  "Set your price": − and + preview a price and its split without
      saving; "Use {price}" saves it, never below what an answer costs to
      run; nobody else can.
  O7  A version fixes its teachers' shares; "Your share of version 1" is
      their part of it, and a month's earnings above the minimum are paid
      in tokens, once.
  O8  "Download the data" (the one download route) holds the teachers' own
      ratings and answers, each teacher and example a number, never what a
      speaker said or the sealed exam, and a private example's answers only
      for its owner and the teachers invited to it; someone who never taught
      it is told
      "Only its owner and its teachers can download its data."
  O9  An API answer runs under its buyer's processing authority: refused
      there, the model is never asked.
  O10 Never an unpaid answer and never a charge with no answer: the price is
      taken first, and refunded when the model gives no answer.
  O11 A monthly limit and a month's payouts count every answer, past the
      database's 1,000 rows an answer; only a finished month is paid.
PROVES   O1 -> ModelApiTest::test_without_the_ring_nothing_is_sold
         O2 -> ModelApiTest::test_the_card_and_trying_a_model
         O3 -> ModelApiTest::test_a_test_key_is_shown_once_and_answers_100_times
         O4 -> ModelApiTest::test_a_live_key_pays_in_tokens_and_stops_at_its_limit
         O5 -> ModelApiTest::test_unsure_questions_reach_teachers_only_when_allowed
         O6 -> ModelApiTest::test_the_founder_sets_the_price_above_the_running_cost
         O7 -> ModelApiTest::test_a_version_fixes_shares_and_earnings_are_paid_in_tokens
         O8 -> ModelApiTest::test_the_download_holds_the_teachers_answers_only
         O9 -> ModelApiTest::test_an_api_answer_needs_the_buyers_authority
         O10 -> ModelApiTest::test_no_answer_is_never_charged_and_a_charge_is_never_unanswered
         O11 -> ModelApiTest::test_limits_and_payouts_count_past_a_thousand_rows
WHY      The models' API and its money (migration
         a_business_can_buy_a_model_s_answers), served by
         services/model_api_store.py over services/model_api.py.
"""
from __future__ import annotations

import logging
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services.db import db
from services.processing_authorization import ProcessingAuthorizationError
from services.token_account import ChargeResult
from tests.test_chats import _Query, _Result, _Store


class _CappedQuery(_Query):
    """PostgREST as Supabase runs it: at most 1,000 rows an answer unless a
    range asks for a page, and the gte/lt filters the money reads use."""

    MAX_ROWS = 1000

    def __init__(self, store, name):
        super().__init__(store, name)
        self.offset = 0

    def range(self, start, end):
        self.offset, self.cap = start, end - start + 1
        return self

    def gte(self, column, value):
        self.filters.append(lambda r: str(r.get(column) or "") >= str(value))
        return self

    def lt(self, column, value):
        self.filters.append(lambda r: str(r.get(column) or "") < str(value))
        return self

    def execute(self):
        if self.write:
            return super().execute()
        rows = self.store.tables.setdefault(self.name, [])
        hits = [dict(r) for r in rows if all(f(r) for f in self.filters)]
        if self.sort:
            hits.sort(key=lambda r: r[self.sort[0]], reverse=self.sort[1])
        cap = min(self.cap or self.MAX_ROWS, self.MAX_ROWS)
        return _Result(hits[self.offset:self.offset + cap])


class _CappedStore(_Store):
    def table(self, name):
        return _CappedQuery(self, name)

KASIA = "11111111-1111-4111-8111-111111111111"   # started Job interview coach
MARTA = "22222222-2222-4222-8222-222222222222"   # teaches it; started Pitch Coach
BIZ = "33333333-3333-4333-8333-333333333333"     # a careers website
ARTUR = "44444444-4444-4444-8444-444444444444"   # teaches it too
JOB = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PITCH = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
V1 = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
WORDS = {"input": "text", "steps": ["words"], "question": "How would you answer this interview question?"}


class ModelApiTest(unittest.TestCase):
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
        self.who = BIZ
        self.ring = True
        self.reply = {"answer": "Name a real weakness, then what you changed.", "confidence": 0.9}
        self.asked: list[str] = []
        self.charged: list[tuple] = []
        self.paid: list[tuple] = []
        self.charge_ok = True

        def complete(**kw):
            self.asked.append(kw["user"])
            return SimpleNamespace(parsed=dict(self.reply), text="")

        def charge(user_id, units, *, ref_id, database=None):
            self.charged.append((user_id, units))
            return ChargeResult(True, units if self.charge_ok else 0, 0,
                                "" if self.charge_ok else "insufficient", "model_answer")

        self.refunded: list[tuple] = []

        def refund(user_id, units, *, ref_id, database=None):
            self.refunded.append((user_id, units))
            return {"ok": True, "reason": ""}

        def grant(user_id, units, *, ref_id, database=None):
            self.paid.append((user_id, units, ref_id))
            return {"ok": True, "reason": ""}

        for p in (patch.object(auth, "verify_supabase_token", lambda _t: {"sub": self.who}),
                  patch.object(db, "client", self.store),
                  patch("services.rings.feature_is_on_for_user", lambda *_a, **_k: self.ring),
                  patch("services.llm.chat_complete", complete),
                  patch("services.token_account.enabled", lambda: True),
                  patch("services.token_account.charge_model_answer", charge),
                  patch("services.token_account.model_earnings_grant", grant),
                  patch("services.token_account.refund_model_answer", refund)):
            p.start()
            self.addCleanup(p.stop)
        t = self.store.tables
        t["ai_models"] = [
            {"id": JOB, "name": "Job interview coach", "owner_id": KASIA, "owner_name": "Kasia",
             "visibility": "public", "status": "ready", "field": "interviews",
             "description": "It answers the questions candidates dread.", "draft_step": None,
             "recipe": WORDS, "targets": {}, "price_units": 300},
            {"id": PITCH, "name": "Pitch Coach", "owner_id": MARTA, "owner_name": "Marta",
             "visibility": "public", "status": "learning", "field": "pitches", "description": "",
             "draft_step": None, "recipe": WORDS, "targets": {}, "price_units": None},
        ]
        t["ai_model_teachers"] = [
            {"model_id": JOB, "user_id": KASIA, "role": "owner", "trust_status": "counts", "trust_kappa": 0.8},
            {"model_id": JOB, "user_id": MARTA, "role": "contributor", "trust_status": "counts", "trust_kappa": 1.0},
            {"model_id": JOB, "user_id": ARTUR, "role": "contributor", "trust_status": "counts", "trust_kappa": 1.0},
            {"model_id": PITCH, "user_id": MARTA, "role": "owner", "trust_status": "counts"},
        ]
        t["ai_model_versions"] = [
            {"id": V1, "model_id": JOB, "number": 1, "status": "released", "base_model": "gpt-4o-mini",
             "provider_model": None, "founder_id": KASIA, "created_at": "2026-11-01",
             "released_at": "2026-11-02T10:00:00+00:00", "exam": {"as_good_in_ten": 8},
             "card": {"good_at": "Interviews in English", "not_so_good_at": "Other languages",
                      "not_for": "Legal advice"}},
        ]
        t["ai_model_examples"] = [
            {"id": "e1", "model_id": JOB, "source": "takes", "private": False, "speaker_id": KASIA,
             "kind": "talk", "content": {"words": "What a speaker said"}, "sureness": 0.5},
        ]
        t["ai_model_answers"] = [
            {"id": "a1", "example_id": "e1", "model_id": JOB, "teacher_id": MARTA, "step": "words",
             "answer": "Say what you learned.", "counted": True},
            {"id": "a2", "example_id": "e1", "model_id": JOB, "teacher_id": ARTUR, "step": "words",
             "answer": "Keep it short.", "counted": False},
        ]

    def _get(self, path):
        return self.client.get(path, headers={"Authorization": "Bearer t"})

    def _post(self, path, body=None):
        return self.client.post(path, json=body or {}, headers={"Authorization": "Bearer t"})

    def _ask(self, key, message="How do I answer: what is your biggest weakness?", model=JOB):
        return self.client.post(f"/v2/models/{model}/answer", json={"message": message},
                                headers={"Authorization": f"Bearer {key}"})

    def _key(self, body=None):
        return self._post(f"/v2/models/{JOB}/keys", body).get_json()

    def test_without_the_ring_nothing_is_sold(self):
        self.ring = False
        for path in (f"/v2/models/{JOB}/card", f"/v2/models/{JOB}/use", f"/v2/models/{JOB}/usage"):
            self.assertEqual(self._get(path).status_code, 404, path)
        self.assertEqual(self._post(f"/v2/models/{JOB}/keys").status_code, 404)

    def test_the_card_and_trying_a_model(self):
        card = self._get(f"/v2/models/{JOB}/card").get_json()
        self.assertEqual([r["label"] for r in card["rows"]],
                         ["Good at", "Not so good at", "Not for", "On its final exam",
                          "When it isn’t sure", "Version"])
        self.assertEqual(card["rows"][-1]["value"], "1 · passed its exam on 2026-11-02")
        self.assertEqual(card["actions"], ["Use it in your business", "Try it"])
        self.assertEqual(self._get(f"/v2/models/{PITCH}/card").status_code, 404)

        self.reply = {"answer": "Pause before the number.", "confidence": 0.3}
        tried = self._post(f"/v2/models/{PITCH}/try", {"message": "How do I end my pitch?"}).get_json()
        self.assertEqual(tried["sub"], "trying it · not for sale yet")
        self.assertEqual(tried["text"], "I’m not sure about this one, so I won’t guess. One of the "
                                        "coaches who taught me will answer it here within a day.")
        self.assertEqual(tried["mark"], "Not sure · a coach will answer")
        self.assertEqual(self._get(f"/v2/models/{PITCH}/use").get_json()["refused"],
                         "This model can’t be used in a product yet. It opens once its first "
                         "training passes its final exam.")

    def test_a_test_key_is_shown_once_and_answers_100_times(self):
        with self.assertLogs(level=logging.DEBUG) as logs:
            logging.getLogger("probe").debug("start")
            made = self._key()
            key = made["key"]
            self.assertEqual(self._ask(key).status_code, 200)
        self.assertTrue(key.startswith("wpl_sk_test_"))
        self.assertEqual(made["note"], "This is a test key: free for 100 answers. You see it only once. "
                                       "Keep it secret, like a password. If it leaks, delete it and make a new one.")
        stored = self.store.tables["ai_model_api_keys"][0]
        self.assertNotIn(key, str(stored))
        self.assertNotIn(key, "\n".join(logs.output))
        self.assertEqual(self._post(f"/v2/models/{JOB}/keys").status_code, 409)  # one test key, ever

        code = self._get(f"/v2/models/{JOB}/code").get_json()
        self.assertEqual([t["label"] for t in code["tabs"]], ["JavaScript", "Python", "curl"])
        self.assertNotIn(key, str(code))
        self.assertEqual(code["sure"], "Each answer comes with “sure”: true or false. When it is false, "
                                       "show the answer as a draft, or pass the question to a person.")

        for _ in range(99):
            out = self._ask(key)
        self.assertEqual(out.get_json(), {"answer": "Name a real weakness, then what you changed.",
                                          "sure": True, "version": 1})
        refused = self._ask(key)
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (402, "FREE_ANSWERS_USED"))
        self.assertEqual(self.charged, [])
        usage = self._get(f"/v2/models/{JOB}/usage").get_json()
        self.assertEqual(usage["line"], "Job interview coach answered 100 questions for your users this month.")
        self.assertEqual(usage["version"]["line"],
                         "You use version 1. When version 2 passes the same exam, you choose when to switch.")
        self.assertEqual(self._ask(key, model=PITCH).status_code, 401)

    def test_a_live_key_pays_in_tokens_and_stops_at_its_limit(self):
        key = self._key({"kind": "live", "monthly_limit_units": 900})["key"]
        for _ in range(3):
            self.assertEqual(self._ask(key).status_code, 200)
        self.assertEqual(self.charged, [(BIZ, 300)] * 3)
        call = self.store.tables["ai_model_calls"][0]
        # N577: 300 less 60 to run = 240; WillpowerLab 20% = 48; the founder 10% of 192 = 19.
        self.assertEqual((call["cost_units"], call["fee_units"], call["founder_units"], call["teachers_units"]),
                         (60, 48, 19, 173))
        stopped = self._ask(key)
        self.assertEqual((stopped.status_code, stopped.get_json()["code"]), (429, "MONTHLY_LIMIT"))

        poor = self._key({"kind": "live", "monthly_limit_units": 5000})["key"]
        self.charge_ok = False
        refused = self._ask(poor)
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (402, "NOT_ENOUGH_TOKENS"))
        self.assertNotIn("answer", refused.get_json())
        self.assertEqual(len(self.store.tables["ai_model_calls"]), 3)

    def test_unsure_questions_reach_teachers_only_when_allowed(self):
        made = self._key()
        self.reply = {"answer": "Maybe.", "confidence": 0.2}
        out = self._ask(made["key"], "Why did Maria Lopez leave Acme after four months?").get_json()
        self.assertFalse(out["sure"])
        added = [e for e in self.store.tables["ai_model_examples"] if e["source"] == "business"]
        self.assertEqual(added, [])
        self._post(f"/v2/models/keys/{made['id']}/unsure", {"on": True})
        self._ask(made["key"], "Why did Maria Lopez leave Acme after four months?")
        added = [e for e in self.store.tables["ai_model_examples"] if e["source"] == "business"]
        self.assertEqual(added[0]["content"], {"text": "Why did […] […] leave […] after four months?"})
        self.assertTrue(added[0]["private"])

    def test_the_founder_sets_the_price_above_the_running_cost(self):
        self.who = KASIA
        screen = self._get(f"/v2/models/{JOB}/price").get_json()
        self.assertEqual(screen["title"], "Set your price")
        self.assertEqual([p["label"] for p in screen["split"]],
                         ["Infrastructure", "You, who started it", "The teachers, by their points"])
        preview = self._get(f"/v2/models/{JOB}/price?units=500&uses=1000").get_json()
        self.assertEqual((preview["price_units"], preview["saved_units"]), (500, 300))
        # 1,000 answers at 500: 60,000 to run + 88,000 to WillpowerLab; 35,200 to Kasia.
        self.assertEqual([p["units"] for p in preview["split"]], [148_000, 35_200, 316_800])
        self.assertEqual(self.store.tables["ai_models"][0]["price_units"], 300)  # − and + save nothing
        self.assertEqual(self._post(f"/v2/models/{JOB}/price", {"units": 50}).status_code, 422)
        at_floor = self._post(f"/v2/models/{JOB}/price", {"units": 60}).get_json()
        self.assertFalse(at_floor["minus_enabled"])
        self.assertEqual([p["units"] for p in at_floor["split"]], [600_000, 0, 0])
        self.who = MARTA
        self.assertEqual(self._post(f"/v2/models/{JOB}/price", {"units": 500}).status_code, 404)

    def test_a_version_fixes_shares_and_earnings_are_paid_in_tokens(self):
        from services import model_api_store as store
        made = store.record_version(db, PITCH, provider_model=None, card={}, exam={})
        self.assertEqual(made["number"], 1)
        self.store.tables["ai_model_shares"] = [
            {"version_id": V1, "user_id": MARTA, "points": 3.0, "answers": 3},
            {"version_id": V1, "user_id": ARTUR, "points": 1.0, "answers": 1}]
        self.store.tables["ai_models"][0]["price_units"] = 3000
        key = self._key({"kind": "live", "monthly_limit_units": 10_000_000})["key"]
        for _ in range(130):
            self._ask(key)
        self.who = MARTA
        earn = self._get("/v2/models/earnings").get_json()
        self.assertEqual(earn["rows"][0], {"label": "Your share of version 1", "value": "75%"})
        self.assertEqual(earn["rows"][1], {"label": "Your answers that trained it", "value": "3"})
        for never in ("€", "bank"):  # nothing is paid out in money (N614)
            self.assertNotIn(never, str(earn))

        self.assertEqual(self._pay(store._month_start()[:7]), "MONTH_NOT_FINISHED")  # never mid-month
        last = self._last_month()
        for c in self.store.tables["ai_model_calls"]:
            c["created_at"] = f"{last}-15T10:00:00+00:00"
        store.pay_month(db, last, pay=True)
        store.pay_month(db, last, pay=True)  # a second run pays nobody twice
        # 3000 an answer: 60 to run, 588 to WillpowerLab, 235 to Kasia, 2,117 to the
        # teachers. 130 answers: the teachers' 275,210 split 3:1, and only Marta's
        # part passes the 200,000 minimum; Artur's and Kasia's wait.
        self.assertEqual({(uid, units) for uid, units, _ref in self.paid}, {(MARTA, 206_408)})
        self.assertEqual(len(self.paid), 1)

    @staticmethod
    def _last_month():
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        return f"{now.year - (now.month == 1):04d}-{12 if now.month == 1 else now.month - 1:02d}"

    def _pay(self, month):
        from services import model_api_store as store
        from services.chats import ChatsError
        try:
            store.pay_month(db, month, pay=True)
        except ChatsError as e:
            return e.code
        return None

    def test_no_answer_is_never_charged_and_a_charge_is_never_unanswered(self):
        key = self._key({"kind": "live", "monthly_limit_units": 5000})["key"]
        with patch("services.llm.chat_complete", lambda **_k: None):
            out = self._ask(key)
        self.assertEqual((out.status_code, out.get_json()["code"]), (503, "MODEL_UNAVAILABLE"))
        self.assertEqual((self.charged, self.refunded), ([(BIZ, 300)], [(BIZ, 300)]))
        self.assertEqual(self.store.tables.get("ai_model_calls", []), [])

        def boom(**_k):
            raise RuntimeError("provider down")
        with patch("services.llm.chat_complete", boom):
            self.assertEqual(self._ask(key).status_code, 500)
        self.assertEqual(self.refunded, [(BIZ, 300)] * 2)

        self.charge_ok = False
        refused = self._ask(key)
        self.assertEqual(refused.get_json()["code"], "NOT_ENOUGH_TOKENS")
        self.assertEqual(self.asked, [])        # the provider is never asked unpaid

    def test_limits_and_payouts_count_past_a_thousand_rows(self):
        from services import model_api_store as store
        made = self._key({"kind": "live", "monthly_limit_units": 330_000})
        kid = self.store.tables["ai_model_api_keys"][-1]["id"]
        now = store._month_start()
        self.store.tables["ai_model_calls"] = [
            {"id": f"c{i}", "key_id": kid, "buyer_id": BIZ, "model_id": JOB, "version_id": V1, "test": False,
             "sure": True, "price_units": 300, "cost_units": 60, "fee_units": 48, "founder_units": 19,
             "teachers_units": 173, "created_at": f"{now[:7]}-02T10:{i % 60:02d}:00+00:00"}
            for i in range(1100)]
        stopped = self._ask(made["key"])            # 1,100 × 300 already reaches 330,000
        self.assertEqual(stopped.get_json()["code"], "MONTHLY_LIMIT")
        self.assertEqual(self.charged, [])

        last = self._last_month()
        for c in self.store.tables["ai_model_calls"]:
            c["created_at"] = f"{last}-02T10:00:00+00:00"
        self.store.tables["ai_model_shares"] = [{"version_id": V1, "user_id": MARTA, "points": 1.0, "answers": 1}]
        store.pay_month(db, last, pay=True)
        owed = {(p["user_id"], p["role"]): p["units"] for p in self.store.tables["ai_model_payouts"]}
        self.assertEqual(owed, {(MARTA, "teacher"): 1100 * 173, (KASIA, "founder"): 1100 * 19})

    def test_the_download_holds_the_teachers_answers_only(self):
        self.store.tables["ai_model_examples"].append(
            {"id": "x-exam", "model_id": JOB, "source": "upload", "private": False, "in_exam": True})
        self.store.tables["ai_model_answers"].append(
            {"id": "a3", "example_id": "x-exam", "model_id": JOB, "teacher_id": MARTA, "step": "words",
             "answer": "An exam answer", "counted": True})
        self.who = MARTA
        screen = self._get(f"/v2/models/{JOB}/download").get_json()
        self.assertEqual(screen["actions"], ["Download the data", "Not now"])
        self.assertIn("To sell a product built on it, you need a licence", screen["lines"][2])
        out = self._get(f"/v2/models/{JOB}/download?rows=1").get_json()
        self.assertEqual(sorted((r["answer"], r["teacher"], r["example"]) for r in out["rows"]),
                         [("Keep it short.", 2, 1), ("Say what you learned.", 1, 1)])
        for never in ("What a speaker said", "An exam answer", MARTA, ARTUR):
            self.assertNotIn(never, str(out))
        # A private example (a company's own data): Marta came in at the door
        # of this public model, so its answers never reach her; the owner's do.
        self.store.tables["ai_model_examples"].append(
            {"id": "x-private", "model_id": JOB, "source": "upload", "private": True, "in_exam": False,
             "content": {"text": "The company's own row"}})
        self.store.tables["ai_model_answers"].append(
            {"id": "a4", "example_id": "x-private", "model_id": JOB, "teacher_id": KASIA, "step": "words",
             "answer": "On the company's row", "counted": True})
        out = self._get(f"/v2/models/{JOB}/download?rows=1").get_json()
        self.assertNotIn("On the company's row", str(out))
        self.who = KASIA
        out = self._get(f"/v2/models/{JOB}/download?rows=1").get_json()
        self.assertIn("On the company's row", str(out))
        for never in ("The company's own row", "An exam answer"):
            self.assertNotIn(never, str(out))
        self.who = BIZ
        self.assertEqual(self._get(f"/v2/models/{JOB}/download").get_json()["refused"],
                         "Only its owner and its teachers can download its data.")

    def test_an_api_answer_needs_the_buyers_authority(self):
        key = self._key()["key"]

        def refuse(*_a, **_k):
            raise ProcessingAuthorizationError("PROCESSING_NOT_ACCEPTED", "Not accepted.", 403)

        from services.processing_authorization import ProcessingAuthorizationService
        with patch.object(ProcessingAuthorizationService, "enforced", True), \
             patch("routes.v2.processing_authorization.resolve_owner_principal",
                   lambda *_a, **_k: SimpleNamespace(id="p1")), \
             patch.object(ProcessingAuthorizationService, "resolve_acquisition_principal",
                          lambda *_a, **_k: "p1"), \
             patch.object(ProcessingAuthorizationService, "require_current", refuse):
            out = self._ask(key)
        self.assertEqual((out.status_code, out.get_json()["code"]), (403, "PROCESSING_NOT_ACCEPTED"))
        self.assertEqual(self.asked, [])


if __name__ == "__main__":
    unittest.main()
