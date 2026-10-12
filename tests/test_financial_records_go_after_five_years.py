"""0426 (financial_records_go_after_five_years.sql), read as text.

The released-lane rehearsal (tests/test_retention_cleaner_postgres.py)
executes it; this pins what a reader of the file relies on:

  * it is 0426 in the manifest, applied twice by the released lane after
    0425, and its suite is in the tier;
  * it is additive: no destructive statement, no environment variable,
    every function closed to browser roles; the service role gets rule 4's
    door (SELECT (id, created_at), DELETE on the two financial tables, each
    guarded on its table existing) and nothing else;
  * the four functions it re-issues stay 0423's text plus the one change
    each is for: the log list loses dev_bugs (N50 C4 B), the counter takes
    rule 4's keys, the listing and the report gain rule 4 (N50 P7);
  * rule 4 reads the financial year in Polish time and leaves an account
    under erasure to its purge, account-wide purges only (0378).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
NAME = "financial_records_go_after_five_years.sql"
SQL = (MIGRATIONS / NAME).read_text()
BEFORE = (MIGRATIONS / "old_data_goes_on_a_schedule.sql").read_text()

sys.path.insert(0, str(ROOT / "scripts"))


def _function(sql: str, name: str) -> str:
    start = sql.index(f"CREATE OR REPLACE FUNCTION public.{name}(")
    body = sql.index("$$", start)
    return sql[start:sql.index("$$;", body + 2) + 3]


class MigrationTests(unittest.TestCase):


    def test_the_counter_differs_from_0423_only_by_rule_4s_keys(self):
        before = _function(BEFORE, "retention_count_v1")
        after = _function(SQL, "retention_count_v1")
        old = r"'^(guests|audio|measurements|logs)\.[a-z0-9_.]+$'"
        new = r"'^(guests|audio|measurements|logs|financial)\.[a-z0-9_.]+$'"
        self.assertIn(old, before)
        self.assertEqual(after, before.replace(old, new))


if __name__ == "__main__":
    unittest.main()
