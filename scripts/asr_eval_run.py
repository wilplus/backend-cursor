#!/usr/bin/env python3
"""Run the ASR bake-off over a golden set.

    # free, no API calls — what can this corpus actually measure?
    python scripts/asr_eval_run.py --manifest evals/asr/manifest.json --check

    # the sweep
    python scripts/asr_eval_run.py \
        --manifest evals/asr/manifest.json \
        --providers openai:whisper-1,faster-whisper,whisperx \
        --out /tmp/asr-eval.json

    # produce TIER 2 reference word times first (needs whisperx + reference_text)
    python scripts/asr_eval_run.py --manifest evals/asr/manifest.json --align

Always run --check before spending money: it says which numbers the corpus
can support, and refuses to start a paid sweep whose headline metric would
come back blank.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from asr_eval import corpus as corpus_mod          # noqa: E402
from asr_eval import metrics, providers, report    # noqa: E402

DEFAULT_BASELINE = "openai:whisper-1"


def _print_readiness(r: dict) -> None:
    print("=" * 78)
    print("CORPUS READINESS")
    print("=" * 78)
    print(f"  takes                      {r['takes']}")
    print(f"  with audio on disk         {r['with_audio']}")
    print(f"  with reference_text        {r['with_reference_text']}  → WER")
    print(f"  with deck timeline         {r['with_deck_timeline']}  → SLIDE-BUCKET (the metric)")
    print(f"  with reference word times  {r['with_reference_word_times']}  → timestamp ACCURACY (tier 2)")
    print(f"  strata                     {r['strata']}")
    for b in r["blockers"]:
        print(f"  BLOCKER  {b}")
    for w in r["warnings"]:
        print(f"  warning  {w}")
    print(f"  ready: {r['ready']}")


def _align(c: dict) -> int:
    """Produce tier-2 reference word times next to each take's audio."""
    made = skipped = 0
    for t in c["takes"]:
        if not t["audio_exists"] or not t["reference_text"]:
            skipped += 1
            continue
        out_path = os.path.join(c["root"], f"{t['take_id']}.words.json")
        if os.path.exists(out_path):
            print(f"  skip {t['take_id']} (already aligned)")
            skipped += 1
            continue
        res = providers.transcribe(
            "forced-align-reference", t["audio_path"],
            language=t["language"], reference_text=t["reference_text"])
        if res.get("unavailable") or not res.get("words"):
            print(f"  FAIL {t['take_id']}: {res.get('unavailable') or 'no words'}")
            skipped += 1
            continue
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(res["words"], fh, ensure_ascii=False, indent=1)
        print(f"  ok   {t['take_id']} → {os.path.basename(out_path)} "
              f"({len(res['words'])} words)")
        made += 1
    print(f"\naligned {made}, skipped {skipped}. "
          f"Add \"reference_words\": \"<take_id>.words.json\" to each manifest "
          f"entry to activate tier-2 timing.")
    return 0 if made else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--providers", default=DEFAULT_BASELINE)
    ap.add_argument("--baseline", default=DEFAULT_BASELINE,
                    help="incumbent to compare against (default whisper-1)")
    ap.add_argument("--check", action="store_true",
                    help="report corpus readiness and exit (no API calls)")
    ap.add_argument("--align", action="store_true",
                    help="forced-align reference_text to produce tier-2 word times")
    ap.add_argument("--strata", default="accent")
    ap.add_argument("--out", default=None)
    ap.add_argument("--force", action="store_true",
                    help="run even when readiness reports blockers")
    args = ap.parse_args(argv)

    try:
        c = corpus_mod.load_manifest(args.manifest)
    except corpus_mod.CorpusError as e:
        print(f"manifest error: {e}", file=sys.stderr)
        return 2

    ready = corpus_mod.readiness(c)
    _print_readiness(ready)
    if args.check:
        return 0 if ready["ready"] else 1
    if args.align:
        return _align(c)
    if not ready["ready"] and not args.force:
        print("\nrefusing to run a paid sweep with blockers above. "
              "Fix them, or pass --force.", file=sys.stderr)
        return 1

    names = [p.strip() for p in args.providers.split(",") if p.strip()]
    unknown = [p for p in names if p not in providers.available()]
    if unknown:
        print(f"unknown provider(s) {unknown}; have {providers.available()}",
              file=sys.stderr)
        return 2

    # Baseline first — its words are the tier-3 timing reference for the rest.
    if args.baseline in names:
        names = [args.baseline] + [p for p in names if p != args.baseline]

    raw: dict = {}
    for p in names:
        print(f"\n── running {p} over {len(c['takes'])} take(s)")
        raw[p] = {}
        for t in c["takes"]:
            if not t["audio_exists"]:
                print(f"   skip {t['take_id']} (audio missing)")
                continue
            res = providers.transcribe(p, t["audio_path"],
                                       language=t["language"],
                                       vocabulary=t["vocabulary"])
            raw[p][t["take_id"]] = res
            note = res.get("unavailable") or (
                f"{len(res.get('words') or [])} words, "
                f"{res.get('wall_seconds')}s")
            print(f"   {t['take_id']}: {note}")

    summaries, gates, per_take = [], [], {}
    base_rows = raw.get(args.baseline) or {}
    for p in names:
        rows = []
        for t in c["takes"]:
            res = (raw.get(p) or {}).get(t["take_id"])
            if res is None:
                continue
            m = metrics.evaluate_take(
                reference_text=t["reference_text"],
                candidate=res,
                baseline=base_rows.get(t["take_id"]) if p != args.baseline else None,
                slide_advances=t["slide_advances"],
                slides=t["slides"],
                language=t["language"],
                reference_words=t["reference_words"],
            )
            rows.append({"take": t, "result": m})
        per_take[p] = rows
        summaries.append(report.summarize(p, rows))

    base_summary = next((s for s in summaries
                         if s["provider"] == args.baseline), None)
    # The incumbent is the reference, not a candidate — gating it against
    # itself would print a meaningless verdict on the anchor row.
    for s in summaries:
        if s["provider"] != args.baseline:
            gates.append(report.gate(s, baseline=base_summary))

    print()
    print(report.render(summaries, gates, baseline=args.baseline))

    # Per-stratum, because a corpus average hides the accent case.
    print("\n" + "-" * 78)
    print(f"BY {args.strata.upper()}")
    for p in names:
        st = corpus_mod.strata_report(per_take[p], key=args.strata)
        print(f"\n  {p}")
        for name, grp in st.items():
            sub = report.summarize(p, grp["rows"])
            flag = "" if grp["trustworthy"] else "  (too few takes — noise)"
            bd = (sub["slide_bucket"] or {}).get("disagreement_rate")
            wv = (sub["wer_verbatim"] or {}).get("wer_micro")
            print(f"    {name:<28} n={grp['takes']:<3} "
                  f"bucket={report._pct(bd, 3):<9} "
                  f"wer={report._pct(wv):<8}{flag}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump({
                "manifest": os.path.abspath(args.manifest),
                "readiness": ready,
                "summaries": summaries,
                "gates": gates,
                "per_take": {p: [{"take_id": r["take"]["take_id"],
                                  "accent": r["take"]["accent"],
                                  "result": r["result"]}
                                 for r in rows]
                             for p, rows in per_take.items()},
            }, fh, ensure_ascii=False, indent=2, default=str)
        print(f"\nwrote {args.out}")

    # Exit non-zero if any non-baseline candidate failed its gate, so this
    # can gate CI later without rewriting the runner.
    bad = [g for g in gates
           if g["provider"] != args.baseline and g["verdict"] != "PASS"]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
