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
        # SHORTENED 2026-08-15 (founder, on the delivered bubbles). Same
        # doctrine, half the words: the three takes, the varied setup, the
        # day-spacing nudge and "this one is the baseline" all survive — the
        # scaffolding around them ("for the best result", "not just a
        # different voice", "varied surroundings … give a cleaner read than
        # doing them all back-to-back in the same spot") did not. A chat
        # bubble is read in one glance; anything that is not the next action
        # is spent attention.
        "intent": (
            "Same talk, three times, each in a different style and a "
            "different setup — that's how we find your strongest version of "
            "each line. Space one out to another day if you can. This first "
            "one is your baseline: say it the way you'd say it today."
        ),
        "fixed_facts": [
            # #2 (2026-06-21): no time promise — the natural baseline may run
            # well under 30 min. Just the takes + the reset.
            "record the same talk 3 times, with a short reset between each",
            # 2026-06-27 (founder recording-cadence guidance): 3 different
            # SETUPS is a structural count, parallel to "3 times". The SOFT
            # day-spacing nudge ("at least one on a different day") stays in
            # `intent`, NOT here — pinning soft prose in the verbatim fixed-
            # fact channel would read as a floor/requirement (the never-gate
            # fence); in `intent` the renderer can voice + soften it.
            "3 different setups",
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
            "Same talk again, loosened — like telling one trusted friend over "
            "coffee. Slower, warmer, no audience. A new spot if you can."
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
            "Same talk in authority gear: slower, pitch slightly lower, "
            "weight on the key numbers and claims — like the person who knows "
            "this cold. Somewhere different again if you can."
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
            "Last one, same talk, full energy. Get it up, then record "
            "straight away while it's up — usually the most alive take."
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
        # TIGHTENED 2026-08-15 (founder). "2–4 sentences" reliably produced
        # four, and the delivered bubbles read as briefings. This is the lever
        # that actually caps the OUTPUT — shortening `intent` alone only
        # shortens the source the model is free to expand from.
        "Keep it SHORT: TWO sentences, about 40 words. This is a chat bubble "
        "someone reads in one glance, not a briefing — cut anything that is "
        "not the next action. Do not restate the protocol back to them, do "
        "not explain WHY the method works, and do not add an encouraging "
        "sign-off. A safety caveat, where one is present, is exempt from this "
        "limit and may add a sentence — never trim that.",
        "No preamble, no headers, no emoji unless the user's language norm "
        "expects it.",
    ]
    if beat.get("mode"):
        rules.append(
            f"This take's style is '{beat['mode']}' — convey that register in "
            "the user's words; you may keep a recognizable label for it."
        )
    # #3 (2026-06-21) — the "Take N of M" spine. The DENOMINATOR is always the
    # target (3), not the running count (it was showing "Take 2 of 2"), and the
    # numerator is the take they're ABOUT to record (beat N invites take N+1).
    # Framed as an imperative invitation, never a "try again?" retry question
    # (this is the next take, not a redo). Only on the post-take invite beats —
    # an invited take past the target (the optional spark) gets no spine.
    fires_after = beat.get("fires_after_take")
    if fires_after:
        invited_take = fires_after + 1
        if invited_take <= TARGET_TAKES:
            rules.append(
                f"Open with 'Take {invited_take} of {TARGET_TAKES}' so they "
                "know where they are, then give this take's direction as an "
                "IMPERATIVE invitation to record the same talk again in this "
                "style — NOT a 'try again?' retry question (it's the next take, "
                "not a redo of the last one)."
            )
    if weave_goal:
        rules.append(
            "Weave in the user's stated goal naturally (see USER GOAL) so the "
            "framing connects to what they're working toward. Echo it, never "
            "grade it. Then, in ONE short clause, let them know they can change "
            "their goal anytime by just telling you (e.g. 'and if your goal "
            "shifts, just say the word')."
        )
    elif beat.get("weave_goal"):
        # Beat wants the goal woven but none is on file yet — invite them to
        # set one so they know the goal exists + is theirs to steer.
        rules.append(
            "The user hasn't set a goal yet. In ONE short, low-pressure clause, "
            "invite them to tell you their goal so you can keep it in mind."
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
