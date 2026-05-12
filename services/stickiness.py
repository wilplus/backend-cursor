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
from typing import Any


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
    """Pull (turn_number, transcript) out of each snippet, in order.

    Returns only items with non-empty transcripts. ``turn_number`` is
    forwarded to the LLM so it can keep the per-turn topic array
    aligned with the input.
    """
    out: list[dict] = []
    for s in snippets:
        transcript = (
            (s.get("transcript") or "")
            or (s.get("transcript_text") or "")
            or (s.get("transcript_excerpt") or "")
        ).strip()
        if not transcript:
            continue
        out.append({
            "turn_number": s.get("turn_number"),
            "transcript": transcript,
        })
    return out


def _extract_topics_via_llm(items: list[dict]) -> list[str] | None:
    """One batch call. Returns per-turn topic list (some may be empty)."""
    try:
        from services.openai_service import OpenAIService
        from services.llm_schemas import (
            SESSION_TOPIC_EXTRACTION_SCHEMA,
            response_format,
        )
    except Exception as e:
        logger.warning("stickiness: import failed: %s", e)
        return None

    service = OpenAIService()
    if not service.client:
        return None

    user_prompt = _build_user_prompt(items)
    system_prompt = (
        "Extract a 1-2 word topic for each interview turn. Normalise "
        "different surface forms of the same subject to one phrase "
        "across turns (so \"my boss Sarah\" and \"Sarah\" should be "
        "the same topic in your output). Return one topic per turn "
        "in the order given. Use an empty string for non-substantive "
        "turns (\"yeah\", filler, single words). Output strict JSON "
        "with the key per_turn_topics only."
    )

    try:
        response = service.client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=_MAX_TOKENS,
            temperature=0.2,
            response_format=response_format(SESSION_TOPIC_EXTRACTION_SCHEMA),
        )
        raw = (response.choices[0].message.content or "").strip()
    except Exception as e:
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
    """Render snippets as a numbered list the LLM can align its output to."""
    lines: list[str] = []
    for i, it in enumerate(items, start=1):
        turn = it.get("turn_number") or i
        transcript = it.get("transcript") or ""
        # Trim very long transcripts — topic extraction doesn't need
        # the full text, just enough to identify the subject. Cap at
        # ~600 chars per turn to keep the whole prompt under budget.
        if len(transcript) > 600:
            transcript = transcript[:600] + "…"
        lines.append(f"Turn {turn}: {transcript}")
    return "INTERVIEW TURNS:\n" + "\n\n".join(lines)
