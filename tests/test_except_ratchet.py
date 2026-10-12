"""Silent catch-all handlers may only get fewer (audit A4, 2026-09-28).

scripts/except_ratchet.py counts, per file, the handlers that catch
everything and keep neither the error nor its traceback. The count is
frozen in scripts/except_ratchet_baseline.json and only ever shrinks.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import except_ratchet as er  # noqa: E402


def test_the_ratchet_holds_on_the_repository():
    problems = er.check(er.measure(), json.loads(er.BASELINE.read_text()))
    assert problems == [], "\n".join(problems)


def test_check_catches_growth_a_first_offender_and_a_stale_baseline():
    baseline = {"a.py": 2, "gone.py": 1}
    problems = er.check({"a.py": 3, "b.py": 1}, baseline)
    text = "\n".join(problems)
    assert "a.py: 3 silent catch-all handlers (frozen at 2)" in text
    assert "b.py: 1 silent catch-all handlers (frozen at 0)" in text
    assert "gone.py: in the baseline but no longer scanned" in text
    shrunk = er.check({"a.py": 1}, {"a.py": 2})
    assert shrunk and "Lock the gain in" in shrunk[0]
    assert er.check({"a.py": 2, "c.py": 0}, {"a.py": 2}) == []
