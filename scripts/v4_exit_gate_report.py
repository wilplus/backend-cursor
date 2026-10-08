#!/usr/bin/env python3
"""V4 BEXIT: print the exit-gate report (founder V21 A, V15a A).

Read-only. Run with the service key in the environment, as the app does:
    python scripts/v4_exit_gate_report.py            # before the switch
    python scripts/v4_exit_gate_report.py --served-by v4
Prints the six lines in plain words, then the JSON for the decisions log.
Internal only (AC-9); nothing here switches V4 on."""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--served-by", choices=("v3", "v4"), default="v3")
    args = parser.parse_args()
    from services.db import db
    from services.v4_exit_gate import gather, plain_words
    report = gather(db, served_by=args.served_by)
    print("\n".join(plain_words(report)))
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
