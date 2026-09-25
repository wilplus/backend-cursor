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


class PreviewTests(unittest.TestCase):

    def test_only_the_unticked_with_practice_are_listed_and_hashed(self):
        out = tick.preview(_Db(ROWS, PRACTICES))
        self.assertEqual(out["erase"], [{"principal_id": "p-unticked",
                                         "practice_ids": ["a", "b"]}])
        self.assertEqual(out["erase_practices"], 2)
        self.assertRegex(out["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(out["untouched"], {
            "ticked_people": 1, "no_receipt_people": 1, "no_receipt_practices": 3})

    def test_the_hash_follows_the_list(self):
        first = tick.preview(_Db(ROWS, PRACTICES))["sha256"]
        grown = tick.preview(_Db(ROWS, {**PRACTICES, "p-unticked": ["a", "b", "c"]}))
        self.assertNotEqual(first, grown["sha256"])

    def test_an_unknown_category_or_unreadable_list_stops_everything(self):
        with self.assertRaises(RuntimeError):
            tick.preview(_Db([{"principal_id": "p", "category": "maybe"}], {}))
        with self.assertRaises(RuntimeError):
            tick.preview(_Db(None, {}))


class ExecuteTests(unittest.TestCase):

    def test_a_changed_list_is_refused_and_nothing_is_erased(self):
        with mock.patch.object(tick, "erase_practice_for_principal") as erase:
            with self.assertRaises(SystemExit):
                tick.execute(_Db(ROWS, PRACTICES), approved_sha256="0" * 64)
            with self.assertRaises(SystemExit):
                tick.execute(_Db(ROWS, PRACTICES), approved_sha256="")
            erase.assert_not_called()

    def test_the_approved_list_and_only_it_is_erased(self):
        database = _Db(ROWS, PRACTICES)
        approved = tick.preview(database)["sha256"]
        with mock.patch.object(tick, "erase_practice_for_principal",
                               return_value={"complete": True}) as erase:
            out = tick.execute(database, approved_sha256=approved.upper())
        erase.assert_called_once_with(database=database, principal_id="p-unticked")
        self.assertTrue(out["complete"])

    def test_an_unfinished_erasure_is_reported(self):
        database = _Db(ROWS, PRACTICES)
        approved = tick.preview(database)["sha256"]
        with mock.patch.object(tick, "erase_practice_for_principal",
                               return_value={"complete": False, "failed": 1}):
            self.assertFalse(tick.execute(database, approved_sha256=approved)["complete"])


class ScriptTests(unittest.TestCase):

    def test_the_default_is_a_preview_and_execute_needs_the_hash(self):
        import importlib.util
        import pathlib
        path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "erase_practice_without_the_tick.py"
        spec = importlib.util.spec_from_file_location("erase_script", path)
        script = importlib.util.module_from_spec(spec)
        with mock.patch.dict("sys.modules", {}):
            spec.loader.exec_module(script)
        with mock.patch.object(script, "preview", return_value={"mode": "preview"}) as prev, \
             mock.patch.object(script, "execute") as run:
            self.assertEqual(script.main([]), 0)
            prev.assert_called_once()
            with self.assertRaises(SystemExit):
                script.main(["--execute"])
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
