"""
STORY    As a new speaker who recorded a Take as a guest and then signed up,
         I want my Take to arrive in my account even when the page reloaded
         before it heard back from the first claim, so that my chat is not
         empty as if I had never recorded.
OUTCOME
  O1  The same account presenting the same guest token again, after its
      first claim landed, is answered (200) from the claim function.
  O2  Another account presenting that token is still refused.
PROVES   O1 -> test_a_repeated_claim_by_the_same_account_is_answered
         O2 -> test_another_account_is_still_refused
WHY      Founder 2026-10-20: "after I sign up ... it shows me a button like
         my take was not registered; particularly the new users".
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.project_ownership import issue_guest_owner
from services.project_repository import ProjectOwnershipError

USER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


class FakeRepository:
    """The guest principal after a new account's claim: the account's own,
    its secret erased. The claim function answers only its own replay."""

    def __init__(self, principal_id: str, secret_hash: str):
        self.row = {"id": principal_id, "user_id": USER, "guest_secret_hash": None,
                    "claimed_by_owner_principal_id": None}
        self.secret_hash = secret_hash

    def __call__(self, _db):
        return self

    def get_principal(self, principal_id):
        return dict(self.row) if principal_id == self.row["id"] else None

    def claim_guest(self, principal_id, secret_hash, user_id):
        if principal_id == self.row["id"] and secret_hash == self.secret_hash and user_id == USER:
            return dict(self.row)
        raise ProjectOwnershipError("guest owner claim rejected")


class RepeatedClaim(unittest.TestCase):
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

        self.issued = issue_guest_owner()
        self.who = USER
        for p in (
            patch.object(auth, "verify_supabase_token", lambda _t: {"sub": self.who}),
            patch("routes.v2.projects.ProjectRepository",
                  FakeRepository(self.issued.principal_id, self.issued.secret_hash)),
        ):
            p.start()
            self.addCleanup(p.stop)

    def claim(self):
        from services.project_ownership import GUEST_OWNER_HEADER

        return self.client.post("/v2/projects/claim", headers={
            "Authorization": "Bearer t", GUEST_OWNER_HEADER: self.issued.token})

    def test_a_repeated_claim_by_the_same_account_is_answered(self):
        response = self.claim()
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()["claimed"])

    def test_another_account_is_still_refused(self):
        self.who = OTHER
        self.assertNotEqual(self.claim().status_code, 200)
