"""Charisma-Awareness Dashboard payload builder.

Assembles the `charisma_profile` JSONB that powers the user-facing
results dashboard (radar charts, heatmaps, archetype + recommendation
cards). Pure aggregation over data already on disk — no LLM call,
no new tables. The narrative slot reuses the existing learner-mirror
narrative when available and falls back to a deterministic one-line
summary otherwise.

Architecture
------------
- One public entry point: ``build_charisma_profile``.
- Composes from four data sources, all already populated by earlier
  phases:
    1. `v2_sessions` row (KPI, stickiness, global acoustic averages)
    2. `charisma_snippets` rows for that session (per-turn metrics)
    3. `user_settings.inferred_learner_profile` (Phase 3)
    4. `user_settings.current_learner_mirror` (Phase 6 narrative)
- Five output blocks: archetype, narrative, acoustics, trinity,
  triggers, recommendation. All defined in the contract:
  see the route docstring on ``v2_user_session_charisma_profile``.

Degraded mode
-------------
Every block computes from whatever data is present — sparse sessions
get sensible defaults (e.g. WPM falls back to band-midpoint when the
session never measured), and the trinity scores degrade to 0.5
neutral when the inputs are missing. The frontend always receives a
shape-complete payload; nothing flashes ``undefined`` rendering.
"""
from __future__ import annotations

import logging
from typing import Any, Optional


logger = logging.getLogger(__name__)


# Pace band the dashboard surfaces — tighter than the
# normalize_pace target (120-160) so the on-screen "ideal" range
# matches what we coach toward, not what we tolerate.
_IDEAL_WPM_MIN = 125
_IDEAL_WPM_MAX = 140
_PACE_BAND_MID = (_IDEAL_WPM_MIN + _IDEAL_WPM_MAX) / 2

# Trinity neutral default when no signal exists for a dimension.
_TRINITY_NEUTRAL = 0.5


def build_charisma_profile(
    *,
    session: dict,
    snippets: list[dict],
    learner_profile: Optional[dict],
    mirror: Optional[dict],
) -> dict[str, Any]:
    """Build the full charisma_profile payload.

    Inputs are read-only; this never writes to the DB. Returned dict
    matches the frontend contract exactly — every key is present,
    every nested object is shape-complete (defaults applied when
    underlying data is missing).
    """
    snippets_sorted = _sort_snippets(snippets or [])

    acoustics = _build_acoustics(session or {}, snippets_sorted)
    trinity = _build_trinity(session or {}, snippets_sorted, learner_profile)
    triggers = _build_triggers(
        session or {}, snippets_sorted, learner_profile,
    )
    archetype = _build_archetype(trinity, learner_profile)
    recommendation = _build_recommendation(trinity, archetype)
    narrative = _build_narrative(
        session=session or {},
        mirror=mirror,
        trinity=trinity,
        acoustics=acoustics,
        triggers=triggers,
    )

    return {
        "archetype": archetype,
        "narrative": narrative,
        "acoustics": acoustics,
        "trinity": trinity,
        "triggers": triggers,
        "recommendation": recommendation,
    }


# ── Internals ───────────────────────────────────────────────────────────────


def _sort_snippets(snippets: list[dict]) -> list[dict]:
    """Turn-row order. Stable on turn_number, then start_offset_ms."""
    return sorted(
        snippets,
        key=lambda s: (
            int(s.get("turn_number") or 0),
            int(s.get("start_offset_ms") or 0),
        ),
    )


# ── Acoustics ──────────────────────────────────────────────────────


def _build_acoustics(session: dict, snippets: list[dict]) -> dict[str, Any]:
    """Pace + ideal band + peak topic + per-turn WPM timeline."""
    raw_pace = session.get("global_wpm")
    try:
        pace = round(float(raw_pace), 1) if raw_pace is not None else None
    except (TypeError, ValueError):
        pace = None

    timeline: list[dict[str, Any]] = []
    cumulative_ms = 0
    for s in snippets:
        # Prefer the per-row offset when finalize has rewritten it;
        # otherwise fall back to a running cumulative cursor so the
        # x-axis stays monotonic even on fresh sessions.
        start_ms = s.get("start_offset_ms")
        try:
            t_ms = int(start_ms) if start_ms is not None else cumulative_ms
        except (TypeError, ValueError):
            t_ms = cumulative_ms
        wpm_raw = s.get("wpm")
        try:
            wpm = float(wpm_raw) if wpm_raw is not None else None
        except (TypeError, ValueError):
            wpm = None
        if wpm is None or wpm <= 0:
            # Skip rows where WPM wasn't measured. The dashboard
            # shouldn't plot a 0 point — would look like a silent
            # turn (which usually means the data is missing, not
            # that the user paused for the whole turn).
            cumulative_ms += int(s.get("duration_ms") or 0)
            continue
        timeline.append({
            "t": _mmss(t_ms),
            "wpm": round(wpm, 1),
        })
        cumulative_ms += int(s.get("duration_ms") or 0)

    peak_topic = (session.get("stickiness_top_topic") or "").strip() or None

    return {
        "pace": pace,
        "idealMin": _IDEAL_WPM_MIN,
        "idealMax": _IDEAL_WPM_MAX,
        "peakTopic": peak_topic,
        "timeline": timeline,
    }


