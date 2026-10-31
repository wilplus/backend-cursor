"""The context a Take carries (founder 2026-10-31, N293; N290, N291, N292).

Three slots, each with a value, where it came from, and a state:

  who      who the talk is for
  what     what it answers, what it is about
  success  what the listener should do or feel when it ends

  sure     the speaker said it: their answer to Will's question, kept in the
           talk's setup (``audience``; the setup's "Desired call to action:",
           ``services.will_question``), or the plan's answers
  guess    read from the Take: Will's "heard" read of the title and the
           transcript, copied word for word or nothing, kept in the setup
           under ``heard`` (``services.will_question.start_heard``)
  missing  nothing yet

A guess never replaces a sure answer. The coach's chat and the other chats
(N292) are more sources when they exist; nothing else changes.

The picker reads it (``relevance``): a sentence that carries the key line or
the call to action is relevant, in full when its slot is sure, at half weight
when it is a guess. No model call here; the words are matched as the plan's
key line already is (``plan_walk.key_line_at``).

Internal only (Never 1): no state, weight or match reaches a screen, and a
coach never sees why a moment was picked (Never 2).
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

SURE = "sure"
GUESS = "guess"
MISSING = "missing"
#: How much a slot's state counts in the picker (N293 item 3).
WEIGHT = {SURE: 1.0, GUESS: 0.5, MISSING: 0.0}
#: The share of a phrase's words a sentence must say to carry it, as the
#: plan's key line is matched (``plan_walk.KEY_LINE_MATCH``).
MATCH = 0.6
_WORD = re.compile(r"[a-z0-9']+")


def _slot(value: Any, state: str, source: str) -> dict:
    return {"value": str(value).strip(), "state": state, "source": source}


def _missing() -> dict:
    return {"value": "", "state": MISSING, "source": ""}


def _text(value: Any) -> str:
    return str(value).strip() if isinstance(value, str) else ""


def assemble(setup: Any, facts: Any) -> dict:
    """The Take's context from its setup (``intake_context``) and the plan's
    answers (``facts``), best source first. Pure.

    Returns ``{"who", "what", "success", "key_line"}``: three slots and the
    key line (a phrase, sure when the plan has it)."""
    from services.will_question import call_to_action
    setup = setup if isinstance(setup, dict) else {}
    facts = facts if isinstance(facts, dict) else {}
    heard = setup.get("heard") if isinstance(setup.get("heard"), dict) else {}

    def first(*options: tuple[Any, str, str]) -> dict:
        for value, state, source in options:
            if _text(value):
                return _slot(value, state, source)
        return _missing()

    return {
        "who": first((setup.get("audience"), SURE, "setup"), (facts.get("audience"), SURE, "plan"),
                     (facts.get("who"), SURE, "plan"), (heard.get("audience"), GUESS, "take")),
        "what": first((setup.get("topic"), SURE, "setup"), (facts.get("topic"), SURE, "plan")),
        "success": first((call_to_action(setup.get("strategic_context")), SURE, "setup"),
                         (facts.get("success"), SURE, "plan"), (heard.get("ask"), GUESS, "take")),
        "key_line": first((facts.get("key_line"), SURE, "plan")),
    }


def for_take(database: Any, user_id: Any, take: Any) -> dict:
    """The Take's context, read from its setup and the speaker's open plan.
    Never raises: anything unreadable is missing, and the walk is as it was."""
    take = take if isinstance(take, dict) else {}
    setup = take.get("intake_context") if isinstance(take.get("intake_context"), dict) else {}
    facts: dict = {}
    try:
        plan = database.get_open_plan(str(user_id)) if user_id else None
        facts = (plan or {}).get("facts") or {}
    except Exception as error:  # noqa: BLE001 -- the context without the plan's answers
        logger.warning("take context: plan not read user=%s: %s", user_id, error)
    return assemble(setup, facts)


def _words(text: Any) -> set[str]:
    return {w for w in _WORD.findall(str(text or "").lower()) if len(w) > 2}


def carries(sentence: Any, phrase: Any) -> bool:
    """The sentence says at least ``MATCH`` of the phrase's words. Pure."""
    want = _words(phrase)
    return bool(want) and len(want & _words(sentence)) / len(want) >= MATCH


def relevance(sentence: Any, context: Any) -> float:
    """How much the sentence serves the talk, 0 to 1: the weight of the
    surest slot whose phrase it carries (the key line, the call to action).
    0 with no context. Pure."""
    if not isinstance(context, dict):
        return 0.0
    found = [WEIGHT.get(str(slot.get("state")), 0.0)
             for slot in (context.get("key_line"), context.get("success"))
             if isinstance(slot, dict) and slot.get("value") and carries(sentence, slot["value"])]
    return max(found, default=0.0)
