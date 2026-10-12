"""The complexity ratchet (audit Q-C7): no function in the production
surface exceeds CC 25 unless it is frozen in
scripts/complexity_baseline.json, and a frozen one may only come down.
The live run is the checks job's "Complexity ratchet" step (radon is
pinned there and in scripts/local_ci.sh); these tests pin the rule."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import complexity_ratchet as cr  # noqa: E402


def test_a_new_offender_fails_and_a_frozen_one_may_only_come_down():
    measures = {"services/x.py:f": 30, "services/x.py:g": 3}
    assert cr.check(measures, {}) == [
        "services/x.py:f: CC 30 > 25 and not grandfathered. Split it."]
    assert cr.check(measures, {"services/x.py:f": 30}) == []
    assert cr.check(measures, {"services/x.py:f": 40}) == []
    assert "grew 29 → 30" in cr.check(measures, {"services/x.py:f": 29})[0]


def test_a_stale_baseline_entry_must_be_refrozen():
    measures = {"services/x.py:f": 10}
    problems = cr.check(measures, {"services/x.py:f": 30,
                                   "services/x.py:gone": 30})
    assert len(problems) == 2
    assert all("--update" in p for p in problems)
