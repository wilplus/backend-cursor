"""Aggregation and the migration gate.

Turns per-take metrics into one decision. The gate is deliberately hard to
pass and easy to read: an ASR swap under a north star of "PERFECT
transcript, segmented EXACTLY 1:1 per slide" should have to prove it costs
nothing at the slide boundary, not merely that its WER looks nice.

MICRO, NOT MACRO
----------------
WER is pooled across takes (total errors / total reference words), which is
the standard and the honest one: macro-averaging per-take rates lets a
12-word take swing the corpus as hard as a 900-word take. Macro is reported
alongside, because a large micro/macro gap is itself a signal that one long
take is carrying the result.
"""
from __future__ import annotations

from typing import Any, Optional

# Gate thresholds. These are STARTING POINTS to be re-set from the observed
# whisper-1 baseline once the golden set exists — a threshold invented before
# any measurement is a guess wearing a number's clothes. `gate` reports the
# threshold it used alongside the verdict so the two are never separated.
MAX_BUCKET_DISAGREEMENT = 0.005          # 0.5% of words change slide
MAX_BOUNDARY_DISAGREEMENT = 0.02         # 2% of boundary-adjacent words
MAX_VERBATIM_WER_REGRESSION = 0.0        # no WER regression vs incumbent
MAX_BOUNDARY_TIMING_P90_MS = 200.0       # p90 |Δstart| at the boundary


def _mean(vals: Any) -> Optional[float]:
    v = [x for x in (vals or []) if isinstance(x, (int, float))]
    return (sum(v) / len(v)) if v else None


def _pooled_wer(results: Any, key: str) -> dict:
    """Micro + macro WER over every take that produced ``key``."""
    subs = dels = ins = ref = hyp = 0
    rates, n = [], 0
    for r in (results or []):
        m = (r or {}).get(key)
        if not isinstance(m, dict) or not m.get("ref_words"):
            continue
        subs += m["substitutions"]
        dels += m["deletions"]
        ins += m["insertions"]
        ref += m["ref_words"]
        hyp += m["hyp_words"]
        if isinstance(m.get("wer"), (int, float)):
            rates.append(m["wer"])
        n += 1
    return {
        "takes": n,
        "wer_micro": ((subs + dels + ins) / ref) if ref else None,
        "wer_macro": _mean(rates),
        "substitutions": subs, "deletions": dels, "insertions": ins,
        "ref_words": ref, "hyp_words": hyp,
        # Deletion-heavy errors cost whole slide fragments, not just words.
        "deletion_share": (dels / (subs + dels + ins))
        if (subs + dels + ins) else None,
    }


def _pooled_bucket(results: Any) -> dict:
    matched = agreed = b_matched = b_agreed = 0
    n = 0
    delta: dict = {}
    for r in (results or []):
        m = (r or {}).get("slide_bucket")
        if not isinstance(m, dict) or not m.get("matched"):
            continue
        matched += m["matched"]
        agreed += m["agreed"]
        b_matched += m.get("boundary_matched") or 0
        b_agreed += int(round((m.get("boundary_matched") or 0) *
                              (1.0 - (m.get("boundary_disagreement_rate") or 0.0))))
        for k, v in (m.get("net_slide_word_delta") or {}).items():
            delta[int(k)] = delta.get(int(k), 0) + v
        n += 1
    return {
        "takes": n,
        "matched_words": matched,
        "disagreement_rate": (1.0 - agreed / matched) if matched else None,
        "boundary_matched_words": b_matched,
        "boundary_disagreement_rate": (1.0 - b_agreed / b_matched)
        if b_matched else None,
        "worst_slide_word_delta": max((abs(v) for v in delta.values()),
                                      default=0),
    }


def _pooled_timing(results: Any) -> dict:
    tiers = {(r or {}).get("timing", {}).get("tier")
             for r in (results or []) if (r or {}).get("timing")}
    return {
        "tier": (tiers.pop() if len(tiers) == 1 else
                 ("mixed" if tiers else None)),
        "median_ms": _mean([(r or {}).get("timing", {}).get("median_ms")
                            for r in (results or [])]),
        "p90_ms": _mean([(r or {}).get("timing", {}).get("p90_ms")
                         for r in (results or [])]),
        "p95_ms": _mean([(r or {}).get("timing", {}).get("p95_ms")
                         for r in (results or [])]),
        "within_200ms": _mean([(r or {}).get("timing", {}).get("within_200ms")
                               for r in (results or [])]),
        "matched": sum((r or {}).get("timing", {}).get("matched") or 0
                       for r in (results or [])),
    }


