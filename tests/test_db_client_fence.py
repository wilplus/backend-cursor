"""Fence: only ``services/db.py`` constructs a Supabase client (audit Q-A2,
Phase 4), and the F1 repositories read the client through the service.

Read from the AST so a docstring cannot trip or dodge it:

1. ``create_client(`` is called only in ``services/db.py`` and in the one
   grandfathered file below, frozen at its count. Down only. The auth routes
   used to build three ad-hoc service-role clients per request; they now ask
   ``services.db.new_client()`` for a fresh one (a shared client must not
   carry a user's password-grant session, so the per-request isolation is
   kept — the construction just lives in one place).
2. The three F1 repositories hold no client of their own: ``client`` is a
   property over the injected database service, so ``reset_connections()``
   after a fork reaches them.

Run: python3 -m pytest tests/test_db_client_fence.py
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from tests.repo_scan import ROOT, python_files, try_parse

ALLOWED = {"services/db.py"}

# path → create_client( calls, frozen 2026-09-14. Down only.
GRANDFATHERED_CLIENT_CONSTRUCTIONS = {
    # The delivery worker builds a bounded-timeout client of its own (D-series
    # amendment; the file is in the Confident Moment reviewed-hash manifest).
    "services/confident_moment_delivery_worker.py": 1,
    # Root-level developer utility (prints a login token); nothing imports it.
    "get_token.py": 1,
}

REPOSITORIES = (
    "services/recording_repository.py",
    "services/take_repository.py",
    "services/ideal_text_repository.py",
)


def _production_files() -> list[pathlib.Path]:
    out = []
    for path in python_files(""):
        rel = path.relative_to(ROOT)
        top = rel.parts[0]
        if top in ("tests", "scripts") or rel.name.startswith("test_") or rel.name == "conftest.py":
            continue
        out.append(path)
    return out


def _client_constructions(tree: ast.Module) -> int:
    n = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if (isinstance(fn, ast.Name) and fn.id == "create_client") or (
            isinstance(fn, ast.Attribute) and fn.attr == "create_client"
        ):
            n += 1
    return n


@pytest.fixture(scope="module")
def constructions() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in _production_files():
        tree = try_parse(path)
        if tree is None:
            continue
        n = _client_constructions(tree)
        if n:
            found[path.relative_to(ROOT).as_posix()] = n
    return found


def test_only_services_db_constructs_a_client(constructions):
    assert "services/db.py" in constructions, "services/db.py no longer builds the client?"
    found = {p: n for p, n in constructions.items() if p not in ALLOWED}
    new = {p: n for p, n in found.items() if p not in GRANDFATHERED_CLIENT_CONSTRUCTIONS}
    assert not new, (
        "a new Supabase client construction — use services.db.db.client, or "
        f"services.db.new_client() when the call needs its own session: {new}"
    )
    grown = {p: (GRANDFATHERED_CLIENT_CONSTRUCTIONS[p], n) for p, n in found.items()
             if n > GRANDFATHERED_CLIENT_CONSTRUCTIONS[p]}
    assert not grown, f"client constructions grew (frozen, found): {grown}"
    stale = {p: (n, found.get(p, 0)) for p, n in GRANDFATHERED_CLIENT_CONSTRUCTIONS.items()
             if found.get(p, 0) < n}
    assert not stale, f"a construction was removed (good) — lower its number here: {stale}"


def test_the_repositories_read_the_client_through_the_service():
    import inspect

    from services.table_repository import TableRepository

    base_source = inspect.getsource(TableRepository)
    assert "def client(self)" in base_source and "return self.database.client" in base_source, (
        "TableRepository must define client(self) reading self.database.client"
    )
    for rel in REPOSITORIES:
        tree = try_parse(ROOT / rel)
        assert tree is not None, rel
        assert _client_constructions(tree) == 0, f"{rel} constructs a client"
        source = (ROOT / rel).read_text()
        defines_directly = (
            "def client(self)" in source and "return self.database.client" in source
        )
        inherits_table_repository = (
            "from services.table_repository import TableRepository" in source
            and "(TableRepository)" in source
        )
        assert defines_directly or inherits_table_repository, (
            f"{rel} must read the client through the injected database service, "
            "either directly or by inheriting services.table_repository.TableRepository"
        )
        assert "from services.db import" not in source and "import services.db" not in source, (
            f"{rel} must not import services.db (the service imports the repository)"
        )


def test_new_client_is_a_fresh_object_not_the_shared_one(monkeypatch):
    from services import db as db_module

    built = []

    def _builder(self):
        built.append(object())
        return built[-1]

    monkeypatch.setattr(db_module.DatabaseService, "_build_supabase_client", _builder)
    fresh = db_module.new_client()
    assert fresh is built[-1]
    assert fresh is not db_module.db.client
