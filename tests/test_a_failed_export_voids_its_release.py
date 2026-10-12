"""0455 (a_failed_export_voids_its_release.sql), read as text.

The released-lane rehearsal
(tests/test_a_failed_export_voids_its_release_postgres.py) executes it;
this pins what a reader of the file relies on:

  * it is 0455 in the manifest, applied twice by the released lane after
    0454, and its suite is in the tier;
  * it is additive: one transaction, no destructive statement, no table or
    column touched, no environment variable read, its one function closed
    to browser roles and open to service_role;
  * it re-issues nothing: the function is new, and the weekly refresh
    (latest 0422) and the mark (0405) stay as they stand;
  * the void has a reason of its own, voids only a live release, and sends
    a voided release's pairs back to waiting with the refresh's own
    statement;
  * the export calls it by that name, and writes the release row before
    any object.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
NAME = "a_failed_export_voids_its_release.sql"
FUNCTION = "void_failed_pair_release_v1"
SQL = (MIGRATIONS / NAME).read_text()

sys.path.insert(0, str(ROOT / "scripts"))


def _function(sql: str, name: str) -> str:
    start = sql.index(f"CREATE OR REPLACE FUNCTION public.{name}(")
    body = sql.index("$$", start)
    return sql[start:sql.index("$$;", body + 2) + 3]


def _squash(text: str) -> str:
    text = re.sub(r"--[^\n]*", "", text)
    return re.sub(r"\s+", " ", text).strip()


class MigrationTests(unittest.TestCase):


    def test_its_pairs_go_back_to_waiting_as_the_refresh_sends_them(self):
        void = _squash(_function(SQL, FUNCTION))
        self.assertIn("UPDATE public.feedback_pairs pair SET release_id = NULL, "
                      "exported_at = NULL WHERE pair.release_id = p_release_id;", void)
        refresh = _squash(_function(
            (MIGRATIONS / "a_deletion_completes_after_seven_days.sql").read_text(),
            "refresh_feedback_pair_consent_v1"))
        self.assertIn("UPDATE public.feedback_pairs pair SET release_id = NULL, "
                      "exported_at = NULL", refresh)


if __name__ == "__main__":
    unittest.main()
