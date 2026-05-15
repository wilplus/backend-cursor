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

    # Cross-session admin coaching observations — the strongest
    # signal for "what's actually going on with this user". Pulled
    # once here so the prompt build below stays a pure function.
    recent_admin_comments = _load_recent_admin_comments(user_id)

    system = _build_system_prompt()
    user_prompt = _build_user_prompt(profile, attempts, recent_admin_comments)

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
        "CRITICAL — IGNORE THE LITERAL SUBJECT MATTER OF THE "
        "DIAGNOSTIC QUESTIONS the user answered (math problems, "
        "trivia, facts, etc.). Those are cognitive-load probes, NOT "
        "topics the user 'is good at'. Never say 'you handled the "
        "math well' / 'you stayed on the trivia topic'. The literal "
        "content of the questions is irrelevant to the reflection.\n"
        "\n"
        "REDEFINE 'STICKINESS' for this reflection: stickiness is a "
        "MENTAL FOCUS / PRESENCE UNDER PRESSURE signal — the user's "
        "ability to hold a clear train of thought when their working "
        "memory is taxed. Talk about it as composure, focus, "
        "presence. Never name the topic stickiness was measured on.\n"
        "\n"
        "PRIMARY SOURCES OF TRUTH (in order):\n"
        "  1. Admin coaching comments — what a human coach has "
        "     flagged on this user's snippets. These are the most "
        "     signal-dense observations available; the reflection "
        "     should sound like a continuation of what the coach "
        "     has already noticed.\n"
        "  2. Acoustic delivery: Pace, Flow (fillers), Pitch, "
        "     Dynamic dB, Energy — HOW the user speaks.\n"
        "  3. Learner profile aggregates (trend, behavioral "
        "     profile, attempts count). Background colour, not "
        "     foreground claims.\n"
        "\n"
        "OUTPUT — strict JSON with exactly:\n"
        "  headline    — 1 sentence naming the pattern. NO raw "
        "                  numeric scores. NO component jargon "
        "                  (engagement / specificity / emotional_"
        "                  movement / stickiness as named metric "
        "                  buckets). Describe the pattern in plain "
        "                  English.\n"
        "  narrative   — Write EXACTLY ONE cohesive paragraph "
        "                  (3-4 sentences). NO bullet points, NO "
        "                  headers, NO line breaks, NO raw decimal "
        "                  scores (\"0.50 across engagement, "
        "                  specificity…\") — that style is BANNED. "
        "                  Talk about HOW they show up: their "
        "                  presence, their composure under pressure, "
        "                  the coach's observations about delivery, "
        "                  the trajectory of their work. End on "
        "                  something forward-looking.\n"
        "  observations — 3-6 short bullets of the FACTS your "
        "                  narrative is built on (trend direction, "
        "                  weakest dimension named in plain English, "
        "                  recurring patterns the coach has flagged, "
        "                  self-rating vs measured gap). Plain "
        "                  English. Numbers ALLOWED here — this is "
        "                  the bullets-only place where raw scores "
        "                  can live, never inside the narrative.\n"
        "\n"
        "EXAMPLES of the bar to hit:\n"
        "\n"
        "  BAD (banned style — do NOT write narratives like this):\n"
        "    \"I see you engaging with the themes of confidence and "
        "    future aspirations, particularly in your second attempt "
        "    where you scored 0.50 across engagement, specificity, "
        "    and emotional movement. Your overall average remains at "
        "    0.175, indicating room to deepen specificity, which "
        "    currently sits at 0.1667.\"\n"
        "\n"
        "  GOOD (this is the vibe):\n"
        "    \"You're showing up with intention, and your coach has "
        "    noticed your delivery steadying as you take on harder "
        "    moments. Under cognitive pressure your focus holds, "
        "    though your specifics still arrive in broad strokes "
        "    rather than concrete detail — that's the edge to push "
        "    on next. Trust the deliberate pace you've already "
        "    found.\""
    )


def _load_recent_admin_comments(user_id: str) -> list[dict]:
    """Pull the user's most recent admin coaching observations across
    all their snippets.

    The mirror runs at user-level (not session-level) so admin
    comments are the strongest cross-session signal we can hand the
    LLM — they're what a human coach has literally written about
    this person. Returns a list of ``{label, comment}`` dicts,
    newest first, capped at 5.
    """
    try:
        rows = (
            db.client.table("charisma_snippets")
            .select("admin_comment, coach_label, snippet_type, created_at")
            .eq("user_id", user_id)
            .not_.is_("admin_comment", "null")
            .order("created_at", desc=True)
            .limit(8)
            .execute()
            .data
        ) or []
    except Exception as e:
        logger.warning(
            "mirror: recent admin comments load failed user=%s err=%s",
            user_id, e,
        )
        return []

    out: list[dict] = []
    for r in rows:
        comment = (r.get("admin_comment") or "").strip()
        if not comment:
            continue
        label = (r.get("coach_label") or r.get("snippet_type") or "").lower()
        if len(comment) > 240:
            comment = comment[:240].rstrip() + "…"
        out.append({
            "label": label if label in ("stress", "charisma") else "",
            "comment": comment,
        })
        if len(out) >= 5:
            break
    return out


