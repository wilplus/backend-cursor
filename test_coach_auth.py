"""willab coach role — allowlist gate (is_coach / require_admin_or_coach).

BE pre-flight B.5.2 decision: the coach role is an ALLOWLIST (coach_users),
mirroring admin_users / is_admin — NOT a Supabase JWT role claim. These tests
prove:
  * is_coach() authorizes by token email against an active coach_users row;
  * require_admin_or_coach passes when EITHER is_admin or is_coach is true,
    and 403s when neither is (the re-gate model: admins keep access,
    allowlisted coaches gain it).

Run: python3 -m unittest test_coach_auth
"""
from __future__ import annotations

import unittest
from functools import wraps

try:
    from flask import Flask, request, jsonify
    import auth as auth_mod
    from routes import admin as admin_mod
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover - env/bootstrap guard
    Flask = None
    request = None
    jsonify = None
    auth_mod = None
    admin_mod = None
    _IMPORT_ERROR = e


class _FakeResult:
    def __init__(self, rows):
        self.data = rows


class _FakeQuery:
    """Chainable stub for table(...).select(...).eq(...).eq(...).execute()."""

    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def execute(self):
        return _FakeResult(self._rows)


class _FakeClient:
    def __init__(self, table_rows):
        self._table_rows = table_rows  # {table_name: [rows]}

    def table(self, name):
        return _FakeQuery(self._table_rows.get(name, []))


@unittest.skipIf(_IMPORT_ERROR is not None, f"coach auth tests need app deps: {_IMPORT_ERROR}")
class IsCoachTests(unittest.TestCase):
    """is_coach keys on token email against an active coach_users row."""

    def setUp(self):
        self.app = Flask(__name__)
        self._orig_client = admin_mod.db.client

    def tearDown(self):
        admin_mod.db.client = self._orig_client

    def _set_rows(self, rows):
        admin_mod.db.client = _FakeClient({"coach_users": rows})

    def test_active_coach_email_authorized(self):
        self._set_rows([{"id": "c1"}])
        with self.app.test_request_context():
            request.token_payload = {"email": "coach@x.com"}
            self.assertTrue(admin_mod.is_coach("ignored-uid"))

    def test_unlisted_email_denied(self):
        self._set_rows([])  # no active coach row for this email
        with self.app.test_request_context():
            request.token_payload = {"email": "nobody@x.com"}
            self.assertFalse(admin_mod.is_coach("ignored-uid"))

    def test_missing_token_payload_denied(self):
        self._set_rows([{"id": "c1"}])
        with self.app.test_request_context():
            # no token_payload set at all
            self.assertFalse(admin_mod.is_coach("ignored-uid"))

    def test_missing_email_denied(self):
        self._set_rows([{"id": "c1"}])
        with self.app.test_request_context():
            request.token_payload = {}  # authenticated but no email claim
            self.assertFalse(admin_mod.is_coach("ignored-uid"))


@unittest.skipIf(_IMPORT_ERROR is not None, f"coach auth tests need app deps: {_IMPORT_ERROR}")
class RequireAdminOrCoachTests(unittest.TestCase):
    """The OR gate in isolation: admin OR coach → 200; neither → 403.

    The real JWT layer (auth.require_auth) is stubbed to a pass-through so the
    test exercises only the AUTHORIZATION decision, not token decoding.
    """

    def setUp(self):
        # Stub auth.require_auth BEFORE the view is decorated, so the
        # `from auth import require_auth` inside require_admin_or_coach binds
        # the pass-through (sets a fake identity; no real JWT needed).
        self._orig_require_auth = auth_mod.require_auth

        def _passthrough(f):
            @wraps(f)
            def w(*a, **k):
                request.user_id = "u1"
                request.token_payload = {"email": "x@x.com"}
                return f(*a, **k)
            return w

        auth_mod.require_auth = _passthrough
        self._orig_is_admin = admin_mod.is_admin
        self._orig_is_coach = admin_mod.is_coach

    def tearDown(self):
        auth_mod.require_auth = self._orig_require_auth
        admin_mod.is_admin = self._orig_is_admin
        admin_mod.is_coach = self._orig_is_coach

    def _client(self, *, admin: bool, coach: bool):
        admin_mod.is_admin = lambda _uid: admin
        admin_mod.is_coach = lambda _uid: coach
        app = Flask(__name__)

        @app.route("/guarded")
        @admin_mod.require_admin_or_coach
        def guarded():
            return jsonify({"ok": True}), 200

        return app.test_client()

    def test_admin_only_passes(self):
        self.assertEqual(self._client(admin=True, coach=False).get("/guarded").status_code, 200)

    def test_coach_only_passes(self):
        self.assertEqual(self._client(admin=False, coach=True).get("/guarded").status_code, 200)

    def test_both_passes(self):
        self.assertEqual(self._client(admin=True, coach=True).get("/guarded").status_code, 200)

    def test_neither_forbidden(self):
        resp = self._client(admin=False, coach=False).get("/guarded")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json().get("code"), "FORBIDDEN")


if __name__ == "__main__":
    unittest.main()
