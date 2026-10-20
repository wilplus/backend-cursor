"""
STORY    As a speaker, I want to see whether I already paid for an action on
         this presentation, without being charged for looking, so that the
         prices on its buttons are true. (Critical path: payments.)
OUTCOME
  O1  GET /v2/tokens/arc/<arc_id> answers, for every per-arc action, whether I
      already paid for it here and what it costs.
  O2  Looking charges nothing: no ledger row, no balance change, no charge
      call.
  O3  It reads only my own rows: on another user's arc every action reads
      unpaid.
  O4  Every action the routes charge once per arc is in the list the lookup
      answers for, so no button keeps a stale price.
PROVES   O1 -> test_the_lookup_reports_what_i_paid_on_this_arc
         O2 -> test_the_lookup_reports_what_i_paid_on_this_arc
         O3 -> test_another_users_arc_reads_unpaid
         O4 -> test_every_per_arc_charge_is_listed
WHY      Per-arc actions charge with ref_id=arc_id, so a static price label is
         right once and wrong forever after.
"""
from __future__ import annotations

import ast
import pathlib
import unittest
from unittest.mock import patch

from flask import Flask, request

from routes import token_routes
from services.token_prices import PER_ARC_ACTIONS, price_of

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Ledger:
    """token_ledger honouring .eq() filters; every write is recorded."""

    def __init__(self, rows, writes):
        self.rows, self.writes, self.f = rows, writes, {}

    def select(self, *_a, **_k):
        return self

    def insert(self, payload):
        self.writes.append(("insert", payload))
        return self

    def update(self, payload):
        self.writes.append(("update", payload))
        return self

    def upsert(self, payload):
        self.writes.append(("upsert", payload))
        return self

    def eq(self, col, val):
        self.f[col] = str(val)
        return self

    def execute(self):
        return type("R", (), {"data": [
            r for r in self.rows
            if all(str(r.get(k)) == v for k, v in self.f.items())]})()


class _Database:
    def __init__(self, rows):
        self.writes: list = []
        outer = self

        class _Client:
            def table(self, _name):
                return _Ledger(rows, outer.writes)

            def rpc(self, name, params):
                outer.writes.append(("rpc", name))
                raise AssertionError("the lookup must not call " + name)

        self.client = _Client()


ROWS = [
    {"user_id": "u1", "ref_id": "arc1", "action": "insights"},
    {"user_id": "u1", "ref_id": "arc2", "action": "moment_explanation"},
    {"user_id": "u2", "ref_id": "arc9", "action": "insights"},
]


class ArcLookupRouteTests(unittest.TestCase):

    def _get(self, arc_id, user="u1"):
        database = _Database(ROWS)
        with patch.dict("os.environ", {"TOKEN_PRICING_ENABLED": "1"}), \
                patch("services.token_account._db", return_value=database), \
                Flask(__name__).test_request_context():
            request.user_id = user
            resp, status = token_routes.tokens_arc_state.__wrapped__(arc_id)
        self.assertEqual(status, 200)
        return resp.get_json(), database.writes

    def test_the_lookup_reports_what_i_paid_on_this_arc(self):
        body, writes = self._get("arc1")
        self.assertEqual(body["charged"],
                         {a: a == "insights" for a in PER_ARC_ACTIONS})
        self.assertEqual(body["prices"], {a: price_of(a) for a in PER_ARC_ACTIONS})
        self.assertEqual(writes, [])

    def test_another_users_arc_reads_unpaid(self):
        body, writes = self._get("arc9")       # paid for by u2, not u1
        self.assertEqual(body["charged"], {a: False for a in PER_ARC_ACTIONS})
        self.assertEqual(writes, [])


class _ArcCharges(ast.NodeVisitor):
    """Literal actions passed to a charge call keyed on an arc id."""

    def __init__(self):
        self.actions: set = set()

    def visit_Call(self, node):
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", "")
        if "charge" in name:
            mentions_arc = any("arc_id" in ast.unparse(a)
                               for a in [*node.args, *node.keywords])
            literals = [a.value for a in node.args
                        if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if mentions_arc and literals:
                self.actions.update(literals)
        self.generic_visit(node)


class PerArcListTests(unittest.TestCase):

    def test_every_per_arc_charge_is_listed(self):
        finder = _ArcCharges()
        for path in (ROOT / "routes").rglob("*.py"):
            finder.visit(ast.parse(path.read_text()))
        self.assertTrue(finder.actions, "no per-arc charge found in routes/")
        self.assertEqual(finder.actions - set(PER_ARC_ACTIONS), set(),
                         "a per-arc charge is missing from PER_ARC_ACTIONS")


if __name__ == "__main__":
    unittest.main()
