#!/usr/bin/env python3
"""
KPI sanity check for canonical v2_sessions.score.

Run from project root:
  python scripts/kpi_sanity_check.py

Uses same .env as the app. Works with 0, 1, or many completed homework sessions.
"""
import statistics
import sys
import os

# Run from project root so app modules resolve
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.db import db


def main():
    result = (
        db.client.table("v2_sessions")
        .select("id, user_id, created_at, score")
        .eq("status", "completed")
        .not_.is_("score", "null")
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    rows = result.data or []

    if not rows:
        print("No completed homework sessions with score found.")
        print("Run this again after more sessions are completed.")
        return

    print(f"Found {len(rows)} completed session(s).\n")
    print("Session          score")
    print("-" * 30)
    scores = []

    for r in rows:
        s = float(r.get("score") or 0)
        scores.append(s)
        sid = (r.get("id") or "")[:8]
        print(f"  {sid}..        {s:.2f}")

    print("-" * 30)
    n_sessions = len(scores)
    print("\n--- Score Snapshot ---")
    print("Samples:", n_sessions)
    print("Mean score:", round(statistics.mean(scores), 4))
    print("Median score:", round(statistics.median(scores), 4))
    print("Min score:", round(min(scores), 4))
    print("Max score:", round(max(scores), 4))

    print("\n(Re-run after more homeworks for a fuller picture.)")
    print("\nInterpretation: watch for stable or improving score distribution over time.")


if __name__ == "__main__":
    main()
