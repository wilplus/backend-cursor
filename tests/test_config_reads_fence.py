"""Fence: environment variables are read in ``config.py`` and
``services/secrets.py``, nowhere else (audit Q-A5, Phase 4).

The CONFIG-FIRST rule (CLAUDE.md, 2026-08-10) says a variable is set on
every Railway service before the code that reads it merges. That is only
checkable when there is one place the code reads from. The audit found 86
``os.environ`` / ``os.getenv`` reads in 42 production files outside
``config.py``; the F1 modules (transcription, Ideal Text, Manager) among them
now read through ``Config``, and this test keeps it that way:

1. Every module in the F1 coverage floor (``scripts/coverage_floor.json``)
   reads no environment variable directly.
2. Every other production file is frozen at its current count below. Down
   only: a new read anywhere fails the unit tier, and a file that moves its
   reads into ``Config`` lowers its number here in the same change.

Read from the AST (``os.environ`` / ``os.getenv`` attribute access on the
``os`` module), so a comment or a docstring neither trips nor dodges it.

Run: python3 -m pytest tests/test_config_reads_fence.py
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from tests.repo_scan import ROOT, python_files, try_parse


def _production_files() -> list[pathlib.Path]:
    out = []
    for path in python_files(""):
        rel = path.relative_to(ROOT)
        top = rel.parts[0]
        if top in ("tests", "scripts") or rel.name.startswith("test_") or rel.name == "conftest.py":
            continue
        out.append(path)
    return out


def _env_reads(tree: ast.Module) -> int:
    return sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name) and node.value.id == "os"
        and node.attr in ("environ", "getenv")
    )


@pytest.fixture(scope="module")
def reads_by_file() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in _production_files():
        tree = try_parse(path)
        if tree is None:
            continue
        n = _env_reads(tree)
        if n:
            found[path.relative_to(ROOT).as_posix()] = n
    return found


def test_the_f1_modules_read_no_environment_variable_directly(reads_by_file):
    floor = json.loads((ROOT / "scripts" / "coverage_floor.json").read_text())
    offenders = {p: reads_by_file[p] for p in floor if p in reads_by_file}
    assert not offenders, (
        "F1 modules read configuration through Config (config.py), never "
        f"os.environ / os.getenv directly: {offenders}"
    )
