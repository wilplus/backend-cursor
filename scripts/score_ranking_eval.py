#!/usr/bin/env python3
"""Score the labeled ranking answers against the closed key — and apply the
RATIFIED decision rules (R0–R5, founder 2026-08-03, docs/RANKING-EVAL.md).

Joins the page's ranking_answers.csv to key.csv. No DB, no network;
power_score is IMPORTED from production for variant recomputes, never
re-implemented.

WHAT PRINTS, in order:
  R0 ceiling      rater self-agreement on the disguised repeats. Below 0.70
                  → every other verdict is GATED: refine the RUBRIC first.
  Agreement       per variant, overall + per band, twice: all cases, and
                  with none-fit-flagged (garbage) cases excluded. Actions
                  key off the CLEAN pass (ratified).
  R1–R3 duels     challenger vs shipped on the cases where they DIFFER —
                  clear_win needs ≥6 decided cases and a ≥2/3 win share.
                  R1 no_sentence_gate → demote completeness to tiebreak.
                  R2 debiased_coverage → fix the activation double-count.
                  R3 confidence_on → evidence to flip
                     VOICE_CONFIDENCE_RANKING_ENABLED (founder sign-off).
  R4              shipped_local − shipped_assembly gap (dedupe cost),
                  report-only.
  R5              shipped more than 20pts below the ceiling (clean pass) →
                  weight sweep + a FRESH confirmation batch.

This is a report, not a gate: exit 0 with valid inputs regardless of rates.
AC-9: internal — nothing here rides a user payload.

Usage:
  python scripts/score_ranking_eval.py \
      --answers ranking_answers.csv --key /tmp/ranking_eval/key.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.ranking_eval import (  # noqa: E402
    VARIANTS, agreement_report, parse_answers, parse_key_rows,
)

_RULE_ACTIONS = {
    "R1_no_sentence_gate": (
        "clear_win", "DEMOTE completeness from hard sort key to tiebreak "
        "(select_best_per_slide sort — one-line PR)"),
    "R2_debiased_coverage": (
        "clear_win", "FIX the activation input so slide coverage enters "
        "power_score once, not twice"),
    "R3_confidence_on": (
        "clear_win", "EVIDENCE to flip VOICE_CONFIDENCE_RANKING_ENABLED "
        "(founder sign-off — yours to give)"),
}


def _read_csv(path: str) -> list:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _print_variants(block: dict) -> None:
    for v in VARIANTS:
        r = block["variants"][v]
        o = r["overall"]
        rate = f"{o['agree']}/{o['n']} = {o['rate']}" if o["n"] else "n/a"
        print(f"  {v:>18}: {rate}")
        for band, br in r["by_band"].items():
            if br["n"]:
                print(f"  {'':>18}  {band}: "
                      f"{br['agree']}/{br['n']} = {br['rate']}")
        if r["uncomputable_cases"]:
            print(f"  {'':>18}  (uncomputable on "
                  f"{r['uncomputable_cases']} cases)")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--answers", required=True,
                    help="ranking_answers.csv downloaded from the page")
    ap.add_argument("--key", required=True, help="the closed key.csv")
    ap.add_argument("--json-out", default=None,
                    help="also write the full report as JSON")
    args = ap.parse_args()

    labels, none_fit, why, problems = parse_answers(_read_csv(args.answers))
    key = parse_key_rows(_read_csv(args.key))

    if problems:
        print(f"INVALID answer rows (excluded): {len(problems)}")
        for p in problems:
            print(f"  - {p}")
    if not labels:
        print("No valid answers — nothing to score.", file=sys.stderr)
        return 1

    report = agreement_report(labels, key, none_fit=none_fit)

    print("=== Best-per-slide ranking — human agreement "
          "(protocol: docs/RANKING-EVAL.md) ===")
    print(f"cases labeled={report['cases_labeled']} "
          f"unmatched={report['cases_unmatched']} "
          f"none_fit_flagged={report['none_fit_flagged']} "
          f"invalid_rows={len(problems)}")

    c = report["ceiling"]
    if c["pairs"]:
        print(f"\nR0 CEILING (self-agreement on {c['pairs']} disguised "
              f"repeats): {c['agree']}/{c['pairs']} = {c['rate']}")
        if report["r0_gated"]:
            print("  *** BELOW 0.70 — the rubric is noisier than the "
                  "machine differences we're judging. Per the ratified "
                  "protocol: refine the RUBRIC, convict nothing. All "
                  "verdicts below are stamped GATED. ***")
    else:
        print("\nR0 CEILING: no completed repeat pairs — label the "
              "end-of-run repeat cases to get your ceiling.")

    print("\nAgreement — ALL cases:")
    _print_variants(report["all_cases"])
    print("\nAgreement — none-fit-flagged cases EXCLUDED "
          "(actions key off these):")
    _print_variants(report["clean"])

    print("\nDuels vs shipped (differing cases only; "
          "clear verdict needs ≥6 decided and ≥2/3 share):")
    for rule, duel in report["duels"].items():
        print(f"  {rule}: differing={duel['differing']} "
              f"decided={duel['decided']} challenger_wins={duel['wins']} "
              f"shipped_wins={duel['losses']} → {duel['verdict']}")
        want, action = _RULE_ACTIONS[rule]
        if duel["verdict"] == want:
            print(f"      ACTION: {action}")
        elif duel["verdict"] == "insufficient_data":
            print("      ACTION: none — extend the set before deciding "
                  "(a coin flip is not a conclusion)")

    gap = report["r4_local_minus_assembly"]
    print(f"\nR4 dedupe cost (local − assembly agreement): {gap}")
    print(f"R5 floor breached (shipped > 20pts below ceiling, clean): "
          f"{report['r5_floor_breached']}"
          + (" → weight sweep + FRESH confirmation batch"
             if report["r5_floor_breached"] else ""))

    dis = report["clean"]["disagreements"]
    if dis:
        print("\nDisagreements vs shipped (clean pass) — "
              "RE-LISTEN TO THESE, the rates only say where to look:")
        for d in dis:
            note = f"  why: {why[d['case_id']]}" if d["case_id"] in why else ""
            print(f"  {d['case_id']} [{d['band']}] human={d['human']} "
                  f"shipped={d['shipped']}{note}")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
        print(f"\nfull report: {args.json_out}")

    print("\nInterpretation guardrails: N is small; a variant is better "
          "only when its duel says clear_win AND re-listening to the "
          "disagreements backs it up. If the export warned that stamped "
          "confidence coverage was 0, R3 was structurally unable to differ "
          "— that verdict describes nothing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
