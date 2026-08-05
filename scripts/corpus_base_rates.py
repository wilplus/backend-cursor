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
                     "text": " ".join(texts)})

    if len(rows) < limit:
        try:
            res = (db.client.table("recordings")
                   .select("id, transcription_text")
                   .not_.is_("transcription_text", "null")
                   .limit(limit - len(rows)).execute())
            for r in (res.data or []):
                text = (r.get("transcription_text") or "").strip()
                if text:
                    rows.append({"unit_id": r["id"], "group_id": r["id"],
                                 "text": text})
        except Exception as e:
            print(f"  ! recordings read failed: {e}", file=sys.stderr)
    return rows


def analyse(rows: list[dict], *, strict_only: bool = True) -> dict:
    """Per-class r-hat, phi-hat, prior and the implied window."""
    key = "strict" if strict_only else "total"
    per_class_pairs: dict[str, list[tuple[int, int]]] = defaultdict(list)
    term_totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    total_words = 0

    for row in rows:
        c = vm.count(row["text"])
        n_words = c["n_words"]
        if n_words <= 0:
            continue
        total_words += n_words
        for cls in vm.CLASSES:
            per_class_pairs[cls].append((c[cls][key], n_words))
            for term, n in c[cls]["terms"].items():
                term_totals[cls][term] += n

    out: dict[str, Any] = {
        "documents": len(rows),
        "total_words": total_words,
        "counting": key,
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
        # Pairs, not rates — the prior's mean must be the POOLED rate. See
        # verbal_markers.fit_prior; the unweighted version ran 3.6x high on
        # TIC against real transcripts.
        prior = vm.fit_prior(pairs)
        out["classes"][cls] = {
            "marks": marks,
            "rate_per_word": round(rate, 6),
            "rate_per_1000_words": round(rate * 1000.0, 3),
            "phi": round(phi, 3) if phi is not None else None,
            "prior_alpha_beta": ([round(prior[0], 4), round(prior[1], 4)]
                                 if prior else None),
            "window_words_phi1": vm.window_for_precision(rate),
            "window_words_phi_observed": (
                vm.window_for_precision(rate, phi=phi) if phi else None),
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
    ap.add_argument("--json", action="store_true", help="machine-readable")
    args = ap.parse_args()

    rows = _fetch(args.limit)
    if not rows:
        print("No transcripts found. Nothing to measure.", file=sys.stderr)
        return 1

    result = analyse(rows, strict_only=not args.include_ambiguous)

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"\n  {result['documents']} transcripts, "
          f"{result['total_words']:,} words, counting = {result['counting']}\n")
    for cls, d in result["classes"].items():
        if "error" in d:
            print(f"  {cls:8s}  {d['error']}")
            continue
        print(f"  {cls.upper()}")
        print(f"    rate        {d['rate_per_1000_words']:.2f} per 1,000 words "
              f"({d['marks']:,} marks)")
        print(f"    phi         {d['phi']}   "
              f"(1.0 = independent; >1 = bursty, and it inflates the SE)")
        w1, wp = d["window_words_phi1"], d["window_words_phi_observed"]
        print(f"    window      {w1} words at phi=1 -> {wp} words at observed phi")
        print(f"    prior       {d['prior_alpha_beta']}  (alpha, beta for D20)")
        print(f"    top         {', '.join(f'{t}({n})' for t, n in d['top_terms'][:6])}")
        print()

    print("  Next: paste the (alpha, beta) into the D20 prior, and check the "
          "window against\n  the span you want to intervene on. A window wider "
          "than a piece means that\n  class can only ever be a session-level "
          "read.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
