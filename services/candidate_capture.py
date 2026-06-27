"""willab Lab — candidate-window capture (automation-audit fix #1). Pure.

Builds the rows for ``candidate_windows`` (the "offered vs chosen" training
signal): the FULL pool the segmenter scored, each window's raw feature vector,
and WHICH cut it made (notable / surfaced) — so the SELECTION step can later be
learned instead of re-coded. See migrations/add_candidate_windows.sql.

FENCE (services/snippet_salience.py): we store the raw acoustic ``metrics``
vector (score recomputable) + the heuristic's PROVISIONAL surfaced/notable
DECISION — NEVER the transient salience/control selection SCORE as a key. The
``surfaced`` flag is the heuristic's call, not a coach-truth label and not a
validation draw.
"""
from __future__ import annotations

from typing import Any, Optional

# Provenance stamp for the corpus — bump when the selector (salience weights /
# control composite / pool sizes) changes, so a later training run can segment
# the corpus by selector generation.
SELECTOR_VERSION = "salience-equal-0.2-v1+control-extremes-v1"

# Separate stamp for the FEATURE-EXTRACTOR generation (analyze_pcm_window's
# vector layout). The extractor can drift INDEPENDENTLY of the selector, and a
# corpus that accrues for months without knowing which extractor produced a
# given `metrics` blob is itself a latent data-loss — bump on any feature-vector
# schema change so the corpus stays segmentable by extractor generation.
FEATURES_VERSION = "analyze_pcm_window-11feat-v1"


def build_candidate_rows(
    candidates: list,
    *,
    notable_starts: set,
    surfaced_info: dict,
    session_id: Any,
    recording_id: Any,
    user_id: Optional[Any],
    heuristic_version: str = SELECTOR_VERSION,
    features_version: str = FEATURES_VERSION,
) -> list:
    """One row per candidate window.

    ``candidates``      — the full pool: dicts {start_ms, dur_ms, metrics, transcript}.
    ``notable_starts``  — set of start_ms that made the activation (notable) pool.
    ``surfaced_info``   — {start_ms: {"rank": int|None, "snippet_id": str|None}} for
                          the windows surfaced to the coach (membership = surfaced).

    Pure; never raises on a malformed candidate (skips it). ``metrics`` is the
    RAW feature vector as analysed — no selection score is added.
    """
    rows: list = []
    for pos, c in enumerate(candidates or []):
        if not isinstance(c, dict):
            continue
        sm = c.get("start_ms")
        if sm is None:
            continue
        info = surfaced_info.get(sm) or {}
        surfaced = sm in surfaced_info
        rows.append({
            "session_id": session_id,
            "recording_id": recording_id,
            "user_id": user_id,
            "start_offset_ms": sm,
            "duration_ms": c.get("dur_ms"),
            "pool_position": pos,
            "notable": sm in notable_starts,
            "surfaced": surfaced,
            "surfaced_rank": info.get("rank") if surfaced else None,
            "snippet_id": info.get("snippet_id") if surfaced else None,
            # RAW acoustic vector only (no salience/control score — fence).
            "metrics": c.get("metrics") or {},
            "transcript": (c.get("transcript") or None),
            "heuristic_version": heuristic_version,
            "features_version": features_version,
        })
    return rows

# Known v1 limitations (documented, not blocking — see the audit review):
#   • surfaced_rank blends an acoustic + a SLIDE-delivery signal; only the
#     acoustic features are captured here, so the slide component of the rank is
#     not reproducible from this corpus alone (slide scoring runs on the
#     surfaced set only). A later pass can add per-candidate slide context.
#   • Re-process FREEZES the first capture (insert is ON CONFLICT DO NOTHING per
#     (recording_id, start_offset_ms)) — by design for an append-only "what was
#     offered at the time" corpus; snippet_id is valid against that run's snippets.
