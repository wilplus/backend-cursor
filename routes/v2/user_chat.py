"""The signed-in user's chat-question surface: the multi-turn interview
question machinery + the post-attempt self-rating.

  POST /v2/user/chat/first-question
  POST /v2/user/coaching/self-rating

Moved verbatim out of ``routes/v2_routes.py`` (god-file split, phase 3);
bodies are byte-identical. Routes register on the SAME ``v2_bp`` object, so
endpoint names and the URL map are unchanged.

The services.skills aliases below mirror the ones ``routes/v2_routes.py``
keeps for its own staying callers -- the registry import is shared, the
aliased NAMES are what the moved bodies reference.

Re-exported from ``routes.v2_routes`` for import compatibility.
"""
import logging
import re

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from config import Config
from routes.v2.blueprint import v2_bp
from routes.v2.common import _is_valid_uuid
from services.db import db
from services.rate_limits import llm_limit
from services.skills import (
    get_skill as _get_skill,
    list_skill_ids as _list_skill_ids,
)
from services.snippet_tables import SNIPPETS_TABLE

logger = logging.getLogger(__name__)
config = Config()


_INTERVIEW_QUESTIONS_FALLBACK = {
    "charisma": [
        "Tell us, in your own words: do you think you're a good communicator? Why?",
        "What's something you're genuinely passionate about?",
        "Describe a moment in your life or career that you're really proud of.",
        "If you could teach anyone one thing, what would it be and why?",
        "What's the best piece of advice you've ever received?",
        "What makes you unique compared to other people in your field?",
    ],
    "stress": [
        "What's your biggest professional weakness, and how does it show up day-to-day?",
        "Describe a time you completely failed at something that mattered to you.",
        "If I told you your communication style sometimes puts people off, how would you respond?",
        "Explain a complex topic from your field as if you're talking to a 10-year-old.",
        "What would your harshest critic say about you — and would they be right?",
        "Tell me about a decision you made that you still regret.",
    ],
}

_INTERVIEW_SYSTEM_PROMPT = """You are an interview coach conducting a voice charisma assessment.
Your job is to ask questions that alternate between two tones:

1. CHARISMA-PROVOKING questions: These let the interviewee shine — topics where they can show passion, storytelling ability, warmth, and vocal energy. Examples: achievements, passions, advice they'd give.

2. STRESS-PROVOKING questions: These are challenging, slightly uncomfortable, or technical — designed to test how the person handles pressure, pauses, and uncertainty. Examples: failures, weaknesses, defending a controversial stance.

RULES:
- You MUST alternate tones: if the previous question was charisma, the next MUST be stress, and vice versa.
- Keep questions concise (1-2 sentences max).
- Never repeat a question you've already asked in this session.
- You must dynamically build upon a specific element from the user's most recent answer to challenge them further. DO NOT parrot or awkwardly repeat their words back to them. Push the conversation forward contextually.
- Never break character or explain what you're doing.
- FORMATTING RULE: If you include a brief acknowledgment or validation before your question,
  separate it from the question using the exact delimiter `|||`.
  Example: `That was a vivid story! ||| Now tell me about a time you completely failed at something that mattered to you.`
  If there is no acknowledgment, return ONLY the question text with no delimiter.

LANGUAGE HANDLING — English-only with a one-shot disclaimer:
- You always speak ENGLISH, regardless of the language the user uses. Do NOT mirror, translate into, or switch to the user's language.
- The FIRST time in this conversation that you detect the user has spoken a language other than English (e.g. Polish, Spanish, French, etc.), prepend EXACTLY this disclaimer as the acknowledgment segment before your next question, separated by `|||`:
  "I only speak English, but feel free to continue in your native language! The acoustic analysis will still be completed perfectly."
  Example: `I only speak English, but feel free to continue in your native language! The acoustic analysis will still be completed perfectly. ||| Tell me about a moment when…`
- Inspect the conversation history before issuing this disclaimer. If you have ALREADY issued it once in this session (look for the exact phrase in your prior turns), do NOT repeat it — just continue with your next question in English.
- After the disclaimer fires, immediately continue with your normal coaching agenda (in English).

IDENTITY & PERSONA — graceful pivot, never get stuck:
- If the user asks about your identity, name, whether you're real, human, or an AI (e.g. "Who are you?", "Are you real?", "What is your name?", "Am I talking to a bot?"), respond with a brief, graceful acknowledgment IMMEDIATELY followed by your next coaching question, separated by `|||`.
  Example: `I am your AI coaching chatbot! But let's get back to it... ||| Tell me about the toughest decision you've ever had to defend.`
- Never give a long, robotic AI disclaimer. Never let the conversation get stuck on your identity.
- On repeat identity probes within the same session, shorten the acknowledgment further (or drop it entirely) and pivot straight back to the coaching agenda. You are always in control of the dialogue flow.
"""


