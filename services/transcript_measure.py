"""F1 — the three numbers for transcription and word→slide bucketing (D-ML-1,
build plan 2026-10-07), measured against a founder golden set.

services/slide_boundary_metrics.py measures EXPOSURE (how many words sit near
a tap) because the live pipeline has no ground truth. This module is the
other half: given a hand transcript per slide and the true slide-change
times, it turns the live pipeline's output into accuracy rates.

  * word_error_rate      — Levenshtein edits over the hand transcript's words:
                           (substitutions + insertions + deletions) / ref words.
  * slide_assignment     — of the pipeline words that align to a hand-transcript
                           word, the share the pipeline put on a different slide
                           than the hand transcript did. Truth comes from the
                           TEXT (which slide file the word was typed under), so it
                           does not depend on the provider's word times, which are
                           part of what is being measured.
  * boundary_offset_error — per slide change, the pipeline's boundary time (the
                           tap after the measured clock-offset correction) minus
                           the true change time, in ms. Signed: positive means
                           the pipeline's boundary is LATE, so the first words of
                           the new slide land on the previous one.

Normalisation for alignment is the one slide_word_split uses for its own word
alignment: lowercase, letters and digits only ("Store," ≡ store, "don't" ≡
dont). Punctuation and case are never counted as errors.

AC-9: internal only. These numbers go to a JSON report under docs/audit/measure
and to the decisions log; never to a user payload.

Pure: no DB, no I/O, no provider. Never raises on malformed input where a
truthful None or empty result exists.
"""
from __future__ import annotations

import re
from typing import Any, Optional

_NORM_RE = re.compile(r"[\W_]+", re.UNICODE)


def normalize_tokens(text: Any) -> list[str]:
    """Alignment tokens of a text: whitespace-split, lowercased, letters and
    digits only; a token that normalises to nothing (a lone dash) is dropped."""
    out: list[str] = []
    for raw in str(text or "").split():
        tok = _NORM_RE.sub("", raw.lower())
        if tok:
            out.append(tok)
    return out


