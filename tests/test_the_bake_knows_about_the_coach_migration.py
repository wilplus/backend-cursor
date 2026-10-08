"""0428 (the_bake_knows_about_the_coach.sql), read as text.

The bake lane (tests/test_ideal_text_feedback_bake_postgres.py, built by
scripts/rehearsal_tier.sh) executes it; this pins what a reader of the file
relies on:

  * it is in the manifest after 0351 and after the coach's request chain it
    reads, the bake lane applies it twice after that chain, and the bake
    suite is in the tier;
  * it is one transaction, additive, reads no environment, and keeps the
    function closed to browser roles and open to service_role;
  * it re-issues ONE function, and that function differs from 0351's only by
    the coach's branch: the writer, the reader and what a bake stores stay
    0345's and 0351's;
  * every time column a coach request carries is accounted for, so a
    withdrawal or an update time added later fails here until the rule has
    learned it;
  * the latest definition in manifest order still reads all five tables.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
NAME = "the_bake_knows_about_the_coach.sql"
SQL = (MIGRATIONS / NAME).read_text()
PREVIOUS = "the_bake_knows_about_answers_and_its_own_start.sql"
FUNCTION = "ideal_text_feedback_surface_touched_at_v1"
#: The coach's request chain the branch reads, in manifest order.
REQUEST_CHAIN = (
    "a_coach_hears_when_nothing_fits", "every_judgement_reaches_the_coach",
    "a_coach_answers_in_words_too", "a_word_for_this_take",
    "a_moment_opens_before_it_is_judged",
)

sys.path.insert(0, str(ROOT / "scripts"))
import migrate  # noqa: E402

#: The one branch 0428 adds, exactly as the file writes it.
BRANCH = """    UNION ALL
    -- What the coach made of a bookmark (0428): the request rose, the coach
    -- answered, the coach shared. A request names its take by text; the
    -- take names the arc.
    SELECT max(GREATEST(request.created_at, request.resolved_at,
                        request.shared_at)) AS touched
      FROM public.exercise_coach_requests request
      JOIN public.v2_sessions session
        ON session.id::text = request.take_session_id
     WHERE session.arc_id::text = p_arc_id