# Phase 7 — the registry in services/skills/ is the source of truth
# for which intents the contextual /chat flow accepts. The literal
# {"charisma", "stress"} that used to live here is gone; adding a
# skill is now a package-level change, not a route-level edit.
_CONTEXTUAL_INTENTS = _list_skill_ids()


def _build_few_shot_block(
    *,
    intent: str,
    exclude_snippet_id: str | None = None,
    limit: int = 3,
    viewer_user_id: str | None = None,
) -> str:
    """Render the top-N high-scoring past exchanges as a system-prompt
    preamble for contextual question generation.

    Pulls from db.get_top_followup_examples which returns charisma_snippets
    rows whose follow_up_outcome.score is at least min_score. Each example
    is rendered with four pieces of context:
      - the original user transcript (the moment the coach annotated)
      - the coach's insight
      - the question that was asked
      - the user's actual answer + the evaluator's score

    When ``viewer_user_id`` is provided AND Config.FEW_SHOT_TENANT_SCOPED
    is on, retrieval is scoped to the viewer's company (joined via
    user_settings.company_id) plus any 'canonical' rows. Otherwise the
    legacy cross-tenant retrieval is preserved exactly. Every call
    writes one row to ``few_shot_retrievals`` for compliance + Phase 1
    pool-depth telemetry.

    Returns an empty string when no qualifying examples exist (early
    days of the loop, before enough outcomes have accumulated) — the
    caller is responsible for handling the empty case.

    Example budget: we trim each field to a sane character cap so a
    handful of long transcripts can't blow the context window. The
    examples block typically lands in the 400-1200 char range.
    """
    examples = db.get_top_followup_examples(
        intent,
        limit=limit,
        exclude_snippet_id=exclude_snippet_id,
        viewer_user_id=viewer_user_id,
    )
    if not examples:
        return ""

    def _truncate(s: str | None, cap: int) -> str:
        text = (s or "").strip()
        if not text:
            return ""
        if len(text) <= cap:
            return text
        return text[:cap].rstrip() + "…"

    chunks: list[str] = [
        "Below are examples of past coaching follow-ups that the user "
        "actually engaged with deeply (each scored highly by an automated "
        "evaluator). Study the STYLE of the questions: specific, somatic, "
        "concrete, non-leading. Use the SAME style when you generate the "
        "new question further down."
    ]
    for i, ex in enumerate(examples, start=1):
        outcome = ex.get("follow_up_outcome") or {}
        score_raw = outcome.get("score") if isinstance(outcome, dict) else None
        try:
            score_pct = int(round(float(score_raw) * 100))
        except (TypeError, ValueError):
            score_pct = 0
        question = (
            ex.get("follow_up_question")
            or (outcome.get("question_text") if isinstance(outcome, dict) else None)
            or ""
        )
        user_answer = (
            (outcome.get("user_answer") or {}).get("text")
            if isinstance(outcome, dict)
            else None
        ) or ""
        chunks.append(
            f"\nEXAMPLE {i} (score: {score_pct}/100)\n"
            f"Original moment: \"{_truncate(ex.get('transcript'), 240)}\"\n"
            f"Coach insight:   \"{_truncate(ex.get('admin_comment'), 200)}\"\n"
            f"Question asked:  \"{_truncate(question, 200)}\"\n"
            f"User responded:  \"{_truncate(user_answer, 280)}\""
        )
    return "\n".join(chunks)


