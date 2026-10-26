#!/usr/bin/env python3
"""The docs guard: every part of the code has one home doc, and a new doc
needs the founder (founder, 2026-10-21, N107).

WHY. By 21 October 2026 the two repos held 423 Markdown files, because every
piece of work started a file of its own: a handoff, a design, an audit, a
prompt. N107 cut them to 246 and said a new doc is not started. This is the
check that keeps that true.

Four checks. The first three are against README.md (the master doc, N106):

  * Every part of the code has a home doc. The table under "Home docs for the
    code" names code by folder or file pattern, and its home doc ("No page"
    when the code and its comments describe it). Every tracked file outside
    the docs, the legal pack and the tests must match a row. A row whose
    patterns match nothing is refused, so the table can't go stale, and so
    is a home doc that is missing or labelled History or Archive.
  * Every doc is listed. Every .md file in the repo is linked from README.md
    (prompts read at run time, under services/prompts/, are code).
  * A new doc needs the founder. A .md file that is not on the base
    (origin/main) must be linked from a README.md line that carries
    `Founder-Approved: <where and when the founder said yes>`.

The fourth is the decisions log itself (docs audit, 2026-10-26; N95 says
nothing is in force until it is written there):

  * Every entry's number is unique, and an entry is never written below a
    higher one (the two that were, N90 and N166, are named in KNOWN_LATE).
  * Every N-number a rules page cites is an entry. A rules page is CLAUDE.md,
    README.md, or a doc labelled In force. N78 and N91 were cited but never
    written (KNOWN_UNLOGGED); the log's header says so.
  * From N183 on, an entry says where it landed: "The rules:" naming the
    page, or "No rules page" when nothing else changes.

Pattern rules: a pattern ending in "/" covers its whole folder; "*" matches
within one path segment; anything else is one exact file. When several rows
match a file, the most exact pattern wins (an exact path, then the longest
pattern without its "*"). Two equally exact patterns with different homes
are refused.

    python scripts/doc_guard.py                    # in CI and scripts/local_ci.sh
    python scripts/doc_guard.py --base origin/main
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MASTER = "README.md"
START, END = "<!-- code-homes:start -->", "<!-- code-homes:end -->"
NO_PAGE = "No page"
APPROVED = "Founder-Approved:"
#: Not docs: prompts the app reads at run time.
NOT_DOCS = ("services/prompts/",)
#: Not code: the docs, the legal pack, the tests and the repo's own settings.
NOT_CODE = ("docs/", "legal/", "tests/", ".")
OTHER_REPO = "https://github.com/wilplus/frontend-cursor/blob/main/"
LINK = re.compile(r"\]\(([^)\s]+)\)")
LOG = "docs/SPEC-DECISIONS-LOG.md"
ENTRY = re.compile(r"^\*\*N(\d+) ·", re.M)
CITE = re.compile(r"(?<![A-Za-z0-9_\-./#])N(\d{1,3})(?!\d)")
IN_FORCE = "**Label: In force**"
#: Cited but never written as entries; the log's header lists them.
KNOWN_UNLOGGED = {78, 91}
#: Written after a higher number; the log's header lists them.
KNOWN_LATE = {90, 166}
#: From this entry on, an entry names the rules page it landed on.
LANDED_FROM = 183
LANDED = re.compile(r"The rules:|Rules and words:|No rules page")
UNEDITED = re.compile(r"\*\*Label: (History|Archive)\*\*")


@dataclass
class Row:
    part: str
    patterns: list[str]
    home: str | None  # None is "No page"


def parse_homes(readme: str) -> list[Row]:
    """The rows of the home-doc table between the two markers."""
    if START not in readme or END not in readme:
        return []
    table = readme.split(START, 1)[1].split(END, 1)[0]
    rows = []
    for line in table.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 3 or set(cells[0]) <= set("-: ") or cells[1] == "Files":
            continue
        patterns = re.findall(r"`([^`]+)`", cells[1])
        link = LINK.search(cells[2])
        home = None if NO_PAGE in cells[2] else (link.group(1) if link else cells[2])
        rows.append(Row(cells[0], patterns, home))
    return rows


def matches(pattern: str, path: str) -> bool:
    if pattern.endswith("/"):
        return path.startswith(pattern)
    return re.fullmatch(re.escape(pattern).replace(r"\*", "[^/]*"), path) is not None


def exactness(pattern: str) -> tuple[int, int]:
    exact = "*" not in pattern and not pattern.endswith("/")
    return (1 if exact else 0, len(pattern.replace("*", "")))


def is_code(path: str) -> bool:
    return not path.endswith(".md") and not path.startswith(NOT_CODE) and path != "conftest.py"


def home_of(path: str, rows: list[Row]) -> tuple[list[Row], list[str]]:
    """The rows that win for a file, and their winning patterns."""
    hits = [(exactness(p), r, p) for r in rows for p in r.patterns if matches(p, path)]
    if not hits:
        return [], []
    best = max(h[0] for h in hits)
    top = [h for h in hits if h[0] == best]
    return [h[1] for h in top], [h[2] for h in top]


def check_homes(files: list[str], rows: list[Row], root: Path) -> list[str]:
    problems = []
    if not rows:
        return [f"{MASTER} has no home-doc table between {START} and {END}."]
    for f in (f for f in files if is_code(f)):
        winners, patterns = home_of(f, rows)
        if not winners:
            problems.append(f"{f} has no home doc. Add it to a row of the table in {MASTER}, or add a row.")
        elif len({r.home for r in winners}) > 1:
            problems.append(f"{f} is claimed equally by {', '.join(patterns)}, with different home docs.")
    for r in rows:
        for p in r.patterns:
            if not any(matches(p, f) for f in files):
                problems.append(f"the pattern {p} ({r.part}) matches no file. Remove it, or fix it after a rename.")
        if r.home is None or r.home.startswith(OTHER_REPO):
            continue
        doc = root / r.home.split("#")[0]
        if not doc.is_file():
            problems.append(f"the home doc {r.home} ({r.part}) does not exist.")
        elif UNEDITED.search(doc.read_text(encoding="utf-8")[:2000]):
            problems.append(f"the home doc {r.home} ({r.part}) is History or Archive, which is not edited. Pick a doc that is.")
    return problems


def links_in(readme: str) -> set[str]:
    return {m.split("#")[0] for m in LINK.findall(readme)}


def is_doc(path: str) -> bool:
    return path.endswith(".md") and not path.startswith(NOT_DOCS)


def check_listed(files: list[str], readme: str) -> list[str]:
    listed = links_in(readme)
    return [f"{f} is not listed in {MASTER}. Every doc has a line there with its label (N106)."
            for f in files if is_doc(f) and f != MASTER and f not in listed]


def check_new(added: list[str], readme: str) -> list[str]:
    problems = []
    for f in (f for f in added if is_doc(f)):
        lines = [line for line in readme.splitlines() if f in links_in(line)]
        approved = [line for line in lines if re.search(re.escape(APPROVED) + r"\s*\S", line)]
        if not approved:
            problems.append(f"{f} is a new doc. N107: a new doc needs the founder's OK. Its line in {MASTER} "
                            f"must say \"{APPROVED} <where and when the founder said yes>\", or edit the "
                            "code's home doc instead.")
    return problems


def entries(log: str) -> list[tuple[int, str]]:
    """The log's entries in file order: (number, text up to the next entry)."""
    marks = list(ENTRY.finditer(log))
    return [(int(m.group(1)), log[m.start():(marks[i + 1].start() if i + 1 < len(marks) else len(log))])
            for i, m in enumerate(marks)]


