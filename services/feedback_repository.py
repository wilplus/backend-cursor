"""Canonical FeedbackItem repository over coach draft persistence.

This is the only module allowed to translate the historical
``coach_snippet_drafts`` shape (note/tag/surfaced) into product FeedbackItems.
Routes, readouts and publish orchestration consume canonical items.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from services.canonical_product import (
    CoachReviewState,
    EvidenceLocator,
    FeedbackFamily,
    FeedbackItem,
)


class FeedbackContractError(ValueError):
    """A surfaced item cannot be delivered under the product contract."""


_LEGACY_FAMILY = {
    "strong": FeedbackFamily.GREAT_FORMULATION,
    "to_work_on": FeedbackFamily.REWRITE_FOR_CLARITY,
}

LEGACY_COACH_TAGS = tuple(_LEGACY_FAMILY)


def normalize_coach_overall_message(value: Any) -> str | None:
    """Validate the optional take-level summary kept beside FeedbackItems."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise FeedbackContractError("overall_message: must be a string")
    clean = value.strip()
    if len(clean) > 4000:
        raise FeedbackContractError("overall_message: 4000 chars max")
    return clean or None


def _family(row: dict) -> FeedbackFamily:
    raw = row.get("feedback_family")
    try:
        return FeedbackFamily(str(raw))
    except ValueError:
        pass
    legacy = _LEGACY_FAMILY.get(str(row.get("tag") or ""))
    if legacy is not None:
        return legacy
    # An unclassified written coach note is verbal feedback, never acoustic
    # praise.  Great Formulation is the neutral compatibility projection.
    return FeedbackFamily.GREAT_FORMULATION


def _project_id(session: dict) -> str:
    """Canonical id, with the historical arc id confined to this adapter."""
    value = session.get("project_id") or session.get("arc_id")
    if not value:
        raise FeedbackContractError("feedback requires a project")
    return str(value)


def _document_evidence(database: Any, session: dict, snippet: dict) -> EvidenceLocator:
    from services.transcript_document import build_transcript_document

    take_id = str(session.get("id") or snippet.get("session_id") or "")
    document = build_transcript_document(
        session.get("arc_id") or session.get("project_id"),
        database=database,
        session_id=take_id,
    ) or {}
    raw_pieces = document.get("pieces")
    pieces: list[dict[str, Any]] = (
        [piece for piece in raw_pieces if isinstance(piece, dict)]
        if isinstance(raw_pieces, list)
        else []
    )
    raw_paragraphs = document.get("paragraphs")
    paragraphs: list[dict[str, Any]] = (
        [paragraph for paragraph in raw_paragraphs
         if isinstance(paragraph, dict)]
        if isinstance(raw_paragraphs, list)
        else []
    )
    piece = next(
        (p for p in pieces if str(p.get("snippet_id") or "") == str(snippet.get("id") or "")),
        None,
    )
    if not piece:
        raise FeedbackContractError("feedback requires an exact transcript span")
    slide_index = piece.get("slide_index")
    if not isinstance(slide_index, int) or isinstance(slide_index, bool):
        raise FeedbackContractError("feedback requires an exact slide")
    start = piece.get("start")
    end = piece.get("end")
    if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
        raise FeedbackContractError("feedback requires a valid evidence span")
    paragraph_index = next(
        (
            index
            for index, paragraph in enumerate(paragraphs)
            if isinstance(paragraph, dict)
            and isinstance(paragraph.get("start"), int)
            and isinstance(paragraph.get("end"), int)
            and paragraph["start"] <= start < paragraph["end"]
        ),
        None,
    )
    if paragraph_index is None:
        raise FeedbackContractError("feedback requires an exact paragraph")

    audio_interval = None
    start_ms = snippet.get("start_offset_ms")
    duration_ms = snippet.get("duration_ms")
    if isinstance(start_ms, (int, float)) and isinstance(duration_ms, (int, float)):
        audio_interval = {
            "start_ms": max(0, int(start_ms)),
            "end_ms": max(0, int(start_ms + duration_ms)),
        }
    return EvidenceLocator(
        project_id=_project_id(session),
        take_id=take_id,
        slide_index=slide_index,
        paragraph_index=paragraph_index,
        evidence_span={"start": start, "end": end, "text": piece.get("text") or ""},
        audio_interval=audio_interval,
        piece_id=str(snippet.get("id") or "") or None,
    )


