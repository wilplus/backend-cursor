"""willab Lab — Level 1 salience ranking for coach-candidate selection.

WHAT THIS IS
------------
A pure ranking function over the EXISTING per-snippet acoustic feature
vector (the same 11-feature blob ``analyze_pcm_window`` already
produces). It replaces the naive duration-ranked selection with an
acoustic-ACTIVATION ranking, so the coach's scarce review attention
lands on the most coachable moments rather than merely the longest.

It is a pure swap of the selection/ranking STEP:
  in  = candidate windows, each carrying the existing metrics blob
  out = the top-N of those same windows (N = the existing per-session
        snippet cap), same shape, in chronological order.

No new features are extracted. No new snippet fields. The snippet
count and §3.3 contract are unchanged — only WHICH windows become
coach candidates changes.

PROVISIONAL WEIGHTS — NOT calibrated, NOT a fixed scientific formula
-------------------------------------------------------------------
The five salience components are combined with EQUAL 0.2 weights as a
provisional placeholder ("provisional-equal"). These weights are NOT
calibrated and are pending a separate dedicated pilot. They are
deliberately simple so the selection is explainable; they are NOT a
validated activation model and must NOT be treated as one. There is
intentionally NO machinery here to tune the weights on any data — the
weights are constants, full stop.

HARD METHODOLOGICAL FENCE (read before touching anything)
---------------------------------------------------------
This selector serves ONE frame only: the live product / coach-candidate
path. It must remain provably independent of any future validation
sample.

  • The salience score is PIPELINE-INTERNAL and TRANSIENT. It is
    computed here, used only to order/cap the candidates, and then
    DISCARDED. It is never written to the snippet row, never added to
    the metrics blob, never serialized into a user payload (AC-9), and
    never persisted anywhere. So it cannot become a selection key a
    later sampler could inherit.
  • A validation sample (e.g. the set any AUC-against-an-external-anchor
    is computed on) MUST be drawn INDEPENDENTLY of these salience
    features — random / stratified / whole-recording — and MUST NOT be
    drawn from the salience-selected set this function returns (i.e.
    NOT from the persisted charisma_snippets rows, which are this
    function's output). This was already required before Level 1,
    because charisma_snippets was always a SELECTED subset (duration
    before, salience now); Level 1 changes the flavour of the product
    selection, not this requirement. No validation/anchor path exists
    in this repository today (verified). When one is built, it draws
    from the raw recording, not from here.

If you are about to make a future validation sampler read from the
charisma_snippets set this function selects — STOP. The separation is
the point; do not unify them.
"""
from __future__ import annotations

import logging
from typing import Any, Optional


logger = logging.getLogger(__name__)


# How many candidate windows to score before taking the top-N. The
# willab segmenter (segment_into_snippets) returns its windows
# DURATION-ordered and capped at max_snippets; we ask it for a generous
# pool so salience selects across the whole recording's moments rather
# than re-ordering a tiny pre-capped set. For typical 1–5 min Lab
# recordings the real window count is well under this, so in practice
# salience scores over ALL of the recording's windows.
SALIENCE_CANDIDATE_POOL = 60


# ── Salience components (provisional-equal, 0.2 each) ──────────────
#
# Each entry: (metrics_key, direction). All five are read straight from
# the existing metrics blob — NO new extraction.
#   direction "high"      → higher raw value = more activated/salient
#   direction "abs_high"  → larger MAGNITUDE (either sign) = more salient
#   direction "low"       → lower raw value = more salient (inverted)
#
# Rationale (acoustic activation, recording-local):
#   f0_sd            pitch variability — a flat voice is low-activation
#   f0_slope         pitch trend; magnitude of movement, sign-agnostic
#   f0_mid_end_delta phrase-final pitch movement; magnitude
#   pause_regularity irregular pausing reads as activated → INVERTED
#   dynamic_db       loudness range / intensity dynamics
_SALIENCE_COMPONENTS: list[tuple[str, str]] = [
    ("f0_sd", "high"),
    ("f0_slope", "abs_high"),
    ("f0_mid_end_delta", "abs_high"),
    ("pause_regularity", "low"),
    ("dynamic_db", "high"),
]
# Provisional-equal. NOT calibrated. NOT pre-... (do not treat as fixed).
_SALIENCE_WEIGHT = 0.2  # 5 components × 0.2 = 1.0