def _build_longitudinal_context_block(
    *,
    snippet_id: str | None,
    user_id: str | None,
) -> str | None:
    """Phase 15 — assemble per-user longitudinal context for the
    first-question prompt of a contextual /chat click.

    Returns a multi-section string ready to splice into the system
    prompt, or None when no signal is available for this user.

    Sections (each independently optional):

      [LEARNER PROFILE]              — behavioral_profile + recurring
                                       themes from inferred profile,
                                       layered with any admin override.
      [RECENT REFLECTION]            — current_learner_mirror narrative
                                       (truncated to 600 chars so it
                                       doesn't dominate the prompt).
      [PRIOR ATTEMPTS ON THIS MOMENT]— last 3 coaching_attempts for
                                       this snippet+user, with the
                                       questions previously asked so
                                       the LLM avoids repeating
                                       angles and acknowledges
                                       progress.

    Failure modes swallow + log — a partial block is better than
    blocking the first-question generation. Returns None when ALL
    three sections come back empty (caller falls through to the
    pre-Phase-15 behaviour).
    """
    if not user_id or not snippet_id:
        return None

    sections: list[str] = []
    settings: dict = {}

    # ── Learner profile section removed in the excision (sniper
    # behavioral_profile + learner_profile inferred themes no longer
    # inject). settings still loaded for the sections below. ───────
    try:
        settings = db.get_user_settings(user_id) or {}
    except Exception as e:
        logger.warning(
            "first-question: settings load failed user=%s err=%s",
            user_id, e,
        )

    # ── Recent reflection (mirror) ────────────────────────────────
    try:
        mirror = (settings or db.get_user_settings(user_id) or {}).get(
            "current_learner_mirror"
        ) or {}
        narrative = (mirror.get("narrative") or "").strip() if isinstance(mirror, dict) else ""
        if narrative:
            if len(narrative) > 600:
                narrative = narrative[:600].rstrip() + "…"
            sections.append(f"[RECENT REFLECTION]\n{narrative}")
    except Exception as e:
        logger.warning(
            "first-question: mirror load failed user=%s err=%s",
            user_id, e,
        )

    # ── Prior sessions: archetype + recent admin coaching notes ──
    # Cross-session memory. The infinite-flywheel UX is "each loop
    # is wiser than the last" — the LLM should see what archetype
    # the user landed on in their previous session(s) and what the
    # admin has been telling them, so the new opening question
    # builds on (not repeats) that thread.
    try:
        prior_sessions = (
            db.v2_get_published_sessions_for_user(user_id) or []
        )
        last_session = prior_sessions[0] if prior_sessions else None

        archetype: str | None = None
        if isinstance(last_session, dict):
            cp = last_session.get("charisma_profile") or {}
            if isinstance(cp, dict):
                archetype = (cp.get("archetype") or "").strip() or None

        # Pull the most recent admin coaching notes the user has
        # received across ALL their published snippets. We cap at 3
        # so the LLM has continuity without the prompt ballooning.
        recent_notes: list[str] = []
        try:
            note_rows = (
                db.client.table(SNIPPETS_TABLE)
                .select("admin_comment, created_at, session_id")
                .eq("user_id", user_id)
                .not_.is_("admin_comment", "null")
                .order("created_at", desc=True)
                .limit(8)
                .execute()
                .data
            ) or []
            for r in note_rows:
                # Exclude the snippet the user is currently working
                # on — the parent prompt already has its admin_comment.
                if r.get("session_id") and r.get("session_id") == snippet_id:
                    continue
                note = (r.get("admin_comment") or "").strip()
                if not note:
                    continue
                if len(note) > 180:
                    note = note[:180].rstrip() + "…"
                recent_notes.append(note)
                if len(recent_notes) >= 3:
                    break
        except Exception as note_err:
            logger.warning(
                "first-question: recent admin notes load failed "
                "user=%s err=%s", user_id, note_err,
            )

        if archetype or recent_notes:
            lines = ["[PRIOR SESSIONS]"]
            if archetype:
                lines.append(
                    f"Last session's archetype read: {archetype}. "
                    "Use this as a continuity anchor — acknowledge "
                    "the trajectory, don't restart from zero."
                )
            if recent_notes:
                lines.append(
                    "Recent admin coaching notes (most-recent first):"
                )
                for note in recent_notes:
                    lines.append(f"  • {note}")
                lines.append(
                    "Build on these threads — do NOT repeat advice "
                    "the admin already gave; probe the next layer."
                )
            sections.append("\n".join(lines))
    except Exception as e:
        logger.warning(
            "first-question: prior-sessions load failed user=%s err=%s",
            user_id, e,
        )

    # ── Prior attempts on THIS snippet ────────────────────────────
    try:
        attempts = db.list_coaching_attempts_for_snippet(
            snippet_id, user_id=user_id,
        ) or []
        # list_coaching_attempts_for_snippet returns chronological
        # (attempt_number ASC) — last 3 means the most recent three.
        recent = attempts[-3:] if attempts else []
        question_lines: list[str] = []
        for a in recent:
            q = (a.get("question_text") or "").strip()
            if not q:
                continue
            if len(q) > 200:
                q = q[:200].rstrip() + "…"
            question_lines.append(f"  - {q}")
        if question_lines:
            lines = ["[PRIOR ATTEMPTS ON THIS MOMENT]"]
            lines.append(
                f"The user has already worked through these "
                f"{len(question_lines)} angle(s) on THIS snippet:"
            )
            lines.extend(question_lines)
            lines.append(
                "Open with ONE sentence acknowledging their progress "
                "(\"You've already worked the X angle…\"), then ask a "
                "NEW question that probes a different dimension — "
                "emotion if they covered mechanics, mechanics if they "
                "covered emotion, the people involved if they covered "
                "the situation, etc. DO NOT repeat any prior question's "
                "angle."
            )
            sections.append("\n".join(lines))
    except Exception as e:
        logger.warning(
            "first-question: prior attempts load failed "
            "snippet=%s user=%s err=%s",
            snippet_id, user_id, e,
        )

    if not sections:
        return None
    return "\n\n".join(sections)


