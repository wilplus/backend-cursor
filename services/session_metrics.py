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
- JSONB ``metrics`` fallback. This was documented as a legacy path
  "for rows written before the dedicated columns existed"; that is
  wrong and was corrected 2026-08-06. It is the ONLY path. Nothing
  on the live loop ever wrote the six columns — their only writer,
  ``db.update_snippet_metrics``, was reached solely from the orphaned
  ``recompute_snippet_metrics_for_window``. Both were deleted
  2026-08-06 and migration 0254 drops the columns. The blob is the
  representation.

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


# The plumbing moved to services/snippet_values (PM-9): `services.db` needs
# the same resolver and this module imports db, so it cannot live here without
# a cycle. Re-exported under the old private names so the two grains below read
# unchanged.
from services.snippet_values import SNIPPET_FIELDS as _SNIPPET_FIELDS  # noqa: E402
from services.snippet_values import resolve as _resolve_dimension  # noqa: E402
from services.snippet_values import resolve_all as _resolve_all  # noqa: E402
from services.snippet_values import weights_of as _weights_of  # noqa: E402


def _resolve_snippet_value(snippet, dimension_id, metrics=None,
                           transcript=None, seconds=None):
    """Column -> JSONB blob -> transcript derivation. None if all miss.

    The trailing arguments are accepted and ignored: snippet_values derives
    them from the row itself, which is what stops the two grains disagreeing
    about which duration or transcript a value was measured against.
    """
    return _resolve_dimension(snippet, dimension_id)


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
            if dim.dimension_id not in _SNIPPET_FIELDS:
                continue                      # in the registry, not wired here
            if not registry.measurable_in_a_snippet(dim.dimension_id):
                continue         # windowed below — a snippet cannot hold it
            value = _resolve_snippet_value(
                s, dim.dimension_id, metrics, transcript, seconds)

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

    rows.extend(_windowed_rate_rows(session_id, active_snippets))
    if not rows:
        return 0
    return db.record_dimension_evaluations(rows)


def _windowed_rate_rows(session_id: str, active_snippets: list) -> list:
    """The three RATE dimensions, measured over ~40 s of stitched speech.

    D33. `wpm`, `fillers` and `pause_ms` gate at 30 s and a snippet is 6.55 s
    at the median — so at snippet grain they are `insufficient_data` on every
    row, forever, and PSI would report nothing for half the live set while
    looking perfectly healthy. A 60-second test recording produced four
    ~15 s snippets: four refusals, zero measurements, and more than three
    planning cycles of measurable speech thrown away for being asked about at
    the wrong zoom.

    The snippet is the F1 SEGMENTATION unit — slide-aligned, load-bearing for
    transcription and ranking. It is not a measurement window, and Appendix
    F-2's claim that it approximated one was retracted when its duration was
    measured.

    Anchored on the first snippet of each window (see rate_windows). The
    trailing remainder of a recording is emitted flagged `insufficient_data`
    rather than dropped — F.5 makes that state first-class, and silently
    discarding short windows would hide how much speech still falls through.
    """
    from services import dimension_registry as registry
    from services.rate_windows import Piece, build_windows

    windowed = [d for d in registry.live_dimensions()
                if _SNIPPET_FIELDS.get(d.dimension_id)
                and not registry.measurable_in_a_snippet(d.dimension_id)]
    if not windowed:
        return []

    pieces, owner = [], None
    for s in active_snippets or ():
        snippet_id, duration_ms = s.get("id"), s.get("duration_ms")
        if not snippet_id or not isinstance(duration_ms, (int, float)):
            continue
        owner = owner or s.get("user_id")
        metrics = s.get("metrics") if isinstance(s.get("metrics"), dict) else {}
        transcript = (s.get("transcript") or "").strip()
        seconds = float(duration_ms) / 1000.0
        values = {}
        for dim in windowed:
            value = _resolve_snippet_value(
                s, dim.dimension_id, metrics, transcript, seconds)
            if isinstance(value, (int, float)):
                values[dim.dimension_id] = float(value)
        pieces.append(Piece(
            snippet_id=str(snippet_id),
            recording_id=s.get("recording_id"),
            start_ms=float(s.get("start_offset_ms") or 0),
            duration_ms=float(duration_ms),
            words=len(transcript.split()) if transcript else 0,
            values=values,
            # How many observations each mean was taken over, where the row
            # records it. Makes the pause_ms roll-up exact instead of
            # duration-weighted; absent on pre-2026-08-06 snippets.
            weights=_weights_of(s),
        ))

    ids = [d.dimension_id for d in windowed]
    rows = []
    for window in build_windows(pieces, dimensions=ids):
        for dim in windowed:
            value = window.values.get(dim.dimension_id)
            usable = isinstance(value, (int, float)) and window.meets
            rows.append({
                "snippet_id": window.anchor_snippet_id,
                "recording_id": window.recording_id,
                "session_id": session_id,
                "user_id": owner,
                "dimension_id": dim.dimension_id,
                "raw_value": float(value) if usable else None,
                "fired": None,                   # no fire_at in code yet
                "insufficient_data": not usable,
                "benchmark_tier": dim.tier,
                "benchmark_version": dim.benchmark_version,
                "window_class": dim.window_class,
                # For a WINDOW row this is the window's own speech coverage in
                # minutes, whatever the dimension's denominator — the window
                # length is otherwise unrecoverable from the row, and the
                # drift analysis needs to know how much speech each value
                # rests on. Summed speech, so a gap between takes can never
                # enter it.
                "n_units": round(window.minutes, 4),
            })
    return rows


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

    # PM-9: ONE resolver, not six ad-hoc lookups with three different fallback
    # policies. The old code read the six denormalized columns first, then
    # patched wpm/fillers from the transcript, then patched the other four from
    # the blob — three precedence chains that disagreed with each other and
    # with the drift layer's. Every column is dead on the live path (see
    # services/snippet_values), so in practice the first chain always missed
    # and the KPI scored on whatever the second and third happened to recover.
    #
    # The fallbacks are no longer conditional on the list being EMPTY. That
    # test — `if not wpms` — meant one snippet with a value suppressed
    # recovery for every other snippet in the session, so a session roll-up
    # could rest on a single measured snippet out of twenty and look complete.
    _values = [_resolve_all(s) for s in active_snippets]

    def _column(dimension: str) -> list:
        return [v[dimension] for v in _values if v[dimension] is not None]

    wpms = _column("wpm")
    fillers_list = [int(v) for v in _column("fillers")]
    pauses = _column("pause_ms")
    dynamics = _column("dynamic_db")
    pitches = _column("pitch_center")
    energies = _column("energy")

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
