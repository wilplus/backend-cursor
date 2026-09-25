"""Every purge-registry selector names a column its table really has.

THE BUG THIS EXISTS TO PREVENT (found 2026-09-26). Ten registry entries
selected rows by a column no migration creates: `voice_album.user_id`
(the table has only arc_id and snippet_id), `owner_voice_album_routing.user_id`
(the column is owner_user_id), `take_feedback_exposure.session_id` (it is
take_session_id), and seven more. The inventory reads each dependency, a
missing column raises, the target becomes DEPENDENCY_INVENTORY_FAILED, and
because resolve_targets is all-or-nothing the whole account deletion stops.
Nothing looked wrong until someone tried to delete an account.

So this reads every CREATE TABLE and ALTER TABLE in migrations/ and requires
each dependency's selector column to appear in its table's definition.

LEGACY_TABLES are tables created before migrations/ existed (their CREATE is
not in this repo), so their columns cannot be checked here. The set may only
shrink: a new entry means a new table nobody can verify.

Run: python3 -m pytest tests/test_purge_registry_selectors_exist.py
"""
from __future__ import annotations

import re
import sys
import types
from pathlib import Path

for _m in ("supabase", "sentry_sdk"):
    if _m not in sys.modules:
        sys.modules[_m] = types.ModuleType(_m)
if not hasattr(sys.modules["supabase"], "create_client"):
    sys.modules["supabase"].create_client = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["supabase"].Client = object  # type: ignore[attr-defined]

from services.data_purge_registry import DEPENDENCIES  # noqa: E402

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"

#: Tables whose CREATE predates migrations/. Frozen 2026-09-26. Down only.
LEGACY_TABLES = {
    "few_shot_retrievals", "post_recording_answers", "tasks",
    "snippets", "recordings", "recording_sessions", "performance_scores",
    "pre_recording_answers",
}


def _sql() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(MIGRATIONS.rglob("*.sql"))
    )


def _definitions(sql: str, relation: str) -> list[str]:
    name = r'(?:public\.)?"?%s"?' % re.escape(relation)
    found = []
    for match in re.finditer(
            r"CREATE TABLE(?: IF NOT EXISTS)?\s+%s\s*\(" % name, sql, re.I):
        depth, start = 0, match.end() - 1
        for index in range(start, len(sql)):
            if sql[index] == "(":
                depth += 1
            elif sql[index] == ")":
                depth -= 1
                if depth == 0:
                    found.append(sql[start:index])
                    break
    for match in re.finditer(
            r"ALTER TABLE(?: IF EXISTS)?(?: ONLY)?\s+%s\b[^;]*;" % name,
            sql, re.I):
        found.append(match.group(0))
    return found


def test_every_selector_column_exists_in_its_table():
    sql = _sql()
    missing = []
    for dependency in DEPENDENCIES:
        if dependency.relation in LEGACY_TABLES:
            continue
        definitions = _definitions(sql, dependency.relation)
        assert definitions, (
            f"{dependency.code}: no CREATE TABLE {dependency.relation} in "
            "migrations/. Define it, or (only for a pre-migrations table) "
            "add it to LEGACY_TABLES with a reason."
        )
        column = re.compile(r"\b%s\b" % re.escape(dependency.selector_column))
        if not any(column.search(text) for text in definitions):
            missing.append(
                f"{dependency.code}: {dependency.relation}."
                f"{dependency.selector_column}")
    assert not missing, (
        "registry selectors that name a column the table does not have:\n  "
        + "\n  ".join(missing))


def test_the_legacy_list_only_names_tables_still_undefined():
    """Once a legacy table gains a CREATE in migrations/, it must leave the
    list and be checked like every other table."""
    sql = _sql()
    defined = {t for t in LEGACY_TABLES
               if any(d.startswith("(") for d in _definitions(sql, t))}
    assert not defined, f"now defined in migrations/: {sorted(defined)}"
