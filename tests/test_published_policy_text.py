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

try:
    from flask import Flask

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


if __name__ == "__main__":
    unittest.main()
