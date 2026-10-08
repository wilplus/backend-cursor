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

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
NAME = "financial_records_go_after_five_years.sql"
SQL = (MIGRATIONS / NAME).read_text()
BEFORE = (MIGRATIONS / "old_data_goes_on_a_schedule.sql").read_text()

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

    def test_it_is_0426_applied_twice_after_0425_and_its_suite_runs(self):
        manifest = (MIGRATIONS / "manifest.txt").read_text().splitlines()
        self.assertIn(f"0426\t{NAME}", manifest)
        self.assertLess(manifest.index("0425\tthe_purge_can_delete_job_plumbing.sql"),
                        manifest.index(f"0426\t{NAME}"))
        recipe = (ROOT / "tests/integration/confident_moment_rehearsal.sh").read_text()
        self.assertEqual(recipe.count(f"hard migrations/{NAME}"), 2)
        self.assertLess(recipe.index("hard migrations/the_purge_can_delete_job_plumbing.sql"),
                        recipe.index(f"hard migrations/{NAME}"))
        tier = (ROOT / "scripts/rehearsal_tier.sh").read_text()
        self.assertIn("tests/test_retention_cleaner_postgres.py", tier)

    def test_it_is_additive_and_closed_to_browsers(self):
        self.assertEqual(migrate.destructive_statements(SQL), [])
        self.assertTrue(migrate.looks_idempotent(SQL))
        self.assertNotIn("current_setting", SQL)
        self.assertNotIn("getenv", SQL)
        functions = set(re.findall(r"CREATE OR REPLACE FUNCTION public\.(\w+)\(", SQL))
        self.assertEqual(functions, {
            "retention_log_relations_v1", "retention_financial_cut_v1",
            "retention_financial_relations_v1", "retention_financial_condition_v1",
            "retention_due_financial_v1", "retention_due_financial_ids_v1",
            "retention_count_v1", "list_retention_due_v1", "retention_report_v1"})
        for name in functions:
            self.assertRegex(
                SQL, rf"REVOKE ALL ON FUNCTION public\.{name}\([^;]*\) "
                     r"FROM PUBLIC, anon, authenticated;", name)
        granted = set(re.findall(r"GRANT EXECUTE ON FUNCTION public\.(\w+)\(", SQL))
        self.assertEqual(granted, {
            "retention_log_relations_v1", "retention_financial_relations_v1",
            "list_retention_due_v1", "retention_report_v1"})
        self.assertNotRegex(SQL, r"GRANT[^;]*\b(INSERT|UPDATE|TRUNCATE)\b")
        self.assertNotRegex(SQL, r"GRANT[^;]*TO (PUBLIC|anon|authenticated)")

    def test_the_door_is_rule_4s_deletes_and_nothing_more(self):
        grants = re.findall(r"GRANT ([^;]*) ON public\.(\w+) TO service_role;", SQL)
        self.assertEqual(sorted(grants), [
            ("SELECT (id, created_at), DELETE", "llm_usage"),
            ("SELECT (id, created_at), DELETE", "token_ledger")])
        for table in ("llm_usage", "token_ledger"):
            self.assertIn(f"IF to_regclass('public.{table}') IS NOT NULL THEN", SQL)

    def test_the_log_list_loses_only_the_founders_bug_list(self):
        before = _function(BEFORE, "retention_log_relations_v1")
        after = _function(SQL, "retention_log_relations_v1")
        removed = "        ('dev_bugs', ARRAY[]::text[]),\n"
        self.assertIn(removed, before)
        self.assertNotIn("dev_bugs", after)
        self.assertEqual(after, before.replace(removed, ""))

    def test_the_counter_differs_from_0423_only_by_rule_4s_keys(self):
        before = _function(BEFORE, "retention_count_v1")
        after = _function(SQL, "retention_count_v1")
        old = r"'^(guests|audio|measurements|logs)\.[a-z0-9_.]+$'"
        new = r"'^(guests|audio|measurements|logs|financial)\.[a-z0-9_.]+$'"
        self.assertIn(old, before)
        self.assertEqual(after, before.replace(old, new))

    def test_the_listing_differs_from_0423_only_by_rule_4(self):
        before = _function(BEFORE, "list_retention_due_v1")
        after = _function(SQL, "list_retention_due_v1")
        added = ("ELSIF p_rule = 'financial' AND EXISTS ( SELECT 1 FROM "
                 "public.retention_financial_relations_v1() f WHERE f.relation = "
                 "p_relation) THEN RETURN QUERY SELECT x.row_id FROM "
                 "public.retention_due_financial_ids_v1( run.as_of, p_relation, "
                 "p_limit) x; ")
        self.assertEqual(_squash(after).count(added), 1)
        self.assertEqual(_squash(after).replace(added, ""), _squash(before))

    def test_the_report_differs_from_0423_only_by_rule_4(self):
        before = _function(BEFORE, "retention_report_v1")
        after = _function(SQL, "retention_report_v1")
        added = ("UNION ALL SELECT 4, 'financial records whose five years have "
                 "ended: ' || f.relation, f.due FROM "
                 "public.retention_due_financial_v1(p_as_of) f ")
        self.assertEqual(_squash(after).count(added), 1)
        self.assertEqual(_squash(after).replace(added, ""), _squash(before))

    def test_rule_4_reads_the_year_in_polish_time_and_waits_for_an_erasure(self):
        cut = _function(SQL, "retention_financial_cut_v1")
        self.assertIn("SELECT (date_trunc('year', p_as_of AT TIME ZONE 'Europe/Warsaw')"
                      "\n            - interval '5 years') AT TIME ZONE 'Europe/Warsaw'",
                      cut)
        condition = _squash(_function(SQL, "retention_financial_condition_v1"))
        for clause in ("t.created_at < $1 AND NOT EXISTS (",
                       "JOIN public.data_purge_requests r ON "
                       "r.acquisition_principal_id = p.id",
                       "p.user_id::text = t.%I AND r.state <> ''done''",
                       "AND r.project_id IS NULL /* 0378: account-wide purges only */"):
            self.assertIn(clause, condition)
        relations = _function(SQL, "retention_financial_relations_v1")
        self.assertEqual(re.findall(r"\('([a-z_]+)', '([a-z_]+)'\)", relations),
                         [("llm_usage", "user_id"), ("token_ledger", "user_id")])


if __name__ == "__main__":
    unittest.main()
