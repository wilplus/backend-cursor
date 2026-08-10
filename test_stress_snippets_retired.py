"""`stress_snippets` is retired in place — no writer, no reader.

Founder decision 2026-08-10. The rows stay (human-generated coach labels
that cannot be re-derived, since both the clip generator and the model that
ranked it were deleted). What must not come back is CODE that touches them.

WHY A TEST AND NOT A DATABASE CONSTRAINT. A trigger raising on INSERT would
be a live failure mode on a table nobody touches — it can only ever fire in
production, at the worst moment, on a path that was probably a mistake but
might have been deliberate. A test fails in CI instead, before the write
exists, and tells the author what the alternative is: if the lane is revived,
mint a NEW table rather than mixing fresh rows into a frozen corpus — the
same rule detector_version applies to a changed definition.

SCOPED TO RUNTIME CODE. `scripts/cleanup_corrupt_stress_snippets.py` is a
hand-run maintenance tool, not a runtime path, and it is exempt: the whole
point of keeping the rows is that a human can still operate on them.

Checked with AST, not substring matching — prose must stay free to name the
table, since explaining the retirement is the point. This repo has three
times shipped a text-matching fence that its own comments then tripped.

Run: python3 -m unittest test_stress_snippets_retired
"""
from __future__ import annotations

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).parent
TABLE = "stress_snippets"

# Runtime code only. scripts/ is hand-run tooling — see the module docstring.
RUNTIME_DIRS = ("services", "routes", "utils")


def _runtime_files():
    for d in RUNTIME_DIRS:
        for py in (ROOT / d).rglob("*.py"):
            if "__pycache__" not in str(py):
                yield py


class TestNoRuntimeCodeTouchesStressSnippets(unittest.TestCase):
    def test_no_table_call_targets_the_retired_table(self):
        """`.table("stress_snippets")` must not appear in runtime code."""
        offenders = []
        for py in _runtime_files():
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                if not (isinstance(fn, ast.Attribute) and fn.attr == "table"):
                    continue
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and arg.value == TABLE:
                        offenders.append(f"{py.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(
            offenders, [],
            "stress_snippets is retired in place — these call sites bring it "
            "back to life. If the lane is being revived, mint a NEW table "
            "rather than mixing fresh rows into a frozen corpus: "
            + ", ".join(offenders))

    def test_the_deleted_accessors_have_not_returned(self):
        """The named db accessors are gone and must stay gone.

        Listed individually rather than by prefix so that reviving one is a
        deliberate act with a visible diff, not something a wildcard quietly
        permits.
        """
        gone = ("v2_get_stress_snippet", "v2_insert_stress_snippets",
                "v2_delete_stress_snippets_for_recording",
                "v2_set_stress_snippet_label", "v2_clear_stress_snippet_label",
                "v2_merge_stress_snippet_features", "v2_list_stress_snippets",
                "set_stress_snippet_ai_draft_notes",
                "generate_stress_draft_for_snippet")
        found = []
        for py in _runtime_files():
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and node.name in gone:
                    found.append(f"{py.relative_to(ROOT)}:{node.name}")
        self.assertEqual(found, [], f"retired accessors are back: {found}")

    def test_the_retirement_migration_drops_nothing(self):
        """The migration must be a COMMENT and nothing else.

        The entire value of "retired in place" is that the data survives. A
        DROP or DELETE reaching this file would read as routine cleanup in a
        diff while being the one irreversible act the decision forbade.
        """
        sql = (ROOT / "migrations" / "retire_stress_snippets.sql").read_text(
            encoding="utf-8")
        # Strip SQL comments — the prose deliberately says "NO DROP".
        code = "\n".join(
            line.split("--")[0] for line in sql.splitlines()).upper()
        for forbidden in ("DROP TABLE", "DELETE FROM", "TRUNCATE",
                          "DROP COLUMN"):
            self.assertNotIn(forbidden, code,
                             f"{forbidden} in the retirement migration — "
                             f"retirement keeps the rows, by decision")


if __name__ == "__main__":
    unittest.main()