# ── Trinity (Power / Warmth / Presence) ─────────────────────────────


def _build_trinity(
    session: dict,
    snippets: list[dict],
    learner_profile: Optional[dict],
) -> dict[str, Any]:
    """Three normalised 0..1 scores + a one-line insight.

    Heuristic mapping from existing metrics:
      Power    — wpm-driven assertiveness + dynamic range, penalised
                 by filler density. "Did the voice command the room?"
      Warmth   — emotional_movement from coaching attempts +
                 inverse-of-too-fast-pace, energy in mid-range.
                 "Did the voice invite the listener in?"
      Presence — pace-in-ideal-band + filler suppression + low
                 cross-turn variance. "Was the voice steady and
                 deliberate?"

    Each dimension defaults to ``_TRINITY_NEUTRAL`` when no signal
    is present, so the radar chart never shows a 0 from missing data.
    """
    wpm = _to_float(session.get("global_wpm"))
    fillers = _to_int(session.get("global_fillers"))
    dynamic_db = _to_float(session.get("global_dynamic_db"))
    energy = _to_float(session.get("global_energy"))

    # Power — assertive delivery.
    power_parts: list[float] = []
    if wpm is not None and wpm > 0:
        # Above the ideal band → asserting force; below → too soft.
        # Map 100..170 → 0..1 with band centre at 0.7 (slightly
        # above midpoint so the strong-voice end gets more weight).
        power_parts.append(_clamp01((wpm - 100) / 70.0))
    if dynamic_db is not None:
        # Center 25 dB → 1.0, falls off below 15 dB; above 35 dB
        # plateaus.
        power_parts.append(_clamp01((dynamic_db - 15) / 20.0))
    if fillers is not None:
        # 0 fillers → +1.0, 10+ → 0. Quadratic-ish via linear slope.
        power_parts.append(_clamp01(1.0 - (fillers / 12.0)))
    power = (
        round(sum(power_parts) / len(power_parts), 4)
        if power_parts else _TRINITY_NEUTRAL
    )

    # Warmth — emotional invitation.
    warmth_parts: list[float] = []
    em_avg = _coaching_components_average(learner_profile, "emotional_movement")
    if em_avg is not None:
        warmth_parts.append(em_avg)
    if wpm is not None and wpm > 0:
        # Above 170 WPM gets cold-and-fast → penalty. Below 100 →
        # plodding → also penalty.
        if wpm > 170:
            warmth_parts.append(_clamp01((220 - wpm) / 50.0))
        elif wpm < 100:
            warmth_parts.append(_clamp01(wpm / 100.0))
        else:
            warmth_parts.append(0.85)  # in-range = high warmth
    if energy is not None:
        # Mid-range energy (0.4..0.8) reads warmest; flat (low) is
        # cold, hot (>0.95) reads aggressive.
        if 0.4 <= energy <= 0.8:
            warmth_parts.append(0.9)
        elif energy < 0.4:
            warmth_parts.append(_clamp01(energy / 0.4))
        else:
            warmth_parts.append(_clamp01((1.1 - energy) / 0.3))
    warmth = (
        round(sum(warmth_parts) / len(warmth_parts), 4)
        if warmth_parts else _TRINITY_NEUTRAL
    )

    # Presence — steady, deliberate delivery.
    presence_parts: list[float] = []
    if wpm is not None and wpm > 0:
        # 1.0 inside the ideal band; falls off linearly to 0 at 80
        # or 200.
        if _IDEAL_WPM_MIN <= wpm <= _IDEAL_WPM_MAX:
            presence_parts.append(1.0)
        elif wpm < _IDEAL_WPM_MIN:
            presence_parts.append(_clamp01((wpm - 80) / (_IDEAL_WPM_MIN - 80)))
        else:
            presence_parts.append(_clamp01((200 - wpm) / (200 - _IDEAL_WPM_MAX)))
    if fillers is not None:
        presence_parts.append(_clamp01(1.0 - (fillers / 15.0)))
    # Cross-turn WPM consistency — low variance = high presence.
    wpms = [
        _to_float(s.get("wpm"))
        for s in snippets
        if _to_float(s.get("wpm")) is not None and _to_float(s.get("wpm")) > 0
    ]
    if len(wpms) >= 2:
        avg = sum(wpms) / len(wpms)
        spread = max(wpms) - min(wpms)
        # spread of 0 → 1.0; spread of 80+ → 0.
        presence_parts.append(_clamp01(1.0 - (spread / 80.0)))
        # avg keeps unused warning quiet; future use: weighting
    presence = (
        round(sum(presence_parts) / len(presence_parts), 4)
        if presence_parts else _TRINITY_NEUTRAL
    )

    insight = _trinity_insight(power, warmth, presence)
    return {
        "power": power,
        "warmth": warmth,
        "presence": presence,
        "insight": insight,
    }


