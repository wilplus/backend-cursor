"""Phase Directives-Queue (BE) — LLM suggestion generator for the
admin's 5-step coaching arc.

Powers ``POST /v2/admin/users/<user_id>/directives-queue/suggest``.
Does NOT persist — the endpoint returns the 5-row suggestion list
and the admin reviews / edits / posts it via the normal
``POST .../directives-queue`` flow.

Inputs (all best-effort, gracefully degrade when missing):
  - last 5-10 published charisma_snippets for this user
    (transcripts + admin_comment as "what the coach has already
    said about this person's speech")
  - long-term profile signals: behavioral_profile, custom LLM
    instructions, and the most recent session's charisma_profile
    JSONB (the "charisma trinity" + recent themes)
  - optional snippet_id_context: a specific snippet the admin is
    currently reviewing, used as soft anchor for the arc

Output: a list of 5 dicts ``{intent_tag, question}`` ordered to
form a coherent progressive arc (warm-up → probe → challenge →
reflect → close, but the LLM picks the tags itself; no enum).

Failure semantics
-----------------
Never raises. Any failure (LLM down, parse error, empty profile)
returns ``[]`` — the endpoint surfaces that as an empty rows list
and the admin authors manually. Cold-start (no transcripts, no
profile) intentionally returns ``[]`` rather than emitting
generic filler.
"""
from __future__ import annotations

import json
import logging
from typing import List, Optional

from services.db import db


logger = logging.getLogger(__name__)


# Per-question soft cap (chars). The prompt encodes it as a rule;
# we don't truncate on the server side because the admin will see
# overshoots and edit anyway.
_QUESTION_SOFT_CAP_CHARS = 120
# How many directives the admin authors per arc. Tightened from 5
# to 2 — keeps the admin's authoring overhead low and matches the
# product spec for the directives queue v2 surface.
_ARC_LENGTH = 2

# Model + decoding spec centralized in services/llm_config.py so a
# model deprecation = one diff. See SPEC_DIRECTIVE_SUGGESTIONS for
# the chosen temperature / max_tokens / response_format.


def suggest_directive_arc(
    *,
    user_id: str,
    snippet_id_context: Optional[str] = None,
) -> List[dict]:
    """Generate ``_ARC_LENGTH`` ordered ``{intent_tag, question}`` dicts.

    Returns ``[]`` on any failure mode (LLM unavailable, parse
    error, insufficient context). The admin endpoint surfaces this
    as ``rows: []`` and the FE renders an empty form for manual
    authoring.
    """
    from services.llm import chat_complete
    from services.llm_config import SPEC_DIRECTIVE_SUGGESTIONS

    context_payload = _build_context_payload(
        user_id=user_id,
        snippet_id_context=snippet_id_context,
    )

    from services.will_voice import with_voice_rules
    system = with_voice_rules(
        f"You are an expert communication coach building a "
        f"{_ARC_LENGTH}-step coaching arc for ONE user. Each step "
        "is one open-ended question the AI will ask in their next "
        "chat / interview session.\n"
        "\n"
        "Rules:\n"
        f"  • Exactly {_ARC_LENGTH} questions, each "
        f"≤{_QUESTION_SOFT_CAP_CHARS} characters (a strong rule of "
        "thumb for chat readability, not a hard cap; the admin can "
        "edit overshoots).\n"
        "  • Order matters. Build progressively: open with a warm "
        "probe, then deepen or challenge. Don't ask the same "
        "angle twice.\n"
        "  • Anchor on the user's actual recent transcripts and "
        "profile — every question should feel like it belongs to "
        "THIS user, not a generic template.\n"
        "  • Assign each question an `intent_tag` — a short "
        "free-text label (1-3 words) describing what that step is "
        "doing (e.g. \"warm-up\", \"probe past\", \"challenge "
        "framing\", \"reflect impact\", \"close commit\"). The "
        "tag is for the admin's quick-scan; pick what fits, don't "
        "force a fixed taxonomy.\n"
        "  • Output STRICT JSON: "
        '{"rows": [{"intent_tag": "...", "question": "..."}, ...]}.'
    )

    user_prompt = (
        "USER CONTEXT (best-effort; sections may be empty if the "
        "user is new):\n"
        f"{context_payload}\n\n"
        f"Generate the {_ARC_LENGTH}-step arc now. Strict JSON only."
    )

    result = chat_complete(
        spec=SPEC_DIRECTIVE_SUGGESTIONS,
        system=system,
        user=user_prompt,
        surface="directive_suggestions",
        user_id=user_id,
    )
    if result is None:
        # chat_complete already logged the failure reason.
        return []

    parsed = result.parsed
    rows_raw = parsed.get("rows") if isinstance(parsed, dict) else None
    if not isinstance(rows_raw, list):
        logger.warning(
            "directive_suggestions: malformed JSON shape user=%s "
            "raw_head=%r",
            user_id, result.text[:200],
        )
        return []

    # Normalize + validate. Drop malformed rows rather than fail
    # the whole call; the admin will see the partial result and
    # can ask for a re-suggest.
    out: List[dict] = []
    for r in rows_raw:
        if not isinstance(r, dict):
            continue
        intent_tag = (r.get("intent_tag") or "").strip()
        question = (r.get("question") or "").strip()
        if not intent_tag or not question:
            continue
        out.append({"intent_tag": intent_tag, "question": question})

    if not out:
        logger.warning(
            "directive_suggestions: parsed but produced 0 usable "
            "rows user=%s",
            user_id,
        )
    return out[:_ARC_LENGTH]