def _build_user_prompt(
    profile: dict,
    attempts: list[dict],
    recent_admin_comments: list[dict],
) -> str:
    """Serialise the inputs the LLM should ground its reflection in.

    Sections in priority order (matches the system prompt's ranking
    of sources of truth):

      1. ADMIN COACHING OBSERVATIONS — what the coach has flagged
         (PRIMARY).
      2. ACOUSTIC SIGNALS — extracted from the recent attempts so
         the narrative can talk about HOW they speak.
      3. LEARNER PROFILE — high-level traits only, NO raw score
         dump.
      4. RECENT ATTEMPTS — compact view (kept terse — the LLM
         doesn't need full numbers in prose, but observations
         bullets can quote them).
    """
    parts: list[str] = []

    # ── 1. Admin coaching observations (PRIMARY) ────────────────
    if recent_admin_comments:
        lines = [
            "ADMIN COACHING OBSERVATIONS (primary source — the "
            "reflection should sound like a continuation of these):"
        ]
        for entry in recent_admin_comments:
            tag = f"[{entry.get('label')}]" if entry.get("label") else ""
            lines.append(f"  {tag} {entry.get('comment')}".strip())
        parts.append("\n".join(lines))
    else:
        parts.append(
            "ADMIN COACHING OBSERVATIONS: (none yet — fall back to "
            "acoustic signals + learner profile, and explicitly say "
            "the read is early)"
        )

    # ── 2. Acoustic signals (from recent attempts, deterministic)
    acoustic_lines = _aggregate_acoustic_signals(attempts)
    if acoustic_lines:
        parts.append(
            "ACOUSTIC DELIVERY (HOW they speak — secondary "
            "source):\n" + "\n".join(acoustic_lines)
        )

    # ── 3. Learner profile (high-level only) ─────────────────────
    traits = profile.get("traits") or {}
    profile_lines: list[str] = []
    behavioral = (
        (profile.get("behavioral_profile") or "").strip()
        or (traits.get("behavioral_profile") or "").strip()
    )
    if behavioral:
        profile_lines.append(f"  Behavioral profile: {behavioral}")
    score_trend = (
        traits.get("score_trend") or traits.get("trend")
    )
    if isinstance(score_trend, str) and score_trend.strip():
        profile_lines.append(f"  Score trend: {score_trend.strip()}")
    attempts_analyzed = (
        profile.get("attempts_analyzed")
        or traits.get("attempts_analyzed")
    )
    if isinstance(attempts_analyzed, int) and attempts_analyzed > 0:
        profile_lines.append(
            f"  Coaching attempts analysed: {attempts_analyzed}"
        )
    if profile_lines:
        parts.append("LEARNER PROFILE:\n" + "\n".join(profile_lines))

    # ── 4. Recent attempts — terse compact view ─────────────────
    attempt_lines: list[str] = []
    for a in reversed(attempts):
        bits = [f"#{a.get('attempt_number')}"]
        score = a.get("score")
        if score is not None:
            try:
                bits.append(f"score={float(score):.2f}")
            except (TypeError, ValueError):
                pass
        sr = a.get("self_rating")
        if isinstance(sr, int) and 1 <= sr <= 10:
            bits.append(f"self={sr}/10")
        attempt_lines.append(" | ".join(bits))
    if attempt_lines:
        parts.append(
            f"RECENT ATTEMPTS (terse — for the observations "
            f"bullets only, NOT for narrative prose):\n"
            + "\n".join(attempt_lines)
        )

    return "\n\n".join(parts)


def _aggregate_acoustic_signals(attempts: list[dict]) -> list[str]:
    """Pull average pace/fillers/etc from the attempts' acoustic
    metrics block when present. Mirror runs at user level so we
    average over recent attempts to get the "how they speak"
    picture.

    Each attempt may or may not carry an ``acoustic`` dict — we
    aggregate over whatever's there.
    """
    pace_vals: list[float] = []
    filler_vals: list[float] = []
    dynamic_vals: list[float] = []
    pitch_vals: list[float] = []
    for a in attempts:
        ac = a.get("acoustic") or a.get("metrics") or {}
        if not isinstance(ac, dict):
            continue
        for src_key, bucket in (
            ("wpm", pace_vals),
            ("pace", pace_vals),
            ("fillers", filler_vals),
            ("dynamic_db", dynamic_vals),
            ("pitch_center", pitch_vals),
        ):
            v = ac.get(src_key)
            if isinstance(v, (int, float)) and v > 0:
                bucket.append(float(v))
    lines: list[str] = []
    if pace_vals:
        lines.append(
            f"  Pace (avg WPM across recent attempts): "
            f"{sum(pace_vals) / len(pace_vals):.0f}"
        )
    if filler_vals:
        lines.append(
            f"  Flow (avg filler count per attempt): "
            f"{sum(filler_vals) / len(filler_vals):.1f}"
        )
    if dynamic_vals:
        lines.append(
            f"  Dynamic dB (avg): {sum(dynamic_vals) / len(dynamic_vals):.1f}"
        )
    if pitch_vals:
        lines.append(
            f"  Pitch center (avg semitones): "
            f"{sum(pitch_vals) / len(pitch_vals):.1f}"
        )
    return lines