def _trinity_insight(power: float, warmth: float, presence: float) -> str:
    """One-sentence framing of the dominant + lagging axes."""
    scores = {"Power": power, "Warmth": warmth, "Presence": presence}
    top = max(scores, key=scores.get)
    bot = min(scores, key=scores.get)
    if scores[top] - scores[bot] < 0.10:
        return (
            f"Your profile is balanced across Power ({power:.2f}), "
            f"Warmth ({warmth:.2f}), and Presence ({presence:.2f}). "
            "Push any one dimension to stand out."
        )
    return (
        f"Your authoritative profile is heavy on {top} ({scores[top]:.2f}) "
        f"but lacks {bot} ({scores[bot]:.2f}) under pressure."
    )


# ── Triggers ────────────────────────────────────────────────────────


def _build_triggers(
    session: dict,
    snippets: list[dict],
    learner_profile: Optional[dict],
) -> dict[str, Any]:
    """Heatmap-style trigger payload.

    topTheme         — top recurring theme from learner profile.
    pitchDelta       — semitone spread across the session.
    fillerMultiplier — ratio of fillers in second half vs first half.
    points           — per-turn stress-intensity points [0..1].
    """
    top_theme = _top_recurring_theme(learner_profile)

    # Pitch delta — max minus min across turns, in semitones.
    pitch_centers = [
        _to_float(s.get("pitch_center"))
        for s in snippets
        if _to_float(s.get("pitch_center")) is not None
    ]
    pitch_delta_label: str
    if len(pitch_centers) >= 2:
        delta = max(pitch_centers) - min(pitch_centers)
        pitch_delta_label = f"{delta:+.1f}st"
    else:
        pitch_delta_label = "—"

    # Filler multiplier — second half / first half. >1.0 means
    # fillers crept in under pressure.
    filler_counts = [
        _to_int(s.get("fillers"))
        for s in snippets
        if _to_int(s.get("fillers")) is not None
    ]
    multiplier_label: str
    if len(filler_counts) >= 2:
        mid = len(filler_counts) // 2
        first_half = sum(filler_counts[:mid]) or 0
        second_half = sum(filler_counts[mid:]) or 0
        if first_half == 0 and second_half == 0:
            multiplier_label = "1x"
        elif first_half == 0:
            multiplier_label = f"{second_half}x"  # no baseline → raw count
        else:
            multiplier_label = f"{second_half / first_half:.1f}x"
    else:
        multiplier_label = "—"

    # Per-turn intensity points. Combine filler density + pitch
    # volatility into a 0..1 stress proxy. ``t`` is seconds from
    # session start (use cumulative duration when start_offset_ms
    # missing).
    points: list[dict[str, Any]] = []
    cumulative_sec = 0
    avg_pitch = (
        sum(pitch_centers) / len(pitch_centers) if pitch_centers else None
    )
    for s in snippets:
        start_ms = s.get("start_offset_ms")
        try:
            t_sec = (
                int(start_ms) // 1000
                if start_ms is not None
                else cumulative_sec
            )
        except (TypeError, ValueError):
            t_sec = cumulative_sec
        intensity_parts: list[float] = []
        fillers = _to_int(s.get("fillers"))
        if fillers is not None:
            intensity_parts.append(_clamp01(fillers / 6.0))
        pitch = _to_float(s.get("pitch_center"))
        if pitch is not None and avg_pitch is not None:
            intensity_parts.append(_clamp01(abs(pitch - avg_pitch) / 6.0))
        wpm = _to_float(s.get("wpm"))
        if wpm is not None and wpm > 0:
            # WPM above 170 reads stressed.
            intensity_parts.append(_clamp01((wpm - 140) / 60.0))
        if intensity_parts:
            points.append({
                "t": t_sec,
                "intensity": round(
                    sum(intensity_parts) / len(intensity_parts), 4
                ),
            })
        cumulative_sec += int((s.get("duration_ms") or 0) / 1000)

    return {
        "topTheme": top_theme,
        "pitchDelta": pitch_delta_label,
        "fillerMultiplier": multiplier_label,
        "points": points,
    }


