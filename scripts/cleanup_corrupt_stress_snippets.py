#!/usr/bin/env python3
"""
Remove stress snippets whose audio object is missing or too small to be a
valid MP3 (i.e. "corrupted" — will not play in the labeling UI).

Strategy:
  1. Page through public.stress_snippets.
  2. For each row, mint a short signed URL for its storage_path and HEAD it.
  3. Treat the snippet as corrupted if:
       - storage_path is empty, OR
       - HEAD fails, returns non-2xx, OR
       - Content-Length is below --min-bytes (default 2048 — a real 10s clip
         is ~80KB; the broken ones in prod were 44 bytes).
  4. Delete the storage object (best effort) and the DB row.

Safe by default: runs in --dry-run mode unless --apply is passed.

Usage:
  # see what would be deleted
  python3 scripts/cleanup_corrupt_stress_snippets.py

  # actually delete
  python3 scripts/cleanup_corrupt_stress_snippets.py --apply

  # only one recording
  python3 scripts/cleanup_corrupt_stress_snippets.py --recording-id <uuid> --apply
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Optional

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config  # noqa: E402
from services.db import db  # noqa: E402

config = Config()


def _page_snippets(recording_id: Optional[str], page_size: int = 500):
    offset = 0
    while True:
        query = (
            db.client.table("stress_snippets")
            .select("id,recording_id,storage_path,source_type,coach_label")
            .order("created_at", desc=False)
            .range(offset, offset + page_size - 1)
        )
        if recording_id:
            query = query.eq("recording_id", recording_id)
        result = query.execute()
        rows = result.data or []
        if not rows:
            return
        for r in rows:
            yield r
        if len(rows) < page_size:
            return
        offset += page_size


def _head(url: str, timeout: float = 10.0) -> tuple[int, int]:
    """Return (status_code, content_length). content_length is -1 if unknown."""
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException:
        return (0, -1)
    length = -1
    try:
        length = int(resp.headers.get("content-length") or -1)
    except (TypeError, ValueError):
        length = -1
    return (resp.status_code, length)


def _delete_object(bucket: str, path: str) -> bool:
    try:
        db.client.storage.from_(bucket).remove([path])
        return True
    except Exception as e:
        print(f"    ! storage remove failed: {e}")
        return False


def _delete_row(snippet_id: str) -> bool:
    try:
        db.client.table("stress_snippets").delete().eq("id", snippet_id).execute()
        return True
    except Exception as e:
        print(f"    ! db delete failed: {e}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually delete (default is dry-run).")
    parser.add_argument("--min-bytes", type=int, default=2048,
                        help="Objects smaller than this are considered corrupted (default 2048).")
    parser.add_argument("--recording-id", type=str, default=None,
                        help="Limit to snippets for one recording.")
    parser.add_argument("--skip-labeled", action="store_true",
                        help="Do not touch snippets that already have a coach_label.")
    parser.add_argument("--keep-object", action="store_true",
                        help="Delete the DB row but leave the storage object in place.")
    args = parser.parse_args()

    bucket = config.AUDIO_BUCKET_NAME
    print(f"bucket: {bucket}")
    print(f"mode:   {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"min:    {args.min_bytes} bytes")
    if args.recording_id:
        print(f"filter: recording_id={args.recording_id}")
    if args.skip_labeled:
        print("filter: skip-labeled")
    print()

    total = 0
    corrupt = 0
    deleted_rows = 0
    deleted_objs = 0
    skipped_labeled = 0

    for row in _page_snippets(args.recording_id):
        total += 1
        snippet_id = row.get("id")
        storage_path = (row.get("storage_path") or "").strip()
        recording_id = row.get("recording_id")
        has_label = row.get("coach_label") is not None

        if args.skip_labeled and has_label:
            skipped_labeled += 1
            continue

        reason = None
        status = None
        length = None

        if not storage_path:
            reason = "no storage_path"
        else:
            try:
                signed = db.create_signed_url(bucket, storage_path, 120)
            except Exception as e:
                signed = None
                reason = f"sign failed: {e}"
            if signed and not reason:
                status, length = _head(signed)
                if status == 0:
                    reason = "HEAD network error"
                elif status < 200 or status >= 300:
                    reason = f"HEAD {status}"
                elif length >= 0 and length < args.min_bytes:
                    reason = f"content-length={length} < {args.min_bytes}"

        if not reason:
            continue

        corrupt += 1
        label_tag = f" [labeled={row.get('coach_label')}]" if has_label else ""
        print(f"- {snippet_id}  rec={recording_id}  {reason}{label_tag}")
        print(f"    path: {storage_path}")

        if not args.apply:
            continue

        if storage_path and not args.keep_object:
            if _delete_object(bucket, storage_path):
                deleted_objs += 1
        if _delete_row(snippet_id):
            deleted_rows += 1

        # gentle pacing
        time.sleep(0.02)

    print()
    print(f"scanned:          {total}")
    print(f"skipped labeled:  {skipped_labeled}")
    print(f"corrupt:          {corrupt}")
    if args.apply:
        print(f"rows deleted:     {deleted_rows}")
        print(f"objects deleted:  {deleted_objs}")
    else:
        print("dry-run — pass --apply to delete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
