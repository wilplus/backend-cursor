"""The complexity ratchet (audit Q-C7): no function in the production
surface exceeds CC 25 unless it is frozen in
scripts/complexity_baseline.json, and a frozen one may only come down.
The live run is the checks job's "Complexity ratchet" step (radon is
pinned there and in scripts/local_ci.sh); these tests pin the rule."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import complexity_ratchet as cr  # noqa: E402


def _report(**per_file):
    return {file: items for file, items in per_file.items()}


def test_the_threshold_and_targets_are_the_decided_ones():
    assert cr.THRESHOLD == 25
    assert cr.TARGETS == ("routes", "services", "utils", "app.py",
                          "worker.py", "config.py")


def test_the_baseline_only_lists_functions_over_the_threshold():
    baseline = json.loads(cr.BASELINE.read_text())
    assert baseline
    assert all(cc > cr.THRESHOLD for cc in baseline.values())
    assert list(baseline) == sorted(baseline)
    assert all(":" in key and key.split(":")[0].endswith(".py")
               for key in baseline)


def test_methods_are_keyed_by_class_and_classes_are_skipped():
    report = _report(**{"services/x.py": [
        {"type": "method", "name": "m", "classname": "C", "complexity": 4,
         "closures": []},
        {"type": "class", "name": "C", "complexity": 4,
         "methods": [{"type": "method", "name": "m", "classname": "C",
                      "complexity": 4}]},
        {"type": "function", "name": "f", "classname": None, "complexity": 30,
         "closures": [{"name": "inner", "complexity": 2}]},
    ]})
    assert cr.measures_from(report) == {
        "services/x.py:C.m": 4,
        "services/x.py:f": 30,
        "services/x.py:f.inner": 2,
    }


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


def test_the_split_changes_block_is_not_in_the_baseline():
    """Q-C1's proof: the 900-line block came down under the threshold in
    every stage, so nothing under services/ideal_text_changes.py is
    grandfathered."""
    baseline = json.loads(cr.BASELINE.read_text())
    assert not [k for k in baseline if "ideal_text_changes" in k]
