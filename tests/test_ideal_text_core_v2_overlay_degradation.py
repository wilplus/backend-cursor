"""The Confident Moment overlay may never take the Ideal Text read down again.

WHY THIS FILE EXISTS
--------------------
LIVE LOOP incident, 2026-09-15. Every GET /v2/explore/arc/<id>/ideal-text/core
returned 500 in production for about two and a half hours. The cause was one
line in 0327's ``read_ideal_text_document_core_v2``: the OPTIONAL Confident
Moment overlay was fetched inside a handler that degraded only when the error
TEXT matched ``'%DISABLED%'``, and re-raised everything else.

That literal matches exactly two strings in the whole migration set, both
deliberate kill switches. It therefore handled "somebody turned the overlay
off" and did not handle "the overlay was never turned on" — the shipped
default, which raises MLC3_ROLLOUT_NOT_ACTIVE. An F2 overlay took down the F1
document. CLAUDE.md R12: F1 must be bulletproof WITHOUT the learning layer.

0328 inverts the rule — ANY overlay failure degrades and the document is still
returned — and stops three ``INTO STRICT`` selects turning "no document yet"
into a 500. These assertions are that rule with teeth, because the next person
to add an overlay to this read will not have watched it break.

``tests/test_ideal_text_core_read_degrades.py`` pins the Python wrapper's
fallback (#507). This file pins the SQL underneath it. They are independent
safety nets on purpose: the wrapper stops a raise reaching the user, this stops
the raise happening.

Run: python3 -m pytest tests/test_ideal_text_core_v2_overlay_degradation.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "migrations"
FIX = MIGRATIONS / "fix_ideal_text_core_v2_optional_overlay_degradation.sql"
ORIGIN = MIGRATIONS / "add_confident_moment_coaching_bundle_v1.sql"
MANIFEST = MIGRATIONS / "manifest.txt"

SQL = FIX.read_text()
FUNCTION = "CREATE OR REPLACE FUNCTION public.read_ideal_text_document_core_v2"


def _body(sql: str) -> str:
    """The function body only, so header prose never satisfies an assertion."""
    assert FUNCTION in sql, "the core v2 read is not defined in this file"
    return sql.split(FUNCTION, 1)[1].split("END $$;", 1)[0]


def _strip_comments(body: str) -> str:
    return "\n".join(line.split("--")[0] for line in body.splitlines())


def _overlay_handler(body: str) -> str:
    """The exception block around the optional Confident Moment summary."""
    marker = "project_confident_moment_bundles_v1"
    assert marker in body
    return body.split(marker, 1)[1].split("snapshot_json:=", 1)[0]


def test_the_overlay_handler_never_re_raises() -> None:
    """The one line that caused the incident. Every path must assign a status."""
    handler = _strip_comments(_overlay_handler(_body(SQL)))
    assert not re.search(r"\bRAISE\s*;", handler), (
        "a bare RAISE in the overlay handler re-raises an OPTIONAL overlay's "
        "failure out of the F1 document read — this is exactly the 2026-09-15 "
        "outage. Degrade to a status state instead."
    )


def test_degradation_is_not_keyed_on_an_enumerated_error_list() -> None:
    """The defect was enumerating survivable failures. The default must degrade.

    ``%DISABLED%`` may stay — it distinguishes the two explicit kill switches —
    but it may not be the only way out of the handler.
    """
    handler = _strip_comments(_overlay_handler(_body(SQL)))
    assert "ELSE" in handler.upper(), "the handler has no default branch"
    for state in ("'unavailable'", "'disabled'"):
        assert state in handler, f"the handler never reports {state}"


def test_a_missing_document_is_not_an_error() -> None:
    """No INTO STRICT: 'no document yet' is a 404 pending, not a P0002 500."""
    body = _strip_comments(_body(SQL))
    assert "INTO STRICT" not in body.upper(), (
        "INTO STRICT raises no_data_found for an arc with no project row and "
        "for an arc whose document has not been published yet — both normal "
        "states that the route already answers with 404 pending."
    )
    assert body.count("IF NOT FOUND THEN RETURN NULL; END IF;") == 3, (
        "each of the three lookups must return no-document rather than raise"
    )


def test_the_ownership_fence_still_raises() -> None:
    """Degrading the overlay must not soften an identity check."""
    body = _body(SQL)
    assert body.count("RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'") == 2, (
        "an actor/principal mismatch is a real integrity failure, not a "
        "missing optional overlay, and must stay loud"
    )


def test_the_wire_contract_is_unchanged() -> None:
    """No new user-facing string: AC-9 and the LIVE LOOP copy fence.

    The status object keeps its exact shape, so no client changes and nothing
    needs founder sign-off. The diagnostic goes to the server log instead.
    """
    body = _body(SQL)
    states = set(re.findall(r"'state','([a-z_]+)'", body))
    assert states == {"available", "unavailable", "disabled"}, states
    assert "'code',NULL" in body and "'retryable',false" in body
    assert "RAISE LOG" in body, (
        "once the RPC stops raising, the server log is the only trace that the "
        "overlay degraded"
    )


def test_the_original_migration_is_not_edited() -> None:
    """0327 is applied, checksum-pinned and in the ledger. Editing it desyncs."""
    origin = ORIGIN.read_text()
    assert FUNCTION in origin, "0327 should still carry its own definition"
    assert "IF SQLERRM LIKE '%DISABLED%' THEN summary:=NULL" in origin, (
        "0327 is an applied migration and must keep its original text; the fix "
        "belongs in a later CREATE OR REPLACE, not in an edit to history"
    )


def test_the_fix_is_manifested_after_the_migration_it_corrects() -> None:
    """Order is the whole contract: run 0328 before 0327 and 0327 wins."""
    order = [
        line.rstrip("\n").split("\t")[1]
        for line in MANIFEST.read_text().splitlines()
        if "\t" in line
    ]
    assert FIX.name in order, "the fix is not in the manifest, so it never runs"
    assert order.index(FIX.name) > order.index(ORIGIN.name), (
        "the CREATE OR REPLACE must be applied after the definition it replaces"
    )
