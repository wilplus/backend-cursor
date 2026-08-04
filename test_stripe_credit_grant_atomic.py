"""The Stripe credit grant as ONE transaction.

services/stripe_checkout_credits.py · migrations/add_stripe_credit_grant_rpc.sql

WHAT THIS PINS DOWN
  * the half-state that costs a user real money — claim lands, process dies,
    every retry thereafter reports duplicate=true and grants nothing;
  * that "the function is BROKEN" is never mistaken for "the function is
    ABSENT". That mistake is not hypothetical: token_charge shipped with a
    `uuid = text` comparison, raised SQLSTATE 42883, and the fallback read it
    as "not installed" — so #328's atomicity fix was inert in production for
    its entire life while the logs said everything was fine;
  * that a genuine RPC failure does NOT retry through the legacy path, because
    a lost response after a successful commit is indistinguishable from a
    failure, and retrying would credit twice.

Run: python3 -m unittest test_stripe_credit_grant_atomic
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

_ORIG_DB = None


def setUpModule():
    global _ORIG_DB
    _ORIG_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    stub._free_credit_grant = lambda: 25
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_DB is not None:
        sys.modules["services.db"] = _ORIG_DB
    else:
        sys.modules.pop("services.db", None)


class RpcMissing(RuntimeError):
    """PostgREST's shape for a function that is not in the schema cache."""
    code = "PGRST202"

    def __init__(self, name="stripe_checkout_grant_credits"):
        super().__init__(
            f"Could not find the function public.{name} in the schema cache")


class UuidTextError(RuntimeError):
    """The real production error from token_charge: a BROKEN function body.

    Same SQLSTATE as a missing function, which is the whole trap.
    """
    code = "42883"

    def __init__(self):
        super().__init__("operator does not exist: uuid = text")


class FakeGrantDB:
    """Models the Postgres function: claim + grant, atomically."""

    def __init__(self, credits=10, installed=True, raises=None):
        self.credits = credits
        self.claims: dict = {}
        self.installed = installed
        self.raises = raises
        self.calls: list = []
        self.client = MagicMock()
        self.client.rpc.side_effect = self._rpc

    def _rpc(self, name, params):
        if not self.installed:
            raise RpcMissing(name)
        if self.raises is not None:
            raise self.raises
        self.calls.append(dict(params))
        return _Call(lambda: self._grant(params))

    def _grant(self, p):
        sid = p["p_checkout_session_id"]
        if sid in self.claims:
            return {"ok": True, "granted": False, "duplicate": True,
                    "credits": self.credits, "delta": 0,
                    "reason": "already_granted"}
        # Claim and grant commit together — there is no state in which one
        # landed and the other did not.
        self.claims[sid] = (p["p_user_id"], p["p_credits"])
        self.credits = max(0, self.credits + int(p["p_credits"]))
        return {"ok": True, "granted": True, "duplicate": False,
                "credits": self.credits, "delta": int(p["p_credits"]),
                "reason": ""}


class _Call:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return MagicMock(data=self._fn())


def _reset_cache():
    import services.stripe_checkout_credits as m
    m._rpc_missing_until = 0.0


class AtomicGrantTests(unittest.TestCase):
    def setUp(self):
        _reset_cache()

    def tearDown(self):
        _reset_cache()

    def test_a_grant_claims_and_credits_in_one_call(self):
        import services.stripe_checkout_credits as m
        db = FakeGrantDB(credits=10)
        with patch.object(m, "db", db):
            out = m._grant_atomic("cs_1", "u-1", 25)
        self.assertTrue(out["ok"])
        self.assertTrue(out["granted"])
        self.assertFalse(out["duplicate"])
        self.assertEqual(out["credits"], 35)
        self.assertEqual(db.claims["cs_1"], ("u-1", 25))

    def test_the_same_session_never_credits_twice(self):
        import services.stripe_checkout_credits as m
        db = FakeGrantDB(credits=10)
        with patch.object(m, "db", db):
            m._grant_atomic("cs_1", "u-1", 25)
            again = m._grant_atomic("cs_1", "u-1", 25)
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["delta"], 0)
        self.assertEqual(db.credits, 35, "a retry credited a second time")

    def test_the_free_grant_is_passed_so_a_first_purchase_keeps_it(self):
        import services.stripe_checkout_credits as m
        db = FakeGrantDB()
        with patch.object(m, "db", db):
            m._grant_atomic("cs_1", "u-1", 25)
        self.assertEqual(db.calls[0]["p_free_grant"], 25)


