"""The FULL post-upload analysis pipeline as one module-level function.

Extracted VERBATIM from the `_run_analysis_pipeline` closure in
routes/v2_routes.py::v2_lab_create_recording (async-mode work, F1-SURFACE)
so the same code runs in all three execution modes:

  1. synchronous  — the legacy in-request path (v2_routes calls this
                    directly and blocks);
  2. daemon       — ASYNC_ANALYSIS_ENABLED's in-process background thread
                    (survives client disconnect, not a redeploy);
  3. queue worker — the durable RQ worker (services/pipeline_jobs.py), which
                    survives redeploys via the processing_jobs table.

Everything request-scoped is a PARAMETER here — this module must never
touch flask.request (the daemon/worker contract the closure already
enforced). Behaviour is intentionally identical across modes: LIVE LOOP
says the pipeline's outputs never depend on where it executes.

`progress` is an optional callable(stage, percent, message) used by the
queue mode to surface coarse mechanical progress ("transcribing…") to the
FE poll. It is best-effort and NEVER carries scores/verdicts (AC-9 — the
stages are plumbing labels, not reads on the speaker).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, Dict, Optional, Tuple

from services.db import db

logger = logging.getLogger(__name__)

ProgressFn = Optional[Callable[[str, int, Optional[str]], None]]


def _moment_suggestions_enabled() -> bool:
    """Star suggestions flag — same env read as routes/v2_routes.py's
    `_moment_suggestions_enabled` (kept duplicated rather than importing a
    routes module from services; both read MOMENT_SUGGESTIONS_ENABLED)."""
    return (os.getenv("MOMENT_SUGGESTIONS_ENABLED") or "0").strip().lower() \
        in ("1", "true", "yes")


class _Timeline:
    """PHASE TIMINGS for one run (founder 2026-08-11: "put tracking timers on
    the AI pipeline to see exactly which step takes the longest, rather than
    blindly trying to fix it").

    The wait after a take is long enough that the founder asked twice about
    it, and nothing in this pipeline has ever recorded where the time goes —
    the same position the intervention serve was in this evening, where an
    hour of database queries answered a question one log line now answers.

    Each phase is logged AS IT CLOSES rather than in one summary at the end,
    which is deliberate: a run that CRASHES is exactly the run whose timings
    you want, and a summary written after the last statement is the one you
    never get. The totals line is a convenience on top, not the record.

    AC-9: durations of machine work. Nothing here is a read on the speaker,
    and none of it reaches a payload."""

    __slots__ = ("_sid", "_t0", "_last", "_stage", "phases")

    def __init__(self, session_id: str) -> None:
        self._sid = str(session_id or "")
        self._t0 = time.monotonic()
        self._last = self._t0
        # Named for what has been happening SINCE the caller handed us the
        # take, which is where the user's wait actually starts.
        self._stage = "intake"
        self.phases: Dict[str, int] = {}

    def mark(self, stage: str) -> None:
        """Close the running phase and open `stage`."""
        now = time.monotonic()
        ms = int((now - self._last) * 1000)
        self.phases[self._stage] = ms
        logger.info("pipeline phase session=%s %s=%dms",
                    self._sid, self._stage, ms)
        self._stage, self._last = stage, now

    def done(self, ok: bool = True) -> None:
        self.mark("done")
        total = int((time.monotonic() - self._t0) * 1000)
        logger.info("pipeline timing session=%s total=%dms ok=%s %s",
                    self._sid, total, ok, self.phases)

    # Used as `with _Timeline(sid) as tl:` so the totals line survives a
    # CRASH. A `tl.done()` written as the last statement of the pipeline is
    # precisely the timing you never get when something raises three phases
    # earlier — and a run that falls over after a long wait is the run the
    # founder is asking about. The open phase is closed under its own name,
    # so the last line before the traceback says where the time went.
    def __enter__(self) -> "_Timeline":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        # Returns None → the exception propagates untouched. Instrumentation
        # never swallows a pipeline error (LIVE LOOP).
        self.done(ok=exc_type is None)


def _emit(progress: ProgressFn, stage: str, percent: int,
          message: Optional[str] = None) -> None:
    """Best-effort progress ping — a broken callback must never break the
    pipeline (live loop)."""
    if not progress:
        return
    try:
        progress(stage, percent, message)
    except Exception as pe:  # pragma: no cover - defensive
        logger.warning("analysis progress callback failed: %s", pe)


def run_full_analysis(
    *,
    session_id: str,
    user_id: Optional[str],
    recording_id: str,
    audio_bytes: bytes,
    filename: str,
    session_context: Optional[dict],
    parent_audio_url: str,
    recording_kind: str = "spoken",
    paired_session_id: Optional[str] = None,
    arc_id: Optional[str] = None,
    take_index: Optional[int] = None,
    arc_take_count: Optional[int] = None,
    spark_enabled: bool = False,
    progress: ProgressFn = None,
) -> Tuple[Dict[str, Any], bool]:
    """Runs the full pipeline to completion. Returns (readout, sent_to_coach).

    Transcribe → cut pieces → metrics → persist → cadence → auto-send →
    arc cards → eager ideal-text. Stage semantics, ordering, and all
    best-effort try/except behaviour are the closure's, unchanged.
    """
    from services.lab_recording import process_lab_recording

    with _Timeline(session_id) as tl:
        _emit(progress, "analysis", 15, "Transcribing and analyzing your take…")
        tl.mark("analysis")
        readout_local = process_lab_recording(
            session_id=session_id,
            user_id=user_id,  # fix #2b: attribute at record time
            recording_id=recording_id,
            audio_bytes=audio_bytes,
            filename=filename,
            session_context=session_context,
            parent_audio_url=parent_audio_url,
            recording_kind=recording_kind,  # spoken | read (2026-07-14)
            # A re-read z-scores against its PARENT take (2026-07-17) —
            # 1–2 pieces can't be their own reference.
            paired_session_id=paired_session_id,
        )
        logger.info(
            "lab: recording processed sid=%s rec=%s snippets=%d",
            session_id, recording_id,
            len(readout_local.get("snippets") or []),
        )

        # SESSION-LEVEL GLOBALS — restored 2026-08-06, dead since 2026-06-06.
        #
        # `compute_session_global_metrics` is the ONLY writer of global_wpm /
        # global_fillers / global_pause_ms / global_dynamic_db /
        # global_pitch_center / global_energy. Its only caller was the old-admin
        # POST /admin/sessions/<id>/compute-metrics route, removed in 0d74f12 as
        # "FE-orphaned". The route went, the service stayed, nothing replaced it —
        # so for two months four live readers have been getting NULL:
        #
        #   user_sessions._metrics_ready()  the FE's processing-phase gate, whose
        #                                   own docstring calls global_wpm "the
        #                                   canonical metrics-computed signal"
        #   routes/v2/coaching.py           feeds the coaching state machine, so
        #                                   target_dynamic_db was never derived
        #   routes/v2/user_chat.py          reads the latest session's globals
        #   routes/v2/admin.py              admin session view
        #
        # HERE is the right call site: process_lab_recording has just persisted
        # the charisma_snippets rows (lab_recording.create_charisma_snippets_bulk),
        # which is exactly what compute_session_global_metrics reads back.
        #
        # Best-effort by construction. Aggregation that observes the scoring path
        # must never be able to break it — the same rule the drift telemetry
        # inside it already follows.
        try:
            from services.session_metrics import compute_session_global_metrics
            _globals = compute_session_global_metrics(session_id)
            logger.info("lab: session globals sid=%s computed=%s",
                        session_id, _globals is not None)
        except Exception as _gm_err:
            logger.warning("lab: session globals failed sid=%s err=%s",
                           session_id, _gm_err)

        _emit(progress, "post_processing", 70, "Wrapping up…")
        tl.mark("post_processing")

        # Explore-session cadence (Prompt A §6 C3) — after a take in an
        # arc, invite the NEXT take as a Lounge bubble. Authed only;
        # best-effort + idempotent.
        if user_id and arc_id:
            try:
                from services.session_cadence import (
                    fire_arc_start, fire_post_take,
                )
                _goal = (db.get_user_profile(user_id) or {}).get("goal")
                # Always-on (2026-06-17): the framing fires here on take 1.
                # Idempotent per arc.
                if take_index == 1:
                    fire_arc_start(user_id, arc_id, goal=_goal)
                fire_post_take(
                    user_id, arc_id, take_index,
                    take_count=arc_take_count,
                    spark_enabled=spark_enabled,
                    goal=_goal,
                )
            except Exception as _ce:
                logger.warning("lab: cadence fire failed sid=%s: %s",
                               session_id, _ce)

        # AUTO-SEND to the coach (founder re-lock 2026-07-06, bug #4):
        # EVERY registered recording reaches the coach queue. Idempotent
        # + best-effort; the merge-path send stays the guest fallback.
        sent_local = False
        if user_id:
            try:
                from services.lab_send import send_lab_recording_to_coach
                _send_res = send_lab_recording_to_coach(
                    session_id, str(user_id),
                )
                sent_local = bool(_send_res.get("ok"))
                logger.info(
                    "lab: auto-send sid=%s ok=%s already=%s",
                    session_id, _send_res.get("ok"),
                    _send_res.get("already_sent"),
                )
            except Exception as _send_err:
                logger.warning(
                    "lab: auto-send failed sid=%s: %s (non-fatal)",
                    session_id, _send_err,
                )

        # Arc lifecycle cards + notes (founder #1/#11) — idempotent per
        # (arc, kind), best-effort.
        if user_id and arc_id:
            try:
                from services.arc_notifications import (
                    fire_human_check_note,
                )
                if take_index == 1:
                    fire_human_check_note(db, user_id, arc_id)
            except Exception as _bpe:
                logger.warning(
                    "lab: arc cards failed sid=%s: %s (non-fatal)",
                    session_id, _bpe,
                )

        _emit(progress, "finalizing", 90, "Preparing your results…")
        tl.mark("finalizing")

        # EAGER ideal-text assembly (founder 2026-07-15): the moment the
        # arc's 3rd SPOKEN take finishes analysis, assemble + persist the
        # machine draft so the coach's panel opens instantly ("no loading
        # or anything" fixed at the source). Idempotent; never clobbers a
        # coach edit. Best-effort.
        #
        # Force-alignment on reads is RETIRED with the read-out-loud lane
        # (founder 2026-08-05). It had ground truth to align against — the
        # ideal-text version the user read — but that ground truth only ever
        # existed because a read existed. The ingest route now rejects
        # recording_kind='read', so the lane is unreachable by construction.
        #
        # SPOKEN ONLY (founder bug 2026-07-20). An older condition let a
        # RE-READ run the whole assembly (regenerate suggestions, reassemble
        # the text, bump the version, fire a ready bubble), so a re-read read
        # as a take. "Only a spoken take is a real take" is now enforced
        # here, not just in the counters.
        if arc_id and recording_kind == "spoken":
            try:
                from services.ideal_text_block import (
                    maybe_assemble_ideal_text,
                )
                # Star suggestions (2026-07-18): generate BEFORE the
                # assembly so the fresh text's anchors include the
                # suggestion-flagged picks. Best-effort.
                if _moment_suggestions_enabled():
                    try:
                        from services.moment_suggestions import (
                            generate_for_session,
                        )
                        generate_for_session(
                            session_id, arc_id)
                    except Exception as _ms_err:
                        logger.warning(
                            "lab: moment suggestions failed "
                            "sid=%s: %s (non-fatal)",
                            session_id, _ms_err)
                # Single deliverable (2026-07-17): assemble after
                # EVERY take (take 1 included) AND every re-read;
                # a changed compose bumps the version, resetting
                # verification. The per-VERSION ready bubble fires
                # idempotently (a no-op reassembly re-fires the
                # same version key → deduped).
                # MASTER DOCUMENT (founder 2026-07-22, flag-gated):
                # judge this take against the persistent master
                # BEFORE assembly — take 1 builds the skeleton,
                # later takes write approve-gated block upgrade
                # offers. Best-effort; the master never moves
                # without an accept.
                try:
                    from services.master_document import (
                        master_document_enabled, process_new_take,
                    )
                    if master_document_enabled():
                        process_new_take(arc_id, session_id,
                                         db)
                except Exception as _md_err:
                    logger.warning(
                        "lab: master-document take processing "
                        "failed sid=%s: %s (non-fatal)",
                        session_id, _md_err)
                _eager_ok = maybe_assemble_ideal_text(
                    arc_id, require_target=False,
                    include_suggestion_anchors=(
                        _moment_suggestions_enabled()))
                if _eager_ok and user_id:
                    from services.arc_notifications import (
                        fire_ideal_version_ready,
                    )
                    _row = db.get_coach_arc_ideal_text(arc_id) or {}
                    _new_v = _row.get("version") or 1
                    # Spoken take count → the takes-1-and-2 nudge
                    # line (bug token 3c; soft nudge, never a gate).
                    try:
                        from services.best_presentation import (
                            spoken_arc_sessions,
                        )
                        _n_spoken = len(spoken_arc_sessions(
                            db.get_arc_sessions(arc_id)))
                    except Exception:
                        _n_spoken = None
                    fire_ideal_version_ready(
                        db, user_id, arc_id, _new_v,
                        spoken_take_count=_n_spoken)
                    # BE-4: a student edit of a PRIOR version is the
                    # strongest phrasing-preference signal the corpus
                    # gets. The assembler has no per-user selection
                    # channel yet, so capture it as structured
                    # metadata (selection-influence = named follow-up).
                    try:
                        _pe = db.get_user_ideal_edit(arc_id, user_id)
                        if _pe and isinstance(_pe.get("version"), int) \
                                and _pe["version"] < _new_v:
                            logger.info(
                                "ideal_text: user-edit superseded "
                                "arc=%s edited_v=%s new_v=%s chars=%d "
                                "(preference signal; assembler "
                                "selection-influence is a follow-up)",
                                arc_id, _pe["version"], _new_v,
                                len(_pe.get("text") or ""))
                    except Exception:
                        pass
            except Exception as _ea_err:
                logger.warning(
                    "lab: eager ideal-text failed sid=%s: %s (non-fatal)",
                    session_id, _ea_err,
                )
    return readout_local, sent_local
