#!/usr/bin/env python3
"""Offline replay — score the shadow direction model against the FROZEN holdout
(readiness rig #3).

The holdout (~20%, deterministic in snippet_id) is NEVER trained on, so this
agreement is the HONEST "is the machine ready to take over?" read — unlike the
in-train random split, whose test rows leak into training as the corpus grows.

Usage: python3 scripts/eval_direction_holdout.py
Prints agreement_overall + per-class + counts. READ-ONLY; no DB writes. Needs the
same Supabase env as the app and at least one trained shadow model (>=50 labels).
"""
from __future__ import annotations


def main() -> int:
    from services.learning_export import export_snippet_labels_dataset
    from services.learning_serve import predict_direction

    rows, summary = export_snippet_labels_dataset()
    holdout = [r for r in rows if r.get("is_holdout")]
    if not holdout:
        print("No holdout rows yet (corpus too small / no labels).")
        print(f"corpus total={summary.get('total')} holdout={summary.get('holdout')}")
        return 0

    n = 0
    agree = 0
    by_class: dict = {}  # truth label -> [agree, total]
    no_pred = 0
    for r in holdout:
        truth = r.get("label")
        pred = predict_direction(r.get("features"))
        if not pred or not pred.get("label"):
            no_pred += 1
            continue
        n += 1
        bucket = by_class.setdefault(truth, [0, 0])
        bucket[1] += 1
        if pred["label"] == truth:
            agree += 1
            bucket[0] += 1

    if n == 0:
        print("No predictions — the shadow model isn't trained yet "
              "(needs >=50 labels). Holdout is reserved and waiting.")
        print(f"holdout_rows={len(holdout)} no_prediction={no_pred}")
        return 0

    print("=== Direction model — HOLDOUT agreement (uncontaminated) ===")
    print(f"agreement_overall = {agree}/{n} = {agree / n:.3f}")
    for k, (a, t) in sorted(by_class.items(), key=lambda kv: str(kv[0])):
        print(f"  {k}: {a}/{t} = {a / t:.3f}" if t else f"  {k}: n/a")
    print(f"holdout_rows={len(holdout)} scored={n} no_prediction={no_pred} "
          f"corpus_total={summary.get('total')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
