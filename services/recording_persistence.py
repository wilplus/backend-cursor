"""Canonical snippet and raw candidate-corpus persistence stage."""
from __future__ import annotations

from dataclasses import replace
import logging
from typing import Any

from services.recording_state import RecordingState


logger = logging.getLogger(__name__)


def _piece_stickiness(state: RecordingState, index: int) -> dict:
    return state.stickiness[index] if index < len(state.stickiness) else {}


def _piece_metrics(state: RecordingState, index: int, piece: dict) -> dict:
    metrics = dict(piece["metrics"])
    metrics["recording_kind"] = state.persisted_recording_kind
    stickiness = _piece_stickiness(state, index)
    metrics["stickiness"] = {
        "composite": stickiness.get("composite"),
        "comment": stickiness.get("comment"),
    }

    slide_score = (
        state.slide_scores[index] if index < len(state.slide_scores) else None
    )
    if isinstance(slide_score, dict) and slide_score.get("composite") is not None:
        metrics["slide_stickiness"] = slide_score
    if index in state.overall_by_index:
        metrics["overall_score"] = round(state.overall_by_index[index], 3)
        metrics["rank"] = state.rank_by_index.get(index)
    if index == 0 and state.slide_coverage:
        metrics["slide_coverage"] = list(state.slide_coverage)
    return metrics


def _snippet_rows(state: RecordingState) -> tuple[list[dict], list[dict]]:
    from services.slide_word_split import slice_words_for_window

    words = list(state.words_all)
    metrics_by_index: list[dict] = []
    rows: list[dict] = []
    for index, piece in enumerate(state.analyzed_pieces):
        metrics = _piece_metrics(state, index, piece)
        snippet_words = (
            slice_words_for_window(
                words,
                piece["start_ms"],
                piece["start_ms"] + piece["dur_ms"],
            )
            if words
            else None
        )
        metrics_by_index.append(metrics)
        rows.append({
            "session_id": state.session_id,
            "user_id": state.user_id,
            "recording_id": state.recording_id,
            "start_offset_ms": piece["start_ms"],
            "duration_ms": piece["dur_ms"],
            "audio_segment_path": state.parent_audio_url,
            "metrics": metrics,
            "transcript": piece["transcript"] or None,
            "words": snippet_words or None,
        })
    return rows, metrics_by_index


def _persisted_snippets(
    state: RecordingState,
    ids: list,
    metrics_by_index: list[dict],
) -> list[dict]:
    snippets: list[dict] = []
    for index, piece in enumerate(state.analyzed_pieces):
        snippets.append({
            "id": ids[index] if index < len(ids) else None,
            "index": piece["idx"],
            "transcript": piece["transcript"],
            "audio_ref": state.parent_audio_url,
            "start_offset_ms": piece["start_ms"],
            "duration_ms": piece["dur_ms"],
            "metrics": metrics_by_index[index],
        })
    return snippets


def _stickiness_payload(state: RecordingState, snippets: list[dict]) -> list[dict]:
    return [
        {
            "snippet_id": snippet["id"],
            "composite": _piece_stickiness(state, index).get("composite"),
            "comment": _piece_stickiness(state, index).get("comment"),
        }
        for index, snippet in enumerate(snippets)
    ]


def _raw_candidate_rows(state: RecordingState, snippets: list[dict]) -> list[dict]:
    from services.candidate_capture import build_candidate_rows

    pieces = list(state.analyzed_pieces)
    surfaced_info = {
        piece["start_ms"]: {
            "rank": state.rank_by_index.get(index),
            "snippet_id": snippets[index]["id"] if index < len(snippets) else None,
        }
        for index, piece in enumerate(pieces)
    }
    candidates: list[dict] = []
    for index, piece in enumerate(pieces):
        raw_metrics = (
            dict(state.raw_metrics_snapshot[index])
            if index < len(state.raw_metrics_snapshot)
            else {}
        )
        raw_metrics.pop("piece", None)
        candidates.append({
            "start_ms": piece["start_ms"],
            "dur_ms": piece["dur_ms"],
            "metrics": raw_metrics,
            "transcript": piece.get("transcript"),
        })
    notable_starts = {
        pieces[index].get("start_ms")
        for index in state.llm_budget_indices
    }
    return build_candidate_rows(
        candidates,
        notable_starts=notable_starts,
        surfaced_info=surfaced_info,
        session_id=state.session_id,
        recording_id=state.recording_id,
        user_id=state.user_id,
        heuristic_version="pieces-200char-v1",
    )


def _capture_candidates(
    state: RecordingState,
    snippets: list[dict],
    *,
    database: Any,
    log: logging.Logger,
) -> None:
    try:
        rows = _raw_candidate_rows(state, snippets)
        inserted = database.insert_candidate_windows(rows)
        log.info(
            "process_lab_recording: candidate pool captured sid=%s windows=%d "
            "surfaced=%d",
            state.session_id,
            inserted,
            len(state.analyzed_pieces),
        )
    except Exception as error:
        log.warning(
            "process_lab_recording: candidate-pool capture failed sid=%s "
            "err=%s (non-fatal)",
            state.session_id,
            error,
        )


def persist_recording_snippets(
    state: RecordingState,
    *,
    database: Any,
    log: logging.Logger = logger,
) -> RecordingState:
    """Persist canonical rows and return their stable readout identities."""
    rows, metrics_by_index = _snippet_rows(state)
    ids = database.create_charisma_snippets_bulk(rows)
    snippets = _persisted_snippets(state, ids, metrics_by_index)
    stickiness_payload = _stickiness_payload(state, snippets)
    _capture_candidates(state, snippets, database=database, log=log)
    log.info(
        "process_lab_recording: sid=%s snippets=%d transcribed=%s",
        state.session_id,
        len(snippets),
        bool(state.segments),
    )
    return replace(
        state,
        persisted_snippets=tuple(snippets),
        stickiness_payload=tuple(stickiness_payload),
    )
