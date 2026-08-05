#!/usr/bin/env python3
"""Corpus base rates for hedges / boosters / tics — the D20 unblock.

    python3 scripts/corpus_base_rates.py

That is the whole job. It reads transcripts already in the database, counts
markers with the three lexicons (services/verbal_markers, SPEC D21), and prints
r-hat, phi-hat and the resulting window per class.

WHAT THIS REPLACES. SPEC D20 estimates lexical rates with a Beta-Binomial
posterior whose prior comes from the corpus. Until this runs, that prior is
guessed — and the guess in circulation (1%) came from WRITTEN ACADEMIC PROSE,
the register where hedging is rarest. MICASE puts the single lexeme "just" at
5.25 per 1,000 words in academic SPEECH, already 3x the entire epistemic-verb
class in written articles. If our real rate is nearer 5% than 1%, the window
for a usable estimate falls from ~1,100 words to ~210 — the difference between
"whole talk only" and "a section".

So this is not a nice-to-have measurement. The number it prints decides
whether hedge density can ever be a span-level intervention at all.

NO LABELS REQUIRED. Counting needs a lexicon and text, nothing else. This is
the only piece of the verbal work not gated by the ~15 effective labels/week
(SPEC §1), which makes it the cheapest thing on the board.

READ-ONLY. Selects transcripts; writes nothing. Safe to run against prod.

OUTPUT IS INTERNAL (AC-9). Rates, phi and windows are machine-facing inputs to
the ranking blend. None of it is ever shown to a user.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from typing import Any

sys.path.insert(0, ".")

from services import verbal_markers as vm  # noqa: E402


def _fetch(limit: int) -> list[dict]:
    """Transcripts from wherever they live. Snippets first (that is where the
    text actually is), recordings as a fallback for sessions that predate the
    snippet pipeline."""
    from services.db import db

    rows: list[dict] = []
    # The physical table is `charisma_snippets`, NOT `snippets` — see
    # db.get_snippets_by_session. Getting this wrong returns PGRST205, which
    # reads like a stale schema cache and is not one.
    #
    # Snippets are grouped to SESSION grain below before any dispersion is
    # computed. Same rule as the drift layer: snippets inside a session are
    # not independent, and at snippet length the expected marker count per
    # document is well under 1, where the chi-square dispersion estimator
    # stops being trustworthy.
    by_session: dict[str, list[str]] = defaultdict(list)
    try:
        res = (db.client.table("charisma_snippets")
               .select("id, session_id, transcript")
               .not_.is_("transcript", "null")
               .limit(limit).execute())
        for r in (res.data or []):
            text = (r.get("transcript") or "").strip()
            if text:
                by_session[str(r.get("session_id") or r["id"])].append(text)
    except Exception as e:
        print(f"  ! charisma_snippets read failed: {e}", file=sys.stderr)

    for session_id, texts in by_session.items():
        rows.append({"unit_id": session_id, "group_id": session_id,
                     "source": "snippets", "text": " ".join(texts)})

    if len(rows) < limit:
        try:
            res = (db.client.table("recordings")
                   .select("id, user_id, transcription_text")
                   .not_.is_("transcription_text", "null")
                   .limit(limit - len(rows)).execute())
            for r in (res.data or []):
                text = (r.get("transcription_text") or "").strip()
                if text:
                    # group_id is the SPEAKER. Dispersion must be measured
                    # WITHIN speaker: pooling across speakers folds "some
                    # people hedge more" into a number meant to answer "how
                    # much text do I need from THIS person", and inflates it
                    # by however much speakers differ.
                    rows.append({"unit_id": r["id"],
                                 "group_id": r.get("user_id") or r["id"],
                                 "source": "recordings", "text": text})
        except Exception as e:
            print(f"  ! recordings read failed: {e}", file=sys.stderr)
    return rows


def analyse(rows: list[dict], *, strict_only: bool = True) -> dict:
    """Per-class r-hat, phi-hat, prior and the implied window."""
    key = "strict" if strict_only else "total"
    per_class_pairs: dict[str, list[tuple[int, int]]] = defaultdict(list)
    per_class_groups: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    term_totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # Per-SOURCE marks and words. charisma_snippets are SELECTED moments, not
    # a random sample of speech, so their marker rates can differ from
    # whole-recording transcripts by a lot. Pooling two populations with
    # different rates manufactures overdispersion by construction -- phi then
    # reports "these are two registers", not "this speaker is bursty".
    by_source: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    total_words = 0

    for row in rows:
        c = vm.count(row["text"])
        n_words = c["n_words"]
        if n_words <= 0:
            continue
        total_words += n_words
        src = str(row.get("source") or "?")
        by_source[src]["words"] += n_words
        for cls in vm.CLASSES:
            by_source[src][cls] += c[cls][key]
            per_class_pairs[cls].append((c[cls][key], n_words))
            per_class_groups[cls][str(row.get("group_id") or "?")].append(
                (c[cls][key], n_words))
            lex = vm.lexicon(cls)
            for term, n in c[cls]["terms"].items():
                # Only terms that were actually COUNTED in this mode. Showing
                # ambiguous terms under `counting = strict` made the top list
                # advertise words the totals excluded -- HEDGE led with
                # "about", "pretty", "sometimes", none of which were in the
                # strict 124.
                if strict_only and lex.get(term, False):
                    continue
                term_totals[cls][term] += n

    # HOW MANY DISTINCT SPEAKERS. The single most important number here and
    # the easiest to never ask. If this is 1 -- a founder recording tests --
    # then nothing below is a POPULATION rate; it is one person's rate, and
    # using it as a D20 prior would shrink every other user's posterior toward
    # the founder's speech. A corroborating signal: with many speakers at
    # different rates, pooled phi sits FAR above within-speaker phi. When the
    # two are close, the corpus has few speakers.
    speakers = {str(r.get("group_id")) for r in rows
                if str(r.get("source")) == "recordings"}

    out: dict[str, Any] = {
        "documents": len(rows),
        "distinct_speakers": len(speakers),
        "total_words": total_words,
        "counting": key,
        "sources": {
            src: {
                "words": d["words"],
                **{cls: {"marks": d[cls],
                         "rate_per_1000_words": (round(d[cls] / d["words"] * 1000, 3)
                                                 if d["words"] else None)}
                   for cls in vm.CLASSES},
            }
            for src, d in by_source.items()
        },
        "classes": {},
    }

    for cls in vm.CLASSES:
        pairs = per_class_pairs[cls]
        marks = sum(m for m, _ in pairs)
        words = sum(w for _, w in pairs)
        if words <= 0:
            out["classes"][cls] = {"error": "no words"}
            continue
        rate = marks / words
        phi = vm.dispersion(pairs)
        phi_within = vm.dispersion_within(per_class_groups[cls])
        exp_per_doc = vm.expected_marks_per_doc(pairs)
        # Pairs, not rates — the prior's mean must be the POOLED rate. See
        # verbal_markers.fit_prior; the unweighted version ran 3.6x high on
        # TIC against the single-speaker test corpus.
        prior = vm.fit_prior(pairs)
        out["classes"][cls] = {
            "marks": marks,
            "rate_per_word": round(rate, 6),
            "rate_per_1000_words": round(rate * 1000.0, 3),
            "phi_pooled": round(phi, 3) if phi is not None else None,
            "phi_within_speaker": (round(phi_within, 3)
                                   if phi_within is not None else None),
            "expected_marks_per_doc": (round(exp_per_doc, 3)
                                       if exp_per_doc is not None else None),
            "phi_trustworthy": bool(exp_per_doc and exp_per_doc >= 5.0),
            "prior_alpha_beta": ([round(prior[0], 4), round(prior[1], 4)]
                                 if prior else None),
            "window_words_phi1": vm.window_for_precision(rate),
            "window_words_phi_pooled": (
                vm.window_for_precision(rate, phi=phi) if phi else None),
            "window_words_phi_within": (
                vm.window_for_precision(rate, phi=phi_within)
                if phi_within else None),
            "top_terms": sorted(term_totals[cls].items(),
                                key=lambda kv: -kv[1])[:10],
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=5000,
                    help="max transcripts to read (default 5000)")
    ap.add_argument("--include-ambiguous", action="store_true",
                    help="count ambiguous terms too. This is an UPPER BOUND: "
                         "'like', 'so', 'right' and the modals cannot be "
                         "disambiguated without POS tagging. Run BOTH and "
                         "compare -- the gap is how much the ambiguity costs.")
    ap.add_argument("--source", choices=("recordings", "snippets"),
                    help="fit on ONE source only. charisma_snippets are "
                         "SELECTED moments, so their rates are not "
                         "representative of general speech; `--source "
                         "recordings` gives the unselected sample and is the "
                         "better basis for a D20 prior.")
    ap.add_argument("--json", action="store_true", help="machine-readable")
    args = ap.parse_args()

    rows = _fetch(args.limit)
    if args.source:
        rows = [r for r in rows if r.get("source") == args.source]
        print(f"\n  [--source {args.source}] — pooled numbers below are that "
              f"source only.")
    if not rows:
        print("No transcripts found. Nothing to measure.", file=sys.stderr)
        return 1

    result = analyse(rows, strict_only=not args.include_ambiguous)

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"\n  {result['documents']} transcripts, "
          f"{result['total_words']:,} words, counting = {result['counting']}")
    n_sp = result.get("distinct_speakers", 0)
    print(f"  {n_sp} distinct speaker(s) in the recordings source.")
    if n_sp <= 2:
        print("\n  *** NOT A POPULATION RATE ***")
        print("  With this few speakers these are ONE PERSON's rates. Using them")
        print("  as a D20 prior would shrink every other user's posterior toward")
        print("  this speaker. Corpus-relative thresholds built here are")
        print("  self-referential. The lexicons and the machinery are still")
        print("  validated; the NUMBERS are not a population.")
    print()

    srcs = result.get("sources") or {}
    if len(srcs) > 1:
        print("  BY SOURCE — check these agree before trusting any pooled number.")
        print(f"    {'source':12s} {'words':>9s}  "
              + "  ".join(f"{c:>9s}" for c in vm.CLASSES))
        for src, d in srcs.items():
            print(f"    {src:12s} {d['words']:9,}  "
                  + "  ".join(f"{d[c]['rate_per_1000_words'] or 0:8.2f}/k"
                              for c in vm.CLASSES))
        print("    charisma_snippets are SELECTED moments, not a random sample.")
        print("    Two sources at different rates make phi report 'two registers',")
        print("    not 'this speaker is bursty'.\n")
    for cls, d in result["classes"].items():
        if "error" in d:
            print(f"  {cls:8s}  {d['error']}")
            continue
        marks = d["marks"]
        print(f"  {cls.upper()}"
              + ("   *** TOO FEW MARKS TO ESTIMATE ANYTHING ***"
                 if marks < 30 else ""))
        print(f"    rate        {d['rate_per_1000_words']:.2f} per 1,000 words "
              f"({marks:,} marks)")
        print(f"    phi         pooled {d['phi_pooled']}  |  "
              f"WITHIN-SPEAKER {d['phi_within_speaker']}")
        print("                pooled phi mixes 'some people hedge more' into "
              "a number meant to\n"
              "                answer 'how much text from THIS person'. Size "
              "windows on the\n"
              "                within-speaker figure.")
        exp = d["expected_marks_per_doc"]
        flag = "OK" if d["phi_trustworthy"] else "UNRELIABLE — chi-square wants >= 5"
        print(f"    exp/doc     {exp}   [{flag}]")
        print(f"    window      {d['window_words_phi1']} at phi=1  |  "
              f"{d['window_words_phi_within']} at within-speaker phi  |  "
              f"{d['window_words_phi_pooled']} at pooled phi")
        print(f"    prior       {d['prior_alpha_beta']}  (alpha, beta for D20; "
              f"mean is the POOLED rate)")
        print(f"    top         {', '.join(f'{t}({n})' for t, n in d['top_terms'][:6])}")
        print()

    print("  READ THE exp/doc LINE FIRST. Below ~1 expected mark per document "
          "the chi-square\n  dispersion estimator is dominated by whether a "
          "document happened to contain a\n  marker at all, and every window "
          "derived from it is guesswork.\n\n"
          "  Then size on WITHIN-SPEAKER phi, not pooled. And treat any class "
          "under ~30 marks\n  as unmeasured rather than measured-as-small.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
