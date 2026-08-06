"""What the writer produces must fit the column it is written to.

WHY. `n_units` was typed INTEGER. `_denominator_count` returns MINUTES for a
temporal rate, and a 6.55-second snippet is 0.109 of a minute. PostgREST casts
JSON through text, so the write became `'0.109'::integer` — a hard error, not
a rounding. A PostgREST insert is ONE statement per batch, so one `fillers`
row took every row of that recording with it, and the writer's deliberate
catch-and-return-0 turned a total failure into an empty table.

This is the second defect of the same shape in one day (the first: a partial
unique index used as an ON CONFLICT arbiter, see test_upsert_arbiters). Both
were invisible for the same reason — telemetry that must never break the
scoring path it observes cannot also be loud when it breaks itself. The
compensating control is a static check on the schema/code contract, because
nothing at runtime will ever complain.

Run: python3 -m unittest test_schema_column_types
"""
from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).parent
MIGRATIONS = ROOT / "migrations"


def _denominator_count():
    """The real function, lifted out of its module by AST.

    services.session_metrics imports services.db and therefore the supabase
    client, which this pure-unit suite must not require — the same reason
    test_dimension_registry reads that file's source instead of importing it.
    Executing just this one function keeps the assertion about the REAL code
    rather than a copy that can drift.
    """
    import ast
    src = (ROOT / "services" / "session_metrics.py").read_text()
    tree = ast.parse(src)
    node = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef)
                and n.name == "_denominator_count")
    ns: dict = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<lifted>", "exec"),
         ns)
    return ns["_denominator_count"]


_INT_TYPES = ("integer", "int", "int4", "int8", "bigint", "smallint")


def _column_type(table: str, column: str) -> str | None:
    """The column's type as last declared, in manifest order.

    Manifest order matters: an ALTER ... TYPE in a later migration is exactly
    how this gets fixed, and reading files alphabetically would report the
    superseded declaration.
    """
    found: str | None = None
    manifest = (MIGRATIONS / "manifest.txt").read_text().splitlines()
    for line in manifest:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        path = MIGRATIONS / parts[1]
        if not path.exists():
            continue
        sql = path.read_text()

        # CREATE TABLE ... ( ... n_units  INTEGER  NULL, ... )
        for m in re.finditer(
                rf"CREATE\s+TABLE[^;]*?\b{table}\b\s*\((?P<body>[^;]*?)\);",
                sql, re.IGNORECASE | re.DOTALL):
            for row in m.group("body").split("\n"):
                row = row.split("--")[0].strip()
                if re.match(rf"^{column}\s+", row, re.IGNORECASE):
                    found = row.split()[1].lower().rstrip(",")

        # ALTER TABLE ... ALTER COLUMN n_units TYPE DOUBLE PRECISION
        for m in re.finditer(
                rf"ALTER\s+COLUMN\s+{column}\s+TYPE\s+(?P<type>[A-Za-z ]+)",
                sql, re.IGNORECASE):
            found = " ".join(m.group("type").split()).lower()
    return found


class TestNUnitsHoldsAFraction(unittest.TestCase):

    def test_the_writer_can_produce_a_fraction(self):
        """Pins the input side. If _denominator_count ever stops returning
        minutes, the column requirement below can be revisited."""
        value = _denominator_count()("minutes", seconds=6.55, words=14)
        self.assertIsInstance(value, float)
        self.assertLess(value, 1.0, "a 6.55 s snippet is a fraction of a minute")

    def test_the_column_is_not_an_integer_type(self):
        """The contract. An INTEGER column here does not round 0.109 down —
        PostgREST casts through text and `'0.109'::integer` raises, taking the
        whole batch with it."""
        declared = _column_type("dimension_evaluations", "n_units")
        self.assertIsNotNone(declared, "n_units is not declared in migrations/")
        self.assertNotIn(
            declared, _INT_TYPES,
            f"n_units is {declared!r}, but _denominator_count returns "
            f"fractional minutes — every write carrying a rate will fail, and "
            f"record_dimension_evaluations swallows it, so the table just "
            f"stays empty")

    def test_the_words_denominator_stays_whole(self):
        """The other half: a lexical rate denominates in WORDS, which are
        whole. Widening the column must not be read as license to store a
        fractional word count."""
        self.assertEqual(
            _denominator_count()("words", seconds=6.55, words=14), 14)

    def test_an_unknown_denominator_writes_nothing(self):
        """A wrong denominator is worse than an absent one — it is silently
        wrong rather than visibly missing (F.3)."""
        fn = _denominator_count()
        self.assertIsNone(fn("furlongs", seconds=6.55, words=14))
        self.assertIsNone(fn(None, seconds=6.55, words=14))


if __name__ == "__main__":
    unittest.main()
