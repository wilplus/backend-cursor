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


def short_ledger(*rows):
    return "\n".join(
        [
            "| ID | Note | Status |",
            "| --- | --- | --- |",
            *rows,
        ]
    )


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


def test_duplicate_row_ids_across_tables_are_rejected():
    check = load_check()
    text = "\n\n".join(
        [
            short_ledger("| N04a | first table | OPEN |"),
            short_ledger("| N04a | second table | PARKED (waiting) |"),
        ]
    )
    assert_offending(check(text), "N04a")


def test_unique_row_ids_of_every_ledger_shape_are_accepted():
    check = load_check()
    text = ledger(
        twelve_cell_row("A002", "OPEN"),
        twelve_cell_row("A003b", "VERIFYING"),
        twelve_cell_row("N04a", "CONFIRMED"),
        twelve_cell_row("X10", "FALSE"),
        twelve_cell_row("B1.1", "DUPLICATE (of A023)"),
        twelve_cell_row("B1.4b", "FOUNDER (ops: read the log)"),
        twelve_cell_row("BEXIT", "PARKED (waiting on legal)"),
        twelve_cell_row("BP-a", "OPEN"),
        twelve_cell_row("B2.3", "OPEN"),
        twelve_cell_row("O1", "OPEN"),
        twelve_cell_row("BG01", "OPEN"),
        twelve_cell_row("CA12", "IN-PR", pr="#12"),
    )
    assert_valid(check(text))


def test_status_word_must_be_one_of_the_allowed_set():
    check = load_check()
    text = ledger(
        twelve_cell_row("A002", "OPEN"),
        twelve_cell_row("X10", "CLOSED"),
        twelve_cell_row("O1", "open"),
        twelve_cell_row("BG01", "IN PR"),
        twelve_cell_row("CA12", "—"),
    )
    assert_offending(check(text), "X10", "O1", "BG01", "CA12")


def test_allowed_status_words_with_optional_reason_and_question_are_accepted():
    check = load_check()
    text = ledger(
        twelve_cell_row("A002", "OPEN"),
        twelve_cell_row("A003b", "VERIFYING"),
        twelve_cell_row("N04a", "CONFIRMED"),
        twelve_cell_row("X10", "FALSE"),
        twelve_cell_row("B1.1", "DUPLICATE (of A023)"),
        twelve_cell_row("B1.4b", "FOUNDER (ops: read the log)"),
        twelve_cell_row("BEXIT", "PARKED (waiting on legal)"),
        twelve_cell_row("BP-a", "IN-PR (DECIDED in review)", pr="#9"),
        twelve_cell_row("B2.3", "DONE · QUESTION: ship it?", pr="#10", test="tests/test_done.py"),
        twelve_cell_row("O1", "FALSE (not in code)"),
    )
    assert_valid(check(text))


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


def test_status_may_change_and_rows_may_be_added_when_base_text_is_given():
    check = load_check()
    base = "\n".join(
        [
            HEADER,
            SEPARATOR,
            twelve_cell_row("A002", "OPEN"),
            twelve_cell_row("B1.1", "VERIFYING"),
            "| V4 coverage | not a ledger row | OPEN |",
        ]
    )
    current = ledger(
        twelve_cell_row("A002", "DONE", pr="#4", test="tests/test_a002.py"),
        twelve_cell_row("B1.1", "FOUNDER (ops: read the log)"),
        twelve_cell_row("CA12", "OPEN"),
    )
    assert_valid(check(current, base))


def test_in_pr_or_done_on_twelve_cell_rows_need_a_pr_cell():
    check = load_check()
    text = ledger(
        twelve_cell_row("A002", "IN-PR", pr="—", test="tests/test_a002.py"),
        twelve_cell_row("A003b", "IN-PR (DECIDED ...)", pr="", test="tests/test_a003b.py"),
        twelve_cell_row("N04a", "DONE", pr="—", test="tests/test_n04a.py"),
        twelve_cell_row("X10", "DONE", pr="", test="tests/test_x10.py"),
    )
    assert_offending(check(text), "A002", "A003b", "N04a", "X10")


def test_other_statuses_and_short_rows_may_omit_the_pr_cell():
    check = load_check()
    text = "\n\n".join(
        [
            ledger(
                twelve_cell_row("A002", "OPEN"),
                twelve_cell_row("A003b", "FALSE"),
                twelve_cell_row("N04a", "IN-PR", pr="#15"),
            ),
            short_ledger("| B1.1 | no pr column here | IN-PR |"),
            short_ledger("| X10 | no pr column here | DONE |"),
        ]
    )
    assert_valid(check(text))


def test_done_on_twelve_cell_rows_needs_a_test_cell():
    check = load_check()
    text = ledger(
        twelve_cell_row("A002", "DONE", pr="#1", test="—"),
        twelve_cell_row("BG01", "DONE", pr="#2", test=""),
        twelve_cell_row("CA12", "DONE · QUESTION: where is the test?", pr="#3", test="—"),
    )
    assert_offending(check(text), "A002", "BG01", "CA12")


def test_done_with_pr_and_test_passes_and_in_pr_may_omit_the_test_cell():
    check = load_check()
    text = ledger(
        twelve_cell_row("A002", "DONE", pr="#8", test="tests/test_a002.py"),
        twelve_cell_row("A003b", "IN-PR", pr="#9", test="—"),
        twelve_cell_row("N04a", "IN-PR (DECIDED ...)", pr="#10", test=""),
        twelve_cell_row("O1", "OPEN", test="—"),
    )
    assert_valid(check(text))


def test_founder_or_parked_need_a_non_empty_reason_in_parentheses():
    check = load_check()
    text = "\n\n".join(
        [
            ledger(
                twelve_cell_row("A002", "FOUNDER"),
                twelve_cell_row("A003b", "FOUNDER ()"),
                twelve_cell_row("N04a", "PARKED"),
                twelve_cell_row("X10", "PARKED ()"),
                twelve_cell_row("B1.1", "FOUNDER · QUESTION: who owns this?"),
            ),
            short_ledger("| BG01 | short row | PARKED |"),
        ]
    )
    assert_offending(check(text), "A002", "A003b", "N04a", "X10", "B1.1", "BG01")


def test_founder_or_parked_with_a_reason_are_accepted():
    check = load_check()
    text = ledger(
        twelve_cell_row("A002", "FOUNDER (ops: read the log)"),
        twelve_cell_row("A003b", "PARKED (waiting on legal)"),
        twelve_cell_row("B1.4b", "FOUNDER (needs a human) · QUESTION: which log?"),
        twelve_cell_row("O1", "OPEN"),
        twelve_cell_row("CA12", "DUPLICATE (of A023)"),
    )
    assert_valid(check(text))


def test_v4_coverage_lines_headers_and_separators_are_not_ledger_rows():
    check = load_check()
    text = "\n".join(
        [
            HEADER,
            SEPARATOR,
            "| V4 A002 | coverage | area | yes | ev | keep | low | plan | — | — | CLOSED |",
            "| V4 not-an-id | still coverage | OPEN |",
            twelve_cell_row("A002", "OPEN"),
            twelve_cell_row("BEXIT", "CONFIRMED"),
        ]
    )
    assert_valid(check(text))


def test_docs_audit_ledger_md_passes():
    check = load_check()
    if not LEDGER_PATH.is_file():
        pytest.fail(f"docs/audit/LEDGER.md is missing at {LEDGER_PATH}")
    errors = check(LEDGER_PATH.read_text(encoding="utf-8"))
    assert_valid(errors)
