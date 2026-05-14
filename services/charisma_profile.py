"""Charisma-Awareness Dashboard payload builder + persistor.

Assembles the ``charisma_profile`` JSONB the /results page reads to
render its radar / heatmap / archetype / recommendation cards.
Computed once during session-finalize (publish) and admin compute-
metrics; persisted to ``v2_sessions.charisma_profile``; read straight
off the row by the BFF endpoints.

Public surface
--------------
- ``build_charisma_profile(...)`` — pure aggregation, no LLM, no
  DB. Always returns a shape-complete dict so callers (tests,
  preview tools) get something usable even on sparse input.
- ``compute_and_persist_charisma_profile(session_id, user_id)`` —
  the production entry. Loads inputs, builds the deterministic
  blob, layers in LLM-generated insight + recommendation (one
  call, with deterministic fallback), and writes the result to
  ``v2_sessions.charisma_profile``. Returns the persisted blob or
  ``None`` when the session is too sparse to bother.
- ``generate_charisma_profile(session_id, user_id)`` — kept as a
  thin alias over ``compute_and_persist_charisma_profile`` so any
  caller wired up before persistence existed still works.

Contract
--------
Six required sub-objects when ``charisma_profile`` is non-null:
``archetype``, ``narrative``, ``acoustics``, ``trinity``,
``triggers``, ``recommendation``. The frontend treats partial
objects as a runtime error, so every block in here is forced
shape-complete even when the underlying data is missing.

Why we LLM ``trinity.insight`` and ``recommendation`` (but not the
rest):
- the deterministic blocks describe *what* — numbers, archetype
  labels, peak topics. Cheap and reliable.
- the LLM blocks describe *what to do about it* — phrased the way
  a coach would phrase it. Worth one call per finalize/recompute,
  cached, never invoked on the read path.
- failure mode: if the LLM call fails (no key, timeout, parse
  error), we land on deterministic copies that are good enough to
  ship. Recompute later → real LLM read.

Why a "too-sparse" gate
-----------------------
The narrative we want is "you delivered N minutes of audio and we
noticed X." If the session has no acoustic signal at all (zero
WPM measurements, no fillers tracked, no snippets), every block
falls back to neutral 0.5 / "—" / empty arrays — that's a
dashboard that *technically* renders but is worse than hiding.
``compute_and_persist_charisma_profile`` returns ``None`` (and
writes ``NULL`` to the column) in that case so the frontend hides
the section entirely.
"""
from __future__ import annotations

import json
import logging
import statistics
from collections import Counter
from typing import Any, Optional

from services.db import db


logger = logging.getLogger(__name__)


# ── Dashboard contract constants ────────────────────────────────────

# Pace band the dashboard surfaces — tighter than the
# normalize_pace target (120-160) so the on-screen "ideal" range
# matches what we coach toward, not what we tolerate.
_IDEAL_WPM_MIN = 125
_IDEAL_WPM_MAX = 140

# Trinity neutral default when no signal exists for a dimension.
_TRINITY_NEUTRAL = 0.5

# Filler-density saturation (per minute). 0 fillers/min → 1.0;
# 12+/min → 0. Same threshold across power-input, presence-input
# and per-snippet flow so the dashboard's "stressed-delivery"
# read is consistent.
_FILLER_PER_MIN_SAT = 12.0

# Dynamic-dB normalisation range. 15 dB → 0; 35 dB → 1; linear
# in between. Below 15 reads flat, above 35 plateaus.
_DYNAMIC_DB_MIN = 15.0
_DYNAMIC_DB_MAX = 35.0

# Pause variability normalisation. Std-dev of per-snippet
# pause_ms expressed as a fraction of session mean. 0 → 1.0;
# 1.0+ (std equals mean → very erratic) → 0.
_PAUSE_CV_SAT = 1.0

# Archetype proximity thresholds — read directly from spec.
# All three within this delta → "Balanced Communicator".
_ARCHETYPE_BALANCED_DELTA = 0.10
# Top two within this delta → pair-dominant archetype.
_ARCHETYPE_PAIR_DELTA = 0.05

# LLM model + token budget for insight + recommendation.
_LLM_MODEL = "gpt-4o-mini"
_LLM_MAX_TOKENS = 300


# ── Public entries ──────────────────────────────────────────────────