def summarize(provider: str, rows: Any) -> dict:
    """One provider's corpus-level summary. ``rows`` are per-take results."""
    results = [(r or {}).get("result") or {} for r in (rows or [])]
    usable = [r for r in results if not r.get("skipped")]
    failed = [r for r in results if r.get("skipped")]
    return {
        "provider": provider,
        "takes_total": len(results),
        "takes_usable": len(usable),
        "takes_failed": len(failed),
        "failure_reasons": sorted({r.get("skipped") for r in failed
                                   if r.get("skipped")}),
        "wer_verbatim": _pooled_wer(usable, "wer_verbatim"),
        "wer_content": _pooled_wer(usable, "wer_content"),
        "wer_boundary_critical": _pooled_wer(usable, "wer_boundary_critical"),
        "timing": _pooled_timing(usable),
        "slide_bucket": _pooled_bucket(usable),
    }


def gate(candidate: Any, baseline: Any = None, *,
         max_bucket: float = MAX_BUCKET_DISAGREEMENT,
         max_boundary: float = MAX_BOUNDARY_DISAGREEMENT,
         max_wer_regression: float = MAX_VERBATIM_WER_REGRESSION,
         max_boundary_p90_ms: float = MAX_BOUNDARY_TIMING_P90_MS) -> dict:
    """PASS / FAIL / INSUFFICIENT-DATA for one candidate.

    INSUFFICIENT-DATA is a first-class outcome, not a soft pass. The most
    likely way this migration goes wrong is a candidate that never produced
    word timestamps being read as "no disagreements found", so the absence
    of a number is treated as a reason to refuse, never as a reason to
    approve.

    ``reasons`` is ordered by severity so the first line is the finding.
    """
    c = candidate or {}
    reasons: list = []
    blocking: list = []

    if not c.get("takes_usable"):
        return {
            "verdict": "FAIL",
            "provider": c.get("provider"),
            "reasons": [f"no usable takes — {c.get('failure_reasons') or ['unknown']}"],
            "thresholds": {},
        }

    if c.get("takes_failed"):
        reasons.append(
            f"{c['takes_failed']}/{c['takes_total']} take(s) unusable: "
            f"{c.get('failure_reasons')}")
        blocking.append("unusable takes")

    bucket = c.get("slide_bucket") or {}
    bd = bucket.get("disagreement_rate")
    bbd = bucket.get("boundary_disagreement_rate")

    if bd is None:
        reasons.append(
            "slide-bucket agreement UNMEASURABLE — the metric that decides "
            "this migration was not computed on any take (needs deck "
            "timeline + word timestamps on both sides)")
        blocking.append("bucket unmeasurable")
    else:
        if bd > max_bucket:
            reasons.append(
                f"slide-bucket disagreement {bd:.3%} exceeds {max_bucket:.3%} "
                f"— words move to different slides vs the reference")
            blocking.append("bucket disagreement")
        if bbd is not None and bbd > max_boundary:
            reasons.append(
                f"boundary-adjacent disagreement {bbd:.2%} exceeds "
                f"{max_boundary:.2%} — the damage is concentrated exactly "
                f"where a slide starts")
            blocking.append("boundary disagreement")

    timing = c.get("timing") or {}
    if timing.get("tier") == "tier3_agreement":
        reasons.append(
            "timing is TIER 3 (agreement with whisper-1, not accuracy) — this "
            "can only show the candidate DIFFERS, never that it is BETTER. "
            "Produce reference_words to upgrade to tier 2.")
    p90 = timing.get("p90_ms")
    if isinstance(p90, (int, float)) and p90 > max_boundary_p90_ms:
        reasons.append(
            f"word-timestamp p90 {p90:.0f}ms exceeds {max_boundary_p90_ms:.0f}ms")
        blocking.append("timing p90")

    if baseline:
        cw = (c.get("wer_verbatim") or {}).get("wer_micro")
        bw = (baseline.get("wer_verbatim") or {}).get("wer_micro")
        if isinstance(cw, (int, float)) and isinstance(bw, (int, float)):
            drift = cw - bw
            if drift > max_wer_regression:
                reasons.append(
                    f"verbatim WER regressed {drift:+.2%} vs "
                    f"{baseline.get('provider')} ({bw:.2%} → {cw:.2%})")
                blocking.append("wer regression")
            else:
                reasons.append(
                    f"verbatim WER {bw:.2%} → {cw:.2%} ({drift:+.2%})")
        # A candidate that keeps WER by DELETING less but INSERTING more is
        # not equivalent; deletions cost whole fragments of a slide.
        cd = (c.get("wer_verbatim") or {}).get("deletion_share")
        bd_share = (baseline.get("wer_verbatim") or {}).get("deletion_share")
        if isinstance(cd, (int, float)) and isinstance(bd_share, (int, float)) \
                and cd > bd_share + 0.15:
            reasons.append(
                f"error mix shifted toward DELETIONS ({bd_share:.0%} → "
                f"{cd:.0%} of errors) — dropped speech costs whole slide "
                f"fragments, not just words")
            blocking.append("deletion shift")

    if "bucket unmeasurable" in blocking or "unusable takes" in blocking:
        verdict = "INSUFFICIENT-DATA"
    elif blocking:
        verdict = "FAIL"
    else:
        verdict = "PASS"

    return {
        "verdict": verdict,
        "provider": c.get("provider"),
        "blocking": blocking,
        "reasons": reasons,
        "thresholds": {
            "max_bucket_disagreement": max_bucket,
            "max_boundary_disagreement": max_boundary,
            "max_verbatim_wer_regression": max_wer_regression,
            "max_boundary_timing_p90_ms": max_boundary_p90_ms,
        },
    }


