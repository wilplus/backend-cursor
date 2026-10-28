"""
STORY    As the founder, I want "Delete" on the Users list and on a profile to
         delete any account, an old one that never agreed to processing
         included, and to delete again after an Undo, so that the people I
         delete are really deleted.
OUTCOME
  O1  An account with no owner principal is given one and gets the same
      pending seven-day deletion as everyone else; its sign-in record is
      never deleted outright. The person then leaves the Users list.
  O2  Deleting again after a cancel records a new pending deletion, not the
      cancelled one.
PROVES   O1 -> AdminDeleteUserTest::test_an_account_without_a_principal_takes_the_seven_day_road
         O2 -> AdminDeleteUserTest::test_a_delete_after_a_cancel_is_a_new_deletion
WHY      Founder 2026-10-28 (N222): the list's Delete failed with a 500 for an
         account from May; Supabase refuses to delete a sign-in record whose
         Takes are kept as history. "Make Delete really delete".
"""
from __future__ import annotations

import unittest
import uuid
from unittest.mock import patch

import httpx

from services.db import db
from tests.fakes import FakeQuery, FakeSupabaseClient

FOUNDER = "11111111-1111-4111-8111-111111111111"
OLD_ACCOUNT = "5759faf9-6c6f-463d-90db-386d60467c28"
PRINCIPAL = "55555555-5555-4555-8555-555555555555"
AUTH_USERS = [{"user_id": OLD_ACCOUNT, "email": "aaaa@aaa.pl"}]


class _Deletions:
    """The two deletion functions' contract, as the database keeps it: a key
    asked again returns its own request, a live request is returned as it is,
    otherwise a new pending one; a cancel moves pending to cancelled."""

    def __init__(self):
        self.rows: list[dict] = []
        self.principals: list[dict] = []

    def owner_principals(self, query: FakeQuery):
        if query.payload and not self.principals:
            self.principals.append({"id": PRINCIPAL, "user_id": query.payload["user_id"]})
        return list(self.principals)

    def live(self, _query: FakeQuery):
        return [row for row in self.rows if row["state"] in ("pending", "started", "done")]

    def request(self, query: FakeQuery):
        key = query.payload["p_idempotency_key"]
        for row in self.rows:
            if row["idempotency_key"] == key:
                return [row]
        live = self.live(query)
        if live:
            return [live[0]]
        row = {"id": str(uuid.uuid4()), "acquisition_principal_id": PRINCIPAL,
               "state": "pending", "idempotency_key": key,
               "requested_at": "2026-10-28T08:00:00+00:00",
               "completes_after": "2099-11-04T08:00:00+00:00"}
        self.rows.append(row)
        return [row]

    def cancel(self, query: FakeQuery):
        row = next(r for r in self.rows if r["id"] == query.payload["p_request_id"])
        row.update(state="cancelled", cancelled_at="2026-10-28T08:01:00+00:00")
        return [row]


class AdminDeleteUserTest(unittest.TestCase):
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
        self.db = _Deletions()
        supabase = FakeSupabaseClient(
            {"admin_users": [], "owner_principals": self.db.owner_principals,
             "account_deletion_requests": self.db.live},
            rpc_rows={"request_phase1_account_deletion_v1": self.db.request,
                      "cancel_phase1_account_deletion_v1": self.db.cancel})

        def never(*args, **kwargs):
            raise AssertionError("the sign-in record is never deleted outright")

        for p in (patch.object(auth, "verify_supabase_token",
                               lambda t: {"sub": FOUNDER, "email": "founder@example.com"}),
                  patch.object(routes.admin, "is_admin", lambda uid: True),
                  patch.object(db, "client", supabase),
                  patch.object(db, "v2_list_auth_users",
                               lambda limit=50, offset=0: AUTH_USERS[offset:offset + limit]),
                  patch.object(httpx, "delete", never)):
            p.start()
            self.addCleanup(p.stop)

    def _post(self, path: str) -> tuple[int, dict]:
        res = self.client.post(path, headers={"Authorization": "Bearer t"})
        return res.status_code, res.get_json()

    def _listed(self) -> list[str]:
        res = self.client.get("/v2/admin/users", headers={"Authorization": "Bearer t"})
        return [u["user_id"] for u in res.get_json()["users"]]

    def test_an_account_without_a_principal_takes_the_seven_day_road(self):
        self.assertEqual(self._listed(), [OLD_ACCOUNT])
        status, body = self._post(f"/v2/admin/people/{OLD_ACCOUNT}/delete")
        self.assertEqual(status, 202)
        self.assertEqual(body["deletion"]["state"], "pending")
        self.assertTrue(body["deletion"]["cancellable"])
        self.assertEqual(self.db.principals, [{"id": PRINCIPAL, "user_id": OLD_ACCOUNT}])
        self.assertEqual(self._listed(), [])

    def test_a_delete_after_a_cancel_is_a_new_deletion(self):
        _, first = self._post(f"/v2/admin/people/{OLD_ACCOUNT}/delete")
        request_id = first["deletion"]["request_id"]
        status, _ = self._post(f"/v2/admin/people/{OLD_ACCOUNT}/delete/{request_id}/cancel")
        self.assertEqual(status, 200)
        self.assertEqual(self._listed(), [OLD_ACCOUNT])
        status, again = self._post(f"/v2/admin/people/{OLD_ACCOUNT}/delete")
        self.assertEqual(status, 202)
        self.assertEqual(again["deletion"]["state"], "pending")
        self.assertNotEqual(again["deletion"]["request_id"], request_id)
        self.assertEqual(self._listed(), [])


if __name__ == "__main__":
    unittest.main()