def build_charisma_profile(
    *,
    session: dict,
    snippets: list[dict],
    learner_profile: Optional[dict],
    mirror: Optional[dict],
) -> dict[str, Any]:
    """Pure-aggregation build of the full payload.

    Returned dict is shape-complete (every required key present,
    every nested object with all spec keys). ``trinity.insight`` and
    ``recommendation`` are deterministic here — the LLM upgrade
    happens in ``compute_and_persist_charisma_profile`` so callers
    that just want the structural blob (tests, preview, ad-hoc
    inspection) don't pay for an OpenAI round-trip.
    """
    snippets_sorted = _sort_snippets(snippets or [])

    acoustics = _build_acoustics(session or {}, snippets_sorted)
    trinity = _build_trinity(session or {}, snippets_sorted, learner_profile)
    triggers = _build_triggers(session or {}, snippets_sorted)
    archetype = _build_archetype(trinity)
    recommendation = _deterministic_recommendation(trinity, archetype, triggers)
    narrative = _build_narrative(session=session or {}, mirror=mirror)
    # Deterministic insight — overwritten by the LLM layer when the
    # caller goes through compute_and_persist.
    trinity["insight"] = _deterministic_trinity_insight(trinity, archetype)

    return {
        "archetype": archetype,
        "narrative": narrative,
        "acoustics": acoustics,
        "trinity": trinity,
        "triggers": triggers,
        "recommendation": recommendation,
    }


def compute_and_persist_charisma_profile(
    session_id: str,
    user_id: str,
) -> Optional[dict[str, Any]]:
    """Production entry — load, build, LLM-upgrade, persist.

    Called by:
      - the publish-session-results internal endpoint (first compute
        on session finalize)
      - the admin compute-metrics endpoint (overwrite on demand)

    Returns the persisted blob, or ``None`` when the session has no
    usable signal (no WPM, no snippets, no acoustic averages). In
    the None case we also write NULL to the column so a stale blob
    from a prior compute doesn't linger and mislead the dashboard.
    """
    try:
        session = db.v2_get_session_by_id(session_id) or {}
    except Exception as e:
        logger.warning(
            "charisma_profile: session load failed sid=%s err=%s",
            session_id, e,
        )
        session = {}

    if session and str(session.get("user_id") or "") != str(user_id):
        # Caller passed the wrong user — refuse to persist anything
        # under that session, but don't raise.
        logger.warning(
            "charisma_profile: owner mismatch sid=%s uid=%s actual=%s",
            session_id, user_id, session.get("user_id"),
        )
        return None

    try:
        snippets = db.get_snippets_by_session(session_id) or []
    except Exception as e:
        logger.warning(
            "charisma_profile: snippet load failed sid=%s err=%s",
            session_id, e,
        )
        snippets = []

    settings: dict = {}
    try:
        settings = db.get_user_settings(user_id) or {}
    except Exception as e:
        logger.warning(
            "charisma_profile: settings load failed uid=%s err=%s",
            user_id, e,
        )
    learner_profile = settings.get("inferred_learner_profile") or None
    mirror = settings.get("current_learner_mirror") or None

    if not _has_usable_signal(session, snippets):
        # Too sparse to render anything honest. Clear the column so
        # the dashboard stays hidden rather than showing stale data.
        try:
            db.update_session_charisma_profile(session_id, None)
        except Exception as e:
            logger.warning(
                "charisma_profile: null-clear failed sid=%s err=%s",
                session_id, e,
            )
        return None

    payload = build_charisma_profile(
        session=session,
        snippets=snippets,
        learner_profile=learner_profile,
        mirror=mirror,
    )

    # LLM upgrade — one call returns both insight + recommendation.
    # Failure leaves the deterministic strings build_charisma_profile
    # already wrote in place.
    upgraded = _llm_insight_and_recommendation(
        trinity=payload["trinity"],
        archetype=payload["archetype"],
        triggers=payload["triggers"],
        acoustics=payload["acoustics"],
    )
    if upgraded is not None:
        if upgraded.get("insight"):
            payload["trinity"]["insight"] = upgraded["insight"]
        if upgraded.get("recommendation"):
            payload["recommendation"] = upgraded["recommendation"]

    try:
        db.update_session_charisma_profile(session_id, payload)
    except Exception as e:
        logger.error(
            "charisma_profile: persist failed sid=%s err=%s",
            session_id, e,
        )
        # Caller gets the computed blob anyway so a publish flow can
        # still email the user the right archetype; just the cache
        # write didn't land.

    return payload


def generate_charisma_profile(
    session_id: str,
    user_id: str,
) -> Optional[dict[str, Any]]:
    """Back-compat alias for ``compute_and_persist_charisma_profile``.

    Pre-persistence callers used this name. Keeping the alias means
    the route handler that wires the dedicated GET endpoint doesn't
    need a parallel rename.
    """
    return compute_and_persist_charisma_profile(session_id, user_id)


# ── Sparseness gate ─────────────────────────────────────────────────


