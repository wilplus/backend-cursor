"""Fence: the production statement-timeout hook names three RPCs LITERALLY.

D49 §5 is satisfied by a PostgREST ``db-pre-request`` hook deployed on
2026-09-15 that bounds ``statement_timeout`` to 500 ms for three request paths
and leaves every other path at the role default (8 s for ``service_role``).
The hook matches by exact literal, so it has one silent failure mode: **rename,
re-version or re-route any of the three and that path drops out of the bound,
the 8 s ceiling returns, and nothing fails.** A 409'd owner would then exhaust
both bounded retries in ~1 s against their own orphaned transaction, which is
the dead-end retry D49 §5 exists to prevent — and no test, gate or monitor
would say so.

This fence is the tripwire. It reads the AST so a docstring or a comment cannot
trip or dodge it:

1. ``services/confident_moment_bundle_repository.py`` still calls exactly the
   three RPC names the deployed hook bounds — the same names, the same
   versions, from the same three methods.
2. The attestation document's deployed-hook block still lists exactly those
   three paths, so the record and the code cannot drift apart silently.

If this test fails, the production hook is out of date. Update the hook in the
database FIRST, then re-take the D49 §5 attestation, then update this fence —
in that order. Do not "fix" the fence to match new code and leave production
bounded to a path nothing calls any more.

Run: python3 -m pytest tests/test_confident_moment_timeout_hook_fence.py
"""
from __future__ import annotations

import ast
import re

import pytest

from tests.repo_scan import ROOT

REPOSITORY = "services/confident_moment_bundle_repository.py"
ATTESTATION = "docs/MLC3-CONFIDENT-MOMENT-D49-SECTION-5-ACTIVATION-ATTESTATION.md"

# The exact RPC names the deployed db-pre-request hook bounds to 500 ms,
# mapped from the repository method that calls each one. Frozen 2026-09-15
# against the production hook; see the attestation document.
BOUNDED_RPC_BY_METHOD = {
    "resolve_source_playback_authority":
        "resolve_confident_moment_source_playback_authority_v1",
    "authorize_source_playback_emit":
        "authorize_confident_moment_source_playback_emit_v1",
    "resolve_exercise_offer":
        "resolve_confident_moment_exercise_offer_v1",
}


def _called_rpc_names(source: str) -> dict[str, list[str]]:
    """method name → the string literals it passes as an RPC name.

    The repository invokes every RPC as ``<provider>.call("<name>", {...})``,
    so the first positional argument of a ``.call(...)`` is the RPC name.
    """
    tree = ast.parse(source)
    found: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names: list[str] = []
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Call):
                continue
            func = inner.func
            if not (isinstance(func, ast.Attribute) and func.attr == "call"):
                continue
            if not inner.args:
                continue
            first = inner.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                names.append(first.value)
        if names:
            found[node.name] = names
    return found


def test_the_bounded_rpc_names_are_still_the_ones_the_code_calls():
    source = (ROOT / REPOSITORY).read_text()
    called = _called_rpc_names(source)

    for method, expected_rpc in BOUNDED_RPC_BY_METHOD.items():
        assert method in called, (
            f"{REPOSITORY} no longer has a method {method!r} that calls an "
            f"RPC. The production timeout hook bounds {expected_rpc!r} on its "
            f"behalf; if this method moved or was renamed, confirm the hook "
            f"still covers whatever calls that RPC now."
        )
        assert expected_rpc in called[method], (
            f"{method}() calls {called[method]!r}, but the deployed hook "
            f"bounds {expected_rpc!r}. That path is no longer covered: it has "
            f"silently returned to the 8 s ceiling against a ~1 s client "
            f"window. Update the production hook and re-take the D49 §5 "
            f"attestation before changing this fence."
        )


def test_the_attestation_records_exactly_those_three_paths():
    text = (ROOT / ATTESTATION).read_text()
    deployed = text.split("## What was deployed", 1)
    assert len(deployed) == 2, (
        f"{ATTESTATION} no longer has a 'What was deployed' section; the "
        f"record of which paths production bounds has gone missing."
    )
    block = deployed[1].split("\n## ", 1)[0]
    recorded = set(re.findall(r"/rpc/([a-z0-9_]+)", block))

    assert recorded == set(BOUNDED_RPC_BY_METHOD.values()), (
        f"The attestation's deployed-hook block records {sorted(recorded)}, "
        f"but this fence is frozen at "
        f"{sorted(BOUNDED_RPC_BY_METHOD.values())}. The document and the "
        f"fence must move together, and only after the production hook does."
    )


@pytest.mark.parametrize("rpc_name", sorted(BOUNDED_RPC_BY_METHOD.values()))
def test_each_bounded_rpc_is_still_defined_by_a_migration(rpc_name):
    """A bounded path must still exist; the hook cannot bound a dropped RPC."""
    definitions = [
        path for path in (ROOT / "migrations").glob("*.sql")
        if f"FUNCTION public.{rpc_name}(" in path.read_text()
    ]
    assert definitions, (
        f"No migration defines {rpc_name!r}, which the production timeout "
        f"hook bounds by name. Either it was renamed — in which case the hook "
        f"now bounds nothing on that path — or the hook should stop naming it."
    )
