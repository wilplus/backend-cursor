"""Session-level metric aggregation.

Aggregates the per-snippet acoustic columns into the session row's
``global_*`` fields plus a B6 KPI score, and runs the Phase 17.1
drift guard. Extracted from routes/v2_routes.py so service-layer
callers (the auto-finalize daemon, the auto-publish path, the
contextual-chat upload finalize) don't have to reach back into
routes for a helper — and so the late-import cycle smell goes away.

Public surface
--------------
- ``compute_session_global_metrics(session_id)`` — one entry. Reads
  all active snippets for the session, aggregates them with the
  same rules the admin compute-metrics endpoint uses, persists
  global_* + kpi_score + drift columns, and returns the computed
  dict (or ``None`` when the session has no active snippets).

Aggregation rules
-----------------
- Averages for rates (wpm, pause_ms, dynamic_db, pitch_center,
  energy)
- Sum for counts (fillers)
- Transcript-derived fallback (utils.metrics.compute_wpm +
  count_fillers) for snippets whose pipeline never filled the
  per-row columns
- JSONB ``metrics`` fallback for legacy rows that wrote metrics
  into the blob before the dedicated columns existed

KPI policy
----------
We REFUSE to score when any of (wpm, fillers, energy) is missing —
the previous version defaulted those to 0 / 140 / 0 and silently
produced a "perfect" 100 on sessions where the metrics pipeline
never ran, making one user's KPI incomparable to another's. Missing
inputs → kpi_score=None → frontend renders "—".
"""
from __future__ import annotations

import logging
from typing import Any

from services import dimension_registry as _registry
from services.db import db


logger = logging.getLogger(__name__)


# Where each registry dimension's value is read from on a snippet row:
#   dimension_id -> (column, JSONB `metrics` fallback key)
# ONLY the plumbing lives here. Window class, tier, minimum length, denominator
# and aggregation all come from services/dimension_registry — Appendix F.4 is
# the source, and retyping any of it into this file is how two consumers start
# disagreeing about the same dimension.
_SNIPPET_FIELDS = {
    "wpm":          ("wpm",          None),
    "fillers":      ("fillers",      None),
    "pause_ms":     ("pause_ms",     "pause_ms"),
    "dynamic_db":   ("dynamic_db",   "dynamic_db"),
    "pitch_center": ("pitch_center", "pitch_center_st"),
    "energy":       ("energy",       "energy_ratio"),
}


def _denominator_count(denominator, seconds, words):
    """How many units the registry's declared denominator counts, or None.

    An UNRECOGNISED denominator returns None rather than a guess: writing the
    word count under a denominator that means minutes is the exact F.3 error
    — off by whatever the speech rate happens to be, and still plausible.
    """
    if denominator == "minutes":
        return round(seconds / 60.0, 3) if seconds else None
    if denominator == "words":
        return words or None
    return None


