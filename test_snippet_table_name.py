"""The snippet table name lives in ONE place.

WHY THIS TEST. The cutover in services/snippet_tables.py only works if the
name is genuinely centralised. One surviving `.table("charisma_snippets")`
literal anywhere in the source is a query that keeps pointing at the OLD name
after the rename — and PostgREST answers a missing table with a 404 that this
codebase swallows by design, so that one straggler would fail SILENTLY. The
symptom would be interview answers or Lab cuts quietly not saving, with
nothing red anywhere.

Checked with AST, not substring matching: prose in a docstring or comment
must be free to name the old table (the whole point is explaining the fossil
name), while a string literal handed to `.table(...)` must not.

That distinction is not academic here — this repo has three times written a
text-matching fence that its own explanatory comments then tripped.

Run: python3 -m unittest test_snippet_table_name
"""
from __future__ import annotations

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).parent
LEGACY = "charisma_snippets"

# Source that talks to the database at runtime. Tests are excluded on
# purpose: a test asserting the PHYSICAL name is legitimately a literal, and
# migrations are SQL, not Python.
SOURCE_DIRS = ("services", "routes", "utils", "scripts")


def _source_files():
    for d in SOURCE_DIRS:
        for py in (ROOT / d).rglob("*.py"):
            if "__pycache__" not in str(py):
                yield py


class TestTableNameIsCentralised(unittest.TestCase):
    def test_no_table_call_hardcodes_the_legacy_name(self):
        """`.table("charisma_snippets")` must not exist outside the constant."""
        offenders = []
        for py in _source_files():
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                if not (isinstance(fn, ast.Attribute) and fn.attr == "table"):
                    continue
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and arg.value == LEGACY:
                        offenders.append(f"{py.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(
            offenders, [],
            "these call sites still hardcode the legacy table name and would "
            "silently 404 after the rename — import SNIPPETS_TABLE from "
            "services.snippet_tables instead: " + ", ".join(offenders))

    def test_the_constant_declares_the_legacy_name_as_its_default(self):
        """With SNIPPETS_TABLE unset, behaviour must be exactly as before.

        The default is what makes deploying this change a no-op. If someone
        flips the default to the new name in code, the rename stops being a
        reversible config change and becomes a deploy-coupled one.
        """
        from services import snippet_tables
        self.assertEqual(snippet_tables.LEGACY_SNIPPETS_TABLE, LEGACY)

    def test_the_storage_prefix_is_not_the_table_and_must_not_be_renamed(self):
        """`charisma_snippets/` is a STORAGE BUCKET PREFIX, not the table.

        THE TRAP THIS GUARDS. Somebody doing the rename "thoroughly" — a
        project-wide find-and-replace of the string `charisma_snippets` — would
        rewrite these object keys too. Every clip already in the bucket lives
        under the old prefix, so the new key would point at nothing: silent
        404s on playback for the entire back catalogue, and no database error
        to notice, because the database was never involved.

        Storage keys are immutable history. The table name is a pointer. Only
        the pointer moves.
        """
        prefixed = set()
        for py in _source_files():
            tree = ast.parse(py.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if f"{LEGACY}/" in node.value:
                        prefixed.add(str(py.relative_to(ROOT)))
                elif isinstance(node, ast.JoinedStr):
                    for part in node.values:
                        if (isinstance(part, ast.Constant)
                                and isinstance(part.value, str)
                                and f"{LEGACY}/" in part.value):
                            prefixed.add(str(py.relative_to(ROOT)))
        self.assertTrue(
            prefixed,
            "the storage prefix 'charisma_snippets/' vanished from the "
            "source — if the rename rewrote object keys, every clip already "
            "in the bucket is now unreachable and this must be reverted")


class TestRenameMigrationsReloadTheSchemaCache(unittest.TestCase):
    """Any migration that RENAMEs a table must also reload PostgREST.

    THE INCIDENT THIS ENCODES (2026-08-10). The charisma_snippets -> snippets
    rename ran cleanly, every SQL check passed, and the application silently
    stopped writing. PostgREST answers from a CACHED schema; a rename does not
    reliably invalidate it, so it kept serving the old name and returned
    "Could not find the table 'public.snippets' in the schema cache" — which
    this codebase swallows by design. A perfect-looking migration with a dead
    app behind it.

    The same class of failure is already on the record at services/db.py:8711
    (PGRST204, 2026-05-11). Twice is a pattern, so it becomes a test.

    NOTIFY belongs INSIDE the transaction: it is delivered at COMMIT, making
    the reload atomic with the rename rather than a step someone remembers.
    """

    # Applied long ago, and left alone deliberately. `migrate.py` compares
    # applied files against a recorded checksum, so editing one reports drift
    # — a cost worth paying only when the fix still matters. It does not here:
    # this migration renamed v2_post_recording_questions_pool, a table no live
    # code path reads under either name (the live one is
    # `post_recording_questions`), and its cache reloaded on the next restart
    # years ago. The rename migration whose bug IS live-relevant — the one a
    # rebuild would re-run — carries the NOTIFY.
    _HISTORICAL = {"v2_post_recording_questions_table.sql"}

    def test_every_rename_migration_notifies_pgrst(self):
        offenders = []
        for sql_path in (ROOT / "migrations").glob("*.sql"):
            if sql_path.name in self._HISTORICAL:
                continue
            sql = sql_path.read_text(encoding="utf-8")
            code = "\n".join(line.split("--")[0] for line in sql.splitlines())
            if "RENAME TO" not in code.upper():
                continue
            if "NOTIFY" not in code.upper() or "RELOAD SCHEMA" not in code.upper():
                offenders.append(sql_path.name)
        self.assertEqual(
            offenders, [],
            "these migrations rename a table without reloading the PostgREST "
            "schema cache — the rename will appear to work while the app "
            "silently writes nothing. Add `NOTIFY pgrst, 'reload schema';` "
            "before COMMIT: " + ", ".join(offenders))


if __name__ == "__main__":
    unittest.main()
