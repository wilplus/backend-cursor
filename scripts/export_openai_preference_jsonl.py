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
  python3 scripts/export_openai_preference_jsonl.py --train-out dpo-train.jsonl
  python3 scripts/export_openai_preference_jsonl.py --train-out dpo-train.jsonl --val-out dpo-val.jsonl --val-ratio 0.1
  python3 scripts/export_openai_preference_jsonl.py --train-out dpo-train.jsonl --fields email_draft,task_draft,script_draft --enrich-sessions
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


def _write_jsonl(path: Path, rows: list[dict], *, strip_event_id: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            out = dict(row)
            if strip_event_id:
                out.pop("event_id", None)
            fh.write(example_jsonl_line(out) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export OpenAI preference JSONL from annotation events.")
    parser.add_argument("--train-out", required=True, help="Output train JSONL path")
    parser.add_argument("--val-out", default=None, help="Optional output validation JSONL path")
    parser.add_argument("--val-ratio", type=float, default=0.1, help="Validation split ratio [0..0.5], default 0.1")
    parser.add_argument("--limit", type=int, default=20000, help="Max events to scan")
    parser.add_argument("--since", default=None, help="Only events with created_at > ISO timestamp")
    parser.add_argument("--fields", default=None, help="Comma-separated field_name allowlist")
    parser.add_argument("--reason-chips", default=None, help="Comma-separated reason_chip allowlist")
    parser.add_argument("--require-reason-chip", action="store_true", help="Skip rows with empty reason_chip")
    parser.add_argument("--min-preferred-chars", type=int, default=20, help="Minimum chars in coach_final_text")
    parser.add_argument("--min-non-preferred-chars", type=int, default=20, help="Minimum chars in ai_original_text")
    parser.add_argument("--max-similarity", type=float, default=0.985, help="Skip if texts are too similar (0..1)")
    parser.add_argument("--enrich-sessions", action="store_true", help="Include session context_short/score in prompt")
    parser.add_argument("--keep-event-id", action="store_true", help="Keep internal event_id key in JSONL (debug only)")
    args = parser.parse_args()

    cfg = DpoFilterConfig(
        min_preferred_chars=max(1, int(args.min_preferred_chars)),
        min_non_preferred_chars=max(1, int(args.min_non_preferred_chars)),
        max_similarity=max(0.0, min(1.0, float(args.max_similarity))),
        require_reason_chip=bool(args.require_reason_chip),
        field_names=parse_csv_set(args.fields),
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
    train_path = Path(args.train_out)
    _write_jsonl(train_path, train_rows, strip_event_id=not args.keep_event_id)

    val_path = None
    if args.val_out:
        val_path = Path(args.val_out)
        _write_jsonl(val_path, val_rows, strip_event_id=not args.keep_event_id)

    print(
        "DPO export done:"
        f" scanned={stats.scanned}"
        f" kept={stats.kept}"
        f" skipped={stats.skipped}"
        f" train={len(train_rows)}"
        f" val={len(val_rows)}"
        f" train_out={train_path}"
        f" val_out={val_path}"
    )
    if stats.skipped_by_reason:
        print(f"Skipped by reason: {stats.skipped_by_reason}")


if __name__ == "__main__":
    main()
