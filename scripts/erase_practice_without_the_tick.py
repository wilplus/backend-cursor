#!/usr/bin/env python3
"""Preview, or erase, practice made for people who never ticked the box.

Founder decision 1 (2026-09-25). Preview is the default and changes nothing.
Execute needs both --execute and --approved-sha256 equal to the hash the
approved preview printed; a list that changed since is refused whole.

  python3 scripts/erase_practice_without_the_tick.py
  python3 scripts/erase_practice_without_the_tick.py --execute --approved-sha256 <hash>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.db import db
from services.practice_without_the_tick import execute, preview


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approved-sha256")
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps(preview(db), sort_keys=True, indent=2))
        return 0
    if not args.approved_sha256:
        raise SystemExit("APPROVED_SHA256_REQUIRED")
    outcome = execute(db, approved_sha256=args.approved_sha256)
    print(json.dumps(outcome, sort_keys=True, indent=2))
    return 0 if outcome["complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
