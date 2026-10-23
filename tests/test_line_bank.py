"""
STORY    As the founder, I want the lines in code to be exactly the lines I
         signed, with no number but the Take number, so that no unapproved
         words or scores reach a speaker.
OUTCOME
  O1  Every bank in services/line_bank.py, the AI clip's openers, tips per
      problem and closers included (N120), equals the signed doc, bullet for
      bullet and in order; no line is invented, dropped or reworded (Never-4).
  O2  A line a speaker can be shown carries no number except the Take number
      a later line fills in (Never-1: no scores or numbers to speakers).
PROVES   O1 -> test_every_bank_line_equals_the_signed_doc
         O2 -> test_ac9_no_digit_except_take_placeholder
WHY      docs/SIGNED-line-bank-2026-10-06.md is the source of truth (N54);
         the AI clip's bubble signed 2026-10-23 (N120).
"""

from __future__ import annotations

import re
from pathlib import Path

from services.line_bank import BANKS, LATER, later_line, line

SIGNED = (
    Path(__file__).resolve().parent.parent / "docs" / "SIGNED-line-bank-2026-10-06.md"
)

# The practising banks are named by their decision code, not "**Bxx".
_HEADING_BANK = {
    "After a try where nothing moved": "NX3a",
    "After the third try that isn't praise": "CM3b",
}


def _signed_banks() -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    """Parse the signed markdown into (banks, later lines) keyed like the code."""
    banks: dict[str, list[str]] = {}
    later: dict[str, str] = {}
    current: str | None = None
    for raw in SIGNED.read_text(encoding="utf-8").splitlines():
        if raw.startswith("## "):
            current = None
        elif raw.startswith("**"):
            code = re.match(r"\*\*(B\d\d|AI[a-z]+) ", raw)
            title = raw[2:].split("**", 1)[0]
            current = code.group(1) if code else _HEADING_BANK.get(title)
            if current:
                banks[current] = []
        elif current and raw.startswith("- "):
            text = raw[2:]
            if text.startswith("Later: "):
                later[current] = text[len("Later: "):]
            else:
                banks[current].append(text)
    return {k: tuple(v) for k, v in banks.items()}, later


def test_every_bank_line_equals_the_signed_doc() -> None:
    signed_banks, signed_later = _signed_banks()
    # Guard the parser itself: it must find all 24 banks (16, and the AI
    # clip's 8, N120) and 9 later lines.
    assert len(signed_banks) == 24 and len(signed_later) == 9
    assert BANKS == signed_banks
    assert LATER == signed_later


def test_ac9_no_digit_except_take_placeholder() -> None:
    """Every sayable line has words and no digit; a later line shows only the
    Take number; an AI clip's tip shows only the speaker's own phrase."""
    for bank, bullets in BANKS.items():
        for i in range(len(bullets)):
            shown = line(bank, i).replace("{phrase}", "four days")
            assert re.search(r"[A-Za-z]{3}", shown)
            assert re.search(r"\d", shown) is None
            assert "{" not in shown and "}" not in shown
    for bank in LATER:
        shown = later_line(bank, 7)
        assert re.search(r"[A-Za-z]{3}", shown)
        assert re.search(r"\d", shown.replace("Take 7", "")) is None
        assert "{" not in shown and "}" not in shown
        # B09's signed later line names no earlier Take; every other one does.
        assert ("Take 7" in shown) is (bank != "B09")
