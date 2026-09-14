"""Tests for GET/PUT /v2/user/consent.

The unified consent endpoint that surfaces four prompted moments
(mic / share / email / terms). Three are runtime preferences on
user_settings; the fourth reads the immutable user_consents
ledger against Config.CURRENT_TERMS_VERSION.

Test surface:
  * GET when nothing has been set — all flags null,
    has_answered=False, terms_consent=False
  * PUT partial (only mic) — share/email stay null, the
    set_at column is stamped
  * PUT all three runtime flags + accepting terms — full
    round-trip echo, has_answered=True, terms ledger row
    inserted
  * Terms validation — only `true` is accepted; false/null
    are rejected with 400 because the ledger is append-only
  * Idempotency — accepting terms when a row already exists
    for the current version does not write a duplicate
  * Clear semantics — null on a runtime flag wipes the
    column and the corresponding set_at
"""
import unittest

try:
    from flask import Flask
    from routes.v2 import user_account as v2_user_account
    from services.db import db
    from flask import request
    _IMPORT_ERROR = None
except Exception as import_err:  # pragma: no cover - env/bootstrap guard
    Flask = None
    _IMPORT_ERROR = import_err


_TERMS_VERSION = "test-1.0"


@unittest.skipIf(
    _IMPORT_ERROR is not None,
    f"consent tests require full app deps: {_IMPORT_ERROR}",
)
class ConsentEndpointTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.user_id = "user-consent-1"

        # In-memory user_settings row stand-in. The endpoint reads
        # this through get_user_consent_state's call to
        # get_user_settings, and writes through
        # set_user_consent_preferences.
        self.user_settings: dict = {}
        # In-memory user_consents ledger keyed by version.
        # record_user_consent appends; we treat dupes as no-ops.
        self.ledger: list[dict] = []

        self.originals = {}
        self._patch_config("CURRENT_TERMS_VERSION", _TERMS_VERSION)
        self._patch_db("get_user_settings", self._fake_get_user_settings)
        self._patch_db(
            "set_user_consent_preferences",
            self._fake_set_user_consent_preferences,
        )
        self._patch_db(
            "get_user_consent_state",
            self._fake_get_user_consent_state,
        )
        self._patch_db("record_user_consent", self._fake_record_user_consent)

    def tearDown(self):
        for target, attr, original in reversed(self.originals.values()):
            setattr(target, attr, original)

    # ── patching plumbing (mirrors test_admin_coach_approval style) ──

    def _patch_db(self, attr, replacement):
        key = f"db:{attr}"
        self.originals[key] = (db, attr, getattr(db, attr))
        setattr(db, attr, replacement)

    def _patch_config(self, attr, replacement):
        # /v2/user/consent lives in routes.v2.user_account (god-file split),
        # which holds its own Config instance — setattr on v2.config would
        # not reach it.
        from routes.v2 import user_account as ua
        key = f"config:{attr}"
        self.originals[key] = (ua.config, attr, getattr(ua.config, attr, None))
        setattr(ua.config, attr, replacement)

    # ── in-memory fakes ──────────────────────────────────────────────

    def _fake_get_user_settings(self, user_id):
        if user_id != self.user_id:
            return None
        return dict(self.user_settings) if self.user_settings else None

    def _fake_set_user_consent_preferences(
        self,
        user_id,
        *,
        mic=None,
        share=None,
        email=None,
        update_mic=False,
        update_share=False,
        update_email=False,
    ):
        if user_id != self.user_id:
            return False
        if not (update_mic or update_share or update_email):
            return True
        # Simulate the real upsert: stamp set_at iff value is non-None.
        now = "2026-05-19T12:00:00+00:00"
        if update_mic:
            self.user_settings["mic_consent_preference"] = mic
            self.user_settings["mic_consent_set_at"] = (
                now if mic is not None else None
            )
        if update_share:
            self.user_settings["share_consent_preference"] = share
            self.user_settings["share_consent_set_at"] = (
                now if share is not None else None
            )
        if update_email:
            self.user_settings["email_consent_preference"] = email
            self.user_settings["email_consent_set_at"] = (
                now if email is not None else None
            )
        return True

    def _fake_record_user_consent(
        self,
        user_id,
        terms_version="1.0",
        ip_address=None,
        user_agent=None,
    ):
        # Idempotent like the real upsert with on_conflict.
        existing = [
            r for r in self.ledger
            if r["user_id"] == user_id and r["terms_version"] == terms_version
        ]
        if existing:
            return existing[0]
        row = {
            "user_id": user_id,
            "terms_version": terms_version,
            "terms_accepted_at": "2026-05-19T12:00:00+00:00",
            "ip_address": ip_address,
            "user_agent": user_agent,
        }
        self.ledger.append(row)
        return row

    def _fake_get_user_consent_state(self, user_id, *, current_terms_version):
        """Mirrors the real DB helper's shape so we exercise the
        route's serialisation path against realistic data."""
        settings = self.user_settings or {}
        terms_row = next(
            (
                r for r in self.ledger
                if r["user_id"] == user_id
                and r["terms_version"] == current_terms_version
            ),
            None,
        )
        mic = settings.get("mic_consent_preference")
        share = settings.get("share_consent_preference")
        email = settings.get("email_consent_preference")
        terms_consent = bool(terms_row)
        return {
            "has_answered": (
                mic is not None
                or share is not None
                or email is not None
                or terms_consent
            ),
            "mic_consent": mic,
            "mic_consent_set_at": settings.get("mic_consent_set_at"),
            "share_consent": share,
            "share_consent_set_at": settings.get("share_consent_set_at"),
            "email_consent": email,
            "email_consent_set_at": settings.get("email_consent_set_at"),
            "terms_consent": terms_consent,
            "terms_version_current": current_terms_version,
            "terms_version_accepted": (
                terms_row.get("terms_version") if terms_row else None
            ),
            "terms_accepted_at": (
                terms_row.get("terms_accepted_at") if terms_row else None
            ),
        }

    # ── route invocation helpers (auth-decorator-aware) ──────────────

    def _invoke(self, method, json_body=None):
        ctx = self.app.test_request_context(
            "/v2/user/consent",
            method=method,
            json=json_body,
        )
        with ctx:
            request.user_id = self.user_id
            response, status = v2_user_account.v2_user_consent.__wrapped__()
            return status, response.get_json()

    # ── tests ────────────────────────────────────────────────────────

    def test_get_when_nothing_set_returns_all_nulls(self):
        """Cold-start user: every flag NULL, has_answered False,
        terms_version_accepted None. Frontend uses this to know
        to surface every prompt."""
        status, payload = self._invoke("GET")
        self.assertEqual(status, 200)
        self.assertFalse(payload["has_answered"])
        self.assertIsNone(payload["mic_consent"])
        self.assertIsNone(payload["share_consent"])
        self.assertIsNone(payload["email_consent"])
        self.assertFalse(payload["terms_consent"])
        self.assertEqual(payload["terms_version_current"], _TERMS_VERSION)
        self.assertIsNone(payload["terms_version_accepted"])
        self.assertIsNone(payload["terms_accepted_at"])

    def test_put_partial_mic_only_leaves_others_null(self):
        """PUT {mic_consent: true} touches mic, leaves share+email
        NULL. has_answered flips True because mic is now set."""
        status, payload = self._invoke("PUT", {"mic_consent": True})
        self.assertEqual(status, 200)
        self.assertTrue(payload["has_answered"])
        self.assertTrue(payload["mic_consent"])
        self.assertIsNotNone(payload["mic_consent_set_at"])
        self.assertIsNone(payload["share_consent"])
        self.assertIsNone(payload["email_consent"])
        self.assertFalse(payload["terms_consent"])

    def test_put_all_three_plus_terms_records_ledger(self):
        """Full first-time submission: three prefs land + a ledger
        row is appended at the current terms_version."""
        status, payload = self._invoke("PUT", {
            "mic_consent": True,
            "share_consent": False,
            "email_consent": True,
            "terms_consent": True,
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["has_answered"])
        self.assertTrue(payload["mic_consent"])
        self.assertFalse(payload["share_consent"])
        self.assertTrue(payload["email_consent"])
        self.assertTrue(payload["terms_consent"])
        self.assertEqual(payload["terms_version_accepted"], _TERMS_VERSION)
        # Exactly one ledger row was written.
        self.assertEqual(len(self.ledger), 1)
        self.assertEqual(self.ledger[0]["terms_version"], _TERMS_VERSION)

    def test_put_terms_consent_false_is_rejected(self):
        """Terms ledger is append-only: false is not a valid value."""
        status, payload = self._invoke("PUT", {"terms_consent": False})
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "INVALID_INPUT")
        self.assertEqual(len(self.ledger), 0)

    def test_put_terms_consent_null_is_rejected(self):
        """Same as above but with null — the endpoint doesn't pretend
        you can clear an audit record."""
        status, payload = self._invoke("PUT", {"terms_consent": None})
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "INVALID_INPUT")
        self.assertEqual(len(self.ledger), 0)

    def test_put_terms_consent_true_is_idempotent(self):
        """Accepting twice at the same version writes one row only
        (the underlying upsert uses on_conflict=do_nothing)."""
        self._invoke("PUT", {"terms_consent": True})
        status, payload = self._invoke("PUT", {"terms_consent": True})
        self.assertEqual(status, 200)
        self.assertEqual(len(self.ledger), 1)
        self.assertTrue(payload["terms_consent"])

    def test_put_null_on_runtime_flag_clears_it(self):
        """First set mic to True, then PUT mic_consent=null and
        verify both the column AND set_at are NULL again. Lets the
        frontend re-prompt by detecting NULL state."""
        self._invoke("PUT", {"mic_consent": True})
        status, payload = self._invoke("PUT", {"mic_consent": None})
        self.assertEqual(status, 200)
        self.assertIsNone(payload["mic_consent"])
        self.assertIsNone(payload["mic_consent_set_at"])
        # has_answered now depends only on terms / other flags. None
        # set yet → False.
        self.assertFalse(payload["has_answered"])

    def test_put_invalid_type_rejected(self):
        """A string where a bool is expected returns 400 with the
        offending field name in the error message."""
        status, payload = self._invoke("PUT", {"mic_consent": "yes"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "INVALID_INPUT")
        self.assertIn("mic_consent", payload["error"])

    def test_put_unknown_keys_are_ignored(self):
        """Extra keys in the body are silently dropped (PATCH-style),
        not rejected. Frontend can ship a payload with future fields
        without breaking older backend deploys."""
        status, payload = self._invoke("PUT", {
            "mic_consent": True,
            "future_consent_flag_v2": True,  # unknown — should be ignored
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["mic_consent"])
        # Sanity: nothing called future_consent_flag_v2 landed.
        self.assertNotIn("future_consent_flag_v2", payload)

    def test_put_empty_body_is_a_clean_read_back(self):
        """An empty PUT body skips writes entirely and just returns
        current state — useful for the frontend to refresh after an
        out-of-band consent change."""
        self._invoke("PUT", {"mic_consent": True})
        status, payload = self._invoke("PUT", {})
        self.assertEqual(status, 200)
        self.assertTrue(payload["mic_consent"])

# ── merged from tests/test_mlc2_consent_endpoint.py (audit Q-T9) ──

try:
    from flask import Flask
    from routes.v2 import mlc2_consent as v2_mlc2_consent
    from flask import request
    from routes.v2 import mlc2_consent as route
    _IMPORT_ERROR = None
except Exception as import_error:  # pragma: no cover
    Flask = None
    route = None
    _IMPORT_ERROR = import_error


STATUS = {
    "configured": True,
    "granted": False,
    "speaker_bound": False,
    "consent_policy_version": "mlc2-bundled-consent-v1",
    "required_for_service": True,
    "bundled_ui": True,
    "approval_reference": "WILLAB-MLC2-CONSENT-2026-08-28",
    "approved_copy_sha256": "a" * 64,
    "onboarding_copy": "Approved copy",
    "terms_version": "1.2",
    "privacy_policy_version": "1.2",
    "article_6_basis": "6(1)(a)",
    "article_9_treatment": "9(2)(a)_when_special_category",
}


@unittest.skipIf(_IMPORT_ERROR is not None, f"full app deps required: {_IMPORT_ERROR}")
class Mlc2ConsentEndpointTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.originals = []
        self._patch(route.config, "ADMIN_EMAIL", "artur@willonski.com")
        self._patch(
            route.config,
            "MLC2_CONFIDENCE_CANARY_FOUNDER_EMAIL",
            "artur@willonski.com",
        )
        self._patch(route, "_owner_and_status", lambda: ("principal-1", dict(STATUS)))

    def tearDown(self):
        for target, name, original in reversed(self.originals):
            setattr(target, name, original)

    def _patch(self, target, name, replacement):
        self.originals.append((target, name, getattr(target, name)))
        setattr(target, name, replacement)

    def _invoke(self, method, body=None, email="artur@willonski.com"):
        with self.app.test_request_context(
            "/v2/user/mlc2-consent",
            method=method,
            json=body,
            headers={"X-Willab-Client-Version": "test-client"},
        ):
            request.user_id = "founder-user-id"
            request.token_payload = {
                "sub": "founder-user-id",
                "email": email,
                "iss": "https://auth.example/auth/v1",
            }
            response, status = v2_mlc2_consent.v2_user_mlc2_consent.__wrapped__()
            return status, response.get_json()

    def test_ordinary_account_is_not_modified_or_gated(self):
        self._patch(
            route,
            "_owner_and_status",
            lambda: self.fail("ordinary account must not resolve a principal"),
        )
        status, payload = self._invoke("GET", email="student@example.com")
        self.assertEqual(status, 200)
        self.assertFalse(payload["applicable"])

    def test_get_returns_approved_policy_without_internal_principal_id(self):
        status, payload = self._invoke("GET")
        self.assertEqual(status, 200)
        self.assertTrue(payload["applicable"])
        self.assertFalse(payload["granted"])
        self.assertEqual(payload["terms_version"], "1.2")
        self.assertNotIn("acquisition_principal_id", payload)

    def test_post_requires_explicit_unambiguous_checkbox(self):
        self._patch(
            route.db,
            "accept_mlc2_founder_consent",
            lambda **kwargs: self.fail("identity must not bind without consent"),
        )
        status, payload = self._invoke("POST", {
            "accepted": False,
            "idempotency_key": "consent-1",
        })
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "EXPLICIT_CONSENT_REQUIRED")

    def test_post_rejects_stale_copy_before_any_canonical_write(self):
        self._patch(
            route.db,
            "accept_mlc2_founder_consent",
            lambda **kwargs: self.fail("stale copy must not bind identity"),
        )
        status, payload = self._invoke("POST", {
            "accepted": True,
            "idempotency_key": "consent-2",
            "consent_policy_version": STATUS["consent_policy_version"],
            "copy_sha256": "b" * 64,
        })
        self.assertEqual(status, 409)
        self.assertEqual(payload["code"], "CONSENT_VERSION_MISMATCH")

    def test_post_binds_verified_identity_and_records_both_purposes(self):
        calls = {}
        def accept(**kwargs):
            calls["accept"] = kwargs
            return {"consent_event_id": "grant-1", "binding_id": "binding-1"}

        self._patch(route.db, "accept_mlc2_founder_consent", accept)
        granted = {**STATUS, "granted": True, "speaker_bound": True}
        self._patch(
            route.db,
            "get_mlc2_principal_consent_status",
            lambda principal_id: granted,
        )
        status, payload = self._invoke("POST", {
            "accepted": True,
            "idempotency_key": "consent-3",
            "consent_policy_version": STATUS["consent_policy_version"],
            "copy_sha256": STATUS["approved_copy_sha256"],
        })
        self.assertEqual(status, 200)
        self.assertTrue(payload["granted"])
        self.assertEqual(calls["accept"]["binding_kind"], "verified_account_link")
        self.assertEqual(
            calls["accept"]["affirmative_action"]["purposes"],
            ["personalized_coaching", "pooled_model_improvement"],
        )
        self.assertTrue(calls["accept"]["article_9_applies"])

    def test_delete_appends_withdrawal_and_never_erases_grant(self):
        status_with_grant = {**STATUS, "granted": True, "grant_event_id": "grant-1"}
        self._patch(route, "_owner_and_status", lambda: ("principal-1", status_with_grant))
        calls = {}

        def withdraw(**kwargs):
            calls.update(kwargs)
            return {"id": "withdraw-1", "supersedes_event_id": "grant-1"}

        self._patch(route.db, "record_mlc2_consent_withdrawal", withdraw)
        self._patch(
            route.db,
            "get_mlc2_principal_consent_status",
            lambda principal_id: STATUS,
        )
        status, payload = self._invoke("DELETE", {"idempotency_key": "withdraw-1"})
        self.assertEqual(status, 200)
        self.assertFalse(payload["granted"])
        self.assertEqual(calls["grant_event_id"], "grant-1")
        self.assertTrue(calls["affirmative_action"]["service_access_ends"])


if __name__ == "__main__":
    unittest.main()
