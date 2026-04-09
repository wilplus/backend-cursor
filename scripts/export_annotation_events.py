#!/usr/bin/env python3
"""
Export admin annotation events into JSONL training artifacts.

Delegates to services.annotation_export.run_annotation_export.

Usage:
  python3 scripts/export_annotation_events.py --dry-run
  python3 scripts/export_annotation_events.py --limit 5000
  python3 scripts/export_annotation_events.py --output-dir exports/annotation-events
  python3 scripts/export_annotation_events.py --upload-bucket my-bucket
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.annotation_export import result_to_dict, run_annotation_export  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Export admin annotation events to JSONL.")
    parser.add_argument("--limit", type=int, default=5000, help="Max events per run")
    parser.add_argument("--output-dir", type=str, default="exports/annotation-events", help="Local output directory")
    parser.add_argument("--upload-bucket", type=str, default=None, help="Supabase Storage bucket for JSONL upload")
    parser.add_argument("--upload-prefix", type=str, default="annotation-events", help="Object key prefix inside bucket")
    parser.add_argument("--created-by", type=str, default="ops:export_annotation_events.py", help="Run owner tag")
    parser.add_argument("--dry-run", action="store_true", help="Count only; do not write files or advance checkpoint")
    args = parser.parse_args()

    out_dir = None if args.dry_run else args.output_dir
    try:
        result = run_annotation_export(
            limit=args.limit,
            output_dir=out_dir,
            dry_run=bool(args.dry_run),
            created_by=args.created_by,
            upload_bucket=(args.upload_bucket or "").strip() or None,
            upload_prefix=args.upload_prefix,
        )
        print(result_to_dict(result))
    except Exception as exc:
        print({"status": "failed", "error": str(exc)}, file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
