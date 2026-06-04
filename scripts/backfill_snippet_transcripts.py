#!/usr/bin/env python3
"""Backfill Whisper transcripts on stress_snippets / charisma_snippets.

Walks rows WHERE transcript IS NULL, downloads the MP3 from storage,
transcribes via services.snippet_transcription, and UPDATEs the row
with {transcript, language, words, transcribed_duration_ms}.

Idempotent — only touches rows where transcript IS NULL, so re-running
is safe. Whisper failures leave the row alone (will be picked up on
the next run).

Usage:
    python3 scripts/backfill_snippet_transcripts.py --dry-run
    python3 scripts/backfill_snippet_transcripts.py --table stress --limit 100
    python3 scripts/backfill_snippet_transcripts.py --table both --limit 500
    python3 scripts/backfill_snippet_transcripts.py --recording-id <uuid>
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import Iterable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config  # noqa: E402
from services.db import db  # noqa: E402
from services.snippet_transcription import transcribe_snippet_bytes  # noqa: E402

logger = logging.getLogger("backfill_snippet_transcripts")
config = Config()


def _select_untranscribed(
    table: str,
    *,
    recording_id: str | None,
    limit: int,
) -> list[dict]:
    q = (
        db.client.table(table)
        .select("id, recording_id, storage_path")
        .is_("transcript", "null")
        .order("created_at", desc=False)
        .limit(limit)
    )
    if recording_id:
        q = q.eq("recording_id", recording_id)
    res = q.execute()
    return res.data or []


def _transcribe_and_update(
    table: str,
    row: dict,
    *,
    dry_run: bool,
) -> bool:
    snippet_id = row["id"]
    storage_path = row.get("storage_path")
    if not storage_path:
        logger.warning("[%s] skip id=%s: missing storage_path", table, snippet_id)
        return False

    if dry_run:
        logger.info("[%s] DRY id=%s path=%s", table, snippet_id, storage_path)
        return True

    try:
        clip_bytes = db.download_audio(config.AUDIO_BUCKET_NAME, storage_path)
    except Exception as e:
        logger.warning("[%s] download failed id=%s err=%s", table, snippet_id, type(e).__name__)
        return False
    if not clip_bytes:
        logger.warning("[%s] empty bytes id=%s", table, snippet_id)
        return False

    tr = transcribe_snippet_bytes(clip_bytes, hint_filename=f"{snippet_id}.mp3")
    if not tr:
        # Whisper call already logged; skip this row, it'll get picked up next run.
        return False

    update_payload = {
        "transcript": tr.get("transcript"),
        "language": tr.get("language"),
        "words": tr.get("words"),
        "transcribed_duration_ms": tr.get("transcribed_duration_ms"),
    }
    try:
        db.client.table(table).update(update_payload).eq("id", snippet_id).execute()
    except Exception as e:
        logger.warning("[%s] update failed id=%s err=%s", table, snippet_id, type(e).__name__)
        return False

    logger.info(
        "[%s] OK id=%s lang=%s words=%d chars=%d",
        table, snippet_id, tr.get("language"),
        len(tr.get("words") or []),
        len((tr.get("transcript") or "")),
    )
    return True


def run_backfill(
    *,
    tables: Iterable[str],
    recording_id: str | None,
    limit: int,
    sleep_seconds: float,
    dry_run: bool,
) -> None:
    total_ok = 0
    total_skip = 0
    for table in tables:
        logger.info("=== %s ===", table)
        rows = _select_untranscribed(table, recording_id=recording_id, limit=limit)
        logger.info("[%s] candidates: %d", table, len(rows))
        for row in rows:
            ok = _transcribe_and_update(table, row, dry_run=dry_run)
            if ok:
                total_ok += 1
            else:
                total_skip += 1
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
    logger.info("done. ok=%d skip=%d dry_run=%s", total_ok, total_skip, dry_run)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--table",
        choices=["stress", "charisma", "both"],
        default="both",
        help="Which table(s) to backfill (default: both)",
    )
    parser.add_argument("--limit", type=int, default=200, help="Max rows per table per run (default: 200)")
    parser.add_argument("--recording-id", default=None, help="Restrict to one parent recording")
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.2,
        help="Pause between Whisper calls (seconds, default 0.2) — soft rate limit",
    )
    parser.add_argument("--dry-run", action="store_true", help="List candidates without transcribing")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.table == "stress":
        tables = ("stress_snippets",)
    elif args.table == "charisma":
        tables = ("charisma_snippets",)
    else:
        tables = ("stress_snippets", "charisma_snippets")

    run_backfill(
        tables=tables,
        recording_id=args.recording_id,
        limit=args.limit,
        sleep_seconds=args.sleep,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
