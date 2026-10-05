#!/usr/bin/env python3
"""Preview or run the deletions whose seven days are over (founder
2026-10-05, decisions log N48.4 Q14 A, Q17 A; migration 0422).

The same run the cron makes through POST /v2/internal/deletion/complete-due
(services/deletion_completion.py), for an operator in a shell. A preview by
default: it lists what is due and what waits for a person, and writes
nothing. Executing is double-gated like scripts/run_phase1_data_purge.py:
the kill switch PHASE1_PURGE_EXECUTION_ENABLED=true in this shell AND
--execute on the command line.

    python scripts/run_due_deletions.py                 # preview
    python scripts/run_due_deletions.py --execute       # run (needs the switch)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.db import db  # noqa: E402
from services.deletion_completion import (  # noqa: E402
    DEFAULT_LIMIT, MAX_LIMIT, run_due_deletions,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or run the deletions whose seven days are over.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help=f"requests to work on (1..{MAX_LIMIT})")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.execute and os.getenv(
            "PHASE1_PURGE_EXECUTION_ENABLED", "").strip().lower() != "true":
        raise SystemExit("PHASE1_PURGE_EXECUTION_DISABLED")
    report = run_due_deletions(db, execute=args.execute, limit=args.limit)
    print(json.dumps(report, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
