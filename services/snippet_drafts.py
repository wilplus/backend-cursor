"""AI-prefilled draft generation for snippet admin annotations.

Phase 10 of the snippet-CTA learning loop. When a charisma or stress
snippet is first extracted, this module generates an AI suggestion
for the admin-typed field (admin_comment / coach_label_notes) so the
admin sees a draft they can keep or edit instead of staring at an
empty box.

Why generate at extraction time
-------------------------------
- The admin reviews the snippet later (minutes to hours after the
  recording finishes). Generating then lets them open the snippet
  panel and immediately see a draft.
- Cost: one cheap LLM call per snippet. Acceptable in the snippet
  extraction pipeline which already runs async after upload.

Implicit-approval signal
------------------------
Both edited and not-edited produce learning signal. The capture
happens at publish time (see services/db.py::
record_snippet_publish_annotations) — not on the admin's save click —
because we want admins to leave the AI draft alone when it's good
WITHOUT being forced to manually approve. Publication is the implicit
"this draft is shipped" moment.

Failure semantics
-----------------
Every failure path swallows + logs. A missing draft is far better
than blocking the snippet extraction pipeline. If the LLM is down,
the admin sees an empty admin_comment field (same as today) and the
loop continues without that training pair.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from services.db import db


logger = logging.getLogger(__name__)


_MODEL = "gpt-4o-mini"
_MAX_TOKENS = 220


def generate_charisma_draft_for_snippet(snippet_id: str) -> str | None:
    """Generate + persist an ai_draft_admin_comment for a charisma snippet.

    Returns the generated draft string, or None when:
      - the snippet doesn't exist
      - the transcript is empty (nothing for the LLM to react to)
      - the LLM call failed
      - the DB write failed
    Caller (the snippet extraction daemon) does not retry — a missing
    draft just falls back to the existing empty-field UX.
    """
    snippet = _load_charisma(snippet_id)
    if snippet is None:
        return None
    transcript = (snippet.get("transcript") or "").strip()
    if not transcript:
        return None

    draft = _call_llm_draft(
        system_prompt=_charisma_system_prompt(),
        user_prompt=_charisma_user_prompt(snippet),
        json_key="admin_comment",
        schema_name="CHARISMA_DRAFT_SCHEMA",
    )
    if not draft:
        return None

    persisted = db.set_charisma_snippet_ai_draft_comment(snippet_id, draft)
    return draft if persisted else None


def generate_stress_draft_for_snippet(snippet_id: str) -> str | None:
    """Generate + persist an ai_draft_coach_notes for a stress snippet.

    Mirror of generate_charisma_draft_for_snippet. Returns the draft
    or None on any failure.
    """
    snippet = _load_stress(snippet_id)
    if snippet is None:
        return None
    transcript = (snippet.get("transcript") or "").strip()
    if not transcript:
        return None

    draft = _call_llm_draft(
        system_prompt=_stress_system_prompt(),
        user_prompt=_stress_user_prompt(snippet),
        json_key="coach_notes",
        schema_name="STRESS_DRAFT_SCHEMA",
    )
    if not draft:
        return None

    persisted = db.set_stress_snippet_ai_draft_notes(snippet_id, draft)
    return draft if persisted else None


# ── Internals ───────────────────────────────────────────────────────────────


def _load_charisma(snippet_id: str) -> dict | None:
    try:
        # Admin-context read (user_id=None) — the daemon generating
        # drafts runs server-side, not on behalf of a specific user.
        return db.get_snippet_by_id(snippet_id, user_id=None)
    except Exception as e:
        logger.warning("snippet_drafts: charisma load failed %s: %s", snippet_id, e)
        return None


def _load_stress(snippet_id: str) -> dict | None:
    try:
        return db.v2_get_stress_snippet(snippet_id)
    except Exception as e:
        logger.warning("snippet_drafts: stress load failed %s: %s", snippet_id, e)
        return None


def _call_llm_draft(
    *,
    system_prompt: str,
    user_prompt: str,
    json_key: str,
    schema_name: str,
) -> str | None:
    """Run one LLM call and pull the named field out of the structured response.

    schema_name selects which schema from services.llm_schemas to use
    — kept as a string here so this helper can serve both charisma
    and stress without importing both schemas eagerly.
    """
    try:
        from services.openai_service import OpenAIService
        service = OpenAIService()
    except Exception as e:
        logger.warning("snippet_drafts: openai import failed: %s", e)
        return None
    if not service.client:
        return None

    try:
        from services.llm_schemas import (
            CHARISMA_DRAFT_SCHEMA,
            STRESS_DRAFT_SCHEMA,
            response_format,
        )
        schema = {
            "CHARISMA_DRAFT_SCHEMA": CHARISMA_DRAFT_SCHEMA,
            "STRESS_DRAFT_SCHEMA": STRESS_DRAFT_SCHEMA,
        }[schema_name]
    except Exception as e:
        logger.warning("snippet_drafts: schema load failed: %s", e)
        return None

    try:
        response = service.client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=_MAX_TOKENS,
            temperature=0.5,
            response_format=response_format(schema),
        )
        # Cost ledger (token-pricing Phase 0). Recorded HERE, immediately
        # after the call returns and BEFORE any parsing — we have already
        # paid for this response, so a downstream parse failure must not
        # lose the cost row. This service bypasses services/llm.py, so
        # without this hook it is invisible to the ledger.
        try:
            from services.llm_usage import record_response_usage
            record_response_usage(response, surface="snippet_drafts",
                                  model=_MODEL,)
        except Exception:
            pass
        raw = (response.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("snippet_drafts: openai call failed: %s", e)
        return None

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("snippet_drafts: unparseable structured output %r", raw[:300])
        return None

    value = (parsed.get(json_key) or "").strip()
    # Sanity check — schema enforces maxLength but defense-in-depth.
    return value[:300] if value else None


def _charisma_system_prompt() -> str:
    from services.will_voice import with_voice_rules
    return with_voice_rules(
        "You write the one-sentence admin comment a charisma coach "
        "would leave on a snippet where a user sounded magnetic — "
        "confident, in flow, perfectly paced. The admin will see "
        "your suggestion as a pre-filled draft they can keep or edit; "
        "match the tone they would write themselves.\n"
        "\n"
        "VOICE: Second-person, terse, specific. No therapy-speak, no "
        "preamble, no praise inflation (\"amazing!\", \"wow\").\n"
        "GROUND in the transcript and acoustic features the user "
        "prompt gives you. If the transcript is too short to say "
        "anything specific, write the most generic version "
        "(\"Your delivery here was charismatic.\") rather than "
        "inventing detail.\n"
        "OUTPUT: strict JSON with key \"admin_comment\" only."
    )


def _stress_system_prompt() -> str:
    from services.will_voice import with_voice_rules
    return with_voice_rules(
        "You write the one-sentence coach note a charisma coach "
        "would leave on a snippet where a user's voice tightened "
        "under pressure. The admin will see your suggestion as a "
        "pre-filled draft they can keep or edit; match the tone "
        "they'd write themselves.\n"
        "\n"
        "VOICE: Second-person, terse, specific. Quote the trigger "
        "phrase from the transcript verbatim when it's identifiable. "
        "No therapy-speak (\"anxiety\", \"panic\", \"nerves\").\n"
        "GROUND in the transcript and acoustic features the user "
        "prompt gives you.\n"
        "OUTPUT: strict JSON with key \"coach_notes\" only."
    )


def _charisma_user_prompt(snippet: dict) -> str:
    transcript = (snippet.get("transcript") or "").strip()
    metrics = snippet.get("metrics") or {}
    feature_bits = _format_metrics(metrics)
    return (
        f"transcript: \"{transcript}\"\n"
        f"acoustic features: {feature_bits or '(none captured)'}"
    )


def _stress_user_prompt(snippet: dict) -> str:
    transcript = (snippet.get("transcript") or "").strip()
    features = snippet.get("features") or {}
    feature_bits = _format_metrics(features)
    return (
        f"transcript: \"{transcript}\"\n"
        f"acoustic features: {feature_bits or '(none captured)'}"
    )


def _format_metrics(m: dict[str, Any]) -> str:
    """Render a metrics dict as short flat string for the user prompt."""
    if not isinstance(m, dict) or not m:
        return ""
    keep = ("wpm", "dynamic_db", "filler_count", "specificity",
            "emotional_movement", "engagement", "length_fit",
            "filler_density")
    parts = []
    for k in keep:
        v = m.get(k)
        if v is None:
            continue
        if isinstance(v, (int, float)):
            parts.append(f"{k}={float(v):.2f}")
        else:
            parts.append(f"{k}={v}")
    return ", ".join(parts)
