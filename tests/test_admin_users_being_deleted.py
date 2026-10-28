"""
STORY    As the founder, I want a person whose account is being deleted to
         leave the Users list at once, though their data is deleted only
         after seven days, so that the list shows only the people who are
         still here.
OUTCOME
  O1  The list leaves out everyone whose account is being deleted, whether
      the founder deleted it or the person did, and the next page starts
      where this one ended. A finished deletion is left out too.
PROVES   O1 -> AdminUsersBeingDeletedTest::test_the_list_leaves_out_who_is_being_deleted
WHY      Founder 2026-10-27 (N219; N221 drops the "Being deleted" view).
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.db import db
from tests.fakes import FakeSupabaseClient

FOUNDER = "11111111-1111-4111-8111-111111111111"
STAYS = "22222222-2222-4222-8222-222222222222"
DELETED_BY_FOUNDER = "33333333-3333-4333-8333-333333333333"
DELETED_THEMSELVES = "44444444-4444-4444-8444-444444444444"
THEIR_PRINCIPAL = "55555555-5555-4555-8555-555555555555"
GONE = "77777777-7777-4777-8777-777777777777"

AUTH_USERS = [
    {"user_id": STAYS, "email": "stays@example.com"},
    {"user_id": DELETED_BY_FOUNDER, "email": "founder-deleted@example.com"},
    {"user_id": DELETED_THEMSELVES, "email": "self-deleted@example.com"},
    {"user_id": GONE, "email": None},
]


class AdminUsersBeingDeletedTest(unittest.TestCase):
    def setUp(self):
        from flask import Flask

        import auth
        import routes.admin
        from routes.v2 import register_domains
        from routes.v2.blueprint import v2_bp

        register_domains()
        app = Flask(__name__)
        app.register_blueprint(v2_bp, url_prefix="/v2")
        self.client = app.test_client()
        supabase = FakeSupabaseClient({
            "account_deletion_requests": [
                {"id": "req-a", "acquisition_principal_id": "66666666-6666-4666-8666-666666666666",
                 "state": "pending", "requested_at": "2026-10-27T10:00:00+00:00",
                 "completes_after": "2099-11-03T10:00:00+00:00",
                 "idempotency_key": f"admin-delete:{DELETED_BY_FOUNDER}:3f2a9c1b7e04"},
                {"id": "req-b", "acquisition_principal_id": THEIR_PRINCIPAL,
                 "state": "pending", "requested_at": "2026-10-26T09:00:00+00:00",
                 "completes_after": "2099-11-02T09:00:00+00:00",
                 "idempotency_key": "speaker-own-request"},
                {"id": "req-c", "acquisition_principal_id": "88888888-8888-4888-8888-888888888888",
                 "state": "done", "requested_at": "2026-10-01T09:00:00+00:00",
                 "completes_after": "2026-10-08T09:00:00+00:00",
                 "idempotency_key": f"admin-delete:{GONE}"},
            ],
            "owner_principals": [{"id": THEIR_PRINCIPAL, "user_id": DELETED_THEMSELVES}],
            "admin_users": [],
        })
        for p in (patch.object(auth, "verify_supabase_token",
                               lambda t: {"sub": FOUNDER, "email": "founder@example.com"}),
                  patch.object(routes.admin, "is_admin", lambda uid: True),
                  patch.object(db, "client", supabase),
                  patch.object(db, "v2_list_auth_users",
                               lambda limit=50, offset=0: AUTH_USERS[offset:offset + limit])):
            p.start()
            self.addCleanup(p.stop)

    def _get(self, query: str) -> dict:
        res = self.client.get(f"/v2/admin/users?{query}", headers={"Authorization": "Bearer t"})
        self.assertEqual(res.status_code, 200)
        return res.get_json()

    def test_the_list_leaves_out_who_is_being_deleted(self):
        body = self._get("limit=4&offset=0")
        self.assertEqual([u["user_id"] for u in body["users"]], [STAYS])
        self.assertEqual(body["next_offset"], 4)
        self.assertTrue(body["has_more"])


if __name__ == "__main__":
    unittest.main()
