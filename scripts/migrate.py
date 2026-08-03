#!/usr/bin/env python3
"""willab migration runner — ordered, tracked, forward-only.

WHAT THIS REPLACES
    239 flat .sql files applied by hand, with no ordering and no record of
    what ran where. "Which migrations ran in prod?" was answered by grepping
    Railway logs for Postgres error codes — you learned a migration had been
    missed when a user hit the bug. Now: migrations/manifest.txt is the order
    of record, public.schema_migrations is the applied-state of record.

COMMANDS
    verify     Structural check, NO DATABASE NEEDED. manifest <-> files are
               1:1, versions contiguous, checksums readable, destructive and
               non-idempotent files reported. This is the CI gate.
    status     What this database has applied, what is pending, what drifted.
    plan       What `apply` would do, without touching anything.
    apply      Run pending migrations in manifest order.
    baseline   Record migrations as applied WITHOUT running them. The adoption
               path for a database that was already migrated by hand.
    new        Scaffold a new migration + append it to the manifest.

DESIGN CONSTRAINTS (from CLAUDE.md — these are not preferences)
    * "Never break the live loop."  Nothing here runs automatically on the web
      boot path by default. When MIGRATE_ON_BOOT is opted into, failures are
      logged and the boot continues — a bad migration must never take the app
      down. Exit code 2 means "could not run" and is non-fatal to callers.
    * "Never auto-drop tables/columns/migrations."  Files containing DROP
      TABLE / DROP COLUMN / TRUNCATE / DELETE FROM are refused unless
      --allow-destructive is passed explicitly. Automation never passes it.
    * "Migrations are idempotent and degrade gracefully."  A missing psycopg2
      or missing DATABASE_URL degrades to a clear message, never a crash.

WHY NOT SUPABASE CLI / ALEMBIC / ATLAS
    All three want to own the migration files. Supabase CLI expects
    timestamped names under supabase/migrations and a linked project; Alembic
    wants Python revisions with down_revision chains; Atlas wants a declarative
    HCL schema. Any of them means rewriting or renaming 239 files that are
    referenced by name across migrations/README.md, docs/*.md and the test
    suite (test_lounge_kind_migration.py pins a filename), and re-deriving a
    history that cannot be re-derived. This runner adopts the same core
    contract those tools implement — ordered versions, a schema_migrations
    ledger, checksum drift detection, run-in-CI — against the files as they
    already exist, with a baseline path for the hand-applied prod database.
    If the file layout is ever reworked, the manifest is the migration path
    into whichever tool wins.

USAGE
    python scripts/migrate.py verify
    python scripts/migrate.py status
    DATABASE_URL=postgres://... python scripts/migrate.py baseline --to 0239
    DATABASE_URL=postgres://... python scripts/migrate.py apply --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = REPO_ROOT / "migrations"
MANIFEST_PATH = MIGRATIONS_DIR / "manifest.txt"
LEDGER_SQL_PATH = MIGRATIONS_DIR / "create_schema_migrations.sql"

# The ledger bootstraps the system, so it can't be an entry in the list it
# tracks. `verify` excludes it from the manifest <-> files comparison.
NON_MANIFEST_FILES = {LEDGER_SQL_PATH.name}

# Exit codes. 2 is load-bearing: callers (bin/railway-migrate.sh, the opt-in
# boot hook) treat it as "nothing to do here", not as a failure, so a Railway
# service without DATABASE_URL boots normally instead of crash-looping.
EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_CANNOT_RUN = 2

# Two sessions must not apply the same migration concurrently (two Railway
# replicas booting together, or a deploy racing a manual run). Postgres
# advisory locks are held for the session and released on disconnect, so a
# killed process cannot strand the lock.
ADVISORY_LOCK_KEY = 0x77494C41  # 'WILA'

# Statements that destroy data or schema. CLAUDE.md: never auto-drop tables,
# columns, or migrations — so these are refused unless a human passes
# --allow-destructive. DROP INDEX/POLICY/TRIGGER/CONSTRAINT are deliberately
# absent: `DROP POLICY IF EXISTS ... ; CREATE POLICY ...` is the idempotency
# idiom used throughout this repo and flagging it would make the gate noise.
_DESTRUCTIVE_PATTERNS = (
    (re.compile(r"\bDROP\s+TABLE\b", re.I), "DROP TABLE"),
    (re.compile(r"\bDROP\s+COLUMN\b", re.I), "DROP COLUMN"),
    (re.compile(r"\bDROP\s+SCHEMA\b", re.I), "DROP SCHEMA"),
    (re.compile(r"\bDROP\s+DATABASE\b", re.I), "DROP DATABASE"),
    (re.compile(r"\bTRUNCATE\b", re.I), "TRUNCATE"),
    (re.compile(r"\bDELETE\s+FROM\b", re.I), "DELETE FROM"),
)

_IDEMPOTENCY_MARKERS = re.compile(r"IF\s+NOT\s+EXISTS|IF\s+EXISTS|OR\s+REPLACE", re.I)

# Escape hatch for a future migration that genuinely cannot run in a
# transaction (CREATE INDEX CONCURRENTLY, ALTER TYPE ... ADD VALUE). None of
# the current 239 need it — every one of them is transaction-safe.
_NO_TXN_MARKER = re.compile(r"^\s*--\s*migrate:no-transaction\s*$", re.I | re.M)


# --------------------------------------------------------------------------
# SQL text handling
# --------------------------------------------------------------------------

def strip_sql_comments(sql: str) -> str:
    """Remove /* */ and -- comments.

    Required before scanning for destructive statements: these files are
    heavily commented and several *describe* drops in prose ("Drops: the
    unused pool tables"). Scanning raw text flags those as destructive and
    the gate becomes noise everyone learns to bypass.
    """
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def destructive_statements(sql: str) -> list[str]:
    """Destructive statement kinds present in `sql`, comments excluded."""
    body = strip_sql_comments(sql)
    return [label for pattern, label in _DESTRUCTIVE_PATTERNS if pattern.search(body)]


def looks_idempotent(sql: str) -> bool:
    """Heuristic: does this file use any re-runnable guard?

    Reported by `verify`, never enforced — a pure `INSERT ... ON CONFLICT`
    seed is perfectly re-runnable without matching this pattern. It is a
    signal for review, not a gate.
    """
    return bool(_IDEMPOTENCY_MARKERS.search(strip_sql_comments(sql)))


def wants_no_transaction(sql: str) -> bool:
    return bool(_NO_TXN_MARKER.search(sql))


def checksum(text: str) -> str:
    """sha256 of the file's bytes, newline-normalised.

    Normalised so a CRLF checkout doesn't report drift on every file.
    """
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Migration:
    version: str
    filename: str

    @property
    def path(self) -> Path:
        return MIGRATIONS_DIR / self.filename

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")


class ManifestError(RuntimeError):
    pass


def load_manifest(path: Path = MANIFEST_PATH) -> list[Migration]:
    """Parse manifest.txt into ordered Migrations.

    Raises ManifestError on anything malformed — a manifest that silently
    half-parses is worse than no manifest, because `apply` would skip entries
    without saying so.
    """
    if not path.exists():
        raise ManifestError(f"manifest not found: {path}")

    migrations: list[Migration] = []
    seen_versions: dict[str, int] = {}
    seen_files: dict[str, int] = {}

    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            raise ManifestError(
                f"{path.name}:{lineno}: expected '<version>\\t<filename>', got {raw!r}"
            )
        version, filename = parts[0].strip(), parts[1].strip()
        if not re.fullmatch(r"\d{4,}", version):
            raise ManifestError(f"{path.name}:{lineno}: bad version {version!r}")
        if version in seen_versions:
            raise ManifestError(
                f"{path.name}:{lineno}: duplicate version {version} "
                f"(first seen line {seen_versions[version]})"
            )
        if filename in seen_files:
            raise ManifestError(
                f"{path.name}:{lineno}: duplicate file {filename} "
                f"(first seen line {seen_files[filename]})"
            )
        seen_versions[version] = lineno
        seen_files[filename] = lineno
        migrations.append(Migration(version=version, filename=filename))

    return migrations


def next_version(migrations: Iterable[Migration]) -> str:
    highest = max((int(m.version) for m in migrations), default=0)
    return f"{highest + 1:04d}"


# --------------------------------------------------------------------------
# Database access (lazy — psycopg2 is never imported by the web app)
# --------------------------------------------------------------------------

class CannotRun(RuntimeError):
    """Environment can't run migrations. Callers exit 2, never 1."""


def connect(database_url: str | None = None):
    """Open an autocommit connection, or raise CannotRun.

    Autocommit at the connection level; each migration opens its own explicit
    transaction so a failure rolls back that file alone and the ledger row
    lands atomically with the DDL it describes.
    """
    url = database_url or os.getenv("DATABASE_URL")
    if not url:
        raise CannotRun(
            "DATABASE_URL is not set.\n"
            "  Railway/Supabase: copy the Postgres connection string into the\n"
            "  service env (see .env.example). To apply by hand instead, run\n"
            "  `python scripts/migrate.py plan` and paste each file into the\n"
            "  Supabase SQL Editor — that remains a supported workflow."
        )
    try:
        import psycopg2  # noqa: PLC0415 — lazy on purpose; not a runtime dep of app.py
    except ImportError as exc:
        raise CannotRun(
            "psycopg2 is not installed (pip install psycopg2-binary).\n"
            "  It is listed in requirements.txt for the runner; the Flask app\n"
            "  never imports it."
        ) from exc

    try:
        conn = psycopg2.connect(url)
    except Exception as exc:  # noqa: BLE001 — surfaced verbatim to the operator
        raise CannotRun(f"could not connect to the database: {exc}") from exc
    conn.autocommit = True
    return conn


def ensure_ledger(conn) -> None:
    """Create public.schema_migrations if absent. Idempotent."""
    with conn.cursor() as cur:
        cur.execute(LEDGER_SQL_PATH.read_text(encoding="utf-8"))


def fetch_applied(conn) -> dict[str, dict]:
    """version -> ledger row."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT version, filename, checksum, applied_at, applied_by, baselined "
            "FROM public.schema_migrations"
        )
        rows = cur.fetchall()
    return {
        r[0]: {
            "version": r[0],
            "filename": r[1],
            "checksum": r[2],
            "applied_at": r[3],
            "applied_by": r[4],
            "baselined": r[5],
        }
        for r in rows
    }


def actor() -> str:
    return os.getenv("MIGRATION_ACTOR") or os.getenv("USER") or "unknown"


class _AdvisoryLock:
    """Session-scoped advisory lock so two runners can't apply concurrently."""

    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        with self._conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s)", (ADVISORY_LOCK_KEY,))
            if not cur.fetchone()[0]:
                raise CannotRun(
                    "another migration run holds the advisory lock; "
                    "not applying concurrently."
                )
        return self

    def __exit__(self, *exc):
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (ADVISORY_LOCK_KEY,))
        except Exception:  # noqa: BLE001 — disconnect already released it
            pass
        return False


