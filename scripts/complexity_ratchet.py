#!/usr/bin/env python3
"""Cyclomatic-complexity ratchet (audit Q-C7, founder decision 2026-09-14,
option a).

Nothing flagged a new CC-121 function before this. Now every function in
the production surface (``TARGETS``) must have a cyclomatic complexity of at
most ``THRESHOLD`` — or be listed, at its frozen value, in
``scripts/complexity_baseline.json``. Same pattern as the mypy ratchet and
the F1 coverage floor: the baseline is the grandfathered set and it only
ever shrinks, in a reviewed commit.

    python scripts/complexity_ratchet.py            # check
    python scripts/complexity_ratchet.py --update   # re-freeze the baseline

Measured with radon (pinned in the checks job and scripts/local_ci.sh).
Keys are ``file:Class.method`` / ``file:function`` / ``file:outer.closure``
so a function keeps its entry when the lines around it move.

The check fails when
  * a function over the threshold is not in the baseline (new offender), or
  * a listed function grew past its frozen value (it may only come down), or
  * a listed function is now within the threshold or no longer exists (the
    baseline must be re-frozen so the shrink is visible).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "scripts" / "complexity_baseline.json"
THRESHOLD = 25
TARGETS = ("routes", "services", "utils", "app.py", "worker.py", "config.py")


def radon_json(targets: tuple[str, ...] = TARGETS) -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "radon", "cc", "-j", *targets],
        cwd=ROOT, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"radon failed ({proc.returncode}): {proc.stderr}")
    return json.loads(proc.stdout)


def measures_from(report: dict) -> dict[str, int]:
    """``{key: complexity}`` for every function, method and closure.
    Class entries are containers (radon lists their methods at the top
    level too) and are skipped."""
    out: dict[str, int] = {}
    for file, items in report.items():
        if isinstance(items, dict):   # {"error": ...} for an unparsable file
            raise SystemExit(f"radon could not parse {file}: {items}")
        for item in items:
            if item.get("type") == "class":
                continue
            owner = item.get("classname")
            name = f"{owner}.{item['name']}" if owner else item["name"]
            key = f"{file}:{name}"
            out[key] = max(out.get(key, 0), int(item["complexity"]))
            for closure in item.get("closures") or []:
                ckey = f"{file}:{name}.{closure['name']}"
                out[ckey] = max(out.get(ckey, 0), int(closure["complexity"]))
    return out


def check(measures: dict[str, int], baseline: dict[str, int]) -> list[str]:
    problems: list[str] = []
    for key, cc in sorted(measures.items()):
        frozen = baseline.get(key)
        if frozen is None:
            if cc > THRESHOLD:
                problems.append(
                    f"{key}: CC {cc} > {THRESHOLD} and not grandfathered. "
                    f"Split it.")
            continue
        if cc <= THRESHOLD:
            problems.append(
                f"{key}: CC {cc} is within the threshold now — remove it "
                f"from the baseline (python scripts/complexity_ratchet.py "
                f"--update)")
        elif cc > frozen:
            problems.append(
                f"{key}: CC grew {frozen} → {cc}. A grandfathered function "
                f"may only come down.")
    for key in baseline:
        if key not in measures:
            problems.append(
                f"{key}: in the baseline but no longer exists — re-freeze "
                f"(python scripts/complexity_ratchet.py --update)")
    return problems


def frozen_from(measures: dict[str, int]) -> dict[str, int]:
    return {k: v for k, v in sorted(measures.items()) if v > THRESHOLD}


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 2
    measures = measures_from(radon_json())
    if "--update" in argv:
        frozen = frozen_from(measures)
        BASELINE.write_text(json.dumps(frozen, indent=2) + "\n")
        print(f"complexity ratchet: froze {len(frozen)} functions over "
              f"CC {THRESHOLD} into {BASELINE.relative_to(ROOT)}")
        return 0
    baseline = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
    problems = check(measures, baseline)
    over = sum(1 for v in measures.values() if v > THRESHOLD)
    print(f"complexity ratchet: {len(measures)} functions, {over} "
          f"grandfathered over CC {THRESHOLD}")
    for line in problems:
        print(f"  FAIL {line}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
