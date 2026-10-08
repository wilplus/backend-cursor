"""A training withdrawal deletes the coach sheets about the speaker's Takes
(3.5 pack, file 22 E4; Privacy 3.5 §4a).

Pins:
  * turning the training switch off DELETES (not hides) every V4 moment-pick
    sheet, V4 surer sheet and blind block pick about the speaker's Takes;
  * other speakers' rows are untouched;
  * someone who holds the yes again is skipped; a failed read is named and
    never raises into the switch; the queued erasure job runs it again;
  * the database method deletes by Take only, in the three tables, and each
    table is a take-scoped delete in the purge registry (the registry stays
    consistent with what the withdrawal erases).

Run: python3 -m pytest tests/test_withdrawal_erases_sheets.py
"""
from __future__ import annotations

import unittest
from unittest import mock

from services import pair_consent as pc
from services import training_consent as tc
from services import training_corpus as corpus
from services.data_purge_registry import DEPENDENCIES

TABLES = ("v4_moment_pick_sheets", "v4_surer_sheets", "coach_block_pick")
POLICY = {"version": "training-v1", "onboarding_copy": "x", "approved_copy_sha256": "c" * 64,
          "terms_version": "t", "privacy_policy_version": "p"}


def _rows():
    return {table: [{"id": f"{table}-{take}-{i}", "take_session_id": take}
                    for take in ("tA1", "tA2", "tB1") for i in range(2)]
            for table in TABLES}


class _Db:
    """The switch's database, with the three tables in memory. Speaker A
    owns tA1 and tA2; speaker B owns tB1."""

    def __init__(self, *, active=True, fail_graph=False):
        self.active = active
        self.fail_graph = fail_graph
        self.tables = _rows()
        self.withdrawals: list[dict] = []

    def get_active_training_consent_policy(self):
        return POLICY

    def get_mlc2_training_consent_status(self, owner_id):
        return {"active": True, "grant_event_id": "g1"} if self.active else {"active": False}

    def record_mlc2_training_consent_withdrawal(self, **kwargs):
        self.withdrawals.append(kwargs)
        self.active = False
        return {"id": "w1"}

    def take_ids_for_principal(self, principal_id):
        if self.fail_graph:
            raise RuntimeError("subject graph unavailable")
        return {"principal-a": ["tA1", "tA2"], "principal-b": ["tB1"]}.get(principal_id, [])

    def delete_learning_sheets_for_takes(self, take_ids):
        out = {}
        for table, rows in self.tables.items():
            keep = [r for r in rows if r["take_session_id"] not in set(take_ids)]
            out[table] = len(rows) - len(keep)
            self.tables[table] = keep
        return out

    def list_due_training_corpus_items(self, principal_id):
        return []

    def takes_left(self, table):
        return sorted({r["take_session_id"] for r in self.tables[table]})


class WithdrawalTests(unittest.TestCase):
    def _withdraw(self, db, owner="principal-a"):
        with mock.patch("services.training_corpus.enqueue_corpus_purge", return_value=True) as queued:
            state = tc.handle(db, owner, "DELETE", {"idempotency_key": "k1"}, "test")
        queued.assert_called_once_with(owner)
        return state

    def test_withdraw_deletes_the_speakers_rows_and_only_theirs(self):
        db = _Db()
        state = self._withdraw(db)
        self.assertFalse(state["active"])
        self.assertEqual(len(db.withdrawals), 1)
        for table in TABLES:
            self.assertEqual(db.takes_left(table), ["tB1"], table)
            self.assertEqual(len(db.tables[table]), 2, table)

    def test_someone_holding_the_yes_is_skipped(self):
        db = _Db(active=True)
        with mock.patch("services.account_deletion.learning_stopped", return_value=False):
            out = pc.erase_withdrawn_sheets(db, "principal-a")
        self.assertEqual(out, {"skipped": "holds the training yes"})
        self.assertEqual(db.takes_left("coach_block_pick"), ["tA1", "tA2", "tB1"])

    def test_a_failed_read_is_named_and_never_breaks_the_switch(self):
        db = _Db(fail_graph=True)
        self.assertFalse(self._withdraw(db)["active"])
        self.assertEqual(db.takes_left("v4_surer_sheets"), ["tA1", "tA2", "tB1"])
        self.assertIn("unavailable", pc.erase_withdrawn_sheets(db, "principal-a"))
        # The queued erasure runs it again and finishes the job.
        db.fail_graph = False
        corpus.purge_due_copies("principal-a", database=db)
        for table in TABLES:
            self.assertEqual(db.takes_left(table), ["tB1"], table)

    def test_a_retry_is_a_no_op(self):
        db = _Db(active=False)
        first = pc.erase_withdrawn_sheets(db, "principal-a")
        self.assertEqual(first["deleted"], {t: 4 for t in TABLES})
        again = pc.erase_withdrawn_sheets(db, "principal-a")
        self.assertEqual(again["deleted"], {t: 0 for t in TABLES})


class DatabaseMethodTests(unittest.TestCase):
    def test_deletes_by_take_in_the_three_tables(self):
        try:
            from services.db import DatabaseService
        except Exception as e:  # pragma: no cover - needs app deps
            self.skipTest(f"needs app deps: {e}")
        calls: list[tuple] = []

        class _Query:
            def __init__(self, table):
                self.table = table

            def delete(self):
                calls.append((self.table, "delete"))
                return self

            def in_(self, column, values):
                calls.append((self.table, column, tuple(values)))
                self.values = values
                return self

            def execute(self):
                return mock.Mock(data=[{"id": v} for v in self.values])

        service = DatabaseService.__new__(DatabaseService)
        service.client = mock.Mock(table=lambda name: _Query(name))
        out = service.delete_learning_sheets_for_takes(["tA2", "tA1", "tA1", ""])
        self.assertEqual(out, {t: 2 for t in TABLES})
        self.assertEqual([c for c in calls if c[1] != "delete"],
                         [(t, "take_session_id", ("tA1", "tA2")) for t in TABLES])
        self.assertEqual(tuple(DatabaseService.LEARNING_SHEET_TABLES), TABLES)


class RegistryTests(unittest.TestCase):
    def test_each_erased_table_is_a_take_scoped_delete_in_the_purge_registry(self):
        for table in TABLES:
            deps = [d for d in DEPENDENCIES if d.relation == table and d.locator_kind == "take"]
            self.assertEqual(len(deps), 1, table)
            self.assertEqual((deps[0].selector_column, deps[0].disposition),
                             ("take_session_id", "delete"), table)


if __name__ == "__main__":
    unittest.main()