def _has_usable_signal(session: dict, snippets: list[dict]) -> bool:
    """True when there's *anything* worth rendering.

    Bar is intentionally low: at least one WPM measurement OR at
    least one snippet with duration. We'd rather show a partial
    dashboard than hide a real session because filler counts
    happened to be missing.
    """
    if _to_float(session.get("global_wpm")) is not None:
        return True
    for s in snippets:
        if _to_int(s.get("duration_ms")) and _to_int(s.get("duration_ms")) > 0:
            return True
        if _to_float(s.get("wpm")) is not None:
            return True
    return False


# ── Acoustics ──────────────────────────────────────────────────────


def _build_acoustics(session: dict, snippets: list[dict]) -> dict[str, Any]:
    """Session-level pace + ideal band + peak topic + per-turn timeline.

    Spec contract:
      pace      — int WPM (session avg)
      idealMin  — int WPM (125)
      idealMax  — int WPM (140)
      peakTopic — string (free text)
      timeline  — list of { t: "T<n>", wpm: int } per snippet with WPM
    """
    wpms = [
        _to_float(s.get("wpm"))
        for s in snippets
        if _to_float(s.get("wpm")) is not None and _to_float(s.get("wpm")) > 0
    ]
    if wpms:
        pace_int: Optional[int] = int(round(sum(wpms) / len(wpms)))
    else:
        # Fall back to the global column so the band still anchors
        # somewhere meaningful even when per-snippet WPM is missing.
        raw_global = _to_float(session.get("global_wpm"))
        pace_int = int(round(raw_global)) if raw_global else None

    timeline: list[dict[str, Any]] = []
    turn_idx = 1
    for s in snippets:
        wpm_raw = _to_float(s.get("wpm"))
        if wpm_raw is None or wpm_raw <= 0:
            # Skip rows where WPM wasn't measured — dashboard
            # shouldn't plot a 0 point. Don't bump turn_idx either;
            # the on-screen tick should match the *measured* turns.
            continue
        timeline.append({
            "t": f"T{turn_idx}",
            "wpm": int(round(wpm_raw)),
        })
        turn_idx += 1

    peak_topic = _peak_topic(session, snippets)

    return {
        "pace": pace_int,
        "idealMin": _IDEAL_WPM_MIN,
        "idealMax": _IDEAL_WPM_MAX,
        "peakTopic": peak_topic,
        "timeline": timeline,
    }


def _peak_topic(session: dict, snippets: list[dict]) -> Optional[str]:
    """Topic of the strongest snippet. Falls back to stickiness top
    topic when per-snippet topic data isn't available — which is
    almost always the case in v1 since snippets only carry
    ``question_text``, not a discrete topic label."""
    # Best snippet by simple per-snippet quality proxy. Most
    # interesting interpretation of "highest engagement" we can
    # cheaply compute today.
    best_score = -1.0
    best_snippet: Optional[dict] = None
    for s in snippets:
        sc = _snippet_quality_score(s)
        if sc is None:
            continue
        if sc > best_score:
            best_score = sc
            best_snippet = s
    if best_snippet is not None:
        for field in ("topic", "question_text"):
            label = (best_snippet.get(field) or "").strip()
            if label:
                return label[:80]

    top = (session.get("stickiness_top_topic") or "").strip()
    return top or None


# ── Trinity ─────────────────────────────────────────────────────────


def _build_trinity(
    session: dict,
    snippets: list[dict],
    learner_profile: Optional[dict],
) -> dict[str, Any]:
    """Three normalised 0..1 scores + a one-line insight.

    Spec — each axis is a *weighted* composite of three signals.
    Missing signals drop out of the average (we re-normalise over
    the surviving weights), so a dimension with one valid input
    still produces a meaningful number instead of bias from a
    constant fill-value.

      POWER    = 0.5·engagement + 0.3·norm(dynamic_db) + 0.2·(1 − norm(filler_density))
      WARMTH   = 0.6·emotional_movement + 0.4·norm(pitch_range)
      PRESENCE = 0.5·flow + 0.3·specificity + 0.2·(1 − norm(pause_variability))

    ``engagement``, ``emotional_movement``, ``specificity`` come
    from ``learner_profile.traits.score_per_component`` — the
    Phase-3/Phase-4 aggregate. We use the user-level aggregate
    rather than per-session because v1 snippets don't carry
    per-attempt evaluator components (those live on
    ``coaching_attempts``, which most onboarding snippets don't
    spawn). Future enhancement: average per-session coaching
    attempts when present.

    ``flow`` is computed from session filler density — same
    threshold as the per-snippet ``1 − flow`` intensity on
    triggers, so the dashboard's overall fluency read and its
    heatmap agree on what 'stressed delivery' looks like.
    """
    engagement = _component_avg(learner_profile, "engagement")
    emotional_movement = _component_avg(learner_profile, "emotional_movement")
    specificity = _component_avg(learner_profile, "specificity")

    dynamic_db_norm = _norm_dynamic_db(session)
    filler_inv = _inv_filler_density(session, snippets)
    flow = _flow_score(session, snippets)
    pitch_range_norm = _norm_pitch_range(snippets)
    pause_var_inv = _inv_pause_variability(snippets)

    power = _weighted_average([
        (0.5, engagement),
        (0.3, dynamic_db_norm),
        (0.2, filler_inv),
    ])
    warmth = _weighted_average([
        (0.6, emotional_movement),
        (0.4, pitch_range_norm),
    ])
    presence = _weighted_average([
        (0.5, flow),
        (0.3, specificity),
        (0.2, pause_var_inv),
    ])

    return {
        "power": round(power, 4),
        "warmth": round(warmth, 4),
        "presence": round(presence, 4),
        # Insight is filled by build_charisma_profile (deterministic)
        # or compute_and_persist_charisma_profile (LLM upgrade).
        "insight": "",
    }


