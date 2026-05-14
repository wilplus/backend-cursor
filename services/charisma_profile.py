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


def generate_charisma_profile(
    session_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Spec-named entry: load the four input slices for ``session_id``
    (owner-checked against ``user_id``) and return the full
    charisma_profile payload.

    Use this from BFF endpoints that have only the IDs — the route
    handler at ``/v2/user/sessions/<id>/charisma-profile`` has the
    session already in hand and goes through ``build_charisma_profile``
    directly to save a round-trip.

    Owner-mismatched or missing sessions degrade to an empty
    ``session`` dict so the builder applies neutral defaults — the
    payload is always shape-complete, never raises, and the BFF
    caller can safely splat it into the response.
    """
    from services.db import db  # local import — keeps module import-cheap

    try:
        session = db.v2_get_session_by_id(session_id) or {}
    except Exception as e:
        logger.warning(
            "generate_charisma_profile: session load failed sid=%s err=%s",
            session_id, e,
        )
        session = {}

    # Owner gate. We don't raise — the caller decides whether to
    # surface 404 or render a sparse profile. Returning a neutral
    # shape protects against accidental cross-user leakage if a
    # caller forgets to verify ownership before injection.
    if session and str(session.get("user_id") or "") != str(user_id):
        session = {}

    try:
        snippets = db.get_snippets_by_session(session_id) or []
    except Exception as e:
        logger.warning(
            "generate_charisma_profile: snippet load failed sid=%s err=%s",
            session_id, e,
        )
        snippets = []

    settings: dict = {}
    try:
        settings = db.get_user_settings(user_id) or {}
    except Exception as e:
        logger.warning(
            "generate_charisma_profile: settings load failed uid=%s err=%s",
            user_id, e,
        )

    learner_profile = settings.get("inferred_learner_profile") or None
    mirror = settings.get("current_learner_mirror") or None

    return build_charisma_profile(
        session=session,
        snippets=snippets,
        learner_profile=learner_profile,
        mirror=mirror,
    )


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

    Per the dashboard spec — every dimension is a simple average of
    two already-normalised inputs:

      POWER    = avg(stickiness, pace)
      WARMTH   = avg(emotional_movement, engagement)
      PRESENCE = avg(flow, score)

    ``stickiness``, ``emotional_movement``, ``engagement`` are read
    directly from ``inferred_learner_profile.traits.score_per_component``
    (Phase 4 evaluator output, already 0..1). ``pace`` is the WPM
    proximity-to-ideal-band score from session.global_wpm.
    ``flow`` is an inverse-filler-density proxy on the session.
    ``score`` is session.kpi_score / 100.

    Missing inputs are skipped, not zeroed — a dimension with one
    valid input averages just that one. A dimension with no inputs
    degrades to ``_TRINITY_NEUTRAL`` (0.5) so the radar chart never
    shows a 0 from missing data.
    """
    stickiness = _coaching_components_average(learner_profile, "stickiness")
    emotional_movement = _coaching_components_average(
        learner_profile, "emotional_movement",
    )
    engagement = _coaching_components_average(learner_profile, "engagement")
    pace = _pace_proximity_score(session)
    flow = _flow_score(session)
    score = _kpi_normalised(session)

    power = _avg_or_neutral([stickiness, pace])
    warmth = _avg_or_neutral([emotional_movement, engagement])
    presence = _avg_or_neutral([flow, score])

    insight = _trinity_insight(power, warmth, presence)
    return {
        "power": round(power, 4),
        "warmth": round(warmth, 4),
        "presence": round(presence, 4),
        "insight": insight,
    }


def _avg_or_neutral(values: list[Optional[float]]) -> float:
    """Mean of the non-None inputs; 0.5 if none present."""
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else _TRINITY_NEUTRAL


def _pace_proximity_score(session: dict) -> Optional[float]:
    """0..1 proximity of global_wpm to the ideal band.

    1.0 inside [_IDEAL_WPM_MIN, _IDEAL_WPM_MAX]; falls off linearly
    to 0 at 80 (too slow) or 200 (too fast). Returns None when WPM
    is missing so the trinity averages skip it instead of zeroing.
    """
    wpm = _to_float(session.get("global_wpm"))
    if wpm is None or wpm <= 0:
        return None
    if _IDEAL_WPM_MIN <= wpm <= _IDEAL_WPM_MAX:
        return 1.0
    if wpm < _IDEAL_WPM_MIN:
        return _clamp01((wpm - 80) / (_IDEAL_WPM_MIN - 80))
    return _clamp01((200 - wpm) / (200 - _IDEAL_WPM_MAX))


def _flow_score(session: dict) -> Optional[float]:
    """0..1 delivery-fluency proxy from session-level filler count.

    0 fillers → 1.0; 12+ fillers → 0. Linear in between. The same
    threshold the spec uses for the per-snippet ``1.0 - flow``
    intensity points, so the dashboard's overall flow read and its
    heatmap agree on what 'stressed delivery' looks like.
    """
    fillers = _to_int(session.get("global_fillers"))
    if fillers is None:
        return None
    return _clamp01(1.0 - (fillers / 12.0))


def _kpi_normalised(session: dict) -> Optional[float]:
    """KPI master score (0..100) → 0..1. None when KPI missing."""
    kpi = _to_float(session.get("kpi_score"))
    if kpi is None:
        return None
    return _clamp01(kpi / 100.0)


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
    """Heatmap-style trigger payload — spec-aligned.

    topTheme         — theme/question from the worst-performing
                       snippet (lowest per-snippet flow score). This
                       is what the user wants to drill into next;
                       reading it off the LEARNER PROFILE's top
                       recurring entity would surface what's
                       frequent, not what's hardest.
    pitchDelta       — semitone spread across the session.
    fillerMultiplier — ratio of fillers in second half vs first half.
    points           — per-turn stress points where
                       ``t`` is percentage (0..100) of session
                       duration and ``intensity`` is
                       ``1.0 - per_snippet_flow``. Both spec-shaped
                       so the frontend can plot a clean heatmap
                       without further math.
    """
    top_theme = _worst_snippet_theme(snippets) or _top_recurring_theme(
        learner_profile,
    )

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

    # Per-turn intensity points. Spec: ``t`` is 0..100 (percent of
    # session duration), ``intensity`` is ``1.0 - flow_score`` where
    # flow_score is the per-snippet fluency proxy. High intensity
    # therefore = stressed delivery (lots of fillers per minute on
    # that turn).
    total_ms = sum(int(s.get("duration_ms") or 0) for s in snippets) or 0
    points: list[dict[str, Any]] = []
    cumulative_ms = 0
    for s in snippets:
        # Anchor the point at the START of the turn — gives the
        # heatmap a left-edge "stress at minute X" reading rather
        # than smearing across the turn.
        start_ms = s.get("start_offset_ms")
        try:
            t_ms = int(start_ms) if start_ms is not None else cumulative_ms
        except (TypeError, ValueError):
            t_ms = cumulative_ms

        if total_ms > 0:
            t_pct = round((t_ms / total_ms) * 100.0, 1)
        else:
            t_pct = 0.0
        t_pct = max(0.0, min(100.0, t_pct))

        flow = _snippet_flow(s)
        if flow is not None:
            intensity = round(_clamp01(1.0 - flow), 4)
            points.append({"t": t_pct, "intensity": intensity})

        cumulative_ms += int(s.get("duration_ms") or 0)

    return {
        "topTheme": top_theme,
        "pitchDelta": pitch_delta_label,
        "fillerMultiplier": multiplier_label,
        "points": points,
    }


def _snippet_flow(s: dict) -> Optional[float]:
    """Per-snippet flow score (0..1) — inverse filler density.

    0 fillers/min → 1.0; 12+ fillers/min → 0. The minute basis
    normalises across turn lengths so a 10s turn with 1 filler
    doesn't read as catastrophic. Returns None when fillers or
    duration are missing.
    """
    fillers = _to_int(s.get("fillers"))
    dur_ms = _to_int(s.get("duration_ms"))
    if fillers is None or dur_ms is None or dur_ms <= 0:
        return None
    per_minute = fillers / (dur_ms / 60000.0)
    return _clamp01(1.0 - per_minute / 12.0)


def _worst_snippet_theme(snippets: list[dict]) -> Optional[str]:
    """Surface the question/topic of the worst-performing snippet
    (lowest flow → highest delivery stress). The dashboard renders
    this as 'where it spiked', so it should point at the moment
    that needs work, not the most-recurring topic.

    We prefer ``question_text`` (always set on directed turns),
    then fall back to ``topic`` / first sentence of ``transcript``
    so we have something even on legacy snippets.
    """
    if not snippets:
        return None

    scored: list[tuple[float, dict]] = []
    for s in snippets:
        flow = _snippet_flow(s)
        if flow is None:
            continue
        scored.append((flow, s))
    if not scored:
        return None

    scored.sort(key=lambda x: x[0])  # lowest flow first
    worst = scored[0][1]

    for field in ("question_text", "topic"):
        label = (worst.get(field) or "").strip()
        if label:
            return label[:80]

    transcript = (worst.get("transcript") or "").strip()
    if transcript:
        # First sentence-ish — terminate at the first sentence
        # boundary so we don't blow up the card with the whole
        # answer.
        for terminator in (". ", "? ", "! ", "\n"):
            idx = transcript.find(terminator)
            if 0 < idx <= 80:
                return transcript[: idx + 1].strip()
        return transcript[:80].strip()

    return None


# ── Archetype ───────────────────────────────────────────────────────


def _build_archetype(trinity: dict, learner_profile: Optional[dict]) -> str:
    """Map the trinity dominant axis to a spec archetype name.

    Per the dashboard spec:
      Balanced (top–bottom delta < 0.10) → "The Harmonizer"
      POWER-dominant                     → "The Commander"
      WARMTH-dominant                    → "The Empath"
      PRESENCE-dominant                  → "The Anchor"

    Pure trinity-derived so the archetype matches the radar the
    user is staring at — no override from behavioral_profile_auto
    in v1.
    """
    scores = {
        "Power": trinity.get("power") or 0.0,
        "Warmth": trinity.get("warmth") or 0.0,
        "Presence": trinity.get("presence") or 0.0,
    }
    top = max(scores, key=scores.get)
    bot = min(scores, key=scores.get)
    if scores[top] - scores[bot] < 0.10:
        return "The Harmonizer"
    return {
        "Power": "The Commander",
        "Warmth": "The Empath",
        "Presence": "The Anchor",
    }[top]


# ── Recommendation ──────────────────────────────────────────────────


def _build_recommendation(
    trinity: dict, archetype: str,
) -> dict[str, str]:
    """Next-step card driven by the weakest trinity axis.

    Spec body strings — one per weakest axis, no interpolation of
    raw numbers so the copy stays clean:

      Weakest POWER    → "Your warmth and presence are strong, but
                          let's practice Power under fire."
      Weakest WARMTH   → "Your authority is strong, but let's
                          practice Warmth under fire."
      Weakest PRESENCE → "Your authority is strong, but let's
                          practice Presence under fire."
    """
    scores = {
        "Power": trinity.get("power") or 0.0,
        "Warmth": trinity.get("warmth") or 0.0,
        "Presence": trinity.get("presence") or 0.0,
    }
    weakest = min(scores, key=scores.get)

    body_by_axis = {
        "Power": (
            "Your warmth and presence are strong, but let's "
            "practice Power under fire."
        ),
        "Warmth": (
            "Your authority is strong, but let's practice Warmth "
            "under fire."
        ),
        "Presence": (
            "Your authority is strong, but let's practice Presence "
            "under fire."
        ),
    }
    return {
        "title": "Ready for your next stress-test?",
        "body": body_by_axis[weakest],
    }


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
    emit the spec's deterministic fallback so the dashboard always
    has prose to render even on a sparse first session."""
    if isinstance(mirror, dict):
        cached = (mirror.get("narrative") or "").strip()
        if cached:
            return cached

    # Spec fallback — verbatim. Keeps the copy honest: we promised
    # narrative when there's enough data, and we say so explicitly
    # when there isn't.
    return (
        "Your acoustic baseline has been captured. Complete more "
        "scenarios to unlock your deep narrative."
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