def _generate_llm_question(
    *, contextual_init: dict, user_id: str | None = None,
) -> str | None:
    """Generate one question anchored to an exact feedback item.

    Generic interviews, baseline probing, retention loops and unanchored
    profile questions are retired. The caller must supply the recording
    evidence and professional explanation that make this coaching question
    relevant.
    """
    del user_id  # reserved for tenant-scoped observability, never prompt input
    try:
        from services.openai_service import OpenAIService

        intent = str(contextual_init.get("intent") or "").strip().lower()
        transcript = str(contextual_init.get("transcript") or "").strip()
        explanation = str(
            contextual_init.get("admin_comment") or "").strip()
        if intent not in _CONTEXTUAL_INTENTS or not explanation:
            return None

        evidence = (
            f"The exact words were: {transcript!r}."
            if transcript
            else "The exact transcript is unavailable; use only the explanation."
        )
        focus = (
            "what made this delivery feel confident and repeatable"
            if intent == "charisma"
            else "what would make this specific moment feel calmer and clearer"
        )
        prompt = (
            "You are a presentation coach. Ask one concise, supportive question "
            "about one specific recorded feedback item. Do not diagnose the "
            "speaker, infer hidden traits, or start a general interview. "
            f"{evidence} The professional explanation was: {explanation!r}. "
            f"Help the speaker explore {focus}. Return only the question."
        )
        service = OpenAIService()
        if not service.client:
            return None
        response = service.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}],
            max_tokens=100,
            temperature=0.7,
        )
        question = str(response.choices[0].message.content or "").strip()
        return question.strip('"') or None
    except Exception as error:
        logger.warning("contextual coaching question failed: %s", error)
        return None

