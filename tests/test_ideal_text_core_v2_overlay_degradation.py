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
into a 500. 0329 then fixed the defect 0328 EXPOSED: with the raise gone, the
read reached the D29 validator for the first time and was rejected, because
``current_part_revision_id`` crossed as a JSON number instead of a canonical
bigint string.

These assertions are those rules with teeth, because the next person to touch
this read will not have watched it break.

WHY THIS FOLLOWS THE MANIFEST INSTEAD OF NAMING A FILE
------------------------------------------------------
Each fix is a new ``CREATE OR REPLACE`` — applied migrations are never edited —
so the definition that PRODUCTION runs is the one in the LAST manifest entry
that defines the function, not any fixed filename. Pinning a filename would
quietly start guarding a superseded copy the moment the next fix lands, which
is the same class of stale-guard bug this file exists to prevent. So the
assertions resolve the live definition through the manifest every run.

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
ORIGIN = MIGRATIONS / "add_confident_moment_coaching_bundle_v1.sql"
MANIFEST = MIGRATIONS / "manifest.txt"

FUNCTION = "CREATE OR REPLACE FUNCTION public.read_ideal_text_document_core_v2"


def _manifest_order() -> list[str]:
    return [
        line.rstrip("\n").split("\t")[1]
        for line in MANIFEST.read_text().splitlines()
        if "\t" in line
    ]


def _live_migration() -> str:
    """The last manifest migration defining the read — what production runs."""
    winner = None
    for name in _manifest_order():
        path = MIGRATIONS / name
        if path.exists() and FUNCTION in path.read_text():
            winner = name
    assert winner is not None, "no manifest migration defines the core v2 read"
    return winner


def _body() -> str:
    """The live function body only, so header prose never satisfies a check."""
    sql = (MIGRATIONS / _live_migration()).read_text()
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
    handler = _strip_comments(_overlay_handler(_body()))
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
    handler = _strip_comments(_overlay_handler(_body()))
    assert "ELSE" in handler.upper(), "the handler has no default branch"
    for state in ("'unavailable'", "'disabled'"):
        assert state in handler, f"the handler never reports {state}"


def test_a_missing_document_is_not_an_error() -> None:
    """No INTO STRICT: 'no document yet' is a 404 pending, not a P0002 500."""
    body = _strip_comments(_body())
    assert "INTO STRICT" not in body.upper(), (
        "INTO STRICT raises no_data_found for an arc with no project row and "
        "for an arc whose document has not been published yet — both normal "
        "states that the route already answers with 404 pending."
    )
    assert body.count("IF NOT FOUND THEN RETURN NULL; END IF;") == 3, (
        "each of the three lookups must return no-document rather than raise"
    )


def test_every_bigint_id_crosses_as_a_string() -> None:
    """A bigint past 2^53 loses precision as a JSON number in any JS client.

    ``services/confident_moment_bundle.py`` enforces this with ``_bigint_string``
    (``^[1-9][0-9]*$``) and rejects the WHOLE document when it is broken, so a
    missing cast is not cosmetic. ``ideal_text_part_revision.id`` is BIGSERIAL
    and needs the cast that its sibling ``user_text_revision`` already had.
    """
    body = _strip_comments(_body())
    assert "'current_part_revision_id',l.current_part_revision_id::text" in body, (
        "current_part_revision_id must be cast to text; uncast, BIGSERIAL "
        "crosses as a JSON number and the D29 validator rejects the document"
    )
    assert "owner_note.user_text_revision::text" in body, (
        "user_text_revision must keep its cast for the same reason"
    )


