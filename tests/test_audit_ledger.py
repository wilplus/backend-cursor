"""Contract tests for scripts/ledger_check.py.

The checker does not exist yet. These tests must fail (not skip) until
``check(ledger_text, base_text=None) -> list[str]`` is importable from
scripts/ledger_check.py and enforces the ledger rules. An empty list means
the ledger is valid. Every error string must contain the offending row ID
(for a deleted row, the missing ID).
"""

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "scripts" / "ledger_check.py"
LEDGER_PATH = REPO_ROOT / "docs" / "audit" / "LEDGER.md"

HEADER = (
    "| ID | Source | Claim | Area | Verified? | Evidence | Filter verdict "
    "| Severity | Plan | PR | Test | Status |"
)
SEPARATOR = "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"


def load_check():
    """Import check() from scripts/ledger_check.py. Missing module fails the test."""
    if not MODULE_PATH.is_file():
        pytest.fail(f"scripts/ledger_check.py is missing at {MODULE_PATH}")
    spec = importlib.util.spec_from_file_location("ledger_check", MODULE_PATH)
    if spec is None or spec.loader is None:
        pytest.fail(f"cannot load module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    check = getattr(module, "check", None)
    if check is None:
        pytest.fail("scripts/ledger_check.py must define check(ledger_text, base_text=None)")
    return check


def twelve_cell_row(row_id, status, pr="—", test="—"):
    return (
        f"| {row_id} | src | claim | area | yes | ev | keep | low | plan "
        f"| {pr} | {test} | {status} |"
    )


def ledger(*rows):
    return "\n".join([HEADER, SEPARATOR, *rows])


def assert_valid(errors):
    assert errors == [], errors


def assert_offending(errors, *row_ids):
    assert isinstance(errors, list), errors
    assert errors, "expected at least one error"
    for err in errors:
        assert isinstance(err, str) and err, err
        assert any(row_id in err for row_id in row_ids), err
    blob = "\n".join(errors)
    for row_id in row_ids:
        assert row_id in blob, errors


def test_duplicate_row_ids_are_rejected():
    check = load_check()
    text = ledger(
        twelve_cell_row("A002", "OPEN"),
        twelve_cell_row("A003b", "CONFIRMED"),
        twelve_cell_row("A002", "FALSE"),
    )
    assert_offending(check(text), "A002")


def test_row_ids_present_in_base_text_must_still_be_present():
    check = load_check()
    base = ledger(
        twelve_cell_row("A002", "OPEN"),
        twelve_cell_row("A003b", "VERIFYING"),
        twelve_cell_row("N04a", "OPEN"),
    )
    current = ledger(
        twelve_cell_row("A002", "CONFIRMED"),
        twelve_cell_row("X10", "OPEN"),
    )
    assert_offending(check(current, base), "A003b", "N04a")


def test_done_on_twelve_cell_rows_needs_a_test_cell():
    check = load_check()
    text = ledger(
        twelve_cell_row("A002", "DONE", pr="#1", test="—"),
        twelve_cell_row("BG01", "DONE", pr="#2", test=""),
        twelve_cell_row("CA12", "DONE · QUESTION: where is the test?", pr="#3", test="—"),
    )
    assert_offending(check(text), "A002", "BG01", "CA12")


def test_docs_audit_ledger_md_passes():
    check = load_check()
    if not LEDGER_PATH.is_file():
        pytest.fail(f"docs/audit/LEDGER.md is missing at {LEDGER_PATH}")
    errors = check(LEDGER_PATH.read_text(encoding="utf-8"))
    assert_valid(errors)
