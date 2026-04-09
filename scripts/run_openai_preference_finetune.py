#!/usr/bin/env python3
"""
Start an OpenAI preference/DPO fine-tune job from JSONL files, optionally poll
to completion and auto-promote the resulting model for copilot inference.

Requires:
  - OPENAI_API_KEY in env
  - For --auto-promote: runtime_config table migration applied and SUPABASE service env configured

Examples:
  python3 scripts/run_openai_preference_finetune.py \
    --train-file exports/dpo-train.jsonl \
    --val-file exports/dpo-val.jsonl \
    --base-model gpt-4.1-mini-2025-04-14 \
    --suffix willab-dpo-v1 \
    --poll

  python3 scripts/run_openai_preference_finetune.py \
    --train-file exports/dpo-train.jsonl \
    --poll --auto-promote --promote-key openai_copilot_model
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
from services.db import db  # noqa: E402


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


def _auto_promote(model_id: str, key: str, actor: str) -> None:
    res = db.upsert_runtime_config(
        key=key,
        value=model_id,
        updated_by=actor,
        metadata={"source": "run_openai_preference_finetune.py"},
    )
    if not res:
        raise RuntimeError(
            "Failed to promote model (runtime_config unavailable). "
            "Run migrations/add_runtime_model_config.sql."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run OpenAI preference/DPO fine-tune job.")
    parser.add_argument("--train-file", required=True, help="Training JSONL path (preference format)")
    parser.add_argument("--val-file", default=None, help="Optional validation JSONL path")
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
    parser.add_argument("--auto-promote", action="store_true", help="Write resulting model id into runtime_config")
    parser.add_argument(
        "--promote-key",
        default="openai_copilot_model",
        help="runtime_config key to update on success",
    )
    parser.add_argument(
        "--promoted-by",
        default="ops:run_openai_preference_finetune.py",
        help="metadata updated_by value when promoting",
    )
    args = parser.parse_args()

    cfg = Config()
    api_key = (cfg.OPENAI_API_KEY or "").strip()
    if not api_key:
        raise SystemExit("OPENAI_API_KEY missing.")

    train_path = Path(args.train_file)
    if not train_path.exists():
        raise SystemExit(f"Training file not found: {train_path}")
    val_path = Path(args.val_file) if args.val_file else None
    if val_path and not val_path.exists():
        raise SystemExit(f"Validation file not found: {val_path}")

    try:
        method_json = json.loads(args.method_json)
    except Exception as e:
        raise SystemExit(f"--method-json must be valid JSON: {e}")

    with httpx.Client() as client:
        train_file_id = _upload_file(client, api_key, train_path)
        val_file_id = _upload_file(client, api_key, val_path) if val_path else None
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
                    if args.auto_promote:
                        if not fine_tuned_model:
                            raise SystemExit("Job succeeded but fine_tuned_model is missing.")
                        _auto_promote(str(fine_tuned_model), args.promote_key, args.promoted_by)
                        print(
                            json.dumps(
                                {
                                    "status": "promoted",
                                    "promote_key": args.promote_key,
                                    "model_id": fine_tuned_model,
                                },
                                ensure_ascii=False,
                            )
                        )
                    return
                raise SystemExit(f"Fine-tune job ended with status={status}")
            time.sleep(interval)


if __name__ == "__main__":
    main()
