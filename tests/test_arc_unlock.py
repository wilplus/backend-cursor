"""The atomic credit-deduct CAS logic via a fake PostgREST client (no live DB).

The $25 arc unlock route this file once also covered was retired 2026-07-17
and its 410 tombstone deleted 2026-10-11.

Run: python3 -m unittest tests.test_arc_unlock
"""
from __future__ import annotations

import unittest

try:
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
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
        cls = db.__class__
        s = cls.__new__(cls)
        fake = _FakeCreditsClient(balances)
        s.client = fake
        s.v2_get_student_details = lambda uid: (
            {"credits": fake._balances.get(uid)}
            if fake._balances.get(uid) is not None else {}
        )
        return s, fake


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


if __name__ == "__main__":
    unittest.main()
