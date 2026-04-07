#!/usr/bin/env python3
"""
Backfill v2_sessions.score_for_display / score_ready_at / score_components.

Usage:
  python3 scripts/backfill_score_for_display.py --dry-run
  python3 scripts/backfill_score_for_display.py --limit 500
  python3 scripts/backfill_score_for_display.py --user-id <uuid>
"""
import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.db import db  # noqa: E402
from services.utils import score_01_from_recording_row  # noqa: E402


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description="Backfill score_for_display on completed v2 sessions.")
    parser.add_argument("--user-id", type=str, default=None, help="Scope to one user_id")
    parser.add_argument("--limit", type=int, default=1000, help="Max rows to scan")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    args = parser.parse_args()

    query = (
        db.client.table("v2_sessions")
        .select("id, user_id, status, created_at, completed_at, score, score_for_display, score_components, recording_1_id")
        .eq("status", "completed")
        .is_("score_for_display", "null")
        .order("created_at", desc=False)
        .limit(max(1, int(args.limit)))
    )
    if args.user_id:
        query = query.eq("user_id", args.user_id)
    rows = query.execute().data or []
    if not rows:
        print("No rows need backfill.")
        return

    updated = 0
    skipped = 0
    for row in rows:
        session_id = row.get("id")
        user_id = row.get("user_id")
        score_01 = None
        try:
            if row.get("score") is not None:
                score_01 = float(row.get("score"))
        except (TypeError, ValueError):
            score_01 = None
        if score_01 is None or score_01 <= 0:
            rec_id = row.get("recording_1_id")
            if rec_id:
                rec = db.get_recording(str(rec_id), None)
                recovered = score_01_from_recording_row(rec or {})
                if recovered is not None:
                    score_01 = float(recovered)
        if score_01 is None:
            skipped += 1
            print(f"SKIP {session_id}: no score and no recoverable scoring_debug")
            continue

        score_01 = _clamp(float(score_01), 0.0, 1.0)
        score_100 = int(round(score_01 * 100.0))
        payload = {
            "score": score_01,
            "score_for_display": score_100,
            "score_ready_at": row.get("completed_at") or _now_iso(),
            "score_components": {
                "version": 1,
                "backfilled": True,
                "source": "score_or_scoring_debug",
                "canonical": {"score_for_display": score_100, "score_01": round(score_01, 4)},
            },
        }
        if args.dry_run:
            print(f"DRY {session_id}: score={score_01:.4f} score_for_display={score_100}")
            updated += 1
            continue
        db.v2_update_session(session_id, user_id, payload)
        updated += 1
        print(f"OK  {session_id}: score={score_01:.4f} score_for_display={score_100}")

    print(f"Done. updated={updated} skipped={skipped} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
