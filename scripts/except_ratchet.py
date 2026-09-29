#!/usr/bin/env python3
"""Silent catch-all exception handlers, per file, shrink-only (audit A4).

WHY (bug-trace drills, 2026-09-26). The drills went cold at an ``except``
more often than anywhere else. Of about 1,500 ``except Exception`` handlers
under services/ and routes/, most caught the error without keeping its
traceback, so "why did this Take lose its slide links" became a guess.

A handler is SILENT when it catches everything (``except:``,
``Exception`` or ``BaseException``, alone or in a tuple) and its body does
none of these:

  * re-raise (any ``raise`` statement in the handler);
  * keep the traceback: ``<logger>.exception(...)``, any call passing
    ``exc_info=`` with a value other than literal False/None, or
    ``capture_exception(...)``.

A handler whose ``except`` line carries ``# noqa: BLE001`` followed by a
reason is a deliberate, explained swallow and is not counted.

The check is per file and shrink-only, like the route fence:

  * a file may not gain silent handlers, and a file with none may not get
    its first: new code logs with the traceback, re-raises, or catches the
    narrow type it expects;
  * when a file's count drops, the baseline is re-frozen in the same change,
    so the gain is locked in visibly.

    python scripts/except_ratchet.py            # check
    python scripts/except_ratchet.py --update   # re-freeze
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "scripts" / "except_ratchet_baseline.json"
SCANNED = ("services", "routes", "utils", "app.py", "worker.py", "config.py")
BROAD = {"Exception", "BaseException"}
_EXPLAINED = re.compile(r"#\s*noqa:\s*BLE001\s*[-—:]*\s*\S")
_TRACEBACK_CALLS = {"exception", "capture_exception"}


def _is_broad(handler_type: ast.expr | None) -> bool:
    if handler_type is None:
        return True
    if isinstance(handler_type, ast.Name):
        return handler_type.id in BROAD
    if isinstance(handler_type, ast.Attribute):
        return handler_type.attr in BROAD
    if isinstance(handler_type, ast.Tuple):
        return any(_is_broad(e) for e in handler_type.elts)
    return False


def _call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return ""


def _passes_exc_info(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg != "exc_info":
            continue
        falsy = (isinstance(kw.value, ast.Constant)
                 and kw.value.value in (False, None))
        if not falsy:
            return True
    return False


def _keeps_the_error(handler: ast.ExceptHandler) -> bool:
    for stmt in handler.body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Raise):
                return True
            if isinstance(node, ast.Call) and (
                    _call_name(node) in _TRACEBACK_CALLS
                    or _passes_exc_info(node)):
                return True
    return False


def silent_handlers(source: str) -> list[int]:
    """Line numbers of the silent catch-all handlers in ``source``."""
    lines = source.splitlines()
    out: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.ExceptHandler) or not _is_broad(node.type):
            continue
        if _EXPLAINED.search(lines[node.lineno - 1]):
            continue
        if not _keeps_the_error(node):
            out.append(node.lineno)
    return sorted(out)


def scanned_files(root: Path = ROOT) -> list[Path]:
    files: list[Path] = []
    for entry in SCANNED:
        path = root / entry
        if path.is_dir():
            files.extend(p for p in path.rglob("*.py")
                         if "__pycache__" not in p.parts)
        elif path.exists():
            files.append(path)
    return sorted(files)


def measure(root: Path = ROOT) -> dict[str, int]:
    """``{relative path: silent handler count}`` for every scanned file."""
    counts: dict[str, int] = {}
    for path in scanned_files(root):
        label = path.relative_to(root).as_posix()
        counts[label] = len(silent_handlers(path.read_text(encoding="utf-8")))
    return counts


def check(counts: dict[str, int], baseline: dict[str, int]) -> list[str]:
    """The ratchet's findings; empty when it holds."""
    problems: list[str] = []
    for label, count in sorted(counts.items()):
        frozen = baseline.get(label, 0)
        if count > frozen:
            problems.append(
                f"{label}: {count} silent catch-all handlers (frozen at "
                f"{frozen}). Keep the traceback (logger.exception or "
                f"exc_info=True), re-raise, or catch the narrow type.")
        elif count < frozen:
            problems.append(
                f"{label}: down to {count} from {frozen}. Lock the gain in: "
                f"python scripts/except_ratchet.py --update")
    for label in sorted(set(baseline) - set(counts)):
        problems.append(
            f"{label}: in the baseline but no longer scanned. Re-freeze: "
            f"python scripts/except_ratchet.py --update")
    return problems


def frozen_from(counts: dict[str, int]) -> dict[str, int]:
    return {label: n for label, n in sorted(counts.items()) if n}


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 2
    counts = measure()
    if "--update" in argv:
        frozen = frozen_from(counts)
        BASELINE.write_text(json.dumps(frozen, indent=2) + "\n")
        print(f"except ratchet: froze {sum(frozen.values())} silent handlers "
              f"in {len(frozen)} files into {BASELINE.relative_to(ROOT)}")
        return 0
    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    problems = check(counts, baseline)
    print(f"except ratchet: {sum(counts.values())} silent catch-all handlers "
          f"in {sum(1 for n in counts.values() if n)} of {len(counts)} files "
          f"(shrink-only)")
    for line in problems:
        print(f"  FAIL {line}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
