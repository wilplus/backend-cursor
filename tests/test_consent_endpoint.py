"""
STORY    As a speaker, I want to give or change my mic, share and email
         choices and accept the terms once, so that the app records exactly
         what I agreed to (consent on the critical path).
OUTCOME
  O1  Before I answer, GET shows every choice unset and no terms accepted.
  O2  PUT stores the choices I send (only those), stamps when, and accepting
      the terms appends one ledger row at the current version.
  O3  Accepting again writes no second row; null clears a choice and its
      time; terms "false" is refused and nothing is written.
  O4  The retired bundled route (/v2/user/mlc2-consent) records no grant
      (410) and still lets a holder withdraw.
PROVES   O1 -> test_get_before_any_answer_shows_nothing_set
         O2 -> test_put_all_three_plus_terms_records_ledger
               test_put_only_mic_leaves_the_others_unset
         O3 -> test_accepting_twice_and_clearing
               test_put_terms_consent_false_is_rejected
         O4 -> test_post_records_nothing_and_answers_410_with_a_code_only
               test_delete_withdraws_a_held_grant_and_never_erases_it
WHY      The real services.db consent methods run over an in-memory
         user_settings / user_consents store, so the echoed state is the
         app's own read-back, not a fake's. No frontend caller of
         /v2/user/consent was found on 2026-10-19 (founder to confirm it is
         still live).
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


_TERMS_VERSION = "test-1.0"


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """user_settings (one row per user) and user_consents (one row per user
    and terms version) as the two tables the consent methods use."""

    def __init__(self, store, name):
        self.store, self.name = store, name
        self.filters, self.write, self.ignore = {}, None, False

    def select(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def eq(self, column, value):
        self.filters[column] = value
        return self

    def upsert(self, row, on_conflict=None, ignore_duplicates=False):
        self.write, self.ignore = dict(row), ignore_duplicates
        return self

    def execute(self):
        rows = self.store.setdefault(self.name, [])
        if self.write is None:
            return _Result([dict(r) for r in rows
                            if all(r.get(k) == v for k, v in self.filters.items())])
        keys = ("user_id",) if self.name == "user_settings" else ("user_id", "terms_version")
        match = next((r for r in rows if all(r.get(k) == self.write[k] for k in keys)), None)
        if match is None:
            rows.append(self.write)
            return _Result([dict(self.write)])
        if self.ignore:
            return _Result([])
        match.update(self.write)
        return _Result([dict(match)])


class _Store:
    def __init__(self):
        self.rows = {}

    def table(self, name):
        return _Query(self.rows, name)


@unittest.skipIf(
    _IMPORT_ERROR is not None,
    f"consent tests require full app deps: {_IMPORT_ERROR}",
)
class ConsentEndpointTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.user_id = "user-consent-1"
        self.store = _Store()
        swap = swap_attr(db, "client", self.store)
        swap.__enter__()
        self.addCleanup(swap.__exit__, None, None, None)
        terms = swap_attr(v2_user_account.config, "CURRENT_TERMS_VERSION", _TERMS_VERSION)
        terms.__enter__()
        self.addCleanup(terms.__exit__, None, None, None)

    @property
    def ledger(self):
        return self.store.rows.get("user_consents", [])

    def _invoke(self, method, json_body=None):
        with self.app.test_request_context(
            "/v2/user/consent", method=method, json=json_body,
        ):
            request.user_id = self.user_id
            response, status = v2_user_account.v2_user_consent.__wrapped__()
            return status, response.get_json()

    def test_get_before_any_answer_shows_nothing_set(self):
        status, payload = self._invoke("GET")
        self.assertEqual(status, 200)
        self.assertFalse(payload["has_answered"])
        self.assertEqual(
            (payload["mic_consent"], payload["share_consent"], payload["email_consent"]),
            (None, None, None))
        self.assertFalse(payload["terms_consent"])
        self.assertEqual(payload["terms_version_current"], _TERMS_VERSION)

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
        self.assertIsNotNone(payload["share_consent_set_at"])
        self.assertTrue(payload["terms_consent"])
        self.assertEqual(payload["terms_version_accepted"], _TERMS_VERSION)
        self.assertEqual([(r["user_id"], r["terms_version"]) for r in self.ledger],
                         [(self.user_id, _TERMS_VERSION)])

    def test_put_only_mic_leaves_the_others_unset(self):
        status, payload = self._invoke("PUT", {"mic_consent": True})
        self.assertEqual(status, 200)
        self.assertTrue(payload["has_answered"])
        self.assertTrue(payload["mic_consent"])
        self.assertIsNotNone(payload["mic_consent_set_at"])
        self.assertEqual((payload["share_consent"], payload["email_consent"]), (None, None))
        self.assertFalse(payload["terms_consent"])
        self.assertEqual(self.ledger, [])

    def test_accepting_twice_and_clearing(self):
        _, first = self._invoke("PUT", {"mic_consent": True, "terms_consent": True})
        status, again = self._invoke("PUT", {"mic_consent": None, "terms_consent": True})
        self.assertEqual(status, 200)
        self.assertEqual(len(self.ledger), 1)
        self.assertEqual(again["terms_accepted_at"], first["terms_accepted_at"])
        self.assertEqual((again["mic_consent"], again["mic_consent_set_at"]), (None, None))
        self.assertTrue(again["has_answered"])  # the terms still count

    def test_put_terms_consent_false_is_rejected(self):
        """Terms ledger is append-only: false is not a valid value."""
        status, payload = self._invoke("PUT", {"terms_consent": False, "mic_consent": True})
        self.assertEqual(status, 400)
        self.assertEqual(payload["code"], "INVALID_INPUT")
        self.assertEqual(self.ledger, [])
        self.assertEqual(self.store.rows.get("user_settings", []), [])


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