"""

#: Every time column on a coach request, and whether its write can change
#: the stored block. The True ones are read by the branch.
REQUEST_TIMES = {
    "created_at": True,    # the request rose: the open promise rides the bookmark
    "resolved_at": True,   # the coach answered: open becomes answered
    "shared_at": True,     # the exercise, the words and the video ride it
    "drafted_at": False,   # 0402: the model's draft for the coach; never served
    "answered_at": False,  # 0408: the speaker's judgement; the answer routes count it
}

#: The tables the rule reads after 0428.
SURFACE = (
    "intervention_decisions", "user_suggestion_feedback",
    "take_feedback_self_report", "feedback_v3_owner_responses",
    "exercise_coach_requests",
)


def _function(sql: str, name: str) -> str:
    start = sql.index(f"CREATE OR REPLACE FUNCTION public.{name}(")
    body = sql.index("$$", start)
    return sql[start:sql.index("$$;", body + 2) + 3]


def _squash(text: str) -> str:
    text = re.sub(r"--[^\n]*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _manifest() -> list[str]:
    """Migration files in the order the runner applies them."""
    out: list[str] = []
    for line in (MIGRATIONS / "manifest.txt").read_text().splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and not line.lstrip().startswith("#"):
            out.append(parts[1].strip())
    return out


def _defines(name: str) -> bool:
    text = (MIGRATIONS / name).read_text()
    return f"CREATE OR REPLACE FUNCTION public.{FUNCTION}(" in text


class MigrationTests(unittest.TestCase):

    def test_it_follows_0351_and_the_request_chain_and_the_lane_applies_it(self):
        lines = (MIGRATIONS / "manifest.txt").read_text().splitlines()
        self.assertIn(f"0428\t{NAME}", lines)
        manifest = _manifest()
        self.assertIn(NAME, manifest)
        at = manifest.index(NAME)
        self.assertGreater(at, manifest.index(PREVIOUS))
        for chain in REQUEST_CHAIN:
            self.assertLess(manifest.index(f"{chain}.sql"), at, chain)
        tier = (ROOT / "scripts/rehearsal_tier.sh").read_text()
        lane = tier[tier.index("BAKE=willab_bake_rehearsal"):
                    tier.index("MODELGATE=")]
        self.assertIn(
            "sql_file $BAKE migrations/$m.sql; sql_file $BAKE migrations/$m.sql",
            lane)
        order = [lane.index(f" {m}") for m in
                 ("the_bake_knows_about_answers_and_its_own_start",
                  *REQUEST_CHAIN, NAME[:-len(".sql")])]
        self.assertEqual(order, sorted(order))
        self.assertIn(
            "bake|IDEAL_TEXT_FEEDBACK_BAKE_REHEARSAL_DSN|willab_bake_rehearsal|"
            "tests/test_ideal_text_feedback_bake_postgres.py", tier)

    def test_it_is_one_additive_transaction_with_no_env_read(self):
        body = migrate.strip_sql_comments(SQL).strip()
        self.assertEqual(migrate.destructive_statements(SQL), [])
        self.assertEqual(migrate.unbalanced_delimiters(SQL), [])
        self.assertTrue(migrate.looks_idempotent(SQL))
        self.assertTrue(body.startswith("BEGIN;"))
        self.assertTrue(body.endswith("COMMIT;"))
        self.assertEqual(body.count("BEGIN;"), 1)
        self.assertEqual(body.count("COMMIT;"), 1)
        self.assertNotIn("current_setting", body)
        self.assertNotIn("DROP ", body.upper())

    def test_it_re_issues_one_function_and_keeps_its_door(self):
        body = migrate.strip_sql_comments(SQL)
        self.assertEqual(
            re.findall(r"CREATE OR REPLACE FUNCTION public\.(\w+)\(", body),
            [FUNCTION])
        self.assertRegex(
            body, rf"REVOKE ALL ON FUNCTION public\.{FUNCTION}\(\s*TEXT\) FROM PUBLIC;")
        self.assertIn("ARRAY['anon', 'authenticated']", body)
        self.assertIn("'REVOKE ALL ON FUNCTION %s FROM %I'", body)
        self.assertIn("'GRANT EXECUTE ON FUNCTION %s TO service_role'", body)
        self.assertIn(f"'public.{FUNCTION}(text)'", body)
        for untouched in ("read_ideal_text_feedback_bake_v1",
                          "write_ideal_text_feedback_bake_v1",
                          "ideal_text_feedback_bakes"):
            self.assertNotIn(untouched, body)

    def test_0351_held_the_latest_definition_before_it(self):
        manifest = _manifest()
        earlier = [name for name in manifest[:manifest.index(NAME)]
                   if _defines(name)]
        self.assertEqual(earlier[-1], PREVIOUS)

    def test_the_rule_differs_from_0351_only_by_the_coach_branch(self):
        before = _function((MIGRATIONS / PREVIOUS).read_text(), FUNCTION)
        after = _function(SQL, FUNCTION)
        self.assertEqual(after.count(BRANCH), 1)
        self.assertEqual(_squash(after.replace(BRANCH, "")), _squash(before))

    def test_the_branch_reads_each_time_that_changes_the_block(self):
        branch = _squash(BRANCH)
        for column, feeds in REQUEST_TIMES.items():
            with self.subTest(column=column):
                if feeds:
                    self.assertIn(f"request.{column}", branch)
                else:
                    self.assertNotIn(f"request.{column}", branch)
        # The session's id is cast to text, never the request's text to
        # uuid: a malformed id must not make the freshness read raise.
        self.assertIn("session.id::text = request.take_session_id", branch)
        self.assertNotIn("::uuid", branch)

    def test_every_time_on_a_request_is_accounted_for(self):
        """A withdrawal, or an update time, added to the request row later
        must be classified in REQUEST_TIMES, and read by the rule when it
        can change the stored block, before it ships."""
        create = re.compile(
            r"CREATE TABLE IF NOT EXISTS public\.exercise_coach_requests\s*"
            r"\((.*?)\n\);", re.S | re.I)
        alter = re.compile(
            r"ALTER TABLE (?:ONLY )?public\.exercise_coach_requests\b(.*?);",
            re.S | re.I)
        timed = re.compile(
            r"ADD COLUMN (?:IF NOT EXISTS )?(\w+)\s+"
            r"(?:TIMESTAMPTZ|TIMESTAMP)\b", re.I)
        found: set[str] = set()
        for name in _manifest():
            sql = migrate.strip_sql_comments((MIGRATIONS / name).read_text())
            for columns in create.findall(sql):
                found.update(re.findall(
                    r"^\s*(\w+)\s+(?:TIMESTAMPTZ|TIMESTAMP)\b", columns,
                    re.M | re.I))
            for statement in alter.findall(sql):
                found.update(timed.findall(statement))
        self.assertEqual(found, set(REQUEST_TIMES))

    def test_the_latest_rule_in_manifest_order_reads_the_whole_surface(self):
        """Whichever file re-issues the rule last keeps every branch: a
        writer nobody enumerated is how three of them were missed."""
        latest = [name for name in _manifest() if _defines(name)][-1]
        rule = migrate.strip_sql_comments(
            _function((MIGRATIONS / latest).read_text(), FUNCTION))
        for table in SURFACE:
            with self.subTest(table=table, file=latest):
                self.assertIn(f"public.{table} ", rule)


if __name__ == "__main__":
    unittest.main()
