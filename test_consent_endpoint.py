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
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as import_err:  # pragma: no cover - env/bootstrap guard
    Flask = None
    v2 = None
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
        self.originals[key] = (v2.db, attr, getattr(v2.db, attr))
        setattr(v2.db, attr, replacement)

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
            v2.request.user_id = self.user_id
            response, status = v2.v2_user_consent.__wrapped__()
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


if __name__ == "__main__":
    unittest.main()
