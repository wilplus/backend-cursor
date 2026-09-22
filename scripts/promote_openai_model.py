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

from config import Config  # noqa: E402
from services.db import db  # noqa: E402
from services.ml_dpo_release import load_evaluation_report  # noqa: E402
from services.ml_surface_contracts import (  # noqa: E402
    contract_for_surface,
    locked_prompt_hash,
    runtime_config_key,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote OpenAI model by writing runtime_config key/value.")
    parser.add_argument("--surface", required=True, help="Canonical DPO surface")
    parser.add_argument("--model-id", required=True, help="Model id to use at inference (e.g. ft:...)")
    parser.add_argument("--evaluation-report", required=True, help="Passing immutable evaluation report")
    parser.add_argument("--max-report-age-hours", type=int, default=336, help="Maximum report age, default 14 days")
    parser.add_argument("--updated-by", default="ops:promote_openai_model.py", help="updated_by marker")
    parser.add_argument(
        "--prompt-hash",
        default=None,
        help=(
            "The prompts.lock.json digest for this surface, as printed by "
            "`--show-prompt-hash`. Must match the lockfile at promotion time."
        ),
    )
    parser.add_argument(
        "--show-prompt-hash", action="store_true",
        help="Print the current locked prompt hash for --surface and exit.",
    )
    args = parser.parse_args()

    contract = contract_for_surface(args.surface)

    if args.show_prompt_hash:
        print(locked_prompt_hash(contract.id))
        return

    # LEGACY-1 / J1-2 (audit 2026-09-22). THE GATE, BEFORE ANY WRITE.
    #
    # This script was the only writer of `runtime_config`, and
    # `services/llm.py` served what it wrote within sixty seconds — on the
    # Take-1 Ideal Text composition and every Say It Stronger card. The three
    # MLC2_* constants documented the lane as switched off and were read by
    # nothing on the path, so an operator with the service-role key could
    # change the words in a speaker's document while the HTTP surface still
    # answered "promotion is not active".
    #
    # Checked FIRST, before the evaluation report is even opened, so that a
    # refusal cannot be confused with a report problem.
    if not Config.MLC2_PROMOTION_ENABLED:
        raise SystemExit(
            "Promotion is disabled: MLC2_PROMOTION_ENABLED is false. This is "
            "the shipped posture; opening it is a founder decision taken in "
            "the activation runbook with the readiness evaluators green, not "
            "a flag flipped at promotion time."
        )

    model_id = (args.model_id or "").strip()
    if not model_id:
        raise SystemExit("--model-id is required.")
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

    # H-1 (audit 2026-09-22). BIND THE MODEL TO THE PROMPT IT WAS GATED UNDER.
    #
    # The evaluation above proves the candidate answers correctly through the
    # real serving adapter. It does not record WHICH PROMPT the adapter sent,
    # so a prompt edit after promotion re-points a gated model at text it was
    # never evaluated against, invisibly. Storing the digest turns that into a
    # mismatch somebody can see.
    expected_prompt_hash = locked_prompt_hash(contract.id)
    supplied = (args.prompt_hash or "").strip().lower()
    if not supplied:
        raise SystemExit(
            "--prompt-hash is required. The model must be bound to the "
            f"prompts it was evaluated under; current value for "
            f"{contract.id}: {expected_prompt_hash}"
        )
    if supplied != expected_prompt_hash:
        raise SystemExit(
            "Prompt lock mismatch: the prompts for "
            f"{contract.id} have changed since this candidate was evaluated "
            f"(supplied {supplied}, current {expected_prompt_hash}). "
            "Re-run the golden evaluation against the current prompts."
        )

    key = runtime_config_key(contract.id)
    row = db.promote_runtime_surface_model(
        key=key,
        value=model_id,
        updated_by=str(args.updated_by).strip() or None,
        metadata={
            "source": "evaluation_gated_manual_promotion",
            "surface": contract.id,
            "dataset_release_id": report["dataset_release_id"],
            "evaluation_sha256": report["evaluation_sha256"],
            "prompt_lock_sha256": expected_prompt_hash,
        },
    )
    if not row:
        raise SystemExit(
            "Failed to update runtime_config. Run "
            "migrations/guard_runtime_config_model_keys.sql first."
        )
    print({
        "status": "ok",
        "surface": contract.id,
        "key": key,
        "model_id": model_id,
        "dataset_release_id": report["dataset_release_id"],
        "prompt_lock_sha256": expected_prompt_hash,
    })


if __name__ == "__main__":
    main()