def align(ref: list[str], hyp: list[str]) -> list[tuple[Optional[int], Optional[int]]]:
    """Levenshtein alignment of two token lists as (ref_index, hyp_index)
    pairs in order: a match or substitution carries both indexes, a deletion
    only the ref index, an insertion only the hyp index. Ties prefer a
    match/substitution, then a deletion, then an insertion — deterministic."""
    n, m = len(ref), len(hyp)
    # dist[i][j] = edits to turn ref[:i] into hyp[:j]
    dist = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dist[i][0] = i
    for j in range(1, m + 1):
        dist[0][j] = j
    for i in range(1, n + 1):
        ri = ref[i - 1]
        row = dist[i]
        prev = dist[i - 1]
        for j in range(1, m + 1):
            cost = 0 if ri == hyp[j - 1] else 1
            row[j] = min(prev[j - 1] + cost, prev[j] + 1, row[j - 1] + 1)
    pairs: list[tuple[Optional[int], Optional[int]]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            if dist[i][j] == dist[i - 1][j - 1] + cost:
                pairs.append((i - 1, j - 1))
                i -= 1
                j -= 1
                continue
        if i > 0 and dist[i][j] == dist[i - 1][j] + 1:
            pairs.append((i - 1, None))
            i -= 1
            continue
        pairs.append((None, j - 1))
        j -= 1
    pairs.reverse()
    return pairs


def word_error_rate(ref: list[str], hyp: list[str]) -> dict:
    """Edit counts and WER of ``hyp`` against ``ref`` (normalised tokens).
    ``wer`` is None when the reference is empty — a rate over nothing is not
    a zero."""
    subs = ins = dels = 0
    for ri, hi in align(ref, hyp):
        if ri is None:
            ins += 1
        elif hi is None:
            dels += 1
        elif ref[ri] != hyp[hi]:
            subs += 1
    errors = subs + ins + dels
    return {
        "ref_words": len(ref),
        "hyp_words": len(hyp),
        "substitutions": subs,
        "insertions": ins,
        "deletions": dels,
        "errors": errors,
        "wer": (errors / len(ref)) if ref else None,
    }


def hyp_tokens_with_index(words: Any) -> tuple[list[str], list[int]]:
    """(normalised tokens, index of the source word dict for each token) for
    a pipeline word list in time order. Word dicts whose text normalises to
    nothing contribute no token."""
    toks: list[str] = []
    src: list[int] = []
    for idx, w in enumerate(words or []):
        if not isinstance(w, dict):
            continue
        norm = normalize_tokens(w.get("word") or "")
        for t in norm:
            toks.append(t)
            src.append(idx)
    return toks, src


def slide_assignment(
    ref_slides: list[list[str]],
    hyp_tokens: list[str],
    hyp_slide_of_token: list[int],
) -> dict:
    """How often the pipeline put a word on the wrong slide.

    ``ref_slides`` — the hand transcript's normalised tokens, one list per
    slide in deck order (the truth of which slide each word belongs to).
    ``hyp_tokens`` — the pipeline's normalised tokens in time order, and
    ``hyp_slide_of_token`` the slide index the pipeline bucketed each to.

    Only pipeline tokens that align to a reference token (a match or a
    substitution) can be judged; insertions are counted as ``unjudged``.
    ``wrong_slide_share`` is None when nothing could be judged.
    """
    ref: list[str] = []
    ref_slide: list[int] = []
    for si, toks in enumerate(ref_slides):
        for t in toks:
            ref.append(t)
            ref_slide.append(si)
    judged = wrong = unjudged = 0
    per_slide: dict[int, dict[str, int]] = {
        si: {"judged": 0, "wrong": 0} for si in range(len(ref_slides))
    }
    for ri, hi in align(ref, hyp_tokens):
        if hi is None:
            continue
        if ri is None:
            unjudged += 1
            continue
        judged += 1
        truth = ref_slide[ri]
        per_slide[truth]["judged"] += 1
        if hyp_slide_of_token[hi] != truth:
            wrong += 1
            per_slide[truth]["wrong"] += 1
    return {
        "judged": judged,
        "wrong_slide": wrong,
        "unjudged_insertions": unjudged,
        "wrong_slide_share": (wrong / judged) if judged else None,
        "per_slide": [
            {"slide_index": si, **per_slide[si]} for si in range(len(ref_slides))
        ],
    }


def true_slide_at(start_s: float, true_changes_s: list[float]) -> int:
    """The slide on screen at ``start_s`` by the TRUE change times (sorted
    seconds, one per transition from slide k to k+1)."""
    idx = 0
    for t in true_changes_s:
        if start_s >= t:
            idx += 1
        else:
            break
    return idx


def pipeline_boundaries_ms(slide_advances: Any) -> list[int]:
    """The pipeline's boundary times in ms, time-sorted, without the
    recording-start entry (t_ms <= 0) — the same reading
    slide_boundary_metrics uses."""
    out: list[int] = []
    for a in slide_advances or []:
        if not isinstance(a, dict):
            continue
        t = a.get("t_ms")
        if isinstance(t, bool) or not isinstance(t, (int, float)):
            continue
        if t <= 0:
            continue
        out.append(int(t))
    out.sort()
    return out


def boundary_offset_error(
    true_changes_s: list[float], slide_advances: Any,
) -> dict:
    """Signed error (pipeline boundary − true change, ms) per slide change,
    k-th against k-th, over the boundaries both sides have. A count
    mismatch is reported, never papered over."""
    truth_ms = [int(round(float(t) * 1000)) for t in true_changes_s]
    pipe_ms = pipeline_boundaries_ms(slide_advances)
    n = min(len(truth_ms), len(pipe_ms))
    errors = [pipe_ms[k] - truth_ms[k] for k in range(n)]
    abs_errors = [abs(e) for e in errors]
    return {
        "true_boundaries": len(truth_ms),
        "pipeline_boundaries": len(pipe_ms),
        "compared": n,
        "count_mismatch": len(truth_ms) != len(pipe_ms),
        "errors_ms": errors,
        "mean_ms": (sum(errors) / n) if n else None,
        "mean_abs_ms": (sum(abs_errors) / n) if n else None,
        "max_abs_ms": max(abs_errors) if n else None,
    }


def summarize(items: list[dict]) -> dict:
    """Micro-averaged totals over per-item results shaped like the report's
    ``items`` entries (``wer``, ``slide_assignment``, ``offset`` keys)."""
    ref = errs = judged = wrong = 0
    offsets: list[int] = []
    for it in items:
        w = it.get("wer") or {}
        ref += int(w.get("ref_words") or 0)
        errs += int(w.get("errors") or 0)
        s = it.get("slide_assignment") or {}
        judged += int(s.get("judged") or 0)
        wrong += int(s.get("wrong_slide") or 0)
        o = it.get("offset") or {}
        offsets.extend(int(e) for e in (o.get("errors_ms") or []))
    return {
        "items": len(items),
        "ref_words": ref,
        "errors": errs,
        "wer": (errs / ref) if ref else None,
        "judged_words": judged,
        "wrong_slide_words": wrong,
        "wrong_slide_share": (wrong / judged) if judged else None,
        "boundaries_compared": len(offsets),
        "offset_mean_ms": (sum(offsets) / len(offsets)) if offsets else None,
        "offset_mean_abs_ms": (
            sum(abs(e) for e in offsets) / len(offsets)) if offsets else None,
        "offset_max_abs_ms": max((abs(e) for e in offsets), default=None),
    }


def summarize_by_tag(items: list[dict]) -> dict:
    """``summarize`` per tag, over the items carrying that tag."""
    tags: dict[str, list[dict]] = {}
    for it in items:
        for tag in it.get("tags") or []:
            tags.setdefault(str(tag), []).append(it)
    return {tag: summarize(group) for tag, group in sorted(tags.items())}