def _emit_drift_telemetry(session_id: str, active_snippets: list) -> int:
    """Write one dimension_evaluations row per (snippet, live dimension).

    Every spec fact is READ FROM THE REGISTRY, never restated here.

    MEASUREMENTS, not decisions: none of the live dimensions has a `fire_at`
    in code yet, so `fired` stays None. That is a real third state, distinct
    from a negative decision and from missing data (SPEC D30).

    APPENDIX F.2's MINIMUM-LENGTH GATE IS ENFORCED HERE, PER DIMENSION. The
    gate is NOT uniform and must not be applied as if it were: F.1 scopes the
    30 s minimum to pause/disfluency RATES, where Henderson's planning cycle
    makes a sub-cycle rate swing with where the window happens to land. Three
    of the six live measures are LEVELS (loudness dynamics, pitch centre,
    energy) and carry no seconds gate at all — a mean is stable well inside
    one cycle. Applying the rate gate to them marked good data insufficient.
    The registry holds which is which; this loop only asks.

    Rows below their own gate are written as `insufficient_data` rather than
    dropped — F.5 makes "could not compute this" first-class, and a value
    under the gate is noise wearing a number's clothes. Dropping them instead
    would make the gap invisible to PSI, which is the failure mode the column
    exists to prevent.
    """
    from services import dimension_registry as registry

    rows = []
    for s in active_snippets or ():
        snippet_id = s.get("id")
        if not snippet_id:
            continue
        metrics = s.get("metrics") if isinstance(s.get("metrics"), dict) else {}
        transcript = (s.get("transcript") or "").strip()
        word_count = len(transcript.split()) if transcript else None
        duration_ms = s.get("duration_ms")
        seconds = (float(duration_ms) / 1000.0
                   if isinstance(duration_ms, (int, float)) else None)

        for dim in registry.live_dimensions():
            plumbing = _SNIPPET_FIELDS.get(dim.dimension_id)
            if not plumbing:
                continue                      # in the registry, not wired here
            column, fallback_key = plumbing
            value = s.get(column)
            if value is None and fallback_key:
                value = metrics.get(fallback_key)

            has_value = isinstance(value, (int, float))
            long_enough = registry.meets_minimum(
                dim.dimension_id, seconds=seconds, tokens=word_count)
            usable = has_value and long_enough

            rows.append({
                "snippet_id": snippet_id,
                "session_id": session_id,
                "user_id": s.get("user_id"),
                "dimension_id": dim.dimension_id,
                "raw_value": float(value) if usable else None,
                "fired": None,                       # no fire_at in code yet
                "insufficient_data": not usable,
                "benchmark_tier": dim.tier,
                "benchmark_version": dim.benchmark_version,
                "window_class": dim.window_class,
                # HOW MANY UNITS THE RATE WAS COMPUTED OVER (F.3), read from
                # the registry's declared denominator. NULL for a LEVEL, which
                # divides by nothing, and NULL where the count is unknowable —
                # a wrong denominator is worse than an absent one, because it
                # is silently wrong rather than visibly missing.
                "n_units": _denominator_count(dim.denominator, seconds,
                                              word_count),
            })
    if not rows:
        return 0
    return db.record_dimension_evaluations(rows)


