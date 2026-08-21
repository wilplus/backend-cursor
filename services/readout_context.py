"""Attach presentation, transcript, and instant-chunk context to readouts."""
from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger(__name__)


def attach_suggestions_to_chunks(chunks: list, output_snippets: list) -> list:
    """Attach each upgrade card to at most one containing transcript chunk."""
    output: list = []
    used_snippet_ids: set = set()
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        prepared = dict(chunk)
        prepared.setdefault("say_it_stronger", None)
        prepared.setdefault("snippet_id", None)
        chunk_start = prepared.get("start_offset_ms")
        chunk_duration = prepared.get("duration_ms")
        if (
            isinstance(chunk_start, (int, float))
            and isinstance(chunk_duration, (int, float))
            and chunk_duration > 0
        ):
            _attach_first_contained_suggestion(
                prepared,
                output_snippets,
                used_snippet_ids,
                chunk_start=chunk_start,
                chunk_duration=chunk_duration,
            )
        output.append(prepared)
    return output


def _attach_first_contained_suggestion(
    chunk: dict,
    output_snippets: list,
    used_snippet_ids: set,
    *,
    chunk_start: float,
    chunk_duration: float,
) -> None:
    for snippet in output_snippets:
        snippet_id = str(snippet.get("id"))
        if snippet_id in used_snippet_ids:
            continue
        if not isinstance(snippet.get("say_it_stronger"), dict):
            continue
        snippet_start = snippet.get("start_offset_ms")
        if not isinstance(snippet_start, (int, float)):
            continue
        snippet_duration = snippet.get("duration_ms")
        midpoint = snippet_start + (
            snippet_duration / 2.0
            if isinstance(snippet_duration, (int, float)) and snippet_duration > 0
            else 0
        )
        if chunk_start <= midpoint < chunk_start + chunk_duration:
            chunk["say_it_stronger"] = snippet.get("say_it_stronger")
            chunk["snippet_id"] = snippet.get("id")
            used_snippet_ids.add(snippet_id)
            return


def _canonical_piece_rows(output_snippets: list) -> list:
    piece_rows = [
        row for row in output_snippets if row.get("piece_index") is not None
    ]
    seen_indexes: set = set()
    canonical_rows: list = []
    for row in sorted(piece_rows, key=lambda item: item.get("piece_index") or 0):
        piece_index = row.get("piece_index")
        if piece_index in seen_indexes:
            continue
        seen_indexes.add(piece_index)
        canonical_rows.append(row)
    return canonical_rows


def _piece_instant_chunk(
    row: dict,
    *,
    edits_by_chunk: dict,
    include_upgrade_cards: bool,
) -> dict:
    chunk = {
        "index": row.get("piece_index"),
        "transcript": row.get("transcript") or "",
        "start_offset_ms": row.get("start_offset_ms"),
        "duration_ms": row.get("duration_ms"),
        "snippet_id": row.get("id"),
        "say_it_stronger": (
            row.get("say_it_stronger") if include_upgrade_cards else None
        ),
        "user_edited_text": (
            row.get("user_edited_text")
            or edits_by_chunk.get(row.get("piece_index"))
        ),
    }
    if row.get("slide_index") is not None:
        chunk["slide_index"] = row.get("slide_index")
    if row.get("recording_kind"):
        chunk["recording_kind"] = row.get("recording_kind")
    if row.get("applied_upgrade_indexes"):
        chunk["applied_upgrade_indexes"] = row.get(
            "applied_upgrade_indexes"
        )
    return chunk


def _attach_piece_instant_chunks(
    result: dict,
    output_snippets: list,
    *,
    edits_by_chunk: dict,
    include_upgrade_cards: bool,
) -> None:
    canonical_rows = _canonical_piece_rows(output_snippets)
    if canonical_rows:
        result["instant_chunks"] = [
            _piece_instant_chunk(
                row,
                edits_by_chunk=edits_by_chunk,
                include_upgrade_cards=include_upgrade_cards,
            )
            for row in canonical_rows
        ]


def _load_intake_context(database: Any, session_id: str) -> dict:
    try:
        context = database.get_session_intake_context(session_id) or {}
    except Exception:
        return {}
    return context if isinstance(context, dict) else {}


def _attach_setup_fields(result: dict, context: dict) -> None:
    if context.get("topic") or context.get("slides"):
        result["setup"] = {
            "topic": context.get("topic"),
            "audience": context.get("audience"),
            "target_length_seconds": context.get("target_length_seconds"),
            "slides": context.get("slides") or [],
            "presentation_ref": context.get("presentation_ref"),
        }
    raw_audience = context.get("audience")
    audience = raw_audience.strip() if isinstance(raw_audience, str) else ""
    if audience:
        result["audience"] = audience
    if context.get("presentation_ref"):
        result["presentation_ref"] = context.get("presentation_ref")


