"""Deterministic per-piece stress↔charisma read (founder 2026-07-14) — the
coach-only potentiometer + the outside-normal-range triage flag.

WHAT IT IS. For every ≤200-char piece of a take, a fixed, acoustic-only
composite locating the moment on a stress↔charisma axis: −1.0 (shaky /
stress-leaning) … +1.0 (controlled / charisma-leaning). Scherer-inspired
appraisal features (pitch variability, pause regularity, loudness range,
voicing) z-scored against the speaker's OWN baseline, weighted-summed via the
existing ``score_control_direction`` composite, squashed with tanh. Plus a
salience flag: any component beyond ``_OUT_OF_RANGE_Z`` z from the speaker's
normal → ``outside_normal_range`` — the coach's manual-attention triage queue.

WHAT IT IS NOT (fences):
  * NOT learned. Fixed literature-tilted weights, never trained — so showing
    it to the labeling coach cannot anchor labels to a model's opinion
    (BLIND COACH: the shadow model's guess still never reaches the labeler).
  * NEVER user-facing (AC-9). Persisted under metrics["acoustic_read"] and
    surfaced ONLY on the coach packet (include_slide_scores). The user readout
    must never carry acoustic_read / potentiometer / outside_normal_range —
    fence-tested in test_acoustic_read.py.

FENCE AMENDMENT (founder 2026-07-14): services/snippet_salience.py documents
its salience/control scores as TRANSIENT (never persisted). This module
deliberately PERSISTS a derived composite per piece — a founder-directed
change for the coach potentiometer. The amendment is scoped: (a) versioned
(``version`` rides every blob so a weight change never mixes regimes),
(b) coach-only, (c) the candidate_windows capture corpus stays RAW
(no composite is ever written there — validation-sample independence holds).

Baseline: per-user (mean, sd) per feature over the speaker's OWN historical
pieces (``build_user_baseline``); cold-start (guest / first take) falls back
to within-take z-scores — same graceful degradation as the salience selector.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional

from services.snippet_salience import (
    _CONTROL_COMPONENTS,
    _zscore_column,
    score_control_direction,
)

logger = logging.getLogger(__name__)

_READ_VERSION = "acoustic-read-v1"

# |z| beyond this on ANY control component → outside the speaker's normal
# range → flagged for the coach's manual pass. 2.0 ≈ the conventional
# "notably atypical" bar; deliberately conservative so the flag stays a
# triage signal, not noise.
_OUT_OF_RANGE_Z = 2.0

# tanh squash scale: a weighted z-sum of ~1.5 (solidly atypical) lands ≈ 0.9
# on the needle; typical moments stay near the middle.
_SQUASH_SCALE = 1.0

# The needle must lean beyond this before the auto-comment may speak a tone
# word at all (the comment's own hedging is on top of this).
TONE_HINT_THRESHOLD = 0.35

# Cold-start floor: within-take z-scores are scale-free, so a 2–3-piece take
# pegs the needle near ±1 on trivial variation (noise as signal). With NO
# per-user baseline we require at least this many pieces before the needle
# may leave neutral; below it every piece reads potentiometer 0.0 /
# outside_normal_range False. A real per-user baseline bypasses the floor
# (its z-scores are against a stable reference, not the tiny pool).
_MIN_PIECES_FOR_WITHIN_TAKE_READ = 6

# Baseline history caps — this runs SYNC on the upload path, so keep the DB
# work tight (≤5 sessions × get_snippets_by_session). A future move to a
# daemon/materialized baseline can widen it.
_BASELINE_MAX_SESSIONS = 5
_BASELINE_MIN_SAMPLES = 8

# Parent-take reference floor (founder 2026-07-17). A mid-take RE-READ is a
# 1–2-piece recording: with no user baseline it fell under the within-take
# cold-start floor and every re-read piece read a fake-neutral 0.0 — the
# needle pegged dead centre, which is exactly what the coach saw. Its parent
# SPOKEN take is the honest reference (same speaker, same session, same mic)
# AND the meaningful comparison: "did the re-read land differently than the
# take it re-reads?". Same evidence bar as the within-take rule.
_BASELINE_MIN_SAMPLES_PARENT = _MIN_PIECES_FOR_WITHIN_TAKE_READ


def _baseline_from_metrics(metric_dicts: list, min_samples: int) -> Optional[dict]:
    """{feature_key: (mean, sd)} over a pool of piece-metric dicts, keeping
    only features with >= min_samples usable values and a non-zero spread.
    None when nothing clears the bar. Pure."""
    cols: dict = {name: [] for name, _w in _CONTROL_COMPONENTS}
    for m in metric_dicts:
        if not isinstance(m, dict):
            continue
        for name, _w in _CONTROL_COMPONENTS:
            v = m.get(name)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cols[name].append(float(v))
    out: dict = {}
    for name, vals in cols.items():
        if len(vals) < min_samples:
            continue
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        sd = math.sqrt(var)
        if sd > 0:
            out[name] = (mean, sd)
    return out or None


def _session_piece_metrics(session_id: Any, *, database=None) -> list:
    """Every stored piece's metrics dict for one session. Best-effort: []."""
    if not session_id:
        return []
    try:
        if database is None:
            from services.db import db as database
        return [
            snip.get("metrics")
            for snip in (database.get_snippets_by_session(str(session_id)) or [])
            if isinstance(snip.get("metrics"), dict)
        ]
    except Exception as e:
        logger.warning("acoustic_read: session metrics read failed sid=%s: %s",
                       session_id, e)
        return []