def _weighted_average(pairs: list[tuple[float, Optional[float]]]) -> float:
    """Weighted mean over present (non-None) inputs.

    When every input is None → 0.5 neutral. When some are present,
    weights of the missing ones are dropped and the rest re-
    normalised so the result is still a proper [0,1] average.
    """
    num = 0.0
    denom = 0.0
    for w, v in pairs:
        if v is None:
            continue
        num += w * _clamp01(v)
        denom += w
    if denom <= 0:
        return _TRINITY_NEUTRAL
    return num / denom


def _component_avg(
    learner_profile: Optional[dict],
    key: str,
) -> Optional[float]:
    """Read an evaluator-component aggregate (0..1) from the
    learner profile. None when missing."""
    if not isinstance(learner_profile, dict):
        return None
    traits = learner_profile.get("traits") or {}
    per_component = traits.get("score_per_component") or {}
    if not isinstance(per_component, dict):
        return None
    return _to_float(per_component.get(key))


def _norm_dynamic_db(session: dict) -> Optional[float]:
    """Map session global_dynamic_db to 0..1.

    15 dB → 0, 35 dB → 1. Higher dynamic range = more vocal
    authority = more Power.
    """
    raw = _to_float(session.get("global_dynamic_db"))
    if raw is None:
        return None
    return _clamp01(
        (raw - _DYNAMIC_DB_MIN) / (_DYNAMIC_DB_MAX - _DYNAMIC_DB_MIN)
    )


def _inv_filler_density(
    session: dict,
    snippets: list[dict],
) -> Optional[float]:
    """Inverse of session-level filler density (per minute).

    Prefer per-snippet sum (lets the dashboard agree with the
    heatmap), fall back to global_fillers + cumulative duration if
    per-snippet data is empty.
    """
    fillers_total = 0
    duration_ms_total = 0
    for s in snippets:
        f = _to_int(s.get("fillers"))
        d = _to_int(s.get("duration_ms"))
        if f is not None:
            fillers_total += f
        if d is not None and d > 0:
            duration_ms_total += d
    if duration_ms_total <= 0:
        # Fall back to the session row's globals.
        fillers_global = _to_int(session.get("global_fillers"))
        if fillers_global is None:
            return None
        # No per-minute basis available — saturate against the
        # absolute threshold the spec uses for the global blob.
        return _clamp01(1.0 - (fillers_global / _FILLER_PER_MIN_SAT))
    per_minute = fillers_total / (duration_ms_total / 60000.0)
    return _clamp01(1.0 - per_minute / _FILLER_PER_MIN_SAT)


def _flow_score(
    session: dict,
    snippets: list[dict],
) -> Optional[float]:
    """Delivery-fluency proxy. Same input as _inv_filler_density —
    keep them in lockstep so 'flow' and 'low fillers' don't
    disagree on the same session.
    """
    return _inv_filler_density(session, snippets)


def _norm_pitch_range(snippets: list[dict]) -> Optional[float]:
    """Map pitch-range (semitones spread across snippets) to 0..1.

    1 semitone → 0; 8+ semitones → 1. More melodic variation reads
    warmer — flat monotone is the cold extreme.
    """
    centers = [
        _to_float(s.get("pitch_center"))
        for s in snippets
        if _to_float(s.get("pitch_center")) is not None
    ]
    if len(centers) < 2:
        return None
    span = max(centers) - min(centers)
    return _clamp01((span - 1.0) / (8.0 - 1.0))


