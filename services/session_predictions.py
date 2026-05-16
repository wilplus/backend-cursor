"""Session-level admin-comment + next-question pre-generation.

After a session finalizes, this module fires one LLM call that
pre-writes two things the admin would otherwise type from
scratch:

  * ``ai_predicted_session_comment`` — the session-level "what
    would you tell this user overall" message, intended as the
    admin_comment they'd post on Publish.
  * ``ai_predicted_next_question`` — the suggested next coaching
    question to ask this user in their next loop iteration.

Both land on v2_sessions so the admin opens the user-detail page
to a pre-filled draft, accepts or edits, then clicks Publish.
The Publish handler logs the (predicted, final) pair to
admin_annotations_log — that table is the weekly RLHF
fine-tuning dataset.

Why a separate module from session_kpi_narrative
------------------------------------------------
Different audience. kpi_narrative writes user-facing prose into
ai_task_alignment_comment (read by the charisma_profile
dashboard). This module writes ADMIN-facing prose — what a
coach would say to the user — and the LLM is told to address
the user as "you", not narrate about them in third person.

Failure semantics
-----------------
Every failure path swallows + logs and returns ``None``. A
missing prediction just leaves the admin to type the comment +
question themselves (the same UX as before this module existed).
The publish handler still works — it logs the row with
ai_predicted_* = NULL and was_corrected = TRUE.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from services.db import db


logger = logging.getLogger(__name__)


_MODEL = "gpt-4o-mini"
# Comment (~150 tok) + 5 × question (~50 tok) + JSON envelope.
# 800 leaves comfortable headroom; the strict schema enforces
# total length via maxLength on each field.
_MAX_TOKENS = 800


def generate_session_predictions(
    session_id: str,
    *,
    overwrite: bool = False,
) -> Optional[dict[str, Any]]:
    """Generate + persist the admin-facing predictions for ``session_id``.

    Returns ``{comment, question, generated_at}`` on success,
    ``None`` when the session is too sparse to generate from or
    the LLM call failed. ``overwrite=False`` (default) keeps any
    existing predictions — pass True from admin "Regenerate"
    affordances when the underlying metrics have drifted.
    """
    try:
        session = db.v2_get_session_by_id(session_id) or {}
    except Exception as e:
        logger.warning(
            "session_predictions: session load failed sid=%s err=%s",
            session_id, e,
        )
        return None
    if not session:
        return None

    if not overwrite:
        existing_comment = (
            session.get("ai_predicted_session_comment") or ""
        ).strip()
        existing_questions = session.get("ai_predicted_next_questions")
        if existing_comment and isinstance(existing_questions, list) and existing_questions:
            return {
                "comment": existing_comment,
                "questions": existing_questions,
                # Back-compat: surface position-1 as the single
                # field for legacy callers that still read 'question'.
                "question": (existing_questions[0].get("text") if isinstance(existing_questions[0], dict) else None),
                "generated_at": session.get("ai_predictions_generated_at"),
            }

    if not _has_usable_signal(session):
        logger.info(
            "session_predictions: skipping sid=%s — no usable signal",
            session_id,
        )
        return None

    try:
        snippets = db.get_snippets_by_session(session_id) or []
    except Exception as e:
        logger.warning(
            "session_predictions: snippet load failed sid=%s err=%s",
            session_id, e,
        )
        snippets = []

    # Cross-session learner profile so the next-question prediction
    # references the user's broader trajectory rather than just
    # this one session.
    learner_profile: dict = {}
    owner_id = session.get("user_id")
    if owner_id:
        try:
            settings = db.get_user_settings(str(owner_id)) or {}
            learner_profile = settings.get("inferred_learner_profile") or {}
        except Exception:
            pass

    parsed = _llm_generate(session, snippets, learner_profile)
    if parsed is None:
        return None

    comment = (parsed.get("admin_comment") or "").strip()
    raw_questions = parsed.get("next_questions") or []
    questions = _normalize_questions(raw_questions)

    if not comment or not questions:
        logger.warning(
            "session_predictions: empty fields sid=%s comment=%d questions=%d",
            session_id, len(comment), len(questions),
        )
        return None

    # Back-compat single string — position 1's text. Old admin UI
    # still reads ai_predicted_next_question; the array is the
    # new source of truth.
    single_question = questions[0]["text"] if questions else ""

    row = db.set_session_predictions(
        session_id=session_id,
        ai_predicted_session_comment=comment,
        ai_predicted_next_question=single_question,
        ai_predicted_next_questions=questions,
    )
    return {
        "comment": comment,
        "questions": questions,
        "question": single_question,
        "generated_at": (row or {}).get("ai_predictions_generated_at"),
    }


def _normalize_questions(raw: list) -> list[dict]:
    """Clean + cap the LLM's questions array.

    The strict schema in _llm_generate enforces 5 entries with
    {position, text, intent_tag}, but we still defensively:
      - drop entries with empty text
      - reassign positions 1..N if the model emitted gaps
      - cap at 5 even if the model overran (shouldn't happen)
    Returns a list of dicts in position order; empty list when
    nothing usable came back.
    """
    out: list[dict] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        text = (entry.get("text") or "").strip()
        if not text:
            continue
        intent_tag = (entry.get("intent_tag") or "").strip() or None
        out.append({"text": text, "intent_tag": intent_tag})
        if len(out) >= 5:
            break
    # Renumber positions 1..N now that we've dropped any empties.
    return [
        {"position": i + 1, "text": e["text"], "intent_tag": e["intent_tag"]}
        for i, e in enumerate(out)
    ]


# ── Internals ──────────────────────────────────────────────────────


def _has_usable_signal(session: dict) -> bool:
    if session.get("kpi_score") is not None:
        return True
    for k in ("global_wpm", "global_fillers", "global_dynamic_db"):
        if session.get(k) is not None:
            return True
    return False


def _llm_generate(
    session: dict,
    snippets: list[dict],
    learner_profile: dict,
) -> Optional[dict[str, Any]]:
    try:
        from services.openai_service import OpenAIService
        service = OpenAIService()
    except Exception as e:
        logger.warning("session_predictions: openai import failed: %s", e)
        return None
    if not service.client:
        return None

    system = (
        "You are pre-writing admin-facing drafts a coach can accept "
        "or edit before publishing a coaching session to the user. "
        "Two outputs, both addressed TO the user as a coach would "
        "address them — second-person, warm, specific, short:\n"
        "\n"
        "  admin_comment   — the session-level message the user sees "
        "                    on their /chat page when results "
        "                    publish. 2-4 sentences, no fluff. "
        "                    Reflect what actually happened in this "
        "                    session (KPI, top topic, what the "
        "                    recent admin notes have been threading "
        "                    on). Forward-looking; end on what to "
        "                    push on next.\n"
        "\n"
        "  next_questions  — an ordered SCRIPT of EXACTLY 5 "
        "                    questions the admin will use to direct "
        "                    the next coaching conversation with "
        "                    this user. The chat will walk the user "
        "                    through them in order, one per turn.\n"
        "\n"
        "RULES FOR THE 5-QUESTION SCRIPT (these are not negotiable):\n"
        "  • The 5 questions MUST build on each other — they are a "
        "    sequence, not 5 restatements of the same prompt. "
        "    Typical arc: ground emotion → test application → "
        "    rehearse tactic → challenge belief → close loop. "
        "    Pick whichever arc fits THIS user's session.\n"
        "  • Each question stands alone (the user reads one bubble "
        "    at a time) and is ≤ 25 words, direct second-person.\n"
        "  • Each carries a position (1..5) and an intent_tag — a "
        "    short snake_case label for what the question is doing. "
        "    Soft vocabulary; pick from {ground-emotion, "
        "    test-application, rehearse-tactic, challenge-belief, "
        "    close-loop, name-the-pattern, surface-resistance, "
        "    invite-specifics, contrast-before-after, commit-to-"
        "    action} or coin a tighter tag if one fits better.\n"
        "  • DO NOT roleplay or set up scenarios in the questions "
        "    themselves — they are PROMPTS for the user to answer, "
        "    not openings of skits.\n"
        "\n"
        "GENERAL RULES:\n"
        "  • Both fields ground in the data below. Do NOT invent "
        "    moments, scores, or topics the inputs don't show.\n"
        "  • IGNORE the literal subject matter of any diagnostic "
        "    questions (math, trivia, etc.) — those are cognitive-"
        "    load probes, not topics the user 'is good at'.\n"
        "  • The admin will edit if you miss; aim for usable rather "
        "    than perfect.\n"
        "\n"
        "Output strict JSON with keys 'admin_comment' and "
        "'next_questions' (array of exactly 5)."
    )

    user_prompt = _build_user_prompt(session, snippets, learner_profile)

    schema = {
        "name": "session_predictions",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["admin_comment", "next_questions"],
            "properties": {
                "admin_comment": {"type": "string", "maxLength": 700},
                "next_questions": {
                    "type": "array",
                    "minItems": 5,
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["position", "text", "intent_tag"],
                        "properties": {
                            "position": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 5,
                            },
                            "text": {
                                "type": "string",
                                "maxLength": 240,
                            },
                            "intent_tag": {
                                "type": "string",
                                "maxLength": 40,
                            },
                        },
                    },
                },
            },
        },
        "strict": True,
    }

    try:
        response = service.client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=_MAX_TOKENS,
            temperature=0.5,
            response_format={"type": "json_schema", "json_schema": schema},
        )
        raw = (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("session_predictions: llm call failed: %s", e)
        return None

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning(
            "session_predictions: llm output not JSON: %r", raw[:300],
        )
        return None


def _build_user_prompt(
    session: dict,
    snippets: list[dict],
    learner_profile: dict,
) -> str:
    """Compact, deterministic serialisation of the session for the
    LLM. Sections mirror session_kpi_narrative's structure so the
    admin draft + the user-facing narrative agree on the facts."""
    parts: list[str] = []

    # Existing admin coaching observations — the strongest signal
    # for what the coach has actually been telling this user.
    coach_lines: list[str] = []
    for s in snippets:
        c = (s.get("admin_comment") or "").strip()
        if not c:
            continue
        label = (s.get("coach_label") or s.get("snippet_type") or "").lower()
        tag = f"[{label}]" if label in ("stress", "charisma") else ""
        if len(c) > 200:
            c = c[:200].rstrip() + "…"
        coach_lines.append(f"  {tag} {c}".strip())
        if len(coach_lines) >= 6:
            break
    if coach_lines:
        parts.append(
            "EXISTING ADMIN OBSERVATIONS (continuity — your draft "
            "should sound like a continuation of these):\n"
            + "\n".join(coach_lines)
        )

    # Session-level metrics. KPI + global delivery numbers.
    parts.append(
        "SESSION METRICS:\n"
        f"  KPI (0-100):       {session.get('kpi_score') if session.get('kpi_score') is not None else '—'}\n"
        f"  Pace (WPM):        {session.get('global_wpm') if session.get('global_wpm') is not None else '—'}\n"
        f"  Fillers (total):   {session.get('global_fillers') if session.get('global_fillers') is not None else '—'}\n"
        f"  Dynamic dB:        {session.get('global_dynamic_db') if session.get('global_dynamic_db') is not None else '—'}\n"
        f"  Pitch center (st): {session.get('global_pitch_center') if session.get('global_pitch_center') is not None else '—'}\n"
        f"  Stickiness top:    {(session.get('stickiness_top_topic') or '').strip() or '—'}"
    )

    # Cross-session learner profile (high-level, no raw decimals).
    if isinstance(learner_profile, dict) and learner_profile:
        traits = learner_profile.get("traits") or {}
        prof_lines: list[str] = []
        behavioral = (
            (learner_profile.get("behavioral_profile") or "").strip()
            or (traits.get("behavioral_profile") or "").strip()
        )
        if behavioral:
            prof_lines.append(f"  Behavioral profile: {behavioral}")
        trend = traits.get("score_trend") or traits.get("trend")
        if isinstance(trend, str) and trend.strip():
            prof_lines.append(f"  Score trend: {trend.strip()}")
        attempts = (
            traits.get("attempts_analyzed")
            or learner_profile.get("attempts_analyzed")
        )
        if isinstance(attempts, int) and attempts > 0:
            prof_lines.append(f"  Coaching attempts on record: {attempts}")
        if prof_lines:
            parts.append(
                "CROSS-SESSION PROFILE:\n" + "\n".join(prof_lines)
            )

    return "\n\n".join(parts)
