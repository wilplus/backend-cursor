"""Explore-Session cadence — staged guidance bubbles (willab Prompt A §4).

An "explore session" walks the user through deliberately-distinct takes of
the SAME talk (baseline → chill → data → optional spark) so the app can find
their strongest version of each line. THIS module renders the invitation for
each next take as a Lounge bubble.

THE LANGUAGE PRINCIPLE (§2 — do NOT hardcode). The cadence CONTENT is a fixed,
structured, LANGUAGE-NEUTRAL spec (``BEATS`` below — doctrine; the model may
not invent or alter it). The DELIVERED message is RENDERED in the user's
language at fire time by a CONSTRAINED generation call pinned to: the beat's
intent + the EXACT fixed facts (numbers verbatim) + the EXACT safety caveat +
the woven goal + Will's tone. There is NO per-language translation table and
NO hardcoded delivered string. If a render fails, we SKIP the bubble (never
ship a hardcoded fallback — that would violate the fence).

ARCHITECTURAL CONSTRAINT (§0): this is a SEPARATE staged-message flow that
lifts the next_session_icebreaker pattern (render → db.insert_lounge_messages).
It does NOT touch the master_doc_rag Lounge librarian (at its attention
ceiling). Bubbles are kind="cadence", idempotent per (arc_id, beat).

FENCES (§7): wellbeing caveat preserved in EVERY language; AC-9 split-sink —
the cadence is INSTRUCTION/INVITATION only, never a grade/verdict/"improving"
trajectory; tone is "Will" (observational, guides the next action — never a
cheerleader); the cadence INVITES, never gates.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Target arc = 3 takes (baseline + chill + data); spark = optional 4th.
TARGET_TAKES = 3

_SURFACE = "session_cadence"
_CLIENT_ID_NS = uuid.NAMESPACE_URL


# ── The cadence spec: language-neutral doctrine (§4). ───────────────────
# Keyed by beat_no. `fires_after_take` = the just-completed take this beat
# responds to (None = arc start, pre-take-1). The English `intent` is the
# SOURCE the renderer translates + voices; it is never shipped verbatim.
BEATS: dict[int, dict[str, Any]] = {
    0: {
        "beat_no": 0,
        "key": "arc_start",
        "fires_after_take": None,  # pre-take-1 framing
        "mode": None,
        "weave_goal": True,
        "intent": (
            "For the best result you'll deliver the SAME talk a few times, "
            "each in a different style, so together we find your strongest "
            "version of each line. This first one is just your natural "
            "baseline — say it the way you'd say it today."
        ),
        "fixed_facts": [
            "~30 minutes",
            "at least 3 takes, with a short reset between each",
        ],
        "safety_caveat": None,
    },
    1: {
        "beat_no": 1,
        "key": "after_take_1",
        "fires_after_take": 1,
        "mode": "Confidant (chill)",
        "weave_goal": False,
        "intent": (
            "That's your baseline. Now record the SAME talk again, loosened: "
            "like you're telling one trusted friend over coffee — slower, "
            "warmer, no audience."
        ),
        "fixed_facts": [],
        "safety_caveat": None,
    },
    2: {
        "beat_no": 2,
        "key": "after_take_2",
        "fires_after_take": 2,
        "mode": "Authority (data)",
        "weave_goal": False,
        "intent": (
            "The SAME talk once more, in authority gear: slow down, drop your "
            "pitch slightly, put weight on the key numbers and claims — like "
            "the person who knows this cold."
        ),
        "fixed_facts": [],
        "safety_caveat": None,
    },
    3: {
        "beat_no": 3,
        "key": "after_take_3",
        "fires_after_take": 3,
        "mode": "Spark (energized)",
        "spark_only": True,  # fires only if spark appetite is on
        "weave_goal": False,
        "intent": (
            "Last one, SAME talk, full energy. You're warmed up now — get the "
            "energy up, then record straight away while it's up. This is "
            "usually the most alive take."
        ),
        "fixed_facts": [
            "10 pushups or jumping jacks",
            "3 slow breaths to settle",
            "record straight away",
        ],
        "safety_caveat": (
            "The exercise is ALWAYS optional and ONLY if you're physically "
            "able. A low-impact alternative is marching in place for about "
            "20 seconds; the breathing is the safe default. Skipping it is "
            "completely fine — it's never required and this is not medical "
            "advice."
        ),
    },
}


def select_post_take_beat(
    take_index: Any, *, spark_enabled: bool = False,
) -> Optional[dict]:
    """The beat that fires AFTER a just-completed ``take_index`` to INVITE the
    next take. Returns ``None`` (no nag) once the planned arc is done:

      take 1 done → BEAT 1 (chill)   take 2 done → BEAT 2 (data)
      take 3 done → BEAT 3 (spark) ONLY if spark_enabled, else None
      take ≥ last planned → None
    """
    try:
        ti = int(take_index)
    except (TypeError, ValueError):
        return None
    beat = BEATS.get(ti)  # beat_no n is invited by completing take n
    if not beat:
        return None
    if beat.get("spark_only") and not spark_enabled:
        return None
    return beat


# ── Rendering: constrained in-language generation (§2). ─────────────────
def _render_beat(
    beat: dict,
    *,
    take_index: Optional[int],
    take_count: Optional[int],
    language: Optional[str],
    goal: Optional[str],
) -> Optional[str]:
    """Render ONE beat into the user's language. Pinned to the beat's intent +
    fixed facts (numbers verbatim) + safety caveat (preserved, never weakened)
    + woven goal + Will's tone. Returns the bubble body, or ``None`` on ANY
    failure (the caller then skips the insert — we never ship a hardcoded
    string, §7)."""
    try:
        import json as _json

        from services.llm import chat_complete
        from services.llm_config import SPEC_SESSION_CADENCE
        from services.will_voice import with_voice_rules
    except Exception as e:  # pragma: no cover - import guard
        logger.warning("cadence: llm import failed: %s", e)
        return None

    weave_goal = bool(beat.get("weave_goal")) and bool((goal or "").strip())
    caveat = beat.get("safety_caveat")
    facts = list(beat.get("fixed_facts") or [])

    rules = [
        "You are rendering ONE cadence message for a voice-coaching app. The "
        "PROTOCOL below is fixed doctrine — you translate and voice it, you "
        "NEVER invent, add, reorder, or drop content.",
        "Render the message ENTIRELY in the user's language (see USER "
        "LANGUAGE). Match that language exactly; do not mix languages.",
        "Preserve every fixed fact EXACTLY — numbers, counts, and durations "
        "survive verbatim in the user's language.",
        "Tone is 'Will': observational, calm, guides the very next action. "
        "NOT a cheerleader — never 'great job', 'amazing', 'you're crushing "
        "it', and never imply a score, grade, or that they're improving.",
        "Keep it to a short chat bubble (2–4 sentences). No preamble, no "
        "headers, no emoji unless the user's language norm expects it.",
    ]
    if beat.get("mode"):
        rules.append(
            f"This take's style is '{beat['mode']}' — convey that register in "
            "the user's words; you may keep a recognizable label for it."
        )
    if take_index and take_count:
        rules.append(
            f"You MAY include a light 'take {take_index} of {take_count}' "
            "spine so they know where they are in the arc."
        )
    if weave_goal:
        rules.append(
            "Weave in the user's stated goal naturally (see USER GOAL) so the "
            "framing connects to what they're working toward. Echo it, never "
            "grade it."
        )
    if caveat:
        rules.append(
            "The SAFETY CAVEAT is non-negotiable: render its full meaning in "
            "the user's language, intact — optional, only-if-able, the "
            "low-impact alternative, breathing as the safe default, skipping "
            "is fine, not medical. Do NOT weaken or shorten it away."
        )
    rules.append('Output strict JSON: {"message": "<the rendered bubble>"}.')

    system = with_voice_rules("\n".join(f"- {r}" for r in rules))

    # The user prompt carries the language-neutral protocol + the user's own
    # words (goal) — which also let the model infer the language when no code
    # is supplied (the goal is in the user's language).
    lang_line = (
        language.strip() if isinstance(language, str) and language.strip()
        else "unknown — infer it from the user's goal text below; if there is "
        "no goal, use clear, simple English"
    )
    parts = [
        f"USER LANGUAGE: {lang_line}",
        "",
        "PROTOCOL (translate + voice; do not invent):",
        f"  intent: {beat['intent']}",
    ]
    if facts:
        parts.append("  fixed_facts (keep numbers verbatim):")
        parts.extend(f"    - {f}" for f in facts)
    if caveat:
        parts.append(f"  safety_caveat (preserve fully): {caveat}")
    if weave_goal:
        parts.append("")
        parts.append(f"USER GOAL (weave in, in their language): {goal.strip()}")
    elif (goal or "").strip():
        parts.append("")
        parts.append(
            f"(User's goal, for LANGUAGE inference only — do NOT mention it): "
            f"{goal.strip()}"
        )
    user_prompt = "\n".join(parts)

    schema = {
        "name": "session_cadence_message",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["message"],
            "properties": {
                "message": {"type": "string", "minLength": 8, "maxLength": 900},
            },
        },
        "strict": True,
    }

    try:
        result = chat_complete(
            spec=SPEC_SESSION_CADENCE,
            system=system,
            user=user_prompt,
            surface=_SURFACE,
            response_format_override={
                "type": "json_schema",
                "json_schema": schema,
            },
        )
    except Exception as e:
        logger.warning("cadence: render call failed beat=%s: %s",
                       beat.get("beat_no"), e)
        return None
    if not result:
        return None

    parsed = result.parsed
    if not isinstance(parsed, dict):
        try:
            parsed = _json.loads((result.text or "").strip())
        except Exception:
            logger.warning("cadence: output unparseable beat=%s: %r",
                           beat.get("beat_no"), (result.text or "")[:200])
            return None
        if not isinstance(parsed, dict):
            return None
    body = str(parsed.get("message") or "").strip()
    return body or None


# ── Persistence: idempotent Lounge bubble. ──────────────────────────────
def _client_id(arc_id: str, beat_no: int) -> str:
    """Stable per (arc, beat) so re-firing a beat is a no-op upsert (§6 C1)."""
    return str(uuid.uuid5(_CLIENT_ID_NS, f"willab-cadence:{arc_id}:beat{beat_no}"))


def _insert_bubble(
    database,
    user_id: str,
    arc_id: str,
    beat_no: int,
    body: str,
    *,
    take_index: Optional[int],
    take_count: Optional[int],
) -> bool:
    try:
        rows = database.insert_lounge_messages(str(user_id), [{
            "client_id": _client_id(arc_id, beat_no),
            "role": "bot",
            "kind": "cadence",
            "body": body,
            "metadata": {
                "arc_id": arc_id,
                "beat": beat_no,
                "take_index": take_index,
                "take_count": take_count,
            },
            "client_created_at": datetime.now(timezone.utc).isoformat(),
        }])
        return bool(rows)
    except Exception as e:
        logger.warning("cadence: insert failed arc=%s beat=%s: %s",
                       arc_id, beat_no, e)
        return False


def _get_db(database):
    if database is not None:
        return database
    from services.db import db as _db
    return _db


def fire_arc_start(
    user_id: Optional[str],
    arc_id: Optional[str],
    *,
    goal: Optional[str] = None,
    language: Optional[str] = None,
    database=None,
) -> bool:
    """BEAT 0 — the pre-take-1 framing bubble (goal-woven). Idempotent.
    Returns True iff a bubble was rendered + inserted."""
    if not user_id or not arc_id:
        return False
    beat = BEATS[0]
    body = _render_beat(
        beat, take_index=1, take_count=TARGET_TAKES,
        language=language, goal=goal,
    )
    if not body:
        return False
    return _insert_bubble(
        _get_db(database), user_id, arc_id, 0, body,
        take_index=1, take_count=TARGET_TAKES,
    )


def fire_post_take(
    user_id: Optional[str],
    arc_id: Optional[str],
    take_index: Any,
    *,
    take_count: Optional[int] = None,
    spark_enabled: bool = False,
    goal: Optional[str] = None,
    language: Optional[str] = None,
    database=None,
) -> bool:
    """Fire the beat that INVITES the next take, after ``take_index`` just
    completed. No-op (no nag) once the planned arc is done. Idempotent.
    Returns True iff a bubble was rendered + inserted."""
    if not user_id or not arc_id:
        return False
    beat = select_post_take_beat(take_index, spark_enabled=spark_enabled)
    if not beat:
        return False
    body = _render_beat(
        beat, take_index=take_index, take_count=take_count or TARGET_TAKES,
        language=language, goal=goal,
    )
    if not body:
        return False
    return _insert_bubble(
        _get_db(database), user_id, arc_id, beat["beat_no"], body,
        take_index=take_index, take_count=take_count,
    )