def _inv_pause_variability(snippets: list[dict]) -> Optional[float]:
    """Inverse coefficient-of-variation of pause_ms across snippets.

    Tight, consistent pauses → high presence (1.0); erratic pauses
    → low (0). Coefficient of variation = std / mean — scale-free,
    so a fast and a slow speaker get judged on their own consistency.
    Needs ≥ 2 snippets with pause data; returns None below that.
    """
    pauses = [
        _to_float(s.get("pause_ms"))
        for s in snippets
        if _to_float(s.get("pause_ms")) is not None
    ]
    if len(pauses) < 2:
        return None
    mean = sum(pauses) / len(pauses)
    if mean <= 0:
        return None
    try:
        stdev = statistics.pstdev(pauses)
    except statistics.StatisticsError:
        return None
    cv = stdev / mean
    return _clamp01(1.0 - cv / _PAUSE_CV_SAT)


# ── Archetype ───────────────────────────────────────────────────────


def _build_archetype(trinity: dict) -> str:
    """7-tier archetype mapping per spec.

    Single-axis dominance:
      POWER lead    → "The Decisive Leader"
      WARMTH lead   → "The Trusted Confidant"
      PRESENCE lead → "The Calm Anchor"

    Pair-dominance (top two within 0.05):
      POWER + WARMTH    → "The Visionary Leader"
      WARMTH + PRESENCE → "The Empathic Communicator"
      POWER + PRESENCE  → "The Composed Authority"

    All three within 0.10 of each other:
      → "The Balanced Communicator"
    """
    p = trinity.get("power") or 0.0
    w = trinity.get("warmth") or 0.0
    pr = trinity.get("presence") or 0.0
    scores = {"power": p, "warmth": w, "presence": pr}

    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (top_axis, top_val), (mid_axis, mid_val), (bot_axis, bot_val) = ordered

    # All three close — balanced.
    if top_val - bot_val < _ARCHETYPE_BALANCED_DELTA:
        return "The Balanced Communicator"

    # Top two within pair threshold — pair archetype.
    if top_val - mid_val < _ARCHETYPE_PAIR_DELTA:
        pair = frozenset([top_axis, mid_axis])
        if pair == frozenset({"power", "warmth"}):
            return "The Visionary Leader"
        if pair == frozenset({"warmth", "presence"}):
            return "The Empathic Communicator"
        if pair == frozenset({"power", "presence"}):
            return "The Composed Authority"

    # Single-axis dominant.
    return {
        "power": "The Decisive Leader",
        "warmth": "The Trusted Confidant",
        "presence": "The Calm Anchor",
    }[top_axis]


# ── Triggers ────────────────────────────────────────────────────────


def _build_triggers(
    session: dict,
    snippets: list[dict],
) -> dict[str, Any]:
    """Heatmap-style trigger payload — stress-snippet-anchored.

    Spec semantics:
      topTheme         — most common theme across stress snippets
                          (snippet_type == 'stress' OR coach_label
                          == 'stress'). Falls back to lowest-
                          quality non-stress snippet, then to
                          session stickiness top topic.
      pitchDelta       — max pitch deviation on stress snippets vs
                          session-mean baseline, in semitones,
                          formatted as "+N.N st" / "-N.N st".
      fillerMultiplier — (stress filler density) / (charisma filler
                          density), floored at "1.0x" — never report
                          a multiplier below baseline.
      points           — one entry per stress snippet:
                          t = (start_offset_ms / total_session_ms)·100
                          intensity = 1 − snippet quality score
    """
    stress_snips, charisma_snips = _partition_by_coach_label(snippets)

    top_theme = _stress_top_theme(stress_snips, snippets, session)
    pitch_delta = _format_pitch_delta(stress_snips, snippets)
    filler_multiplier = _format_filler_multiplier(stress_snips, charisma_snips)
    points = _stress_points(stress_snips, snippets)

    return {
        "topTheme": top_theme,
        "pitchDelta": pitch_delta,
        "fillerMultiplier": filler_multiplier,
        "points": points,
    }


