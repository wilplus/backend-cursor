"""0422 (a_deletion_completes_after_seven_days.sql), read as text.

The released-lane rehearsal (tests/test_a_deletion_completes_after_seven_days_postgres.py)
executes it; this pins what a reader of the file relies on:

  * it is in the manifest, applied twice by the released lane, and its
    suite is in the tier;
  * it is additive: no destructive statement, RLS on both new tables, every
    function closed to browser roles and open to service_role;
  * the five functions it re-issues stay what they were plus the one change
    each is for: the status function keeps every key 0358 returns, 0310's
    purge request differs only by the learning stop, 0405's refresh and
    0375's corpus door keep their statements;
  * no environment variable is read (CONFIG-FIRST has nothing to wait for).
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
NAME = "a_deletion_completes_after_seven_days.sql"
SQL = (MIGRATIONS / NAME).read_text()

sys.path.insert(0, str(ROOT / "scripts"))
import migrate  # noqa: E402


def _function(sql: str, name: str) -> str:
    start = sql.index(f"CREATE OR REPLACE FUNCTION public.{name}(")
    body = sql.index("$$", start)
    return sql[start:sql.index("$$;", body + 2) + 3]


def _squash(text: str) -> str:
    text = re.sub(r"--[^\n]*", "", text)
    return re.sub(r"\s+", " ", text).strip()


class MigrationTests(unittest.TestCase):

    def test_it_is_0422_applied_twice_and_its_suite_runs(self):
        manifest = (MIGRATIONS / "manifest.txt").read_text().splitlines()
        self.assertIn(f"0422\t{NAME}", manifest)
        recipe = (ROOT / "tests/integration/confident_moment_rehearsal.sh").read_text()
        self.assertEqual(recipe.count(f"hard migrations/{NAME}"), 2)
        tier = (ROOT / "scripts/rehearsal_tier.sh").read_text()
        self.assertIn("tests/test_a_deletion_completes_after_seven_days_postgres.py", tier)

    def test_it_is_additive_and_closed_to_browsers(self):
        self.assertEqual(migrate.destructive_statements(SQL), [])
        for table in ("account_deletion_requests", "deletion_completion_lease"):
            self.assertIn(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY", SQL)
            self.assertIn(f"CREATE TABLE IF NOT EXISTS public.{table}", SQL)
        functions = set(re.findall(r"CREATE OR REPLACE FUNCTION public\.(\w+)\(", SQL))
        self.assertGreaterEqual(len(functions), 14)
        for name in functions:
            self.assertRegex(SQL, rf"REVOKE ALL ON FUNCTION public\.{name}\(",
                             name)
            if not name.startswith("guard_"):
                self.assertRegex(
                    SQL, rf"GRANT EXECUTE ON FUNCTION public\.{name}\([^;]*\)\s+TO service_role;",
                    name)
        self.assertNotIn("current_setting", SQL)
        self.assertNotIn("GRANT INSERT", SQL)

    def test_the_status_function_keeps_every_key_0358_returns(self):
        before = _function((MIGRATIONS / "status_knows_a_reacceptance.sql").read_text(),
                           "get_phase1_processing_authorization_v1")
        after = _function(SQL, "get_phase1_processing_authorization_v1")
        keys = re.compile(r"'([a-z_0-9]+)',")

        def returned(body: str) -> set:
            return set(keys.findall(body[body.rindex("RETURN jsonb_build_object("):]))

        self.assertEqual(returned(before), returned(after))
        self.assertIn("reacceptance_required", returned(after))
        self.assertIn("account_deletion_requests", after)
        self.assertIn("'pending', 'started', 'done'", after)

    def test_the_purge_request_differs_from_0310_only_by_the_learning_stop(self):
        before = _function((MIGRATIONS / "add_phase1_processing_boundary.sql").read_text(),
                           "request_phase1_purge_v1")
        after = _function(SQL, "request_phase1_purge_v1")
        added = "PERFORM public.stop_phase1_learning_v1(p_acquisition_principal_id);"
        self.assertEqual(after.count(added), 1)
        self.assertEqual(_squash(after.replace(added, "")), _squash(before))

    def test_the_refresh_and_the_corpus_door_keep_their_statements(self):
        refresh_before = _function((MIGRATIONS / "a_pair_remembers_the_yes.sql").read_text(),
                                   "refresh_feedback_pair_consent_v1")
        refresh_after = _function(SQL, "refresh_feedback_pair_consent_v1")
        for line in ("SET release_id = NULL, exported_at = NULL",
                     "LEFT JOIN public.training_consent_active_grants grant_row",
                     "'voided_releases', v_voided"):
            self.assertIn(line, refresh_before)
            self.assertIn(line, refresh_after)
        self.assertIn("'consent_withdrawn'", refresh_after)
        self.assertIn("phase1_learning_stopped_v1(pair.owner_principal_id)", refresh_after)
        door_before = _function((MIGRATIONS / "training_copies_are_copies.sql").read_text(),
                                "record_training_corpus_item_v1")
        door_after = _function(SQL, "record_training_corpus_item_v1")
        stop = ("IF public.phase1_learning_stopped_v1(p_acquisition_principal_id) THEN "
                "RAISE EXCEPTION 'TRAINING_CORPUS_SERVICE_ENDING'; END IF; ")
        self.assertIn(stop, _squash(door_after))
        self.assertEqual(_squash(door_after).replace(stop, ""), _squash(door_before))

    def test_a_project_cancel_closes_with_its_window(self):
        before = _function((MIGRATIONS / "a_project_deletion_can_be_requested.sql").read_text(),
                           "cancel_project_deletion_v1")
        after = _function(SQL, "cancel_project_deletion_v1")
        window = ("IF now() >= request.due_at THEN RAISE EXCEPTION "
                  "'PROJECT_DELETION_WINDOW_CLOSED'; END IF;")
        self.assertIn(window, _squash(after))
        self.assertEqual(_squash(after).replace(window + " ", ""), _squash(before))


if __name__ == "__main__":
    unittest.main()
