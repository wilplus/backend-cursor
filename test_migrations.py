"""willab — the migration manifest + runner are enforceable, not aspirational.

What this suite defends, in order of how badly it hurts when it breaks:

  1. APPEND-ONLY. Versions 0001-0239 are recorded in every environment's
     schema_migrations by version number. Renumbering or reordering one of
     them silently desynchronises prod from the repo, and nothing else would
     notice. A frozen hash makes that a red build.

  2. MANIFEST <-> DISK 1:1. A .sql added without a manifest line never runs
     anywhere — the exact failure the old flat directory had, just quieter.

  3. DESTRUCTIVE DETECTION. The runner refuses DROP TABLE / DROP COLUMN /
     TRUNCATE / DELETE FROM without an explicit flag (CLAUDE.md: never
     auto-drop tables/columns/migrations). 30 of the 239 files carry
     commented-out rollback hints like
         -- Rollback: ALTER TABLE x DROP COLUMN IF EXISTS y;
     If the scanner ever stops stripping comments, those 30 get blocked, the
     gate becomes noise, and someone adds --allow-destructive to the deploy
     script to make it shut up. Both directions are tested.

  4. DEPENDENCY ORDER. The manifest's whole claim is that a file lands after
     everything it depends on. Appending a migration that ALTERs a table
     created later breaks a from-scratch rebuild.

No database required — every test here reads files or uses a fake connection.

STDLIB ONLY. The `migrations` CI job installs no dependencies, so nothing
here may depend on psycopg2 (or any other optional package) being importable.
A test that asserts on post-connect behaviour will pass locally and fail in
CI — that is exactly how the pooler-warning test broke on its first run.
Assert on what holds in both environments, or fake the connection.

Run: python3 -m unittest test_migrations
"""
from __future__ import annotations

import hashlib
import io
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "scripts"))

import migrate  # noqa: E402
from migrate import (  # noqa: E402
    EXIT_CANNOT_RUN,
    EXIT_FAILURE,
    EXIT_OK,
    ManifestError,
    checksum,
    destructive_statements,
    load_manifest,
    looks_idempotent,
    next_version,
    strip_sql_comments,
    wants_no_transaction,
)

REPO = Path(__file__).parent
MIGRATIONS_DIR = REPO / "migrations"

# The hand-applied block, frozen 2026-08-03. These versions are recorded in
# prod's schema_migrations (via `migrate.py baseline`), so their numbering is
# now permanent. New migrations APPEND at 0240+; this hash never changes.
BASELINE_COUNT = 239
BASELINE_BLOCK_SHA256 = "97cc43b3fd2dc38c00b03e3fc1daef30048d2d7739f7562314fa8beeec2f8765"


def run_cli(argv: list[str]) -> tuple[int, str]:
    """Invoke the CLI, capturing output. Returns (exit_code, combined output)."""
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        code = migrate.main(argv)
    return code, buf.getvalue()


