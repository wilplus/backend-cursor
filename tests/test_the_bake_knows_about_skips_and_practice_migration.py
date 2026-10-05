"""The skip-and-practice re-issue (the_bake_knows_about_skips_and_practice.sql),
read as text.

The bake lane (tests/test_ideal_text_feedback_bake_postgres.py, built by
scripts/rehearsal_tier.sh) executes it; this pins what a reader of the file
relies on:

  * it is in the manifest after 0428 and after the tables it reads, the bake
    lane applies it twice after 0428, and the bake suite is in the tier;
  * it is one transaction, additive, reads no environment, and keeps the
    function closed to browser roles and open to service_role;
  * it re-issues ONE function, which differs from 0428's only by the two
    branches: the writer, the reader and what a bake stores stay as they are;
  * every time column on the two tables is accounted for, and the branches
    read exactly the ones whose writes change the block;
  * the two things the branches assume stay true: every write that settles a
    practice stamps `closed_at` in the same patch (and nothing else writes
    the table), and the settled read still reads only skips and a practice's
    status and answer;
  * the lane's narrow practice table keeps the released types;
  * the latest definition in manifest order still reads all seven tables.
"""
from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
NAME = "the_bake_knows_about_skips_and_practice.sql"
NUMBER = "0430"
SQL = (MIGRATIONS / NAME).read_text()
PREVIOUS = "the_bake_knows_about_the_coach.sql"
FUNCTION = "ideal_text_feedback_surface_touched_at_v1"
PRACTICE_CREATED = "add_confident_voice_practice.sql"
EVENTS_CREATED = "a_moment_opens_before_it_is_judged.sql"
PREREQUISITES = ROOT / "tests/integration/ideal_text_feedback_bake_prerequisites.sql"

sys.path.insert(0, str(ROOT / "scripts"))
import migrate  # noqa: E402

#: The two branches the file adds, exactly as it writes them.
BRANCHES = """    UNION ALL
    -- A moment settled without an answer: the speaker skipped it. An open
    -- settles nothing and is not counted. An event names its take by text;
    -- the take names the arc.
    SELECT max(moment.created_at) AS touched
      FROM public.moment_events moment
      JOIN public.v2_sessions session
        ON session.id::text = moment.take_session_id
     WHERE session.arc_id::text = p_arc_id
       AND moment.event = 'skipped'
    UNION ALL
    -- Or the speaker practised it: a practice started (the offer names the
    -- practice it resumes) or closed, completed or dismissed (the moment
    -- settles, the offer goes). Never `updated_at`, which every write to a
    -- practice moves. A practice names its take by uuid.
    SELECT max(GREATEST(practice.created_at, practice.closed_at)) AS touched
      FROM public.confident_voice_practice practice
      JOIN public.v2_sessions session ON session.id = practice.take_session_id
     WHERE session.arc_id::text = p_arc_id
"""

#: Every time column on the two tables, and whether its write can change the
#: stored block. The True ones are read by the branches.
TIMES = {
    "moment_events": {
        "created_at": True,       # the skip (the branch counts skips only)
    },
    "confident_voice_practice": {
        "created_at": True,       # the start: the offer names the practice
        "closed_at": True,        # the close: the moment settles, the offer goes
        "updated_at": False,      # moved by every write, most change nothing
        "coach_shared_at": False,  # the coach's review share; not in the block
        "chat_emitted_at": False,  # the chat receipt
    },
}
ALIASES = {"moment_events": "moment", "confident_voice_practice": "practice"}

