"""
STORY    As a visitor, I want to read the Terms and Privacy Policy without
         signing in, and my sign-up to record the Terms version I was shown,
         so that I see what I agree to and the record says what I agreed to
         (consent).
OUTCOME
  O1  Anyone, with no owner resolved, gets the exact stored text of the one
      policy in force, cacheable for five minutes.
  O2  A policy not yet activated, already retired, or unreadable is never
      served: 404 PROCESSING_POLICY_INACTIVE.
  O3  A sign-up records the Terms version of the policy in force, not the
      old constant; a sign-up without the tick creates no account.
PROVES   O1 -> test_anyone_reads_the_published_copy_and_it_may_be_cached
         O2 -> test_nothing_is_served_when_no_policy_is_in_force
         O3 -> test_a_sign_up_records_the_terms_version_it_was_shown
WHY      Founder 2026-09-25, decisions 2 and 3: /privacy could not load for
         a visitor and /terms showed the retired v1.2 text.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

try:
    from flask import Flask

    from routes import auth as auth_routes
    from routes.v2 import processing_authorization as pa_routes
    from services import rings
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    _IMPORT_ERROR = e

NOW = datetime.now(timezone.utc)


def _policy(**over):
    row = {
        "version": "phase1-2026-09-23",
        "terms_version": "3.1", "terms_copy": "TERMS BYTES",
        "terms_copy_sha256": "a" * 64,
        "privacy_version": "3.1", "privacy_copy": "PRIVACY BYTES",
        "privacy_copy_sha256": "b" * 64,
        "activated_at": (NOW - timedelta(days=1)).isoformat(),
        "retired_at": None,
    }
    row.update(over)
    return row


class _Query:
    def __init__(self, client, relation):
        self.client, self.relation = client, relation

    def select(self, columns):
        self.client.selected = (self.relation, columns)
        return self

    def eq(self, column, value):
        self.client.filters.append((column, value))
        return self

    def limit(self, _count):
        return self

    def execute(self):
        if isinstance(self.client.rows, Exception):
            raise self.client.rows
        return type("Result", (), {"data": self.client.rows})()


class _Client:
    def __init__(self, rows):
        self.rows = rows
        self.selected = None
        self.filters: list = []

    def table(self, relation):
        return _Query(self, relation)


@unittest.skipIf(_IMPORT_ERROR is not None, f"flask app unavailable: {_IMPORT_ERROR}")
class PublishedPolicyTextRouteTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self._orig_client = db.client
        self._orig_principal = pa_routes._principal_id

        def _no_owner():
            raise AssertionError("the public policy read resolved an owner")

        pa_routes._principal_id = _no_owner

    def tearDown(self):
        db.client = self._orig_client
        pa_routes._principal_id = self._orig_principal

    def _get(self, rows):
        db.client = _Client(rows)
        with self.app.test_request_context(method="GET"):
            return pa_routes.v2_processing_policy_text()

    def test_anyone_reads_the_published_copy_and_it_may_be_cached(self):
        response, status = self._get([_policy()])
        self.assertEqual(status, 200)
        self.assertEqual(response.get_json()["privacy"]["copy"], "PRIVACY BYTES")
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=300")

    def test_nothing_is_served_when_no_policy_is_in_force(self):
        cases = {
            "not yet active": [_policy(
                activated_at=(NOW + timedelta(days=1)).isoformat())],
            "retired": [_policy(
                retired_at=(NOW - timedelta(minutes=1)).isoformat())],
            "none active": [],
            "unreadable": RuntimeError("database unreachable"),
        }
        for case, rows in cases.items():
            with self.subTest(case):
                response, status = self._get(rows)
                self.assertEqual(status, 404)
                self.assertEqual(response.get_json()["code"],
                                 "PROCESSING_POLICY_INACTIVE")

    def test_a_sign_up_records_the_terms_version_it_was_shown(self):
        created, consents = [], []
        auth = SimpleNamespace(
            admin=SimpleNamespace(create_user=lambda body: created.append(body)
                                  or SimpleNamespace(user=SimpleNamespace(id="user-1"))),
            sign_in_with_password=lambda _body: SimpleNamespace(session=None))
        originals = (auth_routes.new_client, db.record_user_consent,
                     rings.record_signup_from_request)
        auth_routes.new_client = lambda: SimpleNamespace(auth=auth)
        db.record_user_consent = lambda **kw: consents.append(kw) or {"id": "c"}
        rings.record_signup_from_request = lambda *_a: None
        db.client = _Client([_policy()])
        try:
            def sign_up(ticked):
                with self.app.test_request_context(
                        method="POST", json={"email": "a@b.co", "password": "secret1",
                                             "terms_accepted": ticked}):
                    return auth_routes.signup()

            _response, status = sign_up(False)
            self.assertEqual(status, 400)
            self.assertEqual((created, consents), ([], []))

            _response, status = sign_up(True)
            self.assertEqual(status, 201)
            self.assertEqual(created[0]["user_metadata"]["terms_version"], "3.1")
            self.assertEqual(consents[0]["terms_version"], "3.1")
        finally:
            (auth_routes.new_client, db.record_user_consent,
             rings.record_signup_from_request) = originals


if __name__ == "__main__":
    unittest.main()
