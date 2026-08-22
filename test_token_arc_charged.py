"""willab — GET /v2/tokens/arc/<arc_id>: what's already paid for on this arc.

WHY IT EXISTS. Per-arc actions charge with ref_id=arc_id, so the first open
costs the price and every re-open is free. A control with a static price label
is therefore right exactly once and wrong forever after — and a stale price on
a button is worse than none, because people act on it and it discourages
re-reading something they already own. The FE needs the answer BEFORE it
renders, and it cannot come from the action's own endpoint, because that
response IS the charge.

WHAT IS PINNED:
  * the read charges NOTHING — that is the whole premise; if it ever charged,
    checking a price would cost money;
  * it is scoped to the caller, so another user's arc reports all-false;
  * ⭐ PER_ARC_ACTIONS stays in step with the code. The test greps the routes
    for `ref_id=arc_id` charges and fails if one is missing from the tuple —
    otherwise a new per-arc action ships with a permanently stale price label
    and nobody notices until a user complains about being charged twice.

Run: python3 -m unittest test_token_arc_charged
"""
from __future__ import annotations

import re
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
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_DB is not None:
        sys.modules["services.db"] = _ORIG_DB
    else:
        sys.modules.pop("services.db", None)


class _Ledger:
    """Fake token_ledger honouring .eq() filters."""

    def __init__(self, rows, spy):
        self.rows, self.spy, self.f = rows, spy, {}

    def select(self, *_a, **_k):
        self.spy["select"] = self.spy.get("select", 0) + 1
        return self

    def insert(self, payload):
        self.spy.setdefault("inserts", []).append(payload)
        return self

    def update(self, payload):
        self.spy.setdefault("updates", []).append(payload)
        return self

    def eq(self, col, val):
        self.f[col] = str(val)
        return self

    def limit(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def execute(self):
        out = [r for r in self.rows
               if all(str(r.get(k)) == v for k, v in self.f.items())]
        return MagicMock(data=out)


class _DB:
    def __init__(self, rows):
        self.spy: dict = {}
        self.client = MagicMock()
        self.client.table.side_effect = lambda name: _Ledger(rows, self.spy)


ROWS = [
    {"user_id": "u1", "ref_id": "arc1", "action": "insights"},
    {"user_id": "u1", "ref_id": "arc2", "action": "insights"},
    {"user_id": "OTHER", "ref_id": "arc9", "action": "insights"},
]


class ChargedLookupTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", {"TOKEN_PRICING_ENABLED": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_reports_exactly_what_was_paid_on_this_arc(self):
        from services.token_account import charged_actions_for_ref
        db = _DB(ROWS)
        self.assertEqual(charged_actions_for_ref("u1", "arc1", database=db),
                         {"insights"})
        self.assertEqual(charged_actions_for_ref("u1", "arc2", database=db),
                         {"insights"})

    def test_unpaid_arc_is_empty_not_an_error(self):
        from services.token_account import charged_actions_for_ref
        self.assertEqual(
            charged_actions_for_ref("u1", "arc_never_opened", database=_DB(ROWS)),
            set())

    def test_another_users_arc_reports_nothing(self):
        """Scoped to the caller — it cannot reveal someone else's spend, or
        that an arc exists at all."""
        from services.token_account import charged_actions_for_ref
        self.assertEqual(charged_actions_for_ref("u1", "arc9", database=_DB(ROWS)),
                         set())

    def test_the_lookup_never_writes(self):
        """THE premise. If checking a price could charge, the FE could not use
        it as a pre-render check."""
        from services.token_account import charged_actions_for_ref
        db = _DB(ROWS)
        charged_actions_for_ref("u1", "arc1", database=db)
        self.assertNotIn("inserts", db.spy)
        self.assertNotIn("updates", db.spy)

    def test_database_failure_degrades_to_unknown_not_a_crash(self):
        from services.token_account import charged_actions_for_ref
        db = _DB(ROWS)
        db.client.table.side_effect = RuntimeError("down")
        self.assertEqual(charged_actions_for_ref("u1", "arc1", database=db), set())

    def test_blank_input_is_empty(self):
        from services.token_account import charged_actions_for_ref
        db = _DB(ROWS)
        self.assertEqual(charged_actions_for_ref("", "arc1", database=db), set())
        self.assertEqual(charged_actions_for_ref("u1", "", database=db), set())


class PerArcRegistryTests(unittest.TestCase):
    def test_every_per_arc_action_has_a_price(self):
        from services.token_prices import PER_ARC_ACTIONS, price_of
        for a in PER_ARC_ACTIONS:
            self.assertGreater(price_of(a), 0, f"{a} priced at 0")

    def test_registry_covers_every_arc_keyed_charge_in_the_routes(self):
        """⭐ The drift guard. A new charge(..., ref_id=arc_id) that is not in
        PER_ARC_ACTIONS ships with a permanently stale price label on the FE,
        and nobody finds out until a user says they were charged twice."""
        from services.token_prices import PER_ARC_ACTIONS
        # The /v2 route layer is split across routes/v2_routes.py and the
        # per-domain modules under routes/v2/ (god-file split) — glob them so
        # carving out a domain can never quietly empty this drift guard.
        import glob
        src = ""
        for path in (["routes/v2_routes.py", "services/lab_recording.py"]
                     + sorted(glob.glob("routes/v2/*.py"))):
            with open(path) as fh:
                src += fh.read()
        found = set(re.findall(
            r'_charge_arc_deliverable\(\s*[^,]+,\s*["\'](\w+)["\']', src))
        missing = found - set(PER_ARC_ACTIONS)
        self.assertEqual(missing, set(),
                         f"arc-keyed charges missing from PER_ARC_ACTIONS: {missing}")
        self.assertIn("insights", found, "sanity: the grep found nothing at all")
        self.assertNotIn("game", found)


if __name__ == "__main__":
    unittest.main()
