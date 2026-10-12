"""An unfinished purge request locks a person's services only if it is account-wide.

0378 (a_project_deletion_pauses_only_its_project.sql) narrows nineteen
installed functions from "any unfinished purge of this person" to "any
unfinished ACCOUNT-WIDE purge of this person", so a one-project deletion
waiting for review cannot stop that person's other projects, or close their
delivery jobs for good.

0378 edits installed bodies, so the files before it still hold the old
predicate and that is expected. What must never happen is a LATER file that
re-issues one of those functions from source, or adds a new one, with the
old predicate: it would silently undo the narrowing. This walks every
migration after 0378 in manifest order and fails on any such body.

Run: python3 -m pytest tests/test_purge_scope_predicates.py
"""
from __future__ import annotations

from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
NARROWING = "a_project_deletion_pauses_only_its_project.sql"


def _manifest() -> list[str]:
    rows = (MIGRATIONS / "manifest.txt").read_text(encoding="utf-8").splitlines()
    return [row.split("\t")[1].strip() for row in rows if "\t" in row]


def test_0378_is_in_the_manifest():
    assert NARROWING in _manifest()
