"""Materialized, actor-scoped Ideal Text core documents.

The read screen must never rebuild a document.  Processing and product
mutations call :func:`publish_for_arc`; the cold-open endpoint performs one
head+snapshot read and returns the frozen payload.  Feedback, playback,
exercise, coach and analytics state deliberately stay outside this module.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from typing import Any, Mapping

from services.ideal_text_read import (
    resolve_ideal_text_source,
    resolve_live_text,
    resolve_project_read,
    resolve_suggestion_display,
)

logger = logging.getLogger(__name__)
PUBLICATION_TASK_PATH = (
    "services.ideal_text_core_snapshot.run_pending_publication")


def _canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _completed_spoken(sessions: Any) -> list[Mapping[str, Any]]:
    return [row for row in (sessions or [])
            if row.get("recording_kind") != "read"
            and not row.get("paired_session_id")
            and row.get("analysis_state") in (None, "ready")]


def _applied_moments(database: Any, session_ids: list[Any]) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for session_id in {str(value) for value in session_ids if value}:
        try:
            rows = database.get_suggestion_feedback_by_session(session_id) or []
        except Exception:
            continue
        for row in rows:
            if row.get("target") not in (
                    "moment_emphasize", "moment_replace",
                    "document_replace", "document_bold"):
                continue
            snippet_id = row.get("snippet_id")
            if snippet_id is not None:
                result[str(snippet_id)] = row.get("action") == "applied"
    return {key: value for key, value in result.items() if value}


def _fold_applied(text: str, moments: list[dict[str, Any]]) -> str:
    """Pure legacy-decision fold used only while materializing a snapshot."""
    from services.ideal_text_block import accent_span, within_accent_window
    for moment in moments or []:
        if not moment.get("applied"):
            continue
        suggestion = moment.get("suggestion") or {}
        moment_id = moment.get("id")
        take_id = moment.get("take_session_id")
        if not moment_id or not take_id:
            continue
        pattern = re.compile(
            r"\[\[moment:" + re.escape(str(moment_id)) + r"\|"
            + re.escape(str(take_id)) + r"\]\](?P<inner>.*?)\[\[/moment\]\]",
            re.DOTALL,
        )
        if suggestion.get("kind") == "replace" and str(
                suggestion.get("replacement") or "").strip():
            replacement = str(suggestion["replacement"]).strip()
            text = pattern.sub(
                lambda _match: (
                    f"[[moment:{moment_id}|{take_id}]]{replacement}[[/moment]]"
                ), text, count=1)
        elif suggestion.get("kind") == "emphasize":
            def emphasize(match: re.Match[str]) -> str:
                inner = match.group("inner")
                if "{{orange:" in inner or not within_accent_window(inner):
                    return match.group(0)
                return (f"[[moment:{moment_id}|{take_id}]]"
                        f"{accent_span(inner)}[[/moment]]")
            text = pattern.sub(emphasize, text, count=1)
    return text


def _suggestions_enabled() -> bool:
    return (os.getenv("MOMENT_SUGGESTIONS_ENABLED") or "0").strip().lower() \
        in ("1", "true", "yes")


def _exact_pieces(
    row: Mapping[str, Any],
    text: str,
    parts: list[dict[str, Any]] | None,
    previous_payload: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return only provable paragraph→Slide mappings; never position-guess.

    The first snapshot proves Slide lineage from the canonical Take-1
    document.  Later wording edits preserve stable Paragraph ids, so their
    already-proven Slide lineage can be carried from the previous immutable
    snapshot.  New/split/merged Paragraph ids receive no attachment until a
    writer publishes explicit lineage.
    """
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    document = row.get("document") if isinstance(row.get("document"), dict) else {}
    provenance = document.get("paragraphs") if isinstance(document, dict) else []
    source_text = str(row.get("auto_text") or row.get("text") or "").strip()
    source_paragraphs = [part.strip() for part in source_text.split("\n\n")
                         if part.strip()]
    aligned = (
        isinstance(provenance, list)
        and len(provenance) == len(paragraphs) == len(source_paragraphs)
        and source_paragraphs == paragraphs
    )
    previous_by_part: dict[str, Mapping[str, Any]] = {}
    if isinstance(previous_payload, Mapping):
        previous_parts = previous_payload.get("parts")
        previous_pieces = previous_payload.get("pieces")
        if isinstance(previous_parts, list) and isinstance(previous_pieces, list) \
                and len(previous_parts) == len(previous_pieces):
            for old_part, old_piece in zip(previous_parts, previous_pieces):
                if not isinstance(old_part, Mapping) \
                        or not isinstance(old_piece, Mapping):
                    continue
                old_id = str(old_part.get("id") or "")
                if old_id:
                    previous_by_part[old_id] = old_piece

    out: list[dict[str, Any]] = []
    for index, paragraph in enumerate(paragraphs):
        part = parts[index] if parts and index < len(parts) else {}
        previous = previous_by_part.get(str(part.get("id") or ""), {})
        source: Mapping[str, Any] = previous
        if aligned and isinstance(provenance, list):
            candidate = provenance[index]
            if isinstance(candidate, Mapping):
                source = candidate
        slide = source.get("slide_index")
        if isinstance(slide, bool) or not isinstance(slide, int) or slide < 0:
            slide = None
        out.append({
            "piece_key": index,
            "text": paragraph,
            "root_phrase": part.get("root_phrase"),
            "root_type": "flagship" if part.get("root_phrase") else None,
            "slide_index": slide,
            "block_key": None,
            "snippet_id": source.get("snippet_id"),
            "take_session_id": source.get("take_session_id"),
            "take_index": source.get("take_index"),
            "status": "settled",
            "challenger": None,
        })
    return out


