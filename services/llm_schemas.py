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
    # v2 (Phase 4) — same three sub-scores + rationale, plus a small
    # entities object the same call extracts in one pass. The v1 name
    # is retired; the only consumer (services.coaching_outcomes) reads
    # the new shape. Strict mode rejects extra keys, so a model that
    # somehow returned v1-shape JSON would error and we'd skip the
    # outcome rather than silently lose entity data.
    "name": "exchange_score_v2",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "specificity",
            "emotional_movement",
            "engagement",
            "rationale",
            "entities",
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
            "entities": {
                "type": "object",
                "additionalProperties": False,
                "required": ["people", "situations", "themes"],
                "description": (
                    "Phase 4 — entities the user mentioned in this "
                    "answer. Each list is short (typically 0-5). "
                    "Keep the user's surface phrasing; the aggregator "
                    "handles case-normalisation. Empty lists are fine."
                ),
                "properties": {
                    "people": {
                        "type": "array",
                        "items": {"type": "string", "maxLength": 60},
                        "description": (
                            "Named people the user referenced "
                            "(\"Sarah\", \"my boss\", \"Mom\"). "
                            "First names + role hints are useful — "
                            "skip generic pronouns like \"my team\"."
                        ),
                    },
                    "situations": {
                        "type": "array",
                        "items": {"type": "string", "maxLength": 80},
                        "description": (
                            "Specific situations or events "
                            "(\"the Q4 review\", \"yesterday's "
                            "stand-up\"). Skip vague references like "
                            "\"a meeting\"."
                        ),
                    },
                    "themes": {
                        "type": "array",
                        "items": {"type": "string", "maxLength": 60},
                        "description": (
                            "Recurring patterns or feelings worth "
                            "tracking across sessions (\"imposter "
                            "syndrome\", \"perfectionism\", \"public "
                            "speaking fear\"). 1-2 word phrases."
                        ),
                    },
                },
            },
        },
    },
}


LEARNER_MIRROR_SCHEMA: dict[str, Any] = {
    # Phase 6 — the on-demand narrative the user sees when they ask
    # "what are you noticing about me?". The LLM gets the learner
    # profile + recent attempt aggregates as input and returns a
    # short reflection. ``observations`` is the audit trail: bullet
    # points the model considered salient, distinct from the prose
    # in ``narrative``. Strict mode keeps the shape stable so the
    # frontend renderer can be dumb.
    "name": "learner_mirror_v1",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["headline", "narrative", "observations"],
        "properties": {
            "headline": {
                "type": "string",
                "maxLength": 120,
                "description": (
                    "One sentence that names the pattern you're "
                    "noticing. Warm, second-person, no clinical "
                    "framing. Examples: \"You're learning to bring "
                    "Sarah into the room with you\" or \"Your "
                    "specificity is sharpening — and you can tell.\""
                ),
            },
            "narrative": {
                "type": "string",
                "maxLength": 1200,
                "description": (
                    "2-3 short paragraphs of reflection in the second "
                    "person. Reference the user's actual recurring "
                    "entities and trends by name. Stay grounded in "
                    "the data — don't invent attempts that aren't in "
                    "the input. End on something forward-looking, "
                    "not summative."
                ),
            },
            "observations": {
                "type": "array",
                "maxItems": 6,
                "items": {"type": "string", "maxLength": 160},
                "description": (
                    "3-6 short bullet points listing the concrete "
                    "facts the narrative is built on (trend "
                    "direction, recurring entity counts, weakest "
                    "dimension, self-rating gap). Audit trail — "
                    "admins use this to verify the narrative is "
                    "grounded."
                ),
            },
        },
    },
}


CHARISMA_DRAFT_SCHEMA: dict[str, Any] = {
    # Phase 10 — AI prefill for charisma_snippets.admin_comment.
    # Generated when a charisma snippet is first extracted so the
    # admin sees a draft they can keep or edit. Strict + tight max
    # lengths so the model produces something terse like a real
    # admin would write, not a clinical paragraph.
    "name": "charisma_draft_v1",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["admin_comment"],
        "properties": {
            "admin_comment": {
                "type": "string",
                "maxLength": 220,
                "description": (
                    "One-sentence coaching insight on what made this "
                    "moment charismatic. Second-person, terse, "
                    "specific. Example: \"Your delivery here was "
                    "magnetic — perfect dynamic range and total "
                    "confidence.\" Never start with \"This\" or "
                    "\"The user\"; speak to the user directly."
                ),
            },
        },
    },
}


STRESS_DRAFT_SCHEMA: dict[str, Any] = {
    # Phase 10 — AI prefill for stress_snippets.coach_label_notes.
    # Same shape + tone as the charisma draft. The field name
    # ("coach_notes") is more clinical than "admin_comment" but the
    # UX role is identical: a coaching insight the admin keeps or edits.
    "name": "stress_draft_v1",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["coach_notes"],
        "properties": {
            "coach_notes": {
                "type": "string",
                "maxLength": 220,
                "description": (
                    "One-sentence coaching insight on what tightened "
                    "in this moment. Second-person, terse, specific. "
                    "Example: \"Your voice tightened when the "
                    "prospect said 'too expensive'.\" Quote the "
                    "trigger phrase verbatim when it's in the "
                    "transcript. Never start with \"This\" or \"The "
                    "user\"."
                ),
            },
        },
    },
}


SESSION_TOPIC_EXTRACTION_SCHEMA: dict[str, Any] = {
    # Phase 11 — per-session stickiness-topic metric. The compute-
    # metrics LLM call already evaluates the transcript; we extend
    # that same call to ALSO emit a 1-2-word topic per snippet so
    # stickiness can be computed without a second round-trip.
    #
    # The array length is expected to match the number of snippets
    # passed in, but we don't enforce a length constraint in the
    # schema — the model occasionally drops trailing turns when the
    # input is long. The caller pads with None where lengths don't
    # match so stickiness can still be computed off the topics that
    # ARE present.
    "name": "session_topic_extraction_v1",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["per_turn_topics"],
        "properties": {
            "per_turn_topics": {
                "type": "array",
                "items": {
                    "type": "string",
                    "maxLength": 60,
                    "description": (
                        "1-2 word topic the user is talking about "
                        "in this turn. Use the same wording across "
                        "turns when the topic repeats (so \"my boss "
                        "Sarah\" and \"Sarah\" should be normalised "
                        "by you to one phrase). Empty string when "
                        "the turn was non-substantive (filler, "
                        "\"yeah\", etc.)."
                    ),
                },
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