# --------------------------------------------------------------------------
# verify — hermetic; this is the CI gate
# --------------------------------------------------------------------------

def cmd_verify(args) -> int:
    try:
        migrations = load_manifest()
    except ManifestError as exc:
        print(f"FAIL  {exc}")
        return EXIT_FAILURE

    problems: list[str] = []
    warnings: list[str] = []

    on_disk = {p.name for p in MIGRATIONS_DIR.glob("*.sql")} - NON_MANIFEST_FILES
    in_manifest = {m.filename for m in migrations}

    for missing in sorted(in_manifest - on_disk):
        problems.append(f"manifest lists {missing}, but the file does not exist")
    for untracked in sorted(on_disk - in_manifest):
        problems.append(
            f"{untracked} is not in manifest.txt "
            f"(add it with `migrate.py new`, or append it by hand)"
        )

    # Contiguous and ascending. A gap means a line was deleted; applied
    # versions are recorded by version, so deleting one desynchronises every
    # environment that already ran it.
    for index, migration in enumerate(migrations, start=1):
        if int(migration.version) != index:
            problems.append(
                f"version {migration.version} ({migration.filename}) is out of "
                f"sequence — expected {index:04d}. Versions must be contiguous "
                f"and ascending; never renumber or delete."
            )
            break

    destructive: list[tuple[str, str, list[str]]] = []
    non_idempotent: list[str] = []
    for migration in migrations:
        if migration.filename not in on_disk:
            continue
        try:
            sql = migration.read()
        except OSError as exc:
            problems.append(f"{migration.filename}: unreadable ({exc})")
            continue
        if not sql.strip():
            warnings.append(f"{migration.filename}: file is empty")
        kinds = destructive_statements(sql)
        if kinds:
            destructive.append((migration.version, migration.filename, kinds))
        if not looks_idempotent(sql):
            non_idempotent.append(f"{migration.version} {migration.filename}")

    if not LEDGER_SQL_PATH.exists():
        problems.append(f"missing ledger bootstrap: {LEDGER_SQL_PATH.name}")

    print(f"manifest : {len(migrations)} migrations, versions 0001..{migrations[-1].version if migrations else '----'}")
    print(f"on disk  : {len(on_disk)} .sql files (excluding {LEDGER_SQL_PATH.name})")
    print(f"guards   : {len(migrations) - len(non_idempotent)}/{len(migrations)} carry an "
          f"IF [NOT] EXISTS / OR REPLACE guard")
    print(f"destructive: {len(destructive)} file(s) need --allow-destructive to apply")

    if args.verbose:
        if destructive:
            print("\n  destructive files:")
            for version, filename, kinds in destructive:
                print(f"    {version} {filename}  [{', '.join(kinds)}]")
        if non_idempotent:
            print("\n  no re-run guard detected (review, not a failure):")
            for entry in non_idempotent:
                print(f"    {entry}")

    for warning in warnings:
        print(f"WARN  {warning}")

    if problems:
        print()
        for problem in problems:
            print(f"FAIL  {problem}")
        print(f"\nverify FAILED — {len(problems)} problem(s)")
        return EXIT_FAILURE

    print("\nverify OK")
    return EXIT_OK


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------