def compute_session_global_metrics(session_id: str) -> dict | None:
    """Aggregate snippet-level metrics into session-level averages and
    persist. Returns the computed dict on success, or ``None`` when
    the session has no active snippets (caller decides whether
    that's an error).
    """
    snippets = db.get_snippets_by_session(session_id)
    active_snippets = [s for s in snippets if not s.get("is_skipped", False)]
    if not active_snippets:
        return None

    wpms = [s.get("wpm") for s in active_snippets if s.get("wpm") is not None]
    fillers_list = [s.get("fillers") for s in active_snippets if s.get("fillers") is not None]
    pauses = [s.get("pause_ms") for s in active_snippets if s.get("pause_ms") is not None]
    dynamics = [s.get("dynamic_db") for s in active_snippets if s.get("dynamic_db") is not None]
    pitches = [s.get("pitch_center") for s in active_snippets if s.get("pitch_center") is not None]
    energies = [s.get("energy") for s in active_snippets if s.get("energy") is not None]

    # Transcript-derived fallback for snippets whose per-row wpm /
    # fillers columns were never populated (typical: snippets created
    # via paths that skipped the metrics pipeline). count_fillers +
    # compute_wpm are deterministic and cheap.
    if not wpms or not fillers_list:
        try:
            from utils.metrics import compute_wpm as _compute_wpm
            from utils.metrics import count_fillers as _count_fillers
            for s in active_snippets:
                transcript = (s.get("transcript") or "").strip()
                duration_ms = s.get("duration_ms")
                if not transcript or not duration_ms:
                    continue
                if s.get("wpm") is None:
                    wpms.append(
                        _compute_wpm(transcript, float(duration_ms) / 1000.0)
                    )
                if s.get("fillers") is None:
                    fc = _count_fillers(transcript)
                    fillers_list.append(int(fc.get("total") or 0))
        except Exception as fb_err:
            logger.warning(
                "session metrics: transcript-fallback failed session=%s: %s",
                session_id, fb_err,
            )

    # JSONB ``metrics`` fallback for any field whose dedicated column
    # is empty (legacy rows).
    if not pauses:
        pauses = [
            s["metrics"]["pause_ms"] for s in active_snippets
            if s.get("metrics") and s["metrics"].get("pause_ms") is not None
        ]
    if not dynamics:
        dynamics = [
            s["metrics"]["dynamic_db"] for s in active_snippets
            if s.get("metrics") and s["metrics"].get("dynamic_db") is not None
        ]
    if not pitches:
        pitches = [
            s["metrics"]["pitch_center_st"] for s in active_snippets
            if s.get("metrics") and s["metrics"].get("pitch_center_st") is not None
        ]
    if not energies:
        energies = [
            s["metrics"]["energy_ratio"] for s in active_snippets
            if s.get("metrics") and s["metrics"].get("energy_ratio") is not None
        ]

    global_wpm = round(sum(wpms) / len(wpms), 1) if wpms else None

    # global_fillers stays a COUNT. Three consumers require that and would
    # break silently otherwise: metrics_v2.normalize_fillers thresholds on
    # absolute counts (<=3 -> 1.0, so any rate reads as perfect and the KPI
    # filler component maxes out for everyone); coaching_state_machine passes
    # it as `current_fillers`; and openai_service renders it into user-facing
    # copy as "used N filler words".
    global_fillers = sum(fillers_list) if fillers_list else None

    # ── the registry-governed roll-up ───────────────────────────────────────
    #
    # `global_*` above are the LEGACY product metrics: fixed aggregations with
    # live consumers, kept exactly as they are. `registry_globals` below is the
    # same six measures rolled up the way Appendix F.4 says, read from
    # services/dimension_registry rather than restated here.
    #
    # WHY BOTH RATHER THAN ONE. They disagree, and the disagreement is real
    # rather than a bug to reconcile away: F.4 (E6) defines filler density PER
    # MINUTE while `global_fillers` is a sum, because normalize_fillers
    # thresholds on absolute counts. Two quantities, one name. Collapsing them
    # would silently max out every user's KPI filler component.
    #
    # Nothing consumes registry_globals yet. It exists so the next consumer
    # reads the spec instead of copying the legacy shape — which is how the
    # two drifted apart in the first place.
    _total_ms = sum(
        s["duration_ms"] for s in active_snippets
        if isinstance(s.get("duration_ms"), (int, float))
    )
    _minutes = (_total_ms / 60000.0) if _total_ms > 0 else None
    _words = sum(
        len((s.get("transcript") or "").split()) for s in active_snippets
    )

    registry_globals = _registry.rollup(
        {"wpm": wpms, "fillers": fillers_list, "pause_ms": pauses,
         "dynamic_db": dynamics, "pitch_center": pitches, "energy": energies},
        minutes=_minutes, words=_words,
    )
    # Kept as a named field for readability; it is registry_globals["fillers"].
    global_fillers_per_min = registry_globals.get("fillers")

    global_pause_ms = round(sum(pauses) / len(pauses), 1) if pauses else None
    global_dynamic_db = round(sum(dynamics) / len(dynamics), 1) if dynamics else None
    global_pitch_center = round(sum(pitches) / len(pitches), 1) if pitches else None
    global_energy = round(sum(energies) / len(energies), 3) if energies else None

    # KPI — refuse to score when any input is missing.
    kpi_score: float | None = None
    kpi_debug: dict[str, Any] | None = None
    if (
        global_wpm is not None
        and global_fillers is not None
        and global_energy is not None
    ):
        try:
            from services.metrics_v2 import compute_recording_performance_score
            kpi_result = compute_recording_performance_score(
                center_hold_ratio=global_energy,
                filler_count=global_fillers,
                wpm=global_wpm,
            )
            kpi_score = round(kpi_result["score_01"] * 100, 1)
            kpi_debug = kpi_result
        except Exception as kpi_err:
            logger.warning(
                "session metrics: KPI score compute failed: %s", kpi_err,
            )
    else:
        logger.info(
            "session metrics: skipping KPI for session=%s — missing "
            "inputs wpm=%s fillers=%s energy=%s",
            session_id, global_wpm, global_fillers, global_energy,
        )
        kpi_debug = {
            "score_source": "skipped_missing_inputs",
            "wpm_missing": global_wpm is None,
            "fillers_missing": global_fillers is None,
            "energy_missing": global_energy is None,
        }

    db.update_session_global_metrics(
        session_id=session_id,
        global_wpm=global_wpm,
        global_fillers=global_fillers,
        global_pause_ms=global_pause_ms,
        global_dynamic_db=global_dynamic_db,
        global_pitch_center=global_pitch_center,
        global_energy=global_energy,
        kpi_score=kpi_score,
    )

    # Phase 17.1: cross-layer drift guard. Compare B6 (kpi_score
    # scaled to 0..1) against the average D1 classifier_confidence
    # across the active snippets. When they disagree by > 40 pp one
    # side glitched — flag the session for admin review instead of
    # letting a wrong number publish silently. Non-blocking.
    drift_diag: dict | None = None
    needs_review = False
    try:
        from services.metrics_v2 import detect_classifier_drift
        confidences = [
            float(s.get("classifier_confidence"))
            for s in active_snippets
            if isinstance(s.get("classifier_confidence"), (int, float))
        ]
        avg_confidence = (
            sum(confidences) / len(confidences) if confidences else None
        )
        b6_normalised = (
            (kpi_score / 100.0) if isinstance(kpi_score, (int, float)) else None
        )
        drift_diag = detect_classifier_drift(
            performance_score=b6_normalised,
            classifier_confidence=avg_confidence,
        )
        needs_review = bool(drift_diag.get("needs_admin_review"))
        db.set_session_drift_flag(
            session_id=session_id,
            needs_review=needs_review,
            diagnostic=drift_diag,
        )
        if needs_review:
            logger.warning(
                "session metrics: drift flag fired session=%s "
                "b6=%s classifier_conf=%s deviation=%s",
                session_id, b6_normalised, avg_confidence,
                drift_diag.get("deviation"),
            )
    except Exception as drift_err:
        logger.warning(
            "session metrics: drift check failed session=%s err=%s",
            session_id, drift_err,
        )

    # Appendix G / SPEC D26 — drift telemetry. One row per (snippet,
    # dimension) for every measure that actually runs today. These are
    # MEASUREMENTS, not decisions: none of the six has a fire threshold in
    # code yet, so `fired` stays None and only `raw_value` is recorded. PSI
    # reads the value; the p-chart will read `fired` once benchmarks land.
    #
    # Deliberately last and fully non-blocking: telemetry that observes the
    # scoring path must never be able to break it.
    try:
        _emit_drift_telemetry(session_id, active_snippets)
    except Exception as telemetry_err:
        logger.warning(
            "session metrics: drift telemetry failed session=%s err=%s",
            session_id, telemetry_err,
        )

    return {
        "wpm": global_wpm,
        "fillers": global_fillers,
        # Appendix F.4 (E6) — the registry-declared aggregation, alongside the
        # count rather than replacing it. Not persisted yet; no consumer.
        "fillers_per_min": global_fillers_per_min,
        "pause_ms": global_pause_ms,
        "dynamic_db": global_dynamic_db,
        "pitch_center": global_pitch_center,
        "energy": global_energy,
        "kpi_score": kpi_score,
        "kpi_debug": kpi_debug,
        "needs_admin_review": needs_review,
        "drift_diagnostic": drift_diag,
        "snippets_analyzed": len(active_snippets),
        "active_snippets": active_snippets,
    }
