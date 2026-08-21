"""Prepare persisted snippet rows for the recording readout contract.

This module owns the snippet-level folds that are independent of deck or
deckless presentation context.  The public entry point deliberately receives
the few lab-recording contract helpers it needs, which keeps the module free of
an import cycle and makes every external dependency explicit in tests.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any


logger = logging.getLogger(__name__)


def replay_applied_upgrades(feedback_rows: list, card_sizes: dict) -> dict:
    """Rebuild each snippet's current applied-upgrade indexes from its log."""
    applied: dict = {}
    for row in feedback_rows or []:
        if not isinstance(row, dict):
            continue
        snippet_id = str(row.get("snippet_id") or "")
        if not snippet_id:
            continue
        current = applied.setdefault(snippet_id, set())
        action = row.get("action")
        target = row.get("target")
        index = row.get("upgrade_index")
        if action == "apply_all":
            current.update(range(int(card_sizes.get(snippet_id) or 0)))
        elif (
            target == "upgrade"
            and isinstance(index, int)
            and not isinstance(index, bool)
        ):
            if action == "applied":
                current.add(index)
            elif action == "reverted":
                current.discard(index)

    result: dict = {}
    for snippet_id, indexes in applied.items():
        size = int(card_sizes.get(snippet_id) or 0)
        kept = sorted(index for index in indexes if 0 <= index < size)
        if kept:
            result[snippet_id] = kept
    return result


def _load_user_edits(database: Any, session_id: str) -> tuple[dict, dict]:
    edits_by_snippet: dict = {}
    edits_by_chunk: dict = {}
    try:
        rows = database.get_user_transcript_edits(session_id) or []
        for row in rows:
            text = (row.get("text") or "").strip()
            if not text:
                continue
            if row.get("snippet_id"):
                edits_by_snippet[str(row["snippet_id"])] = text
            elif isinstance(row.get("chunk_index"), int):
                edits_by_chunk[row["chunk_index"]] = text
    except Exception:
        pass
    return edits_by_snippet, edits_by_chunk


def _upgrade_card(snippet: dict, include_upgrade_cards: bool) -> dict | None:
    if not include_upgrade_cards:
        return None
    final = snippet.get("say_it_stronger_final")
    if isinstance(final, dict):
        return final
    draft = snippet.get("say_it_stronger")
    return draft if isinstance(draft, dict) else None


def _attach_piece_provenance(output: dict, metrics: dict) -> None:
    piece = metrics.get("piece")
    if isinstance(piece, dict):
        output["piece_index"] = piece.get("index")
        if piece.get("slide_index") is not None:
            output["slide_index"] = piece.get("slide_index")

    recording_kind = metrics.get("recording_kind")
    if recording_kind in ("spoken", "read"):
        output["recording_kind"] = recording_kind


def _attach_coach_fields(output: dict, snippet: dict, metrics: dict) -> None:
    draft = snippet.get("say_it_stronger")
    if isinstance(draft, dict):
        output["say_it_stronger_draft"] = draft
    slide_stickiness = metrics.get("slide_stickiness")
    if isinstance(slide_stickiness, dict):
        output["slide_stickiness"] = slide_stickiness
    for key in ("overall_score", "rank"):
        if metrics.get(key) is not None:
            output[key] = metrics.get(key)
    acoustic_read = metrics.get("acoustic_read")
    if isinstance(acoustic_read, dict):
        output["acoustic_read"] = acoustic_read


def _serialize_snippets(
    snippets: list,
    *,
    edits_by_snippet: dict,
    include_slide_scores: bool,
    include_upgrade_cards: bool,
    playable: Callable[[Any], Any],
    feature_builder: Callable[[dict], dict],
) -> list:
    output_rows: list = []
    for index, snippet in enumerate(snippets):
        raw_metrics = snippet.get("metrics")
        metrics = raw_metrics if isinstance(raw_metrics, dict) else {}
        raw_stickiness = metrics.get("stickiness")
        stickiness = raw_stickiness if isinstance(raw_stickiness, dict) else {}
        output = {
            "id": snippet.get("id"),
            "index": index + 1,
            "transcript": (
                snippet.get("transcript")
                or snippet.get("transcription_text")
                or ""
            ),
            "audio_ref": playable(snippet.get("audio_segment_path")),
            "start_offset_ms": snippet.get("start_offset_ms"),
            "duration_ms": snippet.get("duration_ms"),
            "features": feature_builder(metrics),
            "stickiness": {
                "composite": stickiness.get("composite"),
                "comment": stickiness.get("comment"),
            },
            "say_it_stronger": _upgrade_card(
                snippet,
                include_upgrade_cards,
            ),
            "user_edited_text": edits_by_snippet.get(str(snippet.get("id"))),
        }
        _attach_piece_provenance(output, metrics)
        if include_slide_scores:
            _attach_coach_fields(output, snippet, metrics)
        output_rows.append(output)
    return output_rows


