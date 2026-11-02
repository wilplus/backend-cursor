"""What the speaker noted themselves, for the walk's pick and its Clearer
version (founder 2026-11-02, N326 items 2 to 4, building N290 item 3;
prototype https://claude.ai/artifact/KvAiek4DrxgbpDudcBFJNQ; rules: frontend
docs/flows/feedback-walk-and-chat.md H1 and docs/flows/principles.md).

``gather`` reads, for one person, only what they noted themselves, each only
where its own ring row and consent already reach them:

  * their principles, with the Life Panel's yes (``LIFE_PANEL_ENABLED`` and
    its consent, services/life_chat.py);
  * their kept strengths (ring ``strengths``, status ``kept``);
  * their life goals (ring ``life_goals``);
  * Your why (ring ``your_why``);
  * their # notes from the last 60 days, read as the walk's quotes read
    them (``voice_notebook.recent_notes``, N268), with the notebook's yes
    (ring ``voice_notebook``).

Behind the walk's own ring row, ``walk_inner_context`` (N326 item 4: the
founder first, at ring 6; no row is off for everyone). Never Will's private
note (speaker memory, N326 item 2); variables and constants are kept
nowhere, so they are not read.

It returns a short, bounded block for one model call (the verbal read,
``services.verbal_read``) and the raw texts it was made from, which the
rewrite's leak guard reads (``services.rewrite_gate.leaks``). Any failure
is a closed door: an empty context, and the walk as it was. Private: never
stored, never shown to a coach or on any screen (Never 2).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_MAX_NOTES = 12
_MAX_PRINCIPLES = 8
_MAX_STRENGTHS = 8
_MAX_GOALS = 4
_MAX_LINE = 240
#: The whole block, so one Take's read stays one bounded call.
MAX_BLOCK = 3000


@dataclass(frozen=True)
class InnerContext:
    """``block``: the prompt text; ``phrases``: the texts it was made from."""
    block: str = ""
    phrases: tuple[str, ...] = field(default_factory=tuple)

    def __bool__(self) -> bool:
        return bool(self.block)


EMPTY = InnerContext()


def reaches(database: Any, user_id: Any) -> bool:
    """The walk's ring row reaches this person. Fails closed."""
    from services import rings
    if not user_id:
        return False
    try:
        return rings.feature_is_on_for_user(rings.WALK_INNER_CONTEXT, user_id,
                                            database=database)
    except Exception as error:  # noqa: BLE001 -- a closed door
        logger.warning("inner context: ring not read user=%s: %s", user_id, error)
        return False


def _clip(value: Any, limit: int = _MAX_LINE) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def _principles(user_id: str) -> list[str]:
    from services import life_chat, life_store
    if not (life_chat.is_enabled() and life_chat.has_consented(user_id)):
        return []
    out = []
    for row in life_store.principles(user_id, limit=40):
        text = _clip(row.get("title") or row.get("body"))
        if text:
            out.append(text)
    return out[:_MAX_PRINCIPLES]


def _strengths(database: Any, user_id: str) -> list[str]:
    from services import life_store, strengths
    if not strengths.enabled(database, user_id):
        return []
    return [title for title in (_clip(s.get("title"), 80) for s in life_store.list_strengths(user_id)
                                if s.get("status") == "kept") if title][:_MAX_STRENGTHS]


def _goals(database: Any, user_id: str) -> list[str]:
    from services import life_goals, life_store
    if not life_goals.enabled(database, user_id):
        return []
    out = []
    for goal in life_store.list_goals(user_id)[:_MAX_GOALS]:
        ladder = goal.get("ladder")
        steps = [ladder.get(key) for key in ("goal", "want", "give")] \
            if isinstance(ladder, dict) else []
        text = _clip(". ".join(step.strip() for step in steps
                               if isinstance(step, str) and step.strip()))
        if text:
            out.append(text)
    return out


def _why(database: Any, user_id: str) -> list[str]:
    from services import life_store, your_why
    if not your_why.enabled(database, user_id):
        return []
    row = life_store.get_why(user_id) or {}
    return [text for text in (_clip(row.get(line)) for line in your_why.LINES) if text]


def _notes(database: Any, user_id: str, now: datetime) -> list[str]:
    from services import voice_notebook
    if not (voice_notebook.enabled(database, user_id)
            and voice_notebook.consented(database, user_id)):
        return []
    notes = voice_notebook.recent_notes(database, user_id, clip=_MAX_LINE, now=now)
    return [f"({note['on']}) {note['text']}" for note in notes[-_MAX_NOTES:]]


def _part(label: str, lines: list[str]) -> str:
    return (label + "\n" + "\n".join(f"- {line}" for line in lines)) if lines else ""


def gather(database: Any, user_id: Any, *, now: Optional[datetime] = None) -> InnerContext:
    """The person's own notes for the walk (see the module); ``EMPTY`` when
    the ring does not reach them, they noted nothing the walk may read, or
    anything fails."""
    if not reaches(database, user_id):
        return EMPTY
    user = str(user_id)
    now = now or datetime.now(timezone.utc)
    parts: list[tuple[str, list[str]]] = []
    for label, read in (
        ("Their principles:", lambda: _principles(user)),
        ("Their kept strengths:", lambda: _strengths(database, user)),
        ("Their life goals:", lambda: _goals(database, user)),
        ("Their why:", lambda: _why(database, user)),
        ("Their own notes, newest last:", lambda: _notes(database, user, now)),
    ):
        try:
            parts.append((label, read()))
        except Exception as error:  # noqa: BLE001 -- that source stays out
            logger.warning("inner context: %s not read user=%s: %s", label, user, error)
    block = "\n\n".join(text for text in (_part(label, lines) for label, lines in parts) if text)
    if not block:
        return EMPTY
    return InnerContext(block=block[:MAX_BLOCK],
                        phrases=tuple(line for _label, lines in parts for line in lines))
