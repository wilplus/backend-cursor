#!/usr/bin/env python3
"""Route fence (audit Q-C3, founder decision 2026-09-14, option a).

A route validates, authorises, calls one service function, serialises. The
fence is on the two symptoms of a route that does more: its size and how
many database calls it makes. Every function under ``routes/`` must be
within ``MAX_LINES`` lines and make at most ``MAX_DB_CALLS`` direct
``db.<method>(...)`` calls — or be listed, at its frozen size, in
``scripts/route_fence_baseline.json``.

    python scripts/route_fence.py            # check
    python scripts/route_fence.py --update   # re-freeze the baseline

The baseline is the grandfathered set: every function that was over a
threshold when the fence went up, keyed ``file:qualname`` with the values
it had. The check fails when

  * a function over a threshold is not in the baseline (a new offender), or
  * a listed function grew past its frozen values (it may only shrink), or
  * a listed function is now within both thresholds or no longer exists
    (the baseline must be re-frozen so it only ever shrinks, visibly, in a
    reviewed commit).

Nested functions are measured on their own AND count toward the function
that encloses them: a closure that calls ``db`` twice is the route calling
``db`` twice.
"""
from __future__ import annotations

import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parent.parent
ROUTES = ROOT / "routes"
BASELINE = ROOT / "scripts" / "route_fence_baseline.json"
MAX_LINES = 80
MAX_DB_CALLS = 1
DB_NAME = "db"


@dataclass(frozen=True)
class Measure:
    key: str
    lines: int
    db_calls: int

    @property
    def over(self) -> bool:
        return self.lines > MAX_LINES or self.db_calls > MAX_DB_CALLS

    def as_json(self) -> dict[str, int]:
        return {"lines": self.lines, "db_calls": self.db_calls}


def _db_calls(node: ast.AST) -> int:
    count = 0
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and isinstance(sub.func.value, ast.Name)
                and sub.func.value.id == DB_NAME):
            count += 1
    return count


def measure_source(source: str, file_label: str) -> Iterator[Measure]:
    """Every function and method in ``source`` (nested ones with a dotted
    qualname), as ``file_label:qualname``."""
    tree = ast.parse(source)

    def walk(node: ast.AST, prefix: str) -> Iterator[Measure]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = f"{prefix}{child.name}"
                end = child.end_lineno or child.lineno
                yield Measure(f"{file_label}:{qualname}",
                              end - child.lineno + 1, _db_calls(child))
                yield from walk(child, f"{qualname}.")
            elif isinstance(child, ast.ClassDef):
                yield from walk(child, f"{prefix}{child.name}.")

    yield from walk(tree, "")


def measure_routes(root: Path = ROUTES) -> list[Measure]:
    out: list[Measure] = []
    for path in sorted(root.rglob("*.py")):
        label = path.relative_to(ROOT).as_posix()
        out.extend(measure_source(path.read_text(encoding="utf-8"), label))
    return out


def check(measures: list[Measure],
          baseline: dict[str, dict[str, int]]) -> list[str]:
    """The fence's findings; empty when the fence holds."""
    problems: list[str] = []
    seen: set[str] = set()
    for m in measures:
        if m.key in seen:
            problems.append(f"{m.key}: two functions share this qualname")
            continue
        seen.add(m.key)
        frozen = baseline.get(m.key)
        if frozen is None:
            if m.over:
                problems.append(
                    f"{m.key}: {m.lines} lines, {m.db_calls} db calls — over "
                    f"the fence ({MAX_LINES} lines / {MAX_DB_CALLS} db call) "
                    f"and not grandfathered. Move the logic into a service.")
            continue
        if not m.over:
            problems.append(
                f"{m.key}: now within the fence — remove it from the "
                f"baseline (python scripts/route_fence.py --update)")
        elif (m.lines > frozen["lines"]
              or m.db_calls > frozen["db_calls"]):
            problems.append(
                f"{m.key}: grew to {m.lines} lines / {m.db_calls} db calls "
                f"(frozen at {frozen['lines']} / {frozen['db_calls']}). A "
                f"grandfathered route may only shrink.")
    for key in baseline:
        if key not in seen:
            problems.append(
                f"{key}: in the baseline but no longer exists — re-freeze "
                f"(python scripts/route_fence.py --update)")
    return problems


def frozen_from(measures: list[Measure]) -> dict[str, dict[str, int]]:
    return {m.key: m.as_json() for m in sorted(measures, key=lambda x: x.key)
            if m.over}


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 2
    measures = measure_routes()
    if "--update" in argv:
        frozen = frozen_from(measures)
        BASELINE.write_text(json.dumps(frozen, indent=2) + "\n")
        print(f"route fence: froze {len(frozen)} grandfathered functions "
              f"into {BASELINE.relative_to(ROOT)}")
        return 0
    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    problems = check(measures, baseline)
    over = sum(1 for m in measures if m.over)
    print(f"route fence: {len(measures)} functions under routes/, {over} "
          f"grandfathered (max {MAX_LINES} lines, {MAX_DB_CALLS} db call)")
    for line in problems:
        print(f"  FAIL {line}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