class ManifestIntegrityTests(unittest.TestCase):
    """The manifest is the order of record. It has to actually parse and match."""

    @classmethod
    def setUpClass(cls):
        cls.migrations = load_manifest()

    def test_manifest_is_not_vacuous(self):
        # Guards against a parser that silently matches nothing and lets every
        # other assertion in this file pass on an empty list.
        self.assertGreaterEqual(len(self.migrations), BASELINE_COUNT)

    def test_versions_are_contiguous_and_ascending(self):
        for index, migration in enumerate(self.migrations, start=1):
            self.assertEqual(
                int(migration.version), index,
                f"{migration.filename} has version {migration.version}, expected {index:04d}. "
                "Versions must be contiguous — never renumber or delete a line.",
            )

    def test_every_manifest_entry_exists_on_disk(self):
        missing = [m.filename for m in self.migrations if not m.path.exists()]
        self.assertEqual(missing, [], f"manifest lists files that do not exist: {missing}")

    def test_every_sql_file_is_in_the_manifest(self):
        on_disk = {p.name for p in MIGRATIONS_DIR.glob("*.sql")} - migrate.NON_MANIFEST_FILES
        tracked = {m.filename for m in self.migrations}
        untracked = sorted(on_disk - tracked)
        self.assertEqual(
            untracked, [],
            f"these .sql files are not in manifest.txt and would never run: {untracked}. "
            "Add them with `python scripts/migrate.py new`.",
        )

    def test_no_duplicate_versions_or_filenames(self):
        versions = [m.version for m in self.migrations]
        filenames = [m.filename for m in self.migrations]
        self.assertEqual(len(versions), len(set(versions)))
        self.assertEqual(len(filenames), len(set(filenames)))

    def test_baseline_block_is_frozen(self):
        """0001-0239 are recorded in prod by version. They can never move."""
        block = self.migrations[:BASELINE_COUNT]
        digest = hashlib.sha256(
            "\n".join(f"{m.version}\t{m.filename}" for m in block).encode("utf-8")
        ).hexdigest()
        self.assertEqual(
            digest, BASELINE_BLOCK_SHA256,
            "The baselined block 0001-0239 changed. Those versions are already "
            "recorded in prod's schema_migrations, so reordering or renaming one "
            "desynchronises every environment. New migrations APPEND at 0240+.",
        )

    def test_ledger_bootstrap_is_not_in_the_manifest(self):
        # The ledger can't be an entry in the list it tracks.
        tracked = {m.filename for m in self.migrations}
        self.assertNotIn("create_schema_migrations.sql", tracked)
        self.assertTrue((MIGRATIONS_DIR / "create_schema_migrations.sql").exists())


class ManifestParserTests(unittest.TestCase):
    """Malformed manifests must fail loudly, not half-parse."""

    def _parse(self, body: str):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
            fh.write(body)
            path = Path(fh.name)
        try:
            return load_manifest(path)
        finally:
            path.unlink()

    def test_comments_and_blank_lines_ignored(self):
        result = self._parse("# a comment\n\n0001\tone.sql\n\n0002\ttwo.sql\n")
        self.assertEqual([m.filename for m in result], ["one.sql", "two.sql"])

    def test_duplicate_version_rejected(self):
        with self.assertRaises(ManifestError) as ctx:
            self._parse("0001\tone.sql\n0001\tother.sql\n")
        self.assertIn("duplicate version", str(ctx.exception))

    def test_duplicate_filename_rejected(self):
        with self.assertRaises(ManifestError) as ctx:
            self._parse("0001\tone.sql\n0002\tone.sql\n")
        self.assertIn("duplicate file", str(ctx.exception))

    def test_missing_tab_rejected(self):
        # Spaces instead of a tab is the obvious hand-editing mistake.
        with self.assertRaises(ManifestError):
            self._parse("0001 one.sql\n")

    def test_non_numeric_version_rejected(self):
        with self.assertRaises(ManifestError):
            self._parse("v1\tone.sql\n")

    def test_missing_file_rejected(self):
        with self.assertRaises(ManifestError):
            load_manifest(Path("/nonexistent/manifest.txt"))

    def test_next_version_appends(self):
        self.assertEqual(next_version(self._parse("0001\ta.sql\n0002\tb.sql\n")), "0003")
        self.assertEqual(next_version([]), "0001")


