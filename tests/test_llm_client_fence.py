"""Fence: one OpenAI client constructor, and no new direct chat call sites
(audit Q-A4, Phase 3).

Two rules, both read from the AST so a docstring or a comment cannot trip
or dodge them:

1. ``openai.OpenAI(`` / ``OpenAI(`` / ``AsyncOpenAI(`` is called in exactly
   one production module, ``services/llm_client.py``. CLAUDE.md's Phase-1
   boundary says "do not add direct provider clients"; this is the check.

2. ``.chat.completions.create(`` is a ratchet. ``services/llm.py`` is the
   sanctioned entry (``chat_complete``: authorization, timeouts, usage
   ledger, one log line). The sites below predate it and are grandfathered
   at their current count. Migrating one to ``chat_complete`` means lowering
   its number here in the same change; a new direct call anywhere fails the
   unit tier. The count can only go down.

Run: python3 -m pytest tests/test_llm_client_fence.py
"""
from __future__ import annotations

import ast
import collections
import pathlib

import pytest

from tests.repo_scan import ROOT, python_files, try_parse

CLIENT_MODULE = "services/llm_client.py"


def _production_files() -> list[pathlib.Path]:
    out = []
    for path in python_files(""):
        rel = path.relative_to(ROOT)
        if rel.parts[0] == "tests" or rel.name.startswith("test_"):
            continue
        out.append(path)
    return out


def _rel(path: pathlib.Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _is_client_constructor(call: ast.Call) -> bool:
    fn = call.func
    if isinstance(fn, ast.Attribute):
        return fn.attr in ("OpenAI", "AsyncOpenAI") and isinstance(fn.value, ast.Name) and fn.value.id == "openai"
    return isinstance(fn, ast.Name) and fn.id in ("OpenAI", "AsyncOpenAI")


def _is_direct_chat_create(call: ast.Call) -> bool:
    fn = call.func
    return (
        isinstance(fn, ast.Attribute) and fn.attr == "create"
        and isinstance(fn.value, ast.Attribute) and fn.value.attr == "completions"
        and isinstance(fn.value.value, ast.Attribute) and fn.value.value.attr == "chat"
    )


@pytest.fixture(scope="module")
def sightings():
    constructors: dict[str, int] = collections.Counter()
    chat_calls: dict[str, int] = collections.Counter()
    for path in _production_files():
        tree = try_parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _is_client_constructor(node):
                constructors[_rel(path)] += 1
            if _is_direct_chat_create(node):
                chat_calls[_rel(path)] += 1
    return dict(constructors), dict(chat_calls)


def test_the_openai_client_is_constructed_in_exactly_one_module(sightings):
    constructors, _ = sightings
    assert constructors == {CLIENT_MODULE: 1}, (
        "OpenAI clients are built only by services.llm_client.build_openai_client "
        f"(timeouts and retries live there). Found: {constructors}"
    )
