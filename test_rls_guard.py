"""The deploy-time RLS assertion — scripts/rls_guard.py.

docs/RLS-AUDIT.md · bin/railway-web.sh

WHAT THIS PINS DOWN
  * the guard CANNOT fail a boot — every degraded path exits 0 or 2, never
    raises, and --strict (the only way to get exit 1) is never on the boot
    path;
  * an unreachable database reports SKIPPED, never "OK". A security check that
    reports success when it did not run is worse than no check, because it
    ends the investigation;
  * extension-owned routines are excluded from both queries — revoking
    pgcrypto's gen_random_uuid() would break DEFAULTs that call it;
  * the queries stay the ones docs/RLS-AUDIT.md calls authoritative.

The queries are exercised against a real PostgreSQL 16 in development (see the
PR); CI has no Postgres, so everything here runs against a fake connection.

Run: python3 -m unittest test_rls_guard
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))


class FakeCursor:
    """Answers the three queries the guard asks, by shape not by parsing."""

    def __init__(self, tables, functions, anon_exists):
        self.tables, self.functions = tables, functions
        self.anon_exists = anon_exists
        self._rows: list = []
        self.closed = False

    def execute(self, sql, params=None):
        if "pg_roles" in sql:
            self._rows = [(1,)] if self.anon_exists else []
        elif "relrowsecurity" in sql:
            self._rows = [(t,) for t in self.tables]
        elif "has_function_privilege" in sql:
            self._rows = [(f,) for f in self.functions]
        else:                                    # pragma: no cover
            raise AssertionError(f"unexpected query: {sql[:80]}")

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, tables=(), functions=(), anon_exists=True):
        self.args = (list(tables), list(functions), anon_exists)
        self.closed = False

    def cursor(self):
        return FakeCursor(*self.args)

    def close(self):
        self.closed = True


def run_main(argv, conn=None, exc=None):
    """Invoke main() with connect() stubbed. Returns (exit_code, stdout)."""
    import rls_guard

    def _connect(*_a, **_k):
        if exc is not None:
            raise exc
        return conn

    buf = io.StringIO()
    with patch.object(rls_guard, "connect", _connect), redirect_stdout(buf):
        code = rls_guard.main(argv)
    return code, buf.getvalue()


class CannotFailABootTests(unittest.TestCase):
    """The live-loop constraint. Nothing this script does is worth a
    crash-looping web service."""

    def test_findings_alone_never_produce_a_nonzero_exit(self):
        code, out = run_main([], FakeConn(tables=["leaky"], functions=["f(x text)"]))
        self.assertEqual(code, 0)
        self.assertIn("EXPOSURE FOUND", out)

    def test_strict_is_the_only_route_to_exit_1(self):
        conn = FakeConn(tables=["leaky"])
        self.assertEqual(run_main([], conn)[0], 0)
        self.assertEqual(run_main(["--strict"], FakeConn(tables=["leaky"]))[0], 1)

    def test_the_boot_hook_does_not_pass_strict(self):
        """If this ever changes, a newly-created table takes production down on
        the next deploy."""
        hook = Path(__file__).resolve().parent / "bin" / "railway-web.sh"
        text = hook.read_text(encoding="utf-8")
        self.assertIn("scripts/rls_guard.py", text, "guard is not wired into boot")
        line = next(ln for ln in text.splitlines() if "rls_guard.py" in ln and not ln.strip().startswith("#"))
        self.assertNotIn("--strict", line)
        self.assertIn("|| true", line)

    def test_a_clean_database_says_so(self):
        code, out = run_main([], FakeConn())
        self.assertEqual(code, 0)
        self.assertIn("OK", out)
        self.assertNotIn("EXPOSURE", out)


class NeverReportsAFalseOkTests(unittest.TestCase):
    """A check that says OK when it did not run ends the investigation. That is
    worse than no check."""

    def test_no_database_url_reports_skipped_not_ok(self):
        import rls_guard
        code, out = run_main([], exc=rls_guard.CannotRun("DATABASE_URL is not set."))
        self.assertEqual(code, 2)
        self.assertIn("skipped", out)
        self.assertNotIn("OK", out)

    def test_unreachable_database_reports_skipped_not_ok(self):
        import rls_guard
        code, out = run_main(
            [], exc=rls_guard.CannotRun("could not connect to the database: boom"))
        self.assertEqual(code, 2)
        self.assertIn("skipped", out)
        self.assertNotIn("OK", out)

    def test_skipped_json_is_null_rather_than_true(self):
        import rls_guard
        _, out = run_main(["--json"], exc=rls_guard.CannotRun("nope"))
        self.assertIsNone(json.loads(out)["ok"])

    def test_a_database_without_the_anon_role_says_functions_were_not_checked(self):
        """Roles are cluster-wide, so this is easy to miss live: a plain
        Postgres has no `anon`, and silently reporting a clean bill of health
        would hide that half the check never ran."""
        import rls_guard
        line = rls_guard.report({"tables": [], "functions": [], "anon_role": False})
        self.assertIn("OK", line)
        self.assertIn("functions not checked", line)
        self.assertNotIn("functions not checked",
                         rls_guard.report({"tables": [], "functions": [],
                                           "anon_role": True}))

    def test_the_connection_is_closed_even_when_the_audit_raises(self):
        import rls_guard
        conn = FakeConn()
        with patch.object(rls_guard, "connect", lambda *a, **k: conn), \
             patch.object(rls_guard, "audit", side_effect=RuntimeError("boom")), \
             self.assertRaises(RuntimeError):
            rls_guard.main([])
        self.assertTrue(conn.closed)


class QueryShapeTests(unittest.TestCase):
    """The queries are the whole product. Guard their load-bearing clauses."""

    def test_both_queries_exclude_extension_owned_objects(self):
        """Revoking EXECUTE on pgcrypto's gen_random_uuid() would break every
        DEFAULT that calls it — the same guard the sweeps carry."""
        import rls_guard
        for sql in (rls_guard.SQL_TABLES_WITHOUT_RLS,
                    rls_guard.SQL_FUNCTIONS_ANON_CAN_EXECUTE):
            self.assertIn("pg_depend", sql)
            self.assertIn("'e'", sql)

    def test_the_table_query_covers_partitioned_tables(self):
        import rls_guard
        self.assertIn("'r', 'p'", rls_guard.SQL_TABLES_WITHOUT_RLS)
        self.assertIn("relrowsecurity = false", rls_guard.SQL_TABLES_WITHOUT_RLS)

    def test_the_function_query_covers_procedures_and_asks_about_anon(self):
        import rls_guard
        self.assertIn("'f', 'p'", rls_guard.SQL_FUNCTIONS_ANON_CAN_EXECUTE)
        self.assertIn("has_function_privilege('anon'",
                      rls_guard.SQL_FUNCTIONS_ANON_CAN_EXECUTE)

    def test_the_missing_anon_role_short_circuits_the_function_query(self):
        """has_function_privilege on a nonexistent role aborts with 42704 and
        would take the table half of the check down with it."""
        code, out = run_main(["--json"], FakeConn(functions=["would_be_found()"],
                                                 anon_exists=False))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["functions"], [])


class ReportContentTests(unittest.TestCase):
    def test_it_names_the_offenders_and_the_fix(self):
        _, out = run_main([], FakeConn(tables=["v2_sessions"],
                                       functions=["token_charge(a text)"]))
        self.assertIn("v2_sessions", out)
        self.assertIn("token_charge(a text)", out)
        self.assertIn("ENABLE ROW LEVEL SECURITY", out)
        self.assertIn("REVOKE ALL ON FUNCTION", out)
        self.assertIn("docs/RLS-AUDIT.md", out)

    def test_json_is_machine_readable(self):
        _, out = run_main(["--json"], FakeConn(tables=["a"], functions=["b()"]))
        payload = json.loads(out)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["tables"], ["a"])
        self.assertEqual(payload["functions"], ["b()"])

    def test_sentry_is_best_effort_and_silent_on_a_clean_run(self):
        import rls_guard
        with patch.dict(os.environ, {"SENTRY_DSN": "https://x@example.invalid/1"}):
            # A broken/absent sentry_sdk must not disturb the exit code.
            code, _ = run_main([], FakeConn(tables=["leaky"]))
            self.assertEqual(code, 0)
        # Nothing to report -> returns before touching the environment at all.
        rls_guard._tell_sentry({"tables": [], "functions": [], "anon_role": True})

    def test_sentry_reports_findings_through_the_real_api(self):
        """The reporter must actually REPORT.

        The first version of _tell_sentry called APIs that do not exist in
        sentry-sdk 2.x (``Client.capture_message``, ``with Scope()``). It threw
        on its first line every time and the best-effort ``except`` swallowed
        it, so it never reported anything and no test noticed — the only
        assertion was "does not crash", which a no-op passes trivially.

        This asserts the message LANDS, and binds against the installed SDK's
        real surface so a future API change fails here instead of going quiet.
        """
        import sentry_sdk
        import rls_guard

        for name in ("init", "set_context", "capture_message", "flush"):
            self.assertTrue(hasattr(sentry_sdk, name),
                            f"sentry_sdk.{name} is gone — _tell_sentry needs updating")

        found = {"tables": ["leaky"], "functions": ["f(x text)"], "anon_role": True}
        with patch.dict(os.environ, {"SENTRY_DSN": "https://k@example.invalid/1"}), \
             patch.object(sentry_sdk, "init") as init, \
             patch.object(sentry_sdk, "set_context") as set_context, \
             patch.object(sentry_sdk, "capture_message") as capture, \
             patch.object(sentry_sdk, "flush"):
            rls_guard._tell_sentry(found)

        init.assert_called_once()
        capture.assert_called_once()
        self.assertEqual(capture.call_args.kwargs.get("level"), "error")
        msg = capture.call_args.args[0]
        self.assertIn("1 table(s) without RLS", msg)
        self.assertIn("1 anon-callable function(s)", msg)
        ctx = set_context.call_args.args[1]
        self.assertEqual(ctx["tables_without_rls"], ["leaky"])
        self.assertEqual(ctx["functions_anon_can_execute"], ["f(x text)"])

    def test_sentry_is_skipped_entirely_without_a_dsn(self):
        import sentry_sdk
        import rls_guard
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(sentry_sdk, "init") as init:
            rls_guard._tell_sentry({"tables": ["leaky"], "functions": [],
                                    "anon_role": True})
        init.assert_not_called()


if __name__ == "__main__":
    unittest.main()
