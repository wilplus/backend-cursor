"""Every `on_conflict=` must name a NON-PARTIAL unique index.

WHY. `dimension_evaluations` stayed empty through a working pipeline because
migration 0249 created its snippet uniqueness as a PARTIAL index:

    CREATE UNIQUE INDEX uq_dimension_evaluations_snip_dim_ver
        ON dimension_evaluations (snippet_id, dimension_id, benchmark_version)
        WHERE snippet_id IS NOT NULL;

while the writer upserts with
`on_conflict="snippet_id,dimension_id,benchmark_version"`.

PostgreSQL infers a partial unique index as an ON CONFLICT arbiter ONLY when
the statement repeats the index predicate. PostgREST's `on_conflict` emits the
column list and no predicate, so every write raised 42P10 — "there is no
unique or exclusion constraint matching the ON CONFLICT specification".

The writer catches everything and returns 0, deliberately, so telemetry can
never break the scoring path it observes. That design is right, and its cost
is that a total failure is indistinguishable from "no data yet". Nothing was
red. The table was simply always empty.

**This is a schema/code contract no unit test could reach**, because it only
fails against a real PostgreSQL. So test the contract statically: pair each
`.table("x") ... on_conflict="a,b"` with the CREATE UNIQUE INDEX statements in
migrations/, and fail when the matching index carries a WHERE.

SCOPE, deliberately narrow. It asserts ONLY on a provably partial index for
the same table. A missing index is NOT reported: uniqueness is just as often
declared as a table-level UNIQUE(...) or PRIMARY KEY, which this file does not
parse, so "no index found" would be a false alarm rather than a finding.

Run: python3 -m unittest test_upsert_arbiters
"""
from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).parent
MIGRATIONS = ROOT / "migrations"

# .table("x") ... .upsert(..., on_conflict="a,b,c") — the TABLE must be
# captured with the columns. Matching on a column set alone attributes an
# upsert to whichever table happens to share those column names, which is how
# the first version of this test blamed `recording_reviews` for a write that
# actually targets `read_alignments`.
_TABLE_UPSERT = re.compile(
    r"""\.table\(\s*["'](?P<table>\w+)["']\s*\)"""
    r"""[\s\S]{0,800}?on_conflict\s*=\s*["'](?P<cols>[^"']+)["']""")

# CREATE UNIQUE INDEX [IF NOT EXISTS] name ON tbl (cols) [WHERE pred];
_UNIQUE_INDEX = re.compile(
    r"CREATE\s+UNIQUE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(?P<name>[\w.]+)\s+ON\s+(?P<table>[\w.]+)\s*"
    r"\((?P<cols>[^)]*)\)"
    r"(?P<tail>[^;]*);",
    re.IGNORECASE | re.DOTALL,
)


def _cols(raw: str) -> tuple[str, ...]:
    return tuple(c.strip().lower() for c in raw.split(",") if c.strip())


def _latest_index_state() -> dict[tuple[str, tuple[str, ...]], bool]:
    """{(table, cols): is_partial} — LAST definition in manifest order wins.

    Manifest order matters: a later migration dropping and recreating an
    index without its predicate is exactly the fix, and reading files
    alphabetically would report the superseded definition instead.
    """
    order: list[str] = []
    manifest = MIGRATIONS / "manifest.txt"
    for line in manifest.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) == 2:
            order.append(parts[1])

    state: dict[tuple[str, tuple[str, ...]], bool] = {}
    for filename in order:
        path = MIGRATIONS / filename
        if not path.exists():
            continue
        sql = path.read_text()
        for m in _UNIQUE_INDEX.finditer(sql):
            table = m.group("table").split(".")[-1].lower()
            key = (table, _cols(m.group("cols")))
            state[key] = "where" in m.group("tail").lower()
    return state


class TestUpsertArbiters(unittest.TestCase):

    def test_every_on_conflict_targets_a_non_partial_unique_index(self):
        indexes = _latest_index_state()
        problems: list[str] = []

        for path in ROOT.rglob("*.py"):
            if any(p in path.parts for p in
                   (".git", "node_modules", "venv", ".venv", "__pycache__")):
                continue
            if path.name.startswith("test_"):
                continue
            source = path.read_text()
            for m in _TABLE_UPSERT.finditer(source):
                table, raw = m.group("table").lower(), m.group("cols")
                is_partial = indexes.get((table, _cols(raw)))
                # None = no CREATE UNIQUE INDEX found for this (table, cols).
                # NOT a defect: uniqueness is just as often a table-level
                # UNIQUE(...) or PRIMARY KEY, which this file does not parse.
                # Only a PROVABLY partial index is asserted on.
                if is_partial:
                    problems.append(
                        f"{path.name}: on_conflict={raw!r} on {table} targets "
                        f"a PARTIAL unique index — PostgreSQL cannot infer it "
                        f"as an arbiter without the predicate, so every write "
                        f"raises 42P10 and, if the caller swallows "
                        f"exceptions, does so silently forever")
        self.assertEqual(problems, [], "\n".join(problems))

    def test_the_dimension_evaluations_arbiter_specifically(self):
        """The one that bit. Pinned by name so a future migration cannot
        quietly restore the predicate."""
        indexes = _latest_index_state()
        key = ("dimension_evaluations",
               ("snippet_id", "dimension_id", "benchmark_version"))
        self.assertIn(key, indexes, "the snippet-grain unique index vanished")
        self.assertFalse(
            indexes[key],
            "uq_dimension_evaluations_snip_dim_ver is partial again — it is "
            "the ON CONFLICT arbiter for record_dimension_evaluations, and a "
            "predicate makes every telemetry write fail silently")

    def test_the_recording_grain_index_may_stay_partial(self):
        """Nothing upserts on recording grain, so its predicate is fine — and
        asserting that keeps the rule 'no partial arbiters', not the much
        broader and wrong 'no partial unique indexes'."""
        indexes = _latest_index_state()
        key = ("dimension_evaluations",
               ("recording_id", "dimension_id", "benchmark_version"))
        self.assertIn(key, indexes)
        self.assertTrue(indexes[key], "expected the recording-grain index to "
                                      "keep its predicate")


if __name__ == "__main__":
    unittest.main()