def build_user_baseline(user_id: Optional[str], *, database=None) -> Optional[dict]:
    """Per-speaker acoustic baseline: {feature_key: (mean, sd)} over the
    user's historical piece metrics — the ISB hook score_control_direction
    always had. None for guests / too-little history (< _BASELINE_MIN_SAMPLES
    moments) → callers fall back to the parent take / within-take z-scores.
    Best-effort: any read hiccup returns None, never raises (a baseline must
    never break a recording)."""
    if not user_id:
        return None
    try:
        if database is None:
            from services.db import db as database
        sessions = database.v2_list_user_lab_sessions(
            user_id, limit=_BASELINE_MAX_SESSIONS) or []
        pool = []
        for s in sessions:
            pool.extend(_session_piece_metrics(s.get("id"), database=database))
        return _baseline_from_metrics(pool, _BASELINE_MIN_SAMPLES)
    except Exception as e:
        logger.warning("acoustic_read: baseline build failed user=%s: %s",
                       user_id, e)
        return None


def build_parent_take_baseline(parent_session_id: Any, *,
                               database=None) -> Optional[dict]:
    """The reference for a mid-take RE-READ (founder 2026-07-17): the parent
    SPOKEN take's own pieces. A re-read is 1–2 pieces — far too few to z-score
    against itself — so without this it fell to the cold-start neutral and the
    coach's needle never moved. None when the parent take is too short to be a
    reference (callers then keep the existing degradation). Best-effort."""
    return _baseline_from_metrics(
        _session_piece_metrics(parent_session_id, database=database),
        _BASELINE_MIN_SAMPLES_PARENT,
    )


def resolve_read_baseline(user_id: Optional[str], *, recording_kind: str = "spoken",
                          paired_session_id: Any = None,
                          database=None) -> tuple:
    """The reference this recording's z-scores are measured against, in
    priority order (founder 2026-07-17):

      1. the speaker's own cross-take baseline (stable, best);
      2. for a RE-READ with no user baseline: its PARENT take's pieces —
         same speaker/session/mic, and the comparison the coach wants;
      3. None → the caller's within-take / cold-start behaviour, unchanged.

    Returns (baseline|None, kind) where kind ∈ {"user", "parent_take", None}
    — `kind` rides the stamped blob so the coach packet is honest about what
    the needle was measured against. Best-effort; never raises."""
    try:
        base = build_user_baseline(user_id, database=database)
        if base:
            return base, "user"
        if recording_kind == "read" and paired_session_id:
            parent = build_parent_take_baseline(
                paired_session_id, database=database)
            if parent:
                return parent, "parent_take"
    except Exception as e:
        logger.warning("acoustic_read: baseline resolve failed: %s", e)
    return None, None


