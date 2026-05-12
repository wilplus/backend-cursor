"""Coaching-outcome capture for the contextual /chat follow-up loop.

Problem this solves
-------------------
When a user clicks "Understand your charisma" or "Release your stress"
on a published snippet (the /results page CTA), the chat boots with an
LLM-generated question that's seeded by the admin's coach insight +
the snippet's transcript. Today that whole exchange — what the user
answered, how long they answered, whether they continued — gets
written to charisma_snippets as a regular interview turn and is then
forgotten. Nothing accumulates back onto the SOURCE snippet, so the
admin who wrote the insight has no idea whether it produced
meaningful reflection or fell flat, and the system has no signal it
could later use to improve question generation.

This module is the first piece of the learning loop. After the user
completes turn 1 of a contextual chat, ``evaluate_and_record_followup_
outcome`` is invoked from a daemon thread by the interview-upload
endpoint. It:

  1. Loads the SOURCE snippet (the one whose CTA the user clicked)
     owner-scoped to the current user.
  2. Builds an evaluation prompt with four pieces of context:
       - the source-snippet transcript (what the user originally said)
       - the admin's coach insight (what the coach noticed)
       - the contextual question asked (admin's stored follow_up_question
         OR the LLM-generated one)
       - the user's turn-1 answer text + length + duration
  3. Calls GPT-4o-mini and asks for a JSON triple
     (specificity, emotional_movement, engagement) each 0..1.
  4. Computes a weighted composite ``score`` in [0, 1].
  5. UPSERTs the whole bundle into ``charisma_snippets.follow_up_
     outcome`` (JSONB) on the source-snippet row.

This commit deliberately collects only. No UI shows the score yet, no
retrieval layer uses it yet. The point is to start accumulating
labeled training data. A later commit surfaces the score in the admin
UI; a later commit retrieves "successful" exchanges as few-shot
examples for new contextual questions.

Idempotency
-----------
Latest-wins. If the user re-records turn 1, the new evaluation
overwrites the prior outcome on the same row. We do not version the
JSONB blob — the source/captured_at fields document when the latest
write landed.

Failure mode
------------
Every failure path is swallowed and logged. Outcome capture must NEVER
break the interview upload it was spawned by. If the LLM call fails,
the column simply stays NULL for that snippet and the loop self-heals
on the next contextual click.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from services.db import db


logger = logging.getLogger(__name__)


# Weights for the composite score. Sum = 1.0. Tunable later.
_W_SPECIFICITY = 0.40
_W_EMOTIONAL_MOVEMENT = 0.35
_W_ENGAGEMENT = 0.25


def evaluate_and_record_followup_outcome(
    *,
    source_snippet_id: str,
    user_id: str,
    user_answer_text: str,
    user_answer_duration_ms: int | None,
    asked_question: str | None = None,
) -> dict[str, Any] | None:
    """Score a contextual turn-1 answer and persist it onto the source snippet.

    Args:
        source_snippet_id: the snippet whose CTA seeded this chat
            (passed by the frontend as ``source_snippet_id`` on the
            interview upload form).
        user_id: the requesting user. Used to scope the snippet lookup
            so a user can never trigger evaluation against someone
            else's snippet.
        user_answer_text: the Whisper transcription of turn-1 audio.
        user_answer_duration_ms: turn-1 audio length, for the engagement
            heuristic. May be None when duration was not provided.
        asked_question: the contextual question the AI asked at the
            top of the chat. Captured for completeness; defaults to
            the source snippet's stored follow_up_question when
            absent (so legacy callers without question context still
            get useful evaluation).

    Returns:
        The persisted outcome dict on success, or None when the eval
        couldn't run (snippet not found, transcript missing, LLM down,
        DB write failed). All failure modes log and return None — the
        caller (a daemon thread off the upload endpoint) must NOT
        propagate the error to the user's upload response.
    """
    answer_text = (user_answer_text or "").strip()
    if not answer_text:
        logger.info(
            "outcome:skip reason=empty_answer source_snippet=%s",
            source_snippet_id,
        )
        return None

    snippet = _load_source_snippet(source_snippet_id, user_id)
    if snippet is None:
        return None

    source_transcript = (snippet.get("transcript") or "").strip()
    admin_comment = (snippet.get("admin_comment") or "").strip()
    stored_question = (snippet.get("follow_up_question") or "").strip()
    question_text = (asked_question or "").strip() or stored_question

    # We need at least admin_comment + question text to evaluate the
    # exchange meaningfully. Source transcript is nice but not strictly
    # required — the user's answer + question alone can be scored.
    if not admin_comment or not question_text:
        logger.info(
            "outcome:skip reason=missing_context source_snippet=%s "
            "has_admin_comment=%s has_question=%s",
            source_snippet_id, bool(admin_comment), bool(question_text),
        )
        return None

    components, rationale = _llm_score_exchange(
        source_transcript=source_transcript,
        admin_comment=admin_comment,
        question_text=question_text,
        answer_text=answer_text,
        answer_duration_ms=user_answer_duration_ms,
    )
    if components is None:
        return None

    composite = _composite_score(components)
    word_count = len(answer_text.split())

    outcome: dict[str, Any] = {
        "source": "post_turn_1_evaluation",
        "version": "v1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "user_id": str(user_id),
        "question_text": question_text,
        "user_answer": {
            "text": answer_text,
            "duration_ms": int(user_answer_duration_ms or 0),
            "word_count": word_count,
        },
        "evaluator": {
            "model": "gpt-4o-mini",
            "score": round(composite, 4),
            "components": {k: round(v, 4) for k, v in components.items()},
            "rationale": rationale,
        },
        # Top-level mirror of the headline number — makes the JSONB
        # path index (idx_charisma_snippets_follow_up_outcome_score)
        # actually work without a deep ->-> traversal.
        "score": round(composite, 4),
    }

    if not _persist_outcome(source_snippet_id, outcome):
        return None

    logger.warning(
        "outcome:recorded source_snippet=%s user=%s score=%.3f "
        "components=%s words=%d",
        source_snippet_id, user_id, composite,
        outcome["evaluator"]["components"], word_count,
    )
    return outcome


# ── Internals ───────────────────────────────────────────────────────────────


def _load_source_snippet(snippet_id: str, user_id: str) -> dict | None:
    """Owner-scoped load. Returns the row or None when the snippet
    doesn't exist OR doesn't belong to ``user_id``.

    Using v2_get_charisma_snippet_for_user keeps the security model
    aligned with how the first-question endpoint already loads the
    same row (routes/v2_routes.py::v2_user_chat_first_question).
    """
    try:
        snippet = db.v2_get_charisma_snippet_for_user(snippet_id, user_id)
    except Exception as e:
        logger.warning(
            "outcome: snippet load failed source_snippet=%s err=%s",
            snippet_id, e,
        )
        return None
    if not snippet:
        logger.info(
            "outcome:skip reason=snippet_not_owned source_snippet=%s user=%s",
            snippet_id, user_id,
        )
    return snippet


def _llm_score_exchange(
    *,
    source_transcript: str,
    admin_comment: str,
    question_text: str,
    answer_text: str,
    answer_duration_ms: int | None,
) -> tuple[dict[str, float] | None, str | None]:
    """Call GPT-4o-mini and parse a (components, rationale) tuple.

    Returns (None, None) on any failure so the caller can short-circuit
    cleanly. The model is asked for strict JSON; we parse defensively
    and bound each component to [0, 1].
    """
    try:
        from services.openai_service import OpenAIService
    except Exception as e:
        logger.warning("outcome: openai_service import failed: %s", e)
        return None, None

    service = OpenAIService()
    if not service.client:
        logger.warning("outcome: OpenAI client unavailable (missing key?)")
        return None, None

    duration_str = (
        f"{answer_duration_ms / 1000:.1f}s" if answer_duration_ms else "unknown"
    )
    word_count = len(answer_text.split())

    system = (
        "You are evaluating the quality of a coaching follow-up "
        "exchange. You score three independent dimensions, each from "
        "0.0 to 1.0, then add a single-sentence rationale.\n"
        "\n"
        "Return STRICT JSON with this exact shape and no additional "
        "keys, prose, or markdown:\n"
        '{\n'
        '  "specificity": <number 0-1>,\n'
        '  "emotional_movement": <number 0-1>,\n'
        '  "engagement": <number 0-1>,\n'
        '  "rationale": "<one sentence summarising the strongest signal>"\n'
        '}\n'
        "\n"
        "Definitions:\n"
        "  SPECIFICITY — did the user name a concrete moment, feeling, "
        "or action, vs answer in generalities? 0 = generic platitudes, "
        "1 = vivid specific detail.\n"
        "  EMOTIONAL_MOVEMENT — did the answer reveal something the "
        "original transcript did not already say? 0 = same surface as "
        "before, 1 = new insight / acknowledgment / specific introspection.\n"
        "  ENGAGEMENT — did the user lean in? Consider answer length, "
        "specificity of language, apparent effort. Note: short answers "
        "can be high-engagement if specific; long answers can be "
        "low-engagement if rambling."
    )

    user_prompt = (
        f"ORIGINAL MOMENT (what the user said earlier):\n"
        f'"{source_transcript or "[no transcript captured]"}"\n'
        f"\n"
        f"COACH INSIGHT (what the human coach noted):\n"
        f'"{admin_comment}"\n'
        f"\n"
        f"FOLLOW-UP QUESTION asked at the top of this chat:\n"
        f'"{question_text}"\n'
        f"\n"
        f"USER'S TURN-1 ANSWER:\n"
        f'"{answer_text}"\n'
        f"(length: {word_count} words, audio duration: {duration_str})\n"
        f"\n"
        f"Return the JSON now."
    )

    try:
        response = service.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=250,
            temperature=0.3,
        )
        raw = (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("outcome: openai call failed: %s", e)
        return None, None

    parsed = _parse_score_json(raw)
    if parsed is None:
        logger.warning("outcome: could not parse model output: %r", raw[:400])
        return None, None

    components = {
        "specificity": _clamp01(parsed.get("specificity")),
        "emotional_movement": _clamp01(parsed.get("emotional_movement")),
        "engagement": _clamp01(parsed.get("engagement")),
    }
    rationale = str(parsed.get("rationale") or "").strip()[:500] or None
    return components, rationale


def _parse_score_json(raw: str) -> dict | None:
    """Pull the first JSON object out of ``raw``. Handles code-fenced output."""
    if not raw:
        return None
    # Strip ```json``` fences if the model wrapped its answer
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    candidate = fence_match.group(1) if fence_match else raw
    # Or pull the outermost {...}
    brace_match = re.search(r"\{.*\}", candidate, re.DOTALL)
    if not brace_match:
        return None
    try:
        return json.loads(brace_match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None


def _composite_score(components: dict[str, float]) -> float:
    return _clamp01(
        _W_SPECIFICITY * components.get("specificity", 0.0)
        + _W_EMOTIONAL_MOVEMENT * components.get("emotional_movement", 0.0)
        + _W_ENGAGEMENT * components.get("engagement", 0.0)
    )


def _clamp01(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


def _persist_outcome(snippet_id: str, outcome: dict[str, Any]) -> bool:
    """Write the JSONB blob to the source snippet's follow_up_outcome.

    Uses the dedicated db helper so the column reference stays in one
    place — if PGRST204 ever surfaces because the column wasn't yet
    migrated (see the recent phantom-column incident), the failure
    logs but doesn't bubble up to the upload endpoint.
    """
    try:
        result = db.set_snippet_follow_up_outcome(snippet_id, outcome)
        return bool(result)
    except Exception as e:
        logger.warning(
            "outcome: persist failed source_snippet=%s err=%s",
            snippet_id, e,
        )
        return False
