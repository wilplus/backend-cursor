"""JSON Schemas for OpenAI structured-output calls.

Centralises every LLM contract this codebase relies on so:
  - parser fragility (the old ``|||`` + ``[ADVANCE]`` + regex-fenced JSON
    workarounds) goes away — the API now guarantees the shape;
  - schema evolution is a one-file diff plus a version bump in the
    schema ``name`` field (older code can still reference the v1 name
    while a v2 schema rolls out);
  - downstream services that fact-check or persist these payloads
    can import the same dict to validate their own writes.

Every schema must:
  - set ``"strict": true`` so the API rejects deviations rather than
    returning loosely-shaped output;
  - declare ``additionalProperties: false`` AND list every property
    in ``required`` (strict mode requires this — optional fields are
    expressed by allowing the type to include ``"null"``);
  - use the ``{"name", "strict", "schema"}`` wrapper expected by the
    OpenAI ``response_format={"type": "json_schema", ...}`` API.

Pin model versions: structured outputs require ``gpt-4o-mini-2024-07-18``
or later (any current ``gpt-4o-mini`` alias on the Anthropic-grade SDK
satisfies this). Older snapshots return 400 on the response_format kwarg
— that's the only way Phase 0 can regress and it's caught loudly.
"""
from __future__ import annotations

from typing import Any


# ── Schemas ─────────────────────────────────────────────────────────────────

EXCHANGE_SCORE_SCHEMA: dict[str, Any] = {
    "name": "exchange_score_v1",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "specificity",
            "emotional_movement",
            "engagement",
            "rationale",
        ],
        "properties": {
            "specificity": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": (
                    "0..1 — did the user name a concrete moment, "
                    "feeling, or action? 0 generic, 1 vivid specific."
                ),
            },
            "emotional_movement": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": (
                    "0..1 — did the answer reveal something the "
                    "original transcript did not already say?"
                ),
            },
            "engagement": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": (
                    "0..1 — did the user lean in? Consider length, "
                    "specificity of language, apparent effort."
                ),
            },
            "rationale": {
                "type": "string",
                "maxLength": 240,
                "description": (
                    "One sentence summarising the strongest signal. "
                    "If you quote the user, the phrase MUST appear "
                    "verbatim in their answer or the original "
                    "transcript — the fact-check guard will downgrade "
                    "scores when quotes are hallucinated."
                ),
            },
        },
    },
}


AWARENESS_TURN_SCHEMA: dict[str, Any] = {
    "name": "awareness_turn_v1",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["validation_bubble", "challenge_bubble", "advance"],
        "properties": {
            "validation_bubble": {
                "type": "string",
                "maxLength": 280,
                "description": (
                    "Brief acknowledgment of the user's first reply. "
                    "1-2 sentences max. Empathetic for stress, warm "
                    "for charisma. No coaching directive yet."
                ),
            },
            "challenge_bubble": {
                "type": "string",
                "maxLength": 280,
                "description": (
                    "The mic-on instruction telling the user what to "
                    "do next. Concrete and specific — name the "
                    "behaviour, not the abstraction."
                ),
            },
            "advance": {
                "type": "boolean",
                "description": (
                    "true when the user is ready to move into the "
                    "trial-recording stage (almost always true on the "
                    "first turn — this two-bubble loop is one-shot)."
                ),
            },
        },
    },
}


# ── Convenience: build the response_format kwarg in one place ──────────────


def response_format(schema: dict[str, Any]) -> dict[str, Any]:
    """Return the ``response_format=`` kwarg for the OpenAI SDK.

    Usage:
        from services.llm_schemas import (
            response_format, EXCHANGE_SCORE_SCHEMA,
        )
        client.chat.completions.create(
            ...,
            response_format=response_format(EXCHANGE_SCORE_SCHEMA),
        )

    Encapsulating the wrapper here means a future SDK change to the
    structured-outputs envelope (a Beta → GA rename, say) is one diff
    in one file rather than a search-and-replace across every call site.
    """
    return {"type": "json_schema", "json_schema": schema}
