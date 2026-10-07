"""Parity guard for the signed line bank.

Lines are parsed from docs/SIGNED-line-bank-2026-10-06.md so a drift in
services/line_bank.py fails here. The module must not invent a line.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from services.line_bank import (
    BANKS,
    CLEARER_BANKS,
    CUE_BANK,
    LATER,
    PRACTISE_BANKS,
    PRAISE_BANKS,
    bank_for_cue,
    later_line,
    line,
)

SIGNED = (
    Path(__file__).resolve().parent.parent / "docs" / "SIGNED-line-bank-2026-10-06.md"
)

# Sanity table read off the signed markdown. The parser, not these numbers,
# is what proves the strings.
EXPECTED_COUNTS = {
    "B01": 5,
    "B02": 4,
    "B03": 4,
    "B04": 4,
    "B05": 5,
    "B06": 5,
    "B07": 5,
    "B08": 5,
    "B09": 5,
    "B10": 5,
    "B11": 7,
    "B12": 5,
    "B13": 7,
    "B14": 7,
    "NX3a": 4,
    "CM3b": 4,
}

_LATER_BANKS = {f"B{n:02d}" for n in range(1, 10)}
_BANK_HEADING = re.compile(r"^\*\*(B\d\d) · ")


def _bank_id(heading: str) -> str | None:
    match = _BANK_HEADING.match(heading)
    if match:
        return match.group(1)
    if heading.startswith("**After a try where nothing moved** (NX3a)"):
        return "NX3a"
    if heading.startswith("**After the third try that isn't praise**"):
        return "CM3b"
    return None


def _is_other_heading(heading: str) -> bool:
    if heading.startswith("## "):
        return True
    return heading.startswith("**") and "**" in heading[2:]


def parse_signed(text: str) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    """Pull sayable bullets and B01-B09 later-lines out of the signed markdown."""
    banks: dict[str, list[str]] = {}
    later: dict[str, str] = {}
    current: str | None = None
    collecting = False
    for raw in text.splitlines():
        bank_id = _bank_id(raw)
        if bank_id is not None:
            current = bank_id
            banks[current] = []
            collecting = False
            continue
        if _is_other_heading(raw):
            current = None
            collecting = False
            continue
        if current is None:
            continue
        if raw.startswith("- "):
            collecting = True
            bullet = raw[2:]
            if bullet.startswith("Later: ") and current in _LATER_BANKS:
                later[current] = bullet[len("Later: ") :]
            else:
                banks[current].append(bullet)
            continue
        if collecting:
            current = None
            collecting = False
    return {key: tuple(value) for key, value in banks.items()}, later


def test_parity_with_signed_markdown() -> None:
    text = SIGNED.read_text(encoding="utf-8")
    parsed, parsed_later = parse_signed(text)
    assert list(BANKS) == list(parsed)
    for bank, bullets in parsed.items():
        assert BANKS[bank] == bullets
    assert LATER == parsed_later
    assert set(BANKS) == {f"B{n:02d}" for n in range(1, 15)} | {"NX3a", "CM3b"}
    assert {bank: len(bullets) for bank, bullets in BANKS.items()} == EXPECTED_COUNTS
    assert len(LATER) == 9
    assert tuple(LATER) == PRAISE_BANKS


def test_bank_kinds() -> None:
    assert PRAISE_BANKS == tuple(f"B{n:02d}" for n in range(1, 10))
    assert CLEARER_BANKS == ("B10", "B11", "B12", "B13", "B14")
    assert PRACTISE_BANKS == ("NX3a", "CM3b")
    assert set(PRAISE_BANKS) | set(CLEARER_BANKS) | set(PRACTISE_BANKS) == set(BANKS)


def test_ac9_no_digit_except_take_placeholder() -> None:
    """No number other than the Take number ever appears (AC-9).

    B09's signed later line names no earlier Take, so it carries no {n}.
    Every other later line carries {n} exactly once, and nothing else numeric.
    """
    for bullets in BANKS.values():
        for text in bullets:
            assert re.search(r"\d", text) is None
            assert "{" not in text and "}" not in text
    for bank, text in LATER.items():
        stripped = text.replace("{n}", "")
        assert re.search(r"\d", stripped) is None
        assert "{" not in stripped and "}" not in stripped
        if bank == "B09":
            assert text.count("{n}") == 0
        else:
            assert text.count("{n}") == 1


def test_line_helper() -> None:
    assert line("B02", 0) == BANKS["B02"][0]
    with pytest.raises(KeyError):
        line("B99", 0)
    with pytest.raises(IndexError):
        line("B01", 99)


def test_later_line_fills_take_and_refuses_a_non_take() -> None:
    assert later_line("B01", 2) == "This sounded more confident than on Take 2."
    with pytest.raises(ValueError):
        later_line("B01", 0)


def test_bank_for_cue() -> None:
    expected = {
        "wide_range": "B02",
        "full_volume": "B03",
        "no_hesitation": "B04",
        "settled_pitch": "B05",
        "kept_moving": "B06",
        "landed_ending": "B07",
        "opened_strong": "B08",
        "confident": "B01",
        "tentative": "B09",
    }
    assert CUE_BANK == expected
    for cue, bank in expected.items():
        assert bank_for_cue(cue) == bank
    assert bank_for_cue(None) == "B09"
    assert bank_for_cue("unknown") == "B09"
    assert set(CUE_BANK.values()) <= set(PRAISE_BANKS)
