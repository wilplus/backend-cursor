"""
STORY    As the founder, I want to see how many visitors without an account
         reach each step from the landing page to their first feedback, so
         that I can fix the step where most of them leave.
OUTCOME
  O1  A visitor reaching a known step counts once, with no account needed
      and nothing kept about them; an unknown step is refused.
  O2  The founder reads the whole path in order, the sign-up screen and the
      accounts made included, in all and per day; nobody else can read it.
PROVES   O1 -> FirstVisitTest::test_a_step_counts_without_an_account
         O2 -> FirstVisitTest::test_the_founder_reads_the_whole_path
WHY      Founder 2026-10-29, N271.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.db import db
from tests.fakes import FakeSupabaseClient

FOUNDER = "11111111-1111-4111-8111-111111111111"


class FirstVisitTest(unittest.TestCase):
    def setUp(self):
        from flask import Flask

        import auth
        import routes.admin
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
        self.supabase = FakeSupabaseClient(rpc_rows={
            "first_visit_counts_v1": [
                {"day": "2026-10-28", "step": "landing", "n": 40},
                {"day": "2026-10-28", "step": "enter", "n": 12},
                {"day": "2026-10-28", "step": "ready", "n": 5},
                {"day": "2026-10-29", "step": "landing", "n": 30},
                {"day": "2026-10-29", "step": "walk", "n": 2},
            ],
            "signup_counts_v1": [
                {"day": "2026-10-29", "step": "seen", "way": None, "n": 4},
                {"day": "2026-10-29", "step": "made", "way": "google", "n": 3},
            ],
        })
        self.admin = True
        for p in (patch.object(auth, "verify_supabase_token",
                               lambda t: {"sub": FOUNDER, "email": "founder@example.com"}),
                  patch.object(routes.admin, "is_admin", lambda uid: self.admin),
                  patch.object(db, "client", self.supabase)):
            p.start()
            self.addCleanup(p.stop)

    def test_a_step_counts_without_an_account(self):
        res = self.client.post("/v2/first-visit/step", json={"step": "agreed"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.supabase.rpcs["first_visit_step_v1"].calls,
                         [("rpc", ("first_visit_step_v1", {"p_step": "agreed"}), {})])

        res = self.client.post("/v2/first-visit/step", json={"step": "anything"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(len(self.supabase.rpcs["first_visit_step_v1"].calls), 1)

    def test_the_founder_reads_the_whole_path(self):
        res = self.client.get("/v2/admin/first-visit-counts?days=7",
                              headers={"Authorization": "Bearer t"})
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["path"], [
            {"step": "landing", "n": 70}, {"step": "enter", "n": 12},
            {"step": "agreed", "n": 0}, {"step": "recording", "n": 0},
            {"step": "recorded", "n": 0}, {"step": "ready", "n": 5},
            {"step": "signup_seen", "n": 4}, {"step": "account_made", "n": 3},
            {"step": "walk", "n": 2},
        ])
        self.assertEqual(body["ways"], {"google": 3})
        self.assertEqual([d["day"] for d in body["days"]], ["2026-10-29", "2026-10-28"])
        self.assertEqual(body["days"][0]["steps"]["signup_seen"], 4)
        self.assertEqual(self.supabase.rpcs["first_visit_counts_v1"].payload["p_since"], body["since"])

        self.admin = False
        res = self.client.get("/v2/admin/first-visit-counts", headers={"Authorization": "Bearer t"})
        self.assertEqual(res.status_code, 403)


if __name__ == "__main__":
    unittest.main()
