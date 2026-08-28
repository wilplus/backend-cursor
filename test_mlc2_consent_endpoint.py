import unittest

try:
    from flask import Flask
    from routes import v2_routes as v2
    from routes.v2 import mlc2_consent as route
    _IMPORT_ERROR = None
except Exception as import_error:  # pragma: no cover
    Flask = None
    v2 = None
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
            v2.request.user_id = "founder-user-id"
            v2.request.token_payload = {
                "sub": "founder-user-id",
                "email": email,
                "iss": "https://auth.example/auth/v1",
            }
            response, status = v2.v2_user_mlc2_consent.__wrapped__()
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