def _fold_applied_upgrade_state(
    database: Any,
    session_id: str,
    output_rows: list,
    *,
    log: logging.Logger,
) -> None:
    try:
        feedback_rows = database.get_suggestion_feedback_by_session(session_id)
        if not feedback_rows:
            return
        card_sizes = {
            str(row.get("id")): len(
                (row.get("say_it_stronger") or {}).get("upgrades") or []
            )
            for row in output_rows
            if isinstance(row.get("say_it_stronger"), dict)
        }
        applied = replay_applied_upgrades(feedback_rows, card_sizes)
        for row in output_rows:
            indexes = applied.get(str(row.get("id")))
            if indexes:
                row["applied_upgrade_indexes"] = indexes
    except Exception as error:
        log.warning(
            "readout: applied-state fold failed sid=%s: %s",
            session_id,
            error,
        )


def _fold_auto_comments(
    snippets: list,
    output_rows: list,
    *,
    include_slide_scores: bool,
    coach_prefill_enabled: Callable[[], bool],
    session_id: str,
    log: logging.Logger,
) -> None:
    has_piece_rows = any(
        row.get("piece_index") is not None for row in output_rows
    )
    if not has_piece_rows or not coach_prefill_enabled():
        return
    try:
        from services.auto_comment import acoustic_tone_word, build_auto_comment
        from services.say_it_stronger import aggregate_session_means

        means = aggregate_session_means(
            [{"metrics": snippet.get("metrics")} for snippet in snippets]
        )
        snippets_by_id = {str(snippet.get("id")): snippet for snippet in snippets}
        for output in output_rows:
            if output.get("piece_index") is None:
                continue
            snippet = snippets_by_id.get(str(output.get("id"))) or {}
            raw_metrics = snippet.get("metrics")
            metrics = raw_metrics if isinstance(raw_metrics, dict) else {}
            tone_word = (
                acoustic_tone_word(metrics)
                if include_slide_scores
                else metrics.get("user_tone_word")
            )
            output["auto_comment"] = build_auto_comment(
                metrics,
                means,
                tone_word=tone_word,
            )
    except Exception as error:
        log.warning(
            "readout: auto_comment fold failed sid=%s: %s",
            session_id,
            error,
        )


def _fold_breakthrough_markers(
    database: Any,
    session_id: str,
    snippets: list,
    output_rows: list,
    *,
    log: logging.Logger,
) -> None:
    try:
        from services.best_presentation import _moment_note
        from services.challenge_threat import detect_breakthroughs, resolve_direction

        coach_labels = {
            str(row.get("snippet_id")): row.get("value")
            for row in (database.get_training_labels(session_id) or [])
        }
        breakthrough_ids = detect_breakthroughs(
            [
                {
                    "id": snippet.get("id"),
                    "start_offset_ms": snippet.get("start_offset_ms"),
                    "direction": resolve_direction(
                        coach_labels.get(str(snippet.get("id"))),
                        None,
                    ),
                }
                for snippet in snippets
            ]
        )
        notes = {
            str(snippet.get("id")): _moment_note(snippet)
            for snippet in snippets
        }
        for output in output_rows:
            is_breakthrough = output.get("id") in breakthrough_ids
            output["breakthrough"] = is_breakthrough
            output["breakthrough_note"] = (
                notes.get(str(output.get("id"))) or None
                if is_breakthrough
                else None
            )
    except Exception as error:
        log.warning(
            "readout: breakthrough markers failed sid=%s: %s",
            session_id,
            error,
        )
        for output in output_rows:
            output.setdefault("breakthrough", False)
            output.setdefault("breakthrough_note", None)


def prepare_readout_snippets(
    database: Any,
    session_id: str,
    snippets: list,
    *,
    include_insights: bool,
    include_slide_scores: bool,
    include_upgrade_cards: bool,
    playable: Callable[[Any], Any],
    feature_builder: Callable[[dict], dict],
    coach_prefill_enabled: Callable[[], bool],
    log: logging.Logger = logger,
) -> tuple[list, dict]:
    """Return serialized snippets plus deckless chunk edits for later folds."""
    edits_by_snippet, edits_by_chunk = _load_user_edits(database, session_id)
    output_rows = _serialize_snippets(
        snippets,
        edits_by_snippet=edits_by_snippet,
        include_slide_scores=include_slide_scores,
        include_upgrade_cards=include_upgrade_cards,
        playable=playable,
        feature_builder=feature_builder,
    )
    _fold_applied_upgrade_state(
        database,
        session_id,
        output_rows,
        log=log,
    )
    _fold_auto_comments(
        snippets,
        output_rows,
        include_slide_scores=include_slide_scores,
        coach_prefill_enabled=coach_prefill_enabled,
        session_id=session_id,
        log=log,
    )
    if include_insights:
        _fold_breakthrough_markers(
            database,
            session_id,
            snippets,
            output_rows,
            log=log,
        )
    return output_rows, edits_by_chunk