# ── rendering ────────────────────────────────────────────────────────────


def _pct(v: Any, nd: int = 2) -> str:
    return f"{v:.{nd}%}" if isinstance(v, (int, float)) else "—"


def _ms(v: Any) -> str:
    return f"{v:.0f}ms" if isinstance(v, (int, float)) else "—"


def render(summaries: Any, gates: Any = None,
           baseline: Optional[str] = None) -> str:
    """Human-readable comparison table, decision-relevant order.

    Coverage first, THE metric second, WER last — the same ranking the
    package docstring argues for, so a reader who stops after two lines has
    still read the two lines that decide the migration.

    ``baseline`` is labeled as the incumbent rather than gated: it is the
    reference the others are measured against, so scoring it against itself
    would print a meaningless verdict next to the row a reader anchors on.
    """
    lines: list = []
    gates = {g["provider"]: g for g in (gates or [])}

    lines.append("=" * 78)
    lines.append(f"ASR EVAL — candidates vs incumbent ({baseline or 'baseline'})")
    lines.append("=" * 78)

    for s in (summaries or []):
        p = s.get("provider")
        is_base = (p == baseline)
        g = {} if is_base else (gates.get(p) or {})
        lines.append("")
        label = ("incumbent — reference" if is_base
                 else g.get("verdict", "no gate"))
        lines.append(f"── {p}  [{label}]")
        lines.append(f"   takes usable          {s.get('takes_usable')}/"
                     f"{s.get('takes_total')}")
        if s.get("failure_reasons"):
            for r in s["failure_reasons"]:
                lines.append(f"     ! {r}")

        b = s.get("slide_bucket") or {}
        if is_base:
            lines.append("   SLIDE-BUCKET           n/a — this IS the reference")
        else:
            lines.append(f"   SLIDE-BUCKET disagree {_pct(b.get('disagreement_rate'), 3)}"
                         f"   (boundary-adjacent {_pct(b.get('boundary_disagreement_rate'))})")
            lines.append(f"     matched words       {b.get('matched_words') or 0}"
                         f"   worst slide Δwords {b.get('worst_slide_word_delta') or 0}")

        t = s.get("timing") or {}
        if not is_base:
            lines.append(f"   TIMING [{t.get('tier') or '—'}]  median {_ms(t.get('median_ms'))}"
                         f"  p90 {_ms(t.get('p90_ms'))}  ≤200ms {_pct(t.get('within_200ms'), 1)}")

        wv, wc = s.get("wer_verbatim") or {}, s.get("wer_content") or {}
        wb = s.get("wer_boundary_critical") or {}
        lines.append(f"   WER verbatim          {_pct(wv.get('wer_micro'))}"
                     f"   (content {_pct(wc.get('wer_micro'))}"
                     f", boundary-critical {_pct(wb.get('wer_micro'))})")
        lines.append(f"     S/D/I               {wv.get('substitutions')}/"
                     f"{wv.get('deletions')}/{wv.get('insertions')}"
                     f"   deletion share {_pct(wv.get('deletion_share'), 0)}")
        for r in (g.get("reasons") or []):
            lines.append(f"   → {r}")

    lines.append("")
    lines.append("-" * 78)
    lines.append("Read order: coverage → slide-bucket → timing → WER.")
    lines.append("A candidate with no word timestamps cannot serve F1 at any WER.")
    return "\n".join(lines)
