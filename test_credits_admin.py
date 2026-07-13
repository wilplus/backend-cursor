"""Testing-phase credits: config-driven upfront grant (BE-A) + the
password-gated admin endpoints (BE-B), founder 2026-07-13.

Flask/Supabase-dependent → skips locally, runs in CI (the known gotcha).

Run: python3 -m unittest test_credits_admin
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask
    from routes import internal_webhooks as iw
    from services.db import db as real_db
    from config import Config
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    iw = None
    real_db = None
    Config = None
    _IMPORT_ERROR = e


_PW = "test-credit-pw"


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class CreditsAdminEndpointTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(iw.internal_webhooks_bp)
        self.client = self.app.test_client()
        self._set = {}
        self._p = [
            patch.object(iw.config, "CREDIT_ADMIN_PASSWORD", _PW),
            patch.object(iw.db, "v2_get_student_details",
                         lambda uid: {"credits": 7}),
            patch.object(iw.db, "v2_set_student_credits",
                         lambda uid, c: self._set.setdefault(uid, c) or c),
            patch.object(iw.db, "v2_find_user_id_by_email",
                         lambda e: "u-email" if e == "found@x.com" else None),
        ]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _post(self, path, body):
        return self.client.post(path, json=body)

    # ── set ────────────────────────────────────────────────────────────
    def test_set_by_user_id(self):
        r = self._post("/v2/internal/student-credits/set",
                       {"password": _PW, "user_id": "u1", "credits": 25})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["credits"], 25)
        self.assertEqual(self._set["u1"], 25)

    def test_set_by_email_resolves(self):
        r = self._post("/v2/internal/student-credits/set",
                       {"password": _PW, "email": "found@x.com", "credits": 40})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["user_id"], "u-email")

    def test_wrong_password_401(self):
        r = self._post("/v2/internal/student-credits/set",
                       {"password": "nope", "user_id": "u1", "credits": 25})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(self._set, {})

    def test_unknown_email_404(self):
        r = self._post("/v2/internal/student-credits/set",
                       {"password": _PW, "email": "ghost@x.com", "credits": 25})
        self.assertEqual(r.status_code, 404)

    def test_missing_target_400(self):
        r = self._post("/v2/internal/student-credits/set",
                       {"password": _PW, "credits": 25})
        self.assertEqual(r.status_code, 400)

    def test_non_int_credits_400(self):
        r = self._post("/v2/internal/student-credits/set",
                       {"password": _PW, "user_id": "u1", "credits": "lots"})
        self.assertEqual(r.status_code, 400)

    def test_negative_credits_400(self):
        r = self._post("/v2/internal/student-credits/set",
                       {"password": _PW, "user_id": "u1", "credits": -5})
        self.assertEqual(r.status_code, 400)

    def test_disabled_when_no_password_configured_503(self):
        with patch.object(iw.config, "CREDIT_ADMIN_PASSWORD", ""):
            r = self._post("/v2/internal/student-credits/set",
                           {"password": "anything", "user_id": "u1", "credits": 25})
        self.assertEqual(r.status_code, 503)

    # ── lookup ─────────────────────────────────────────────────────────
    def test_lookup_returns_balance(self):
        r = self._post("/v2/internal/student-credits/lookup",
                       {"password": _PW, "user_id": "u1"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["credits"], 7)

    def test_lookup_wrong_password_401(self):
        r = self._post("/v2/internal/student-credits/lookup",
                       {"password": "nope", "user_id": "u1"})
        self.assertEqual(r.status_code, 401)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class UpfrontGrantTests(unittest.TestCase):
    """BE-A — the lazy seed now defaults to config.WILLAB_FREE_CREDIT_GRANT."""

    def test_grant_defaults_to_config_value(self):
        # The empty-user short-circuit returns the resolved grant without any
        # DB call, so this exercises the config default cleanly.
        cls = real_db.__class__
        s = cls.__new__(cls)
        self.assertEqual(
            s.v2_ensure_credits_initialized(""),
            int(Config.WILLAB_FREE_CREDIT_GRANT),
        )

    def test_config_default_is_at_least_25(self):
        self.assertGreaterEqual(int(Config.WILLAB_FREE_CREDIT_GRANT), 25)

    def test_explicit_grant_still_honored(self):
        cls = real_db.__class__
        s = cls.__new__(cls)
        self.assertEqual(s.v2_ensure_credits_initialized("", grant=99), 99)


if __name__ == "__main__":
    unittest.main()
