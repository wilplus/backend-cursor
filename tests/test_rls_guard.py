"""
STORY    As an operator, I want the deploy-time row-security check to report
         exposures without ever crashing a boot, and to say SKIPPED when it
         could not run, so that the site stays up and nobody reads a false
         "OK".
OUTCOME
  O1  Findings exit 0 without --strict (the boot path never passes it).
  O2  An unreachable database says skipped, never "OK", and exits 2.
  O3  Extension-owned routines and tables are excluded from both queries
      (reads the SQL text: CI has no Postgres).
  O4  The by-design allowlist is exactly the pinned set (it may only
      shrink); anything not on it is still a finding.
PROVES   O1 -> test_findings_alone_never_produce_a_nonzero_exit
         O2 -> test_an_unreachable_database_says_skipped_never_ok
         O3 -> test_extension_routines_are_excluded_from_both_queries
         O4 -> test_the_allowlist_is_exactly_the_pinned_set,
               test_anything_not_on_the_list_is_still_a_finding
WHY      scripts/rls_guard.py runs in bin/railway-web.sh; docs/RLS-AUDIT.md.
"""
from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


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

    def test_an_unreachable_database_says_skipped_never_ok(self):
        import rls_guard
        code, out = run_main([], exc=rls_guard.CannotRun("no DATABASE_URL"))
        self.assertEqual(code, rls_guard.EXIT_CANNOT_RUN)
        self.assertIn("skipped", out)
        self.assertNotIn("OK", out)
        code, out = run_main([], FakeConn())
        self.assertEqual(code, 0)
        self.assertIn("OK", out)

    def test_extension_routines_are_excluded_from_both_queries(self):
        import rls_guard
        for query in (rls_guard.SQL_TABLES_WITHOUT_RLS,
                      rls_guard.SQL_FUNCTIONS_ANON_CAN_EXECUTE):
            self.assertIn("d.deptype = 'e'", query)
            self.assertIn("NOT EXISTS (SELECT 1 FROM pg_depend d", query)


class AnonExecutableByDesignTests(unittest.TestCase):
    """The allowlist, and the reasons it cannot become a place to hide things.

    It exists because the guard had no answer for the PostgREST pre-request
    hook: the fix it printed (REVOKE ... FROM anon) would have taken every
    signed-out request down, so the line was unactionable and red on every
    boot. A permanently-red security check is one people stop reading, and this
    is the only control on the direct-PostgREST path.

    So the allowlist buys green — and these tests are the price: it may only
    ever shrink, every entry must say what breaks, and nothing on it disappears
    from the output.
    """

    HOOK = "willab_pre_request()"

    def test_the_allowlist_is_exactly_the_pinned_set(self):
        import rls_guard
        self.assertEqual(set(rls_guard.ANON_EXECUTABLE_BY_DESIGN), {self.HOOK})
        code, out = run_main(["--strict"], conn=FakeConn(functions=[self.HOOK]))
        self.assertEqual(code, 0)
        self.assertIn("1 anon-callable by design", out)

    def test_anything_not_on_the_list_is_still_a_finding(self):
        code, out = run_main(
            ["--strict"], conn=FakeConn(functions=[self.HOOK, "leaky(x text)"]))
        self.assertEqual(code, 1)
        self.assertIn("EXPOSURE FOUND", out)
        self.assertIn("leaky(x text)", out)
        self.assertIn("1 public function(s) anon can EXECUTE", out)


if __name__ == "__main__":
    unittest.main()
