"""One file with every test's story: docs/TEST-STORIES.csv.

Each test file starts with a header (STORY/OUTCOME/PROVES/WHY, or
GUARD/CATCHES/IF REMOVED/PROVES for a developer tripwire). This script reads
those headers and writes them as one CSV, one row per test file, so the
founder can review every story in a spreadsheet instead of across many
Markdown files. The test file stays the source; the CSV is generated.

  python scripts/stories_csv.py           # rewrite docs/TEST-STORIES.csv
  python scripts/stories_csv.py --check   # exit 1 if the CSV is stale or a test has no header

tests/test_stories_csv.py runs --check in CI.
"""

from __future__ import annotations

import ast
import csv
import io
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "TEST-STORIES.csv"
COLUMNS = ["file", "type", "story", "outcomes", "proves", "why"]
SECTIONS = ("STORY", "GUARD", "OUTCOME", "CATCHES", "IF REMOVED", "PROVES", "WHY")
_SECTION = re.compile(r"^\s*(" + "|".join(SECTIONS) + r")\b\s*(.*)$")


def story_files() -> list[Path]:
    files = [p for p in (REPO / "tests").rglob("test_*.py") if "__pycache__" not in p.parts]
    root = REPO / "test_jwks.py"
    if root.exists():
        files.append(root)
    return sorted(files, key=lambda p: p.relative_to(REPO).as_posix())


def parse_header(text: str) -> dict[str, str] | None:
    """The header's sections, or None when the file has no STORY/GUARD header."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        m = _SECTION.match(line)
        if m:
            current = m.group(1)
            sections[current] = [m.group(2)] if m.group(2) else []
        elif current:
            sections[current].append(line.strip())

    def joined(name: str, sep: str) -> str:
        return sep.join(x for x in sections.get(name, []) if x).strip()

    if "STORY" in sections:
        return {"type": "Story", "story": joined("STORY", " "), "outcomes": joined("OUTCOME", "\n"),
                "proves": joined("PROVES", "\n"), "why": joined("WHY", " ")}
    if "GUARD" in sections:
        why = joined("IF REMOVED", " ")
        return {"type": "Guard", "story": joined("GUARD", " "), "outcomes": joined("CATCHES", "\n"),
                "proves": joined("PROVES", "\n"), "why": f"If removed: {why}" if why else ""}
    return None


def rows() -> tuple[list[dict[str, str]], list[str]]:
    found, missing = [], []
    for path in story_files():
        rel = path.relative_to(REPO).as_posix()
        try:
            doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
        except SyntaxError:
            doc = ""
        header = parse_header(doc)
        if header is None:
            missing.append(rel)
            continue
        found.append({"file": rel, **header})
    return found, missing


def render(found: list[dict[str, str]]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(found)
    return buf.getvalue()


def main(argv: list[str]) -> int:
    found, missing = rows()
    text = render(found)
    if "--check" in argv:
        problems = [f"no STORY or GUARD header: {m}" for m in missing]
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            problems.append("docs/TEST-STORIES.csv is out of date: run python scripts/stories_csv.py")
        for p in problems:
            print(p)
        return 1 if problems else 0
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}: {len(found)} test files")
    for m in missing:
        print(f"no STORY or GUARD header: {m}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
