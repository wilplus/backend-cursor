"""The numbers that decide the ASR migration.

Ranked by decision-relevance, not by convention. For willab the headline
ASR number is NOT word error rate — it is whether words still land on the
right slide. A provider can beat whisper-1 on WER and lose F1, because F1's
load-bearing mechanism is ``word.start`` → ``slide_index_for_offset``.

GROUND TRUTH — WHAT WE HAVE AND WHAT WE DON'T
---------------------------------------------
``services.slide_boundary_metrics`` already says the hard part out loud:
nothing in the transcript, the acoustics or the deck records which slide was
actually on screen when a word was spoken. The same gap applies to word
timings — a human reference transcript is TEXT, it has no timestamps. So
this module keeps three tiers strictly apart and never lets a weaker one
masquerade as a stronger one:

  TIER 1  reference TEXT (human-typed)      → WER family. Real ground truth
                                              for words, none for timing.
  TIER 2  reference WORD TIMES (forced
          alignment, or hand-labeled)       → timestamp error. Real ground
                                              truth for timing.
  TIER 3  incumbent provider (whisper-1)    → AGREEMENT, not accuracy. Says
                                              "this differs from what we
                                              ship today", never "this is
                                              wrong". Cheap, needs no labels,
                                              and is the right regression
                                              tripwire — but calling it
                                              accuracy would assume the
                                              answer.

Every function here names its tier. ``slide_bucket_agreement`` is tier 3 by
default and becomes tier 1/2 the moment a reference word stream with real
times is passed as ``ref``.

Pure: no I/O, no DB, no network. Never raises on malformed input.
AC-9: internal engineering read; nothing here reaches a user payload.
"""
from __future__ import annotations

import difflib
from typing import Any, Optional

from asr_eval import normalize

# Words this close to a slide tap are boundary-critical — an error here can
# move the word to the wrong slide. Same constant as
# services.slide_boundary_metrics.DEFAULT_RISK_MS, deliberately: the eval
# and the live metric should mean the same thing by "at risk".
DEFAULT_RISK_MS = 500

# Anchor runs at least this long are treated as certain matches and used to
# split the edit-distance problem. A run of 4+ consecutive exact tokens is
# matched in any optimal alignment of real transcripts, so splitting there
# keeps WER exact in practice while making it linear rather than quadratic
# on a 15-minute take. Documented because it IS an approximation.
_ANCHOR_MIN = 4

# Above this many cells, an unanchored region gets difflib's opcodes instead
# of exact DP. ~4M cells ≈ 2000×2000 tokens ≈ a long gap with no exact run.
_DP_CELL_CAP = 4_000_000


# ── tier 1: word error rate ──────────────────────────────────────────────


def _edit_ops(ref: list, hyp: list) -> tuple:
    """``(hits, subs, dels, ins)`` plus matched ``(ref_i, hyp_j)`` pairs.

    Exact Levenshtein, computed per region between long exact anchors (see
    ``_ANCHOR_MIN``). Falls back to difflib opcodes for a pathologically
    large unanchored region so the harness degrades to a slightly loose
    count rather than hanging on a 40-minute take.
    """
    if not ref and not hyp:
        return (0, 0, 0, 0, [])
    if not ref:
        return (0, 0, 0, len(hyp), [])
    if not hyp:
        return (0, 0, len(ref), 0, [])

    sm = difflib.SequenceMatcher(None, ref, hyp, autojunk=False)
    anchors = [b for b in sm.get_matching_blocks()
               if b.size >= _ANCHOR_MIN]

    hits = subs = dels = ins = 0
    pairs: list = []
    prev_r = prev_h = 0
    for blk in anchors + [difflib.Match(len(ref), len(hyp), 0)]:
        h, s, d, i, p = _region_ops(
            ref[prev_r:blk.a], hyp[prev_h:blk.b], prev_r, prev_h)
        hits += h
        subs += s
        dels += d
        ins += i
        pairs.extend(p)
        for k in range(blk.size):
            pairs.append((blk.a + k, blk.b + k))
        hits += blk.size
        prev_r, prev_h = blk.a + blk.size, blk.b + blk.size
    return (hits, subs, dels, ins, pairs)