def _augment_interview_prompt_with_profile(
    base_prompt: str,
    user_id: str,
) -> str:
    """Phase 13 — soft profile injection for the interview-question generator.

    Appends a [COACHING CONTEXT] block with the user's effective
    learner type + admin's global LLM instructions. Adds a stability
    directive telling the model to USE the profile to shape tone
    without becoming locked-in by it ("still probe beyond their
    stated strengths"). Custom instructions remain available as the
    legacy ADDITIONAL INSTRUCTIONS block so the existing wording
    admins typed in keeps applying.

    Failure modes swallow — a missing settings row or DB hiccup
    returns the base prompt unchanged so question generation never
    hard-fails on profile load.
    """
    admin_instructions = ""
    dont_ask_notes = ""
    settings: dict = {}
    try:
        settings = db.get_user_settings(user_id) or {}
        admin_instructions = (
            settings.get("custom_llm_instructions") or ""
        ).strip()
        dont_ask_notes = (
            settings.get("private_admin_notes") or ""
        ).strip()
    except Exception as e:
        logger.warning(
            "interview: settings load failed user=%s: %s", user_id, e,
        )

    # Old-subsystem learner-type (sniper behavioral_profile) injection
    # removed in the excision — willab no longer classifies a learner type.

    # ── Phase 17 — Master Score (B6) block ───────────────────────
    # Pulls the most recent session's persisted kpi_score / global
    # acoustic aggregates and renders them as a tight
    # [PERFORMANCE METRICS] block. Anti-parrot directive can now
    # cite concrete numbers ("your pace landed at 145 wpm, well in
    # band, but your dynamic range came in low") rather than
    # generic shape. Falls silent when no recent session has
    # measurements — protects cold-start users from a misleading
    # "your score" line in the prompt.
    metrics_block: str | None = None
    try:
        metrics_block = _build_master_score_block(user_id)
    except Exception as e:
        logger.warning(
            "interview: master-score block failed user=%s: %s", user_id, e,
        )

    # ── Phase 12.x — private admin notes → don't-ask block ───────
    # Surfaces user_settings.private_admin_notes as a "topics to
    # navigate around" instruction. Same DB read above already
    # pulled the column from the settings dict; render via the
    # shared helper so all four chat surfaces use identical wording.
    from services.utils import render_admin_dont_ask_block
    dont_ask_block = render_admin_dont_ask_block(dont_ask_notes)

    if (
        not admin_instructions
        and not metrics_block and not dont_ask_block
    ):
        return base_prompt

    block_lines = ["", "[COACHING CONTEXT]"]
    if admin_instructions:
        block_lines.append(f"Admin Notes: {admin_instructions}")
    block_lines.append("")
    block_lines.append(
        "Directive: Use this profile to shape your challenge style and "
        "tone, but DO NOT become trapped by it. You must still probe "
        "beyond their stated strengths and test their boundaries under "
        "pressure."
    )

    augmented = base_prompt + "\n" + "\n".join(block_lines)

    if metrics_block:
        augmented += "\n\n" + metrics_block

    # Keep the legacy verbatim block as well — admins relying on the
    # old "ADDITIONAL INSTRUCTIONS FOR THIS USER" wording in their
    # user_settings.custom_llm_instructions content still see it
    # surface unchanged.
    if admin_instructions:
        augmented += (
            "\n\nADDITIONAL INSTRUCTIONS FOR THIS USER:\n"
            f"{admin_instructions}"
        )

    # Don't-ask block goes LAST so it's the final framing the model
    # sees before the user message. Strongest position for negative
    # constraints in practice.
    if dont_ask_block:
        augmented += "\n\n" + dont_ask_block

    return augmented


