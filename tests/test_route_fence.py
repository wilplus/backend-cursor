"""The route fence (audit Q-C3): a route validates, authorises, calls one
service function, serialises. Enforced as size + direct ``db.`` calls per
function under routes/, with the grandfathered set frozen in
scripts/route_fence_baseline.json and only ever shrinking."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import route_fence as rf  # noqa: E402


def _measures(src):
    return {m.key.split(":", 1)[1]: m for m in rf.measure_source(src, "f.py")}


def test_the_fence_holds_on_the_repository():
    problems = rf.check(rf.measure_routes(),
                        json.loads(rf.BASELINE.read_text()))
    assert problems == [], "\n".join(problems)


def test_the_thresholds_are_the_decided_ones():
    assert rf.MAX_LINES == 80
    assert rf.MAX_DB_CALLS == 1


def test_the_baseline_only_lists_functions_over_a_threshold():
    baseline = json.loads(rf.BASELINE.read_text())
    assert baseline, "an empty baseline means the fence measured nothing"
    for key, frozen in baseline.items():
        assert (frozen["lines"] > rf.MAX_LINES
                or frozen["db_calls"] > rf.MAX_DB_CALLS), key
    assert list(baseline) == sorted(baseline), "baseline is sorted by key"


def test_lines_and_direct_db_calls_are_counted_per_function():
    src = (
        "def a():\n"
        "    x = db.get_one(1)\n"
        "    return x\n"
        "\n"
        "class R:\n"
        "    def b(self):\n"
        "        db.one()\n"
        "        db.two()\n"
        "        other.db.three()\n"     # not the module-level db
        "        return db.four\n"       # an attribute, not a call
    )
    m = _measures(src)
    assert m["a"].lines == 3 and m["a"].db_calls == 1
    assert m["R.b"].lines == 5 and m["R.b"].db_calls == 2
    assert not m["a"].over and m["R.b"].over


def test_a_closure_counts_toward_its_enclosing_function():
    src = (
        "def route():\n"
        "    def load():\n"
        "        return db.read(), db.read_again()\n"
        "    return load()\n"
    )
    m = _measures(src)
    assert m["route"].db_calls == 2
    assert m["route.load"].db_calls == 2


def test_a_new_offender_fails_and_a_grandfathered_one_may_only_shrink():
    big = "def big():\n" + "    x = 1\n" * 90
    measures = list(rf.measure_source(big, "routes/x.py"))
    assert rf.check(measures, {}) == [
        "routes/x.py:big: 91 lines, 0 db calls — over the fence (80 lines / "
        "1 db call) and not grandfathered. Move the logic into a service."]
    frozen = {"routes/x.py:big": {"lines": 91, "db_calls": 0}}
    assert rf.check(measures, frozen) == []
    smaller = {"routes/x.py:big": {"lines": 90, "db_calls": 0}}
    assert "grew" in rf.check(measures, smaller)[0]


def test_a_stale_baseline_entry_must_be_refrozen():
    small = "def small():\n    return 1\n"
    measures = list(rf.measure_source(small, "routes/x.py"))
    stale = {"routes/x.py:small": {"lines": 200, "db_calls": 0},
             "routes/x.py:gone": {"lines": 200, "db_calls": 0}}
    problems = rf.check(measures, stale)
    assert [p.split(":")[1].strip().split(" ")[0] for p in problems] == [
        "small", "gone"]
    assert all("--update" in p for p in problems)