def _region_ops(ref: list, hyp: list, off_r: int, off_h: int) -> tuple:
    """Exact Levenshtein over one anchor-free region, with backtrace."""
    n, m = len(ref), len(hyp)
    if n == 0:
        return (0, 0, 0, m, [])
    if m == 0:
        return (0, 0, n, 0, [])
    if n * m > _DP_CELL_CAP:
        return _difflib_ops(ref, hyp, off_r, off_h)

    # dp[i][j] = edit distance between ref[:i] and hyp[:j].
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i
    for j in range(1, m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        ri = ref[i - 1]
        row, prev = dp[i], dp[i - 1]
        for j in range(1, m + 1):
            cost = 0 if ri == hyp[j - 1] else 1
            row[j] = min(prev[j - 1] + cost, prev[j] + 1, row[j - 1] + 1)

    hits = subs = dels = ins = 0
    pairs: list = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            if dp[i][j] == dp[i - 1][j - 1] + cost:
                if cost == 0:
                    hits += 1
                    pairs.append((off_r + i - 1, off_h + j - 1))
                else:
                    subs += 1
                i, j = i - 1, j - 1
                continue
        if i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            dels += 1
            i -= 1
        else:
            ins += 1
            j -= 1
    pairs.reverse()
    return (hits, subs, dels, ins, pairs)


def _difflib_ops(ref: list, hyp: list, off_r: int, off_h: int) -> tuple:
    """Opcode-based S/D/I for an oversized region. Upper bound, not exact."""
    hits = subs = dels = ins = 0
    pairs: list = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, ref, hyp, autojunk=False).get_opcodes():
        if tag == "equal":
            hits += i2 - i1
            pairs.extend((off_r + i1 + k, off_h + j1 + k)
                         for k in range(i2 - i1))
        elif tag == "replace":
            common = min(i2 - i1, j2 - j1)
            subs += common
            dels += (i2 - i1) - common
            ins += (j2 - j1) - common
        elif tag == "delete":
            dels += i2 - i1
        else:
            ins += j2 - j1
    return (hits, subs, dels, ins, pairs)


def word_error_rate(ref_tokens: Any, hyp_tokens: Any) -> dict:
    """TIER 1. WER with its S/D/I breakdown. Pure.

    The breakdown matters more than the rate for this migration: a provider
    whose errors are mostly DELETIONS is dropping speech, which costs whole
    slide fragments; one whose errors are SUBSTITUTIONS is mishearing words
    but keeping the timeline intact. Same WER, very different F1 cost.

    ``wer`` is None when the reference is empty — there is no rate to
    report, and returning 0.0 would read as a perfect score.
    """
    ref = list(ref_tokens or [])
    hyp = list(hyp_tokens or [])
    hits, subs, dels, ins, _ = _edit_ops(ref, hyp)
    n = len(ref)
    return {
        "wer": ((subs + dels + ins) / n) if n else None,
        "hits": hits,
        "substitutions": subs,
        "deletions": dels,
        "insertions": ins,
        "ref_words": n,
        "hyp_words": len(hyp),
    }


def matched_pairs(ref_tokens: Any, hyp_tokens: Any) -> list:
    """Matched ``(ref_i, hyp_j)`` index pairs, strictly increasing. Pure.

    The bridge from TIER 1 to TIER 2/3: timing can only be compared for
    words both streams agree were spoken.
    """
    return _edit_ops(list(ref_tokens or []), list(hyp_tokens or []))[4]


# ── tier 2/3: timing ─────────────────────────────────────────────────────


