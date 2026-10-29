"""Deterministic replies for presentation changes in the chat.

Changing slide structure is a state transition, not an open-ended coaching
answer.  Keep it out of the general chat prompt so the model cannot improvise
it. Since N257 (founder 2026-10-29) a new or updated deck stays in the
current project (``services/slide_deck_update.py``); a different talk is a
new project (N254).
"""
from __future__ import annotations

import re
from typing import Any, Optional


NEW_PROJECT_REPLY = (
    "This looks like a new presentation. Let’s create a new project so its "
    "recordings, feedback and speaking anchors stay separate from your current one."
)
#: N257 (founder 2026-10-29, signed on the prototype): a new or updated deck
#: stays in the project and is used from the next Take.
UPDATE_SLIDES_REPLY = (
    "You can update the slides in this project. Your next Take uses them."
)
EDIT_REPLY = (
    "If the presentation is still fundamentally the same, you can update the "
    "wording without starting over."
)

_DECK = r"(?:slides?|deck|presentation|pdf)"
_SLIDES = r"(?:slides?|(?:pitch\s+)?deck|pdf)"
_NEW_PRESENTATION = re.compile(
    r"\b(?:new|another|different|separate)\s+(?:presentation|talk)\b|"
    r"\b(?:rehearse|practice|prepare)\b.{0,36}\b(?:new|another|different)\s+"
    r"(?:presentation|talk)\b|"
    r"\b(?:different|new)\s+(?:audience|goal|call to action|core message)\b|"
    r"\bsubstantially different\b",
    re.IGNORECASE,
)
_WORDING_ONLY = re.compile(
    r"\b(?:small|minor|tiny|wording|copy|text)\b.{0,28}\b(?:change|edit|update|fix|rewrite)\b|"
    r"\b(?:change|edit|update|fix|rewrite)\b.{0,28}\b(?:wording|copy|text|sentence)\b",
    re.IGNORECASE,
)
_DECK_MUTATION = re.compile(
    rf"\b(?:new|newer|updated|another|different|revised|latest)\s+"
    rf"(?:version\s+of\s+(?:my|the)\s+)?{_SLIDES}\b|"
    rf"\b(?:upload|attach|replace|change|update|swap|add|remove|delete)"
    rf"(?:s|d|ed)?\b.{{0,36}}\b{_DECK}\b|"
    rf"\b{_DECK}\b.{{0,24}}\b(?:upload|replace|change|update|swap|add|remove|delete)\b",
    re.IGNORECASE,
)


def _has_current_project(context: Any) -> bool:
    return bool(isinstance(context, dict) and context.get("has_current_project"))


def _new_project() -> dict:
    return {
        "intent": "new_presentation",
        "answer": NEW_PROJECT_REPLY,
        "suggested_actions": ["create_new_project"],
    }


def handle_presentation_change(
    message: str, context: Any = None
) -> Optional[dict]:
    """Return the fixed reply/actions for a slide-project request, else None.

    Precedence matters: an explicitly new presentation (a different talk)
    starts a new project; a clearly wording-only change stays in the slide
    editor; a new or updated deck stays in the current project and is used
    from its next Take (N257), however many Takes are done. Without a
    current project, any deck change starts one.
    """
    if not isinstance(message, str) or not message.strip():
        return None
    text = message.strip()
    has_project = _has_current_project(context)

    if _NEW_PRESENTATION.search(text):
        return _new_project()

    if _WORDING_ONLY.search(text) and has_project:
        return {
            "intent": "edit_presentation_wording",
            "answer": EDIT_REPLY,
            "suggested_actions": ["edit_current_slide"],
        }

    if not _DECK_MUTATION.search(text):
        return None

    if not has_project:
        return _new_project()

    return {
        "intent": "update_slides",
        "answer": UPDATE_SLIDES_REPLY,
        "suggested_actions": ["update_slides"],
    }