class DestructiveDetectionTests(unittest.TestCase):
    """CLAUDE.md: never auto-drop tables/columns/migrations."""

    def test_real_destructive_statements_are_flagged(self):
        for sql, expected in [
            ("DROP TABLE public.foo;", "DROP TABLE"),
            ("drop table if exists foo;", "DROP TABLE"),
            ("ALTER TABLE foo DROP COLUMN bar;", "DROP COLUMN"),
            ("TRUNCATE public.foo;", "TRUNCATE"),
            ("DELETE FROM public.foo WHERE x = 1;", "DELETE FROM"),
            ("DROP SCHEMA public CASCADE;", "DROP SCHEMA"),
        ]:
            with self.subTest(sql=sql):
                self.assertIn(expected, destructive_statements(sql))

    def test_commented_rollback_hints_are_not_flagged(self):
        """The false-positive class that would make the gate unusable.

        30 of the 239 files document their own rollback in a comment. If those
        get flagged, `apply` blocks on a third of the tree and someone adds
        --allow-destructive to the deploy to unblock it — which is strictly
        worse than having no gate.
        """
        for sql in [
            "-- Rollback: ALTER TABLE v2_sessions DROP COLUMN IF EXISTS tutor_video_url;\n"
            "ALTER TABLE v2_sessions ADD COLUMN IF NOT EXISTS tutor_video_url TEXT;",
            "-- down: drop table if exists public.snippet_labels;\n"
            "CREATE TABLE IF NOT EXISTS public.snippet_labels (id UUID PRIMARY KEY);",
            "/* To revert:\n   DELETE FROM public.token_ledger WHERE action = 'x';\n*/\n"
            "CREATE TABLE IF NOT EXISTS public.token_ledger (id UUID PRIMARY KEY);",
        ]:
            with self.subTest(sql=sql[:40]):
                self.assertEqual(destructive_statements(sql), [])

    def test_drop_index_and_policy_are_not_destructive(self):
        # `DROP POLICY IF EXISTS ...; CREATE POLICY ...` is this repo's
        # idempotency idiom. Flagging it would block routine RLS migrations.
        for sql in [
            "DROP INDEX IF EXISTS idx_foo;",
            "DROP POLICY IF EXISTS p ON public.foo;",
            "DROP TRIGGER IF EXISTS t ON public.foo;",
            "ALTER TABLE foo DROP CONSTRAINT IF EXISTS c;",
        ]:
            with self.subTest(sql=sql):
                self.assertEqual(destructive_statements(sql), [])

    def test_real_repo_files_flagged_are_the_known_set(self):
        """Pins the live-tree result so a scanner regression shows up here."""
        flagged = {
            m.filename for m in load_manifest()
            if m.path.exists() and destructive_statements(m.read())
        }
        self.assertEqual(flagged, {
            "v2_schema_unified.sql",
            "cleanup_unused_sessions.sql",
            "drop_recording_reviews_ml_labeling.sql",
            "drop_v2_sessions_legacy_performance_scores.sql",
            "v2_metric_questions_table_only.sql",
            "rename_warmup_to_tasks_and_drop_focus.sql",
            # Deliberate (founder 2026-08-05): tears down the retired
            # read-out-loud lane — deletes the historical read sessions,
            # then drops v2_sessions.recording_kind / paired_session_id.
            # Destructive on purpose and run by hand, never automatically.
            "drop_reread_lane.sql",
            # Deliberate (founder 2026-08-06, PM-9): drops the six dead metric
            # columns on charisma_snippets. APPLIED BY HAND 2026-08-06 and
            # recorded as 0254, which is why the file is allowed into the
            # manifest at all — an UN-applied destructive migration here aborts
            # the Railway migrate step and blocks every deploy (see #359).
            # Pre-flight confirmed zero rows held a value only in a column;
            # every figure is also in the `metrics` blob.
            "drop_dead_snippet_metric_columns.sql",
        }, "The destructive set changed. If you added a migration that drops "
           "something, add it here deliberately — don't just update the literal.")


class SqlHelperTests(unittest.TestCase):

    def test_strip_sql_comments(self):
        self.assertNotIn("secret", strip_sql_comments("-- secret\nSELECT 1;"))
        self.assertNotIn("secret", strip_sql_comments("/* secret */ SELECT 1;"))
        self.assertIn("SELECT 1", strip_sql_comments("-- note\nSELECT 1;"))

    def test_multiline_block_comment_stripped(self):
        sql = "/*\n DROP TABLE foo;\n*/\nCREATE TABLE IF NOT EXISTS bar (id INT);"
        self.assertEqual(destructive_statements(sql), [])

    def test_looks_idempotent(self):
        self.assertTrue(looks_idempotent("CREATE TABLE IF NOT EXISTS foo (id INT);"))
        self.assertTrue(looks_idempotent("CREATE OR REPLACE FUNCTION f() ..."))
        self.assertFalse(looks_idempotent("CREATE TABLE foo (id INT);"))

    def test_checksum_is_stable_and_newline_normalised(self):
        self.assertEqual(checksum("SELECT 1;\n"), checksum("SELECT 1;\r\n"))
        self.assertNotEqual(checksum("SELECT 1;"), checksum("SELECT 2;"))
        self.assertEqual(len(checksum("x")), 64)

    def test_no_transaction_marker(self):
        self.assertTrue(wants_no_transaction("-- migrate:no-transaction\nCREATE INDEX ..."))
        self.assertFalse(wants_no_transaction("CREATE INDEX CONCURRENTLY ..."))
        # Must be its own line, not incidental prose.
        self.assertFalse(wants_no_transaction("-- we could use migrate:no-transaction here"))

    def test_every_current_migration_is_transaction_safe(self):
        """None of the 239 need the escape hatch — so `apply` wraps them all.

        If a future migration adds CREATE INDEX CONCURRENTLY without the
        marker, `apply` will fail against a real database. This catches it in
        CI instead.
        """
        offenders = []
        for m in load_manifest():
            if not m.path.exists():
                continue
            body = strip_sql_comments(m.read())
            needs_escape = re.search(r"\bCONCURRENTLY\b|\bALTER\s+TYPE\b.*\bADD\s+VALUE\b|\bVACUUM\b",
                                     body, re.I | re.S)
            if needs_escape and not wants_no_transaction(m.read()):
                offenders.append(m.filename)
        self.assertEqual(
            offenders, [],
            "These cannot run inside a transaction — add the "
            "'-- migrate:no-transaction' marker: " + ", ".join(offenders),
        )


