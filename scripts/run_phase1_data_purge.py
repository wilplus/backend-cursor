#!/usr/bin/env python3
"""Preview or execute one already-requested Phase-1 purge.

Execution is deliberately double-gated. Merely deploying this script cannot
delete anything: the operator must set the kill-switch and repeat the exact
immutable request ID on the command line.
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

from services.data_purge import DataPurgeOrchestrator
from services.db import db


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview or resolve one immutable Phase-1 purge request.",
    )
    parser.add_argument("--purge-request-id", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-request-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    orchestrator = DataPurgeOrchestrator(db)
    if not args.execute:
        inventory = orchestrator.build_inventory(args.purge_request_id)
        print(json.dumps({
            "mode": "preview",
            "purge_request_id": args.purge_request_id,
            "subject_graph": inventory["graph"].payload(),
            "targets": [target.payload() for target in inventory["targets"]],
            "catalog": inventory["catalog"],
        }, sort_keys=True))
        return 0

    if os.getenv("PHASE1_PURGE_EXECUTION_ENABLED", "").strip().lower() != "true":
        raise SystemExit("PHASE1_PURGE_EXECUTION_DISABLED")
    if args.confirm_request_id != args.purge_request_id:
        raise SystemExit("PURGE_REQUEST_CONFIRMATION_MISMATCH")
    print(json.dumps(orchestrator.run(args.purge_request_id), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
