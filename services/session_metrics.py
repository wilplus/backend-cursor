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

from services.db import db


logger = logging.getLogger(__name__)


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
    global_fillers = sum(fillers_list) if fillers_list else None
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

    return {
        "wpm": global_wpm,
        "fillers": global_fillers,
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
