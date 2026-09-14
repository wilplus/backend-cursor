#!/usr/bin/env python3
"""F1 coverage floor (audit Q-T12, founder decision 2026-09-14).

A per-file floor on the NAMED F1 modules only — no global number. A global
floor at the repo's 56% invites tests on scaffolding; this fails only when a
load-bearing module loses coverage it had.

    python scripts/coverage_floor.py <coverage.json>          # check
    python scripts/coverage_floor.py <coverage.json> --update  # re-freeze floors

Floors live in scripts/coverage_floor.json: {module path: minimum percent}.
The check reads the JSON report pytest-cov writes
(--cov=services --cov=routes --cov-report=json:<path>) and exits 1 if any
listed module is below its floor, or is missing from the report (a module
that was renamed or deleted must be re-listed, not silently dropped).
`--update` writes the measured values back, rounded DOWN to one decimal
minus a one-point tolerance, so a re-freeze can only ever lower a floor by an
explicit, reviewed commit.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLOORS = ROOT / "scripts" / "coverage_floor.json"
TOLERANCE = 1.0  # points below the measured value at freeze time


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 2
    report = json.loads(Path(argv[1]).read_text())
    files = report.get("files", {})
    floors: dict[str, float] = json.loads(FLOORS.read_text())
    update = "--update" in argv[2:]
    rows: list[tuple[str, float, float | None, str]] = []
    failed = False
    for module, floor in floors.items():
        entry = files.get(module)
        if entry is None:
            rows.append((module, floor, None, "MISSING"))
            failed = True
            continue
        pct = float(entry["summary"]["percent_covered"])
        if update:
            floors[module] = math.floor((pct - TOLERANCE) * 10) / 10
            rows.append((module, floors[module], pct, "frozen"))
        elif pct + 1e-9 < floor:
            rows.append((module, floor, pct, "BELOW"))
            failed = True
        else:
            rows.append((module, floor, pct, "ok"))
    width = max(len(m) for m in floors)
    print(f"{'F1 module':{width}}  floor   now   ")
    for name, minimum, measured, status in rows:
        now = "  n/a" if measured is None else f"{measured:5.1f}"
        print(f"{name:{width}}  {minimum:5.1f}  {now}  {status}")
    if update:
        FLOORS.write_text(json.dumps(floors, indent=2, sort_keys=True) + "\n")
        print(f"floors written to {FLOORS.relative_to(ROOT)}")
        return 0
    if failed:
        print("F1 coverage floor: RED — a load-bearing module lost coverage "
              "(or vanished from the report). Add the test back, or lower the "
              "floor in scripts/coverage_floor.json in a reviewed commit.")
        return 1
    print("F1 coverage floor: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