def cmd_status(args) -> int:
    migrations = load_manifest()
    conn = connect(args.database_url)
    try:
        ensure_ledger(conn)
        applied = fetch_applied(conn)
    finally:
        conn.close()

    pending: list[Migration] = []
    drifted: list[tuple[Migration, dict]] = []
    baselined = 0

    for migration in migrations:
        row = applied.get(migration.version)
        if row is None:
            pending.append(migration)
            continue
        if row["baselined"]:
            baselined += 1
        if not migration.path.exists():
            continue
        # Checksum drift on a baselined row is expected and harmless: nobody
        # ran the file, so the recorded hash only pins what the file looked
        # like at baseline time. Drift on a REAL apply is the dangerous case —
        # the DB was built from different SQL than the repo now contains.
        if not row["baselined"] and row["checksum"] != checksum(migration.read()):
            drifted.append((migration, row))

    unknown = sorted(set(applied) - {m.version for m in migrations})

    print(f"applied  : {len(applied)} / {len(migrations)}  ({baselined} baselined, "
          f"{len(applied) - baselined} run by the runner)")
    print(f"pending  : {len(pending)}")
    if drifted:
        print(f"DRIFT    : {len(drifted)}  <- file edited after it was applied")
    if unknown:
        print(f"unknown  : {len(unknown)} version(s) in the DB but not in the manifest")

    if pending:
        print("\npending, in order:")
        for migration in pending:
            kinds = (destructive_statements(migration.read())
                     if migration.path.exists() else [])
            flag = f"  [DESTRUCTIVE: {', '.join(kinds)}]" if kinds else ""
            missing = "" if migration.path.exists() else "  [FILE MISSING]"
            print(f"  {migration.version}  {migration.filename}{flag}{missing}")

    if drifted:
        print("\ndrift — these files changed after being applied here:")
        for migration, row in drifted:
            print(f"  {migration.version}  {migration.filename}")
            print(f"      applied {row['applied_at']} by {row['applied_by']}")
            print(f"      recorded {row['checksum'][:12]}  now {checksum(migration.read())[:12]}")
        print("\n  This database was built from different SQL than the repo now")
        print("  contains. Reconcile by hand — write a NEW forward migration;")
        print("  never edit an applied file to match.")

    if unknown:
        print("\nin the DB but not in the manifest:")
        for version in unknown:
            print(f"  {version}  {applied[version]['filename']}")

    if not pending and not drifted and not unknown:
        print("\nup to date.")
    return EXIT_OK


