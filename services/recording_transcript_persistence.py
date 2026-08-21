"""Per-slide or deckless transcript persistence for a processed recording."""
from __future__ import annotations

import logging
from typing import Any

from services.recording_state import RecordingState


logger = logging.getLogger(__name__)


def _persist_boundary_metrics(
    state: RecordingState,
    slides: list,
    *,
    database: Any,
    log: logging.Logger,
) -> None:
    try:
        from services.slide_boundary_metrics import boundary_metrics

        metrics = boundary_metrics(
            list(state.words_all),
            (state.session_context or {}).get("slide_advances"),
            slides,
        )
        if metrics:
            database.set_session_boundary_metrics(state.session_id, metrics)
    except Exception as error:
        log.warning(
            "boundary metrics failed sid=%s: %s",
            state.session_id,
            error,
        )


def _persist_deck_transcript(
    state: RecordingState,
    slides: list,
    *,
    database: Any,
    log: logging.Logger,
) -> None:
    from services.slide_word_split import build_slide_transcripts

    transcript = build_slide_transcripts(
        list(state.words_all),
        (state.session_context or {}).get("slide_advances"),
        slides,
    )
    if any((item.get("transcript") or "").strip() for item in transcript):
        database.set_session_slide_transcripts(state.session_id, transcript)
    _persist_boundary_metrics(
        state,
        slides,
        database=database,
        log=log,
    )


def persist_recording_transcript(
    state: RecordingState,
    *,
    database: Any,
    log: logging.Logger = logger,
) -> None:
    """Persist the authoritative transcript view without blocking recording."""
    try:
        slides = (state.session_context or {}).get("slides")
        if slides and state.words_all:
            _persist_deck_transcript(
                state,
                slides,
                database=database,
                log=log,
            )
        elif not slides:
            database.set_session_slide_transcripts(
                state.session_id,
                list(state.canonical_pieces),
            )
    except Exception as error:
        from services.f1_observability import observe_f1_degrade

        observe_f1_degrade(
            "slide_transcript_failed",
            exc=error,
            session_id=state.session_id,
        )
