#!/usr/bin/env python3
"""Assert, on every boot, that the live database has no anon-reachable surface.

    python3 scripts/rls_guard.py            # report; exit 0 even on findings
    python3 scripts/rls_guard.py --strict   # exit 1 on findings (CI / by hand)
    python3 scripts/rls_guard.py --json     # machine-readable

WHY THIS EXISTS — AND WHY IT IS NOT A CRON
------------------------------------------
The 2026-07-25 incident (docs/RLS-AUDIT.md) was not a clever attack. It was a
DEFAULT: Supabase grants `anon`/`authenticated` on `public`, the FE ships the
anon key inlined in the browser bundle, and 57 tables shipped without anyone
typing the one line that closes it. The founder swept it the same day.

The sweep is self-healing ONLY IF SOMEONE RE-RUNS IT. On 2026-08-03 two new
tables slipped through in a single day of ordinary work — `processing_jobs`
(#322) and `schema_migrations` (#323) — neither covered by the sweep, both
found by accident while building something else. That is the failure mode this
file exists to remove.

A scheduled job was the obvious answer and the wrong one, for the reason this
repo has already written down twice — migrations/add_token_pricing.sql, on the
monthly reset:

    "A monthly reset cron is the obvious design and the wrong one here. It is
     a single point of failure that fails SILENTLY (nobody notices a grant
     that did not happen until a user complains)... and this repo has a
     standing habit of infrastructure that was set up in a migration and never
     actually wired."

All of that applies here and worse: a security check that fails silently reads
exactly like a security check that passes. So this runs on a path that ALREADY
RUNS — the deploy — and says something every time.

WHAT IT CANNOT SEE, AND WHY THAT MATTERS
----------------------------------------
test_migration_security_rules.py already gates the migration FILES in CI. It
cannot see the live database, so it is blind to a table created in the Supabase
dashboard, applied by hand, or made by a tool. This reads `pg_class` /
`pg_proc` directly, so it sees what is actually there. The two layers catch
different things and neither replaces the other.

REPORT, DO NOT AUTO-HEAL
------------------------
This deliberately does not fix what it finds, even though enabling RLS is one
statement. docs/RLS-AUDIT.md § "Residual risk" is the reason: a consumer not
visible from these repos — an Edge Function, a Retool dashboard, a Zapier
integration — starts returning EMPTY rather than erroring loudly when RLS lands
under it. Detection is the valuable half and carries none of that risk;
enabling RLS stays a deliberate act with a human behind it
(migrations/add_rls_all_public_tables.sql).

IT CANNOT FAIL A BOOT
---------------------
Same live-loop constraint as the migrate-on-boot hook: every failure path exits
0 and every exception is swallowed. `--strict` is opt-in and exists for
operators and CI, never for the boot path.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# migrate.py owns DATABASE_URL / psycopg2 handling and the operator-facing
# messages for both. Reuse rather than re-derive, so the two tools cannot drift
# into giving different advice for the same broken environment.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from migrate import CannotRun, connect  # noqa: E402

EXIT_OK = 0
EXIT_FINDINGS = 1        # only reachable with --strict
EXIT_CANNOT_RUN = 2      # mirrors migrate.py

# The authoritative live check from docs/RLS-AUDIT.md § Status. Must return
# zero rows. relkind ('r','p') covers ordinary + partitioned tables; views and
# foreign tables have no RLS of their own.
SQL_TABLES_WITHOUT_RLS = """
SELECT c.relname
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public'
   AND c.relkind IN ('r', 'p')
   AND c.relrowsecurity = false
   AND NOT EXISTS (SELECT 1 FROM pg_depend d
                    WHERE d.objid = c.oid AND d.deptype = 'e')
 ORDER BY 1
"""

# The second door (docs/RLS-AUDIT.md § "The second door"). RLS is table-level
# and says nothing about functions; PostgREST publishes every public function
# at /rest/v1/rpc/<name> and Postgres grants EXECUTE to PUBLIC by default.
# Extension-owned routines are excluded — revoking pgcrypto's gen_random_uuid()
# would break DEFAULTs that call it.
SQL_FUNCTIONS_ANON_CAN_EXECUTE = """
SELECT p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')'
  FROM pg_proc p
  JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'public'
   AND p.prokind IN ('f', 'p')
   AND has_function_privilege('anon', p.oid, 'EXECUTE')
   AND NOT EXISTS (SELECT 1 FROM pg_depend d
                    WHERE d.objid = p.oid AND d.deptype = 'e')
 ORDER BY 1
