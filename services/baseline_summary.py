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

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from services.db import db


logger = logging.getLogger(__name__)


_MODEL = "gpt-4o-mini"
_MAX_TOKENS = 600
# Generous-but-bounded budget so a stalled summary call doesn't
# hold up the user's turn-5 question generation indefinitely.
_TIMEOUT_SECONDS = 8.0
_SUMMARY_VERSION = "v1"


def compute_baseline_summary(
    *,
    user_id: str,
    previous_turns: list[dict],
) -> Optional[dict[str, Any]]:
    """Run the digest LLM call and persist the result on user_settings.

    ``previous_turns`` is the same list the question-generator
    receives — each item has at least ``question`` and ``transcript``.
    We only digest when at least 4 substantive turns are present;
    fewer than that and the EBCP run isn't actually complete.

    Returns the persisted summary dict on success, None on any
    failure (LLM down, unparseable, persist failed). Failure cases
    log + return None so the caller can use raw previous_turns
    instead.
    """
    if not user_id or not previous_turns:
        return None

    usable = _serialise_turns(previous_turns)
    if len(usable) < 4:
        logger.info(
            "baseline_summary: skipping user=%s — only %d usable turns",
            user_id, len(usable),
        )
        return None

    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_BASELINE_SUMMARY
    except Exception as e:
        logger.warning("baseline_summary: openai import failed: %s", e)
        return None
    try:
        from services.llm_schemas import (
            BASELINE_SUMMARY_SCHEMA,
            response_format,
        )
    except Exception as e:
        logger.warning("baseline_summary: schema import failed: %s", e)
        return None

    system = _build_system_prompt()
    user_prompt = _build_user_prompt(usable)

    try:
        response = chat_complete(
            spec=SPEC_BASELINE_SUMMARY,
            system=system,
            user=user_prompt,
            surface="baseline_summary",
            response_format_override=response_format(BASELINE_SUMMARY_SCHEMA),
            user_id=user_id,
        )
        if response is None:
            return None
        raw = response.text
    except Exception as e:
        from services.processing_authorization import rethrow_processing_authorization
        rethrow_processing_authorization(e)
        logger.warning(
            "baseline_summary: openai call failed user=%s err=%s",
            user_id, e,
        )
        return None

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning(
            "baseline_summary: unparseable LLM output user=%s raw=%r",
            user_id, raw[:300],
        )
        return None

    # Defensive shape check — strict mode should guarantee this but
    # we don't trust the model 100%.
    required = (
        "headline",
        "themes",
        "aspirational_archetype",
        "tension",
        "coaching_handle",
    )
    if not all(k in parsed for k in required):
        logger.warning(
            "baseline_summary: missing required keys user=%s keys=%s",
            user_id, list(parsed.keys()),
        )
        return None

    summary: dict[str, Any] = {
        "version": _SUMMARY_VERSION,
        "model": _MODEL,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "turns_analyzed": len(usable),
        "headline": str(parsed.get("headline") or "").strip(),
        "themes": [
            str(t).strip() for t in (parsed.get("themes") or [])
            if str(t).strip()
        ],
        "aspirational_archetype": str(
            parsed.get("aspirational_archetype") or ""
        ).strip(),
        "tension": str(parsed.get("tension") or "").strip(),
        "coaching_handle": str(parsed.get("coaching_handle") or "").strip(),
    }
    # Sanity: if the model returned all-empty strings, skip persist.
    if not summary["headline"] and not summary["coaching_handle"]:
        return None

    persisted = db.set_user_baseline_summary(user_id, summary)
    if not persisted:
        return None

    # ── Audit log for the directed-freestyle pivot ──────────────
    # Greppable tag [BASELINE_SUMMARY_AUDIT] so we can pull these
    # straight out of Railway logs for the first ~10 production
    # users post-pivot and judge whether the LLM digest is still
    # producing useful coaching_handles now that the source
    # transcripts come from dynamic scenarios (Phase 19) rather
    # than the old static EBCP probes. Each transcript truncated
    # to 200 chars so a long answer doesn't blow up the log line.
    try:
        excerpts = [
            "T{n}={t!r}".format(
                n=t.get("turn_number") or (i + 1),
                t=(t.get("transcript") or "")[:200],
            )
            for i, t in enumerate(usable)
        ]
        logger.info(
            "[BASELINE_SUMMARY_AUDIT] user=%s "
            "coaching_handle=%r headline=%r turns=[%s]",
            user_id,
            summary.get("coaching_handle"),
            summary.get("headline"),
            " | ".join(excerpts),
        )
    except Exception as audit_err:
        logger.warning(
            "[BASELINE_SUMMARY_AUDIT] log emit failed user=%s err=%s",
            user_id, audit_err,
        )

    return summary


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


def _serialise_turns(previous_turns: list[dict]) -> list[dict]:
    """Pull (question, transcript) pairs out of previous_turns.

    Drops items without a transcript — empty answers don't tell us
    anything about the user. Caps each transcript at 600 chars to
    keep the digest prompt under budget.
    """
    out: list[dict] = []
    for t in previous_turns:
        if not isinstance(t, dict):
            continue
        q = (t.get("question") or "").strip()
        a = (t.get("transcript") or "").strip()
        if not a:
            continue
        if len(q) > 300:
            q = q[:300].rstrip() + "…"
        if len(a) > 600:
            a = a[:600].rstrip() + "…"
        out.append({"question": q, "transcript": a})
    return out


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
