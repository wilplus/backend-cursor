"""willab — $25/25-credit arc unlock (founder re-price 2026-07-06).

POST /v2/arc/<arc_id>/unlock route-level tests (mirrors the test_wave2_be.py /
test_wave3_be.py harness: patch db.* on the v2 module, call the unwrapped
handler directly) + the atomic credit-deduct CAS logic via a fake PostgREST
client (no live DB).

Run: python3 -m unittest test_arc_unlock
"""
from __future__ import annotations

import unittest

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
    _IMPORT_ERROR = e


# ── deduct_credits_strict — atomic CAS deduct, via a fake PostgREST client ──

class _Resp:
    def __init__(self, data):
        self.data = data


class _FakeCreditsClient:
    """Models v2_student_details as an in-memory {user_id: credits} row set.
    .update(...).eq("user_id", u).eq("credits", expected).execute() only
    "matches" (returns data) when credits still equals `expected` — the exact
    CAS semantics deduct_credits_strict relies on."""

    def __init__(self, balances: dict):
        self._balances = dict(balances)
        self.write_attempts = 0

    def table(self, name):
        assert name == "v2_student_details"
        return self

    def select(self, *_a, **_k):
        return self

    def update(self, payload):
        self._pending_update = payload
        return self

    def upsert(self, payload, on_conflict=None):
        # UPSERT creates the row — the distinction that matters here, since
        # deduct_credits_strict seeds via this path before CASing with update().
        self._pending_upsert = payload
        return self

    def eq(self, col, val):
        self._filters = getattr(self, "_filters", {})
        self._filters[col] = val
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        # UPSERT path (the lazy seed) — creates or replaces the row outright.
        if hasattr(self, "_pending_upsert"):
            payload = self._pending_upsert
            del self._pending_upsert
            self._filters = {}
            self._balances[payload["user_id"]] = payload["credits"]
            return _Resp([payload])
        # SELECT path (v2_get_student_details) — no pending update.
        if not hasattr(self, "_pending_update"):
            uid = self._filters.get("user_id")
            bal = self._balances.get(uid)
            return _Resp([{"credits": bal}] if bal is not None else [])
        # UPDATE path — CAS: only "matches" if credits == the filtered value.
        self.write_attempts += 1
        uid = self._filters.get("user_id")
        expected = self._filters.get("credits")
        current = self._balances.get(uid)
        payload = self._pending_update
        del self._pending_update
        self._filters = {}
        if current != expected:
            return _Resp([])  # CAS miss — someone else changed it
        self._balances[uid] = payload["credits"]
        return _Resp([{"credits": payload["credits"]}])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class DeductCreditsStrictTests(unittest.TestCase):
    def _svc(self, balances):
        # Bypass __init__ (no live supabase connection) — same technique as
        # test_wave2_be.CreditGrantLogicTests._svc.
        cls = v2.db.__class__
        s = cls.__new__(cls)
        fake = _FakeCreditsClient(balances)
        s.client = fake
        s.v2_get_student_details = lambda uid: (
            {"credits": fake._balances.get(uid)}
            if fake._balances.get(uid) is not None else {}
        )
        return s, fake

    def test_sufficient_balance_deducts_and_returns_new_balance(self):
        svc, _ = self._svc({"u1": 30})
        new_bal = svc.deduct_credits_strict("u1", 25)
        self.assertEqual(new_bal, 5)

    def test_insufficient_balance_returns_none_no_write_attempt(self):
        svc, fake = self._svc({"u1": 10})
        new_bal = svc.deduct_credits_strict("u1", 25)
        self.assertIsNone(new_bal)
        self.assertEqual(fake.write_attempts, 0)  # never even tried the CAS

    def test_exact_balance_succeeds_to_zero(self):
        svc, _ = self._svc({"u1": 25})
        self.assertEqual(svc.deduct_credits_strict("u1", 25), 0)

    def test_missing_user_defaults_to_lazy_seed(self):
        # v2_get_student_details returns {} for an unknown user — the deduct
        # treats that as the lazy-seed default (config.WILLAB_FREE_CREDIT_GRANT,
        # 25 for the testing phase — consistent with the seed + the unlock
        # amount so a brand-new user can unlock before their row is written).
        from config import Config
        seed = int(Config.WILLAB_FREE_CREDIT_GRANT)
        svc1, _ = self._svc({})
        # seed == 25 and unlock == 25 → exactly enough → succeeds to 0
        self.assertEqual(svc1.deduct_credits_strict("u1", 25), seed - 25)
        svc2, _ = self._svc({})
        self.assertEqual(svc2.deduct_credits_strict("u1", 10), seed - 10)

    def test_unseeded_user_row_is_written_not_just_assumed(self):
        """The 2026-07-30 repair. The old code took the grant as the balance
        but left the row absent, then CASed with UPDATE ... eq(credits, 25) —
        which matches nothing, because an UPDATE never creates a row. A
        brand-new user was told INSUFFICIENT_CREDITS while holding the grant.
        Assert the row actually LANDS, not merely that the call returns a
        number: returning the right value off a phantom row is the bug."""
        from config import Config
        seed = int(Config.WILLAB_FREE_CREDIT_GRANT)
        svc, fake = self._svc({})
        self.assertEqual(svc.deduct_credits_strict("u1", 5), seed - 5)
        self.assertEqual(fake._balances.get("u1"), seed - 5)

    def test_spent_down_user_is_never_re_granted(self):
        """The seed must not become a refill. A balance of 0 is a real value,
        not an unseeded row, so it fails rather than re-granting."""
        svc, fake = self._svc({"u1": 0})
        self.assertIsNone(svc.deduct_credits_strict("u1", 5))
        self.assertEqual(fake._balances.get("u1"), 0)

    def test_bad_args_return_none(self):
        svc, _ = self._svc({"u1": 30})
        self.assertIsNone(svc.deduct_credits_strict(None, 25))
        self.assertIsNone(svc.deduct_credits_strict("u1", 0))
        self.assertIsNone(svc.deduct_credits_strict("u1", -5))


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ArcUnlockRouteTests(unittest.TestCase):
    """POST /v2/arc/<arc_id>/unlock is RETIRED (single-deliverable, founder
    2026-07-17): the $25 arc unlock is gone and the route is now an
    UNCONDITIONAL 410 GONE tombstone. The ideal text + its deliverables are
    free; the only paid item is the 5-credit key-moment explanations. No
    deduct, no purchase insert, no ownership branch — just the tombstone."""

    def setUp(self):
        self.app = Flask(__name__)

    def _call(self, arc_id="a1"):
        with self.app.test_request_context():
            request.user_id = "u1"
            resp, status = v2.v2_arc_unlock.__wrapped__(arc_id)
            return resp.get_json(), status

    def test_unlock_is_gone_tombstone(self):
        body, status = self._call()
        self.assertEqual(status, 410)
        self.assertEqual(body["code"], "GONE")


if __name__ == "__main__":
    unittest.main()
