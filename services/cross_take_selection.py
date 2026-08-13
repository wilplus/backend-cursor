"""Cross-take selection — the phase-1 payoff (willab Prompt A §5).

An explore arc holds the same talk delivered in distinct styles. This module
surfaces, FROM that arc, the user's strongest material to study — either:

  • LINE-LEVEL (§5.1): per matched line across the takes, the take whose
    version landed strongest → "your strongest delivery of EACH LINE". This
    is the specced payoff but DEPENDS on reliable same-line alignment across
    takes (paraphrase + ASR variance), which is a GATED pre-flight (§5.0).
  • TAKE-LEVEL (§5.2): each take's OWN strongest moments, no cross-take line
    matching → "your strongest moments in each style". Always shippable.

§5.0 GATE: a confident MIS-match is worse than no feature (same failure
shape as slide tap-mapping). The pre-flight runs a fuzzy-alignment spike on
REAL multi-take arcs and hand-checks the hit rate. Until that spike passes,
line-level stays OFF and we ship take-level. The spike is currently
DATA-BLOCKED (no real 3-take arcs exist yet), so the gate returns "take".

§5.3 INVARIANT: the gate flips ONE variable — selection GRANULARITY. It
NEVER decides whether the wave ships; the payload always carries a
`granularity` discriminator so the FE renders the matching surface.

AC-9 / split-sink (§7): the salience/control score is used INTERNALLY to
rank, and is NEVER serialized to the user. The user sees text + audio +
which take + a score-FREE plain-language rationale — no number, no verdict,
no "improving" trajectory.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Line-level (§5.1) ships ONLY when the §5.0 alignment spike passes on real
# arc data. Flipping this is a DATA decision, not a code decision: run the
# fuzzy-alignment hit-rate spike first, report it, then enable. Today: no
# real 3-take arcs exist → spike can't run → stays False (take-level).
_LINE_LEVEL_ENABLED = False

DEFAULT_MOMENTS_PER_TAKE = 3

# take_index → the style that take was recorded in. Take 1 is the natural
# baseline; takes 2–4 follow the cadence beats (chill / data / spark).
_MODE_BY_TAKE = {
    1: "Baseline (natural)",
    2: "Confidant (chill)",
    3: "Authority (data)",
    4: "Spark (energized)",
}


def preflight_granularity(arc_sessions: list[dict]) -> str:
    """§5.0 — decide the selection branch BEFORE building the surface.

    Returns "line" only if line-level is enabled (the alignment spike has
    passed) AND the arc actually has ≥2 takes to align across; otherwise
    "take". Deterministic + side-effect-free so it's safe to call per read.
    """
    if _LINE_LEVEL_ENABLED and len([s for s in (arc_sessions or []) if s]) >= 2:
        return "line"
    return "take"


def _tag_from_coach_label(coach_label: Any) -> Optional[str]:
    """Map the snippet's coach_label to the power_score coach term. Unreviewed
    takes (label None) → no coach term, pure acoustic ordering."""
    if coach_label == "charisma":
        return "strong"
    if coach_label == "no_charisma":
        return "to_work_on"
    return None


def _moment_rationale(snippet: dict) -> str:
    """A short, score-FREE plain-language 'why this is strong' line, built from
    the same metric→words conversion the coach drafter uses (no F0/dB/score
    ever reaches the user). Empty string if nothing computable."""
    try:
        from services.coach_comment_drafter import metric_observations
        obs = metric_observations(snippet.get("metrics"))
    except Exception:
        obs = {}
    # Order the observations the way a coach would read them out.
    order = ("pace", "pitch", "pauses", "volume", "clarity")
    parts = [obs[k] for k in order if obs.get(k)]
    if not parts:
        return ""
    phrase = ", ".join(parts)
    return phrase[0].upper() + phrase[1:] + "."


def _rank_inputs(snippet: dict) -> dict:
    """Pull the power_score inputs from a snippet row (metrics JSONB)."""
    metrics = snippet.get("metrics") or {}
    stick = metrics.get("slide_stickiness")
    if isinstance(stick, dict):
        stick = stick.get("composite")
    try:
        from services.voice_confidence import rank_term
        confidence = rank_term(metrics)
    except Exception:
        confidence = None
    return {
        "activation": metrics.get("overall_score"),
        "slide_stickiness": stick,
        "tag": _tag_from_coach_label(snippet.get("coach_label")),
        "rank": metrics.get("rank"),
        # Delivery term (L2) — None when the flag is off / piece unstamped.
        # MACHINE lane only: this reader has one snippet row and no panel
        # rows, so it never has the human aggregate to prefer (SPEC D8 —
        # confidence enters once, and the panel is the caller's job to fetch).
        "machine_confidence": confidence,
    }


def _score_free_moment(snippet: dict) -> dict:
    """The user-facing moment shape — AC-9: NO score, NO classifier verdict."""
    return {
        "snippet_id": snippet.get("id"),
        "transcript": (snippet.get("transcript")
                       or snippet.get("transcript_excerpt") or ""),
        "audio_ref": snippet.get("audio_ref") or snippet.get("storage_path"),
        "features": snippet.get("features"),
        "start_offset_ms": (snippet.get("start_offset_ms")
                            if snippet.get("start_offset_ms") is not None
                            else snippet.get("start_ms")),
        "duration_ms": snippet.get("duration_ms"),
        "rationale": _moment_rationale(snippet),
    }


def select_take_level(
    arc_id: Optional[str],
    *,
    database=None,
    max_moments_per_take: int = DEFAULT_MOMENTS_PER_TAKE,
) -> dict:
    """§5.2 — per-take strongest moments, score-free. The take-level branch.

    Returns the cross-take payload::

        {
          "arc_id": str,
          "granularity": "take",
          "take_count": int,
          "takes": [
            {"take_index": int, "mode": str, "session_id": str,
             "moments": [ {transcript, audio_ref, features, start_offset_ms,
                           duration_ms, rationale}, ... ]},
            ...
          ]
        }
    """
    db = database if database is not None else _default_db()
    # Spoken takes only (founder 2026-07-16): a mid-take RE-READ is part of
    # its take, never a competing take in the moments view.
    from services.best_presentation import spoken_arc_sessions
    sessions = spoken_arc_sessions(db.get_arc_sessions(arc_id)) \
        if arc_id else []
    from services.power_phrase_ranking import power_score

    takes = []
    for s in sessions:
        sid = s.get("id")
        ti = s.get("take_index")
        snippets = db.get_snippets_by_session(sid) if sid else []
        scored = []
        for snip in snippets:
            ps = power_score(**_rank_inputs(snip))
            scored.append((ps, snip))
        # Strongest first by the INTERNAL score; then strip the score.
        scored.sort(key=lambda t: -(t[0] or 0.0))
        moments = [_score_free_moment(snip)
                   for _ps, snip in scored[:max_moments_per_take]]
        takes.append({
            "take_index": ti,
            "mode": _MODE_BY_TAKE.get(ti if isinstance(ti, int) else -1,
                                      "This take"),
            "session_id": sid,
            "moments": moments,
        })

    return {
        "arc_id": arc_id,
        "granularity": "take",
        "take_count": len(sessions),
        "takes": takes,
    }


def select_cross_take(
    arc_id: Optional[str],
    *,
    database=None,
    max_moments_per_take: int = DEFAULT_MOMENTS_PER_TAKE,
) -> dict:
    """Entry point — runs the §5.0 gate, then the earned branch. Today the
    gate is data-blocked → always take-level; when the alignment spike
    passes, the line-level branch slots in here behind the same signature
    and the SAME payload contract (only `granularity` flips to "line")."""
    db = database if database is not None else _default_db()
    from services.best_presentation import spoken_arc_sessions
    sessions = spoken_arc_sessions(db.get_arc_sessions(arc_id)) \
        if arc_id else []
    granularity = preflight_granularity(sessions)
    if granularity == "line":  # pragma: no cover - gated off until §5.0 passes
        # Reserved: line-level selection lands here once _LINE_LEVEL_ENABLED.
        # Until then preflight_granularity never returns "line".
        logger.info("cross_take: line-level branch (arc=%s)", arc_id)
    return select_take_level(
        arc_id, database=db, max_moments_per_take=max_moments_per_take,
    )


def _default_db():
    from services.db import db as _db
    return _db
