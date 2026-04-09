#!/usr/bin/env python3
"""
Promote (or rollback) inference model by updating runtime_config.

Example:
  python3 scripts/promote_openai_model.py --model-id ft:gpt-4.1-mini:org:proj:abc123 \
    --key openai_copilot_model --updated-by artur
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.db import db  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Promote OpenAI model by writing runtime_config key/value.")
    parser.add_argument("--model-id", required=True, help="Model id to use at inference (e.g. ft:...)")
    parser.add_argument("--key", default="openai_copilot_model", help="runtime_config key")
    parser.add_argument("--updated-by", default="ops:promote_openai_model.py", help="updated_by marker")
    args = parser.parse_args()

    model_id = (args.model_id or "").strip()
    if not model_id:
        raise SystemExit("--model-id is required.")

    row = db.upsert_runtime_config(
        key=str(args.key).strip(),
        value=model_id,
        updated_by=str(args.updated_by).strip() or None,
        metadata={"source": "manual_promotion"},
    )
    if not row:
        raise SystemExit(
            "Failed to update runtime_config. Run migrations/add_runtime_model_config.sql first."
        )
    print({"status": "ok", "key": args.key, "model_id": model_id})


if __name__ == "__main__":
    main()