# ── Archetype ───────────────────────────────────────────────────────


def _build_archetype(trinity: dict, learner_profile: Optional[dict]) -> str:
    """Map the trinity dominant axis to a marketing-friendly name.

    Balanced profiles (top–bottom delta < 0.10) → "The Master".
    Power-dominant → "The Authority".
    Warmth-dominant → "The Connector".
    Presence-dominant → "The Visionary".

    The learner profile's behavioral_profile_auto could override
    this in future iterations (e.g. force "The Reactor" for
    classified Stressors), but v1 stays purely trinity-derived so
    the archetype matches the chart the user is staring at.
    """
    scores = {
        "Power": trinity.get("power") or 0.0,
        "Warmth": trinity.get("warmth") or 0.0,
        "Presence": trinity.get("presence") or 0.0,
    }
    top = max(scores, key=scores.get)
    bot = min(scores, key=scores.get)
    if scores[top] - scores[bot] < 0.10:
        return "The Master"
    return {
        "Power": "The Authority",
        "Warmth": "The Connector",
        "Presence": "The Visionary",
    }[top]


# ── Recommendation ──────────────────────────────────────────────────


def _build_recommendation(
    trinity: dict, archetype: str,
) -> dict[str, str]:
    """Next-step card. Title is action-shaped, body names the
    weakest trinity axis so the user knows what to practise."""
    scores = {
        "Power": trinity.get("power") or 0.0,
        "Warmth": trinity.get("warmth") or 0.0,
        "Presence": trinity.get("presence") or 0.0,
    }
    weakest = min(scores, key=scores.get)
    weakest_val = scores[weakest]

    weakness_phrasing = {
        "Power": "build authority under pressure",
        "Warmth": "soften your delivery without losing edge",
        "Presence": "steady your pace and reduce filler density",
    }

    title = "Ready for your next stress-test?"
    body = (
        f"Your {archetype.replace('The ', '').lower()} profile is "
        f"strong, but let's practice "
        f"{weakness_phrasing[weakest]} "
        f"({weakest} sits at {weakest_val:.2f})."
    )
    return {"title": title, "body": body}


# ── Narrative ───────────────────────────────────────────────────────


def _build_narrative(
    *,
    session: dict,
    mirror: Optional[dict],
    trinity: dict,
    acoustics: dict,
    triggers: dict,
) -> str:
    """Use the cached learner-mirror narrative when available; else
    synthesise a one-sentence summary from the trinity + KPI so the
    payload is never empty."""
    if isinstance(mirror, dict):
        cached = (mirror.get("narrative") or "").strip()
        if cached:
            return cached

    # Deterministic fallback. One sentence so the dashboard isn't
    # blank for first-session users who haven't generated a mirror.
    kpi = session.get("kpi_score")
    pace = acoustics.get("pace")
    pace_str = f"{pace:g} WPM" if isinstance(pace, (int, float)) else "an unmeasured pace"
    top_theme = triggers.get("topTheme") or "no recurring theme yet"
    kpi_str = f" with a KPI of {kpi:.0f}/100" if isinstance(kpi, (int, float)) else ""
    return (
        f"You delivered {pace_str}{kpi_str}, scoring Power "
        f"{trinity.get('power', 0):.2f} / Warmth "
        f"{trinity.get('warmth', 0):.2f} / Presence "
        f"{trinity.get('presence', 0):.2f}, with {top_theme} as your "
        "anchor — your next session will tighten the dimension where "
        "you lagged most."
    )


# ── Tiny helpers ────────────────────────────────────────────────────


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


def _mmss(total_ms: int) -> str:
    s = max(0, int(total_ms) // 1000)
    return f"{s // 60}:{s % 60:02d}"


def _coaching_components_average(
    learner_profile: Optional[dict],
    key: str,
) -> Optional[float]:
    """Read the average component score (specificity, engagement,
    emotional_movement, stickiness) from the inferred learner
    profile's traits block. Returns None if absent."""
    if not isinstance(learner_profile, dict):
        return None
    traits = learner_profile.get("traits") or {}
    per_component = traits.get("score_per_component") or {}
    if not isinstance(per_component, dict):
        return None
    v = per_component.get(key)
    return _to_float(v)


def _top_recurring_theme(learner_profile: Optional[dict]) -> Optional[str]:
    if not isinstance(learner_profile, dict):
        return None
    traits = learner_profile.get("traits") or {}
    recurring = traits.get("recurring_entities") or {}
    if not isinstance(recurring, dict):
        return None
    themes = recurring.get("themes") or []
    if not themes:
        return None
    first = themes[0]
    if isinstance(first, dict):
        return (first.get("label") or "").strip() or None
    return str(first).strip() or None
