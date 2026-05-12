"""Skill registry — single source of truth for available coaching intents.

Phase 7 of the snippet-CTA learning loop. Modules in this package
each define one Skill instance; this file collects them into a dict
keyed by ``id`` and exposes the small API the rest of the codebase
uses:

  get_skill(id)        — Skill object or None
  require_skill(id)    — Skill object, raises KeyError on unknown id
  list_skill_ids()     — set of registered ids (replaces the old
                          _CONTEXTUAL_INTENTS literal)
  resolve_for_snippet(snippet) — derive the skill id from a
                          charisma_snippets row's coach_label
                          (replaces _coach_intent_for_snippet)

Adding a skill is a 2-step change: drop a module that builds a
Skill object, add it to the ``_SKILLS`` tuple below. No route
edits, no migration. The skill_id lands on coaching_attempts the
next time that intent is used.
"""
from __future__ import annotations

from typing import Optional

from services.skills.base import Skill
from services.skills.charisma import CHARISMA_SKILL
from services.skills.stress import STRESS_SKILL


# Tuple, not list — registration is meant to be immutable at import
# time. A skill is registered exactly once when this module loads.
_SKILLS: tuple[Skill, ...] = (CHARISMA_SKILL, STRESS_SKILL)

_REGISTRY: dict[str, Skill] = {s.id: s for s in _SKILLS}


def get_skill(skill_id: str) -> Optional[Skill]:
    """Return the registered Skill for ``skill_id``, or None when unknown.

    Use this when the caller already plans to handle missing-skill
    fallback locally (e.g. the few-shot retrieval degrading to []).
    """
    if not skill_id:
        return None
    return _REGISTRY.get(skill_id.strip().lower())


def require_skill(skill_id: str) -> Skill:
    """Same as get_skill but raises KeyError when the id is unknown.

    Use this from code paths where an unknown skill genuinely is a
    bug (the route already validated the input, the snippet was
    resolved). The raise is meant to surface in logs immediately
    rather than mysteriously selecting a default skill.
    """
    skill = get_skill(skill_id)
    if skill is None:
        raise KeyError(f"Unknown skill id: {skill_id!r}")
    return skill


def list_skill_ids() -> set[str]:
    """All registered skill ids. Replaces the old _CONTEXTUAL_INTENTS literal."""
    return set(_REGISTRY.keys())


def resolve_for_snippet(snippet: dict) -> str:
    """Pick the skill id that fits a charisma_snippets row.

    Mirrors the old _coach_intent_for_snippet behaviour: a row
    labelled "charisma" picks the charisma skill; anything else
    (including unlabelled rows) falls through to stress. Keep the
    fallback ordering aligned with whichever skill is the "default
    everything is" — for v1 that's stress.
    """
    label = (snippet.get("coach_label") or "").strip().lower()
    if label == CHARISMA_SKILL.id:
        return CHARISMA_SKILL.id
    return STRESS_SKILL.id


__all__ = [
    "Skill",
    "get_skill",
    "require_skill",
    "list_skill_ids",
    "resolve_for_snippet",
]