def _map_snippets_to_slides(
    output_snippets: list,
    *,
    advances: Any,
    slides: list,
) -> None:
    from services.slide_alignment import slide_for_snippet

    for snippet in output_snippets:
        slide = slide_for_snippet(snippet, advances, slides)
        if slide is not None:
            snippet["slide"] = slide


def _persisted_slide_transcripts(database: Any, session_id: str) -> Any:
    try:
        return database.get_session_slide_transcripts(session_id)
    except Exception:
        return None


def _word_union(snippets: list) -> list:
    words: list = []
    for snippet in snippets:
        snippet_words = snippet.get("words") if isinstance(snippet, dict) else None
        if isinstance(snippet_words, list):
            words.extend(snippet_words)
    return words


def _fallback_slide_transcripts(
    snippets: list,
    *,
    advances: Any,
    slides: list,
    session_id: str,
    log: logging.Logger,
) -> Any:
    try:
        from services.slide_word_split import build_slide_transcripts

        words = _word_union(snippets)
        if not words:
            return None
        candidate = build_slide_transcripts(words, advances, slides)
        if any(
            (item.get("transcript") or "").strip() for item in candidate
        ):
            return candidate
    except Exception as error:
        log.warning(
            "readout: slide_transcripts fallback failed sid=%s: %s",
            session_id,
            error,
        )
    return None


def _deck_instant_source(slide_transcripts: list) -> list:
    return [
        {
            "index": index,
            "slide_index": transcript.get("index"),
            "transcript": (transcript.get("transcript") or "").strip(),
            "start_offset_ms": transcript.get("start_offset_ms"),
            "duration_ms": transcript.get("duration_ms"),
        }
        for index, transcript in enumerate(slide_transcripts)
        if isinstance(transcript, dict)
        and (transcript.get("transcript") or "").strip()
    ]


def _attach_deck_context(
    database: Any,
    session_id: str,
    snippets: list,
    output_snippets: list,
    result: dict,
    *,
    context: dict,
    slides: list,
    log: logging.Logger,
) -> None:
    result["slides"] = slides
    advances = context.get("slide_advances")
    _map_snippets_to_slides(
        output_snippets,
        advances=advances,
        slides=slides,
    )
    slide_transcripts = _persisted_slide_transcripts(database, session_id)
    if not slide_transcripts:
        slide_transcripts = _fallback_slide_transcripts(
            snippets,
            advances=advances,
            slides=slides,
            session_id=session_id,
            log=log,
        )
    if not slide_transcripts:
        return
    result["slide_transcripts"] = slide_transcripts
    if "instant_chunks" not in result:
        result["instant_chunks"] = attach_suggestions_to_chunks(
            _deck_instant_source(slide_transcripts),
            output_snippets,
        )


def _attach_deckless_context(
    database: Any,
    session_id: str,
    output_snippets: list,
    result: dict,
    *,
    edits_by_chunk: dict,
) -> None:
    try:
        slide_transcripts = database.get_session_slide_transcripts(session_id)
        if not slide_transcripts:
            return
        full_transcript = " ".join(
            (item.get("transcript") or "").strip()
            for item in slide_transcripts
            if isinstance(item, dict)
            and (item.get("transcript") or "").strip()
        ).strip()
        if not full_transcript:
            return
        result["full_transcript"] = full_transcript
        from services.slide_word_split import deckless_chunks_from_stx

        chunks = deckless_chunks_from_stx(slide_transcripts)
        for chunk in chunks:
            chunk["user_edited_text"] = edits_by_chunk.get(chunk.get("index"))
        result["full_transcript_chunks"] = chunks
        if "instant_chunks" not in result:
            result["instant_chunks"] = attach_suggestions_to_chunks(
                chunks,
                output_snippets,
            )
    except Exception:
        pass


def attach_readout_context(
    database: Any,
    session_id: str,
    snippets: list,
    output_snippets: list,
    result: dict,
    *,
    edits_by_chunk: dict,
    include_upgrade_cards: bool,
    log: logging.Logger = logger,
) -> None:
    """Attach canonical chunks and deck/deckless presentation context."""
    _attach_piece_instant_chunks(
        result,
        output_snippets,
        edits_by_chunk=edits_by_chunk,
        include_upgrade_cards=include_upgrade_cards,
    )
    context = _load_intake_context(database, session_id)
    _attach_setup_fields(result, context)
    slides = context.get("slides")
    if slides:
        _attach_deck_context(
            database,
            session_id,
            snippets,
            output_snippets,
            result,
            context=context,
            slides=slides,
            log=log,
        )
    else:
        _attach_deckless_context(
            database,
            session_id,
            output_snippets,
            result,
            edits_by_chunk=edits_by_chunk,
        )