class DependencyOrderTests(unittest.TestCase):
    """The manifest's core claim: nothing lands before what it depends on."""

    CREATE_TABLE = re.compile(
        r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([\w\".]+)", re.I)
    ALTER_TABLE = re.compile(
        r"\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?([\w\".]+)", re.I)
    EXTERNAL = {"auth", "storage", "extensions", "graphql", "realtime", "vault", "cron", "net"}

    @classmethod
    def _norm(cls, name: str) -> str:
        name = name.strip().strip('"').lower()
        if "." in name:
            schema, _, tail = name.partition(".")
            if schema in cls.EXTERNAL:
                return ""
            return tail.strip('"')
        return name

    def test_altered_tables_are_created_earlier_or_not_at_all(self):
        migrations = [m for m in load_manifest() if m.path.exists()]
        creates: dict[str, int] = {}
        alters: list[tuple[int, str, str]] = []

        for position, migration in enumerate(migrations):
            body = strip_sql_comments(migration.read())
            for match in self.CREATE_TABLE.finditer(body):
                name = self._norm(match.group(1))
                if name:
                    creates.setdefault(name, position)
            for match in self.ALTER_TABLE.finditer(body):
                name = self._norm(match.group(1))
                if name:
                    alters.append((position, name, migration.filename))

        violations = [
            f"{filename} (#{position + 1}) ALTERs '{table}', "
            f"first created at #{creates[table] + 1}"
            for position, table, filename in alters
            if table in creates and creates[table] > position
        ]
        # Tables never created by any migration (`recordings`, `admin_users`,
        # anything under auth./storage.) are external and correctly skipped.
        self.assertEqual(
            violations, [],
            "Manifest order broken — a migration ALTERs a table created later, "
            "so a from-scratch rebuild fails:\n  " + "\n  ".join(violations),
        )


class ApplyAtomicityTests(unittest.TestCase):
    """The ledger row and the DDL must commit together, or not at all."""

    class FakeCursor:
        def __init__(self, conn):
            self.conn = conn

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            self.conn.executed.append((sql, params))
            if self.conn.fail_on and self.conn.fail_on in sql:
                raise RuntimeError("syntax error at or near ...")

    class FakeConn:
        def __init__(self, fail_on=None):
            self.executed: list[tuple] = []
            self.committed = False
            self.rolled_back = False
            self.autocommit = True
            self.fail_on = fail_on

        def cursor(self):
            return ApplyAtomicityTests.FakeCursor(self)

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

    def test_success_commits_ddl_and_ledger_together(self):
        conn = self.FakeConn()
        sql = "ALTER TABLE public.foo ADD COLUMN IF NOT EXISTS bar TEXT;"
        migration = migrate.Migration(version="0240", filename="add_thing.sql")
        migrate._apply_one(conn, migration, sql, checksum(sql), "tester", 0.0)

        self.assertTrue(conn.committed)
        self.assertFalse(conn.rolled_back)
        self.assertEqual(len(conn.executed), 2)
        self.assertIn("ALTER TABLE", conn.executed[0][0])
        self.assertIn("INSERT INTO public.schema_migrations", conn.executed[1][0])
        version, filename, digest, who, elapsed_ms = conn.executed[1][1]
        self.assertEqual(version, "0240")
        self.assertEqual(filename, "add_thing.sql")
        self.assertEqual(digest, checksum(sql))
        self.assertEqual(who, "tester")
        self.assertIsInstance(elapsed_ms, int)
        # autocommit restored so the connection is reusable for the next file
        self.assertTrue(conn.autocommit)

    def test_failure_rolls_back_and_writes_no_ledger_row(self):
        conn = self.FakeConn(fail_on="ALTER TABLE")
        sql = "ALTER TABLE public.foo ADD COLUMN bar TEXT;"
        migration = migrate.Migration(version="0240", filename="add_thing.sql")

        with self.assertRaises(RuntimeError):
            migrate._apply_one(conn, migration, sql, checksum(sql), "tester", 0.0)

        self.assertTrue(conn.rolled_back)
        self.assertFalse(conn.committed)
        ledger_writes = [s for s, _ in conn.executed if "schema_migrations" in s]
        self.assertEqual(ledger_writes, [], "a failed migration must not be recorded as applied")
        self.assertTrue(conn.autocommit, "autocommit must be restored even on failure")

    def test_ledger_row_is_marked_not_baselined(self):
        conn = self.FakeConn()
        sql = "SELECT 1;"
        migration = migrate.Migration(version="0240", filename="add_thing.sql")
        migrate._apply_one(conn, migration, sql, checksum(sql), "tester", 0.0)
        insert_sql, params = conn.executed[1]
        self.assertIn("FALSE", insert_sql, "runner-applied rows must have baselined = FALSE")
        self.assertEqual(params[1], "add_thing.sql")


class LedgerSqlTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.sql = (MIGRATIONS_DIR / "create_schema_migrations.sql").read_text(encoding="utf-8")

    def test_is_idempotent(self):
        # Standing constraint: migrations are idempotent and degrade gracefully.
        # The runner executes this file on every single invocation.
        self.assertIn("CREATE TABLE IF NOT EXISTS", self.sql)
        self.assertIn("CREATE INDEX IF NOT EXISTS", self.sql)

    def test_creates_the_expected_columns(self):
        for column in ("version", "filename", "checksum", "applied_at",
                       "applied_by", "execution_ms", "baselined"):
            self.assertRegex(self.sql, rf"\b{column}\b")

    def test_has_no_destructive_statements(self):
        self.assertEqual(destructive_statements(self.sql), [])


class BaselineSqlTests(unittest.TestCase):
    """`baseline --sql` is the only adoption path that works without a
    DATABASE_URL — which is the founder's actual environment
    (docs/RLS-AUDIT.md). If it regresses, the machine that most needs to
    adopt tracking silently can't."""

    @classmethod
    def setUpClass(cls):
        code, cls.out = run_cli(["baseline", "--sql"])
        cls.code = code

    def test_needs_no_database(self):
        original = migrate.os.environ.pop("DATABASE_URL", None)
        try:
            code, out = run_cli(["baseline", "--sql"])
            self.assertEqual(code, EXIT_OK, out)
            self.assertIn("INSERT INTO public.schema_migrations", out)
        finally:
            if original is not None:
                migrate.os.environ["DATABASE_URL"] = original

    def test_emits_a_row_per_manifest_entry(self):
        migrations = load_manifest()
        for migration in (migrations[0], migrations[len(migrations) // 2], migrations[-1]):
            with self.subTest(version=migration.version):
                self.assertIn(f"('{migration.version}', '{migration.filename}'", self.out)
        self.assertEqual(self.out.count("), TRUE)") + self.out.count(", TRUE)"),
                         len(migrations))

    def test_rows_are_marked_baselined(self):
        # Every emitted row must be baselined=TRUE — this path never executes
        # SQL, so claiming a verified apply would be a lie.
        self.assertNotIn(", FALSE)", self.out)
        self.assertIn(", TRUE)", self.out)

    def test_checksums_match_the_files(self):
        migration = load_manifest()[0]
        self.assertIn(checksum(migration.read()), self.out)

    def test_is_idempotent_and_cannot_clobber_a_real_apply(self):
        """ON CONFLICT DO NOTHING is what stops a pasted baseline from
        overwriting a runner-applied row (baselined=FALSE) with TRUE."""
        self.assertIn("ON CONFLICT (version) DO NOTHING", self.out)
        self.assertNotIn("DO UPDATE", self.out)

    def test_respects_the_to_bound(self):
        code, out = run_cli(["baseline", "--sql", "--to", "0003"])
        self.assertEqual(code, EXIT_OK, out)
        self.assertIn("('0003',", out)
        self.assertNotIn("('0004',", out)

    def test_sql_literals_are_quote_safe(self):
        self.assertEqual(migrate._sql_quote("plain"), "'plain'")
        self.assertEqual(migrate._sql_quote("it's"), "'it''s'")


class TransactionPoolerWarningTests(unittest.TestCase):
    """Port 6543 vs 5432 is a one-digit mistake with a silent consequence:
    session-scoped advisory locks stop guarding on a transaction pooler, and
    the failure only surfaces under a race, long after the misconfiguration."""

    SESSION_POOLER = "postgresql://u:p@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
    TXN_POOLER = "postgresql://u:p@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"

    def _warn(self, url: str) -> tuple[bool, str]:
        buf = io.StringIO()
        with redirect_stderr(buf):
            warned = migrate.warn_if_transaction_pooler(url)
        return warned, buf.getvalue()

    def test_warns_on_transaction_pooler(self):
        warned, err = self._warn(self.TXN_POOLER)
        self.assertTrue(warned)
        self.assertIn("6543", err)
        self.assertIn("5432", err)

    def test_silent_on_session_pooler(self):
        warned, err = self._warn(self.SESSION_POOLER)
        self.assertFalse(warned)
        self.assertEqual(err, "")

    def test_silent_on_direct_connection(self):
        warned, _ = self._warn("postgresql://u:p@db.abcdef.supabase.co:5432/postgres")
        self.assertFalse(warned)

    def test_matches_port_only_at_a_boundary(self):
        # A password or hostname containing 6543 is not a port.
        for url in [
            "postgresql://u:pass6543word@host:5432/postgres",
            "postgresql://u:p@host-6543.example.com:5432/postgres",
            "postgresql://u:p@host:54321/postgres",
        ]:
            with self.subTest(url=url):
                self.assertFalse(self._warn(url)[0])

    def test_matches_with_query_string_and_trailing_forms(self):
        for url in [
            "postgresql://u:p@host:6543/postgres",
            "postgresql://u:p@host:6543/postgres?sslmode=require",
            "postgresql://u:p@host:6543",
        ]:
            with self.subTest(url=url):
                self.assertTrue(self._warn(url)[0])

    def test_never_echoes_the_url(self):
        # The URL carries the database password; it must not reach the logs.
        _, err = self._warn(self.TXN_POOLER)
        self.assertNotIn("u:p@", err)
        self.assertNotIn("supabase.com", err)

    def test_warning_does_not_block(self):
        """It warns and still attempts the connection — refusing outright would
        strand anyone whose only reachable endpoint is the pooler.

        Uses 127.0.0.1 so the attempt fails instantly with ECONNREFUSED: no
        DNS, no network, no timeout. (An earlier version of this test pointed
        at a realistic Supabase hostname and hung the suite for two minutes.)

        The outcome after the warning differs by environment, and both are
        correct: with psycopg2 installed the connection is refused; in the
        stdlib-only `migrations` CI job the driver is missing. What must hold
        in BOTH is that the warning fired — it diagnoses the URL, not the
        driver. Asserting "could not connect" here is what turned this job red
        on first run, because that CI job installs no dependencies.
        """
        original = migrate.os.environ.get("DATABASE_URL")
        migrate.os.environ["DATABASE_URL"] = "postgresql://u:p@127.0.0.1:6543/postgres"
        try:
            code, out = run_cli(["status"])
            self.assertEqual(code, EXIT_CANNOT_RUN, out)
            self.assertIn("6543", out)  # warned, driver present or not
            self.assertTrue(
                "could not connect" in out or "psycopg2 is not installed" in out,
                f"expected a connection or driver failure after the warning, got: {out!r}",
            )
        finally:
            if original is None:
                migrate.os.environ.pop("DATABASE_URL", None)
            else:
                migrate.os.environ["DATABASE_URL"] = original


class CliTests(unittest.TestCase):

    def test_verify_passes_on_the_real_tree(self):
        code, out = run_cli(["verify"])
        self.assertEqual(code, EXIT_OK, out)
        self.assertIn("verify OK", out)

    def test_verify_verbose_lists_destructive_files(self):
        code, out = run_cli(["verify", "--verbose"])
        self.assertEqual(code, EXIT_OK, out)
        self.assertIn("drop_recording_reviews_ml_labeling.sql", out)

    def test_offline_plan_needs_no_database(self):
        code, out = run_cli(["plan", "--offline"])
        self.assertEqual(code, EXIT_OK, out)
        self.assertIn("would run", out)

    def test_missing_database_url_exits_2_not_1(self):
        """Exit 2 means 'cannot run here' and must stay non-fatal.

        bin/railway-migrate.sh treats 2 as success unless MIGRATE_REQUIRED=1,
        so services without a Postgres URL still deploy. If this ever became
        1, every such deploy would start failing.
        """
        original = migrate.os.environ.pop("DATABASE_URL", None)
        try:
            code, out = run_cli(["status"])
            self.assertEqual(code, EXIT_CANNOT_RUN, out)
            self.assertIn("DATABASE_URL", out)
        finally:
            if original is not None:
                migrate.os.environ["DATABASE_URL"] = original

    def test_verify_fails_on_an_untracked_sql_file(self):
        stray = MIGRATIONS_DIR / "zz_untracked_test_fixture.sql"
        stray.write_text("SELECT 1;\n", encoding="utf-8")
        try:
            code, out = run_cli(["verify"])
            self.assertEqual(code, EXIT_FAILURE)
            self.assertIn("zz_untracked_test_fixture.sql", out)
            self.assertIn("not in manifest.txt", out)
        finally:
            stray.unlink()

    def test_verify_recovers_after_the_stray_is_removed(self):
        code, _ = run_cli(["verify"])
        self.assertEqual(code, EXIT_OK)


class DoctorTests(unittest.TestCase):
    """THE LEDGER SAID APPLIED; THE DATABASE DISAGREED (production 2026-08-12).

    The app logged, on every take::

        upsert_ideal_text_block: table missing (run migrations/add_ideal_text_blocks.sql)
        token_charge() not installed — using the legacy non-atomic path

    while the runner reported ``nothing pending`` over 269/269 with ``verify
    OK``. Token charging has therefore been running on the four-round-trip
    non-atomic path — the exact half-state migration 0241 exists to close.

    IT IS NOT A RUNNER BUG. `baseline` does what it documents: records
    migrations as applied WITHOUT running them, on the stated assumption that
    a hand-migrated database already had them. For 0033 and 0241 the
    assumption was false, and nothing could ever have noticed — `verify`
    compares the manifest to the disk, `status` compares the ledger to
    checksums, and neither asks the database whether the objects are there.

    These cover the half that needs no database: which objects a file CLAIMS.
    A wrong answer there either cries wolf (and gets ignored) or misses the
    drift entirely.
    """

    def test_it_finds_tables_views_and_functions(self):
        sql = (
            "CREATE TABLE IF NOT EXISTS public.alpha (id INT);\n"
            "CREATE OR REPLACE VIEW beta AS SELECT 1;\n"
            "CREATE OR REPLACE FUNCTION public.gamma(a INT) RETURNS INT AS $$ $$;\n"
        )
        self.assertEqual(
            migrate.claimed_objects(sql),
            [("table", "public.alpha"), ("table", "public.beta"),
             ("function", "public.gamma")])

    def test_a_bare_name_is_public_qualified(self):
        # to_regclass('alpha') resolves through search_path, which is not the
        # search_path the app runs under. Qualifying makes the check mean the
        # same thing wherever it is pasted.
        self.assertEqual(
            migrate.claimed_objects("CREATE TABLE alpha (id INT);"),
            [("table", "public.alpha")])

    def test_PROSE_ABOUT_DDL_IS_NOT_A_CLAIM(self):
        # These files describe their own schema at length. A scanner reading
        # the comments would report objects the file never creates — and a
        # check that cries wolf is one everyone learns to skip, the same
        # failure `destructive_statements` strips comments to avoid.
        sql = (
            "-- CREATE TABLE public.described_only (id INT);\n"
            "/* CREATE OR REPLACE FUNCTION public.also_described() */\n"
            "CREATE TABLE IF NOT EXISTS public.real_one (id INT);\n"
        )
        self.assertEqual(migrate.claimed_objects(sql),
                         [("table", "public.real_one")])

    def test_the_same_object_twice_is_claimed_once(self):
        sql = ("CREATE TABLE IF NOT EXISTS public.a (id INT);"
               "CREATE TABLE IF NOT EXISTS public.a (id INT);")
        self.assertEqual(migrate.claimed_objects(sql), [("table", "public.a")])

    def test_a_file_that_creates_nothing_claims_nothing(self):
        # ALTER / INSERT / GRANT-only migrations are common here and must not
        # produce a claim nobody can verify.
        sql = ("ALTER TABLE public.a ADD COLUMN IF NOT EXISTS b INT;"
               "INSERT INTO public.a (b) VALUES (1) ON CONFLICT DO NOTHING;")
        self.assertEqual(migrate.claimed_objects(sql), [])

    def _claims(self, filename):
        return migrate.claimed_objects(
            (MIGRATIONS_DIR / filename).read_text(encoding="utf-8"))

    def test_0033_claims_the_table_the_app_says_is_missing(self):
        claims = self._claims("add_ideal_text_blocks.sql")
        self.assertIn(("table", "public.ideal_text_blocks"), claims)
        self.assertIn(("table", "public.ideal_text_saves"), claims)

    def test_0241_claims_the_function_the_app_says_is_not_installed(self):
        self.assertIn(("function", "public.token_charge"),
                      self._claims("add_token_charge_rpc.sql"))

    def test_both_drifted_files_are_SAFE_TO_RE_RUN(self):
        # The remediation is "run these files again", so re-runnability is not
        # a nicety here — it IS the fix. 0033 is entirely IF NOT EXISTS; 0241
        # is CREATE OR REPLACE FUNCTION and its only DROP sits inside a
        # comment, which is why the destructive scan strips comments first.
        for name in ("add_ideal_text_blocks.sql", "add_token_charge_rpc.sql"):
            sql = (MIGRATIONS_DIR / name).read_text(encoding="utf-8")
            self.assertTrue(migrate.looks_idempotent(sql), name)
            self.assertEqual(migrate.destructive_statements(sql), [], name)

    def test_the_emitted_query_checks_relations_and_functions_differently(self):
        # to_regclass answers for relations and returns NULL for a function,
        # so one check for both would report every function as missing.
        self.assertIn("to_regclass", migrate._DOCTOR_PREDICATE)
        self.assertIn("pg_proc", migrate._DOCTOR_PREDICATE)

    def test_the_sql_mode_needs_no_database_and_filters_to_baselined(self):
        # The environment that most needs this check is the one without a
        # DATABASE_URL — the same reason `baseline --sql` exists. And only
        # baselined rows are suspect: a migration the runner applied was
        # watched, so it committed or it failed loudly.
        code, out = run_cli(["doctor", "--sql"])
        self.assertEqual(code, EXIT_OK)
        self.assertIn("WHERE m.baselined", out)
        self.assertIn("'0033', 'add_ideal_text_blocks.sql', 'table', "
                      "'public.ideal_text_blocks'", out)
        self.assertIn("'0241', 'add_token_charge_rpc.sql', 'function', "
                      "'public.token_charge'", out)
        # READ-ONLY BY CONSTRUCTION: a diagnostic that can write is one nobody
        # dares run against production. Checked structurally rather than by
        # scanning for banned words — the header prose says "claims to CREATE",
        # and a keyword scan that trips on its own documentation is the kind of
        # check that gets deleted rather than fixed.
        body = migrate.strip_sql_comments(out).strip()
        self.assertTrue(body.startswith("WITH claimed"), body[:60])
        self.assertEqual(body.count(";"), 1, "more than one statement")
        self.assertTrue(body.endswith(";"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
