"""Wiring tests — a service with no caller is a service that does not run.

WHY THIS FILE EXISTS. `compute_session_global_metrics` sat with zero callers
from 2026-06-06 to 2026-08-06. Commit 0d74f12 removed the old-admin
`POST /admin/sessions/<id>/compute-metrics` route as "FE-orphaned"; that route
was the only caller. The route went, the service stayed, nothing replaced it,
and for two months `global_wpm` and every sibling global were never written —
while four live readers went on reading them and getting NULL.

Nothing failed. No test went red, no error was logged, no alert fired. The
functions were correct, tested, and unreachable. That is the failure mode this
file exists to make loud: **unit tests prove a function works, never that
anything calls it.**

It also caught a second-order version of the same thing — the drift telemetry
added in #346 was wired correctly into a function that had not run since June,
which is why `dimension_evaluations` was empty.

Uses `ast` rather than a text scan on purpose: this repo's docstrings mention
these function names constantly, so grep-shaped detection would pass on prose
and prove nothing.

Run: python3 -m unittest test_session_globals_wiring
"""
from __future__ import annotations

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).parent
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__",
             "migrations", "docs", "scripts"}


def _python_files():
    for path in ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name.startswith("test_"):
            continue
        yield path


def _callers_of(function_name: str) -> set[str]:
    """Files containing a REAL invocation — an ast.Call, not a mention.

    Excludes the defining module itself: a function calling itself, or a
    sibling in the same file calling it, does not make the module reachable
    from anywhere.
    """
    found: set[str] = set()
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        defines = any(isinstance(n, ast.FunctionDef) and n.name == function_name
                      for n in ast.walk(tree))
        if defines:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (func.id if isinstance(func, ast.Name)
                    else func.attr if isinstance(func, ast.Attribute) else None)
            if name == function_name:
                found.add(str(path.relative_to(ROOT)))
    return found


class TestSessionGlobalsAreReachable(unittest.TestCase):

    def test_compute_session_global_metrics_has_a_caller(self):
        """The bare version of the June defect."""
        callers = _callers_of("compute_session_global_metrics")
        self.assertTrue(
            callers,
            "compute_session_global_metrics has NO caller — it is the only "
            "writer of global_wpm/global_fillers/global_pause_ms/"
            "global_dynamic_db/global_pitch_center/global_energy, so every "
            "reader of those is now getting NULL, silently. This is exactly "
            "how it broke on 2026-06-06 (commit 0d74f12).")

    def test_the_caller_is_on_the_LIVE_recording_pipeline(self):
        """THE TEST THAT WOULD ACTUALLY HAVE CAUGHT IT.

        "Has a caller" was TRUE right up until the excision — the caller was
        an admin route that was itself orphaned. A caller that nothing reaches
        is not reachability, so the assertion has to name the live path: the
        analysis worker, which runs on every recording.
        """
        callers = _callers_of("compute_session_global_metrics")
        self.assertIn(
            "services/analysis_worker.py", callers,
            "the session globals are not computed on the recording pipeline. "
            "A caller elsewhere is not enough — the previous one was an admin "
            "route that was itself dead, which is how this went unnoticed for "
            "two months.")

    def test_the_globals_writer_is_reachable_from_it(self):
        """The next link: computing the globals and never persisting them
        would leave the readers on NULL just the same."""
        self.assertIn("services/session_metrics.py",
                      _callers_of("update_session_global_metrics"))

    def test_the_drift_telemetry_is_reachable_from_it(self):
        """`dimension_evaluations` was empty because the telemetry was wired
        into a function that had not run since June. The telemetry's own
        reachability is therefore this chain's, not its own."""
        source = (ROOT / "services" / "session_metrics.py").read_text()
        tree = ast.parse(source)
        target = next((n for n in ast.walk(tree)
                       if isinstance(n, ast.FunctionDef)
                       and n.name == "compute_session_global_metrics"), None)
        self.assertIsNotNone(target, "the entry point vanished")
        called = {n.func.id for n in ast.walk(target)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("_emit_drift_telemetry", called)

    def test_the_readers_still_exist(self):
        """The inverse check. If every reader of the globals disappears, the
        whole chain above is dead weight and should be deleted rather than
        maintained — this failing is a prompt to decide which."""
        readers = [p for p in (ROOT / "routes").rglob("*.py")
                   if "global_wpm" in p.read_text()]
        self.assertTrue(readers, "nothing reads the session globals any more")


if __name__ == "__main__":
    unittest.main()
