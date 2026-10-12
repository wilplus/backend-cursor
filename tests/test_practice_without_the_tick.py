"""Erasing practice made without the tick: preview first, the approved list only.

Founder decision 1 (2026-09-25). Pinned without a database:
  * the preview lists only the `unticked` group, with a hash of that list,
    and reports the other two groups without touching them;
  * execute refuses unless the fresh list hashes to the approved value, and
    then erases exactly that list through the E2 erasure step;
  * an unknown category, or an unreadable list, stops everything.
"""
from __future__ import annotations

import unittest
from unittest import mock

from services import practice_without_the_tick as tick


class _Rpc:
    def __init__(self, rows):
        self.rows = rows

    def execute(self):
        return type("Result", (), {"data": self.rows})()


class _Db:
    def __init__(self, rows, practices):
        self.rows, self.practices = rows, practices
        self.client = self

    def rpc(self, name, params):
        assert name == "list_practice_without_the_tick_v1" and params == {}
        return _Rpc(self.rows)

    def practice_ids_for_principal(self, principal):
        return self.practices.get(principal, [])


ROWS = [
    {"principal_id": "p-unticked", "category": "unticked", "practice_count": 2},
    {"principal_id": "p-empty", "category": "unticked", "practice_count": 0},
    {"principal_id": "p-ticked", "category": "ticked", "practice_count": 5},
    {"principal_id": "p-legacy", "category": "no_receipt", "practice_count": 3},
]
PRACTICES = {"p-unticked": ["b", "a"], "p-ticked": ["x"], "p-legacy": ["y"]}


class ExecuteTests(unittest.TestCase):


    def test_the_approved_list_and_only_it_is_erased(self):
        database = _Db(ROWS, PRACTICES)
        approved = tick.preview(database)["sha256"]
        with mock.patch.object(tick, "erase_practice_for_principal",
                               return_value={"complete": True}) as erase:
            out = tick.execute(database, approved_sha256=approved.upper())
        erase.assert_called_once_with(database=database, principal_id="p-unticked")
        self.assertTrue(out["complete"])


if __name__ == "__main__":
    unittest.main()
