#!/usr/bin/env python3
"""Score the labeled ranking sheet against the closed key.

Joins the rater's is_best marks (blind_sheet.csv, one per case) to key.csv
and prints agreement for the shipped blend and the named variants — no DB,
no network; power_score is IMPORTED from production for the variant
recomputes, never re-implemented.

  shipped_local     — the per-slide pick (select_best_per_slide on the case)
  shipped_assembly  — the pick after cross-slide dedupe (path dependence)
  no_sentence_gate  — pure score argmax (is the complete-sentence hard
                      gate helping or hurting?)
  debiased_coverage — activation with the slide-coverage half removed
                      (the overall_score double-count suspect)

READ THE BANDS, NOT JUST THE TOTAL. `clear` cases inflate any ranker;
`close` and `gate_decided` are where the decision was real. And the
disagreement list is the actual product insight — re-listen to those
cases before touching a weight.

This is a report, not a gate: exit 0 with valid inputs regardless of the
rates. AC-9: internal — nothing here rides a user payload.

Usage:
  python scripts/score_ranking_eval.py \
      --sheet /tmp/ranking_eval/blind_sheet.csv \
      --key   /tmp/ranking_eval/key.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.ranking_eval import (  # noqa: E402
    VARIANTS, agreement_report, parse_key_rows, parse_labels,
)


def _read_csv(path: str) -> list:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sheet", required=True,
                    help="the labeled blind_sheet.csv")
    ap.add_argument("--key", required=True, help="the closed key.csv")
    ap.add_argument("--json-out", default=None,
                    help="also write the full report as JSON")
    args = ap.parse_args()

    labels, problems = parse_labels(_read_csv(args.sheet))
    key = parse_key_rows(_read_csv(args.key))

    if problems:
        print(f"INVALID cases (excluded from every rate): {len(problems)}")
        for p in problems:
            print(f"  - {p}")
    if not labels:
        print("No validly labeled cases — nothing to score.",
              file=sys.stderr)
        return 1

    report = agreement_report(labels, key)

    print("=== Best-per-slide ranking — human agreement ===")
    print(f"cases labeled={report['cases_labeled']} "
          f"unmatched={report['cases_unmatched']} "
          f"invalid={len(problems)}")
    for v in VARIANTS:
        r = report["variants"][v]
        o = r["overall"]
        rate = f"{o['agree']}/{o['n']} = {o['rate']}" if o["n"] else "n/a"
        print(f"\n{v}: {rate}")
        for band, br in r["by_band"].items():
            if br["n"]:
                print(f"  {band:>12}: {br['agree']}/{br['n']} = {br['rate']}")
        if r["uncomputable_cases"]:
            print(f"  (uncomputable on {r['uncomputable_cases']} cases)")

    if report["disagreements"]:
        print("\nDisagreements vs shipped_local — RE-LISTEN TO THESE:")
        for d in report["disagreements"]:
            print(f"  {d['case_id']} [{d['band']}] "
                  f"human={d['human']} shipped={d['shipped']}")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
        print(f"\nfull report: {args.json_out}")

    print("\nInterpretation guardrails: N is small — treat a variant as "
          "better only when it wins clearly and the disagreement listens "
          "back it up. If direction/voice_confidence were 0 across the "
          "draw (the export printed this), these rates describe the "
          "CONTENT-ONLY blend, not L2 as designed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
