#!/usr/bin/env python3
"""Evaluate a DPO candidate through its real production surface adapter.

The candidate is injected only through an in-process evaluation ContextVar.
Nothing is written to runtime_config, so a failing candidate cannot affect a
production request.  The immutable report is the evidence required by the
separate promotion command.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.ml_dpo_release import (  # noqa: E402
    load_release_manifest,
    write_evaluation_report,
)
from services.ml_surface_contracts import (  # noqa: E402
    contract_for_surface,
    evaluation_model_override,
)
from tests.evals import harness  # noqa: E402
from tests.evals.surfaces import ADAPTERS  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface", required=True, help="Canonical DPO surface")
    parser.add_argument("--model-id", required=True, help="Fine-tuned candidate model id")
    parser.add_argument("--manifest", required=True, help="Dataset release manifest")
    parser.add_argument("--report-out", required=True, help="Immutable evaluation report path")
    args = parser.parse_args()

    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        raise SystemExit("OPENAI_API_KEY is required; candidate evaluation may not skip green.")

    contract = contract_for_surface(args.surface)
    model_id = str(args.model_id or "").strip()
    if not model_id:
        raise SystemExit("--model-id is required")
    manifest = load_release_manifest(
        Path(args.manifest), expected_surface=contract.id,
    )
    adapter = ADAPTERS.get(contract.golden_eval_surface)
    if adapter is None:
        raise SystemExit(
            f"No production eval adapter for {contract.golden_eval_surface!r}"
        )

    with evaluation_model_override(contract.id, model_id):
        verdicts = harness.run_surface(contract.golden_eval_surface, adapter)
    blocking = [v for v in verdicts if harness.is_blocking_failure(v)]
    passed = bool(verdicts) and not blocking
    report_payload = {
        "surface": contract.id,
        "golden_eval_surface": contract.golden_eval_surface,
        "candidate_model_id": model_id,
        "dataset_release_id": manifest["dataset_release_id"],
        "dataset_manifest_sha256": manifest["manifest_sha256"],
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "summary": {
            "cases": len(verdicts),
            "passed": sum(1 for verdict in verdicts if verdict.passed),
            "blocking_failures": len(blocking),
        },
        "verdicts": [
            {
                "case_id": verdict.case_id,
                "surface": verdict.surface,
                "passed": verdict.passed,
                "known_failing": verdict.known_failing,
                "reason": verdict.reason,
            }
            for verdict in verdicts
        ],
    }
    report = write_evaluation_report(Path(args.report_out), report_payload)
    harness.print_report(verdicts, 0.0)
    print({
        "status": "passed" if passed else "failed",
        "surface": contract.id,
        "model_id": model_id,
        "dataset_release_id": manifest["dataset_release_id"],
        "report": args.report_out,
        "evaluation_sha256": report["evaluation_sha256"],
    })
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
