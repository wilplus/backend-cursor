"""Prompt for Best-Presentation composition (Prompt D §4) — F1/L1 surface.

Moved verbatim from services/best_presentation.py (registry extraction
2026-08-03). L1 FENCE lives in this text: the composition is verbatim-
select with a light continuity polish — "change only a FEW words per
slide", "NEVER add new claims". Editing these rules is an L1-relevant
prompt change: regenerate prompts.lock.json and the best_presentation
golden evals must pass.

``system()`` is a builder (not a pre-rendered constant) so
``with_voice_rules`` is applied at call time exactly as the service did
inline — test monkeypatching and voice-rule updates behave identically.
"""
from __future__ import annotations

RULES = [
    "You assemble a speaker's STRONGEST version of their talk from lines "
    "they actually said. For each slide you get the slide's title/body and "
    "the user's best spoken line for it.",
    "Return that line MOSTLY VERBATIM. You may change only a FEW words per "
    "slide — just enough for continuity with the neighbouring slides and "
    "accuracy to this slide's point.",
    "NEVER add new claims, facts, numbers, or sentences the user didn't say. "
    "Keep the user's voice. If a line is already clean, return it unchanged.",
    "Render in the SAME language the user spoke in.",
    'Output strict JSON: {"slides": [{"slide_index": int, "text": str}]} '
    "with one entry per input slide.",
]


def system() -> str:
    from services.will_voice import with_voice_rules
    return with_voice_rules("\n".join(f"- {r}" for r in RULES))


REGISTER = {
    "best_presentation.system": system,
}
