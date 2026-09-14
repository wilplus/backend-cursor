"""One repo walk per test session, shared by the fence tests.

WHY THIS EXISTS (audit Q-T11, 2026-09-14). Four fence modules
(`test_session_globals_wiring`, `test_snippet_table_name`,
`test_stress_snippets_retired`, `test_snippet_value_resolution`) each walked
the repository and re-parsed every Python file inside every test method:
seven full walks and roughly 2,000 `ast.parse` calls per run, about 25 of the
suite's 90 seconds. Worse, under `scripts/local_ci.sh` the walk descended into
`.venv-ci/` — thousands of site-packages files — because the per-module skip
sets predate the venv. The gate was slower than CI and nobody could see why.

This module walks once, parses each file once, and hands out the results.
It is a plain module with `functools.lru_cache` rather than only a pytest
fixture because the fence modules are `unittest.TestCase` classes (which
cannot take fixtures) and are documented to run under
`python3 -m unittest <module>` as well. `conftest.py` exposes the same
object as a session-scoped fixture for pytest-style tests.

The cache is safe because nothing in the suite writes source files. If a
test ever does, call `reset()` first.

    from tests.repo_scan import ROOT, python_files, parse, source_text

    for path in python_files("services"):          # cached tuple of Paths
        tree = parse(path)                         # cached ast.Module
"""
from __future__ import annotations

import ast
import functools
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Never repository source: VCS, caches, environments (including the gate's
# own .venv-ci), the agent tooling's worktrees, and the frontend's modules.
SKIP_DIRS = frozenset({
    ".git", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "node_modules", "venv", ".venv", ".venv-ci", ".claude",
})


def _skipped(path: pathlib.Path) -> bool:
    return any(
        part in SKIP_DIRS or part.startswith(".venv")
        for part in path.relative_to(ROOT).parts
    )


@functools.lru_cache(maxsize=None)
def python_files(subdir: str = "") -> tuple[pathlib.Path, ...]:
    """Every *.py under ROOT/<subdir> (whole repo when subdir is ""), sorted,
    with environment and cache directories excluded. Callers apply their own
    finer filters (skip tests, skip a defining module, ...)."""
    base = ROOT / subdir if subdir else ROOT
    return tuple(sorted(p for p in base.rglob("*.py") if not _skipped(p)))


@functools.lru_cache(maxsize=None)
def source_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@functools.lru_cache(maxsize=None)
def parse(path: pathlib.Path) -> ast.Module:
    """Parsed module. Raises SyntaxError like `ast.parse` would — a fence that
    walks runtime code should fail loudly on a file that does not parse."""
    return ast.parse(source_text(path), filename=str(path))


def try_parse(path: pathlib.Path) -> ast.Module | None:
    """`parse` for walks that legitimately cross files which may not parse."""
    try:
        return parse(path)
    except (SyntaxError, UnicodeDecodeError):
        return None


def reset() -> None:
    python_files.cache_clear()
    source_text.cache_clear()
    parse.cache_clear()
