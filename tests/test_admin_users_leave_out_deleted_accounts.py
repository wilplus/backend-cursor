"""
STORY    As the founder, I want a finished deletion gone from the Users list,
         so that the list never shows an emptied account with no email and
         no name.
OUTCOME
  O1  Every auth user whose deleted_at is set is left out of the paged list
      and of the search; one without it stays. A page shortened by a deleted
      account still says there is more, so the list does not end early.
PROVES   O1 -> AdminUsersLeaveOutDeletedAccountsTest::test_a_deleted_account_is_in_neither_the_page_nor_the_search
WHY      N219: a finished deletion is in neither tab. N218: its auth record
         stays, emptied, with deleted_at set.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.db import db
from tests.fakes import FakeSupabaseClient

FOUNDER = "11111111-1111-4111-8111-111111111111"
STAYS = "22222222-2222-4222-8222-222222222222"
DELETED = "33333333-3333-4333-8333-333333333333"
NEXT_PAGE = "44444444-4444-4444-8444-444444444444"

AUTH_USERS = [
    {"user_id": STAYS, "email": "stays@example.com", "deleted_at": None},
    {"user_id": DELETED, "email": None, "name": None,
     "deleted_at": "2026-10-27T10:00:00+00:00"},
    {"user_id": NEXT_PAGE, "email": "next@example.com"},
]


class AdminUsersLeaveOutDeletedAccountsTest(unittest.TestCase):
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
        for p in (patch.object(auth, "verify_supabase_token",
                               lambda t: {"sub": FOUNDER, "email": "founder@example.com"}),
                  patch.object(routes.admin, "is_admin", lambda uid: True),
                  patch.object(db, "client", FakeSupabaseClient({"admin_users": []})),
                  patch.object(db, "v2_list_auth_users",
                               lambda limit=50, offset=0: AUTH_USERS[offset:offset + limit])):
            p.start()
            self.addCleanup(p.stop)

    def _ids(self, query: str) -> tuple[list[str], bool]:
        res = self.client.get(f"/v2/admin/users?{query}", headers={"Authorization": "Bearer t"})
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        return [u["user_id"] for u in body["users"]], body["has_more"]

    def test_a_deleted_account_is_in_neither_the_page_nor_the_search(self):
        self.assertEqual(self._ids("limit=2&offset=0"), ([STAYS], True))
        self.assertEqual(self._ids("limit=2&offset=2"), ([NEXT_PAGE], False))
        self.assertEqual(self._ids(f"search={DELETED}"), ([], False))
        self.assertEqual(self._ids("search=example.com")[0], [STAYS, NEXT_PAGE])


if __name__ == "__main__":
    unittest.main()
