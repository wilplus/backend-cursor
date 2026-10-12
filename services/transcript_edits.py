"""The speaker's corrected transcript text for ONE target on their own
readout (PUT /v2/user/sessions/<session_id>/transcript-edit, founder
2026-07-07): a snippet's transcript, or a deckless full-transcript chunk.

Moved out of ``routes.v2.user_sessions`` unchanged (founder 2026-10-12). The
route keeps the ownership check (the authenticated owner or the matching
signed Guest ID). Display layer ONLY: the coach keeps reviewing the ORIGINAL
transcript; readout reads carry the edit beside, never instead of, it.
"""
from __future__ import annotations

from typing import Any, Optional

from services.refusal import Refusal
from utils.ids import is_uuid

MAX_LEN = 2000


def _invalid(error: str) -> Refusal:
    return Refusal("INVALID_INPUT", error, 400)


def _text(body: dict) -> str:
    # Type-check BEFORE .strip() — a truthy non-string must be a clean 400.
    raw = body.get("text")
    if raw is not None and not isinstance(raw, str):
        raise _invalid("text must be a string")
    text = (raw or "").strip()
    if not text:
        raise _invalid("text is required")
    if len(text) > MAX_LEN:
        raise _invalid(f"text exceeds {MAX_LEN} characters")
    return text


def _target(body: dict) -> tuple[Optional[str], Any]:
    """(snippet_id, None) or (None, chunk_index): exactly one of them."""
    raw = body.get("snippet_id")
    if raw is not None and not isinstance(raw, str):
        raise _invalid("snippet_id must be a string")
    snippet_id = (raw or "").strip() or None
    chunk_index = body.get("chunk_index")
    has_chunk = isinstance(chunk_index, int) and not isinstance(
        chunk_index, bool) and chunk_index >= 0
    if (snippet_id is not None) == has_chunk:
        raise _invalid("exactly one of snippet_id or chunk_index is required")
    if snippet_id is not None and not is_uuid(snippet_id):
        raise _invalid("snippet_id must be a UUID")
    return (snippet_id, None) if snippet_id is not None else (None, chunk_index)


def _check_target_exists(database, session_id, snippet_id, chunk_index) -> None:
    """An edit may only land on a target this session actually has —
    otherwise orphan rows accrue invisibly, and an INT4-overflow chunk_index
    would 500 at insert instead of 400 here."""
    if snippet_id is not None:
        row = database.get_snippet_by_id(snippet_id)
        if not row or str(row.get("session_id") or "") != str(session_id):
            raise Refusal("SNIPPET_NOT_FOUND",
                          "That moment is not part of this session", 404)
        return
    # SAME helper the readout fold uses — the two counts can't drift.
    from services.slide_word_split import deckless_chunks_from_stx
    stx = database.takes.get_session_slide_transcripts(session_id) or []
    if chunk_index >= len(deckless_chunks_from_stx(stx)):
        raise _invalid("chunk_index is out of range for this session")


def save_transcript_edit(database, session_id: str, body: dict) -> dict:
    """Save the edit; the response body. Raises ``Refusal``."""
    text = _text(body)
    snippet_id, chunk_index = _target(body)
    _check_target_exists(database, session_id, snippet_id, chunk_index)
    if not database.upsert_user_transcript_edit(
            str(session_id), snippet_id=snippet_id, chunk_index=chunk_index,
            text=text):
        raise Refusal("V2_ERROR", "Could not save the edit", 500)
    out: dict[str, Any] = {"saved": True, "session_id": session_id}
    if snippet_id is not None:
        out["snippet_id"] = snippet_id
    else:
        out["chunk_index"] = chunk_index
    return out
