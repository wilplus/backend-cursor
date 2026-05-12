"""On-demand learner mirror — Phase 6 of the snippet-CTA learning loop.

Problem
-------
Phases 2-4 give us per-attempt data and a deterministic learner
profile, but a user looking at /results can't easily read the JSON
and answer "is the coaching working for me?". The data is there;
the narrative isn't.

The mirror is the user-facing reflection on top of that data. It
runs ONCE per user click — there is no scheduler, no auto-
regenerate, and v1 stores a single current mirror per user
(replacing on regenerate). When the user has barely used the
system the mirror won't generate; it needs an analysable sample
of attempts to be honest, otherwise it'd hallucinate a journey.

Why on-demand
-------------
- User intent matters: "show me what you're noticing" is itself a
  reflection moment, and rendering a fresh mirror unprompted on
  every /results visit would dilute that.
- Cost: each generation is one LLM call (~600 tokens). User-
  triggered keeps it predictable.
- Honesty: a profile blob with 3 attempts can support deterministic
  traits ("specificity averaging 0.5") but not honest narrative.
  We gate generation on a sample-size threshold and return a
  diagnostic NOT_ENOUGH_DATA code below it.

Failure semantics
-----------------
Every failure mode (LLM down, profile missing, sample too small)
returns None or a structured error code — the caller (the route
handler) maps to the appropriate HTTP status. We never crash the
user's regenerate click and we never overwrite an existing good
mirror with a degraded one.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from services.db import db


logger = logging.getLogger(__name__)


# Minimum analysed attempts before we'll generate a mirror. Below
# this the narrative would be guessing — the deterministic profile
# also won't have a meaningful trend signal yet.
MIN_ATTEMPTS_TO_GENERATE = 3

# LLM call budget. The schema constrains output to ~1200 chars of
# narrative + small headline + few observations; 900 tokens leaves
# room for the model to think without blowing cost.
_MAX_TOKENS = 900

# Used as the mirror's own version tag (the schema version is
# tracked in llm_schemas.LEARNER_MIRROR_SCHEMA).
_MIRROR_VERSION = "v1"


def generate_learner_mirror(user_id: str) -> tuple[dict[str, Any] | None, str | None]:
    """Generate + persist a fresh mirror for ``user_id``.

    Returns ``(mirror_dict, None)`` on success, or
    ``(None, error_code)`` on failure where ``error_code`` is one of:
      - 'NOT_ENOUGH_DATA' — the user has fewer than
        MIN_ATTEMPTS_TO_GENERATE analysable attempts.
      - 'PROFILE_MISSING' — the inferred profile column is empty;
        the user has never had a coaching attempt persist.
      - 'LLM_UNAVAILABLE' — OpenAI client not configured.
      - 'LLM_ERROR' — the API call threw or returned unparseable.
      - 'PERSIST_FAILED' — generation succeeded but the upsert
        didn't land (PGRST204 from a missing column, Supabase down).
    """
    settings = _load_settings(user_id)
    if settings is None:
        return None, "PROFILE_MISSING"

    profile = settings.get("inferred_learner_profile") or None
    if not isinstance(profile, dict):
        return None, "PROFILE_MISSING"
    attempts_analyzed = int(profile.get("attempts_analyzed") or 0)
    if attempts_analyzed < MIN_ATTEMPTS_TO_GENERATE:
        return None, "NOT_ENOUGH_DATA"

    # Recent attempts give the LLM concrete material to reference.
    # We use the same window the aggregator already pulled, so the
    # narrative can't reference an attempt the profile didn't see.
    attempts = db.list_recent_coaching_attempts_for_user(
        user_id, limit=10,
    )

    try:
        from services.openai_service import OpenAIService
        service = OpenAIService()
    except Exception as e:
        logger.warning("mirror: openai_service import failed: %s", e)
        return None, "LLM_UNAVAILABLE"
    if not service.client:
        return None, "LLM_UNAVAILABLE"

    from services.llm_schemas import LEARNER_MIRROR_SCHEMA, response_format

    system = _build_system_prompt()
    user_prompt = _build_user_prompt(profile, attempts)

    try:
        response = service.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=_MAX_TOKENS,
            temperature=0.6,
            response_format=response_format(LEARNER_MIRROR_SCHEMA),
        )
        raw = (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("mirror: openai call failed user=%s err=%s", user_id, e)
        return None, "LLM_ERROR"

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("mirror: structured output not parseable: %r", raw[:400])
        return None, "LLM_ERROR"

    headline = str(parsed.get("headline") or "").strip()
    narrative = str(parsed.get("narrative") or "").strip()
    observations = [
        str(o).strip() for o in (parsed.get("observations") or [])
        if str(o).strip()
    ]
    if not headline or not narrative:
        return None, "LLM_ERROR"

    mirror: dict[str, Any] = {
        "version": _MIRROR_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": "gpt-4o-mini",
        "based_on_attempts": attempts_analyzed,
        "headline": headline,
        "narrative": narrative,
        "observations": observations,
    }

    persisted = db.set_user_current_learner_mirror(user_id, mirror)
    if not persisted:
        return None, "PERSIST_FAILED"

    return mirror, None


# ── Internals ───────────────────────────────────────────────────────────────


def _load_settings(user_id: str) -> dict | None:
    try:
        return db.get_user_settings(user_id)
    except Exception as e:
        logger.warning("mirror: settings load failed user=%s err=%s", user_id, e)
        return None


def _build_system_prompt() -> str:
    return (
        "You are writing a brief, warm reflection back to a user who "
        "has been practising charisma / stress coaching with this "
        "system. They have asked: \"What are you noticing about me?\"\n"
        "\n"
        "Voice: second-person, generous, specific. Not clinical, not "
        "therapy-speak, not motivational fluff. Speak like a trusted "
        "coach who has been paying attention.\n"
        "\n"
        "GROUND EVERY CLAIM IN THE DATA the user provides. Reference "
        "recurring entities (people, situations, themes) by the "
        "user's exact surface phrasing. Quote a trend direction "
        "only when the input says it. If the data is sparse, say so "
        "honestly — DO NOT invent attempts the data does not show.\n"
        "\n"
        "OUTPUT — strict JSON with exactly:\n"
        "  headline    — 1 sentence naming the pattern.\n"
        "  narrative   — 2-3 short paragraphs (separated by blank "
        "lines). Reference recurring entities by name when natural; "
        "don't force them. End on something forward-looking, not a "
        "summary.\n"
        "  observations — 3-6 short bullets of the FACTS your "
        "narrative is built on (trend, weakest dimension, recurring "
        "entity counts, self-rating gap). Plain English."
    )


def _build_user_prompt(profile: dict, attempts: list[dict]) -> str:
    """Serialise the inputs the LLM should ground its reflection in.

    We send the deterministic profile blob verbatim plus a compact
    view of recent attempts (no full transcripts — saves tokens,
    and the LLM doesn't need the prose to talk about trends).
    """
    traits = profile.get("traits") or {}

    attempt_lines: list[str] = []
    for a in reversed(attempts):  # chronological for readability
        bits = [f"#{a.get('attempt_number')}"]
        score = a.get("score")
        if score is not None:
            try:
                bits.append(f"score={float(score):.2f}")
            except (TypeError, ValueError):
                pass
        components = a.get("components") or {}
        if isinstance(components, dict) and components:
            comp_str = ", ".join(
                f"{k}={float(v):.2f}" for k, v in components.items()
                if isinstance(v, (int, float))
            )
            if comp_str:
                bits.append(comp_str)
        sr = a.get("self_rating")
        if isinstance(sr, int) and 1 <= sr <= 10:
            bits.append(f"self_rating={sr}/10")
        ents = a.get("entities") or {}
        if isinstance(ents, dict):
            ent_bits = []
            for cat in ("people", "situations", "themes"):
                items = ents.get(cat) or []
                if items:
                    ent_bits.append(f"{cat}={items[:3]}")
            if ent_bits:
                bits.append("; ".join(ent_bits))
        attempt_lines.append(" | ".join(bits))

    return (
        "[INFERRED LEARNER PROFILE — traits]\n"
        f"{json.dumps(traits, indent=2)}\n"
        "\n"
        f"[RECENT ATTEMPTS — {len(attempt_lines)}, oldest first]\n"
        + "\n".join(attempt_lines)
    )
