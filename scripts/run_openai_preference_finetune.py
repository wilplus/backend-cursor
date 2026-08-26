#!/usr/bin/env python3
"""
Start an OpenAI preference/DPO fine-tune job from one immutable, surface-scoped
dataset release. A successful job produces a candidate only; promotion is a
separate, evaluation-gated human action.

Requires:
  - OPENAI_API_KEY in env
  - A manifest produced by export_openai_preference_jsonl.py

Examples:
  python3 scripts/run_openai_preference_finetune.py \
    --train-file exports/dpo-train.jsonl \
    --val-file exports/dpo-val.jsonl \
    --manifest exports/dpo-release.json \
    --surface say_it_stronger \
    --base-model gpt-4.1-mini-2025-04-14 \
    --suffix willab-dpo-v1 \
    --poll
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config  # noqa: E402
from services.ml_dpo_release import (  # noqa: E402
    load_release_manifest,
    verify_release_file,
)
from services.ml_surface_contracts import contract_for_surface  # noqa: E402


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def _upload_file(client: httpx.Client, api_key: str, path: Path) -> str:
    with path.open("rb") as fh:
        files = {"file": (path.name, fh, "application/jsonl")}
        data = {"purpose": "fine-tune"}
        r = client.post(
            "https://api.openai.com/v1/files",
            headers=_headers(api_key),
            data=data,
            files=files,
            timeout=120,
        )
    if r.status_code >= 300:
        raise RuntimeError(f"File upload failed ({r.status_code}): {r.text}")
    body = r.json()
    file_id = body.get("id")
    if not file_id:
        raise RuntimeError(f"OpenAI upload response missing id: {body}")
    return str(file_id)


def _create_job(
    client: httpx.Client,
    api_key: str,
    *,
    base_model: str,
    training_file_id: str,
    validation_file_id: str | None,
    suffix: str | None,
    method_json: dict,
) -> dict:
    payload = {
        "model": base_model,
        "training_file": training_file_id,
        "method": method_json,
    }
    if validation_file_id:
        payload["validation_file"] = validation_file_id
    if suffix:
        payload["suffix"] = suffix
    r = client.post(
        "https://api.openai.com/v1/fine_tuning/jobs",
        headers={**_headers(api_key), "Content-Type": "application/json"},
        content=json.dumps(payload),
        timeout=120,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"Fine-tune create failed ({r.status_code}): {r.text}")
    return r.json()


def _get_job(client: httpx.Client, api_key: str, job_id: str) -> dict:
    r = client.get(
        f"https://api.openai.com/v1/fine_tuning/jobs/{job_id}",
        headers=_headers(api_key),
        timeout=60,
    )
    if r.status_code >= 300:
        raise RuntimeError(f"Get job failed ({r.status_code}): {r.text}")
    return r.json()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run OpenAI preference/DPO fine-tune job.")
    parser.add_argument("--surface", required=True, help="Canonical DPO surface")
    parser.add_argument("--train-file", required=True, help="Training JSONL path (preference format)")
    parser.add_argument("--val-file", required=True, help="Validation JSONL path")
    parser.add_argument("--manifest", required=True, help="Immutable DPO release manifest")
    parser.add_argument(
        "--base-model",
        default=os.getenv("OPENAI_DPO_BASE_MODEL", "gpt-4.1-mini-2025-04-14"),
        help="Base model id/version for preference FT",
    )
    parser.add_argument("--suffix", default=None, help="Optional fine-tuned model suffix")
    parser.add_argument(
        "--method-json",
        default='{"type":"dpo"}',
        help='Raw method JSON sent to OpenAI, default {"type":"dpo"}',
    )
    parser.add_argument("--poll", action="store_true", help="Poll job to terminal state")
    parser.add_argument("--poll-interval-sec", type=int, default=30, help="Polling interval")
    args = parser.parse_args()

    contract = contract_for_surface(args.surface)

    cfg = Config()
    api_key = (cfg.OPENAI_API_KEY or "").strip()
    if not api_key:
        raise SystemExit("OPENAI_API_KEY missing.")

    train_path = Path(args.train_file)
    if not train_path.exists():
        raise SystemExit(f"Training file not found: {train_path}")
    val_path = Path(args.val_file)
    if not val_path.exists():
        raise SystemExit(f"Validation file not found: {val_path}")
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        raise SystemExit(f"Manifest not found: {manifest_path}")
    try:
        manifest = load_release_manifest(
            manifest_path, expected_surface=contract.id,
        )
        verify_release_file(manifest, "train", train_path)
        verify_release_file(manifest, "validation", val_path)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Invalid immutable DPO release: {exc}")

    try:
        method_json = json.loads(args.method_json)
    except Exception as e:
        raise SystemExit(f"--method-json must be valid JSON: {e}")

    with httpx.Client() as client:
        train_file_id = _upload_file(client, api_key, train_path)
        val_file_id = _upload_file(client, api_key, val_path)
        job = _create_job(
            client,
            api_key,
            base_model=args.base_model,
            training_file_id=train_file_id,
            validation_file_id=val_file_id,
            suffix=args.suffix,
            method_json=method_json,
        )
        job_id = str(job.get("id") or "")
        print(
            json.dumps(
                {
                    "status": "submitted",
                    "surface": contract.id,
                    "dataset_release_id": manifest["dataset_release_id"],
                    "job_id": job_id,
                    "base_model": args.base_model,
                    "training_file_id": train_file_id,
                    "validation_file_id": val_file_id,
                    "suffix": args.suffix,
                },
                ensure_ascii=False,
            )
        )

        if not args.poll:
            return

        interval = max(5, int(args.poll_interval_sec))
        terminal = {"succeeded", "failed", "cancelled"}
        while True:
            current = _get_job(client, api_key, job_id)
            status = str(current.get("status") or "").lower()
            fine_tuned_model = current.get("fine_tuned_model")
            print(
                json.dumps(
                    {
                        "job_id": job_id,
                        "status": status,
                        "fine_tuned_model": fine_tuned_model,
                        "trained_tokens": current.get("trained_tokens"),
                    },
                    ensure_ascii=False,
                )
            )
            if status in terminal:
                if status == "succeeded":
                    if not fine_tuned_model:
                        raise SystemExit("Job succeeded but fine_tuned_model is missing.")
                    print(json.dumps({
                        "status": "candidate_ready",
                        "surface": contract.id,
                        "dataset_release_id": manifest["dataset_release_id"],
                        "model_id": fine_tuned_model,
                        "next": "run scripts/evaluate_dpo_candidate.py",
                    }, ensure_ascii=False))
                    return
                raise SystemExit(f"Fine-tune job ended with status={status}")
            time.sleep(interval)


if __name__ == "__main__":
    main()
