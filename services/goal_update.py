"""Goal-update intercept (willab Prompt A §6 C4).

A signed-in user typing "change my goal to X" (in ANY language) updates
``user_settings.profile_goal`` and gets a short in-language confirmation —
WITHOUT routing through the Lounge librarian (§0: never add rules to
master_doc_rag, which is at its attention ceiling). The /chat/query route
calls ``handle_goal_update`` BEFORE dispatching to the librarian and
short-circuits the turn when it fires.

Two-stage, cost-aware:
  1. a cheap multilingual KEYWORD pre-gate (no LLM) so normal chat turns
     pay nothing — only a plausible goal-change message reaches the LLM;
  2. ONE constrained LLM call that confirms the intent, extracts the new
     goal, and renders the confirmation in the user's language.

FENCES (§7): AC-9 — the goal is ECHOED, never graded; tone is "Will"
(observational, no cheerleader); the confirmation is rendered in the
user's language, never a hardcoded string.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

_SURFACE = "goal_update"

# Cheap pre-gate: a goal token AND a change/set token must BOTH appear
# before we spend an LLM call. Multilingual-ish (EN/PL/ES/DE/FR/IT/PT) —
# a miss only means the librarian answers instead (graceful), never a
# wrong write. Intentionally broad on the keyword side, the LLM is the
# precise gate.
_GOAL_HINT = re.compile(
    r"\b(goal|goals|objective|aim|target|cel|cele|meta|metas|ziel|"
    r"but|objectif|obiettivo|objetivo|obiettivi)\b",
    re.IGNORECASE,
)
_CHANGE_HINT = re.compile(
    r"\b(change|update|set|make|switch|new|reset|zmie[nń]|ustaw|nowy|nowa|"
    r"cambia|cambiar|nuevo|nueva|[aä]ndere|neue|neu|nouvel|nouveau|cambiare|"
    r"nuovo|mudar|novo)\b",
    re.IGNORECASE,
)


def _looks_like_goal_change(message: str) -> bool:
    """Cheap pre-gate — both a goal token and a change token present."""
    if not message:
        return False
    return bool(_GOAL_HINT.search(message) and _CHANGE_HINT.search(message))


def _classify_goal_update(message: str, *, current_goal: Optional[str]) -> Optional[dict]:
    """ONE constrained LLM call. Returns
    ``{"is_goal_update": bool, "new_goal": str, "confirmation": str}`` or
    ``None`` on any failure (caller falls through to the librarian)."""
    try:
        import json as _json

        from services.llm import chat_complete
        from services.llm_config import SPEC_GOAL_UPDATE
        from services.will_voice import with_voice_rules
    except Exception as e:  # pragma: no cover - import guard
        logger.warning("goal_update: llm import failed: %s", e)
        return None

    system = with_voice_rules(
        "\n".join(f"- {r}" for r in [
            "Decide if the user is EXPLICITLY asking to change, set, update, "
            "or reset their coaching GOAL.",
            "Only is_goal_update=true for a clear instruction to change the "
            "goal (e.g. 'change my goal to X', 'set my goal: X', 'make my new "
            "goal X'). A casual mention, a question about goals, or describing "
            "progress is NOT a goal update → is_goal_update=false.",
            "If true, extract new_goal as a concise statement of the goal in "
            "the user's own words (no leading 'my goal is'); else new_goal is "
            "an empty string.",
            "If true, write 'confirmation': a short, warm acknowledgement IN "
            "THE USER'S LANGUAGE that echoes the new goal back and points at "
            "the next action. Tone is 'Will': observational, not a cheerleader "
            "— never 'great', 'amazing', no praise, and NEVER grade or judge "
            "the goal. Just confirm it's saved and what's next.",
            "If false, 'confirmation' is an empty string.",
            'Output strict JSON: {"is_goal_update": bool, "new_goal": str, '
            '"confirmation": str}.',
        ])
    )
    user_prompt = (
        f"Current goal on file: {current_goal or '(none set)'}\n\n"
        f"User message:\n{message.strip()}"
    )
    schema = {
        "name": "goal_update",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["is_goal_update", "new_goal", "confirmation"],
            "properties": {
                "is_goal_update": {"type": "boolean"},
                "new_goal": {"type": "string", "maxLength": 400},
                "confirmation": {"type": "string", "maxLength": 600},
            },
        },
        "strict": True,
    }
    try:
        result = chat_complete(
            spec=SPEC_GOAL_UPDATE,
            system=system,
            user=user_prompt,
            surface=_SURFACE,
            response_format_override={
                "type": "json_schema", "json_schema": schema,
            },
        )
    except Exception as e:
        logger.warning("goal_update: classify call failed: %s", e)
        return None
    if not result:
        return None
    parsed = result.parsed
    if not isinstance(parsed, dict):
        try:
            parsed = _json.loads((result.text or "").strip())
        except Exception:
            return None
        if not isinstance(parsed, dict):
            return None
    return parsed


def _get_db(database):
    if database is not None:
        return database
    from services.db import db as _db
    return _db


def handle_goal_update(
    user_id: Optional[str],
    message: str,
    *,
    database=None,
) -> Optional[dict]:
    """If ``message`` is an explicit goal-update, persist it and return
    ``{"answer": <in-language confirmation>, "new_goal": <str>}``. Otherwise
    return ``None`` (the route then falls through to the librarian).

    Never raises out — any failure returns None so the chat turn degrades to
    a normal librarian answer."""
    if not user_id or not isinstance(message, str) or not message.strip():
        return None
    if not _looks_like_goal_change(message):
        return None  # cheap pre-gate — no LLM spent on normal chat

    db = _get_db(database)
    try:
        profile = db.get_user_profile(user_id) or {}
    except Exception:
        profile = {}
    current_goal = profile.get("goal")

    verdict = _classify_goal_update(message, current_goal=current_goal)
    if not verdict or not verdict.get("is_goal_update"):
        return None
    new_goal = str(verdict.get("new_goal") or "").strip()
    if not new_goal:
        return None

    # Goal-only update — records old→new (previous_goal + changed_at) so the
    # coach sees what changed; preserves the existing domain.
    try:
        ok = db.update_user_goal(user_id, new_goal, current_goal)
    except Exception as e:
        logger.warning("goal_update: update_user_goal failed user=%s: %s",
                       user_id, e)
        return None
    if not ok:
        return None

    answer = str(verdict.get("confirmation") or "").strip()
    if not answer:
        # We persisted but the render came back empty — don't fabricate a
        # hardcoded string (language fence). Fall through to the librarian;
        # the goal is saved either way.
        logger.info("goal_update: saved but no confirmation render user=%s",
                    user_id)
        return None
    logger.info("goal_update: goal updated user=%s", user_id)
    return {"answer": answer, "new_goal": new_goal, "previous_goal": current_goal}
