"""Canonical-piece construction and acoustic enrichment stage.

The piece is the single authoritative feedback moment. This stage turns the
word-timestamp stream into exact text/audio pieces, computes their acoustic
features, selects the bounded expensive-analysis set, snapshots raw features
before derived reads, and attaches coach/user confidence enrichments.

It does not score text against slides, persist rows, or dispatch feedback.
"""
from __future__ import annotations

from dataclasses import replace
import logging

from services.recording_state import RecordingState


logger = logging.getLogger(__name__)


class PiecesCanonicalUnavailable(RuntimeError):
    """The take cannot be represented by canonical text/audio pieces."""


def build_canonical_pieces(words_all: list, session_context: dict | None) -> list:
    """Build the one authoritative moment set from Whisper word timestamps."""
    if not words_all:
        raise PiecesCanonicalUnavailable(
            "Canonical piece processing requires Whisper word-level timestamps"
        )

    from services.slide_word_split import (
        chunk_slide_words_by_chars,
        chunk_words_by_chars,
    )

    context = session_context or {}
    slides = context.get("slides")
    if slides:
        pieces = chunk_slide_words_by_chars(
            words_all,
            context.get("slide_advances"),
            slides,
        )
    else:
        pieces = chunk_words_by_chars(words_all)

    usable = [
        piece for piece in (pieces or [])
        if isinstance(piece, dict) and (piece.get("transcript") or "").strip()
    ]
    if not usable:
        raise PiecesCanonicalUnavailable(
            "Whisper word-level timestamps produced no canonical pieces"
        )
    return usable


def piece_llm_budget() -> int:
    """Return the bounded number of pieces that receive expensive layers."""
    import os

    try:
        return max(1, int(os.getenv("WILLAB_PIECE_LLM_BUDGET") or "16"))
    except (TypeError, ValueError):
        return 16


def _core_metrics(state: RecordingState, pieces: list) -> list[dict]:
    from services.audio_metrics import analyze_pcm_window

    analyzed: list[dict] = []
    for index, piece in enumerate(pieces, start=1):
        start_ms = int(piece.get("start_offset_ms") or 0)
        duration_ms = int(piece.get("duration_ms") or 0)
        transcript = piece.get("transcript") or ""
        metrics = analyze_pcm_window(
            state.signal,
            start_offset_ms=start_ms,
            duration_ms=duration_ms,
            transcript=transcript,
            include_librosa=False,
        ) or {}
        provenance = {"index": piece.get("index")}
        if piece.get("slide_index") is not None:
            provenance["slide_index"] = piece.get("slide_index")
        metrics["piece"] = provenance
        metrics["recording_kind"] = state.persisted_recording_kind
        analyzed.append({
            "start_ms": start_ms,
            "dur_ms": duration_ms,
            "metrics": metrics,
            "transcript": transcript,
            "idx": index,
        })
    return analyzed


def _budget_indices(analyzed: list[dict], budget: int) -> set[int]:
    if len(analyzed) <= budget:
        return set(range(len(analyzed)))

    from services.snippet_salience import rank_candidates_by_salience

    selected = {
        id(piece)
        for piece in rank_candidates_by_salience(analyzed, top_n=budget)
    }
    return {
        index for index, piece in enumerate(analyzed)
        if id(piece) in selected
    }


def _upgrade_budget_metrics(
    state: RecordingState,
    analyzed: list[dict],
    budget_indices: set[int],
) -> None:
    from services.audio_metrics import analyze_pcm_window

    for index in sorted(budget_indices):
        piece = analyzed[index]
        richer_metrics = analyze_pcm_window(
            state.signal,
            start_offset_ms=piece["start_ms"],
            duration_ms=piece["dur_ms"],
            transcript=piece["transcript"],
            include_librosa=True,
        ) or {}
        provenance = piece["metrics"].get("piece")
        piece["metrics"] = richer_metrics
        if provenance is not None:
            piece["metrics"]["piece"] = provenance


def _attach_voice_confidence(
    state: RecordingState,
    analyzed: list[dict],
    *,
    log: logging.Logger,
) -> None:
    try:
        from services.voice_confidence import (
            attach_voice_confidence,
            enabled,
            resolve_confidence_baseline,
            resolve_take_sex,
        )

        if not enabled():
            return
        baseline, baseline_kind = resolve_confidence_baseline(
            state.user_id,
            [piece.get("metrics") for piece in analyzed],
        )
        sex, sex_source = resolve_take_sex(
            state.user_id,
            state.session_context,
            baseline,
        )
        attach_voice_confidence(
            analyzed,
            baseline=baseline,
            baseline_kind=baseline_kind,
            sex=sex,
            sex_source=sex_source,
        )
    except Exception as error:
        log.warning(
            "process_lab_recording: voice confidence failed sid=%s: %s "
            "(non-fatal)",
            state.session_id,
            error,
        )


def _refresh_acoustic_baseline(
    state: RecordingState,
    *,
    log: logging.Logger,
) -> None:
    """Refresh the neutral speaker reference without stamping a state read."""
    try:
        from services.acoustic_baseline import resolve_for_take

        resolve_for_take(
            state.user_id,
            recording_kind=state.persisted_recording_kind,
            paired_session_id=state.paired_session_id,
        )
    except Exception as error:
        log.warning(
            "process_lab_recording: acoustic baseline refresh failed sid=%s: %s "
            "(non-fatal)",
            state.session_id,
            error,
        )


def analyze_canonical_pieces(
    state: RecordingState,
    *,
    log: logging.Logger = logger,
) -> RecordingState:
    """Return a new state containing canonical, acoustically enriched pieces."""
    pieces = build_canonical_pieces(
        list(state.words_all),
        state.session_context,
    )
    analyzed = _core_metrics(state, pieces)
    budget = piece_llm_budget() if state.run_analytics else 0
    budget_indices = _budget_indices(analyzed, budget)
    _upgrade_budget_metrics(state, analyzed, budget_indices)

    # Validation-sample independence: snapshot raw metrics before any derived
    # confidence read is stamped onto the canonical pieces.
    raw_snapshot = [dict(piece["metrics"]) for piece in analyzed]

    _refresh_acoustic_baseline(state, log=log)
    _attach_voice_confidence(state, analyzed, log=log)

    return replace(
        state,
        canonical_pieces=tuple(pieces),
        analyzed_pieces=tuple(analyzed),
        llm_budget_indices=frozenset(budget_indices),
        raw_metrics_snapshot=tuple(raw_snapshot),
    )
