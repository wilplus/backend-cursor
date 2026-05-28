"""LLM-generated post-session narrative for the KPI panel.

Writes a short, coach-toned paragraph to ``v2_sessions.ai_task_
alignment_comment`` based on the deterministic session-level
metrics (KPI score, global_wpm, global_fillers, top stickiness
topic, snippet count). The charisma_profile dashboard reads this
column as its top-level ``narrative`` field — keeping the LLM
output here (one place, one call per finalize) means the dashboard
narrative stays coherent across the radar + heatmap + cards.

Why this lives alone (not inside charisma_profile)
--------------------------------------------------
charisma_profile builds a structural payload (numbers + labels)
that should remain LLM-free for cheap previews / tests. The
narrative is the ONE block where prose lives — splitting it out
makes the compute graph cleaner:

    finalize_session_pending_admin_review
      ├─ compute_session_global_metrics  (deterministic)
      ├─ generate_session_kpi_narrative  (this module — LLM)
      └─ build_charisma_profile          (reads narrative + numbers)

Failure semantics
-----------------
Every failure path swallows + logs. No narrative is far better
than a broken finalize. If the LLM is down, ``ai_task_alignment_
comment`` stays empty and the charisma_profile narrative falls
back to the cached learner-mirror narrative, then to the spec
"Your acoustic baseline has been captured" line — the dashboard
never renders blank.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from services.db import db


logger = logging.getLogger(__name__)


_MODEL = "gpt-4o-mini"
_MAX_TOKENS = 400


def generate_session_kpi_narrative(
    session_id: str,
    *,
    overwrite: bool = False,
) -> str | None:
    """Generate + persist a coach-toned narrative for ``session_id``.

    Reads the session row, its snippets (for admin_comment context),
    and the owner's learner_profile (for cross-session traits), then
    calls one LLM with a strict JSON schema. Writes the result to
    ``v2_sessions.ai_task_alignment_comment`` and returns the
    narrative string.

    ``overwrite=False`` (default) — if the column is already
    populated we leave it alone. Useful from finalize paths that
    run more than once (admin clicks Compute Metrics again after
    publish). Pass ``overwrite=True`` to force a fresh write.

    Returns ``None`` when:
      - the session has no usable signal (no KPI, no global metrics)
      - the LLM call fails or returns unparseable JSON
      - the DB write fails

    A None return is a feature: the charisma_profile narrative
    falls back gracefully, and the admin can re-trigger from the
    compute-metrics endpoint when the underlying issue is fixed.
    """
    try:
        session = db.v2_get_session_by_id(session_id) or {}
    except Exception as e:
        logger.warning(
            "kpi_narrative: session load failed sid=%s err=%s",
            session_id, e,
        )
        return None
    if not session:
        return None

    existing = (session.get("ai_task_alignment_comment") or "").strip()
    if existing and not overwrite:
        return existing

    if not _has_usable_signal(session):
        logger.info(
            "kpi_narrative: skipping sid=%s — no usable signal",
            session_id,
        )
        return None

    try:
        snippets = db.get_snippets_by_session(session_id) or []
    except Exception as e:
        logger.warning(
            "kpi_narrative: snippet load failed sid=%s err=%s",
            session_id, e,
        )
        snippets = []

    # Cross-session traits the prompt grounds in. user_id is on the
    # session row; we fail closed (empty profile) when the lookup
    # misses, since the narrative should never block on it.
    learner_profile: dict = {}
    owner_id = session.get("user_id")
    if owner_id:
        try:
            settings = db.get_user_settings(str(owner_id)) or {}
            learner_profile = settings.get("inferred_learner_profile") or {}
        except Exception as e:
            logger.warning(
                "kpi_narrative: learner profile load failed sid=%s err=%s",
                session_id, e,
            )

    narrative = _llm_generate_narrative(session, snippets, learner_profile)
    if not narrative:
        return None

    try:
        # ai_task_alignment_score is the legacy 0..100 KPI snapshot;
        # write the current value alongside so the column pair stays
        # consistent. update_session_ai_alignment writes both atomically.
        kpi = session.get("kpi_score")
        kpi_float = float(kpi) if isinstance(kpi, (int, float)) else None
        db.update_session_ai_alignment(
            session_id=session_id,
            score=kpi_float,
            comment=narrative,
        )
    except Exception as e:
        logger.warning(
            "kpi_narrative: persist failed sid=%s err=%s",
            session_id, e,
        )
        # Caller still gets the narrative — the route can choose to
        # return it even if persist failed.

    # Phase 18.x — pin the immutable AI-draft baseline so the
    # trivial-edit gate on PATCH /v2/admin/sessions/<id>/kpi-
    # narrative has something to diff against. Same value as the
    # editable column at generation time; admin edits only touch
    # the editable column going forward. On Compute Metrics
    # re-runs (overwrite=True), the LLM regenerates BOTH columns
    # so a fresh narrative becomes the new baseline and any earlier
    # admin edit on the OLD narrative is gone (intentional —
    # documented in the PATCH endpoint's docstring).
    try:
        db.set_session_kpi_narrative_ai_draft(
            session_id=session_id,
            ai_draft=narrative,
        )
    except Exception as e:
        logger.warning(
            "kpi_narrative: ai_draft pin failed sid=%s err=%s",
            session_id, e,
        )
        # Don't block — the editable copy is already persisted
        # above and the gate's empty-baseline bypass means the
        # admin can still save (just without the gate firing).

    return narrative


# ── Internals ──────────────────────────────────────────────────────


def _has_usable_signal(session: dict) -> bool:
    """At least one acoustic input must be present — otherwise the
    LLM is guessing. KPI is sufficient; failing that, any of the
    global_* averages."""
    if session.get("kpi_score") is not None:
        return True
    for k in ("global_wpm", "global_fillers", "global_dynamic_db"):
        if session.get(k) is not None:
            return True
    return False


def _llm_generate_narrative(
    session: dict,
    snippets: list[dict],
    learner_profile: dict,
) -> str | None:
    try:
        from services.openai_service import OpenAIService
        service = OpenAIService()
    except Exception as e:
        logger.warning("kpi_narrative: openai import failed: %s", e)
        return None
    if not service.client:
        return None

    system = (
        "You write a short post-session reflection that ships verbatim "
        "into the user's results dashboard as the top narrative. The "
        "radar + heatmap + scores below it carry the raw numbers, so "
        "you don't need to recite them — your job is to describe "
        "HOW the user shows up, not WHAT they answered.\n"
        "\n"
        "Voice: warm, specific, second-person. Not clinical. Not "
        "motivational fluff. Sound like a trusted coach summarising "
        "what they noticed.\n"
        "\n"
        "CRITICAL — IGNORE THE LITERAL SUBJECT MATTER OF THE "
        "DIAGNOSTIC QUESTIONS (math problems, trivia, facts, etc.). "
        "Those questions are cognitive-load probes, NOT topics the "
        "user 'is good at'. Do NOT say 'you handled the math well' "
        "or 'you stayed on the trivia topic'. The literal content of "
        "the questions is irrelevant to the charisma read.\n"
        "\n"
        "REDEFINE 'STICKINESS' for this narrative: stickiness is a "
        "MENTAL FOCUS / PRESENCE UNDER PRESSURE signal — the user's "
        "ability to hold a clear train of thought when their working "
        "memory is taxed. Talk about it as composure, focus, "
        "presence. Never name the topic stickiness was measured on.\n"
        "\n"
        "PRIMARY SOURCES OF TRUTH (in order):\n"
        "  1. Admin coaching comments (what a human coach has flagged "
        "     on this user's snippets — these are the most signal-"
        "     dense observations available).\n"
        "  2. Acoustic delivery metrics: Pace (WPM), Flow (fillers "
        "     per minute), Pitch (semitone range), Dynamic dB, Energy.\n"
        "  3. Cross-session learner profile (behavioral profile, "
        "     recurring patterns, score-per-component aggregates).\n"
        "\n"
        "Base the narrative on HOW they speak and what the coach has "
        "observed — NOT what factual questions they answered. Numbers "
        "are background grounding; the coach's words are the "
        "foreground.\n"
        "\n"
        "EXAMPLES of the bar to hit:\n"
        "\n"
        "  BAD (do NOT do this):\n"
        "    \"You answered the math questions quickly and stayed on "
        "    the topic of calculations well, showing great "
        "    stickiness.\"\n"
        "\n"
        "  GOOD (this is the vibe):\n"
        "    \"You have an authoritative presence. Under cognitive "
        "    pressure, your mental focus remains unbroken and your "
        "    pace is steady, though your coach noted a slight drop "
        "    in vocal warmth. You project confidence even when "
        "    challenged.\"\n"
        "\n"
        "Output strict JSON with one key: 'narrative'. ONE cohesive "
        "paragraph (3-5 sentences). No bullets, no headers, no line "
        "breaks, no enumeration of question topics. End on something "
        "forward-looking — what to push on next."
    )
    user_prompt = _build_user_prompt(session, snippets, learner_profile)

    schema = {
        "name": "session_kpi_narrative",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["narrative"],
            "properties": {
                "narrative": {"type": "string", "maxLength": 900},
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
            temperature=0.6,
            response_format={"type": "json_schema", "json_schema": schema},
        )
        raw = (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("kpi_narrative: llm call failed: %s", e)
        return None

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning(
            "kpi_narrative: llm output not JSON: %r", raw[:300],
        )
        return None

    narrative = str(parsed.get("narrative") or "").strip()
    return narrative or None


def _build_user_prompt(
    session: dict,
    snippets: list[dict],
    learner_profile: dict,
) -> str:
    """Serialise just enough of the session to ground the narrative.

    Sections in priority order (matches the system prompt's ranking
    of sources of truth):

      1. ADMIN COACHING COMMENTS — the human coach's observations on
         this session's snippets. PRIMARY truth for the narrative.
      2. LEARNER PROFILE — cross-session traits (behavioral profile,
         recurring patterns, component score aggregates).
      3. ACOUSTIC DELIVERY — Pace, Flow, Pitch, dB, Energy.
      4. STICKINESS DIAGNOSTIC — score only, NO topic. The topic of
         the cognitive-load probe is excluded by design so the LLM
         can't anchor on it.

    The full transcripts are NOT sent — the LLM doesn't need the
    prose to write dashboard prose, and including them would risk
    the model latching onto the question's literal subject matter.
    """
    parts: list[str] = []

    # ── 1. Admin coaching comments (PRIMARY) ────────────────────
    coach_lines: list[str] = []
    for s in snippets:
        comment = (s.get("admin_comment") or "").strip()
        if not comment:
            continue
        label = (s.get("coach_label") or s.get("snippet_type") or "").lower()
        tag = f"[{label}]" if label in ("stress", "charisma") else ""
        # Trim each comment so a chatty admin doesn't blow the prompt;
        # 240 chars is enough to carry the observation.
        if len(comment) > 240:
            comment = comment[:240].rstrip() + "…"
        coach_lines.append(f"  {tag} {comment}".strip())
        if len(coach_lines) >= 8:  # cap to keep the prompt bounded
            break
    if coach_lines:
        parts.append(
            "ADMIN COACHING COMMENTS (primary source — base the "
            "narrative on what the coach saw):\n" + "\n".join(coach_lines)
        )
    else:
        parts.append(
            "ADMIN COACHING COMMENTS: (none yet — fall back to "
            "acoustic delivery + learner profile)"
        )

    # ── 2. Learner profile (cross-session) ──────────────────────
    profile_lines = _learner_profile_lines(learner_profile)
    if profile_lines:
        parts.append("LEARNER PROFILE:\n" + "\n".join(profile_lines))

    # ── 3. Acoustic delivery (Pace / Flow / Pitch / dB / Energy) ─
    kpi = session.get("kpi_score")
    g_wpm = session.get("global_wpm")
    g_fillers = session.get("global_fillers")
    g_dyn = session.get("global_dynamic_db")
    g_pitch = session.get("global_pitch_center")
    g_energy = session.get("global_energy")

    parts.append(
        "ACOUSTIC DELIVERY (how they speak — secondary source):\n"
        f"  Pace (WPM):          {g_wpm if g_wpm is not None else '—'}\n"
        f"  Flow (total fillers):{g_fillers if g_fillers is not None else '—'}\n"
        f"  Dynamic dB:          {g_dyn if g_dyn is not None else '—'}\n"
        f"  Pitch center (st):   {g_pitch if g_pitch is not None else '—'}\n"
        f"  Energy:              {g_energy if g_energy is not None else '—'}\n"
        f"  Overall KPI (0-100): {kpi if kpi is not None else '—'}"
    )

    # ── 4. Stickiness as diagnostic ONLY — no topic ─────────────
    # We deliberately omit stickiness_top_topic. The system prompt
    # tells the LLM to treat stickiness as mental focus / presence
    # under pressure; sending the topic name here would directly
    # contradict that and tempt the model to leak it into prose.
    sticky_score = session.get("stickiness_score")
    if isinstance(sticky_score, (int, float)):
        parts.append(
            "MENTAL FOCUS / PRESENCE (stickiness diagnostic — score "
            "only, DO NOT mention the underlying question topic):\n"
            f"  Stickiness score (0-1): {float(sticky_score):.2f}"
        )

    # ── Snippet shape (for context, no transcripts) ─────────────
    snippet_count = len(snippets)
    stress_count = sum(
        1 for s in snippets
        if (s.get("coach_label") or s.get("snippet_type") or "").lower() == "stress"
    )
    charisma_count = sum(
        1 for s in snippets
        if (s.get("coach_label") or s.get("snippet_type") or "").lower() == "charisma"
    )
    parts.append(
        "SESSION SHAPE:\n"
        f"  Snippets: {snippet_count} total "
        f"({charisma_count} charisma, {stress_count} stress)"
    )

    return "\n\n".join(parts)


def _learner_profile_lines(learner_profile: dict) -> list[str]:
    """Pull a few high-signal traits from the cross-session profile.

    We deliberately stay terse — the system prompt is doing the
    heavy lift, and the profile is "background colour" the LLM
    should weave in only where it lands. Recurring entities are
    explicitly excluded: those are the SAME literal topics we
    want the narrative to ignore.
    """
    if not isinstance(learner_profile, dict) or not learner_profile:
        return []
    lines: list[str] = []
    traits = learner_profile.get("traits") or {}
    if not isinstance(traits, dict):
        return []

    behavioral = (
        (learner_profile.get("behavioral_profile") or "").strip()
        or (traits.get("behavioral_profile") or "").strip()
    )
    if behavioral:
        lines.append(f"  Behavioral profile: {behavioral}")

    components = traits.get("score_per_component") or {}
    if isinstance(components, dict) and components:
        bits = []
        for key in ("engagement", "emotional_movement", "specificity", "stickiness"):
            v = components.get(key)
            if isinstance(v, (int, float)):
                bits.append(f"{key}={float(v):.2f}")
        if bits:
            lines.append("  Component averages: " + ", ".join(bits))

    score_trend = traits.get("score_trend") or traits.get("trend")
    if isinstance(score_trend, str) and score_trend.strip():
        lines.append(f"  Score trend: {score_trend.strip()}")

    attempts = traits.get("attempts_analyzed") or learner_profile.get("attempts_analyzed")
    if isinstance(attempts, int) and attempts > 0:
        lines.append(f"  Coaching attempts on record: {attempts}")

    return lines
