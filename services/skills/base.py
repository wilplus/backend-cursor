"""Skill dataclass — Phase 7 of the snippet-CTA learning loop.

A "skill" in this codebase is one coaching intent the contextual
/chat flow can run. v1 has two: charisma (anchor + strip) and stress
(reframe + re-perform). The dataclass + registry pattern lets us add
new skills (e.g. "pacing", "presence") without touching the routing
layer — drop a module in services/skills/, register it, and
v2_routes.py picks it up automatically.

Each module owns its own static config. There is no DB row for a
skill — they live in code so the prompt text, fallback bubbles, and
behavioural metadata version-control together. If we ever need
admin-editable skills, the read path becomes "registry first, DB
override if present" without a registry redesign.

Why dataclass (not a class hierarchy)
-------------------------------------
Skills are data, not behaviour. The only "method" a skill needs is
"give me your awareness prompt"; everything else is static text.
Subclassing would invite the temptation to put logic in skill
modules, which is exactly the wrong direction — the routing layer
should stay the only place that calls the LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Skill:
    """One coaching intent, with everything the route layer needs.

    Fields:
      id:
        Stable identifier persisted on coaching_attempts.skill_id
        and used in URLs (intent=charisma/stress query param).
        Lowercase, snake_case if multi-word. Never rename — it's
        a DB value.

      display_name:
        Human-facing label admins read in logs / admin views.

      awareness_system_prompt:
        The big system prompt the contextual coaching turn ships to
        the LLM. The contract (||| split + [ADVANCE] tail, structured
        JSON via AWARENESS_TURN_SCHEMA) is the SAME across all
        skills — only the coaching content differs per skill.

      fallback_validation_bubble / fallback_challenge_bubble:
        What the user sees when the LLM call fails entirely. Keep
        them short and tonally consistent with the skill so a
        degraded response doesn't feel jarringly off-brand.

      contextual_first_question:
        Default first question for /chat/first-question when the LLM
        also fails to generate. One question, second-person.
    """

    id: str
    display_name: str
    awareness_system_prompt: str
    fallback_validation_bubble: str
    fallback_challenge_bubble: str
    contextual_first_question: str = field(default="")
