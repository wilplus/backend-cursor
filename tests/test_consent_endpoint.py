"""
STORY    As the founder, I want the retired /v2/user/consent route to refuse
         every call without touching anyone's consent, and to tell me if
         anything still calls it, so that consent is recorded only where it
         is meant to be (consent on the critical path).
OUTCOME
  O1  GET and PUT /v2/user/consent answer 410 GONE and read or write
      nothing (founder 2026-10-19), and each call logs retired_route_called.
  O2  The retired bundled route (/v2/user/mlc2-consent) records no grant
      (410) and still lets a holder withdraw.
PROVES   O1 -> test_get_and_put_answer_410_write_nothing_and_warn
         O2 -> test_post_records_nothing_and_answers_410_with_a_code_only
               test_delete_withdraws_a_held_grant_and_never_erases_it
WHY      No frontend caller of /v2/user/consent was found on 2026-10-19.
         Terms acceptance at sign-up is routes/auth.py and is not affected.
"""
import unittest

try:
    from flask import Flask, request

    from routes.v2 import user_account as v2_user_account
    from services.db import db
    from tests.fakes import swap_attr
    _IMPORT_ERROR = None
except Exception as import_err:  # pragma: no cover - env/bootstrap guard
    Flask = None
    _IMPORT_ERROR = import_err


class _NoDatabase:
    def __getattr__(self, name):
        raise AssertionError(f"a retired route touched the database: {name}")


@unittest.skipIf(
    _IMPORT_ERROR is not None,
    f"consent tests require full app deps: {_IMPORT_ERROR}",
)
class RetiredConsentEndpointTests(unittest.TestCase):

    def test_get_and_put_answer_410_write_nothing_and_warn(self):
        app = Flask(__name__)
        for method, body in (("GET", None),
                             ("PUT", {"mic_consent": True, "terms_consent": True})):
            with self.subTest(method=method), \
                    swap_attr(db, "client", _NoDatabase()), \
                    self.assertLogs("routes.v2.common", "WARNING") as logs, \
                    app.test_request_context(
                        "/v2/user/consent", method=method, json=body):
                request.user_id = "user-consent-1"
                response, status = v2_user_account.v2_user_consent.__wrapped__()
                self.assertEqual(status, 410)
                self.assertEqual(response.get_json()["code"], "GONE")
                [line] = logs.output
                for part in ("retired_route_called", "route=/v2/user/consent",
                             f"method={method}", "user=user-consent-1"):
                    self.assertIn(part, line)


# ── merged from tests/test_mlc2_consent_endpoint.py (audit Q-T9) ──

try:
    from flask import Flask, request

    from routes.v2 import mlc2_consent as route
    from routes.v2 import mlc2_consent as v2_mlc2_consent
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
    """The bundled route, retired as a door (founder 2026-10-05, N48.5 Q27 A;
    N2; N10.6): it records no grant, answers every reader without an error,
    and still lets a holder withdraw a bundled grant."""

    def setUp(self):
        self.app = Flask(__name__)
        self.originals = []
        self._patch(route.db, "get_owner_principal_for_user",
                    lambda user_id: {"id": "principal-1"})
        self.statuses = [dict(STATUS)]
        self._patch(route.db, "get_mlc2_principal_consent_status",
                    lambda principal_id: self.statuses[0] if len(self.statuses) == 1
                    else self.statuses.pop(0))
        self._patch(route.db, "record_mlc2_consent_withdrawal",
                    lambda **kwargs: self.fail("no withdrawal expected"))

    def tearDown(self):
        for target, name, original in reversed(self.originals):
            setattr(target, name, original)

    def _patch(self, target, name, replacement):
        self.originals.append((target, name, getattr(target, name)))
        setattr(target, name, replacement)

    def _invoke(self, method, body=None):
        with self.app.test_request_context(
            "/v2/user/mlc2-consent",
            method=method,
            json=body,
            headers={"X-Willab-Client-Version": "test-client"},
        ):
            request.user_id = "founder-user-id"
            request.token_payload = {
                "sub": "founder-user-id",
                "email": "artur@willonski.com",
                "iss": "https://auth.example/auth/v1",
            }
            response, status = v2_mlc2_consent.v2_user_mlc2_consent.__wrapped__()
            return status, response.get_json()

    def _holding(self):
        held = {**STATUS, "granted": True, "speaker_bound": True,
                "grant_event_id": "grant-1"}
        self.statuses = [held]
        return held

    def test_post_records_nothing_and_answers_410_with_a_code_only(self):
        for name in ("get_owner_principal_for_user",
                     "get_mlc2_principal_consent_status"):
            self._patch(route.db, name,
                        lambda *a, **k: self.fail("a retired POST reads nothing"))
        status, payload = self._invoke("POST", {
            "accepted": True,
            "idempotency_key": "consent-1",
            "consent_policy_version": STATUS["consent_policy_version"],
            "copy_sha256": STATUS["approved_copy_sha256"],
        })
        self.assertEqual(status, 410)
        self.assertEqual(payload, {"code": "BUNDLED_CONSENT_RETIRED"})

    def test_delete_withdraws_a_held_grant_and_never_erases_it(self):
        self._holding()
        calls = {}

        def withdraw(**kwargs):
            calls.update(kwargs)
            self.statuses[0] = dict(STATUS)  # withdrawn: no longer held
            return {"id": "withdraw-1", "supersedes_event_id": "grant-1"}

        self._patch(route.db, "record_mlc2_consent_withdrawal", withdraw)
        status, payload = self._invoke("DELETE", {"idempotency_key": "withdraw-1"})
        self.assertEqual(status, 200)
        self.assertFalse(payload["granted"])
        self.assertFalse(payload["applicable"])
        self.assertEqual(calls["grant_event_id"], "grant-1")
        self.assertEqual(calls["acquisition_principal_id"], "principal-1")
        self.assertTrue(calls["affirmative_action"]["service_access_ends"])


if __name__ == "__main__":
    unittest.main()