class BrokenIsNotAbsentTests(unittest.TestCase):
    """The regression test for the bug that started this.

    A function that EXISTS and throws must never be read as "not installed" —
    that downgrade is silent, permanent, and looks like success.
    """

    def setUp(self):
        _reset_cache()

    def tearDown(self):
        _reset_cache()

    def test_uuid_text_error_is_not_treated_as_a_missing_function(self):
        import services.stripe_checkout_credits as m
        self.assertFalse(m._rpc_not_found(UuidTextError()),
                         "a broken function body was read as 'not installed' — "
                         "this is exactly how token_charge went inert in prod")

    def test_a_genuinely_missing_function_still_reads_as_missing(self):
        import services.stripe_checkout_credits as m
        self.assertTrue(m._rpc_not_found(RpcMissing()))

    def test_a_bare_42883_naming_the_function_still_reads_as_missing(self):
        import services.stripe_checkout_credits as m
        self.assertTrue(m._rpc_not_found(RuntimeError(
            "42883 function public.stripe_checkout_grant_credits does not exist")))

    def test_an_unrelated_error_is_a_failure_not_a_fallback(self):
        import services.stripe_checkout_credits as m
        self.assertFalse(m._rpc_not_found(RuntimeError("connection reset")))

    def test_token_account_carries_the_same_guard(self):
        """Both call sites must agree, or the next one repeats the incident."""
        import services.token_account as ta
        self.assertFalse(ta._rpc_not_found(UuidTextError()))
        self.assertTrue(ta._rpc_not_found(RuntimeError(
            "PGRST202 Could not find the function")))

    def test_a_broken_function_surfaces_as_an_error_not_a_silent_fallback(self):
        import services.stripe_checkout_credits as m
        db = FakeGrantDB(raises=UuidTextError())
        with patch.object(m, "db", db):
            out = m._grant_atomic("cs_1", "u-1", 25)
        self.assertIsNone(out, "a broken function must report failure, not "
                               "quietly reroute to the legacy path")


class FallbackTests(unittest.TestCase):
    def setUp(self):
        _reset_cache()

    def tearDown(self):
        _reset_cache()

    def test_a_database_without_the_migration_uses_the_legacy_path(self):
        import services.stripe_checkout_credits as m
        db = FakeGrantDB(installed=False)
        with patch.object(m, "db", db):
            self.assertIs(m._grant_atomic("cs_1", "u-1", 25), m._RPC_MISSING)

    def test_the_missing_probe_is_cached_then_re_probed(self):
        """One failed round trip per window — but it must expire, or running
        the migration would need a redeploy to take effect."""
        import services.stripe_checkout_credits as m
        db = FakeGrantDB(installed=False)
        with patch.object(m, "db", db):
            m._grant_atomic("cs_1", "u-1", 25)
            first = db.client.rpc.call_count
            m._grant_atomic("cs_2", "u-1", 25)
            self.assertEqual(db.client.rpc.call_count, first,
                             "re-probed inside the cache window")
            m._rpc_missing_until = 0.0
            m._grant_atomic("cs_3", "u-1", 25)
            self.assertEqual(db.client.rpc.call_count, first + 1,
                             "never re-probed — a run migration would stay dark")

    def test_a_real_failure_does_not_fall_back(self):
        """"Failed" and "committed but the response was lost" are the same
        from here. Replaying the legacy path could credit a second time."""
        import services.stripe_checkout_credits as m
        db = FakeGrantDB(raises=RuntimeError("connection reset by peer"))
        with patch.object(m, "db", db):
            out = m._grant_atomic("cs_1", "u-1", 25)
        self.assertIsNone(out)
        self.assertIsNot(out, m._RPC_MISSING)


if __name__ == "__main__":
    unittest.main()
