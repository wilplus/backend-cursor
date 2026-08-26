#!/usr/bin/env python3
"""
Export admin_annotation_events to OpenAI preference (DPO) JSONL.

Each line:
{
  "input": {"messages": [...]},
  "preferred_output": [{"role":"assistant","content":"..."}],
  "non_preferred_output": [{"role":"assistant","content":"..."}]
}

Usage examples:
  python3 scripts/export_openai_preference_jsonl.py \
    --surface say_it_stronger --train-out dpo-train.jsonl \
    --val-out dpo-val.jsonl --manifest-out dpo-release.json
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.db import db  # noqa: E402
from services.ml_dpo_export import (  # noqa: E402
    DpoFilterConfig,
    build_dpo_examples,
    example_jsonl_line,
    parse_csv_set,
    split_train_val,
)
from services.ml_dpo_release import write_release_manifest  # noqa: E402
from services.ml_surface_contracts import contract_for_surface  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as fh:
        for row in rows:
            # Identifiers used for grouping/debug never enter an OpenAI file.
            out = {
                key: value for key, value in row.items()
                if key != "event_id" and not key.startswith("_")
            }
            fh.write(example_jsonl_line(out) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export OpenAI preference JSONL from annotation events.")
    parser.add_argument(
        "--surface", required=True,
        help=(
            "Canonical correction surface: say_it_stronger, "
            "moment_suggestion, ideal_text, or coach_comment_draft"
        ),
    )
    parser.add_argument("--train-out", required=True, help="Output train JSONL path")
    parser.add_argument("--val-out", required=True, help="Output validation JSONL path")
    parser.add_argument("--manifest-out", required=True, help="Immutable release manifest path")
    parser.add_argument("--val-ratio", type=float, default=0.1, help="Validation split ratio [0..0.5], default 0.1")
    parser.add_argument("--limit", type=int, default=20000, help="Max events to scan")
    parser.add_argument("--since", default=None, help="Only events with created_at > ISO timestamp")
    parser.add_argument("--reason-chips", default=None, help="Comma-separated reason_chip allowlist")
    parser.add_argument("--require-reason-chip", action="store_true", help="Skip rows with empty reason_chip")
    parser.add_argument("--min-preferred-chars", type=int, default=20, help="Minimum chars in coach_final_text")
    parser.add_argument("--min-non-preferred-chars", type=int, default=20, help="Minimum chars in ai_original_text")
    parser.add_argument("--max-similarity", type=float, default=0.985, help="Skip if texts are too similar (0..1)")
    parser.add_argument("--enrich-sessions", action="store_true", help="Include non-scored session context in prompt")
    args = parser.parse_args()

    contract = contract_for_surface(args.surface)

    cfg = DpoFilterConfig(
        surface=contract.id,
        min_preferred_chars=max(1, int(args.min_preferred_chars)),
        min_non_preferred_chars=max(1, int(args.min_non_preferred_chars)),
        max_similarity=max(0.0, min(1.0, float(args.max_similarity))),
        require_reason_chip=bool(args.require_reason_chip),
        reason_chips=parse_csv_set(args.reason_chips),
    )

    examples, stats = build_dpo_examples(
        db.client,
        limit=max(1, min(50000, int(args.limit))),
        since_iso=args.since,
        cfg=cfg,
        enrich_sessions=bool(args.enrich_sessions),
    )

    train_rows, val_rows = split_train_val(examples, val_ratio=float(args.val_ratio))
    if not train_rows or not val_rows:
        raise SystemExit(
            "A DPO release requires non-empty train and validation partitions. "
            "Collect more independent owners or adjust --val-ratio."
        )
    train_path = Path(args.train_out)
    val_path = Path(args.val_out)
    manifest_path = Path(args.manifest_out)
    collisions = [p for p in (train_path, val_path, manifest_path) if p.exists()]
    if collisions:
        raise SystemExit(
            "Immutable DPO release path already exists: "
            + ", ".join(str(p) for p in collisions)
        )
    _write_jsonl(train_path, train_rows)
    _write_jsonl(val_path, val_rows)
    manifest = write_release_manifest(
        manifest_path,
        surface=contract.id,
        train_path=train_path,
        val_path=val_path,
        train_examples=len(train_rows),
        val_examples=len(val_rows),
        train_groups=len({row["_split_group"] for row in train_rows}),
        val_groups=len({row["_split_group"] for row in val_rows}),
    )

    print(
        "DPO export done:"
        f" release={manifest['dataset_release_id']}"
        f" surface={contract.id}"
        f" scanned={stats.scanned}"
        f" kept={stats.kept}"
        f" skipped={stats.skipped}"
        f" train={len(train_rows)}"
        f" val={len(val_rows)}"
        f" train_out={train_path}"
        f" val_out={val_path}"
        f" manifest_out={manifest_path}"
    )
    if stats.skipped_by_reason:
        print(f"Skipped by reason: {stats.skipped_by_reason}")


if __name__ == "__main__":
    main()