# ── Internals ──────────────────────────────────────────────────────


def _build_context_payload(
    *,
    user_id: str,
    snippet_id_context: Optional[str],
) -> str:
    """Compose a single multi-section text block the LLM can read
    end-to-end. Sections are emitted with stable headers so the
    model can rely on their presence (or note their absence)."""
    parts: List[str] = []

    # ── 1. Recent transcripts + coach insights ──
    recent_section = _recent_snippets_section(user_id)
    parts.append(
        "[RECENT TRANSCRIPTS — what the user has actually said + "
        "what the coach has already commented]\n"
        f"{recent_section}"
    )

    # ── 2. Long-term profile signals ──
    profile_section = _profile_section(user_id)
    parts.append(
        "[LONG-TERM PROFILE — behavioral tendencies, custom "
        "instructions, charisma trinity from most recent session]\n"
        f"{profile_section}"
    )

    # ── 3. Optional anchor snippet ──
    if snippet_id_context:
        anchor = _anchor_snippet_section(snippet_id_context, user_id)
        if anchor:
            parts.append(
                "[ANCHOR SNIPPET — the moment the admin is reviewing "
                "right now; let it bias the arc but don't make all "
                "5 questions about it]\n"
                f"{anchor}"
            )

    return "\n\n".join(parts)


def _recent_snippets_section(user_id: str) -> str:
    """Last ~8 published snippets' transcript + admin_comment.
    Returns a "(no recent transcripts yet)" sentinel when empty so
    the LLM knows it's working cold rather than seeing a missing
    section."""
    try:
        result = (
            db.client.table("charisma_snippets")
            .select(
                "transcript, admin_comment, snippet_type, "
                "coach_label, created_at"
            )
            .eq("user_id", user_id)
            .not_.is_("admin_comment", "null")
            .order("created_at", desc=True)
            .limit(8)
            .execute()
        )
        rows = list(result.data or [])
    except Exception as e:
        logger.warning(
            "directive_suggestions: recent_snippets fetch failed "
            "user=%s err=%s",
            user_id, e,
        )
        rows = []

    if not rows:
        return "(no recent transcripts yet — user may be new)"

    lines = []
    for r in rows:
        t = (r.get("transcript") or "").strip()
        c = (r.get("admin_comment") or "").strip()
        label = (r.get("coach_label") or r.get("snippet_type") or "—").strip()
        # Bound each transcript to ~280 chars so 8 snippets don't
        # eat the whole context window on chatty users.
        if len(t) > 280:
            t = t[:277] + "…"
        lines.append(
            f"  • [{label}] User: \"{t or '(no transcript)'}\"\n"
            f"    Coach: \"{c or '(no comment)'}\""
        )
    return "\n".join(lines)