def _build_master_score_block(user_id: str) -> str | None:
    """Phase 17 — render the user's latest B6 Master Score for the LLM.

    Source: the most recent v2_sessions row that has computed
    metrics. Surfaces kpi_score (B7, the persisted 0..100 score),
    plus the global acoustic averages that fed it, plus the
    stickiness topic (C4) when present.

    Returns None when no recent session has metrics — better to
    omit the block than to print "—" placeholders the LLM would
    parrot back at the user.

    Uses the LATEST session's data on purpose: the next interview
    question is FORWARD-looking from the user's last completed run,
    not their lifetime average. If we ever want a lifetime view, it
    belongs in a separate block (e.g. learner profile).
    """
    if not user_id:
        return None
    try:
        latest = db.v2_get_latest_published_session_for_user(user_id) or {}
    except Exception as e:
        logger.warning(
            "master-score-block: session load failed user=%s: %s", user_id, e,
        )
        return None
    if not latest:
        return None

    kpi = latest.get("kpi_score")
    g_wpm = latest.get("global_wpm")
    g_fillers = latest.get("global_fillers")
    g_dynamic = latest.get("global_dynamic_db")
    g_pitch = latest.get("global_pitch_center")
    g_pause = latest.get("global_pause_ms")
    sticky_topic = (latest.get("stickiness_top_topic") or "").strip() or None

    # Nothing measurable on the latest session — bail rather than
    # render a hollow block.
    if all(v is None for v in (kpi, g_wpm, g_fillers, g_dynamic, g_pitch, g_pause)):
        return None

    lines: list[str] = [
        "[PERFORMANCE METRICS — from this user's most recent session]"
    ]
    if isinstance(kpi, (int, float)):
        lines.append(f"Master score (KPI, 0-100): {round(float(kpi), 1)}")
    if isinstance(g_wpm, (int, float)):
        lines.append(f"Pace: {round(float(g_wpm), 1)} WPM (target band 120-160)")
    if isinstance(g_fillers, (int, float)):
        lines.append(f"Fillers across session: {int(g_fillers)}")
    if isinstance(g_dynamic, (int, float)):
        lines.append(f"Dynamic range: {round(float(g_dynamic), 1)} dB")
    if isinstance(g_pitch, (int, float)):
        lines.append(f"Pitch centre: {round(float(g_pitch), 1)} st")
    if isinstance(g_pause, (int, float)):
        lines.append(f"Average pause: {round(float(g_pause), 0)} ms")
    if sticky_topic:
        lines.append(f"Sticky topic last session: {sticky_topic}")
    lines.append("")
    lines.append(
        "Directive: cite ONE specific metric above when it would "
        "ground your question — e.g. \"your pace ran at 175 WPM in "
        "the last session, so this time...\". Do NOT recite the "
        "whole block; pick the most coachable number for THIS turn."
    )
    return "\n".join(lines)


def _feedback_transcript(snippet: dict) -> str:
    """Read the exact text evidence through the legacy schema adapter."""
    for key in (
        "transcript", "transcription_text", "transcript_text",
        "transcript_excerpt",
    ):
        value = str(snippet.get(key) or "").strip()
        if value:
            return value
    return ""


def _contextual_question_response(
    *, user_id: str, source_id: str, intent: str,
) -> tuple[dict, int]:
    if not _is_valid_uuid(source_id):
        return {"code": "INVALID_INPUT", "error": "Invalid feedback item"}, 400
    if intent not in _CONTEXTUAL_INTENTS:
        return {"code": "INVALID_INPUT", "error": "Unsupported intent"}, 400

    snippet = db.v2_get_charisma_snippet_for_user(source_id, user_id)
    if not snippet:
        return {"code": "NOT_FOUND", "error": "Feedback item not found"}, 404

    stored = str(snippet.get("follow_up_question") or "").strip()
    if stored:
        return {
            "status": "ok", "question": stored,
            "source": "stored_feedback_follow_up",
        }, 200

    explanation = str(snippet.get("admin_comment") or "").strip()
    if not explanation:
        return {
            "code": "FEEDBACK_CONTEXT_UNAVAILABLE",
            "error": "The feedback explanation is not available yet",
        }, 422

    question = _generate_llm_question(
        contextual_init={
            "intent": intent,
            "transcript": _feedback_transcript(snippet),
            "admin_comment": explanation,
            "source_snippet_id": source_id,
        },
        user_id=user_id,
    )
    skill = _get_skill(intent)
    question = question or (skill.contextual_first_question if skill else None)
    if not question:
        return {
            "code": "QUESTION_GENERATION_FAILED",
            "error": "Failed to prepare a contextual question",
        }, 503
    return {"status": "ok", "question": question, "source": "generated"}, 200


