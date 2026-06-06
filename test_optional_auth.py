"""Tests for auth.optional_auth — the unsigned-home decorator (design §3).

The Lounge bot / librarian chat must answer without a session: optional_auth
attaches request.user_id when a valid Bearer token is present, and sets it to
None (NEVER 401) when the header is missing or the token is invalid/expired.

Flask harness like the other route tests — runs in CI, skips locally without
flask. Run: python3 -m unittest test_optional_auth
"""
import unittest

try:
    from flask import Flask, request
    import auth
    _IMPORT_ERROR = None
except Exception as import_err:  # pragma: no cover - env/bootstrap guard
    Flask = None
    request = None
    auth = None
    _IMPORT_ERROR = import_err


@unittest.skipIf(
    _IMPORT_ERROR is not None,
    f"optional_auth tests require flask: {_IMPORT_ERROR}",
)
class OptionalAuthTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self._orig_verify = auth.verify_supabase_token

    def tearDown(self):
        auth.verify_supabase_token = self._orig_verify

    def _run(self, headers):
        @auth.optional_auth
        def handler():
            return request.user_id, getattr(request, "token_payload", None)
        with self.app.test_request_context("/x", method="POST", headers=headers):
            return handler()

    def test_no_header_is_anonymous(self):
        uid, payload = self._run({})
        self.assertIsNone(uid)
        self.assertIsNone(payload)

    def test_valid_token_attaches_user(self):
        auth.verify_supabase_token = lambda t: {"sub": "user-123", "x": 1}
        uid, payload = self._run({"Authorization": "Bearer good"})
        self.assertEqual(uid, "user-123")
        self.assertEqual(payload, {"sub": "user-123", "x": 1})

    def test_invalid_token_is_anonymous_not_401(self):
        def boom(_t):
            raise Exception("expired")
        auth.verify_supabase_token = boom
        uid, payload = self._run({"Authorization": "Bearer bad"})
        # Lapsed/invalid token degrades to anonymous — chat still works.
        self.assertIsNone(uid)
        self.assertIsNone(payload)

    def test_non_bearer_header_is_anonymous(self):
        uid, _ = self._run({"Authorization": "Basic abc"})
        self.assertIsNone(uid)

    def test_empty_bearer_is_anonymous(self):
        uid, _ = self._run({"Authorization": "Bearer "})
        self.assertIsNone(uid)


if __name__ == "__main__":
    unittest.main()
