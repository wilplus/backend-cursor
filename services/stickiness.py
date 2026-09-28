"""Per-session stickiness-topic metric.

Phase 11. Measures how much a user fixates on a single topic across
the answers in one session. Computed alongside the existing KPI when
admin clicks "Compute Metrics" — one batch LLM call extracts a 1-2
word topic per snippet, frequencies are counted in Python, the top
topic and its share become the metric.

Definition
----------
  stickiness_top_topic = the most-recurring topic across snippets
  stickiness_score     = top_topic_count / total_snippets_with_topic
                          (in [0, 1]; 0 = broad coverage,
                          1 = total fixation on one topic)
  distribution         = {topic_lower: count, ...}

Why session-level (not user-level)
----------------------------------
User-level stickiness is what Phase 4 recurring_entities already
tracks (across coaching_attempts). This is the SESSION view: in this
interview, did the user keep circling back to one subject? Useful
diagnostic for an admin reviewing a single session in isolation —
e.g. "they wouldn't stop talking about Q4 review" or "they covered
a healthy spread of topics".

Failure semantics
-----------------
Returns (None, None, None) on any failure — the caller persists
NULLs and the admin panel renders "—". Stickiness is supplementary;
it must never block the rest of the compute-metrics response.
"""
from __future__ import annotations

import json
import logging


logger = logging.getLogger(__name__)


_MODEL = "gpt-4o-mini"
_MAX_TOKENS = 400


# ── Internals ───────────────────────────────────────────────────────────────


def _extract_topics_via_llm(items: list[dict]) -> list[str] | None:
    """One batch call. Returns per-turn topic list (some may be empty)."""
    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_STICKINESS_TOPICS
        from services.llm_schemas import (
            SESSION_TOPIC_EXTRACTION_SCHEMA,
            response_format,
        )
    except Exception as e:
        logger.warning("stickiness: import failed: %s", e)
        return None

    user_prompt = _build_user_prompt(items)
    system_prompt = (
        "You read an interview transcript and extract one 1-2 word "
        "topic per turn — capturing what the USER was talking about "
        "in their answer (the question is given only as context for "
        "what they were responding to).\n"
        "\n"
        "Apply to EVERY turn in the input — return one topic per "
        "turn in the exact order given, never collapse turns "
        "together, never skip turns. The output array length must "
        "equal the number of turns in the input.\n"
        "\n"
        "Normalise surface forms of the same subject to one phrase "
        "across turns: \"my boss Sarah\" and \"Sarah\" should be "
        "the same topic; \"Q4 review\" and \"the Q4 meeting\" "
        "should be the same topic. This lets the downstream counter "
        "measure how often the user circles back to a subject.\n"
        "\n"
        "Use an empty string \"\" for non-substantive turns — "
        "single-word affirmations, fillers, or answers that don't "
        "name a subject. Better to emit \"\" than to invent a topic.\n"
        "\n"
        "Output strict JSON with the key per_turn_topics only."
    )

    try:
        response = chat_complete(
            spec=SPEC_STICKINESS_TOPICS,
            system=system_prompt,
            user=user_prompt,
            surface="stickiness_topics",
            response_format_override=response_format(
                SESSION_TOPIC_EXTRACTION_SCHEMA
            ),
        )
        if response is None:
            return None
        raw = response.text
    except Exception as e:
        from services.processing_authorization import rethrow_processing_authorization
        rethrow_processing_authorization(e)
        logger.warning("stickiness: openai call failed: %s", e)
        return None

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("stickiness: unparseable LLM output %r", raw[:300])
        return None

    topics_raw = parsed.get("per_turn_topics") or []
    if not isinstance(topics_raw, list):
        return None
    topics = [str(t) for t in topics_raw]

    # Pad / truncate so we never index past the snippet list. The
    # schema doesn't enforce length, so a model that drops trailing
    # turns or hallucinates extra ones is handled here.
    if len(topics) > len(items):
        topics = topics[: len(items)]
    elif len(topics) < len(items):
        topics += [""] * (len(items) - len(topics))
    return topics


def _build_user_prompt(items: list[dict]) -> str:
    """Render the Q+A pairs the LLM topic-extractor should align its
    output array to.

    Each turn is rendered as::

        Turn N:
          Q: <question, trimmed>
          A: <answer, trimmed>

    Including the Q gives the LLM enough context to disambiguate
    answers like "Sarah, again" that would otherwise be a one-word
    blob. Both Q and A are trimmed to 400 chars each (was 600 for
    just A) so 10 long turns still fit comfortably in the model's
    context.
    """
    lines: list[str] = []
    n = len(items)
    for i, it in enumerate(items, start=1):
        turn = it.get("turn_number") or i
        question = (it.get("question") or "").strip()
        transcript = (it.get("transcript") or "").strip()
        if len(question) > 400:
            question = question[:400] + "…"
        if len(transcript) > 400:
            transcript = transcript[:400] + "…"
        block_lines = [f"Turn {turn}:"]
        if question:
            block_lines.append(f"  Q: {question}")
        block_lines.append(f"  A: {transcript}")
        lines.append("\n".join(block_lines))
    header = (
        f"INTERVIEW TURNS ({n} turns total — extract one topic for "
        "EACH, in order):"
    )
    return header + "\n\n" + "\n\n".join(lines)
