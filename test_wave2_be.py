"""UX Wave v2 — backend: credit ledger, roster, recording-min config.

Covers the genuinely-new BE behavior:
  * the 15-credit lazy first-touch grant + its idempotency (spend-to-zero
    never re-grants; purchased balances are preserved) — db logic, via a
    fake PostgREST client so it runs without a live DB.
  * the three new route shapes (/user/credits, /config/recording,
    /coach/students) — mirror the test_coach_session harness (skip locally
    without app deps, run in CI).
  * the recording-min constants the config endpoint exposes — pure, runs
    everywhere.

Run: python3 -m unittest test_wave2_be
"""
from __future__ import annotations

import unittest

# ── pure: the min-content thresholds the /config/recording endpoint serves ──
# min_content_gate is import-safe without numpy (it lazy-imports the audio
# stack inside the functions), so this runs in every env.


class MinContentConstantsTests(unittest.TestCase):
    def test_constants(self):
        from services.min_content_gate import MIN_DURATION_SEC, MIN_VOICED_SEC
        self.assertEqual(MIN_DURATION_SEC, 0.0)  # retired 2026-07-15 (no minimum)
        self.assertEqual(MIN_VOICED_SEC, 3.0)


# ── app-dependent: db grant logic + route shapes ──
try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
    _IMPORT_ERROR = e


# ── a tiny fake PostgREST client, just enough for v2_ensure_credits_initialized ──

class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, store):
        self.store = store
        self._op = None
        self._payload = None
        self._eq = {}
        self._isnull = set()

    def select(self, *a, **k):
        self._op = "select"
        return self

    def upsert(self, payload, on_conflict=None, **k):
        self._op = "upsert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, col, val):
        self._eq[col] = val
        return self

    def is_(self, col, val):
        if val == "null":
            self._isnull.add(col)
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._op == "select":
            rows = [
                dict(r) for r in self.store.values()
                if all(r.get(k) == v for k, v in self._eq.items())
            ]
            return _Resp(rows)
        if self._op == "upsert":
            uid = self._payload.get("user_id")
            self.store.setdefault(uid, {}).update(self._payload)
            return _Resp([dict(self.store[uid])])
        if self._op == "update":
            matched = []
            for r in self.store.values():
                if all(r.get(k) == v for k, v in self._eq.items()) and all(
                    r.get(c) is None for c in self._isnull
                ):
                    r.update(self._payload)
                    matched.append(dict(r))
            return _Resp(matched)
        return _Resp([])


class _FakeClient:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _Q(self.store)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class CreditGrantLogicTests(unittest.TestCase):
    """The grant must fire exactly once and never re-grant after spend."""

    def _svc(self, store):
        cls = v2.db.__class__
        s = cls.__new__(cls)            # bypass __init__ (no live supabase)
        s.client = _FakeClient(store)
        return s

    def test_grants_default_on_first_touch(self):
        # Founder testing 2026-07-13: the default grant is now
        # config.WILLAB_FREE_CREDIT_GRANT (25), not the old hardcoded 15.
        from config import Config
        expected = int(Config.WILLAB_FREE_CREDIT_GRANT)
        store = {}
        bal = self._svc(store).v2_ensure_credits_initialized("u1")
        self.assertEqual(bal, expected)
        self.assertEqual(store["u1"]["credits"], expected)
        self.assertTrue(store["u1"]["credits_initialized_at"])

    def test_spend_to_zero_is_never_regranted(self):
        # already initialized, balance spent to 0 → stays 0 (the whole point
        # of the dedicated flag, not credits==0/NULL)
        store = {"u1": {"user_id": "u1", "credits": 0,
                        "credits_initialized_at": "2026-06-01T00:00:00Z"}}
        bal = self._svc(store).v2_ensure_credits_initialized("u1")
        self.assertEqual(bal, 0)
        self.assertEqual(store["u1"]["credits"], 0)

    def test_preserves_purchased_balance(self):
        # row exists, flag NULL, real balance → preserve it, just stamp flag
        store = {"u1": {"user_id": "u1", "credits": 42}}
        bal = self._svc(store).v2_ensure_credits_initialized("u1")
        self.assertEqual(bal, 42)
        self.assertEqual(store["u1"]["credits"], 42)
        self.assertTrue(store["u1"]["credits_initialized_at"])

    def test_seeds_when_row_exists_but_credits_null(self):
        from config import Config
        expected = int(Config.WILLAB_FREE_CREDIT_GRANT)
        store = {"u1": {"user_id": "u1", "credits": None}}
        bal = self._svc(store).v2_ensure_credits_initialized("u1")
        self.assertEqual(bal, expected)
        self.assertEqual(store["u1"]["credits"], expected)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ConfigRecordingRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def test_serves_thresholds(self):
        with self.app.test_request_context():
            resp, status = v2.v2_config_recording.__wrapped__()
            data = resp.get_json()
            self.assertEqual(status, 200)
            self.assertEqual(data["min_duration_sec"], 0.0)  # retired 2026-07-15
            self.assertEqual(data["min_voiced_sec"], 3.0)

    def test_serves_the_long_take_caution_threshold(self):
        # Founder 2026-07-27: the ceiling side of the same idea, and NOT a
        # gate — the FE shows a soft caution at/above it and the student
        # proceeds anyway. Served so the threshold in the copy has one home.
        with self.app.test_request_context():
            resp, status = v2.v2_config_recording.__wrapped__()
            self.assertEqual(status, 200)
            self.assertEqual(resp.get_json()["long_take_caution_sec"], 600)

    def test_the_caution_threshold_never_becomes_a_gate(self):
        # Nothing server-side may reject or truncate on this number. If an
        # upload path ever reads it, this pin is the place that argues.
        import config as _cfg
        self.assertEqual(_cfg.Config.LONG_TAKE_CAUTION_SECONDS, 600)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class CoachStudentsRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self._orig_list = getattr(v2.db, "list_coach_students", None)
        self._orig_prof = getattr(v2.db, "get_user_profile", None)
        v2.db.list_coach_students = lambda **k: [
            {"user_id": "secret-uid-123", "last_active": "2026-06-08T10:00:00Z",
             "session_count": 7},
        ]
        v2.db.get_user_profile = lambda uid: {"domain": "sales", "goal": "x"}

    def tearDown(self):
        if self._orig_list is not None:
            v2.db.list_coach_students = self._orig_list
        if self._orig_prof is not None:
            v2.db.get_user_profile = self._orig_prof

    def _get(self):
        with self.app.test_request_context():
            request.user_id = "coach-1"
            resp, status = v2.v2_coach_students.__wrapped__()
            return status, resp.get_json()

    def test_pseudonymized_no_pii(self):
        status, data = self._get()
        self.assertEqual(status, 200)
        row = data[0]
        self.assertTrue(row["pseudonym"])
        self.assertEqual(row["domain"], "sales")
        self.assertIn("last_active", row)
        self.assertEqual(row["session_count"], 7)  # coach-load drowning guard
        # user_id is the opaque drill key (FE keys the detail view on it, never
        # renders it) — present, but NOT a displayed field.
        self.assertEqual(row["user_id"], "secret-uid-123")
        # red-line: still no name/email (the actual PII).
        self.assertNotIn("email", row)
        self.assertNotIn("name", row)


if __name__ == "__main__":
    unittest.main()