def _partition_by_coach_label(
    snippets: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Split snippets into (stress, charisma) by coach_label /
    snippet_type. Anything not explicitly labelled either way
    drops out — we don't want unlabelled snippets diluting the
    stress vs charisma comparison."""
    stress: list[dict] = []
    charisma: list[dict] = []
    for s in snippets:
        label = (s.get("coach_label") or s.get("snippet_type") or "").lower()
        if label == "stress":
            stress.append(s)
        elif label == "charisma":
            charisma.append(s)
    return stress, charisma


def _stress_top_theme(
    stress_snips: list[dict],
    all_snips: list[dict],
    session: dict,
) -> Optional[str]:
    """Most common theme across stress snippets.

    Snippets don't carry a discrete topic label, so we approximate
    by clustering on ``question_text`` (which most directed turns
    carry). Falls back to the lowest-quality non-stress snippet's
    theme, then to the session stickiness top topic.
    """
    counts: Counter[str] = Counter()
    for s in stress_snips:
        label = (s.get("question_text") or s.get("topic") or "").strip()
        if label:
            counts[label[:80]] += 1
    if counts:
        return counts.most_common(1)[0][0]

    # No labelled stress snippets — fall back to lowest-engagement
    # non-stress snippet. Spec: "If none labeled stress, return the
    # lowest-engagement topic instead."
    worst_score = 1.1
    worst_label: Optional[str] = None
    for s in all_snips:
        sc = _snippet_quality_score(s)
        if sc is None:
            continue
        if sc < worst_score:
            worst_score = sc
            for field in ("question_text", "topic"):
                cand = (s.get(field) or "").strip()
                if cand:
                    worst_label = cand[:80]
                    break
    if worst_label:
        return worst_label

    sticky = (session.get("stickiness_top_topic") or "").strip()
    return sticky or None


def _format_pitch_delta(
    stress_snips: list[dict],
    all_snips: list[dict],
) -> str:
    """Max pitch deviation on stress snippets vs session-mean
    baseline, in semitones (pitch_center is already stored in
    semitones — recompute_metrics_v2 hands us pitch_center_st).

    Format: "+N.N st" / "-N.N st" with a space. When the data is
    insufficient we return "—" so the card doesn't show a
    misleading 0.0.
    """
    baseline_pool = [
        _to_float(s.get("pitch_center"))
        for s in all_snips
        if _to_float(s.get("pitch_center")) is not None
    ]
    if not baseline_pool:
        return "—"
    baseline = sum(baseline_pool) / len(baseline_pool)

    stress_pitches = [
        _to_float(s.get("pitch_center"))
        for s in stress_snips
        if _to_float(s.get("pitch_center")) is not None
    ]
    if not stress_pitches:
        # No stress snippets — fall back to session-wide max
        # deviation, which at least answers "did this user's pitch
        # vary at all this session?"
        if len(baseline_pool) < 2:
            return "—"
        spread = max(baseline_pool) - min(baseline_pool)
        return _fmt_semitone_signed(spread)

    # Signed max deviation: pick whichever extreme (above or below
    # baseline) is largest in absolute value, keep its sign so the
    # card communicates direction.
    deltas = [p - baseline for p in stress_pitches]
    pick = max(deltas, key=abs)
    return _fmt_semitone_signed(pick)


def _fmt_semitone_signed(v: float) -> str:
    """+N.N st / -N.N st with the U+2212 minus and a space."""
    if v >= 0:
        return f"+{v:.1f} st"
    return f"−{abs(v):.1f} st"


def _format_filler_multiplier(
    stress_snips: list[dict],
    charisma_snips: list[dict],
) -> str:
    """(stress filler density) ÷ (charisma filler density), as Nx.

    Floor at "1.0x" — the spec is explicit: never report < 1.0x
    because "fewer fillers under stress than at baseline" isn't
    a meaningful trigger reading, just noise. Returns "—" if either
    side has zero duration.
    """
    stress_density = _filler_density_per_min(stress_snips)
    charisma_density = _filler_density_per_min(charisma_snips)
    if stress_density is None or charisma_density is None:
        return "—"
    if charisma_density <= 0:
        # Charisma side had zero fillers — the ratio is ∞ or
        # undefined. Treat as 1.0x (no signal) rather than printing
        # a garbage huge number.
        if stress_density <= 0:
            return "1.0x"
        return "—"
    ratio = stress_density / charisma_density
    ratio = max(1.0, ratio)
    return f"{ratio:.1f}x"


def _filler_density_per_min(snippets: list[dict]) -> Optional[float]:
    """Sum fillers / sum duration · 60_000. None when no usable rows."""
    total_fillers = 0
    total_ms = 0
    for s in snippets:
        f = _to_int(s.get("fillers"))
        d = _to_int(s.get("duration_ms"))
        if f is None or d is None or d <= 0:
            continue
        total_fillers += f
        total_ms += d
    if total_ms <= 0:
        return None
    return total_fillers / (total_ms / 60000.0)


def _stress_points(
    stress_snips: list[dict],
    all_snips: list[dict],
) -> list[dict[str, Any]]:
    """One entry per stress snippet.

      t         = (start_offset_ms / total_session_ms) · 100
                  clamped to [0, 100]
      intensity = 1 − snippet quality score, clamped to [0, 1]

    Total session ms is the sum of every snippet's duration (not
    just stress snippets), so the percentage anchors the trigger
    to its position in the session as a whole.
    """
    total_ms = sum(int(s.get("duration_ms") or 0) for s in all_snips)
    if total_ms <= 0:
        return []

    points: list[dict[str, Any]] = []
    for s in stress_snips:
        start_ms_raw = _to_int(s.get("start_offset_ms")) or 0
        t_pct = (start_ms_raw / total_ms) * 100.0
        t_pct = max(0.0, min(100.0, t_pct))
        quality = _snippet_quality_score(s)
        if quality is None:
            continue
        intensity = _clamp01(1.0 - quality)
        points.append({
            "t": round(t_pct, 1),
            "intensity": round(intensity, 4),
        })
    return points


def _snippet_quality_score(s: dict) -> Optional[float]:
    """Per-snippet quality proxy (0..1).

    Mean of:
      - pace-in-band score (1 inside ideal, falls off outside)
      - 1 - filler density per minute (saturated at the same
        threshold as session-level flow)
    Returns None when neither input is computable.
    """
    parts: list[float] = []
    wpm = _to_float(s.get("wpm"))
    if wpm is not None and wpm > 0:
        if _IDEAL_WPM_MIN <= wpm <= _IDEAL_WPM_MAX:
            parts.append(1.0)
        elif wpm < _IDEAL_WPM_MIN:
            parts.append(_clamp01((wpm - 80) / (_IDEAL_WPM_MIN - 80)))
        else:
            parts.append(_clamp01((200 - wpm) / (200 - _IDEAL_WPM_MAX)))

    f = _to_int(s.get("fillers"))
    d = _to_int(s.get("duration_ms"))
    if f is not None and d is not None and d > 0:
        per_minute = f / (d / 60000.0)
        parts.append(_clamp01(1.0 - per_minute / _FILLER_PER_MIN_SAT))

    if not parts:
        return None
    return sum(parts) / len(parts)


# ── Narrative ───────────────────────────────────────────────────────


def _build_narrative(*, session: dict, mirror: Optional[dict]) -> str:
    """Prefer the session's KPI narrative (already AI-written during
    finalize), then the cached learner-mirror narrative, then a
    spec fallback string so the field is never empty."""
    kpi_narrative = (session.get("ai_task_alignment_comment") or "").strip()
    if kpi_narrative:
        return kpi_narrative

    if isinstance(mirror, dict):
        cached = (mirror.get("narrative") or "").strip()
        if cached:
            return cached

    return (
        "Your acoustic baseline has been captured. Complete more "
        "scenarios to unlock your deep narrative."
    )


# ── Deterministic insight + recommendation (fallback / preview) ────


def _deterministic_trinity_insight(trinity: dict, archetype: str) -> str:
    """One sentence framing the lead vs lag axes. Used as the
    deterministic baseline; the LLM upgrade in
    compute_and_persist replaces this with a coach-toned line."""
    scores = {
        "Power": trinity.get("power") or 0.0,
        "Warmth": trinity.get("warmth") or 0.0,
        "Presence": trinity.get("presence") or 0.0,
    }
    top = max(scores, key=scores.get)
    bot = min(scores, key=scores.get)
    if scores[top] - scores[bot] < _ARCHETYPE_BALANCED_DELTA:
        return (
            f"Your profile is balanced — Power, Warmth and Presence "
            f"each near {scores[top]:.2f}."
        )
    return f"{top} leads at {scores[top]:.2f}; {bot} lags at {scores[bot]:.2f}."


def _deterministic_recommendation(
    trinity: dict,
    archetype: str,
    triggers: dict,
) -> dict[str, str]:
    """Spec-shaped recommendation built off the weakest axis. The
    LLM upgrade replaces this with copy anchored on the highest-
    intensity trigger point; this version is what ships when the
    LLM is unavailable."""
    scores = {
        "Power": trinity.get("power") or 0.0,
        "Warmth": trinity.get("warmth") or 0.0,
        "Presence": trinity.get("presence") or 0.0,
    }
    weakest = min(scores, key=scores.get)
    body_by_axis = {
        "Power": (
            "Your warmth and presence are strong — let's practise "
            "Power under pressure on the next scenario."
        ),
        "Warmth": (
            "Your authority is strong — let's practise Warmth under "
            "fire on the next scenario."
        ),
        "Presence": (
            "Your authority is strong — let's anchor Presence under "
            "fire on the next scenario."
        ),
    }
    return {
        "title": "Ready for your next stress-test?",
        "body": body_by_axis[weakest],
    }


# ── LLM insight + recommendation ────────────────────────────────────


def _llm_insight_and_recommendation(
    *,
    trinity: dict,
    archetype: str,
    triggers: dict,
    acoustics: dict,
) -> Optional[dict[str, Any]]:
    """One structured-output call returning both insight and
    recommendation. None on any failure — caller keeps the
    deterministic strings already in the payload.

    We do this once per finalize/recompute, cache in the JSONB
    column, and never invoke from the read path. ~250 tokens out,
    so cost is bounded.
    """
    try:
        from services.openai_service import OpenAIService
        service = OpenAIService()
    except Exception as e:
        logger.warning("charisma_profile: openai import failed: %s", e)
        return None
    if not service.client:
        return None

    peak_intensity_point = _peak_trigger_point(triggers)
    system = (
        "You write short coaching copy for a Charisma Awareness "
        "Dashboard. Voice: warm, specific, second-person. No "
        "therapy-speak, no motivational fluff. Ground every claim "
        "in the data the user gives you — do not invent numbers, "
        "do not invent moments."
    )
    user_prompt = (
        "TRINITY\n"
        f"  Power:    {trinity.get('power', 0):.2f}\n"
        f"  Warmth:   {trinity.get('warmth', 0):.2f}\n"
        f"  Presence: {trinity.get('presence', 0):.2f}\n"
        f"ARCHETYPE: {archetype}\n"
        "TRIGGERS\n"
        f"  topTheme:         {triggers.get('topTheme') or '—'}\n"
        f"  pitchDelta:       {triggers.get('pitchDelta') or '—'}\n"
        f"  fillerMultiplier: {triggers.get('fillerMultiplier') or '—'}\n"
        f"  peak point:       {_peak_point_label(peak_intensity_point)}\n"
        "ACOUSTICS\n"
        f"  pace: {acoustics.get('pace')} wpm "
        f"(ideal {acoustics.get('idealMin')}-{acoustics.get('idealMax')})\n"
        f"  peakTopic: {acoustics.get('peakTopic') or '—'}\n"
        "\n"
        "Return STRICT JSON with two top-level keys:\n"
        "  insight        — one sentence, ≤ 25 words, naming which "
        "trinity axis leads and which lags. Reference the numbers "
        "above; do not paraphrase to new ones.\n"
        "  recommendation — object with `title` (≤ 6 words, action-"
        "shaped) and `body` (≤ 35 words). Anchor body on the "
        "highest-intensity trigger point above — reference its "
        "timing or its signal (pitchDelta / fillerMultiplier)."
    )

    schema = {
        "name": "charisma_insight_recommendation",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["insight", "recommendation"],
            "properties": {
                "insight": {"type": "string", "maxLength": 240},
                "recommendation": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["title", "body"],
                    "properties": {
                        "title": {"type": "string", "maxLength": 60},
                        "body": {"type": "string", "maxLength": 300},
                    },
                },
            },
        },
        "strict": True,
    }

    try:
        response = service.client.chat.completions.create(
            model=_LLM_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=_LLM_MAX_TOKENS,
            temperature=0.5,
            response_format={"type": "json_schema", "json_schema": schema},
        )
        raw = (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("charisma_profile: llm call failed: %s", e)
        return None

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("charisma_profile: llm output not JSON: %r", raw[:300])
        return None

    insight = str(parsed.get("insight") or "").strip()
    rec = parsed.get("recommendation") or {}
    title = str(rec.get("title") or "").strip()
    body = str(rec.get("body") or "").strip()
    if not insight or not title or not body:
        return None

    return {
        "insight": insight,
        "recommendation": {"title": title, "body": body},
    }


def _peak_trigger_point(triggers: dict) -> Optional[dict]:
    """Highest-intensity entry from triggers.points, or None."""
    points = triggers.get("points") or []
    if not points:
        return None
    return max(points, key=lambda p: p.get("intensity") or 0.0)


def _peak_point_label(point: Optional[dict]) -> str:
    if not point:
        return "—"
    t = point.get("t")
    intensity = point.get("intensity")
    if t is None or intensity is None:
        return "—"
    return f"{t:.0f}% in, intensity {intensity:.2f}"


# ── Tiny helpers ────────────────────────────────────────────────────


def _sort_snippets(snippets: list[dict]) -> list[dict]:
    """Stable turn-row order: turn_number, then start_offset_ms."""
    return sorted(
        snippets,
        key=lambda s: (
            int(s.get("turn_number") or 0),
            int(s.get("start_offset_ms") or 0),
        ),
    )


def _to_float(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> Optional[int]:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))
