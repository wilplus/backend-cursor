"""
GUARD      One OpenAI client constructor (services/llm_client.py) and no new
           direct `.chat.completions.create(` call sites. services/llm.py
           (`chat_complete`: authorization, timeouts, usage ledger) is the
           sanctioned entry. Both rules read the AST, so prose cannot trip or
           dodge them.
CATCHES    A second provider client, or a new direct chat call that skips the
           processing-authorization path (CLAUDE.md: every provider call goes
           through it).
IF REMOVED A provider call can be added anywhere without authorization or
           usage accounting, and nothing goes red.
PROVES     test_the_openai_client_is_constructed_in_exactly_one_module
           test_direct_chat_calls_can_only_go_down
             the ratchet: counts must equal CHAT_CALLS_ALLOWED; migrating a
             site to chat_complete lowers its number here in the same change
WHY        Audit Q-A4, Phase 3.
"""
from __future__ import annotations

import ast
import collections
import pathlib

import pytest

from tests.repo_scan import ROOT, python_files, try_parse

CLIENT_MODULE = "services/llm_client.py"

#: Direct chat calls, frozen 2026-10-19. llm.py is the sanctioned entry; the
#: others predate it. Numbers only ever go down; a file not listed may have none.
CHAT_CALLS_ALLOWED = {
    "services/llm.py": 1,
    "services/ceo_work_items.py": 1,
    "services/dev_tasks.py": 2,
    "services/life_engine.py": 1,
}


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


def test_direct_chat_calls_can_only_go_down(sightings):
    _, chat_calls = sightings
    grown = {path: n for path, n in chat_calls.items()
             if n > CHAT_CALLS_ALLOWED.get(path, 0)}
    assert not grown, (
        "new direct .chat.completions.create( call(s); use services.llm."
        f"chat_complete instead: {grown}")
    assert chat_calls == CHAT_CALLS_ALLOWED, (
        "a direct chat call was migrated: lower its number in "
        f"CHAT_CALLS_ALLOWED. Now: {chat_calls}")
