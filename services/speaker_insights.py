"""Insights when the speaker asks (founder, N691 item 4).

Insights are never shown on their own: no card, no screen. When the
speaker asks for them in either chat (the main Speaking Coach chat or a
project chat), they are worked out at that moment from the wider record:

  * Will's private note on the speaker (``services.speaker_memory``), which
    already holds every answer and every Take's outcome;
  * what Will said after each of their recent Takes (the praise, the moment
    to improve, the best moment), only for Takes whose processing
    authorization is in force (``speaker_lookup._takes_in_force``);
  * the messages the speaker sent, for how they talk about their speaking.

One generation answers in words, in the speaker's language, in an ordinary
reply. No score, number or verdict reaches the speaker (Never 1).

Public API:
  asks_for_insights(question) -> bool
  answer(database, user_id, question) -> Optional[str]
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: An explicit ask for the wider picture, in English or Polish. A question
#: about one Take ("how did that Take go?") stays with the coach.
_ASKS = re.compile(
    r"\binsights?\b"
    r"|\bhow am i doing\b|\bhow have i been doing\b"
    r"|\b(my|overall) progress\b|\bam i (getting better|improving)\b"
    r"|\bwhat (have you|do you) (noticed|notice|see) (about|in) me\b"
    r"|\b(my|any) patterns?\b|\bpatterns? (in|across) my\b"
    r"|\bspostrzeżeni|\bwnioski\b|\bjak mi idzie\b|\bmoje postęp|\bmój postęp\b"
    r"|\bczy robię postęp|\bco (o mnie )?zauważy",
    re.IGNORECASE,
)

#: What Will said after a Take: the steps that describe the speaker.
_TAKE_STEPS = {"praise", "best", "fix", "coachnote"}
_MAX_TAKE_LINES = 24
_MAX_OWN_LINES = 30
_MAX_LINE = 280
_PAGE = 300

_SYSTEM = """You are Will, a speaking coach. The speaker asked what you have noticed about them across their talks.

Answer from the record below only. Give two to four short observations that hold across several Takes or messages (what keeps working, what keeps coming back, how they talk about their own speaking), then one concrete thing to try in the next Take. Quote their own words or Will's earlier words briefly where it helps.

Rules:
- Words only. Never give a score, a rating, a number, a percentage, a count or a verdict.
- Speak to the speaker as "you". Warm, plain, short sentences. No headings, no lists of more than four points.
- Only claim what the record shows. If the record is thin, say so in one line and suggest recording another Take.
- Do not mention notes, records, data or analysis; speak as a coach who remembers."""


def asks_for_insights(question: Any) -> bool:
    """Whether the message asks for the wider picture. Pure."""
    return bool(_ASKS.search(str(question or "")))


def _clip(value: Any, limit: int = _MAX_LINE) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _messages(database: Any, user_id: str) -> list[dict]:
    reader = getattr(database, "get_lounge_messages_page", None)
    if not callable(reader):
        return []
    rows = reader(user_id, limit=_PAGE) or []
    rows = [row for row in rows if isinstance(row, dict)]
    return list(reversed(rows))  # oldest first


def _take_rows(database: Any, user_id: str) -> list[dict]:
    repo = getattr(database, "takes", None) or database
    reader = getattr(repo, "list_user_arc_sessions", None)
    rows = reader(user_id) if callable(reader) else []
    return [row for row in (rows or []) if isinstance(row, dict) and row.get("id")]


def _takes_in_force(database: Any, user_id: str) -> set[str]:
    """Ids of the speaker's Takes whose processing authorization holds now.
    Fails closed: a check that cannot be made lets no Take in."""
    try:
        from services.speaker_lookup import _takes_in_force as in_force
        return {str(take) for take in in_force(database, _take_rows(database, user_id))}
    except Exception as error:  # noqa: BLE001 - fail closed
        logger.warning("speaker_insights authorization unread err=%s", type(error).__name__)
        return set()


def _record(database: Any, user_id: str) -> str:
    from services import speaker_memory

    note = speaker_memory.prompt_block(speaker_memory.note_for(database, user_id))
    rows = _messages(database, user_id)
    allowed = _takes_in_force(database, user_id) if rows else set()
    take_lines: list[str] = []
    own_lines: list[str] = []
    for row in rows:
        raw_meta = row.get("metadata")
        meta: dict = raw_meta if isinstance(raw_meta, dict) else {}
        body = _clip(row.get("body"))
        if not body:
            continue
        if row.get("role") == "bot" and row.get("kind") == "walk_step" and meta.get("step") in _TAKE_STEPS:
            take = str(meta.get("take_session_id") or "")
            if take and take in allowed:
                take_lines.append(f"- After a Take: {body}")
        elif row.get("role") == "user" and row.get("kind") in (None, "text", "chat"):
            own_lines.append(f"- They wrote: {body}")
    parts = [note.strip()] if note.strip() else []
    if take_lines:
        parts.append("What Will said after their recent Takes:\n" + "\n".join(take_lines[-_MAX_TAKE_LINES:]))
    if own_lines:
        parts.append("What they wrote in the chat:\n" + "\n".join(own_lines[-_MAX_OWN_LINES:]))
    return "\n\n".join(parts)


def answer(database: Any, user_id: Any, question: str) -> Optional[str]:
    """The insights reply, or None when nothing can be said (the caller
    falls through to its usual reply)."""
    if not user_id or not asks_for_insights(question):
        return None
    from services.content_language import complete_in_language, resolve_content_language
    from services.llm_config import SPEC_SPEAKING_COACH_TAKE

    record = _record(database, str(user_id))
    if not record:
        return None
    system = f"{_SYSTEM}\n\nThe record:\n{record}"

    def generate(**kwargs: Any) -> Any:
        from services.llm import chat_complete
        return chat_complete(**kwargs)

    try:
        response = complete_in_language(
            generate,
            target_language=resolve_content_language(typed_message=question),
            spec=SPEC_SPEAKING_COACH_TAKE,
            system=system,
            user=(question or "").strip(),
            surface="speaker_insights",
            user_id=str(user_id),
        )
    except Exception as error:  # noqa: BLE001 - preserve authorization hard failures
        from services.processing_authorization import rethrow_processing_authorization
        rethrow_processing_authorization(error)
        logger.warning("speaker_insights generation failed err=%s", type(error).__name__)
        return None
    text = (getattr(response, "text", "") or "").strip()
    if not text or re.search(r"\d+\s*(%|/\s*10\b|out of)", text):
        # A number about the speaker never reaches them (Never 1).
        return None
    return text
