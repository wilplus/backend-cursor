#!/usr/bin/env python3
"""
Export stress snippet labels to JSONL for model training.

This script exports rows from public.stress_snippets with optional filters.
Each line includes snippet metadata, label, and storage pointer.

Usage:
  python3 scripts/export_stress_snippets_dataset.py -o exports/stress-labeled.jsonl
  python3 scripts/export_stress_snippets_dataset.py -o exports/stress-student.jsonl --source-type student
  python3 scripts/export_stress_snippets_dataset.py -o exports/stress-all.jsonl --include-unlabeled
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config  # noqa: E402
from services.db import db  # noqa: E402

config = Config()


def _fetch_snippets(limit: int, source_type: str | None) -> list[dict]:
    rows: list[dict] = []
    page = 1000
    offset = 0
    while len(rows) < limit:
        query = (
            db.client.table("stress_snippets")
            .select("*")
            .order("created_at", desc=False)
            .range(offset, offset + page - 1)
        )
        if source_type:
            query = query.eq("source_type", source_type)
        result = query.execute()
        batch = result.data or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return rows[:limit]


def _signed_or_public_url(storage_path: str | None) -> str | None:
    path = (storage_path or "").strip()
    if not path:
        return None
    try:
        signed = db.create_signed_url(config.AUDIO_BUCKET_NAME, path, config.SIGNED_URL_EXPIRY_SECONDS)
        if signed:
            return signed
    except Exception:
        pass
    supabase_url = (config.SUPABASE_URL or "").rstrip("/")
    if not supabase_url:
        return None
    return f"{supabase_url}/storage/v1/object/public/{config.AUDIO_BUCKET_NAME}/{path}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export stress snippet dataset JSONL.")
    parser.add_argument("-o", "--output", required=True, help="Output JSONL path")
    parser.add_argument("--limit", type=int, default=100000, help="Max rows to export")
    parser.add_argument(
        "--source-type",
        choices=["all", "student", "internet"],
        default="all",
        help="Filter by snippet source",
    )
    parser.add_argument(
        "--include-unlabeled",
        action="store_true",
        help="Include snippets without coach label (default exports labeled only)",
    )
    parser.add_argument(
        "--with-audio-url",
        action="store_true",
        help="Include ephemeral signed/public audio_url per snippet",
    )
    args = parser.parse_args()

    source_type = None if args.source_type == "all" else args.source_type
    rows = _fetch_snippets(limit=max(1, int(args.limit)), source_type=source_type)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            label = row.get("coach_label")
            if not args.include_unlabeled and label not in ("stress", "no_stress"):
                skipped += 1
                continue
            item = {
                "snippet_id": row.get("id"),
                "recording_id": row.get("recording_id"),
                "session_id": row.get("session_id"),
                "user_id": row.get("user_id"),
                "source_type": row.get("source_type"),
                "scenario": row.get("scenario"),
                "start_ms": row.get("start_ms"),
                "end_ms": row.get("end_ms"),
                "duration_ms": row.get("duration_ms"),
                "storage_path": row.get("storage_path"),
                "coach_label": label,
                "coach_label_notes": row.get("coach_label_notes"),
                "classifier_stress_probability": row.get("classifier_stress_probability"),
                "classifier_confidence": row.get("classifier_confidence"),
                "selection_score": row.get("selection_score"),
                "features": row.get("features") or {},
                "transcript_excerpt": row.get("transcript_excerpt"),
                "created_at": row.get("created_at"),
                "labeled_at": row.get("labeled_at"),
            }
            if args.with_audio_url:
                item["audio_url"] = _signed_or_public_url(item.get("storage_path"))
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
            written += 1

    print(
        f"Stress dataset export done: scanned={len(rows)} written={written} skipped={skipped} "
        f"source_type={args.source_type} output={out_path}"
    )


if __name__ == "__main__":
    main()
