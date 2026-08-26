#!/usr/bin/env python3
"""Promote an evaluated model into exactly one correction surface.

Example:
  python3 scripts/promote_openai_model.py \
    --surface say_it_stronger \
    --model-id ft:gpt-4.1-mini:org:proj:abc123 \
    --evaluation-report exports/say-it-stronger-eval.json \
    --updated-by artur
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.db import db  # noqa: E402
from services.ml_dpo_release import load_evaluation_report  # noqa: E402
from services.ml_surface_contracts import (  # noqa: E402
    contract_for_surface,
    runtime_config_key,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote OpenAI model by writing runtime_config key/value.")
    parser.add_argument("--surface", required=True, help="Canonical DPO surface")
    parser.add_argument("--model-id", required=True, help="Model id to use at inference (e.g. ft:...)")
    parser.add_argument("--evaluation-report", required=True, help="Passing immutable evaluation report")
    parser.add_argument("--max-report-age-hours", type=int, default=336, help="Maximum report age, default 14 days")
    parser.add_argument("--updated-by", default="ops:promote_openai_model.py", help="updated_by marker")
    args = parser.parse_args()

    model_id = (args.model_id or "").strip()
    if not model_id:
        raise SystemExit("--model-id is required.")

    contract = contract_for_surface(args.surface)
    try:
        report = load_evaluation_report(Path(args.evaluation_report))
    except (ValueError, OSError) as exc:
        raise SystemExit(f"Evaluation gate rejected promotion: {exc}")
    if report.get("surface") != contract.id:
        raise SystemExit("Evaluation report belongs to a different surface")
    if report.get("golden_eval_surface") != contract.golden_eval_surface:
        raise SystemExit("Evaluation report did not exercise the canonical production adapter")
    if report.get("candidate_model_id") != model_id:
        raise SystemExit("Evaluation report belongs to a different model")
    try:
        evaluated_at = datetime.fromisoformat(str(report["evaluated_at"]).replace("Z", "+00:00"))
        age = datetime.now(timezone.utc) - evaluated_at.astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"Evaluation report has invalid evaluated_at: {exc}")
    if age.total_seconds() < 0 or age.total_seconds() > max(1, args.max_report_age_hours) * 3600:
        raise SystemExit("Evaluation report is expired or dated in the future")

    key = runtime_config_key(contract.id)
    row = db.upsert_runtime_config(
        key=key,
        value=model_id,
        updated_by=str(args.updated_by).strip() or None,
        metadata={
            "source": "evaluation_gated_manual_promotion",
            "surface": contract.id,
            "dataset_release_id": report["dataset_release_id"],
            "evaluation_sha256": report["evaluation_sha256"],
        },
    )
    if not row:
        raise SystemExit(
            "Failed to update runtime_config. Run migrations/add_runtime_model_config.sql first."
        )
    print({
        "status": "ok",
        "surface": contract.id,
        "key": key,
        "model_id": model_id,
        "dataset_release_id": report["dataset_release_id"],
    })


if __name__ == "__main__":
    main()