"""

SQL_ROLE_EXISTS = "SELECT 1 FROM pg_roles WHERE rolname = %s"


def _scalars(conn, sql: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(sql)
        return [str(r[0]) for r in cur.fetchall()]


def audit(conn) -> dict:
    """Return {tables: [...], functions: [...], anon_role: bool}. Never raises
    for a missing `anon` role — a plain Postgres (local dev, CI container) has
    no Supabase roles, and has_function_privilege would abort the whole check
    with 42704 rather than report anything."""
    with conn.cursor() as cur:
        cur.execute(SQL_ROLE_EXISTS, ("anon",))
        anon_exists = cur.fetchone() is not None

    return {
        "tables": _scalars(conn, SQL_TABLES_WITHOUT_RLS),
        "functions": (_scalars(conn, SQL_FUNCTIONS_ANON_CAN_EXECUTE)
                      if anon_exists else []),
        "anon_role": anon_exists,
    }


def report(found: dict) -> str:
    tables, functions = found["tables"], found["functions"]
    if not tables and not functions:
        note = "" if found["anon_role"] else " (no `anon` role — functions not checked)"
        return f"[rls-guard] OK — no public table without RLS, no anon-callable function{note}"

    lines = [
        "[rls-guard] EXPOSURE FOUND — the anon key from the browser bundle can "
        "reach these directly via PostgREST, bypassing Flask entirely:",
    ]
    if tables:
        lines.append(f"  {len(tables)} public table(s) WITHOUT row level security "
                     "(readable AND writable):")
        lines += [f"    - {t}" for t in tables]
        lines.append("    fix: ALTER TABLE public.<table> ENABLE ROW LEVEL SECURITY;")
        lines.append("    or re-run migrations/add_rls_all_public_tables.sql (sweeps all).")
    if functions:
        lines.append(f"  {len(functions)} public function(s) anon can EXECUTE:")
        lines += [f"    - {f}" for f in functions]
        lines.append("    fix: REVOKE ALL ON FUNCTION public.<name>(<types>) FROM PUBLIC, anon, authenticated;")
        lines.append("    or re-run migrations/lock_down_public_function_grants.sql.")
    lines.append("  context: docs/RLS-AUDIT.md")
    return "\n".join(lines)


def _tell_sentry(found: dict) -> None:
    """Best-effort. A monitoring hiccup must never be the reason a boot log is
    missing its security line, so every failure here is swallowed."""
    if not (found["tables"] or found["functions"]):
        return
    try:
        dsn = os.getenv("SENTRY_DSN")
        if not dsn:
            return
        import sentry_sdk  # noqa: PLC0415
        # Its own client: this runs as a standalone process before gunicorn, so
        # app.py's sentry_sdk.init has not happened and there is no hub to use.
        client = sentry_sdk.Client(dsn=dsn)
        with sentry_sdk.Scope() as scope:
            scope.set_level("error")
            scope.set_context("rls_guard", {
                "tables_without_rls": found["tables"],
                "functions_anon_can_execute": found["functions"],
            })
            client.capture_message(
                f"RLS guard: {len(found['tables'])} table(s) without RLS, "
                f"{len(found['functions'])} anon-callable function(s)",
                scope=scope,
            )
        client.flush(timeout=5)
    except Exception:  # noqa: BLE001 — monitoring must never break the check
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Report public tables without RLS and anon-callable functions.")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when something is found (CI / by hand). The "
                         "boot path never passes this.")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    try:
        conn = connect()
    except CannotRun as exc:
        # Not a finding and not a failure: plenty of environments legitimately
        # have no DATABASE_URL (a dev box, the founder's machine — see
        # docs/RLS-AUDIT.md). Say so and get out of the way.
        if args.json:
            print(json.dumps({"ok": None, "skipped": str(exc)}))
        else:
            print(f"[rls-guard] skipped — {exc}")
        return EXIT_CANNOT_RUN

    try:
        found = audit(conn)
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    if args.json:
        print(json.dumps({"ok": not (found["tables"] or found["functions"]), **found}))
    else:
        print(report(found))

    _tell_sentry(found)

    if (found["tables"] or found["functions"]) and args.strict:
        return EXIT_FINDINGS
    return EXIT_OK


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        # The boot path calls this. Nothing it can do is worth a crash-loop.
        print(f"[rls-guard] check failed to run ({type(exc).__name__}: {exc}) "
              "— continuing.")
        sys.exit(EXIT_OK)
