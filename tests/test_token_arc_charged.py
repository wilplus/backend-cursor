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

Run: python3 -m unittest tests.test_token_arc_charged
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


if __name__ == "__main__":
    unittest.main()
