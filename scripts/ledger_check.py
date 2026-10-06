#!/usr/bin/env python3
"""Ledger checker (audit row X1, founder decision H1 = A).

Enforces the rules of docs/audit/WORKFLOW.md on docs/audit/LEDGER.md:

  * row IDs are unique, across every table in the file;
  * the status is one of OPEN, VERIFYING, CONFIRMED, FALSE, DUPLICATE,
    FOUNDER, PARKED, IN-PR, DONE (an optional "(reason)" and a trailing
    "· QUESTION: ..." may follow the word);
  * no row present in the base text is missing (rows are never deleted);
  * on 12-cell rows, IN-PR and DONE need a PR cell, DONE needs a Test cell;
  * FOUNDER and PARKED need a reason in parentheses.

Every error string names its row ID. Header lines, separator lines and
lines whose first cell starts with "V4 " (the coverage table) are not rows.

    python scripts/ledger_check.py [--base <git-ref>]

Reads docs/audit/LEDGER.md; with --base it also reads the file at that ref
(git show) and fails if a row was deleted. Prints the errors, exits 1 if any.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

LEDGER_REL = "docs/audit/LEDGER.md"
STATUS_WORDS = (
    "OPEN", "VERIFYING", "CONFIRMED", "FALSE", "DUPLICATE",
    "FOUNDER", "PARKED", "IN-PR", "DONE",
)
_STATUS_RE = re.compile(r"^(" + "|".join(STATUS_WORDS) + r")(?=$|[\s(])")
_REASON_RE = re.compile(r"^\s*\(\s*[^\s)]")
_EMPTY_CELLS = {"", "—", "-", "–"}
_FULL_ROW_CELLS = 12
_PR_CELL, _TEST_CELL = 9, 10


def _is_separator(line: str) -> bool:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return line.strip().startswith("|") and all(re.fullmatch(r":?-{3,}:?", c) for c in cells)


def _rows(text: str) -> list[tuple[str, list[str]]]:
    """(row id, cells) for every ledger row in text."""
    out: list[tuple[str, list[str]]] = []
    lines = [ln.strip() for ln in text.splitlines()]
    for i, line in enumerate(lines):
        if not line.startswith("|") or _is_separator(line):
            continue
        if i + 1 < len(lines) and _is_separator(lines[i + 1]):
            continue  # a table header, whatever its first column is called
        cells = [c.strip() for c in line.strip("|").split("|")]
        first = cells[0]
        if not first or first.startswith("V4 "):
            continue
        out.append((first, cells))
    return out


def _row_errors(row_id: str, cells: list[str]) -> list[str]:
    status = cells[-1]
    m = _STATUS_RE.match(status)
    if not m:
        return [f"{row_id}: status {status!r} is not one of {', '.join(STATUS_WORDS)}"]
    word, rest = m.group(1), status[m.end():]
    errs: list[str] = []
    if word in ("FOUNDER", "PARKED") and not _REASON_RE.match(rest):
        errs.append(f"{row_id}: {word} needs a reason in parentheses, e.g. {word} (why)")
    if len(cells) == _FULL_ROW_CELLS:
        if word in ("IN-PR", "DONE") and cells[_PR_CELL] in _EMPTY_CELLS:
            errs.append(f"{row_id}: {word} needs a PR cell")
        if word == "DONE" and cells[_TEST_CELL] in _EMPTY_CELLS:
            errs.append(f"{row_id}: DONE needs a Test cell")
    return errs


def check(ledger_text: str, base_text: str | None = None) -> list[str]:
    """Return the list of rule violations; an empty list means valid."""
    rows = _rows(ledger_text)
    errors: list[str] = []
    seen: set[str] = set()
    reported: set[str] = set()
    for row_id, cells in rows:
        if row_id in seen:
            if row_id not in reported:
                errors.append(f"{row_id}: duplicate row ID")
                reported.add(row_id)
        seen.add(row_id)
        errors.extend(_row_errors(row_id, cells))
    if base_text is not None:
        for row_id in dict.fromkeys(rid for rid, _ in _rows(base_text)):
            if row_id not in seen:
                errors.append(f"{row_id}: row deleted (rows are never deleted)")
    return errors


def _git_show(root: Path, ref: str) -> str | None:
    """The ledger at ref, or None when the file does not exist there yet."""
    ok = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        cwd=root, capture_output=True, text=True,
    )
    if ok.returncode != 0:
        raise SystemExit(f"ledger_check: unknown git ref {ref!r} (fetch it first)")
    shown = subprocess.run(
        ["git", "show", f"{ref}:{LEDGER_REL}"],
        cwd=root, capture_output=True, text=True, encoding="utf-8",
    )
    return shown.stdout if shown.returncode == 0 else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", metavar="GIT_REF", help="also fail if a row present at this ref is gone")
    args = ap.parse_args(argv)
    root = Path(__file__).resolve().parent.parent
    path = root / LEDGER_REL
    if not path.is_file():
        print(f"ledger_check: {LEDGER_REL} not found", file=sys.stderr)
        return 1
    base = _git_show(root, args.base) if args.base else None
    errors = check(path.read_text(encoding="utf-8"), base)
    for err in errors:
        print(err)
    if errors:
        print(f"ledger_check: {len(errors)} error(s)", file=sys.stderr)
        return 1
    print("ledger_check: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
