"""Deterministic Lounge-bot intent intercepts (audit 2026-06-21).

§0 fence: keep these OUT of master_doc_rag's mega-prompt — the attention
ceiling is full, and the live probe grades the LLM path (answer_question). So
the route runs these cheap regex pre-gates BEFORE the librarian; when one fires
it returns a fixed bubble + the per-turn flags and short-circuits the LLM. Pure
+ unit-tested; no LLM, no I/O. Same pattern as services/audit_intent.

Two intents, in precedence order:
  • crisis      — acute distress / self-harm → empathetic + emergency redirect
                  (NEVER a record CTA). TIGHT phrasing so a normal "I panic
                  before talks" stays a coachable speaking-nerves question.
  • generative  — off-mission "write me a haiku / joke / poem" → on-mission
                  deflect (not a free general-purpose LLM). Whole-speech ghost-
                  writing is NOT caught here — answer_question declines that.

NOTE: there is deliberately NO record-intent intercept. Record/readiness intent
is owned by the LLM (master_doc_rag RULE I): it POINTS to the always-present
"Start official recording" button in words — no mic invite (show_record_ui
stays false), no suggested_action. (A record-CTA intercept was tried and pulled
2026-06-21 — product wants the permanent button, not an in-chat CTA.)
"""
from __future__ import annotations

import re
from typing import Optional


# Acute distress — phrase-anchored (not bare "panic"/"anxious"/"scared", which
# are ordinary speaking-nerves the bot should COACH, not crisis-redirect).
_CRISIS = re.compile(
    r"(panic attack|having a panic|suicid|kill(ing)? myself|want to die|"
    r"wanna die|end(ing)? my life|self[- ]?harm|harm(ing)? myself|"
    r"hurt(ing)? myself|can'?t go on|don'?t want to (live|be here))",
    re.IGNORECASE,
)
_CRISIS_REPLY = (
    "I'm really sorry you're feeling this way — that sounds genuinely hard. "
    "I'm a speaking-practice tool, not a substitute for real support, so if "
    "this is an emergency or you might act on these feelings, please reach out "
    "right now to someone you trust or a local emergency line or mental-health "
    "professional. When you're feeling safer, I'm here whenever you want to "
    "work on your speaking."
)

# Off-mission generative requests (NOT whole-speech writing — the LLM declines
# that itself, with the right nuance).
_GENERATIVE = re.compile(
    r"\b(haiku|limerick|sonnet)\b|"
    r"\b(write|compose|sing|recite|tell)\b[\w\s'\-,]{0,24}?"
    r"\b(poem|story|song|joke|riddle|tale|essay|verse|lyrics?)\b|"
    r"\b(a|another) (poem|song|joke|riddle|tale|story)\b",
    re.IGNORECASE,
)
_GENERATIVE_REPLY = (
    "Ha — I'll leave the haikus to the poets. I'm here to help you speak with "
    "more confidence and presence. Want a hand with nerves, pacing, or how this "
    "app works?"
)


def detect_chat_intent(message: str) -> Optional[dict]:
    """Return a fixed intercept response for a recognised intent, else None.

    Precedence: crisis (safety) → generative. The dict carries {intent, answer,
    show_record_ui, suggested_action}; the route forwards the flags verbatim and
    adds the bubble split. (No record-intent branch — that's the LLM's RULE I.)
    """
    if not isinstance(message, str) or not message.strip():
        return None
    msg = message.strip()
    if _CRISIS.search(msg):
        return {"intent": "crisis", "answer": _CRISIS_REPLY,
                "show_record_ui": False, "suggested_action": None}
    if _GENERATIVE.search(msg):
        return {"intent": "generative", "answer": _GENERATIVE_REPLY,
                "show_record_ui": False, "suggested_action": None}
    return None
