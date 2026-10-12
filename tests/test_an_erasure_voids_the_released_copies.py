"""0456 (an_erasure_voids_the_released_copies.sql), read as text.

The released-lane rehearsal
(tests/test_an_erasure_voids_the_released_copies_postgres.py) executes it;
this pins what a reader of the file relies on:

  * it is 0456 in the manifest, applied twice by the released lane after
    0455, and its suite is in the tier;
  * it is additive: one transaction, no destructive statement, every
    function closed to browser roles and open to service_role, no
    environment variable read;
  * each of the four functions it re-issues is its LATEST definition in
    manifest order plus the one statement it is re-issued for, in the place
    that statement must run, and nothing else; the weekly refresh is not
    re-issued (new releases are the export's eligibility decision's);
  * the void has two reasons of its own, apart from the refresh's, and
    sends a voided release's pairs back to waiting as the refresh does.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
NAME = "an_erasure_voids_the_released_copies.sql"
VERSION = "0456"

sys.path.insert(0, str(ROOT / "scripts"))


def _manifest() -> list[tuple[str, str]]:
    rows = []
    for line in (MIGRATIONS / "manifest.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            version, filename = line.split("\t")
            rows.append((version, filename))
    return rows


#: Where each latest definition lives today. A later migration that
#: re-issues one of them must move this, and re-pin what it changes.
LATEST = {
    "stop_phase1_learning_v1": "a_deletion_completes_after_seven_days.sql",
    "request_project_deletion_v1": "a_project_deletion_can_be_requested.sql",
    "start_due_project_deletion_v1": "a_deletion_completes_after_seven_days.sql",
    "confirm_project_deletion_v1": "one_project_can_be_purged.sql",
}


class MigrationTests(unittest.TestCase):

    def test_it_is_0456_applied_twice_after_0455_and_its_suite_runs(self):
        manifest = _manifest()
        self.assertIn((VERSION, NAME), manifest)
        self.assertEqual(manifest[manifest.index((VERSION, NAME)) - 1],
                         ("0455", "a_failed_export_voids_its_release.sql"))
        recipe = (ROOT / "tests/integration/confident_moment_rehearsal.sh").read_text()
        self.assertEqual(recipe.count(f"hard migrations/{NAME}"), 2)
        first = recipe.index(f"hard migrations/{NAME}")
        self.assertLess(recipe.rindex("hard migrations/a_failed_export_voids_its_release.sql"),
                        first)
        # Released lane only: inside the nearest `if [ "$LANE" = "released" ]`.
        opened = recipe.rindex('if [ "$LANE" = "released" ]; then\n', 0, first)
        self.assertNotIn("\nfi", recipe[opened:first])
        self.assertTrue(recipe[first:].startswith(
            f"hard migrations/{NAME}\n  hard migrations/{NAME}\nfi\n"))
        tier = (ROOT / "scripts/rehearsal_tier.sh").read_text()
        self.assertIn("tests/test_an_erasure_voids_the_released_copies_postgres.py", tier)


if __name__ == "__main__":
    unittest.main()
