"""Phase 16 — pre-baked summary of a user's EBCP baseline (turns 1-4).

Why this exists
---------------
Before Phase 16, the turn-5 LLM call received the 4 raw EBCP
transcripts as conversation history plus the system prompt and was
asked to "generate the next question." One model invocation doing
extraction + generation in a single shot is exactly where shallow
openers leak in — the model spends most of its budget summarising
who-the-user-is and lands the question with what's left.

This module splits the work. ONE dedicated LLM call runs the first
time a user reaches turn 5 (i.e. has graduated from the scripted
EBCP). It digests the 4 baseline answers into a structured JSONB:

    {
      "headline":               <one sentence naming the user>,
      "themes":                 [<2-5 tags>],
      "aspirational_archetype": <who they want to embody>,
      "tension":                <the productive gap>,
      "coaching_handle":        <ONE concrete directive the next
                                 turn's coach should use>
    }

That gets written to user_settings.baseline_summary and read by
every subsequent question-generator call for this user — both the
interview turn 5+ path AND the contextual /chat first-question
path. One extra LLM call per user, exactly once at graduation.

Failure semantics
-----------------
Every failure mode returns None — the caller falls through to the
pre-Phase-16 behaviour (raw previous_turns in conversation
history). A missed summary degrades a single turn-5 prompt; the
next session retries.
"""
from __future__ import annotations

import logging
from typing import Any, Optional



logger = logging.getLogger(__name__)


_MODEL = "gpt-4o-mini"
_MAX_TOKENS = 600
# Generous-but-bounded budget so a stalled summary call doesn't
# hold up the user's turn-5 question generation indefinitely.
_TIMEOUT_SECONDS = 8.0
_SUMMARY_VERSION = "v1"


def format_baseline_for_prompt(summary: Optional[dict[str, Any]]) -> Optional[str]:
    """Render a baseline_summary blob as a tight system-prompt block.

    Returns None when the summary is missing or empty so the caller
    can skip the block entirely. The shape is deliberately compact
    so it costs few tokens but carries every field that shapes the
    next question.
    """
    if not isinstance(summary, dict):
        return None
    headline = (summary.get("headline") or "").strip()
    handle = (summary.get("coaching_handle") or "").strip()
    if not headline and not handle:
        return None

    lines: list[str] = ["[BASELINE INSIGHT — from this user's EBCP run]"]
    if headline:
        lines.append(f"Who they are: {headline}")
    archetype = (summary.get("aspirational_archetype") or "").strip()
    if archetype:
        lines.append(f"Who they want to embody: {archetype}")
    tension = (summary.get("tension") or "").strip()
    if tension:
        lines.append(f"Productive tension: {tension}")
    themes = summary.get("themes") or []
    theme_strs = [str(t).strip() for t in themes if str(t).strip()]
    if theme_strs:
        lines.append(f"Recurring themes: {', '.join(theme_strs[:5])}")
    if handle:
        lines.append("")
        lines.append(
            f"COACHING HANDLE (build your next question on this): "
            f"{handle}"
        )
    return "\n".join(lines)


# ── Internals ───────────────────────────────────────────────────────────────


def _build_system_prompt() -> str:
    from services.will_voice import with_voice_rules
    return with_voice_rules(
        "You're a speaking coach analysing a brand-new user's EBCP "
        "Baseline Mapping (4 scripted opener turns).\n"
        "\n"
        "The 4 turns by design probe different terrain:\n"
        "  Turn 1 — math confidence (\"Are you good at math?\")\n"
        "  Turn 2 — math under pressure (a numeric challenge)\n"
        "  Turn 3 — a leader whose communication they admire\n"
        "  Turn 4 — a fictional character they'd bring to a negotiation\n"
        "\n"
        "Your job is to digest the 4 answers into a structured "
        "summary that the next 20+ coaching questions will build on. "
        "BE SPECIFIC — generic taglines (\"engaged learner\") are "
        "useless. Concrete, image-bearing language only.\n"
        "\n"
        "The most important field is coaching_handle — ONE directive "
        "describing the growth edge this user has, framed so the "
        "next turn's question can be built directly on top of it. "
        "Not what they're good at — where they're avoidant, what "
        "they outsourced to an admired figure, what they haven't "
        "yet claimed as their own.\n"
        "\n"
        "Output strict JSON matching the schema. No prose outside it."
    )


def _build_user_prompt(turns: list[dict]) -> str:
    lines: list[str] = ["[USER'S EBCP BASELINE ANSWERS]"]
    for i, t in enumerate(turns, start=1):
        lines.append("")
        lines.append(f"Turn {i}")
        if t.get("question"):
            lines.append(f"  AI asked: {t['question']}")
        lines.append(f"  User answered: {t['transcript']}")
    return "\n".join(lines)
