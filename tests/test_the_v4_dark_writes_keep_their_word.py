"""0457 (the_v4_dark_writes_keep_their_word.sql), read as text.

The released-lane rehearsal
(tests/test_the_v4_dark_writes_keep_their_word_postgres.py) executes it;
this pins what a reader of the file relies on:

  * it is 0457 in the manifest, after 0456, and its suite is in the tier;
  * it is additive: one transaction, no destructive statement, no table or
    column created or altered, no environment variable read, no new grant
    beyond EXECUTE to service_role on the two functions it re-issues;
  * the two re-issued bodies are 0451's and 0452's, with only the 0457
    lines added (nothing of theirs is lost);
  * the sheet triggers guard UPDATE only, so the purge's DELETE still runs.
"""
from __future__ import annotations

import difflib
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
NAME = "the_v4_dark_writes_keep_their_word.sql"
VERSION = "0457"
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


def _added(old_file: str, name: str) -> list[str]:
    """The lines 0457 adds to an earlier body; fails if any line is lost."""
    old = _function((MIGRATIONS / old_file).read_text(), name).splitlines()
    new = _function(SQL, name).splitlines()
    removed = [line for line in difflib.ndiff(old, new) if line.startswith("- ")]
    replaced = [line for line in removed
                if "abs((r ->> 'willfident')::numeric - read.willfident) >= 1e-9" not in line]
    assert replaced == [], replaced
    return [line[2:] for line in difflib.ndiff(old, new) if line.startswith("+ ")]


class MigrationTests(unittest.TestCase):

    def test_it_is_0457_after_0456_and_its_suite_runs(self):
        manifest = _manifest()
        self.assertIn((VERSION, NAME), manifest)
        self.assertEqual(manifest[manifest.index((VERSION, NAME)) - 1],
                         ("0456", "an_erasure_voids_the_released_copies.sql"))
        tier = (ROOT / "scripts/rehearsal_tier.sh").read_text()
        released = next(line for line in tier.splitlines()
                        if line.lstrip().startswith('"confident-moment released|'))
        self.assertIn("tests/test_the_v4_dark_writes_keep_their_word_postgres.py", released)

    def test_it_is_one_additive_transaction_closed_to_browsers(self):
        self.assertEqual(migrate.destructive_statements(SQL), [])
        self.assertEqual(migrate.unbalanced_delimiters(SQL), [])
        body = _squash(SQL)
        self.assertTrue(body.startswith("BEGIN;"))
        self.assertTrue(body.endswith("COMMIT;"))
        self.assertEqual((body.count("BEGIN;"), body.count("COMMIT;")), (1, 1))
        for statement in ("CREATE TABLE", "ALTER TABLE", "TRUNCATE", "DELETE FROM",
                          "current_setting", "GRANT INSERT", "GRANT UPDATE",
                          "GRANT DELETE", "GRANT SELECT", "GRANT ALL", "DO $$"):
            self.assertNotIn(statement, body, statement)
        self.assertEqual(re.findall(r"CREATE OR REPLACE FUNCTION public\.(\w+)\(", SQL),
                         ["compute_v4_pick_outcomes_v1", "record_v4_picks_v1",
                          "reject_v4_pick_sheet_rewrite_v1",
                          "reject_v4_surer_sheet_rewrite_v1"])
        for signature in ("compute_v4_pick_outcomes_v1(uuid)",
                          "record_v4_picks_v1(uuid, jsonb)",
                          "reject_v4_pick_sheet_rewrite_v1()",
                          "reject_v4_surer_sheet_rewrite_v1()"):
            self.assertIn(f"REVOKE ALL ON FUNCTION public.{signature} "
                          "FROM PUBLIC, anon, authenticated;", body)
        self.assertEqual(re.findall(r"GRANT EXECUTE ON FUNCTION public\.(\w+)", body),
                         ["compute_v4_pick_outcomes_v1", "record_v4_picks_v1"])

    def test_outcomes_keep_0451s_body_and_wait_for_both_maps(self):
        added = _squash("\n".join(_added("each_pick_learns_if_the_paragraph_rose.sql",
                                         "compute_v4_pick_outcomes_v1")))
        self.assertEqual(added.count("FROM public.v4_moment_paragraphs"), 2)
        self.assertIn("take_session_id = v_prev.id", added)
        self.assertIn("take_session_id = v_next.id", added)
        self.assertIn("RETURN jsonb_build_object('outcome', 'no_map');", added)
        body = _squash(_function(SQL, "compute_v4_pick_outcomes_v1"))
        self.assertLess(body.index("'not_ready'"), body.index("'no_map'"))
        self.assertLess(body.index("'no_map'"), body.index("INSERT INTO public.v4_pick_outcomes"))

    def test_picks_keep_0452s_body_and_close_its_three_gaps(self):
        added = _squash("\n".join(_added("the_v4_picker_runs_dark_beside_v3.sql",
                                         "record_v4_picks_v1")))
        self.assertIn("OR read.block_id IS NULL", added)
        self.assertIn("THEN read.willfident IS NULL OR abs((r ->> 'willfident')::numeric "
                      "- read.willfident) >= 1e-9", added)
        self.assertIn("? (r ->> 'v3_snippet_id')", added)
        self.assertIn("trunc((r ->> 'rank_position')::numeric)", added)

    def test_the_sheet_triggers_guard_updates_only(self):
        body = _squash(SQL)
        for table, function in (("v4_moment_pick_sheets", "reject_v4_pick_sheet_rewrite_v1"),
                                ("v4_surer_sheets", "reject_v4_surer_sheet_rewrite_v1")):
            self.assertIn(f"BEFORE UPDATE ON public.{table} FOR EACH ROW "
                          f"EXECUTE FUNCTION public.{function}();", body)
            self.assertNotIn(f"DELETE ON public.{table}", body)
            guard = _squash(_function(SQL, function))
            self.assertIn("IF OLD.answered_at IS NOT NULL THEN "
                          "RAISE EXCEPTION 'V4_SHEET_ANSWERED_ONCE';", guard)
            self.assertIn("RAISE EXCEPTION 'V4_SHEET_QUESTION_IS_FIXED';", guard)
            self.assertNotIn("SECURITY DEFINER", guard)
        # The answer columns are exactly what the app's answer writes.
        from services.db import DatabaseService
        import inspect
        pick = inspect.getsource(DatabaseService.answer_v4_pick_sheet)
        surer = inspect.getsource(DatabaseService.answer_v4_surer_sheet)
        for column in ("answer_snippet_id", "none_needs_it", "answered_at"):
            self.assertIn(f'"{column}"', pick)
            self.assertIn(f"'{column}'", _function(SQL, "reject_v4_pick_sheet_rewrite_v1"))
        for column in ("answer", "chosen_text", "rejected_text", "answered_at"):
            self.assertIn(f'"{column}"', surer)
            self.assertIn(f"'{column}'", _function(SQL, "reject_v4_surer_sheet_rewrite_v1"))


if __name__ == "__main__":
    unittest.main()
