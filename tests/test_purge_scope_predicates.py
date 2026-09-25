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

import re
from pathlib import Path

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
NARROWING = "a_project_deletion_pauses_only_its_project.sql"
MARKER = "/* 0378: account-wide purges only */"

_FUNCTION = re.compile(
    r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+(?:public\.)?(\w+)\s*\(", re.I)
_BODY_TAG = re.compile(r"\bAS\s+(\$\w*\$)", re.I)
_OPEN_PURGE = re.compile(
    r"data_purge_requests\s+(\w+)\s+WHERE[^;]*?\b\1\.state\s*<>\s*'done'",
    re.I | re.S)


def _manifest() -> list[str]:
    rows = (MIGRATIONS / "manifest.txt").read_text(encoding="utf-8").splitlines()
    return [row.split("\t")[1].strip() for row in rows if "\t" in row]


def _bodies(sql: str):
    for match in _FUNCTION.finditer(sql):
        tag = _BODY_TAG.search(sql, match.end())
        if not tag:
            continue
        end = sql.find(tag.group(1), tag.end())
        yield match.group(1), sql[tag.end():end if end >= 0 else len(sql)]


def _unnarrowed(body: str) -> list[str]:
    bad = []
    for match in _OPEN_PURGE.finditer(body):
        tail = body[match.end():match.end() + 120]
        if f"{match.group(1)}.project_id IS NULL" not in tail:
            bad.append(match.group(0)[:80])
    return bad


def test_0378_is_in_the_manifest():
    assert NARROWING in _manifest()


def test_no_later_migration_brings_the_account_wide_lock_back():
    files = _manifest()
    offenders = []
    for name in files[files.index(NARROWING) + 1:]:
        sql = (MIGRATIONS / name).read_text(encoding="utf-8")
        for function, body in _bodies(sql):
            for hit in _unnarrowed(body):
                offenders.append(f"{name}: {function}: {hit}")
    assert not offenders, (
        "an unfinished purge must lock only on account-wide requests; add "
        f"`AND <alias>.project_id IS NULL {MARKER}` after:\n  "
        + "\n  ".join(offenders))


def test_the_check_recognises_both_shapes():
    old = ("SELECT 1 FROM public.data_purge_requests purge WHERE "
           "purge.acquisition_principal_id = x AND purge.state <> 'done'")
    assert _unnarrowed(old)
    assert not _unnarrowed(old + f" AND purge.project_id IS NULL {MARKER}")