class FeedbackRepository:
    def __init__(self, database: Any):
        self.database = database

    def _locator(self, session: dict, row: dict) -> EvidenceLocator:
        stored = row.get("evidence_locator")
        if isinstance(stored, dict):
            try:
                return EvidenceLocator(
                    project_id=str(stored["project_id"]),
                    take_id=str(stored["take_id"]),
                    slide_index=int(stored["slide_index"]),
                    paragraph_index=int(stored["paragraph_index"]),
                    evidence_span=dict(stored["evidence_span"]),
                    audio_interval=(
                        dict(stored["audio_interval"])
                        if isinstance(stored.get("audio_interval"), dict)
                        else None
                    ),
                    piece_id=(
                        str(stored["piece_id"])
                        if stored.get("piece_id")
                        else str(row.get("snippet_id") or "") or None
                    ),
                )
            except (KeyError, TypeError, ValueError):
                pass
        snippet = self.database.get_snippet_by_id(str(row.get("snippet_id") or ""))
        if not snippet or str(snippet.get("session_id") or "") != str(session.get("id") or ""):
            raise FeedbackContractError("feedback evidence does not belong to this take")
        return _document_evidence(self.database, session, snippet)

    def surfaced_items(self, take_id: str, *, published_only: bool = False) -> list[FeedbackItem]:
        session = self.database.v2_get_session_by_id(str(take_id)) or {}
        if not session:
            raise FeedbackContractError("take not found")
        if published_only and not session.get("results_published_at"):
            return []
        items: list[FeedbackItem] = []
        for row in self.database.get_coach_snippet_drafts(str(take_id)) or []:
            if not row.get("surfaced"):
                continue
            message = str(row.get("note") or "").strip()
            replacement = str(row.get("transcript_corrected") or "").strip() or None
            if not message:
                # A surfaced switch without authored feedback is not a
                # FeedbackItem.  Treating it as absent makes an empty
                # professional verdict a valid "no changes needed" result.
                continue
            state_raw = row.get("review_state") or CoachReviewState.REVIEWED.value
            try:
                review_state = CoachReviewState(str(state_raw))
            except ValueError as error:
                raise FeedbackContractError("invalid coach review state") from error
            family = _family(row)
            locator = self._locator(session, row)
            if family is FeedbackFamily.CONFIDENT_VOICE \
                    and locator.audio_interval is None:
                raise FeedbackContractError(
                    "confident voice feedback requires playable audio evidence")
            if family is FeedbackFamily.REWRITE_FOR_CLARITY and not replacement:
                raise FeedbackContractError(
                    "rewrite feedback requires proposed replacement text")
            items.append(FeedbackItem(
                id=f"coach:{take_id}:{row.get('snippet_id')}",
                family=family,
                message=message,
                evidence=locator,
                review_state=review_state,
                replacement_text=replacement,
                application_guidance=(
                    str(row.get("when_context") or "").strip() or None
                ),
                examples=tuple(
                    str(example).strip()
                    for example in (row.get("examples") or [])
                    if str(example).strip()
                ),
            ))
        return items

    def publish(self, take_id: str, *, actor_user_id: str | None) -> list[FeedbackItem]:
        """Validate exact evidence and mark current surfaced items reviewed.

        An empty list is a valid professional verdict: no changes needed.
        """
        session = self.database.v2_get_session_by_id(str(take_id)) or {}
        if not session:
            raise FeedbackContractError("take not found")
        items = self.surfaced_items(str(take_id))
        for item in items:
            if item.review_state is None:
                raise FeedbackContractError(
                    "published feedback requires a coach review state")
            snippet_id = item.id.rsplit(":", 1)[-1]
            saved = self.database.upsert_coach_snippet_draft(
                str(take_id),
                snippet_id,
                {
                    "feedback_family": item.family.value,
                    "review_state": item.review_state.value,
                    "evidence_locator": asdict(item.evidence),
                },
                updated_by=actor_user_id,
            )
            if saved is None:
                raise FeedbackContractError("could not publish coach feedback")
        return items


def serialize_feedback_item(item: FeedbackItem) -> dict:
    return {
        "id": item.id,
        "family": item.family.value,
        "message": item.message,
        "review_state": item.review_state.value if item.review_state else None,
        "replacement_text": item.replacement_text,
        "application_guidance": item.application_guidance,
        "examples": list(item.examples),
        "user_decision": item.user_decision.value,
        "evidence": asdict(item.evidence),
    }
