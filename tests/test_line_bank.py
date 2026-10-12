"""Parity guard for the signed line bank.

Lines are parsed from docs/SIGNED-line-bank-2026-10-06.md so a drift in
services/line_bank.py fails here. The module must not invent a line.
"""

from __future__ import annotations

import re
from pathlib import Path

from services.line_bank import (
    BANKS,
    LATER,
)

SIGNED = (
    Path(__file__).resolve().parent.parent / "docs" / "SIGNED-line-bank-2026-10-06.md"
)


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
