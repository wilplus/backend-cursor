"""
STORY    As the founder, I want to know how many people open the sign-up
         screen and how many make an account, by way, so that I can decide
         on signing up with WhatsApp from real numbers.
OUTCOME
  O1  Opening the sign-up screen counts once, with no account needed and
      nothing kept about the person.
  O2  The founder reads, per day and in all, how many opened the screen and
      how many made an account, by way; nobody else can read it.
PROVES   O1 -> SignupCountTest::test_opening_the_screen_counts_without_an_account
         O2 -> SignupCountTest::test_the_founder_reads_seen_and_made_by_way
WHY      Founder 2026-10-26, N207 item 6 (N174 item 6).
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.db import db
from tests.fakes import FakeSupabaseClient

FOUNDER = "11111111-1111-4111-8111-111111111111"


class SignupCountTest(unittest.TestCase):
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
        self.supabase = FakeSupabaseClient(rpc_rows={"signup_counts_v1": [
            {"day": "2026-10-26", "step": "seen", "way": None, "n": 9},
            {"day": "2026-10-26", "step": "made", "way": "email", "n": 1},
            {"day": "2026-10-26", "step": "made", "way": "google", "n": 2},
            {"day": "2026-10-25", "step": "seen", "way": None, "n": 4},
            {"day": "2026-10-25", "step": "made", "way": "linkedin_oidc", "n": 1},
        ]})
        self.admin = True
        for p in (patch.object(auth, "verify_supabase_token",
                               lambda t: {"sub": FOUNDER, "email": "founder@example.com"}),
                  patch.object(routes.admin, "is_admin", lambda uid: self.admin),
                  patch.object(db, "client", self.supabase)):
            p.start()
            self.addCleanup(p.stop)

    def test_opening_the_screen_counts_without_an_account(self):
        res = self.client.post("/v2/signup/seen")
        self.assertEqual(res.status_code, 200)
        calls = self.supabase.rpcs["signup_screen_seen_v1"].calls
        self.assertEqual(calls, [("rpc", ("signup_screen_seen_v1", {}), {})])

    def test_the_founder_reads_seen_and_made_by_way(self):
        res = self.client.get("/v2/admin/signup-counts?days=7",
                              headers={"Authorization": "Bearer t"})
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["total"], {"seen": 13, "made": 4,
                                         "ways": {"email": 1, "google": 2, "linkedin_oidc": 1}})
        self.assertEqual([d["day"] for d in body["days"]], ["2026-10-26", "2026-10-25"])
        self.assertEqual(body["days"][0]["seen"], 9)
        self.assertEqual(self.supabase.rpcs["signup_counts_v1"].payload["p_since"], body["since"])

        self.admin = False
        res = self.client.get("/v2/admin/signup-counts", headers={"Authorization": "Bearer t"})
        self.assertEqual(res.status_code, 403)


if __name__ == "__main__":
    unittest.main()
