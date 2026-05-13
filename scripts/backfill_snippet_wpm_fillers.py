#!/usr/bin/env python3
"""Persist transcript-derived WPM + filler_count on snippets that have
``transcript`` and ``duration_ms`` but never had the metrics pipeline
populate ``wpm`` / ``fillers`` columns.

Pairs with commits 87a9894 (KPI refuses to score on missing inputs) +
02b4872 (session aggregator falls back to transcript-derived values).
This script caches those values on disk so future "Compute Metrics"
clicks don't recompute them every time.

Idempotent — it only touches rows where the target column is currently
NULL, so re-running is safe. Restricted by --user-id / --session-id /
--limit for incremental runs.

Usage:
    python3 scripts/backfill_snippet_wpm_fillers.py --dry-run
    python3 scripts/backfill_snippet_wpm_fillers.py --limit 500
    python3 scripts/backfill_snippet_wpm_fillers.py --user-id <uuid>
    python3 scripts/backfill_snippet_wpm_fillers.py --session-id <uuid>
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.db import db  # noqa: E402
from utils.metrics import compute_wpm, count_fillers  # noqa: E402


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _select_candidates(*, user_id: str | None, session_id: str | None, limit: int) -> list[dict]:
    """Pull rows that need at least one of wpm/fillers backfilled.

    PostgREST can't express "wpm IS NULL OR fillers IS NULL" cleanly
    via .or_ in some SDK versions, so we just select the candidate
    set (rows with transcript + duration_ms) and let the worker
    decide per-row which column it actually writes.
    """
    q = (
        db.client.table("charisma_snippets")
        .select("id, user_id, session_id, transcript, duration_ms, wpm, fillers")
        .not_.is_("transcript", "null")
        .not_.is_("duration_ms", "null")
        .order("created_at", desc=False)
        .limit(max(1, int(limit)))
    )
    if user_id:
        q = q.eq("user_id", user_id)
    if session_id:
        q = q.eq("session_id", session_id)
    return q.execute().data or []


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill wpm + fillers on charisma_snippets rows with a "
            "transcript + duration but no metrics-pipeline output."
        )
    )
    parser.add_argument("--user-id", type=str, default=None,
                        help="Scope to one user_id")
    parser.add_argument("--session-id", type=str, default=None,
                        help="Scope to one session_id")
    parser.add_argument("--limit", type=int, default=1000,
                        help="Max rows to scan (default 1000)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print actions without writing")
    args = parser.parse_args()

    rows = _select_candidates(
        user_id=args.user_id,
        session_id=args.session_id,
        limit=args.limit,
    )
    if not rows:
        print("No candidate snippets found.")
        return 0

    scanned = 0
    updated_wpm = 0
    updated_fillers = 0
    skipped_already_set = 0
    skipped_too_short = 0
    errors = 0

    for row in rows:
        scanned += 1
        transcript = (row.get("transcript") or "").strip()
        duration_ms = row.get("duration_ms")
        if not transcript or not duration_ms:
            skipped_too_short += 1
            continue

        wants_wpm = row.get("wpm") is None
        wants_fillers = row.get("fillers") is None
        if not wants_wpm and not wants_fillers:
            skipped_already_set += 1
            continue

        patch: dict = {}
        if wants_wpm:
            try:
                wpm = compute_wpm(transcript, float(duration_ms) / 1000.0)
                if wpm and wpm > 0:
                    patch["wpm"] = wpm
            except Exception as e:
                print(f"[error] wpm compute failed snippet={row.get('id')}: {e}")
        if wants_fillers:
            try:
                fc = count_fillers(transcript)
                patch["fillers"] = int(fc.get("total") or 0)
            except Exception as e:
                print(f"[error] fillers compute failed snippet={row.get('id')}: {e}")

        if not patch:
            errors += 1
            continue

        patch["updated_at"] = _now_iso()

        if args.dry_run:
            print(
                f"[dry-run] would update snippet={row.get('id')} "
                f"wpm={patch.get('wpm')} fillers={patch.get('fillers')}"
            )
        else:
            try:
                db.client.table("charisma_snippets").update(patch).eq(
                    "id", row.get("id")
                ).execute()
            except Exception as e:
                print(f"[error] update failed snippet={row.get('id')}: {e}")
                errors += 1
                continue

        if "wpm" in patch:
            updated_wpm += 1
        if "fillers" in patch:
            updated_fillers += 1

    print(
        f"Scanned {scanned} / Updated wpm={updated_wpm} fillers={updated_fillers} "
        f"/ Already-set {skipped_already_set} / Skipped-empty {skipped_too_short} "
        f"/ Errors {errors}"
        + ("  [DRY-RUN]" if args.dry_run else "")
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
