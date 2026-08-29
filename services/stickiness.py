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
from collections import Counter


logger = logging.getLogger(__name__)


_MODEL = "gpt-4o-mini"
_MAX_TOKENS = 400


def compute_session_stickiness(
    snippets: list[dict],
) -> tuple[str | None, float | None, dict[str, int] | None]:
    """Run one LLM batch call and compute (top_topic, score, distribution).

    ``snippets`` is the list of active snippets the metrics computer
    already gathered — each must carry at least a ``transcript`` (or
    transcript_text / transcript_excerpt fallback) and a turn_number.
    Returns (None, None, None) when:
      - too few snippets to compute meaningful stickiness (< 2)
      - LLM call failed or returned unparseable
      - every per-turn topic came back empty
    """
    if not snippets or len(snippets) < 2:
        return None, None, None

    items = _serialise_snippets(snippets)
    if len(items) < 2:
        return None, None, None

    topics = _extract_topics_via_llm(items)
    if not topics:
        return None, None, None

    # Topic counts, case-folded. We use the lower-cased form as the
    # dictionary key but pick the most-common ORIGINAL spelling as
    # the display label so "Sarah" beats "sarah" when both occur.
    surface_counts: dict[str, Counter] = {}
    counts: Counter[str] = Counter()
    for raw in topics:
        if not raw:
            continue
        key = raw.strip().lower()
        if not key:
            continue
        counts[key] += 1
        surface_counts.setdefault(key, Counter())[raw.strip()] += 1

    if not counts:
        return None, None, None

    top_key, top_count = counts.most_common(1)[0]
    topical_total = sum(counts.values())
    score = round(top_count / topical_total, 4) if topical_total else None

    # Pick the most-used surface form for display.
    surfaces = surface_counts.get(top_key) or Counter()
    display_label = surfaces.most_common(1)[0][0] if surfaces else top_key

    distribution = dict(counts)  # already case-folded keys

    return display_label, score, distribution


# ── Internals ───────────────────────────────────────────────────────────────


def _serialise_snippets(snippets: list[dict]) -> list[dict]:
    """Build the per-turn list the LLM topic-extractor consumes.

    Each item carries the question (the AI's prompt for that turn)
    plus the user's answer — both matter for topic extraction
    because the question frames what the user was reacting to.

    Two non-obvious things this function does:

    1. **Deduplicate by turn_number.** ``charisma_snippets`` can hold
       both a turn row (the per-turn answer audio) AND an extracted
       highlight row sliced from that same turn. Both have the same
       turn_number; both have a transcript. Counting them as two
       separate turns inflates stickiness — the same topic appears
       twice, once per row. We keep the row with the longest
       transcript (assumed to be the turn row; highlights are
       sub-slices).

    2. **Order by turn_number, not start_offset_ms.** Turn rows have
       ``start_offset_ms = 0`` (or NULL) before finalize rewrites
       them into the concatenated full recording, so ordering by
       offsets is unstable on fresh sessions. ``turn_number`` is
       written at upload time and never changes.
    """
    # First pass: dedupe by turn_number, keeping the row with the
    # most transcript content.
    by_turn: dict[int, dict] = {}
    standalone: list[dict] = []  # rows without a turn_number
    for s in snippets:
        transcript = (
            (s.get("transcript") or "")
            or (s.get("transcript_text") or "")
            or (s.get("transcript_excerpt") or "")
        ).strip()
        if not transcript:
            continue
        question = (s.get("question_text") or "").strip()

        turn = s.get("turn_number")
        try:
            turn_int = int(turn) if turn is not None else None
        except (TypeError, ValueError):
            turn_int = None

        record = {
            "turn_number": turn_int,
            "question": question,
            "transcript": transcript,
        }

        if turn_int is None:
            standalone.append(record)
            continue

        prev = by_turn.get(turn_int)
        if prev is None or len(record["transcript"]) > len(prev["transcript"]):
            by_turn[turn_int] = record

    # Sort the deduplicated turns by turn_number ASC; append the
    # standalone (no-turn-number) rows last in their original order.
    ordered = [by_turn[k] for k in sorted(by_turn.keys())]
    ordered.extend(standalone)
    return ordered


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
