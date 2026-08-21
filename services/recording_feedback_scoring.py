"""Independent text and slide feedback scoring for a canonical recording."""
from __future__ import annotations

from dataclasses import replace
import logging

from services.recording_state import RecordingState


logger = logging.getLogger(__name__)


def compute_overall_ranking(
    prelim: list,
    stickiness: list,
    slide_scores: list,
    llm_budget_indices: set[int],
) -> tuple[dict[int, float], dict[int, int]]:
    """Blend delivery and slide scores, then rank canonical budget pieces."""
    overall_by_index: dict[int, float] = {}
    rank_inputs: list[tuple[float, float, int, int]] = []
    for index in sorted(llm_budget_indices):
        piece = prelim[index]
        delivery = (
            stickiness[index] if index < len(stickiness) else {}
        ).get("composite")
        delivery = (
            float(delivery) if isinstance(delivery, (int, float)) else 0.0
        )
        slide = slide_scores[index] if index < len(slide_scores) else None
        slide_score = slide.get("composite") if isinstance(slide, dict) else None
        overall = (
            0.5 * delivery + 0.5 * float(slide_score)
            if isinstance(slide_score, (int, float))
            else delivery
        )
        overall_by_index[index] = overall
        rank_inputs.append((overall, delivery, piece["start_ms"], index))

    rank_by_index = {
        item[3]: rank + 1
        for rank, item in enumerate(sorted(
            rank_inputs,
            key=lambda value: (-value[0], -value[1], value[2]),
        ))
    }
    return overall_by_index, rank_by_index


def _score_stickiness(state: RecordingState, pieces: list[dict]) -> list[dict]:
    """Score only the bounded expensive-analysis set, preserving list order."""
    if not state.run_analytics:
        return [{} for _ in pieces]

    from services.snippet_stickiness import score_snippets_stickiness

    budget_order = sorted(state.llm_budget_indices)
    budget_scores = score_snippets_stickiness([
        {"id": None, "transcript": pieces[index]["transcript"]}
        for index in budget_order
    ])
    scores: list[dict] = [{} for _ in pieces]
    for budget_position, piece_index in enumerate(budget_order):
        scores[piece_index] = (
            budget_scores[budget_position]
            if budget_position < len(budget_scores)
            else {}
        )
    return scores


def _piece_slide_input(piece: dict) -> dict:
    provenance = piece["metrics"].get("piece")
    return {
        "transcript": piece["transcript"],
        "duration_ms": piece["dur_ms"],
        "slide_index": (
            provenance.get("slide_index")
            if isinstance(provenance, dict)
            else None
        ),
    }


def _score_slides(
    state: RecordingState,
    pieces: list[dict],
    *,
    log: logging.Logger,
) -> tuple[list[dict], list[dict]]:
    """Return per-piece slide scores; failures preserve the empty score tier."""
    slide_scores: list[dict] = []
    slide_coverage: list[dict] = []
    try:
        slides = (state.session_context or {}).get("slides")
        if slides:
            from services.slide_alignment import compute_piece_slide_scores

            slide_scores = compute_piece_slide_scores(
                [_piece_slide_input(piece) for piece in pieces],
                slides,
                llm_budget_idx=set(state.llm_budget_indices),
            ) or []
    except Exception as error:
        log.warning(
            "process_lab_recording: slide scoring failed sid=%s err=%s",
            state.session_id,
            error,
        )
    return slide_scores, slide_coverage


def score_recording_feedback(
    state: RecordingState,
    *,
    log: logging.Logger = logger,
) -> RecordingState:
    """Run independent feedback units together and return their ranked result."""
    pieces = [dict(piece) for piece in state.analyzed_pieces]

    def _unit_stickiness() -> list[dict]:
        return _score_stickiness(state, pieces)

    def _unit_slide_scores() -> tuple[list[dict], list[dict]]:
        return _score_slides(state, pieces, log=log)

    from services.parallel import run_in_parallel

    sticky, (slide_scores, slide_coverage) = run_in_parallel(
        _unit_stickiness, _unit_slide_scores
    )
    overall, ranks = compute_overall_ranking(
        pieces,
        sticky,
        slide_scores,
        set(state.llm_budget_indices),
    )
    return replace(
        state,
        stickiness=tuple(sticky),
        slide_scores=tuple(slide_scores),
        slide_coverage=tuple(slide_coverage),
        overall_by_index=overall,
        rank_by_index=ranks,
    )
