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


def test_the_fence_holds_on_the_repository():
    problems = rf.check(rf.measure_routes(),
                        json.loads(rf.BASELINE.read_text()))
    assert problems == [], "\n".join(problems)
