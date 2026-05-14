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
# Composite-score weights. Bumped when adding `stickiness` so the
# four components sum to 1.0. Stickiness gets meaningful weight
# (0.25) because an off-topic but vivid answer was previously
# scoring high — that's the bug we're closing.
_W_SPECIFICITY = 0.30
_W_EMOTIONAL_MOVEMENT = 0.25
_W_ENGAGEMENT = 0.20
_W_STICKINESS = 0.25


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

    # Phase 7 — derive the skill id from the source snippet so each
    # coaching_attempt row carries the intent it was practising.
    # Resolution is swallow-on-error: a bad import here would block
    # an otherwise-valid outcome write, which is worse than just
    # losing the skill tag on this row.
    skill_id: str | None = None
    try:
        from services.skills import resolve_for_snippet
        skill_id = resolve_for_snippet(snippet)
    except Exception as e:
        logger.warning(
            "outcome: skill resolution failed snippet=%s err=%s",
            source_snippet_id, e,
        )

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

    components, rationale, entities = _llm_score_exchange(
        source_transcript=source_transcript,
        admin_comment=admin_comment,
        question_text=question_text,
        answer_text=answer_text,
        answer_duration_ms=user_answer_duration_ms,
    )
    if components is None:
        return None

    # ── Phase 5: fact-check guard ──────────────────────────────────
    # Verify the rationale's quoted claims actually appear in the
    # user's answer / source transcript, and apply the specificity
    # floor. Failures don't drop the outcome (admins still see the
    # exchange) but they DO mark it ineligible for downstream
    # learning — the few-shot retrieval (Phase 1) filters on this
    # flag so hallucinated quotes never seed future prompts.
    from services.fact_check import fact_check_outcome

    fc = fact_check_outcome(
        rationale=rationale or "",
        user_answer_text=answer_text,
        source_transcript=source_transcript,
        specificity=components.get("specificity", 0.0),
    )
    if fc.get("adjusted_specificity") is not None:
        components["specificity"] = _clamp01(fc["adjusted_specificity"])

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
        # Phase 4 — entities the user mentioned in this exchange.
        # Empty lists are OK; None means extraction failed.
        "entities": entities,
        # Phase 7 — skill the attempt practised. None means snippet
        # didn't resolve to a registered skill at write time.
        "skill_id": skill_id,
        # Phase 5 — fact-check flag + diagnostics. Phase 1 few-shot
        # retrieval filters on eligible_for_few_shot so hallucinated
        # outcomes never seed future prompts. The full fact_check
        # block stays in the row for admin audit / debugging.
        "eligible_for_few_shot": bool(fc.get("eligible_for_few_shot")),
        "fact_check": {
            "passed": bool(fc.get("passed")),
            "issues": list(fc.get("issues") or []),
            "adjusted_specificity": fc.get("adjusted_specificity"),
        },
    }

    if not _persist_outcome(source_snippet_id, outcome):
        return None

    logger.warning(
        "outcome:recorded source_snippet=%s user=%s score=%.3f "
        "components=%s words=%d eligible=%s fc_issues=%d",
        source_snippet_id, user_id, composite,
        outcome["evaluator"]["components"], word_count,
        outcome["eligible_for_few_shot"], len(outcome["fact_check"]["issues"]),
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

    # Schema-validated structured output — the API guarantees the JSON
    # shape, so the post-parse defence-in-depth (regex extraction,
    # fence stripping, brace-finding) the previous version had is
    # gone. The only failure mode left is the API call itself.
    from services.llm_schemas import EXCHANGE_SCORE_SCHEMA, response_format

    # TARGET_TOPIC is the exact text of the question the AI asked
    # (or, for cold-start onboarding, the CURRENT_TURN_OBJECTIVE).
    # The Stickiness component grades adherence to it. Without this
    # the evaluator scored quality in abstract — vivid but off-
    # topic answers got high engagement and the composite ignored
    # whether the user actually answered the question.
    target_topic = question_text or "[no target topic captured]"

    system = (
        "You evaluate one coaching-follow-up exchange. Score four "
        "independent dimensions in [0.0, 1.0], add a one-sentence "
        "rationale, AND extract the entities the user mentioned.\n"
        "\n"
        "SPECIFICITY — did the user name a concrete moment, feeling, "
        "or action, vs answer in generalities? 0 generic platitudes, "
        "1 vivid specific detail.\n"
        "EMOTIONAL_MOVEMENT — did the answer reveal something the "
        "original transcript did not already say? 0 same surface, "
        "1 new insight / acknowledgment / specific introspection.\n"
        "ENGAGEMENT — did the user lean in? Consider answer length, "
        "specificity of language, apparent effort. Short answers can "
        "be high-engagement if specific; long answers can be "
        "low-engagement if rambling.\n"
        "STICKINESS — To calculate this, you MUST evaluate how well "
        "the user directly answered this specific Target Topic:\n"
        f'    TARGET_TOPIC: "{target_topic}"\n'
        "Penalize HEAVILY if they drifted, avoided the question, "
        "or went on irrelevant tangents. 1.0 fully on-topic, 0.5 "
        "wandered toward adjacent territory, 0.0 ignored or "
        "actively avoided the asked topic. Specificity + engagement "
        "without stickiness is a vivid answer to the wrong question.\n"
        "\n"
        "ENTITIES — three short lists. PEOPLE are named individuals "
        "(\"Sarah\", \"Mom\", \"my boss Mark\") — skip generic "
        "references like \"my team\". SITUATIONS are specific events "
        "(\"Q4 review\", \"yesterday's stand-up\") — skip vague "
        "\"a meeting\". THEMES are recurring patterns worth tracking "
        "across sessions (\"imposter syndrome\", \"perfectionism\"). "
        "Keep the user's surface phrasing; empty lists are fine when "
        "nothing applies.\n"
        "\n"
        "CITATION RULE — when you quote the user in your rationale, "
        "the quoted phrase MUST appear verbatim (or near-verbatim) in "
        "their answer or the original transcript. A fact-check guard "
        "downgrades scores when quotes are hallucinated; if you're "
        "not sure of the exact wording, paraphrase without quotes."
    )

    user_prompt = (
        f"ORIGINAL MOMENT (what the user said earlier):\n"
        f'"{source_transcript or "[no transcript captured]"}"\n'
        f"\n"
        f"COACH INSIGHT (what the human coach noted):\n"
        f'"{admin_comment}"\n'
        f"\n"
        f"TARGET_TOPIC (the question they were asked — grade "
        f"Stickiness against this):\n"
        f'"{target_topic}"\n'
        f"\n"
        f"USER'S TURN-1 ANSWER:\n"
        f'"{answer_text}"\n'
        f"(length: {word_count} words, audio duration: {duration_str})"
    )

    try:
        response = service.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            # Bumped from 250 to 360 to leave room for the Phase 4
            # entities block. Each entity list caps at a handful of
            # short strings, so the extra budget is small but real.
            max_tokens=360,
            temperature=0.3,
            response_format=response_format(EXCHANGE_SCORE_SCHEMA),
        )
        raw = (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("outcome: openai call failed: %s", e)
        return None, None, None

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # With strict structured outputs this should never happen.
        # When it does the SDK probably returned an unrecognised
        # response — log and bail rather than persist garbage.
        logger.warning("outcome: structured output not parseable: %r", raw[:400])
        return None, None, None

    components = {
        "specificity": _clamp01(parsed.get("specificity")),
        "emotional_movement": _clamp01(parsed.get("emotional_movement")),
        "engagement": _clamp01(parsed.get("engagement")),
        # v3 — topic-adherence dimension, weighted 0.25 in the
        # composite. Heavily penalises vivid-but-off-topic answers.
        "stickiness": _clamp01(parsed.get("stickiness")),
    }
    rationale = str(parsed.get("rationale") or "").strip()[:500] or None
    entities = _sanitize_entities(parsed.get("entities"))
    return components, rationale, entities


def _sanitize_entities(raw: Any) -> dict[str, list[str]] | None:
    """Validate + clean the entities sub-object from the LLM response.

    The schema already constrains shape (strict mode), but a defensive
    pass here catches degenerate values (whitespace-only strings,
    duplicate casing, leading/trailing punctuation) so the persisted
    blob is clean enough for the aggregator to count meaningfully.
    Returns None when the input isn't a dict with the expected keys —
    callers persist None and the column stays NULL.
    """
    if not isinstance(raw, dict):
        return None
    out: dict[str, list[str]] = {}
    for key in ("people", "situations", "themes"):
        seq = raw.get(key)
        if not isinstance(seq, list):
            out[key] = []
            continue
        cleaned: list[str] = []
        seen_lower: set[str] = set()
        for item in seq:
            if not isinstance(item, str):
                continue
            v = item.strip().strip(".,;:!?\"'")
            if not v or len(v) > 80:
                continue
            key_lower = v.lower()
            if key_lower in seen_lower:
                continue
            seen_lower.add(key_lower)
            cleaned.append(v)
        out[key] = cleaned
    # All-empty case: still return the dict (callers can distinguish
    # "extraction ran, found nothing" from "no extraction" via the
    # shape rather than a truthy check).
    return out


def _composite_score(components: dict[str, float]) -> float:
    return _clamp01(
        _W_SPECIFICITY * components.get("specificity", 0.0)
        + _W_EMOTIONAL_MOVEMENT * components.get("emotional_movement", 0.0)
        + _W_ENGAGEMENT * components.get("engagement", 0.0)
        + _W_STICKINESS * components.get("stickiness", 0.0)
    )


def _clamp01(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


def _persist_outcome(snippet_id: str, outcome: dict[str, Any]) -> bool:
    """Persist the evaluation. Phase 2: writes to coaching_attempts
    (canonical 1:N store) and, while the dual-write flag is on, also
    mirrors to the legacy charisma_snippets.follow_up_outcome JSONB so
    the admin UI keeps working through the cutover.

    The coaching_attempts insert is the authoritative success signal —
    if it lands, the outcome counts as persisted even when the legacy
    write fails (e.g. PGRST204 on a soon-to-be-dropped column). The
    legacy write only counts when the canonical insert ALSO failed
    (degraded-mode safety net).
    """
    user_id = str(outcome.get("user_id") or "")
    evaluator = outcome.get("evaluator") or {}
    user_answer = outcome.get("user_answer") or {}

    components = evaluator.get("components") if isinstance(evaluator.get("components"), dict) else None
    try:
        score = float(outcome.get("score")) if outcome.get("score") is not None else None
    except (TypeError, ValueError):
        score = None

    inserted = None
    try:
        inserted = db.insert_coaching_attempt(
            snippet_id=snippet_id,
            user_id=user_id,
            source=str(outcome.get("source") or "post_turn_1_evaluation"),
            score=score,
            components=components,
            question_text=outcome.get("question_text"),
            user_answer_text=user_answer.get("text"),
            user_answer_duration_ms=user_answer.get("duration_ms"),
            user_answer_word_count=user_answer.get("word_count"),
            rationale=evaluator.get("rationale"),
            is_eligible_for_few_shot=bool(outcome.get("eligible_for_few_shot", True)),
            fact_check=outcome.get("fact_check"),
            evaluator_model=evaluator.get("model"),
            entities=outcome.get("entities"),
            skill_id=outcome.get("skill_id"),
            raw_outcome=outcome,
        )
    except Exception as e:
        logger.warning(
            "outcome: coaching_attempts insert raised source_snippet=%s err=%s",
            snippet_id, e,
        )

    legacy_ok = False
    try:
        from config import Config
        if Config().COACHING_ATTEMPTS_DUAL_WRITE:
            legacy_ok = bool(db.set_snippet_follow_up_outcome(snippet_id, outcome))
    except Exception as e:
        # Legacy column may already be dropped — don't let a stale
        # mirror write mask a successful canonical insert.
        logger.warning(
            "outcome: legacy follow_up_outcome write failed source_snippet=%s err=%s",
            snippet_id, e,
        )

    # Phase 3: recompute the inferred learner profile from the user's
    # latest window of attempts. Cheap — one indexed LIMIT 10 select +
    # one upsert. Runs only after a successful canonical insert so the
    # recompute always sees the row we just wrote. Failure is swallowed:
    # a stale profile is far better than failing the outcome capture.
    if inserted is not None and user_id:
        _recompute_learner_profile(user_id)

    if inserted is not None:
        return True
    # Canonical insert failed. Treat the legacy mirror as a fallback
    # success so we don't lose the outcome entirely while the migration
    # is still rolling out.
    return legacy_ok


def _recompute_learner_profile(user_id: str) -> None:
    """Pull this user's recent attempts and refresh their profile blob.

    Designed to never throw — the outcome write that called us is
    already committed and the user's about to land on the next
    coaching turn. A profile recompute failure should log and move
    on, never block the response or trigger a retry storm.
    """
    try:
        from services.learner_profile import (
            ATTEMPTS_WINDOW,
            compute_learner_profile,
        )
        attempts = db.list_recent_coaching_attempts_for_user(
            user_id, limit=ATTEMPTS_WINDOW
        )
        profile = compute_learner_profile(attempts)
        # None means "no analysable attempts" — write None to clear
        # any stale blob.
        db.set_user_inferred_learner_profile(user_id, profile)
    except Exception as e:
        logger.warning(
            "outcome: learner-profile recompute failed user=%s err=%s",
            user_id, e,
        )