def build_snapshot(
    database: Any,
    arc_id: str,
    actor_id: str,
    sessions: list[Mapping[str, Any]],
    previous_payload: Mapping[str, Any] | None = None,
) -> tuple[dict, dict, dict]:
    """Build the core payload at a write boundary.

    Returns ``(payload, enrichment_seed, lineage)``.  This function may
    persist a newly composed part list because it runs only while publishing;
    the GET path never calls it.
    """
    row = database.get_coach_arc_ideal_text(arc_id) or {}
    source = resolve_ideal_text_source(row)
    if not source.machine_text:
        raise ValueError("IDEAL_TEXT_DOCUMENT_PENDING")
    live = resolve_live_text(arc_id, actor_id, source, database=database)
    display = resolve_suggestion_display(
        arc_id, live.text, live.user_edited, database=database,
        suggestions_enabled=_suggestions_enabled,
        applied_lookup=lambda ids: _applied_moments(database, ids),
        fold_applied=_fold_applied,
    )
    from services.ideal_text_block import (
        extract_key_moments, sanitize_markers, strip_moment_markers,
    )
    text_with_moments = sanitize_markers(display.text)
    moment_seeds = extract_key_moments(text_with_moments)
    text = strip_moment_markers(text_with_moments)

    from services.ideal_text_parts import compose_locked, serve
    stored_rows = database.get_ideal_text_parts(
        arc_id, actor_id, with_lock=True) or []
    composed = compose_locked(text, stored_rows)
    if composed is not None:
        text = composed["text"]
        if composed.get("changed"):
            locks = {str(row0.get("id")): row0.get("locked_at")
                     for row0 in stored_rows if isinstance(row0, dict)}
            database.replace_ideal_text_parts(
                arc_id, actor_id,
                [{**part, "locked_at": locks.get(str(part["id"]))}
                 for part in composed["parts"]])
            stored_rows = database.get_ideal_text_parts(
                arc_id, actor_id, with_lock=True) or []
    served_parts = serve(stored_rows)
    if served_parts is not None:
        from services.ideal_text_parts import agrees_with_text
        if not agrees_with_text(served_parts, text):
            served_parts = None

    project = resolve_project_read(
        sessions, completed_spoken=_completed_spoken)
    if not project.spoken_rows or not project.latest_take_session_id:
        raise ValueError("IDEAL_TEXT_DOCUMENT_TAKE_REQUIRED")
    latest = project.spoken_rows[-1]
    owner = str(latest.get("owner_principal_id") or "")
    project_id = str(latest.get("project_id") or "")
    if not owner or not project_id:
        raise ValueError("IDEAL_TEXT_DOCUMENT_LINEAGE_REQUIRED")
    version = source.version if isinstance(source.version, int) else 1
    payload = {
        "arc_id": arc_id,
        "version": version,
        "status": live.status,
        "title": project.title,
        "updated_at": row.get("updated_at"),
        "latest_take_session_id": project.latest_take_session_id,
        "take_count": len(project.spoken_rows),
        "can_record_take": project.can_record_take,
        "text": text,
        "presentation_ref": project.presentation_ref or None,
        "slide_titles": project.slide_titles,
        "pieces": _exact_pieces(
            row, text, served_parts, previous_payload=previous_payload),
        "parts": served_parts,
        "user_edited": bool(composed is None and live.user_edited),
    }
    seed = {
        "moments": moment_seeds,
        "prior_edit": live.prior_edit,
        "suggestions_enabled": display.enabled,
    }
    lineage = {
        "acquisition_principal_id": owner,
        "project_id": project_id,
        "source_take_session_id": project.latest_take_session_id,
        "version": version,
        "source_fingerprint_sha256": _canonical_sha({
            "payload": payload,
            "seed": seed,
            "row_updated_at": row.get("updated_at"),
        }),
    }
    return payload, seed, lineage