# --------------------------------------------------------------------------
# plan / apply
# --------------------------------------------------------------------------

def _select_pending(migrations, applied, to_version: str | None) -> list[Migration]:
    pending = [m for m in migrations if m.version not in applied]
    if to_version:
        pending = [m for m in pending if int(m.version) <= int(to_version)]
    return pending


def cmd_plan(args) -> int:
    migrations = load_manifest()
    if args.offline:
        applied: dict[str, dict] = {}
        print("(offline — assuming an empty database)\n")
    else:
        conn = connect(args.database_url)
        try:
            ensure_ledger(conn)
            applied = fetch_applied(conn)
        finally:
            conn.close()

    pending = _select_pending(migrations, applied, args.to)
    if not pending:
        print("nothing pending.")
        return EXIT_OK

    print(f"{len(pending)} migration(s) would run, in this order:\n")
    blocked = 0
    for migration in pending:
        if not migration.path.exists():
            print(f"  {migration.version}  {migration.filename}   [FILE MISSING — would abort]")
            blocked += 1
            continue
        kinds = destructive_statements(migration.read())
        if kinds and not args.allow_destructive:
            print(f"  {migration.version}  {migration.filename}   "
                  f"[BLOCKED: {', '.join(kinds)} — needs --allow-destructive]")
            blocked += 1
        else:
            suffix = f"   [{', '.join(kinds)}]" if kinds else ""
            print(f"  {migration.version}  {migration.filename}{suffix}")

    if blocked:
        print(f"\n{blocked} migration(s) would block `apply`.")
    return EXIT_OK