def attach_acoustic_read(pieces: list, *, baseline: Optional[dict] = None,
                         baseline_kind: Optional[str] = None) -> None:
    """Stamp metrics["acoustic_read"] on every piece dict (in place):

        {"potentiometer": float in [-1, 1],   # stress −1 … +1 charisma
         "outside_normal_range": bool,        # any component |z| ≥ 2.0
         "baseline": "user" | "parent_take" | "take",   # the reference used
         "version": "acoustic-read-v1"}

    ``pieces`` = the record-time piece dicts (each with a "metrics" dict —
    a piece whose metrics are missing/empty gets NO read stamped: an honest
    absence, not a fake-neutral 0.0). ``baseline_kind`` names the reference
    for the coach packet's provenance (defaults to "user" when a baseline is
    passed without a kind — the pre-2026-07-17 behaviour). Deterministic;
    never raises."""
    try:
        usable = [p for p in (pieces or []) if isinstance(p, dict)]
        if not usable:
            return
        _kind = baseline_kind or ("user" if baseline else "take")
        # Cold-start floor — within-take z on too few pieces is noise. Stamp a
        # neutral read (so the coach still sees "computed, nothing notable")
        # rather than a pegged needle. Bypassed whenever a REAL reference (the
        # speaker's baseline, or a re-read's parent take) anchors the z-scores
        # against a stable distribution rather than the tiny local pool.
        cold_start = not baseline
        if cold_start and len(usable) < _MIN_PIECES_FOR_WITHIN_TAKE_READ:
            for p in usable:
                m = p.get("metrics")
                if isinstance(m, dict) and m:
                    m["acoustic_read"] = {
                        "potentiometer": 0.0,
                        "outside_normal_range": False,
                        "baseline": "take",
                        "version": _READ_VERSION,
                    }
            return
        scores = score_control_direction(usable, baseline=baseline)
        # Per-feature |z| for the out-of-range flag — same reference as the
        # composite (speaker baseline when present, else within-take).
        per_feature_z: dict = {}
        for name, _w in _CONTROL_COMPONENTS:
            vals = [
                (p.get("metrics") or {}).get(name)
                if isinstance(p.get("metrics"), dict) else None
                for p in usable
            ]
            base = (baseline or {}).get(name) if baseline else None
            per_feature_z[name] = _zscore_column(vals, base)
        for i, p in enumerate(usable):
            m = p.get("metrics")
            if not isinstance(m, dict) or not m:
                continue
            # No usable control component at all → no read (short pieces
            # under the 1s metrics floor land here).
            has_component = any(
                isinstance(m.get(name), (int, float))
                and not isinstance(m.get(name), bool)
                for name, _w in _CONTROL_COMPONENTS
            )
            if not has_component:
                continue
            z_sum = scores[i] if i < len(scores) else 0.0
            max_abs_z = max(
                (abs(per_feature_z[name][i]) for name, _w in _CONTROL_COMPONENTS
                 if i < len(per_feature_z[name])),
                default=0.0,
            )
            m["acoustic_read"] = {
                "potentiometer": round(
                    math.tanh(_SQUASH_SCALE * float(z_sum)), 3),
                "outside_normal_range": bool(max_abs_z >= _OUT_OF_RANGE_Z),
                "baseline": _kind,
                "version": _READ_VERSION,
            }
    except Exception as e:
        logger.warning("acoustic_read: attach failed (non-fatal): %s", e)


def tone_hint(read: Any) -> Optional[str]:
    """The acoustic tone word for the auto-comment: 'confident' when the
    needle leans charisma, 'stressed' when it leans stress, None in the
    middle. Qualitative input to a sentence — never surfaced as a value."""
    if not isinstance(read, dict):
        return None
    v = read.get("potentiometer")
    if not isinstance(v, (int, float)):
        return None
    if v >= TONE_HINT_THRESHOLD:
        return "confident"
    if v <= -TONE_HINT_THRESHOLD:
        return "stressed"
    return None