def enqueue_pending_publication(
    arc_id: str, source_generation: int | None = None,
) -> bool:
    """Best-effort broker delivery; the generation row is durable truth."""
    from services import job_queue
    if not job_queue.queue_configured():
        return False
    generation = source_generation
    if not isinstance(generation, int):
        from services.db import db
        generation = db.get_ideal_text_document_generation(str(arc_id))
    if not isinstance(generation, int):
        return False
    return job_queue.enqueue(
        PUBLICATION_TASK_PATH, str(arc_id), generation,
        rq_job_id=f"ideal-text-publish:{arc_id}:{generation}",
    )


def run_pending_publication(arc_id: str, source_generation: int) -> None:
    """RQ entry point. A newer generation supersedes this delivery safely."""
    from services.db import db
    current = db.get_ideal_text_document_generation(str(arc_id))
    if current != int(source_generation):
        return
    if publish_for_arc(db, str(arc_id), enqueue_on_failure=False) is None:
        raise RuntimeError("IDEAL_TEXT_DOCUMENT_PUBLICATION_RETRY_REQUIRED")


def sweep_pending_publications(database: Any, limit: int = 100) -> int:
    """Re-enqueue durable invalidations whose materialisation was interrupted."""
    queued = 0
    for row in database.list_pending_ideal_text_document_publications(limit):
        arc_id = str(row.get("arc_id") or "")
        generation = row.get("generation")
        if arc_id and isinstance(generation, int) and enqueue_pending_publication(
                arc_id, generation):
            queued += 1
    return queued


def publish_for_arc(database: Any, arc_id: str,
                    actor_id: str | None = None, *,
                    enqueue_on_failure: bool = True) -> dict | None:
    """Publish one immutable head; retry once if a source mutates mid-build."""
    try:
        sessions = database.get_arc_sessions(arc_id) or []
        spoken = _completed_spoken(sessions)
        if not spoken:
            return None
        latest = sorted(spoken, key=lambda row: row.get("take_index") or 0)[-1]
        actor = str(actor_id or latest.get("user_id")
                    or latest.get("owner_principal_id") or "")
        if not actor:
            return None
        for _attempt in range(2):
            generation = database.get_ideal_text_document_generation(
                str(arc_id))
            if not isinstance(generation, int):
                raise ValueError("IDEAL_TEXT_DOCUMENT_GENERATION_REQUIRED")
            previous = database.get_ideal_text_document_snapshot(
                str(arc_id), actor)
            previous_payload = (
                previous.get("payload")
                if isinstance(previous, Mapping)
                and isinstance(previous.get("payload"), Mapping)
                else None
            )
            payload, seed, lineage = build_snapshot(
                database, str(arc_id), actor, sessions,
                previous_payload=previous_payload)
            result = database.publish_ideal_text_document_snapshot(
                arc_id=str(arc_id), actor_id=actor, payload=payload,
                enrichment_seed=seed, source_generation=generation,
                **lineage)
            if result is not None:
                return result
        raise ValueError("IDEAL_TEXT_DOCUMENT_SOURCE_STALE")
    except Exception as error:
        logger.warning("ideal-text snapshot publish failed arc=%s: %s",
                       arc_id, error)
        if enqueue_on_failure:
            try:
                enqueue_pending_publication(str(arc_id))
            except Exception as enqueue_error:
                logger.warning(
                    "ideal-text snapshot retry enqueue failed arc=%s: %s",
                    arc_id, enqueue_error,
                )
        return None

