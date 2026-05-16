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
_MAX_TOKENS = 500


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
        existing_question = (
            session.get("ai_predicted_next_question") or ""
        ).strip()
        if existing_comment and existing_question:
            return {
                "comment": existing_comment,
                "question": existing_question,
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
    question = (parsed.get("next_question") or "").strip()
    if not comment or not question:
        logger.warning(
            "session_predictions: empty fields sid=%s comment=%d question=%d",
            session_id, len(comment), len(question),
        )
        return None

    row = db.set_session_predictions(
        session_id=session_id,
        ai_predicted_session_comment=comment,
        ai_predicted_next_question=question,
    )
    return {
        "comment": comment,
        "question": question,
        "generated_at": (row or {}).get("ai_predictions_generated_at"),
    }


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
        "  admin_comment  — the session-level message the user sees "
        "                   on their /chat page when results "
        "                   publish. 2-4 sentences, no fluff. Reflect "
        "                   what actually happened in this session "
        "                   (KPI, top topic, what the recent admin "
        "                   notes have been threading on). Forward-"
        "                   looking; end on what to push on next.\n"
        "\n"
        "  next_question  — ONE question to open the user's next "
        "                   coaching loop with. Builds on what they "
        "                   did this session — probes the next layer, "
        "                   not the same angle they already worked. "
        "                   Direct second-person, ≤ 25 words.\n"
        "\n"
        "Rules:\n"
        "  • Both fields ground in the data below. Do NOT invent "
        "    moments, scores, or topics the inputs don't show.\n"
        "  • IGNORE the literal subject matter of any diagnostic "
        "    questions (math, trivia, etc.) — those are cognitive-"
        "    load probes, not topics the user 'is good at'.\n"
        "  • The admin will edit if you miss; aim for usable rather "
        "    than perfect.\n"
        "\n"
        "Output strict JSON with keys 'admin_comment' and "
        "'next_question'. No other keys."
    )

    user_prompt = _build_user_prompt(session, snippets, learner_profile)

    schema = {
        "name": "session_predictions",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["admin_comment", "next_question"],
            "properties": {
                "admin_comment": {"type": "string", "maxLength": 700},
                "next_question": {"type": "string", "maxLength": 240},
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