def _raw_component(value: Any, direction: str) -> Optional[float]:
    """Map a raw metric value to a salience-oriented scalar where
    HIGHER ALWAYS = more salient, BEFORE normalization. Direction is
    folded in here so None can be handled uniformly downstream (a
    missing feature contributes nothing regardless of direction).

      "high"     → v        (higher raw = more salient)
      "abs_high" → abs(v)   (larger magnitude either sign = more salient)
      "low"      → -v       (lower raw = more salient → negate)

    Returns None when the feature is missing for this window."""
    if not isinstance(value, (int, float)):
        return None
    v = float(value)
    if direction == "abs_high":
        return abs(v)
    if direction == "low":
        return -v
    return v


def _minmax(vals: list[Optional[float]]) -> list[float]:
    """Min-max normalize a salience-oriented column to [0, 1] across the
    candidate pool (higher already = more salient — see _raw_component).

      None              → 0.0  (missing feature contributes nothing)
      all-missing column → all 0.0 (no signal)
      zero-range column  → present entries 1.0, None entries 0.0
                           (a present value always beats a missing one;
                            a constant across present entries doesn't
                            change relative ranking)
    """
    present = [v for v in vals if v is not None]
    if not present:
        return [0.0] * len(vals)
    lo, hi = min(present), max(present)
    rng = hi - lo
    if rng <= 0:
        return [0.0 if v is None else 1.0 for v in vals]
    return [0.0 if v is None else (v - lo) / rng for v in vals]


def rank_candidates_by_salience(
    candidates: list[dict],
    *,
    top_n: int,
    metrics_key: str = "metrics",
) -> list[dict]:
    """Select the top-``top_n`` most acoustically-salient candidates.

    Args
    ----
    candidates : list[dict]
        The candidate windows. Each item carries its existing metrics
        blob under ``candidates[i][metrics_key]`` (the 11-feature dict
        from ``analyze_pcm_window``). Items are otherwise opaque and are
        returned UNCHANGED (no salience field is attached).
    top_n : int
        How many to keep — the existing per-session snippet cap. The
        output never exceeds this, so the snippet count contract is
        preserved.
    metrics_key : str
        Where the metrics blob lives on each candidate dict.

    Returns
    -------
    list[dict]
        Up to ``top_n`` of the SAME candidate dicts, in CHRONOLOGICAL
        order (by ``start_ms`` when present, else input order). The
        salience score is NOT attached — it is transient (fence + AC-9).

    Notes
    -----
    Salience is normalized WITHIN this recording's candidate pool, so it
    means "the most activated moments in THIS recording" — recording-
    local, no cross-recording or population baseline, no intra-speaker
    history. (Level 1 scope.)
    """
    if not candidates:
        return []
    n = max(1, int(top_n))
    if len(candidates) <= n:
        # Nothing to select away — return all, chronological. (Salience
        # would only reorder, and we emit chronological regardless.)
        return _chronological(candidates)

    # Build each component column, min-max normalize across the pool,
    # invert the "low" components, sum with equal provisional weights.
    scores = [0.0] * len(candidates)
    for key, direction in _SALIENCE_COMPONENTS:
        # Direction folded into _raw_component (higher = more salient),
        # so _minmax + sum is uniform across components; None → 0.
        col_raw = [
            _raw_component((c.get(metrics_key) or {}).get(key), direction)
            for c in candidates
        ]
        col_norm = _minmax(col_raw)
        for i, x in enumerate(col_norm):
            scores[i] += _SALIENCE_WEIGHT * x

    # Rank by salience desc, take top-N. Stable tie-break on input index
    # keeps it deterministic.
    order = sorted(range(len(candidates)), key=lambda i: (-scores[i], i))
    selected_idx = set(order[:n])
    selected = [candidates[i] for i in range(len(candidates)) if i in selected_idx]

    logger.info(
        "snippet_salience.select pool=%d top_n=%d selected=%d "
        "(provisional-equal weights)",
        len(candidates), n, len(selected),
    )
    # IMPORTANT (fence/AC-9): scores are NOT attached to the returned
    # dicts. They live and die inside this function.
    return _chronological(selected)


def _chronological(items: list[dict]) -> list[dict]:
    """Order by start_ms when available, else preserve input order."""
    if all(isinstance(it.get("start_ms"), (int, float)) for it in items):
        return sorted(items, key=lambda it: it["start_ms"])
    return list(items)