def cmd_apply(args) -> int:
    migrations = load_manifest()
    conn = connect(args.database_url)
    applied_count = 0
    try:
        ensure_ledger(conn)
        with _AdvisoryLock(conn):
            applied = fetch_applied(conn)
            pending = _select_pending(migrations, applied, args.to)
            if args.limit:
                pending = pending[: args.limit]

            if not pending:
                print("nothing pending.")
                return EXIT_OK

            # Pre-flight the whole batch before touching anything, so a
            # destructive file at position 9 doesn't get discovered only
            # after 8 migrations already landed.
            for migration in pending:
                if not migration.path.exists():
                    print(f"ABORT  {migration.version} {migration.filename}: file missing")
                    return EXIT_FAILURE
                kinds = destructive_statements(migration.read())
                if kinds and not args.allow_destructive:
                    print(f"ABORT  {migration.version} {migration.filename} contains "
                          f"{', '.join(kinds)}.")
                    print("       CLAUDE.md: never auto-drop tables/columns/migrations.")
                    print("       Review it, then re-run with --allow-destructive to")
                    print("       apply it deliberately. Automation never passes that flag.")
                    return EXIT_FAILURE

            if args.dry_run:
                print(f"dry-run — {len(pending)} migration(s) would run:")
                for migration in pending:
                    print(f"  {migration.version}  {migration.filename}")
                return EXIT_OK

            who = actor()
            for migration in pending:
                sql = migration.read()
                digest = checksum(sql)
                started = time.monotonic()
                print(f"applying {migration.version}  {migration.filename} ... ", end="", flush=True)
                try:
                    _apply_one(conn, migration, sql, digest, who, started)
                except Exception as exc:  # noqa: BLE001 — reported, then we stop
                    print("FAILED")
                    print(f"\n  {type(exc).__name__}: {exc}")
                    print(f"\n  Rolled back {migration.filename}. "
                          f"{applied_count} earlier migration(s) stayed applied.")
                    print("  Fix the SQL and re-run; already-applied files are skipped.")
                    return EXIT_FAILURE
                elapsed_ms = int((time.monotonic() - started) * 1000)
                print(f"ok ({elapsed_ms} ms)")
                applied_count += 1
    finally:
        conn.close()

    print(f"\napplied {applied_count} migration(s).")
    return EXIT_OK