def test_owner_edit_is_all_or_nothing() -> None:
    """With no owner text there is no owner edit state — every field empty.

    ``validate_owner_edit_transport`` rejects the WHOLE document when a null
    ``text`` arrives beside any non-null sibling or a non-empty ``parts``, and
    the frontend enforces the same rule independently
    (``mapConfidentMomentOwnerEdit``: ``value.parts.length !== 0`` → reject).
    ``owner_edit.parts`` means "the paragraphs the owner has edited", not the
    document's paragraph inventory, so the empty state carries none.
    """
    body = _strip_comments(_body())
    assert "IF owner_note.user_text IS NULL THEN" in body, (
        "all six owner_edit fields must be decided by one condition — whether "
        "an owner edit exists — not by four conditions that mostly coincide"
    )
    assert "'parts','[]'::jsonb" in body, (
        "the canonical empty owner_edit carries parts: [], which is what both "
        "the validator and the client's own fixture require"
    )


def test_the_ownership_fence_still_raises() -> None:
    """Degrading the overlay must not soften an identity check."""
    body = _body()
    assert body.count("RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'") == 2, (
        "an actor/principal mismatch is a real integrity failure, not a "
        "missing optional overlay, and must stay loud"
    )


def test_the_wire_contract_is_unchanged() -> None:
    """No new user-facing string: AC-9 and the LIVE LOOP copy fence.

    The status object keeps its exact shape, so no client changes and nothing
    needs founder sign-off. The diagnostic goes to the server log instead.
    """
    body = _body()
    states = set(re.findall(r"'state','([a-z_]+)'", body))
    assert states == {"available", "unavailable", "disabled"}, states
    assert "'code',NULL" in body and "'retryable',false" in body
    assert "RAISE LOG" in body, (
        "once the RPC stops raising, the server log is the only trace that the "
        "overlay degraded"
    )


def test_applied_migrations_are_never_edited() -> None:
    """0327 is applied, checksum-pinned and in the ledger. Editing it desyncs.

    Every fix is a later CREATE OR REPLACE, which is why the live definition is
    resolved through the manifest rather than by filename.
    """
    origin = ORIGIN.read_text()
    assert FUNCTION in origin, "0327 should still carry its own definition"
    assert "IF SQLERRM LIKE '%DISABLED%' THEN summary:=NULL" in origin, (
        "0327 is an applied migration and must keep its original text; a fix "
        "belongs in a later CREATE OR REPLACE, not in an edit to history"
    )
    assert _live_migration() != ORIGIN.name, (
        "the live definition is still 0327's, so no fix is actually applied"
    )


def test_the_live_definition_is_manifested_after_the_one_it_corrects() -> None:
    """Order is the whole contract: run a fix before 0327 and 0327 wins."""
    order = _manifest_order()
    assert order.index(_live_migration()) > order.index(ORIGIN.name), (
        "the winning CREATE OR REPLACE must be applied after the definition it "
        "replaces"
    )


def test_the_read_extracts_the_key_the_projection_returns() -> None:
    """THE ONE TOKEN (0350). The projection returns `confident_moment_summary`;
    the read asked for `summary`, got NULL, called it `available`, and the
    validator threw the whole v2 envelope away on every V3 Take since GA."""
    import re
    origin = ORIGIN.read_text()
    returned = re.search(
        r"RETURN jsonb_build_object\('bundle_projection',body,'([a-z_]+)',summary\);",
        origin,
    )
    assert returned is not None, "the projection's return shape moved"
    key = returned.group(1)
    assert key == "confident_moment_summary"
    body = _strip_comments(_body())
    assert f"source_take_session_id)->'{key}'" in body
    assert "->'summary'" not in body


def test_a_null_summary_is_reported_unavailable_not_available() -> None:
    """The guard that keeps the SQL consistent with the validator: whatever
    shape the projection returns in future, a NULL summary degrades to
    `unavailable` with `owner_edit` intact, never to an `available` the
    reader must refuse."""
    handler = _overlay_handler(_strip_comments(_body()))
    assert "IF summary IS NULL THEN" in handler
    unavailable = handler.index("'state','unavailable'")
    available = handler.index("'state','available'")
    assert unavailable < available
