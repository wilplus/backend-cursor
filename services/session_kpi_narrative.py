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

    Reads the session row (and a handful of its snippets) for
    grounding, calls one LLM with a strict JSON schema, writes the
    result to ``v2_sessions.ai_task_alignment_comment``, returns
    the narrative string.

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

    narrative = _llm_generate_narrative(session, snippets)
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
        "You write a short post-session reflection for a user who "
        "just finished a charisma / stress coaching session. The "
        "reflection ships verbatim into the user's results "
        "dashboard as the top narrative — the radar + heatmap below "
        "it carry the numbers, so you don't need to repeat them.\n"
        "\n"
        "Voice: warm, specific, second-person. Not clinical. Not "
        "motivational fluff. Sound like a trusted coach summarising "
        "what they noticed.\n"
        "\n"
        "Ground EVERY claim in the data the user gives you — quote "
        "specific numbers (\"around 132 WPM\", \"6 fillers across "
        "the session\") and recurring topics directly. Don't invent "
        "moments. If a number is missing, don't fill in a plausible-"
        "sounding one.\n"
        "\n"
        "Output strict JSON with one key: 'narrative'. ONE cohesive "
        "paragraph (3-5 sentences). No bullets, no headers, no line "
        "breaks. End on something forward-looking — what to push on "
        "next."
    )
    user_prompt = _build_user_prompt(session, snippets)

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


def _build_user_prompt(session: dict, snippets: list[dict]) -> str:
    """Serialise just enough of the session to ground the narrative.

    We send numbers (KPI, global metrics) + topic + a thin index of
    the snippets (count, durations) — NOT the full transcripts. The
    LLM doesn't need the prose to write the dashboard prose.
    """
    kpi = session.get("kpi_score")
    g_wpm = session.get("global_wpm")
    g_fillers = session.get("global_fillers")
    g_dyn = session.get("global_dynamic_db")
    g_pitch = session.get("global_pitch_center")
    g_energy = session.get("global_energy")
    top_topic = (session.get("stickiness_top_topic") or "").strip() or None
    sticky_score = session.get("stickiness_score")

    snippet_count = len(snippets)
    stress_count = sum(
        1 for s in snippets
        if (s.get("coach_label") or s.get("snippet_type") or "").lower() == "stress"
    )
    charisma_count = sum(
        1 for s in snippets
        if (s.get("coach_label") or s.get("snippet_type") or "").lower() == "charisma"
    )

    return (
        "SESSION METRICS\n"
        f"  KPI score (0-100):   {kpi if kpi is not None else '—'}\n"
        f"  WPM (session avg):   {g_wpm if g_wpm is not None else '—'}\n"
        f"  Fillers (total):     {g_fillers if g_fillers is not None else '—'}\n"
        f"  Dynamic dB:          {g_dyn if g_dyn is not None else '—'}\n"
        f"  Pitch center (st):   {g_pitch if g_pitch is not None else '—'}\n"
        f"  Energy:              {g_energy if g_energy is not None else '—'}\n"
        f"  Top stickiness:      {top_topic or '—'}"
        + (
            f" (score {float(sticky_score):.2f})" if isinstance(sticky_score, (int, float)) else ""
        )
        + "\n"
        f"  Snippets:            {snippet_count} total "
        f"({charisma_count} charisma, {stress_count} stress)\n"
    )
