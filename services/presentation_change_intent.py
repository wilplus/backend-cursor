"""Deterministic project-boundary replies for presentation changes.

Changing slide structure is a state transition, not an open-ended coaching
answer.  Keep it out of the general chat prompt so the model cannot improvise
away project isolation or silently move feedback between presentations.
"""
from __future__ import annotations

import re
from typing import Any, Optional


NEW_PROJECT_REPLY = (
    "This looks like a new presentation. Let’s create a new project so its "
    "recordings, feedback and speaking anchors stay separate from your current one."
)
REPLACE_REPLY = (
    "You haven’t completed a take yet, so you can replace this deck without "
    "losing rehearsal progress."
)
LOCKED_REPLY = (
    "Your current roadmap is connected to these slides. Changing the deck here "
    "could mix up your feedback and speaking anchors. Create a new project for "
    "the updated deck, and your current rehearsal will remain available."
)
EDIT_REPLY = (
    "If the presentation is still fundamentally the same, you can update the "
    "wording without starting over."
)

_DECK = r"(?:slides?|deck|presentation|pdf)"
_NEW_PRESENTATION = re.compile(
    rf"\b(?:new|another|different|separate)\s+{_DECK}\b|"
    rf"\b(?:rehearse|practice|prepare)\b.{{0,36}}\b(?:new|another|different)\s+{_DECK}\b|"
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
    rf"\b(?:upload|attach|replace|change|update|swap|add|remove|delete)\b.{{0,36}}\b{_DECK}\b|"
    rf"\b{_DECK}\b.{{0,24}}\b(?:upload|replace|change|update|swap|add|remove|delete)\b",
    re.IGNORECASE,
)


def _completed_takes(context: Any) -> int:
    if not isinstance(context, dict):
        return 0
    raw = context.get("completed_takes", 0)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _has_current_project(context: Any) -> bool:
    return bool(isinstance(context, dict) and context.get("has_current_project"))


def handle_presentation_change(
    message: str, context: Any = None
) -> Optional[dict]:
    """Return the locked reply/actions for a slide-project request, else None.

    Precedence matters: an explicitly new/different presentation always starts
    fresh; a clearly wording-only change stays in the slide editor; structural
    deck mutation then branches on whether Take 1 has completed.
    """
    if not isinstance(message, str) or not message.strip():
        return None
    text = message.strip()
    has_project = _has_current_project(context)

    if _NEW_PRESENTATION.search(text):
        return {
            "intent": "new_presentation",
            "answer": NEW_PROJECT_REPLY,
            "suggested_actions": ["create_new_project"],
        }

    if _WORDING_ONLY.search(text) and has_project:
        return {
            "intent": "edit_presentation_wording",
            "answer": EDIT_REPLY,
            "suggested_actions": ["edit_current_slide"],
        }

    if not _DECK_MUTATION.search(text):
        return None

    if not has_project:
        return {
            "intent": "new_presentation",
            "answer": NEW_PROJECT_REPLY,
            "suggested_actions": ["create_new_project"],
        }

    if _completed_takes(context) == 0:
        return {
            "intent": "replace_pre_take_deck",
            "answer": REPLACE_REPLY,
            "suggested_actions": ["replace_pdf", "create_new_project"],
        }

    return {
        "intent": "protect_recorded_presentation",
        "answer": LOCKED_REPLY,
        "suggested_actions": [
            "create_project_from_updated_deck",
            "keep_current_project",
        ],
    }


def presentation_deck_fingerprint(context: Any) -> tuple:
    """Exact deck identity used by the recording mutation gate.

    The immutable project UUID remains the project identity.  This fingerprint
    only answers whether a later take is still using the slide structure that
    project was created with.
    """
    if not isinstance(context, dict):
        return (None, ())
    ref = context.get("presentation_ref")
    ref = ref.strip() if isinstance(ref, str) and ref.strip() else None
    slides = context.get("slides")
    rows = []
    if isinstance(slides, list):
        for slide in slides:
            if not isinstance(slide, dict):
                rows.append(("", ""))
                continue
            rows.append((
                str(slide.get("title") or "").strip(),
                str(slide.get("body") or "").strip(),
            ))
    return (ref, tuple(rows))


def deck_matches_recorded_project(prior_sessions: Any, incoming: Any) -> bool:
    """True when a continued take keeps the first take's exact deck.

    No prior take means the PDF is still replaceable.  Once a session exists,
    neither its served PDF nor slide structure may be changed in place.
    """
    if not isinstance(prior_sessions, list) or not prior_sessions:
        return True
    ordered = sorted(
        (row for row in prior_sessions if isinstance(row, dict)),
        key=lambda row: int(row.get("take_index") or 0),
    )
    for row in ordered:
        prior = row.get("intake_context")
        if isinstance(prior, dict):
            return presentation_deck_fingerprint(prior) == \
                presentation_deck_fingerprint(incoming)
    return True
