"""Canonical FeedbackItem repository over coach draft persistence.

This is the only module allowed to translate the historical
``coach_snippet_drafts`` shape (note/tag/surfaced) into product FeedbackItems.
Routes, readouts and publish orchestration consume canonical items.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from services.canonical_product import (
    CoachReviewState,
    EvidenceLocator,
    FeedbackFamily,
    FeedbackItem,
)

logger = logging.getLogger(__name__)


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
    if raw:
        # A stated family is read as stated. An unknown one is a contract
        # error, never silently re-read as praise (audit 2026-09-26): the
        # column's CHECK makes it unreachable today, and this keeps a future
        # spelling from turning a rewrite into a compliment unnoticed.
        try:
            return FeedbackFamily(str(raw))
        except ValueError as error:
            raise FeedbackContractError(
                f"unknown feedback family {raw!r}") from error
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


def _dict_rows(value: Any) -> list[dict[str, Any]]:
    """The dict entries of a list; anything else is empty."""
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _exact_piece(pieces: list[dict[str, Any]], snippet: dict) -> tuple:
    """``(piece, slide_index, start, end)`` for the snippet's piece, or the
    refusal naming what is missing."""
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
    return piece, slide_index, start, end


def _paragraph_holding(paragraphs: list[dict[str, Any]], start: int) -> int:
    """The index of the paragraph that holds ``start``, or the refusal."""
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
    return paragraph_index


def _audio_interval(snippet: dict) -> dict[str, int] | None:
    start_ms = snippet.get("start_offset_ms")
    duration_ms = snippet.get("duration_ms")
    if isinstance(start_ms, (int, float)) and isinstance(duration_ms, (int, float)):
        return {
            "start_ms": max(0, int(start_ms)),
            "end_ms": max(0, int(start_ms + duration_ms)),
        }
    return None


def _document_evidence(database: Any, session: dict, snippet: dict) -> EvidenceLocator:
    from services.transcript_document import build_transcript_document

    take_id = str(session.get("id") or snippet.get("session_id") or "")
    document = build_transcript_document(
        session.get("arc_id") or session.get("project_id"),
        database=database,
        session_id=take_id,
    ) or {}
    piece, slide_index, start, end = _exact_piece(
        _dict_rows(document.get("pieces")), snippet)
    paragraph_index = _paragraph_holding(
        _dict_rows(document.get("paragraphs")), start)
    return EvidenceLocator(
        project_id=_project_id(session),
        take_id=take_id,
        slide_index=slide_index,
        paragraph_index=paragraph_index,
        evidence_span={"start": start, "end": end, "text": piece.get("text") or ""},
        audio_interval=_audio_interval(snippet),
        piece_id=str(snippet.get("id") or "") or None,
    )


def _review_state(row: dict) -> CoachReviewState:
    state_raw = row.get("review_state") or CoachReviewState.REVIEWED.value
    try:
        return CoachReviewState(str(state_raw))
    except ValueError as error:
        raise FeedbackContractError("invalid coach review state") from error


def _require_family_evidence(
    family: FeedbackFamily,
    locator: EvidenceLocator,
    replacement: str | None,
) -> None:
    """Confident Voice needs playable audio; a rewrite needs its proposal."""
    if family is FeedbackFamily.CONFIDENT_VOICE \
            and locator.audio_interval is None:
        raise FeedbackContractError(
            "confident voice feedback requires playable audio evidence")
    if family is FeedbackFamily.REWRITE_FOR_CLARITY and not replacement:
        raise FeedbackContractError(
            "rewrite feedback requires proposed replacement text")


def _examples(row: dict) -> tuple[str, ...]:
    return tuple(
        str(example).strip()
        for example in (row.get("examples") or [])
        if str(example).strip()
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
            item = self._coach_item(take_id, session, row)
            if item is not None:
                items.append(item)
        return items

    def _coach_item(self, take_id: str, session: dict, row: dict) -> FeedbackItem | None:
        """One coach draft row as a FeedbackItem, or None when it is not
        surfaced, carries no authored feedback, or states an unknown family."""
        if not row.get("surfaced"):
            return None
        message = str(row.get("note") or "").strip()
        replacement = str(row.get("transcript_corrected") or "").strip() or None
        if not message:
            # A surfaced switch without authored feedback is not a
            # FeedbackItem.  Treating it as absent makes an empty
            # professional verdict a valid "no changes needed" result.
            return None
        review_state = _review_state(row)
        try:
            family = _family(row)
        except FeedbackContractError as error:
            # An unknown stated family is logged and skipped: never read
            # as praise, and never allowed to fail the whole read, which
            # feeds the speaker's recording screen (audit B2).
            logger.error("feedback row skipped take=%s snippet=%s: %s",
                         take_id, row.get("snippet_id"), error)
            return None
        locator = self._locator(session, row)
        _require_family_evidence(family, locator, replacement)
        return FeedbackItem(
            id=f"coach:{take_id}:{row.get('snippet_id')}",
            family=family,
            message=message,
            evidence=locator,
            review_state=review_state,
            replacement_text=replacement,
            application_guidance=(
                str(row.get("when_context") or "").strip() or None
            ),
            examples=_examples(row),
        )

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