def _apply_one(conn, migration: Migration, sql: str, digest: str, who: str, started: float) -> None:
    """Run one migration and record it atomically.

    The DDL and its ledger row commit together, so the ledger can never claim
    a migration ran when it didn't (or vice versa). Postgres has transactional
    DDL, which is what makes this possible.

    The `-- migrate:no-transaction` escape hatch exists for statements that
    Postgres refuses to run in a transaction block (CREATE INDEX
    CONCURRENTLY). None of the current 239 need it; when one does, the ledger
    row is written separately and a mid-file failure leaves partial state,
    which is why it must be opt-in per file.
    """
    ledger_insert = (
        "INSERT INTO public.schema_migrations "
        "(version, filename, checksum, applied_by, execution_ms, baselined) "
        "VALUES (%s, %s, %s, %s, %s, FALSE)"
    )

    if wants_no_transaction(sql):
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(ledger_insert, (
                migration.version, migration.filename, digest, who,
                int((time.monotonic() - started) * 1000),
            ))
        return

    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(ledger_insert, (
                migration.version, migration.filename, digest, who,
                int((time.monotonic() - started) * 1000),
            ))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.autocommit = True


# --------------------------------------------------------------------------
# baseline — the adoption path
# --------------------------------------------------------------------------

def cmd_baseline(args) -> int:
    """Record migrations as applied WITHOUT running them.

    This is how an already-hand-migrated database adopts tracking. Prod has
    all 239 files applied out of band; replaying them would be wrong (13 have
    no re-run guard, 17 contain DROP TABLE). Baselining says "assume these are
    present" and starts real tracking from the next one.

    The rows are marked baselined=TRUE so nobody later mistakes an assumption
    for a verified apply.
    """
    migrations = load_manifest()

    # --sql emits the statements instead of running them, so a database that
    # is only reachable through the Supabase SQL Editor can still be
    # baselined. Without this the adoption path required DATABASE_URL, which
    # the founder's environment does not have (docs/RLS-AUDIT.md) — i.e. the
    # one machine that most needs to adopt tracking couldn't.
    if args.sql:
        return _emit_baseline_sql(migrations, args.to)

    conn = connect(args.database_url)
    try:
        ensure_ledger(conn)
        with _AdvisoryLock(conn):
            applied = fetch_applied(conn)
            targets = [m for m in migrations if m.version not in applied]
            if args.to:
                targets = [m for m in targets if int(m.version) <= int(args.to)]

            if not targets:
                print("nothing to baseline — every manifest entry is already recorded.")
                return EXIT_OK

            print(f"baseline: {len(targets)} migration(s) "
                  f"({targets[0].version}..{targets[-1].version})")
            print("These will be recorded as applied. NO SQL WILL RUN.\n")

            if args.dry_run:
                for migration in targets:
                    print(f"  {migration.version}  {migration.filename}")
                print("\n(dry-run — nothing recorded)")
                return EXIT_OK

            if not args.yes:
                print("Only do this if the database already has these migrations applied.")
                print("On a fresh/empty database use `apply` instead — baselining an")
                print("empty DB permanently hides the fact that nothing ever ran.\n")
                reply = input("Type 'baseline' to confirm: ").strip()
                if reply != "baseline":
                    print("aborted.")
                    return EXIT_FAILURE

            who = actor()
            with conn.cursor() as cur:
                for migration in targets:
                    digest = (checksum(migration.read())
                              if migration.path.exists() else "file-missing")
                    cur.execute(
                        "INSERT INTO public.schema_migrations "
                        "(version, filename, checksum, applied_by, execution_ms, baselined) "
                        "VALUES (%s, %s, %s, %s, NULL, TRUE) "
                        "ON CONFLICT (version) DO NOTHING",
                        (migration.version, migration.filename, digest, who),
                    )
    finally:
        conn.close()

    print(f"recorded {len(targets)} migration(s) as baselined.")
    print("Tracking is live — `apply` now runs only what comes after.")
    return EXIT_OK