@v2_bp.route("/user/chat/first-question", methods=["POST"])
@llm_limit
@require_auth
def v2_user_chat_first_question():
    """Start a contextual chat by generating the first AI question.

    Query params (any one spelling accepted, see comment below):
      - sourceSnippetId / sourceSnippet / source_snippet_id  (UUID)
      - intent: charisma|stress
    """
    try:
        user_id = request.user_id
        # Defensive param read: the frontend /chat page URL has used
        # `sourceSnippet` while the backend canonical name is
        # `sourceSnippetId`. A mismatch causes the contextual init
        # to silently fall through to the cold-start interview path
        # ("Are you good at math?"). Accept all three spellings so a
        # one-side-only deploy can never reintroduce that bug —
        # whichever key the BFF forwards, we resolve it.
        source_snippet_id = (
            request.args.get("sourceSnippetId")
            or request.args.get("sourceSnippet")
            or request.args.get("source_snippet_id")
            or ""
        ).strip() or None
        intent = (request.args.get("intent") or "").strip().lower() or None
        if not (source_snippet_id and intent):
            return jsonify({
                "code": "FEEDBACK_CONTEXT_REQUIRED",
                "error": "sourceSnippetId and intent must be provided together",
            }), 400

        # ── Admin overrides (priority order) ────────────────────────
        # 1) coaching_directives_queue — new user-level 5-step arc.
        #    Pop the lowest-position un-exhausted row, mark exhausted.
        #    Wins over contextual snippet flow, stored follow-up, and
        #    the dynamic LLM. Phase Directives-Queue (BE).
        #
        # Legacy queued_override_question (single-question override
        # via PUT /v2/admin/user/<id>/context) was removed in the
        # Week-1 cleanup. The directives-queue is the single admin
        # override path now. Old data in user_settings.queued_
        # override_question persists in the DB but is ignored.
        # ── 2) Task 10 — next-session icebreaker (soft-queue read).
        # Cold-start path only: if a sourceSnippet/intent is provided
        # the user came in via the snippet-deep-dive CTA, not a fresh
        # session opener, and the icebreaker should be saved for a
        # true new-session entry. Marks the source row 'delivered'
        # atomically with the read (mirrors pop_next_directive's
        # mark-exhausted pattern).
        #
        # Priority slot: AFTER directives_queue (admin always wins),
        # BEFORE contextual_init / dynamic LLM.
        payload, status = _contextual_question_response(
            user_id=user_id,
            source_id=source_snippet_id,
            intent=intent,
        )
        return jsonify(payload), status

    except Exception as e:
        logger.error("user/chat/first-question failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to generate first question"}), 500


_SELF_RATING_RE = re.compile(
    r"\b(10|[1-9]|one|two|three|four|five|six|seven|eight|nine|ten)\b",
    re.IGNORECASE,
)
_SELF_RATING_WORD_MAP: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
# Phase 8 self-rating: bound the free-text payload so an abusive
# client can't ship megabytes through the endpoint. The frontend
# input is the chat composer (typically <200 chars).
_SELF_RATING_TEXT_MAX = 500


def _parse_self_rating_from_text(text: str) -> int | None:
    """Pull a 1..10 integer out of a free-form user reply.

    Accepts digits ("8", "10") and English number words ("eight",
    "ten") case-insensitively. Returns the FIRST 1-10 number found,
    or None when nothing matches.

    Examples:
      "8"              → 8
      "I'd say 8"      → 8
      "9/10"           → 9
      "eight"          → 8
      "TEN"            → 10
      "8 out of 10"    → 8
      "11"             → None (digit out of range; word_boundary kills it)
      "ten and a half" → 10
      ""               → None
    """
    if not text:
        return None
    m = _SELF_RATING_RE.search(text)
    if not m:
        return None
    token = m.group(1).strip().lower()
    if token in _SELF_RATING_WORD_MAP:
        return _SELF_RATING_WORD_MAP[token]
    try:
        n = int(token)
        return n if 1 <= n <= 10 else None
    except (TypeError, ValueError):
        return None


def _first_self_rating(attempts: list[dict]) -> int | None:
    """First chronological self-rating present in ``attempts``.

    Used by /coaching/progress to show first → best progression.
    Attempts are already ordered by attempt_number ASC when the
    progress endpoint builds them.
    """
    for a in attempts:
        r = a.get("self_rating")
        if isinstance(r, int) and 1 <= r <= 10:
            return r
    return None


def _best_self_rating(attempts: list[dict]) -> int | None:
    """Highest self-rating across ``attempts``. None when no attempt has one."""
    ratings = [
        a.get("self_rating") for a in attempts
        if isinstance(a.get("self_rating"), int)
        and 1 <= a.get("self_rating") <= 10
    ]
    return max(ratings) if ratings else None