def _profile_section(user_id: str) -> str:
    """Behavioral profile + custom LLM instructions + most-recent
    charisma_profile (which carries the charisma-trinity blob)."""
    out_lines: List[str] = []

    try:
        settings = db.get_user_settings(user_id) or {}
    except Exception as e:
        logger.warning(
            "directive_suggestions: user_settings fetch failed "
            "user=%s err=%s",
            user_id, e,
        )
        settings = {}

    behavioral = (settings.get("behavioral_profile") or "").strip()
    custom_instr = (settings.get("custom_llm_instructions") or "").strip()
    if behavioral:
        out_lines.append(f"Behavioral profile: {behavioral}")
    if custom_instr:
        # Admin-authored guidance the LLM should respect ("never
        # ask about X; this person prefers Y").
        if len(custom_instr) > 400:
            custom_instr = custom_instr[:397] + "…"
        out_lines.append(f"Admin custom instructions: {custom_instr}")

    # Most recent session's charisma_profile — the per-session
    # "charisma trinity + themes" JSONB. v2_sessions are ordered by
    # created_at; pull the newest with a non-null profile.
    trinity_text = _recent_charisma_profile(user_id)
    if trinity_text:
        out_lines.append(f"Charisma profile (latest): {trinity_text}")

    if not out_lines:
        return "(no profile signals available yet)"
    return "\n".join(out_lines)


def _recent_charisma_profile(user_id: str) -> str:
    """Pull the most recent v2_sessions.charisma_profile JSONB for
    this user. Returns a compact one-line rendering, or "" when
    nothing usable exists."""
    try:
        result = (
            db.client.table("v2_sessions")
            .select("charisma_profile, created_at")
            .eq("user_id", user_id)
            .not_.is_("charisma_profile", "null")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = result.data or []
    except Exception as e:
        logger.warning(
            "directive_suggestions: charisma_profile fetch failed "
            "user=%s err=%s",
            user_id, e,
        )
        return ""

    if not rows:
        return ""
    profile = rows[0].get("charisma_profile")
    if not isinstance(profile, dict):
        return ""
    # Render compactly. Don't assume schema — the model is fine
    # reading raw JSON if we have to.
    try:
        compact = json.dumps(profile, separators=(",", ":"))
        if len(compact) > 600:
            compact = compact[:597] + "…"
        return compact
    except Exception:
        return ""


def _anchor_snippet_section(
    snippet_id: str,
    user_id: str,
) -> Optional[str]:
    """Read the specific snippet the admin is currently reviewing
    and emit it as the anchor block. Owner-scoped to the same user
    the arc is being authored for — if the snippet belongs to
    someone else, return None (caller treats as "no anchor")."""
    try:
        snippet = db.get_snippet_by_id(snippet_id, user_id=user_id)
    except Exception as e:
        logger.warning(
            "directive_suggestions: anchor snippet fetch failed "
            "user=%s snippet=%s err=%s",
            user_id, snippet_id, e,
        )
        return None
    if not snippet:
        return None
    t = (snippet.get("transcript") or "").strip()
    c = (snippet.get("admin_comment") or "").strip()
    label = (
        snippet.get("coach_label")
        or snippet.get("snippet_type")
        or "—"
    )
    if not (t or c):
        return None
    if len(t) > 400:
        t = t[:397] + "…"
    return (
        f"  • [{label}] User: \"{t or '(no transcript)'}\"\n"
        f"    Coach: \"{c or '(no comment)'}\""
    )