# --------------------------------------------------------------------------
# new
# --------------------------------------------------------------------------

_TEMPLATE = """-- {title}
--
-- TODO: what this changes and why. Note anything that must be deployed
-- before or after it runs.
--
-- Idempotent + additive, per the standing constraint: safe to re-run.

-- e.g.
-- ALTER TABLE public.some_table
--     ADD COLUMN IF NOT EXISTS some_column TEXT;
"""


def _sql_quote(value: str) -> str:
    """Single-quote a literal for SQL, doubling embedded quotes."""
    return "'" + value.replace("'", "''") + "'"


def _emit_baseline_sql(migrations: list[Migration], to_version: str | None) -> int:
    """Print a paste-able baseline for the Supabase SQL Editor.

    Generated rather than committed as a static file: a checked-in
    baseline.sql goes stale the moment a migration is added, and a stale
    baseline silently under-records. This always reflects the current
    manifest.

    ON CONFLICT DO NOTHING makes it re-runnable and, more importantly, safe
    to run on a database that has already recorded some of these — it can
    never overwrite a real apply (baselined = FALSE) with an assumption.
    """
    targets = list(migrations)
    if to_version:
        targets = [m for m in targets if int(m.version) <= int(to_version)]
    if not targets:
        print("-- nothing to baseline")
        return EXIT_OK

    # Records HOW the row got there, which is the useful fact months later:
    # this block was pasted into the SQL Editor, not run by the runner.
    who = os.getenv("MIGRATION_ACTOR") or "sql-editor-baseline"
    print("-- willab migration baseline — generated by scripts/migrate.py baseline --sql")
    print("--")
    print("-- Records these migrations as ALREADY APPLIED. Runs no DDL.")
    print("-- Only run this against a database that genuinely has them applied;")
    print("-- on an empty database use `migrate.py apply` instead.")
    print("--")
    print("-- Paste into the Supabase SQL Editor AFTER create_schema_migrations.sql.")
    print("-- Safe to re-run: ON CONFLICT DO NOTHING never overwrites an existing row.")
    print(f"-- {len(targets)} migration(s): {targets[0].version}..{targets[-1].version}")
    print()
    print("INSERT INTO public.schema_migrations")
    print("    (version, filename, checksum, applied_by, execution_ms, baselined)")
    print("VALUES")

    rows = []
    for migration in targets:
        digest = checksum(migration.read()) if migration.path.exists() else "file-missing"
        rows.append(
            f"    ({_sql_quote(migration.version)}, {_sql_quote(migration.filename)}, "
            f"{_sql_quote(digest)}, {_sql_quote(who)}, NULL, TRUE)"
        )
    print(",\n".join(rows))
    print("ON CONFLICT (version) DO NOTHING;")
    print()
    print("-- Verify:")
    print("-- SELECT count(*) FILTER (WHERE baselined) AS baselined,")
    print("--        count(*) FILTER (WHERE NOT baselined) AS run_by_runner")
    print("-- FROM public.schema_migrations;")
    return EXIT_OK