@v2_bp.route("/user/coaching/self-rating", methods=["POST"])
@llm_limit
@require_auth
def v2_user_coaching_self_rating():
    """Capture the user's in-chat 1..10 self-rating for a coaching attempt.

    Phase 8 of the snippet-CTA learning loop. After the LLM evaluation
    lands in coaching_attempts (Phase 2), the frontend asks the user
    "on a scale of 1-10, how do you feel about that response?" inside
    the chat thread and POSTs the reply here.

    Body (any of these shapes works; ``rating`` wins when both are set)::

        { "snippet_id": "<uuid>", "rating": 8 }
        { "snippet_id": "<uuid>", "rating_text": "I'd say 8" }
        { "snippet_id": "<uuid>", "rating_text": "8", "attempt_number": 3 }

    ``attempt_number`` is optional — when omitted we target the most
    recent attempt for this (snippet, user). That is the common path
    because the rating ask follows the latest evaluation in the chat.

    Status codes:
      200 — rating accepted; response carries the persisted row.
      400 — input invalid (missing snippet_id, can't parse a 1..10).
      404 — snippet not owned by the requesting user.
      425 — no coaching_attempts row exists yet (race with the
            evaluation daemon). Client should retry after a beat.
      500 — unexpected error.
    """
    try:
        user_id = request.user_id
        body = request.get_json(silent=True) or {}

        snippet_id = (body.get("snippet_id") or "").strip()
        if not snippet_id or not _is_valid_uuid(snippet_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "snippet_id must be a valid UUID",
            }), 400

        attempt_number = body.get("attempt_number")
        if attempt_number is not None:
            try:
                attempt_number = int(attempt_number)
                if attempt_number < 1:
                    raise ValueError
            except (TypeError, ValueError):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "attempt_number must be a positive integer",
                }), 400

        rating_text_raw = (body.get("rating_text") or "")
        if not isinstance(rating_text_raw, str):
            rating_text_raw = str(rating_text_raw)
        rating_text = rating_text_raw[:_SELF_RATING_TEXT_MAX].strip() or None

        # rating wins when both shapes are sent — it's the explicit
        # numeric path the frontend uses when it already parsed the
        # number client-side.
        rating_val = body.get("rating")
        rating: int | None = None
        if rating_val is not None:
            try:
                rating = int(rating_val)
            except (TypeError, ValueError):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "rating must be an integer 1..10",
                }), 400
        elif rating_text:
            rating = _parse_self_rating_from_text(rating_text)

        if rating is None or not (1 <= rating <= 10):
            return jsonify({
                "code": "RATING_UNPARSEABLE",
                "error": "Could not read a number from 1 to 10 in the reply",
            }), 400

        # Owner check — block users from rating someone else's snippet.
        snippet = db.v2_get_charisma_snippet_for_user(snippet_id, user_id)
        if not snippet:
            return jsonify({
                "code": "NOT_FOUND",
                "error": "Snippet not found",
            }), 404

        updated = db.update_coaching_attempt_self_rating(
            snippet_id=snippet_id,
            user_id=user_id,
            rating=rating,
            rating_text=rating_text,
            attempt_number=attempt_number,
        )
        if not updated:
            # No row found for (snippet, user[, attempt_number]).
            # Most likely cause: the eval daemon hasn't finished
            # writing the coaching_attempts row yet. 425 (Too Early)
            # tells the client to retry shortly.
            return jsonify({
                "code": "ATTEMPT_NOT_READY",
                "error": (
                    "No coaching attempt found for this snippet yet. "
                    "Wait a moment and retry."
                ),
            }), 425

        return jsonify({
            "status": "ok",
            "snippet_id": snippet_id,
            "attempt_number": updated.get("attempt_number"),
            "self_rating": updated.get("self_rating"),
            "self_rating_text": updated.get("self_rating_text"),
            "self_rating_submitted_at": updated.get("self_rating_submitted_at"),
        }), 200

    except Exception as e:
        logger.error("user/coaching/self-rating failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to save self-rating",
        }), 500
