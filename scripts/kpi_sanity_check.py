#!/usr/bin/env python3
"""
KPI sanity check: compare old (simple average) vs new (improvement-weighted) performance_score_end.

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


def old_final(score1: float, score2: float) -> float:
    """Previous formula: simple average."""
    return (score1 + score2) / 2.0


def new_final(score1: float, score2: float) -> float:
    """New formula: improvement-weighted (0.3*score1 + 0.6*score2 + 0.3*improvement)."""
    improvement = max(0.0, score2 - score1)
    raw = 0.3 * score1 + 0.6 * score2 + 0.3 * improvement
    return max(0.0, min(1.0, raw))


def main():
    result = (
        db.client.table("v2_sessions")
        .select("id, user_id, created_at, performance_score_1, performance_score_2, performance_score_end")
        .eq("status", "completed")
        .not_.is_("performance_score_1", "null")
        .not_.is_("performance_score_2", "null")
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    rows = result.data or []

    if not rows:
        print("No completed homework sessions with score_1 and score_2 found.")
        print("Run this again after more sessions are completed.")
        return

    print(f"Found {len(rows)} completed session(s).\n")
    print("Session (old_end → new_end)  score_1  score_2   old     new    diff   note")
    print("-" * 75)

    old_list = []
    new_list = []
    diff_list = []
    deltas = []
    improving = 0
    decreasing = 0

    for r in rows:
        s1 = float(r.get("performance_score_1") or 0)
        s2 = float(r.get("performance_score_2") or 0)
        stored = r.get("performance_score_end")
        stored_f = float(stored) if stored is not None else None

        o = old_final(s1, s2)
        n = new_final(s1, s2)
        old_list.append(o)
        new_list.append(n)
        diff = n - o
        diff_list.append(diff)
        deltas.append(s2 - s1)

        if diff > 0.05:
            improving += 1
        elif diff < -0.05:
            decreasing += 1

        note = ""
        if stored_f is not None and abs(stored_f - o) < 0.001:
            note = "(stored=old)"
        elif stored_f is not None and abs(stored_f - n) < 0.001:
            note = "(stored=new)"

        sid = (r.get("id") or "")[:8]
        print(f"  {sid}..  {o:.2f} → {n:.2f}     {s1:.2f}    {s2:.2f}    {o:.2f}   {n:.2f}   {diff:+.2f}  {note}")

    print("-" * 75)

    n_sessions = len(rows)
    mean_old = statistics.mean(old_list)
    mean_new = statistics.mean(new_list)
    mean_diff = statistics.mean(diff_list)

    print("\n--- KPI Comparison ---")
    print("Samples:", n_sessions)
    print("Old mean:", round(mean_old, 4))
    print("New mean:", round(mean_new, 4))
    print("Mean shift (new - old):", round(mean_diff, 4))
    print("Sessions with new > old by >0.05:", improving)
    print("Sessions with new < old by >0.05:", decreasing)

    improvement_count = sum(1 for d in deltas if d > 0)
    regression_count = sum(1 for d in deltas if d < 0)
    flat_count = sum(1 for d in deltas if d == 0)
    improvement_rate = improvement_count / n_sessions if n_sessions else 0
    avg_delta = statistics.mean(deltas) if deltas else 0

    print("\n--- Improvement Diagnostics ---")
    print("Improvement rate (score2 > score1):", round(improvement_rate * 100, 2), "%")
    print("Regression rate (score2 < score1):", round(regression_count / n_sessions * 100, 2), "%")
    print("Flat rate (score2 == score1):", round(flat_count / n_sessions * 100, 2), "%")
    print("Average delta (score2 - score1):", round(avg_delta, 4))

    print("\n(Re-run after more homeworks for a fuller picture.)")
    print("\nInterpretation: improvement_rate 30-50% and avg_delta ~0 or positive = healthy.")
    print("Red flags: improvement_rate < 20%, avg_delta < -0.05.")


if __name__ == "__main__":
    main()
