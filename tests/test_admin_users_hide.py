"""
STORY    As the founder, I want to hide people from the Users list, and undo
         it, so that the list shows only the people I still need, without
         touching anyone's account.
OUTCOME
  O1  A person I hide leaves the list at once, in the page and in the
      search; Undo brings them back.
  O2  Hiding changes only the list: no deletion is recorded and nothing is
      asked of the person's sign-in.
PROVES   O1 -> AdminUsersHideTest::test_a_hidden_person_leaves_the_list_until_undo
         O2 -> AdminUsersHideTest::test_hiding_touches_no_account
WHY      Founder 2026-10-27 (N221): "Just hide them cause they are deleted
         through other workflow inside the app".
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from services.db import db
from tests.fakes import FakeQuery, FakeSupabaseClient

FOUNDER = "11111111-1111-4111-8111-111111111111"
STAYS = "22222222-2222-4222-8222-222222222222"
HIDDEN = "33333333-3333-4333-8333-333333333333"

AUTH_USERS = [
    {"user_id": STAYS, "email": "stays@example.com"},
    {"user_id": HIDDEN, "email": "hide-me@example.com"},
]


def _account_rows(flags: dict[str, bool]):
    """v2_student_details as a tiny table: a write sets a person's flag, a
    read returns the people whose flag is on."""
    seen = 0

    def run(query: FakeQuery):
        nonlocal seen
        calls, seen = query.calls[seen:], len(query.calls)
        for name, args, _ in calls:
            if name == "upsert":
                flags[args[0]["user_id"]] = args[0]["is_archived"]
            if name == "update":
                user = next(a[1] for n, a, _ in calls if n == "eq" and a[0] == "user_id")
                flags[user] = args[0]["is_archived"]
        return [{"user_id": user} for user, on in flags.items() if on]

    return run


class AdminUsersHideTest(unittest.TestCase):
    def setUp(self):
        from flask import Flask

        import auth
        import routes.admin
        from routes.v2 import register_domains
        from routes.v2.blueprint import v2_bp
        from routes.v2.people import people_bp

        register_domains()
        app = Flask(__name__)
        app.register_blueprint(v2_bp, url_prefix="/v2")
        app.register_blueprint(people_bp)
        self.client = app.test_client()
        self.supabase = FakeSupabaseClient({
            "admin_users": [],
            "v2_student_details": _account_rows({}),
        })
        for p in (patch.object(auth, "verify_supabase_token",
                               lambda t: {"sub": FOUNDER, "email": "founder@example.com"}),
                  patch.object(routes.admin, "is_admin", lambda uid: True),
                  patch.object(db, "client", self.supabase),
                  patch.object(db, "v2_list_auth_users",
                               lambda limit=50, offset=0: AUTH_USERS[offset:offset + limit])):
            p.start()
            self.addCleanup(p.stop)

    def _send(self, method: str, user_id: str) -> int:
        res = self.client.open(f"/v2/admin/people/{user_id}/hidden", method=method,
                               headers={"Authorization": "Bearer t"})
        return res.status_code

    def _ids(self, query: str = "") -> list[str]:
        res = self.client.get(f"/v2/admin/users?{query}", headers={"Authorization": "Bearer t"})
        self.assertEqual(res.status_code, 200)
        return [u["user_id"] for u in res.get_json()["users"]]

    def test_a_hidden_person_leaves_the_list_until_undo(self):
        self.assertEqual(self._ids(), [STAYS, HIDDEN])
        self.assertEqual(self._send("PUT", HIDDEN), 200)
        self.assertEqual(self._ids(), [STAYS])
        self.assertEqual(self._ids("search=hide-me"), [])
        self.assertEqual(self._send("DELETE", HIDDEN), 200)
        self.assertEqual(self._ids(), [STAYS, HIDDEN])

    def test_hiding_touches_no_account(self):
        def no_sign_in_call(*args, **kwargs):
            raise AssertionError("hiding must not call the sign-in service")

        with patch.object(httpx, "delete", no_sign_in_call), \
             patch.object(httpx, "put", no_sign_in_call):
            self.assertEqual(self._send("PUT", HIDDEN), 200)
        self.assertEqual(self.supabase.rpcs, {})
        self.assertEqual(set(self.supabase.tables), {"v2_student_details"})


if __name__ == "__main__":
    unittest.main()
