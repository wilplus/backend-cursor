"""
STORY    As the founder, I want the clean-up of practice made without the
         consent tick to erase only the list I approved, so that no one who
         did tick loses practice.
OUTCOME
  O1  The preview lists only unticked people who have practice, with a hash;
      ticked and no_receipt people are only counted, never listed.
  O2  Execute with the approved hash erases exactly that list.
  O3  A list that changed since approval (hash mismatch) erases nobody.
  O4  An unknown category or an unreadable list stops everything.
PROVES   O1 -> test_the_preview_lists_only_unticked_people
         O2 -> test_the_approved_list_and_only_it_is_erased
         O3 -> test_a_changed_list_erases_nobody
         O4 -> test_an_unknown_category_or_unreadable_list_stops_everything
WHY      Founder decision 1 (2026-09-25): previewed, approved clean-up only.
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


class PreviewTests(unittest.TestCase):

    def test_the_preview_lists_only_unticked_people(self):
        out = tick.preview(_Db(ROWS, PRACTICES))
        self.assertEqual(out["erase"],
                         [{"principal_id": "p-unticked", "practice_ids": ["a", "b"]}])
        self.assertEqual(len(out["sha256"]), 64)
        self.assertEqual(out["untouched"], {
            "ticked_people": 1, "no_receipt_people": 1, "no_receipt_practices": 3})


class ExecuteTests(unittest.TestCase):

    def test_the_approved_list_and_only_it_is_erased(self):
        database = _Db(ROWS, PRACTICES)
        approved = tick.preview(database)["sha256"]
        with mock.patch.object(tick, "erase_practice_for_principal",
                               return_value={"complete": True}) as erase:
            out = tick.execute(database, approved_sha256=approved.upper())
        erase.assert_called_once_with(database=database, principal_id="p-unticked")
        self.assertTrue(out["complete"])

    def test_a_changed_list_erases_nobody(self):
        approved = tick.preview(_Db(ROWS, PRACTICES))["sha256"]
        changed = _Db(ROWS, {**PRACTICES, "p-empty": ["new"]})
        with mock.patch.object(tick, "erase_practice_for_principal") as erase:
            with self.assertRaises(SystemExit):
                tick.execute(changed, approved_sha256=approved)
        erase.assert_not_called()

    def test_an_unknown_category_or_unreadable_list_stops_everything(self):
        bad_rows = ROWS + [{"principal_id": "p-x", "category": "maybe"}]
        for database in (_Db(bad_rows, PRACTICES), _Db(None, PRACTICES)):
            with mock.patch.object(tick, "erase_practice_for_principal") as erase:
                with self.assertRaises(RuntimeError):
                    tick.execute(database, approved_sha256="0" * 64)
            erase.assert_not_called()


if __name__ == "__main__":
    unittest.main()
