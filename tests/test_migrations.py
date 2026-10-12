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

Run: python3 -m unittest tests.test_migrations
"""
from __future__ import annotations

import hashlib
import io
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import migrate  # noqa: E402
from migrate import (  # noqa: E402
    EXIT_FAILURE,
    EXIT_OK,
    checksum,
    destructive_statements,
    load_manifest,
    strip_sql_comments,
    unbalanced_delimiters,
    wants_no_transaction,
)

REPO = Path(__file__).resolve().parents[1]
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


class DestructiveDetectionTests(unittest.TestCase):
    """CLAUDE.md: never auto-drop tables/columns/migrations."""


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
            # Deliberate (founder Decision 37): the entire threat/challenge
            # psychological framework is retired, including its live schema.
            # This migration removes those obsolete columns and tables rather
            # than leaving a degraded compatibility path.
            "retire_threat_challenge_framework.sql",
            # Defines (but does not execute during migration) the atomic guest
            # ownership claim. The DELETE is inside the RPC and removes only
            # the now-empty guest principal after its complete entity graph is
            # transferred to an already-existing permanent owner principal.
            "add_canonical_project_ownership.sql",
            # Flagged on three patterns, none of which destroys user data.
            # DROP COLUMN drops begin_idempotency_key from
            # feedback_language_delivery_scan_runs — a table this same file
            # creates twelve lines earlier, so the column never exists in any
            # database it has not already built. TRUNCATE is the privilege
            # name in a REVOKE. DELETE FROM appears only inside PL/pgSQL
            # bodies, removing transaction-scoped capability rows.
            # APPLIED BY HAND 2026-09-13 and recorded as 0327, which is why
            # the file is allowed into the manifest at all — an UN-applied
            # destructive migration here aborts the Railway migrate step and
            # blocks every deploy (see #359).
            "add_confident_moment_coaching_bundle_v1.sql",
        }, "The destructive set changed. If you added a migration that drops "
           "something, add it here deliberately — don't just update the literal.")


class SqlHelperTests(unittest.TestCase):


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


class LedgerSqlTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.sql = (MIGRATIONS_DIR / "create_schema_migrations.sql").read_text(encoding="utf-8")

    def test_is_idempotent(self):
        # Standing constraint: migrations are idempotent and degrade gracefully.
        # The runner executes this file on every single invocation.
        self.assertIn("CREATE TABLE IF NOT EXISTS", self.sql)
        self.assertIn("CREATE INDEX IF NOT EXISTS", self.sql)


class BaselineSqlTests(unittest.TestCase):
    """`baseline --sql` is the only adoption path that works without a
    DATABASE_URL — which is the founder's actual environment
    (docs/RLS-AUDIT.md). If it regresses, the machine that most needs to
    adopt tracking silently can't."""

    @classmethod
    def setUpClass(cls):
        code, cls.out = run_cli(["baseline", "--sql"])
        cls.code = code


    def test_is_idempotent_and_cannot_clobber_a_real_apply(self):
        """ON CONFLICT DO NOTHING is what stops a pasted baseline from
        overwriting a runner-applied row (baselined=FALSE) with TRUE."""
        self.assertIn("ON CONFLICT (version) DO NOTHING", self.out)
        self.assertNotIn("DO UPDATE", self.out)


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


    def test_never_echoes_the_url(self):
        # The URL carries the database password; it must not reach the logs.
        _, err = self._warn(self.TXN_POOLER)
        self.assertNotIn("u:p@", err)
        self.assertNotIn("supabase.com", err)


class CliTests(unittest.TestCase):

    def test_verify_passes_on_the_real_tree(self):
        code, out = run_cli(["verify"])
        self.assertEqual(code, EXIT_OK, out)
        self.assertIn("verify OK", out)


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


class DelimiterDamageTests(unittest.TestCase):
    """A migration whose parentheses do not close blocks EVERY deploy.

    0333 shipped on 2026-09-15 with a copy-paste that left a GRANT's argument
    list open. Postgres refused it at the next statement and the pre-deploy
    command failed on every deploy for the next day — and because the runner
    stops at the first failure, 0334 and 0335 behind it were never attempted
    either. Nothing in this repository would have caught it: `verify` checked
    structure and never the SQL, and the rehearsal tier applies a curated
    list of files that a new migration does not join.

    The exact shape that shipped, reproduced here so the gate is tested
    against the real defect rather than an invented one.
    """

    SHIPPED_DAMAGE = """
REVOKE ALL ON FUNCTION public.f(TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.f(
REVOKE ALL ON FUNCTION public.f(TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.f(TEXT) TO service_role;
"""


    def test_every_migration_on_disk_is_balanced(self):
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            with self.subTest(path.name):
                self.assertEqual(
                    unbalanced_delimiters(path.read_text(errors="ignore")), [],
                )

    def test_verify_refuses_a_damaged_file(self):
        """The gate, not just the function: `verify` must exit non-zero."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "migrations").mkdir()
            (root / "migrations" / "0001_ok.sql").write_text(
                "CREATE TABLE IF NOT EXISTS t(id INT);\n")
            (root / "migrations" / "0002_bad.sql").write_text(self.SHIPPED_DAMAGE)
            (root / "migrations" / "manifest.txt").write_text(
                "0001\t0001_ok.sql\n0002\t0002_bad.sql\n")
            (root / "migrations" / "create_schema_migrations.sql").write_text(
                "SELECT 1;\n")
            original_dir, original_manifest, original_ledger = (
                migrate.MIGRATIONS_DIR, migrate.MANIFEST_PATH,
                migrate.LEDGER_SQL_PATH)
            migrate.MIGRATIONS_DIR = root / "migrations"
            migrate.MANIFEST_PATH = root / "migrations" / "manifest.txt"
            migrate.LEDGER_SQL_PATH = (
                root / "migrations" / "create_schema_migrations.sql")
            try:
                code, out = run_cli(["verify"])
            finally:
                (migrate.MIGRATIONS_DIR, migrate.MANIFEST_PATH,
                 migrate.LEDGER_SQL_PATH) = (
                    original_dir, original_manifest, original_ledger)
            self.assertEqual(code, EXIT_FAILURE, out)
            self.assertIn("0002_bad.sql", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