def check_log(log: str, pages: dict[str, str]) -> list[str]:
    """The decisions log's numbers and the N-numbers the rules pages cite."""
    problems, seen, top = [], set(), 0
    for n, text in entries(log):
        if n in seen:
            problems.append(f"{LOG} has two entries numbered N{n}. Give the newer one the next free number.")
        elif n < top and n not in KNOWN_LATE:
            problems.append(f"{LOG}: N{n} is written after N{top}. Entries go newest last; use the next free number.")
        if n >= LANDED_FROM and not LANDED.search(text):
            problems.append(f"{LOG}: N{n} doesn't say where it landed. End it with \"The rules:\" and the page, or \"No rules page\".")
        seen.add(n)
        top = max(top, n)
    for path, text in pages.items():
        missing = sorted({int(k) for k in CITE.findall(text)} - seen - KNOWN_UNLOGGED)
        if missing:
            problems.append(f"{path} cites {', '.join(f'N{k}' for k in missing)}, which {LOG} doesn't have. "
                            "Log the decision first (N95), or fix the number.")
    return problems


def rules_pages(files: list[str], root: Path) -> dict[str, str]:
    """CLAUDE.md, README.md and every doc labelled In force."""
    pages = {}
    for f in files:
        if not f.endswith(".md") or f.startswith(NOT_DOCS) or f.startswith("legal/"):
            continue
        text = (root / f).read_text(encoding="utf-8")
        if f in ("CLAUDE.md", MASTER) or IN_FORCE in text[:2000]:
            pages[f] = text
    return pages


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def added_since(base: str) -> list[str]:
    """Files on this checkout that the base does not have. A rename is not new."""
    out = git("diff", "--name-only", "-M", "--diff-filter=A", base, "HEAD")
    return [f for f in out.splitlines() if f]


def run(base: str) -> tuple[int, list[str]]:
    files = [f for f in git("ls-files").splitlines() if f]
    readme = (ROOT / MASTER).read_text(encoding="utf-8")
    rows = parse_homes(readme)
    problems = check_homes(files, rows, ROOT) + check_listed(files, readme)
    problems += check_log((ROOT / LOG).read_text(encoding="utf-8"), rules_pages(files, ROOT))
    try:
        git("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    except subprocess.CalledProcessError:
        problems.append(f"cannot see the base {base}, so new docs were not checked. Fetch it (git fetch origin main).")
        return 2, problems
    problems += check_new(added_since(base), readme)
    if problems:
        return 1, problems
    code = sum(1 for f in files if is_code(f))
    return 0, [f"docs guard: clean. {code} code files in {len(rows)} rows of home docs; every doc listed; "
               "no unapproved new doc; the log's numbers and the rules pages' citations hold."]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="origin/main")
    code, lines = run(ap.parse_args(argv).base)
    if code:
        print("docs guard: " + ("RED" if code == 1 else "CANNOT CHECK") + f", {len(lines)} problem(s):")
        for line in lines:
            print("  " + line)
        print(f"Where code is written up: {MASTER}, \"Home docs for the code\". Docs are not started (N107).")
    else:
        print(lines[0])
    return code


if __name__ == "__main__":
    sys.exit(main())
