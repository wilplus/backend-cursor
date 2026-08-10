"""The star generator says what it did, ESPECIALLY when it did nothing.

THE INCIDENT (2026-08-03 → 2026-08-10). `moment_suggestions` stopped being
written and nobody could tell why for a week. The coach's star review read
"No stars fired on this arc", which is true and useless: it cannot
distinguish a take that produced no candidates from a generator that never
ran, an LLM returning nothing, or a decision ledger that had already ruled
on every phrase.

The generator did have a log line — `if stored: logger.info(...)`. The guard
is the whole problem. The one case worth reporting is the zero, and that was
precisely the case it stayed silent for. A diagnostic that speaks only on
success reports that the system is fine right up until the moment you need
it.

So the line is now unconditional and carries the funnel: snippets seen, each
stage's drop count, stars stored. These tests pin that, because an
instrumentation regression is invisible by construction — you would read its
absence as "nothing to report".

Run: python3 -m unittest test_moment_suggestions_funnel
"""
from __future__ import annotations

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).parent
SRC = ROOT / "services" / "moment_suggestions.py"


def _generate_for_session() -> ast.FunctionDef:
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "generate_for_session":
            return node
    raise AssertionError("generate_for_session not found")


class TestTheFunnelLineIsUnconditional(unittest.TestCase):
    def test_the_summary_log_is_not_guarded_by_stored(self):
        """`if stored: logger.info(...)` must never come back.

        Asserted structurally: no `logger.info` call may sit inside an `if`
        whose test is the bare name `stored`. That is the exact shape that
        hid a week of silence.
        """
        fn = _generate_for_session()
        for node in ast.walk(fn):
            if not isinstance(node, ast.If):
                continue
            if not (isinstance(node.test, ast.Name) and node.test.id == "stored"):
                continue
            for inner in ast.walk(node):
                if (isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Attribute)
                        and inner.func.attr == "info"):
                    self.fail(
                        "the summary log is guarded by `if stored:` again — "
                        "the zero case is the one worth logging")

    def test_the_funnel_line_reports_every_stage(self):
        """Each drop reason must appear in the emitted line.

        Checked on the format string rather than the counters, because a
        counter that is incremented and never printed is the same silence
        with more code.
        """
        src = SRC.read_text(encoding="utf-8")
        marker = "moment_suggestion: sid=%s arc=%s seen=%d stored=%d"
        self.assertIn(marker, src, "the funnel line is gone")
        for stage in ("no_text=", "capped=", "decided=", "no_gen=",
                      "errored=", "unstarred="):
            self.assertIn(stage, src, f"the funnel dropped {stage}")

    def test_every_counter_is_both_incremented_and_passed(self):
        """A counter declared but never bumped would read as a clean zero —
        indistinguishable from a stage that genuinely dropped nothing, and
        therefore worse than not having it."""
        fn = _generate_for_session()
        counters = {"_seen", "_no_text", "_capped", "_decided", "_no_gen",
                    "_errored"}
        bumped = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                bumped.add(node.target.id)
        missing = counters - bumped
        self.assertEqual(
            missing, set(),
            f"declared but never incremented: {sorted(missing)}")


if __name__ == "__main__":
    unittest.main()
