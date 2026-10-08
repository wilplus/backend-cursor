"""0447 (a_failed_export_voids_its_release.sql), read as text.

The released-lane rehearsal
(tests/test_a_failed_export_voids_its_release_postgres.py) executes it;
this pins what a reader of the file relies on:

  * it is 0447 in the manifest, applied twice by the released lane after
    0446, and its suite is in the tier;
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

import inspect
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
NAME = "a_failed_export_voids_its_release.sql"
VERSION = "0447"
FUNCTION = "void_failed_pair_release_v1"
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


def _manifest() -> list[tuple[str, str]]:
    rows = []
    for line in (MIGRATIONS / "manifest.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            version, filename = line.split("\t")
            rows.append((version, filename))
    return rows


def _earlier() -> list[str]:
    """Every manifest file before 0447, in order."""
    out = []
    for version, filename in _manifest():
        if version == VERSION:
            return out
        out.append(filename)
    raise AssertionError(f"{VERSION} is not in the manifest")


class MigrationTests(unittest.TestCase):

    def test_it_is_0447_applied_twice_after_0446_and_its_suite_runs(self):
        manifest = _manifest()
        self.assertIn((VERSION, NAME), manifest)
        self.assertEqual(manifest[manifest.index((VERSION, NAME)) - 1],
                         ("0446", "a_coach_may_change_their_answer.sql"))
        recipe = (ROOT / "tests/integration/confident_moment_rehearsal.sh").read_text()
        self.assertEqual(recipe.count(f"hard migrations/{NAME}"), 2)
        first = recipe.index(f"hard migrations/{NAME}")
        self.assertLess(recipe.rindex("hard migrations/a_coach_may_change_their_answer.sql"),
                        first)
        # Released lane only: inside the nearest `if [ "$LANE" = "released" ]`.
        opened = recipe.rindex('if [ "$LANE" = "released" ]; then\n', 0, first)
        self.assertNotIn("\nfi", recipe[opened:first])
        self.assertTrue(recipe[first:].startswith(
            f"hard migrations/{NAME}\n  hard migrations/{NAME}\nfi\n"))
        tier = (ROOT / "scripts/rehearsal_tier.sh").read_text()
        released = next(line for line in tier.splitlines()
                        if line.lstrip().startswith('"confident-moment released|'))
        self.assertIn("tests/test_a_failed_export_voids_its_release_postgres.py", released)

    def test_it_is_one_additive_transaction_closed_to_browsers(self):
        self.assertEqual(migrate.destructive_statements(SQL), [])
        self.assertEqual(migrate.unbalanced_delimiters(SQL), [])
        body = _squash(SQL)
        self.assertTrue(body.startswith("BEGIN;"))
        self.assertTrue(body.endswith("COMMIT;"))
        self.assertEqual((body.count("BEGIN;"), body.count("COMMIT;")), (1, 1))
        for statement in ("CREATE TABLE", "ALTER TABLE", "DROP ", "TRUNCATE",
                          "DELETE FROM", "current_setting", "GRANT INSERT",
                          "GRANT UPDATE", "GRANT DELETE", "GRANT ALL", "CONSTRAINT",
                          "DO $$", "INSERT INTO"):
            self.assertNotIn(statement, body, statement)
        self.assertEqual(re.findall(r"CREATE OR REPLACE FUNCTION public\.(\w+)\(", SQL),
                         [FUNCTION])
        self.assertIn(f"REVOKE ALL ON FUNCTION public.{FUNCTION}(UUID) "
                      "FROM PUBLIC, anon, authenticated;", body)
        self.assertIn(f"GRANT EXECUTE ON FUNCTION public.{FUNCTION}(UUID) TO service_role;",
                      body)
        self.assertIn("SECURITY DEFINER SET search_path = public", _function(SQL, FUNCTION))

    def test_it_reissues_nothing(self):
        for filename in _earlier():
            text = (MIGRATIONS / filename).read_text()
            self.assertNotIn(FUNCTION, text, filename)
        # The refresh still voids only what a pair points at, under its own
        # two reasons; the mark still refuses the whole set. Neither is here.
        self.assertNotIn("refresh_feedback_pair_consent_v1(", _squash(SQL))
        self.assertNotIn("mark_feedback_pairs_released_v1(", _squash(SQL))

    def test_the_void_has_a_reason_of_its_own_and_reaches_only_a_live_release(self):
        void = _squash(_function(SQL, FUNCTION))
        for filename in _earlier():
            self.assertNotIn("'export_failed'", (MIGRATIONS / filename).read_text(), filename)
        self.assertIn("UPDATE public.pair_releases release SET voided_at = now(), "
                      "voided_reason = 'export_failed' WHERE release.id = p_release_id "
                      "AND release.voided_at IS NULL;", void)
        self.assertIn("RAISE EXCEPTION 'PAIR_RELEASE_UNKNOWN';", void)
        self.assertEqual(void.count("UPDATE public.pair_releases"), 1)
        self.assertNotIn("purged_at", void)
        self.assertNotIn("releasable", void)
        self.assertNotIn("consent", void)

    def test_its_pairs_go_back_to_waiting_as_the_refresh_sends_them(self):
        void = _squash(_function(SQL, FUNCTION))
        self.assertIn("UPDATE public.feedback_pairs pair SET release_id = NULL, "
                      "exported_at = NULL WHERE pair.release_id = p_release_id;", void)
        refresh = _squash(_function(
            (MIGRATIONS / "a_deletion_completes_after_seven_days.sql").read_text(),
            "refresh_feedback_pair_consent_v1"))
        self.assertIn("UPDATE public.feedback_pairs pair SET release_id = NULL, "
                      "exported_at = NULL", refresh)

    def test_the_export_calls_it_and_writes_the_row_before_any_object(self):
        from services import pair_release
        from services.db import DatabaseService
        self.assertIn(f'"{FUNCTION}"', inspect.getsource(DatabaseService.void_failed_pair_release))
        self.assertIn("database.void_failed_pair_release(release_id)",
                      inspect.getsource(pair_release._void_failed))
        export = inspect.getsource(pair_release.export_surface)
        week = export.index("database.get_pair_release_for_week(")
        row = export.index("database.insert_pair_release(")
        self.assertLess(week, export.index("decide(database"))
        self.assertLess(row, export.index("storage.put("))
        self.assertLess(export.index("database.insert_pair_release_owners("),
                        export.index("storage.put("))
        self.assertLess(export.rindex("storage.put("),
                        export.index("database.mark_feedback_pairs_released("))


if __name__ == "__main__":
    unittest.main()