#: The tables the rule reads after this file.
SURFACE = (
    "intervention_decisions", "user_suggestion_feedback",
    "take_feedback_self_report", "feedback_v3_owner_responses",
    "exercise_coach_requests", "moment_events", "confident_voice_practice",
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


def _create_body(sql: str, table: str) -> str:
    match = re.search(
        rf"CREATE TABLE IF NOT EXISTS public\.{table}\s*\((.*?)\n\);",
        sql, re.S | re.I)
    return match.group(1) if match else ""


def _column_type(body: str, column: str) -> str:
    match = re.search(rf"^\s*{column}\s+(\w+)", body, re.M | re.I)
    return match.group(1).upper() if match else ""


class MigrationTests(unittest.TestCase):

    def test_it_follows_0428_and_its_tables_and_the_lane_applies_it(self):
        lines = (MIGRATIONS / "manifest.txt").read_text().splitlines()
        self.assertIn(f"{NUMBER}\t{NAME}", lines)
        manifest = _manifest()
        at = manifest.index(NAME)
        for earlier in (PREVIOUS, PRACTICE_CREATED, EVENTS_CREATED,
                        "a_practice_hears_what_changed.sql"):
            self.assertLess(manifest.index(earlier), at, earlier)
        tier = (ROOT / "scripts/rehearsal_tier.sh").read_text()
        lane = tier[tier.index("BAKE=willab_bake_rehearsal"):
                    tier.index("MODELGATE=")]
        self.assertIn(
            "sql_file $BAKE migrations/$m.sql; sql_file $BAKE migrations/$m.sql",
            lane)
        order = [lane.index(f" {m}") for m in (
            "a_moment_opens_before_it_is_judged",
            PREVIOUS[:-len(".sql")], NAME[:-len(".sql")])]
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

    def test_0428_held_the_latest_definition_before_it(self):
        manifest = _manifest()
        earlier = [name for name in manifest[:manifest.index(NAME)]
                   if _defines(name)]
        self.assertEqual(earlier[-1], PREVIOUS)

    def test_the_rule_differs_from_0428_only_by_the_two_branches(self):
        before = _function((MIGRATIONS / PREVIOUS).read_text(), FUNCTION)
        after = _function(SQL, FUNCTION)
        self.assertEqual(after.count(BRANCHES), 1)
        self.assertEqual(_squash(after.replace(BRANCHES, "")), _squash(before))

    def test_the_branches_read_each_time_that_changes_the_block(self):
        branches = _squash(BRANCHES)
        for table, columns in TIMES.items():
            alias = ALIASES[table]
            for column, feeds in columns.items():
                with self.subTest(table=table, column=column):
                    if feeds:
                        self.assertIn(f"{alias}.{column}", branches)
                    else:
                        self.assertNotIn(f"{alias}.{column}", branches)
        # A skip, never an open; the join never casts text to uuid.
        self.assertIn("moment.event = 'skipped'", branches)
        self.assertNotIn("'opened'", branches)
        self.assertIn("session.id::text = moment.take_session_id", branches)
        self.assertIn("session.id = practice.take_session_id", branches)
        self.assertNotIn("::uuid", branches)

    def test_every_time_on_the_two_tables_is_accounted_for(self):
        """A reopen time, or any new time on either table, must be classified
        here, and read by the rule when it can change the block, before it
        ships."""
        timed = re.compile(
            r"ADD COLUMN (?:IF NOT EXISTS )?(\w+)\s+(?:TIMESTAMPTZ|TIMESTAMP)\b",
            re.I)
        for table, columns in TIMES.items():
            alter = re.compile(
                rf"ALTER TABLE (?:IF EXISTS )?(?:ONLY )?public\.{table}\b(.*?);",
                re.S | re.I)
            found: set[str] = set()
            for name in _manifest():
                sql = migrate.strip_sql_comments((MIGRATIONS / name).read_text())
                found.update(re.findall(
                    r"^\s*(\w+)\s+(?:TIMESTAMPTZ|TIMESTAMP)\b",
                    _create_body(sql, table), re.M | re.I))
                for statement in alter.findall(sql):
                    found.update(timed.findall(statement))
            with self.subTest(table=table):
                self.assertEqual(found, set(columns))

    def test_the_latest_rule_in_manifest_order_reads_the_whole_surface(self):
        latest = [name for name in _manifest() if _defines(name)][-1]
        rule = migrate.strip_sql_comments(
            _function((MIGRATIONS / latest).read_text(), FUNCTION))
        for table in SURFACE:
            with self.subTest(table=table, file=latest):
                self.assertIn(f"public.{table} ", rule)

    def test_the_lane_s_practice_copy_keeps_the_released_types(self):
        released = _create_body(
            migrate.strip_sql_comments((MIGRATIONS / PRACTICE_CREATED).read_text()),
            "confident_voice_practice")
        narrow = _create_body(
            migrate.strip_sql_comments(PREREQUISITES.read_text()),
            "confident_voice_practice")
        self.assertTrue(released and narrow)
        for column in ("id", "owner_user_id", "take_session_id", "snippet_id",
                       "status", "selected_attempt_id", "final_user_answer",
                       "created_at", "updated_at", "closed_at"):
            with self.subTest(column=column):
                self.assertEqual(_column_type(narrow, column),
                                 _column_type(released, column))
        landed = (MIGRATIONS / "a_practice_remembers_where_it_landed.sql").read_text()
        self.assertIn("ADD COLUMN IF NOT EXISTS landed_attempt_index INTEGER", landed)
        self.assertEqual(_column_type(narrow, "landed_attempt_index"), "INTEGER")
        five = ("'yes', 'in_between', 'no', 'not_sure', 'audio_unclear'")
        self.assertIn(five, (MIGRATIONS / "practice_is_judged_after_every_attempt.sql").read_text())
        self.assertIn(five, _squash(narrow))


class WhatTheBranchesAssume(unittest.TestCase):
    """The branches read the start and the close. That is enough only while
    every write that settles a practice is a close that stamps `closed_at`,
    and while the settled read reads nothing else."""

    @staticmethod
    def _patch_keys(function: ast.AST, patch: ast.AST) -> set[str]:
        """The keys a patch can carry: the literal, or every dict literal
        assigned to (or `.update`d into) the named patch in the function."""
        def literal(node: ast.AST) -> set[str]:
            if isinstance(node, ast.Dict):
                return {k.value for k in node.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            return set()

        if not isinstance(patch, ast.Name):
            return literal(patch)
        keys: set[str] = set()
        for node in ast.walk(function):
            if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == patch.id for t in node.targets):
                keys |= literal(node.value)
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "update"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == patch.id and node.args):
                keys |= literal(node.args[0])
        return keys

    def test_every_write_that_settles_a_practice_stamps_closed_at(self):
        calls = 0
        for path in sorted([*ROOT.glob("routes/**/*.py"), *ROOT.glob("services/**/*.py")]):
            tree = ast.parse(path.read_text(), filename=str(path))
            for function in ast.walk(tree):
                if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for node in ast.walk(function):
                    if not (isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)
                            and node.func.attr == "update_confident_voice_practice"
                            and len(node.args) >= 3):
                        continue
                    calls += 1
                    keys = self._patch_keys(function, node.args[2])
                    where = f"{path.relative_to(ROOT)}:{node.lineno}"
                    self.assertTrue(keys, f"{where}: patch keys not readable")
                    if keys & {"status", "final_user_answer"}:
                        self.assertIn("closed_at", keys, where)
        self.assertGreaterEqual(calls, 6)

    def test_nothing_else_writes_a_practice_or_rewrites_a_skip(self):
        for name in _manifest():
            sql = migrate.strip_sql_comments((MIGRATIONS / name).read_text())
            with self.subTest(file=name):
                self.assertIsNone(re.search(
                    r"UPDATE\s+(?:ONLY\s+)?(?:public\.)?"
                    r"(?:confident_voice_practice|moment_events)\b(?!_)",
                    sql, re.I))
        db = (ROOT / "services/db.py").read_text()
        self.assertNotRegex(db, r'table\("moment_events"\)\s*\.update\(')
        self.assertIn("ignore_duplicates=True", db[db.index("def record_moment_event"):
                                                  db.index("def list_moment_events_for_take")])

    def test_the_settled_read_reads_only_what_the_rule_counts(self):
        source = (ROOT / "services/moment_events.py").read_text()
        settled = source[source.index("def settled_status_by_moment"):]
        self.assertEqual(set(re.findall(r'== "(\w+)"', settled)) & {"opened", "skipped"},
                         {"skipped"})
        db = (ROOT / "services/db.py").read_text()
        reader = db[db.index("def list_confident_voice_practice_for_take"):]
        self.assertIn('.select("id,snippet_id,status,final_user_answer")',
                      reader[:reader.index("def ", 10)])


if __name__ == "__main__":
    unittest.main()
