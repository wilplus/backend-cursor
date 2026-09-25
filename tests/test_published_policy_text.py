"""The published Terms and Privacy Policy are readable by anyone.

FOUNDER 2026-09-25, decisions 2 and 3. /privacy and /terms read their copy
through the owner-bound status call: a visitor neither signed in nor holding
a guest token was refused, so /privacy said it could not load and /terms
showed the retired v1.2 text. Pinned here:

  * the service returns the exact stored bytes of the one policy in force —
    the selection get_phase1_processing_authorization_v1 makes — and nothing
    for a policy not yet activated, already retired, or unreadable;
  * the route resolves no owner at all, answers 404 when nothing is in force,
    and may be cached for five minutes;
  * a sign-up records the Terms version it was shown, not the constant "1.2".

Run: python3 -m unittest tests.test_published_policy_text
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from services import processing_authorization as pa

try:
    from flask import Flask
    from routes import auth as auth_routes
    from routes.v2 import processing_authorization as pa_routes
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


def _service(rows):
    database = type("Db", (), {"client": _Client(rows)})()
    return pa.ProcessingAuthorizationService(database, mode="off")


class PublishedPolicyTextServiceTests(unittest.TestCase):

    def test_the_policy_in_force_is_returned_byte_for_byte(self):
        service = _service([_policy()])
        self.assertEqual(service.published_policy_text(), {
            "policy_version": "phase1-2026-09-23",
            "terms": {"version": "3.1", "copy": "TERMS BYTES", "sha256": "a" * 64},
            "privacy": {"version": "3.1", "copy": "PRIVACY BYTES", "sha256": "b" * 64},
        })
        self.assertEqual(service.client.filters, [("status", "active")])
        self.assertEqual(service.client.selected[0], "processing_policy_versions")

    def test_a_policy_not_yet_activated_is_not_in_force(self):
        later = (NOW + timedelta(hours=1)).isoformat()
        self.assertIsNone(_service([_policy(activated_at=later)]).published_policy_text())

    def test_a_retired_policy_is_not_in_force(self):
        earlier = (NOW - timedelta(hours=1)).isoformat()
        self.assertIsNone(_service([_policy(retired_at=earlier)]).published_policy_text())

    def test_a_retirement_still_ahead_leaves_it_in_force(self):
        later = (NOW + timedelta(days=3)).isoformat()
        self.assertIsNotNone(_service([_policy(retired_at=later)]).published_policy_text())

    def test_nothing_active_or_an_unreadable_record_is_none(self):
        self.assertIsNone(_service([]).published_policy_text())
        self.assertIsNone(_service(RuntimeError("down")).published_policy_text())
        self.assertIsNone(_service([_policy(activated_at="not a time")]).published_policy_text())


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

    def test_nothing_in_force_is_a_404(self):
        response, status = self._get([])
        self.assertEqual(status, 404)
        self.assertEqual(response.get_json()["code"], "PROCESSING_POLICY_INACTIVE")

    def test_the_route_carries_no_auth_decorator(self):
        # optional_auth/require_auth wrap the view; this one must not be wrapped.
        self.assertIsNone(getattr(pa_routes.v2_processing_policy_text, "__wrapped__", None))


@unittest.skipIf(_IMPORT_ERROR is not None, f"flask app unavailable: {_IMPORT_ERROR}")
class SignupTermsVersionTests(unittest.TestCase):

    def setUp(self):
        self._orig_client = db.client

    def tearDown(self):
        db.client = self._orig_client

    def test_a_signup_records_the_terms_version_it_was_shown(self):
        db.client = _Client([_policy(terms_version="3.1")])
        self.assertEqual(auth_routes._signup_terms_version(), "3.1")

    def test_with_no_policy_in_force_it_falls_back_to_the_constant(self):
        db.client = _Client([])
        self.assertEqual(auth_routes._signup_terms_version(),
                         auth_routes.CURRENT_TERMS_VERSION)
        db.client = _Client(RuntimeError("down"))
        self.assertEqual(auth_routes._signup_terms_version(),
                         auth_routes.CURRENT_TERMS_VERSION)

    def test_both_signup_writes_use_the_resolved_version(self):
        import inspect
        source = inspect.getsource(auth_routes.signup)
        self.assertIn('user_metadata["terms_version"] = terms_version', source)
        self.assertIn("terms_version=terms_version,", source)
        self.assertNotIn("terms_version=CURRENT_TERMS_VERSION", source)


if __name__ == "__main__":
    unittest.main()
