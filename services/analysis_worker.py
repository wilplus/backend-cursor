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
from services.ideal_text_confirmation import IdealTextUnconfirmedError

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
        _emit(progress, "transcribing", 15, "Transcribing your take…")
        tl.mark("transcribing")
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

        _emit(progress, "ideal_text", 55, "Building your Ideal Text…")
        tl.mark("ideal_text")

        # Explore-session cadence (Prompt A §6 C3) — after a take in an
        # arc, invite the NEXT take as a Lounge bubble. Authed only;
        # best-effort + idempotent.
        if user_id and arc_id:
            try:
                from services.session_cadence import fire_arc_start
                _goal = (db.get_user_profile(user_id) or {}).get("goal")
                # Always-on (2026-06-17): the framing fires here on take 1.
                # Idempotent per arc.
                if take_index == 1:
                    fire_arc_start(user_id, arc_id, goal=_goal)
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

        # INITIAL IDEAL TEXT (L1 + founder confirmation gate, 2026-08-26).
        # Take 1 creates the one canonical document. Its generation is NOT
        # best-effort: the worker may return successfully only after a fresh
        # database read proves non-empty persisted text. Take 2+ still creates
        # feedback moments, but never calls the assembler at all; therefore a
        # missing Take 1 document can never be silently backfilled by a later
        # transcript.
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
            _initial_take = (
                isinstance(take_index, int)
                and not isinstance(take_index, bool)
                and take_index == 1
            )
            _confirmed_row = None
            try:
                from services.ideal_text_confirmation import (
                    build_initial_ideal_text_from_stored_artifacts,
                )
                # Star suggestions (2026-07-18): generate BEFORE the
                # assembly so the fresh text's anchors include the
                # suggestion-flagged picks. Best-effort.
                _emit(progress, "feedback_moments", 72,
                      "Finding feedback moments…")
                tl.mark("feedback_moments")
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
                _emit(progress, "speaking_anchors", 90,
                      "Preparing your speaking anchors…")
                tl.mark("speaking_anchors")
                if _initial_take:
                    # The helper assembles solely from the transcript/snippet
                    # artifacts already persisted above, then polls the source
                    # row for at most 120 seconds. Its typed timeout escapes
                    # this block and becomes the dedicated terminal state.
                    _confirmed_row = \
                        build_initial_ideal_text_from_stored_artifacts(
                            db,
                            arc_id,
                            source_session_id=session_id,
                            include_suggestion_anchors=(
                                _moment_suggestions_enabled()),
                        )
                if _confirmed_row is not None and user_id:
                    from services.arc_notifications import (
                        fire_ideal_version_ready,
                    )
                    _new_v = _confirmed_row.get("version") or 1
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
            except IdealTextUnconfirmedError:
                # This is the Take 1 success boundary, not optional telemetry.
                # Queue/daemon/sync dispatchers translate it into the exact
                # durable terminal state and card; never retry transcription.
                raise
            except Exception as _ea_err:
                if _initial_take and _confirmed_row is None:
                    # Confirmation is the gate: any unexpected builder/read
                    # fault is also forbidden from falling through to ready.
                    raise IdealTextUnconfirmedError(str(arc_id)) from _ea_err
                logger.warning(
                    "lab: post-take feedback stage failed sid=%s: %s "
                    "(non-fatal)",
                    session_id, _ea_err,
                )

        # THE ACOUSTIC KPI (founder 2026-08-12) — fold this take into the
        # per-part moving average and advance the single-point-focus ratchet.
        #
        # AFTER the eager assembly, deliberately: the average is measured over
        # the CURRENT best-of document (L1's chosen takes), so folding before
        # the assembly would score the previous take's selection and report it
        # as this one's.
        #
        # Best-effort like everything else on this path. A KPI that cannot be
        # written degrades to "no focus", which every reader treats as "behave
        # exactly as before" — never as a take that fails (LIVE LOOP).
        # Opened BEFORE the work, like every other phase here: a mark closes
        # the phase that was running and starts the named one, so a mark
        # written after the block would attribute the fold to `finalizing` and
        # report `kpi` as 0ms forever.
        tl.mark("kpi")
        if arc_id and user_id and recording_kind == "spoken":
            try:
                from services.part_acoustics import fold_session
                fold_session(arc_id, user_id, session_id)
            except Exception as _pa_err:
                logger.warning(
                    "lab: part acoustics failed sid=%s: %s (non-fatal)",
                    session_id, _pa_err,
                )
            # THE ACOUSTIC SWAP OFFER (founder 2026-08-13, stage 4). A locked
            # paragraph is invisible to the ranker, so a later take that
            # finally lands it has no way in — this is the one path that asks.
            #
            # AFTER the fold, and the order is load-bearing twice over: the
            # fold is what makes the document's per-part acoustics current,
            # and it runs on the assembly this take just contributed to. A
            # swap offered before it would compare against the previous take's
            # numbers.
            #
            # Its own try/except rather than sharing the fold's: a swap that
            # cannot be offered must not look like a KPI that could not be
            # written, and neither may cost the take (LIVE LOOP).
            try:
                from services.swap_detector import offer_for_take
                offer_for_take(arc_id, user_id, session_id)
            except Exception as _sw_err:
                logger.warning(
                    "lab: swap offer failed sid=%s: %s (non-fatal)",
                    session_id, _sw_err,
                )
    # SESSION TERMINAL RESULT — deliberately OUTSIDE the pipeline timeline.
    # Reaching here means every stage above returned successfully. Take 1 has
    # its document-version ready card; Take 2+ keeps that document by L1 and
    # therefore needs its own per-session terminal identity instead. Best-
    # effort here is safe because the browser writes the same idempotent row
    # when it observes the completed job.
    if (user_id and arc_id and recording_kind == "spoken"
            and isinstance(take_index, int) and not isinstance(take_index, bool)
            and take_index > 1):
        try:
            from services.arc_notifications import fire_take_processed
            fire_take_processed(
                db, user_id, arc_id, session_id, take_index)
        except Exception as _take_result_err:
            logger.warning(
                "lab: take result failed sid=%s: %s (non-fatal)",
                session_id, _take_result_err,
            )
    return readout_local, sent_local