def _percentile(sorted_vals: list, pct: float) -> Optional[float]:
    """Nearest-rank percentile. ``sorted_vals`` must be sorted ascending."""
    if not sorted_vals:
        return None
    k = max(0, min(len(sorted_vals) - 1,
                   int(round(pct / 100.0 * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def timestamp_delta(ref_words: Any, hyp_words: Any, *,
                    tolerances_ms: Any = (50, 100, 200, 500)) -> dict:
    """|Δstart| between two word streams, over words they agree on.

    TIER 2 when ``ref_words`` carries real times (forced alignment or hand
    labels) — this is timestamp ACCURACY.
    TIER 3 when ``ref_words`` is another provider's output — this is
    timestamp AGREEMENT, i.e. drift from the incumbent. The function cannot
    tell which it was given, so the CALLER must label it; ``report.py``
    does.

    Returns median/p90/p95/max in ms, the share within each tolerance, and
    ``matched`` — always read ``matched`` first: a provider that matched 12
    words out of 900 can show a beautiful median.
    """
    ref = list(ref_words or [])
    hyp = list(hyp_words or [])
    pairs = matched_pairs([w["token"] for w in ref], [w["token"] for w in hyp])
    deltas = sorted(abs(ref[i]["start"] - hyp[j]["start"]) * 1000.0
                    for i, j in pairs)
    tols = [int(t) for t in (tolerances_ms or ())]
    within = {
        f"within_{t}ms": (sum(1 for d in deltas if d <= t) / len(deltas))
        if deltas else None
        for t in tols
    }
    return {
        "matched": len(pairs),
        "ref_words": len(ref),
        "hyp_words": len(hyp),
        "median_ms": _percentile(deltas, 50),
        "p90_ms": _percentile(deltas, 90),
        "p95_ms": _percentile(deltas, 95),
        "max_ms": deltas[-1] if deltas else None,
        **within,
    }


# ── THE metric: does the word still land on the right slide? ─────────────


def _bucket(words: Any, slide_advances: Any, n_slides: int) -> list:
    """Slide index per word, via the PRODUCTION rule.

    Imports ``services.slide_alignment.slide_index_for_offset`` rather than
    reimplementing it — an eval that re-derives the bucketing rule stops
    measuring the shipped one the first time either drifts.
    """
    from services.slide_alignment import slide_index_for_offset

    out = []
    for w in words:
        si = slide_index_for_offset(int(w["start"] * 1000), slide_advances)
        si = 0 if not isinstance(si, int) else max(0, min(si, max(0, n_slides - 1)))
        out.append(si)
    return out


def slide_bucket_agreement(ref_words: Any, hyp_words: Any,
                           slide_advances: Any, slides: Any, *,
                           risk_ms: int = DEFAULT_RISK_MS) -> Optional[dict]:
    """THE migration metric: same tap timeline, two word streams — do words
    land on the same slide?

    Returns None when the take cannot be measured (no deck, no taps, no
    words). A deckless take has no boundaries; scoring it 100% agreement
    would pad every average with takes that cannot disagree.

    ``disagreement_rate`` is the number to put in front of the founder: the
    share of mutually-recognized words the candidate would bucket to a
    DIFFERENT slide than the reference does. ``boundary_disagreement_rate``
    is the same thing restricted to words within ``risk_ms`` of a tap, where
    essentially all real disagreement lives — a low overall rate can hide a
    bad boundary rate, because most words sit far from any tap.

    ``net_slide_word_delta`` reports, per slide, how many words the
    candidate moves in or out. A model that shifts a slide's whole opening
    clause to the previous slide is an F1 regression even at 1% overall
    disagreement, and this is where that shows up.
    """
    ref = list(ref_words or [])
    hyp = list(hyp_words or [])
    n_slides = len(slides) if isinstance(slides, list) else 0
    if n_slides <= 0 or not ref or not hyp or not slide_advances:
        return None

    taps = sorted(int(a["t_ms"]) for a in slide_advances
                  if isinstance(a, dict)
                  and isinstance(a.get("t_ms"), (int, float))
                  and not isinstance(a.get("t_ms"), bool)
                  and int(a["t_ms"]) > 0)
    if not taps:
        return None

    ref_b = _bucket(ref, slide_advances, n_slides)
    hyp_b = _bucket(hyp, slide_advances, n_slides)
    pairs = matched_pairs([w["token"] for w in ref], [w["token"] for w in hyp])
    if not pairs:
        return {
            "matched": 0, "agreed": 0, "disagreement_rate": None,
            "boundary_matched": 0, "boundary_disagreement_rate": None,
            "net_slide_word_delta": {}, "slides_total": n_slides,
            "boundaries_total": len(taps), "risk_ms": int(risk_ms),
        }

    agreed = b_matched = b_agreed = 0
    delta: dict = {}
    for i, j in pairs:
        same = ref_b[i] == hyp_b[j]
        agreed += same
        if not same:
            delta[ref_b[i]] = delta.get(ref_b[i], 0) - 1
            delta[hyp_b[j]] = delta.get(hyp_b[j], 0) + 1
        at_risk = any(abs(int(ref[i]["start"] * 1000) - t) <= risk_ms
                      for t in taps)
        if at_risk:
            b_matched += 1
            b_agreed += same

    return {
        "matched": len(pairs),
        "agreed": agreed,
        "disagreement_rate": 1.0 - (agreed / len(pairs)),
        "boundary_matched": b_matched,
        "boundary_disagreement_rate": (1.0 - (b_agreed / b_matched))
        if b_matched else None,
        "net_slide_word_delta": {int(k): v for k, v in sorted(delta.items())
                                 if v},
        "slides_total": n_slides,
        "boundaries_total": len(taps),
        "risk_ms": int(risk_ms),
    }


def boundary_critical_wer(ref_words: Any, hyp_words: Any,
                          slide_advances: Any, *,
                          risk_ms: int = DEFAULT_RISK_MS) -> Optional[dict]:
    """WER restricted to words near a slide tap. TIER 1 (needs a reference).

    Mid-slide errors cost a word. Boundary errors cost a slide
    misattribution — the first clause of a slide is exactly the text a coach
    reads when ranking that slide's takes. Same rate, very different price,
    so it gets its own number.

    Returns None when no reference word falls in any risk window.
    """
    ref = list(ref_words or [])
    hyp = list(hyp_words or [])
    taps = sorted(int(a["t_ms"]) for a in (slide_advances or [])
                  if isinstance(a, dict)
                  and isinstance(a.get("t_ms"), (int, float))
                  and not isinstance(a.get("t_ms"), bool)
                  and int(a["t_ms"]) > 0)
    if not taps or not ref:
        return None

    def near(w: dict) -> bool:
        ms = int(w["start"] * 1000)
        return any(abs(ms - t) <= risk_ms for t in taps)

    ref_near = [w["token"] for w in ref if near(w)]
    hyp_near = [w["token"] for w in hyp if near(w)]
    if not ref_near:
        return None
    out = word_error_rate(ref_near, hyp_near)
    out["risk_ms"] = int(risk_ms)
    return out


# ── coverage guard ───────────────────────────────────────────────────────


def coverage(result: Any, *, expect_words: bool = True) -> dict:
    """Did the provider actually return usable output?

    Ordered FIRST in every report on purpose. A provider that returns no
    word timestamps at all — which is the documented behaviour of the
    gpt-4o-transcribe family — otherwise sails through the timing metrics
    as "no disagreements found". This turns that silence into a hard fail
    instead of a blank cell that reads like a pass.
    """
    if not isinstance(result, dict):
        return {"ok": False, "reason": "provider returned no result",
                "has_text": False, "has_words": False, "word_count": 0}
    text = (result.get("text") or "").strip()
    words = result.get("words") or []
    n = len(words) if isinstance(words, list) else 0
    if not text:
        return {"ok": False, "reason": "empty transcript",
                "has_text": False, "has_words": bool(n), "word_count": n}
    if expect_words and n == 0:
        return {"ok": False,
                "reason": "no word timestamps — cannot bucket words to "
                          "slides, so this provider cannot serve F1",
                "has_text": True, "has_words": False, "word_count": 0}
    return {"ok": True, "reason": "", "has_text": True,
            "has_words": bool(n), "word_count": n}


def evaluate_take(*, reference_text: Any, candidate: Any,
                  baseline: Any = None, slide_advances: Any = None,
                  slides: Any = None, language: Any = None,
                  reference_words: Any = None,
                  risk_ms: int = DEFAULT_RISK_MS) -> dict:
    """Every metric for ONE take, tiers labeled. Pure.

    ``candidate``/``baseline`` are ``transcribe_audio``-shaped dicts.
    ``reference_text`` is the human transcript (tier 1). ``reference_words``
    is optional word timing ground truth (tier 2) — pass it when a forced
    aligner or hand labeling has produced one; without it, timing is scored
    against ``baseline`` and reported as AGREEMENT (tier 3).
    """
    cov = coverage(candidate)
    out: dict = {"coverage": cov}
    if not cov["ok"]:
        # Everything downstream would be measuring an absence. Say so once.
        out["skipped"] = cov["reason"]
        return out

    cand_txt = candidate.get("text")
    cand_words = normalize.word_tokens(candidate.get("words"),
                                       language=language)

    if reference_text:
        ref_v = normalize.tokens(reference_text, language=language)
        ref_c = normalize.tokens(reference_text, strip_fillers=True,
                                 language=language)
        hyp_c = normalize.tokens(cand_txt, strip_fillers=True,
                                 language=language)
        out["wer_verbatim"] = word_error_rate(
            ref_v, normalize.tokens(cand_txt, language=language))
        out["wer_content"] = word_error_rate(ref_c, hyp_c)

    ref_words_norm = (normalize.word_tokens(reference_words, language=language)
                      if reference_words else None)
    timing_ref, timing_tier = None, None
    if ref_words_norm:
        timing_ref, timing_tier = ref_words_norm, "tier2_accuracy"
    elif baseline and coverage(baseline)["ok"]:
        timing_ref, timing_tier = normalize.word_tokens(
            baseline.get("words"), language=language), "tier3_agreement"

    if timing_ref:
        out["timing"] = {
            "tier": timing_tier,
            **timestamp_delta(timing_ref, cand_words),
        }
        if slide_advances and slides:
            out["slide_bucket"] = {
                "tier": timing_tier,
                **(slide_bucket_agreement(timing_ref, cand_words,
                                          slide_advances, slides,
                                          risk_ms=risk_ms) or
                   {"unmeasurable": True}),
            }

    if reference_text and slide_advances and ref_words_norm:
        bc = boundary_critical_wer(ref_words_norm, cand_words,
                                   slide_advances, risk_ms=risk_ms)
        if bc:
            out["wer_boundary_critical"] = bc
    return out
