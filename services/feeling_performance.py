"""Feeling × performance correlation (willab — audit assembly).

Turns the stored pre-recording feelings (recording_feelings, U10) + the existing
per-snippet performance signal into the audit's "Performance under feeling" +
"Stress as fuel" sections — so the interactive HTML audit can SUCK UP the user's
real data instead of the coach hand-typing it.

All functions here are PURE (no DB) so they're unit-tested; the route gathers
the rows and calls them. DIRECTIONAL by design (small-n coaching indicators, not
statistics) — the headline is a DRAFT the coach curates, and everything is gated
on a minimum number of takes so we never assert a trend from one recording.

FENCE: these are coaching indicators assembled for the AUDIT (the curated
deliverable). They are NOT the live split-sink readout — the per-turn user
surface stays score-free (AC-9). The audit is the sanctioned, human-curated
place performance is shown back.
"""
from __future__ import annotations

from typing import Any, Optional

from services.feelings import VALID_FEELINGS

# Need at least this many scored takes before we'll assert a "you perform best
# when X" headline — below it we return the buckets but no claim.
_MIN_PAIRS_FOR_HEADLINE = 3
# A feeling needs at least this many takes to anchor the headline.
_MIN_N_PER_FEELING = 2


def session_performance(snippets: Any) -> Optional[float]:
    """One session's performance = the mean of its snippets' existing salience
    signal (metrics.overall_score, 0–1). None when nothing is scorable — that
    session simply doesn't enter the correlation."""
    if not isinstance(snippets, list):
        return None
    vals = []
    for s in snippets:
        if not isinstance(s, dict):
            continue
        m = s.get("metrics") if isinstance(s.get("metrics"), dict) else {}
        v = m.get("overall_score")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            vals.append(float(v))
    if not vals:
        return None
    return sum(vals) / len(vals)


def correlate_feeling_performance(pairs: Any) -> dict:
    """pairs = [{"feeling": <enum>, "performance": <0–1 | None>}], one per take.
    Returns the "Performance under feeling" payload::

        {
          "buckets": [{"feeling", "performance", "n"}],   # mean per feeling, desc
          "top_feeling": <enum|None>,                     # best, if confident
          "headline": <str|None>,                         # DRAFT, coach edits
          "n": <int>                                      # scored takes used
        }
    """
    sums: dict = {}
    counts: dict = {}
    for p in pairs if isinstance(pairs, list) else []:
        if not isinstance(p, dict):
            continue
        f = p.get("feeling")
        perf = p.get("performance")
        if f not in VALID_FEELINGS:
            continue
        if not isinstance(perf, (int, float)) or isinstance(perf, bool):
            continue
        sums[f] = sums.get(f, 0.0) + float(perf)
        counts[f] = counts.get(f, 0) + 1

    buckets = [
        {"feeling": f, "performance": round(sums[f] / counts[f], 2),
         "n": counts[f]}
        for f in counts
    ]
    buckets.sort(key=lambda b: (-b["performance"], -b["n"]))
    total = sum(counts.values())

    top_feeling = None
    headline = None
    if (
        buckets
        and total >= _MIN_PAIRS_FOR_HEADLINE
        and buckets[0]["n"] >= _MIN_N_PER_FEELING
        # a "best" only means something if there's another feeling to beat
        and len(buckets) >= 2
    ):
        top_feeling = buckets[0]["feeling"]
        headline = f"You perform best when you feel {top_feeling}."

    return {
        "buckets": buckets,
        "top_feeling": top_feeling,
        "headline": headline,
        "n": total,
    }


