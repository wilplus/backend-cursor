"""Measured delivery stars (founder decisions 2026-07-18) — deterministic,
self-referential, NO LLM.

The founder-approved family: per piece, compare the delivery metrics against
the speaker's OWN reference and, when a passage clearly departs from their
norm, offer a behavioural suggestion the modal renders with the approved
copy ("Emphasis: This came out flatter than your usual. Lift it." etc — the
copy lives FE-side, keyed by `device`, same pattern as structural stars).

Triggers (|z| ≥ DELIVERY_STAR_Z vs the speaker's reference; ONE per piece —
the strongest |z| wins):
  * emphasis   — f0_sd or dynamic_db clearly BELOW the norm (flatter)
  * pace_fast  — wpm clearly ABOVE the norm
  * pace_slow  — wpm clearly BELOW the norm
  * pause      — pause_ratio clearly BELOW the norm (ran together)

Reference resolution (founder decision BE-1a option (b)): the speaker's
cross-take baseline when it exists; else, once THIS take has ≥ 6 usable
pieces, the within-take means — the existing self-comparison logic, so
take 1 is not silent on a normal-length take. Fewer than 6 pieces and no
history → silent (honest, never noisy).

The modal's action for these is the FE's snippet re-record mic (founder:
"re-record just that specific snippet to apply the feedback") — there is NO
approve/fold semantics here; a delivery star never mutates text (L1) and
never enters the applied fold.

AC-9: nothing numeric ever leaves this module toward a user payload — the
serve layer emits only {kind:'delivery', device}. Pure; unit-tested without
a DB.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Canonical feature keys (raw metrics names). The readout's coach-view
# `features` block remaps two of them — normalize_features() folds both
# spellings onto these.
DELIVERY_FEATURES = ("f0_sd", "dynamic_db", "wpm", "pause_ratio")

# The closed device set the serve layer + FE copy key on (the FE renders
# the sheet purely from `device` — an unknown spelling must yield no star).
DELIVERY_DEVICES = ("emphasis", "pace_fast", "pace_slow", "pause")

_FEATURE_ALIASES = {
    "speech_rate": "wpm",           # build_readout_features rename
    "loudness_range": "dynamic_db",  # build_readout_features rename
}

# Within-take fallback needs at least this many usable pieces (mirrors the
# acoustic read's cold-start floor — fewer is noise, not signal).
_MIN_PIECES_WITHIN_TAKE = 6


def normalize_features(d: Any) -> dict:
    """Fold either metrics spelling (raw or readout-features) onto the
    canonical DELIVERY_FEATURES keys. Non-numeric / bool values drop."""
    out: dict = {}
    if not isinstance(d, dict):
        return out
    for k, v in d.items():
        key = _FEATURE_ALIASES.get(k, k)
        if key in DELIVERY_FEATURES \
                and isinstance(v, (int, float)) and not isinstance(v, bool):
            out[key] = float(v)
    return out


def feature_stats(metric_dicts: Any, *, min_samples: int) -> Optional[dict]:
    """{feature: (mean, sd)} over a pool of metric dicts (either spelling),
    keeping features with >= min_samples values and non-zero spread. None
    when nothing clears the bar. Pure."""
    cols: dict = {f: [] for f in DELIVERY_FEATURES}
    for m in (metric_dicts or []):
        norm = normalize_features(m)
        for f, v in norm.items():
            cols[f].append(v)
    out: dict = {}
    for f, vals in cols.items():
        if len(vals) < min_samples:
            continue
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        sd = math.sqrt(var)
        if sd > 0:
            out[f] = (mean, sd)
    return out or None


def resolve_delivery_baseline(user_id: Any, current_piece_metrics: Any, *,
                              database=None) -> Optional[dict]:
    """Founder decision BE-1a(b): the speaker's cross-take history first;
    else the within-take pool once THIS take has >= 6 usable pieces; else
    None (silent). Best-effort; never raises."""
    try:
        if user_id:
            if database is None:
                from services.db import db as database
            hist: list = []
            try:
                sessions = database.v2_list_user_lab_sessions(
                    str(user_id), limit=5) or []
                for s in sessions:
                    sid = str(s.get("id") or "")
                    if not sid:
                        continue
                    for snip in (database.get_snippets_by_session(sid) or []):
                        m = snip.get("metrics")
                        if isinstance(m, dict):
                            hist.append(m)
            except Exception:
                hist = []
            stats = feature_stats(hist, min_samples=8)
            if stats:
                return stats
        usable = [m for m in (current_piece_metrics or [])
                  if isinstance(m, dict) and normalize_features(m)]
        if len(usable) >= _MIN_PIECES_WITHIN_TAKE:
            return feature_stats(usable,
                                 min_samples=_MIN_PIECES_WITHIN_TAKE)
        return None
    except Exception as e:
        logger.warning("delivery_stars: baseline resolve failed: %s", e)
        return None


def detect_delivery_issue(piece_metrics: Any, baseline: Optional[dict], *,
                          z_threshold: float = 1.2) -> Optional[str]:
    """The device for ONE piece — 'emphasis' | 'pace_fast' | 'pace_slow' |
    'pause' — or None. One suggestion per piece: the strongest |z| wins.
    Directions are one-sided by design (louder-than-usual or extra pauses
    are not coached here). Pure, deterministic."""
    if not baseline:
        return None
    feats = normalize_features(piece_metrics)
    if not feats:
        return None

    def _z(feature: str) -> Optional[float]:
        v = feats.get(feature)
        base = baseline.get(feature)
        if v is None or not base:
            return None
        mean, sd = base
        if not sd:
            return None
        return (v - mean) / sd

    candidates: list = []   # (|z|, device)
    z_f0 = _z("f0_sd")
    z_dyn = _z("dynamic_db")
    _flat = [z for z in (z_f0, z_dyn) if z is not None and z <= -z_threshold]
    if _flat:
        candidates.append((max(abs(z) for z in _flat), "emphasis"))
    z_wpm = _z("wpm")
    if z_wpm is not None and z_wpm >= z_threshold:
        candidates.append((abs(z_wpm), "pace_fast"))
    elif z_wpm is not None and z_wpm <= -z_threshold:
        candidates.append((abs(z_wpm), "pace_slow"))
    z_pause = _z("pause_ratio")
    if z_pause is not None and z_pause <= -z_threshold:
        candidates.append((abs(z_pause), "pause"))

    if not candidates:
        return None
    candidates.sort(key=lambda t: -t[0])
    return candidates[0][1]


def emphasis_z(piece_metrics: Any, baseline: Optional[dict]) -> Optional[float]:
    """The FLATNESS ordering key for structural intensity (founder #5):
    min(z_f0_sd, z_dynamic_db) — lower = delivered flatter = needs the
    practice prompt more. None when unmeasurable. Pure."""
    if not baseline:
        return None
    feats = normalize_features(piece_metrics)
    zs = []
    for f in ("f0_sd", "dynamic_db"):
        v = feats.get(f)
        base = baseline.get(f)
        if v is None or not base or not base[1]:
            continue
        zs.append((v - base[0]) / base[1])
    return min(zs) if zs else None