def cmd_new(args) -> int:
    slug = re.sub(r"[^a-z0-9_]+", "_", args.name.lower()).strip("_")
    if not slug:
        print("FAIL  name must contain letters or digits")
        return EXIT_FAILURE

    migrations = load_manifest()
    version = next_version(migrations)
    filename = f"{slug}.sql"
    path = MIGRATIONS_DIR / filename

    if path.exists():
        print(f"FAIL  {filename} already exists")
        return EXIT_FAILURE
    if any(m.filename == filename for m in migrations):
        print(f"FAIL  {filename} is already in the manifest")
        return EXIT_FAILURE

    path.write_text(_TEMPLATE.format(title=args.name), encoding="utf-8")

    with MANIFEST_PATH.open("a", encoding="utf-8") as handle:
        handle.write(f"{version}\t{filename}\n")

    print(f"created migrations/{filename}")
    print(f"appended {version}\t{filename} to migrations/manifest.txt")
    return EXIT_OK


# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="migrate.py",
        description="Ordered, tracked, forward-only migrations for willab.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def with_db(sp):
        sp.add_argument("--database-url", default=None,
                        help="Postgres URL (default: $DATABASE_URL)")
        return sp

    verify = sub.add_parser("verify", help="structural check; no database needed (CI gate)")
    verify.add_argument("-v", "--verbose", action="store_true",
                        help="list destructive and unguarded files")
    verify.set_defaults(func=cmd_verify)

    status = with_db(sub.add_parser("status", help="applied / pending / drifted for this database"))
    status.set_defaults(func=cmd_status)

    plan = with_db(sub.add_parser("plan", help="what `apply` would do"))
    plan.add_argument("--to", default=None, metavar="VERSION", help="stop at this version")
    plan.add_argument("--offline", action="store_true",
                      help="assume an empty database; no connection made")
    plan.add_argument("--allow-destructive", action="store_true")
    plan.set_defaults(func=cmd_plan)

    apply_ = with_db(sub.add_parser("apply", help="run pending migrations in order"))
    apply_.add_argument("--to", default=None, metavar="VERSION", help="stop at this version")
    apply_.add_argument("--limit", type=int, default=None, help="apply at most N migrations")
    apply_.add_argument("--dry-run", action="store_true",
                        help="pre-flight only; nothing is executed")
    apply_.add_argument("--allow-destructive", action="store_true",
                        help="permit DROP TABLE / DROP COLUMN / TRUNCATE / DELETE FROM")
    apply_.set_defaults(func=cmd_apply)

    baseline = with_db(sub.add_parser(
        "baseline", help="record migrations as applied WITHOUT running them"))
    baseline.add_argument("--to", default=None, metavar="VERSION",
                          help="baseline up to this version (default: all)")
    baseline.add_argument("--dry-run", action="store_true")
    baseline.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    baseline.add_argument("--sql", action="store_true",
                          help="print the SQL instead of running it, for the Supabase "
                               "SQL Editor (needs no DATABASE_URL)")
    baseline.set_defaults(func=cmd_baseline)

    new = sub.add_parser("new", help="scaffold a migration and append it to the manifest")
    new.add_argument("name", help="slug, e.g. add_speaker_locale_to_recordings")
    new.set_defaults(func=cmd_new)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except CannotRun as exc:
        # Exit 2, never 1: "can't run here" is not a failed migration, and
        # deploy wrappers must not treat it as one.
        print(f"cannot run: {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN
    except ManifestError as exc:
        print(f"manifest error: {exc}", file=sys.stderr)
        return EXIT_FAILURE
    except KeyboardInterrupt:
        print("\ninterrupted.", file=sys.stderr)
        return EXIT_FAILURE
    except Exception as exc:  # noqa: BLE001
        # An operator reading a Railway deploy log needs the error, not a
        # traceback. Anything unexpected here (a database that rejects the
        # ledger DDL, a permissions failure) still exits 1 so the deploy stops.
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_FAILURE


if __name__ == "__main__":
    sys.exit(main())
