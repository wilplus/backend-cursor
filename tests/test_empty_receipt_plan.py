"""The empty-receipt wipe (0379) reaches every table whose words it lists.

`purge_lineage_erasable_columns_v1` names what may be erased per table; the
wipe loop in `tombstone_phase1_purge_lineage_v1` names how each table is
reached. A table listed in the first but missing from the second keeps its
words after an erasure. A table reached on its own must carry the
`project_id` and `owner_principal_id` the frozen scope reads, or the loop
skips it silently; one without them must follow a parent that has them.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIPE = (ROOT / "migrations" / "a_take_keeps_an_empty_receipt.sql").read_text()


def _erasable() -> set[str]:
    body = WIPE.split("purge_lineage_erasable_columns_v1(", 1)[1].split("$$;", 1)[0]
    return set(re.findall(r"WHEN '(\w+)' THEN", body))


def _plan() -> dict[str, str | None]:
    body = WIPE.split("AS plan(plan_relation", 1)[0].rsplit("FROM (VALUES", 1)[1]
    return {
        rel: (None if parent == "NULL" else parent.strip("'"))
        for rel, parent in re.findall(r"\('(\w+)', ('\w+'|NULL),", body)
    }


def _columns(table: str) -> set[str]:
    found: set[str] = set()
    for path in (ROOT / "migrations").glob("*.sql"):
        text = path.read_text()
        match = re.search(
            rf"CREATE TABLE IF NOT EXISTS (?:public\.)?{table} \((.*?)\n\);",
            text, re.S)
        if match:
            found |= set(re.findall(r"^\s+(\w+)\s", match.group(1), re.M))
        found |= set(re.findall(
            rf"ALTER TABLE (?:public\.)?{table}\s+ADD COLUMN IF NOT EXISTS (\w+)",
            text))
    return found


def test_every_listed_table_is_reached():
    assert _erasable() == set(_plan())


def test_a_table_reached_on_its_own_carries_the_scope_columns():
    for rel, parent in _plan().items():
        scoped = parent or rel
        assert {"project_id", "owner_principal_id"} <= _columns(scoped), rel
