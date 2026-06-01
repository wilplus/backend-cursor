"""FIX.1 — Contextual follow-up generator for the interview funnel.

After the tester reported "bicycle → boardroom" non-sequiturs, this
module replaces the rigid alternation in the legacy /next-question
route. The new contract: every question MUST bridge from what the
user just said while eliciting whichever intent (charisma | stress)
is still missing from the session's snippet inventory.

The conflict the legacy prompt couldn't resolve was:
  - "MUST alternate tones" (charisma → stress → charisma → ...)
  - "Push the conversation forward contextually"

Forced alternation wins → bridge breaks → user experiences the
non-sequitur. Here, the target intent is derived from WHAT'S MISSING
(via the completion gate), not from a fixed alternation arc. If the
user is on a roll about cycling and we still need a stress snippet,
the LLM gets BOTH the bridge constraint AND the intent target, and
the prompt explicitly forbids stock prompts that don't reference
the user's last turn.

Failure semantics
-----------------
- LLM down → returns a domain-agnostic but on-intent fallback
  ("Tell me about a moment when..." charisma OR
   "What's a decision you still question?" stress) with
  source="contextual_llm_fallback" so we can audit fallback rate.
- Bridge weak (LLM returns generic question) → still ships;
  the bridge_to debug field reveals when the model couldn't anchor.
- No previous turn (turn 1) → falls back to the soft opener path
  per FE handoff Q1 (single canonical opener); not optimized here.
"""
from __future__ import annotations

import logging
from typing import Any, Optional


logger = logging.getLogger(__name__)


# Charisma fallback questions used when the LLM is unavailable.
# Deliberately not great — the fallback exists to keep the funnel
# moving, not to be the primary experience. If we hit these often,
# the LLM is broken and we should be paged, not pretending it isn't.
_CHARISMA_FALLBACKS = (
    "What's the last thing you did that made you proud of yourself?",
    "Who in your life would you most want to make laugh, and why?",
    "What's a story you find yourself telling more than once?",
)

_STRESS_FALLBACKS = (
    "What's a decision you've made that you still sometimes question?",
    "When was the last time you felt out of your depth?",
    "What's something you believe that you'd have trouble defending?",
)


_SURFACE = "contextual_followup"


def generate_contextual_followup(
    *,
    guest_session_id: Optional[str],
    previous_turns: Optional[list[dict]] = None,
    threshold_seconds: int = 60,
) -> dict[str, Any]:
    """Produce ONE next question + the completion-state snapshot.

    Args
    ----
    guest_session_id : str | None
        The session whose snippets drive the target-intent decision.
        ``None`` on turn 1 (no session row yet) — caller should
        prefer the soft-opener path in that case, but we degrade
        gracefully if invoked anyway.
    previous_turns : list[{question, transcript}] | None
        The conversation so far. The LAST entry's transcript is the
        primary bridge anchor; earlier turns are context. Pass the
        last 2-3 turns max for cost.
    threshold_seconds : int
        Forwarded to the completion-state helper. Keep at 60s unless
        a test override is in play.

    Returns
    -------
    dict with keys::

        {
          "question":          str,
          "target_intent":     "charisma" | "stress",
          "bridge_to":         str,                  # debug: 5-12 word
                                                     # ref to user's last
                                                     # turn, or "" on
                                                     # fallback
          "source":            "contextual_llm"
                               | "contextual_llm_fallback"
                               | "soft_opener",
          "completion_state":  { ready, criteria, current }
        }

    Never raises. Best-effort all the way.
    """
    state = _safe_completion_state(guest_session_id, threshold_seconds)
    target = _pick_target_intent(state)

    last_transcript = _extract_last_transcript(previous_turns)

    # Turn-1 / no-prior-context path. Per FE handoff Q1: caller
    # routes through the soft-opener endpoint here, but if we get
    # called anyway, return a sensible default on the target intent.
    if not last_transcript:
        return _soft_opener_response(target, state)

    # LLM bridge attempt.
    llm_result = _llm_generate_bridge_question(
        last_transcript=last_transcript,
        previous_turns=previous_turns or [],
        target_intent=target,
        guest_session_id=guest_session_id,
    )
    if llm_result is not None:
        return {
            "question":         llm_result["question"],
            "target_intent":    target,
            "bridge_to":        llm_result.get("bridge_to", ""),
            "source":           "contextual_llm",
            "completion_state": state,
        }

    # LLM unavailable / parse failure / empty response. Per FE
    # handoff Q3: ship the fallback with the explicit source tag
    # so we can audit fallback rate.
    return _fallback_response(target, state)


# ── Internals ──────────────────────────────────────────────────────


def _safe_completion_state(
    guest_session_id: Optional[str],
    threshold_seconds: int,
) -> dict[str, Any]:
    """Read the gate, never raise.

    Returns an "empty session" shape when guest_session_id is None
    or the lookup fails so the caller can always proceed with a
    target intent."""
    if not guest_session_id:
        return _empty_completion_state(threshold_seconds)
    try:
        from services.interview_completion_gate import completion_state
        return completion_state(
            guest_session_id, threshold_seconds=threshold_seconds,
        )
    except Exception as e:
        logger.warning(
            "contextual_followup: completion_state lookup failed "
            "sid=%s err=%s — returning empty default",
            guest_session_id, e,
        )
        return _empty_completion_state(threshold_seconds)


def _empty_completion_state(threshold_seconds: int) -> dict[str, Any]:
    return {
        "ready": False,
        "criteria": {
            "has_charisma": False,
            "has_stress":   False,
            "duration_ok":  False,
        },
        "current": {
            "charisma_count":   0,
            "stress_count":     0,
            "total_duration_ms": 0,
            "threshold_seconds": threshold_seconds,
        },
    }


def _pick_target_intent(state: dict[str, Any]) -> str:
    """Pick the intent the next question should elicit.

    Rules (left-to-right, first-match wins):

      1. No charisma snippets yet → 'charisma' (missing intent has
         absolute priority — the gate cares about presence, not depth)
      2. No stress snippets yet → 'stress'
      3. Both present → pick the rarer one (deepen the weaker side)
      4. Tie → 'charisma' (defaults to the gentler intent to avoid
         loading the back-half of a session with stress)

    The "rarer of the two" rule in (3) lets the user keep going past
    the gate threshold while still pushing toward balance, which is
    the brainstorm's "charisma/stress ratio smoothed over time" KPI
    semantics.
    """
    current = state.get("current") or {}
    charisma_count = int(current.get("charisma_count") or 0)
    stress_count = int(current.get("stress_count") or 0)

    if charisma_count == 0:
        return "charisma"
    if stress_count == 0:
        return "stress"
    if charisma_count < stress_count:
        return "charisma"
    if stress_count < charisma_count:
        return "stress"
    return "charisma"


def _extract_last_transcript(
    previous_turns: Optional[list[dict]],
) -> str:
    """Pull the most recent non-empty user transcript from the
    previous_turns list. Returns '' when nothing usable is present
    — caller routes to the soft-opener path in that case."""
    if not previous_turns or not isinstance(previous_turns, list):
        return ""
    for turn in reversed(previous_turns):
        if not isinstance(turn, dict):
            continue
        transcript = (turn.get("transcript") or "").strip()
        if transcript:
            return transcript
    return ""


def _soft_opener_response(
    target_intent: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Turn-1 / no-prior-context response.

    Per FE handoff: a single canonical opener is fine. We pick from
    the same fallback pool the LLM-down path uses so the user gets a
    real on-intent question even when there's no transcript to
    bridge from."""
    bank = (
        _CHARISMA_FALLBACKS if target_intent == "charisma"
        else _STRESS_FALLBACKS
    )
    return {
        "question":         bank[0],
        "target_intent":    target_intent,
        "bridge_to":        "",
        "source":           "soft_opener",
        "completion_state": state,
    }


def _fallback_response(
    target_intent: str,
    state: dict[str, Any],
) -> dict[str, Any]:
    """LLM-failed response — same fallback bank as the soft opener
    but tagged so analytics can split the two."""
    bank = (
        _CHARISMA_FALLBACKS if target_intent == "charisma"
        else _STRESS_FALLBACKS
    )
    return {
        "question":         bank[0],
        "target_intent":    target_intent,
        "bridge_to":        "",
        "source":           "contextual_llm_fallback",
        "completion_state": state,
    }


def _llm_generate_bridge_question(
    *,
    last_transcript: str,
    previous_turns: list[dict],
    target_intent: str,
    guest_session_id: Optional[str],
) -> Optional[dict[str, str]]:
    """One LLM call. Returns {question, bridge_to} or None on any
    failure mode. Inherits Will's Voice anchor."""
    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_CONTEXTUAL_FOLLOWUP
        from services.will_voice import with_voice_rules
    except Exception as e:
        logger.warning(
            "contextual_followup: llm import failed err=%s", e,
        )
        return None

    intent_brief = (
        "CHARISMA — a question that lets the user talk about "
        "something they CARE about (pride, passion, a story they "
        "love telling, a person they admire). Their voice will "
        "naturally open: pitch range expands, pace finds a rhythm, "
        "energy rises."
        if target_intent == "charisma"
        else
        "STRESS — a question that puts cognitive or emotional "
        "pressure (a hard memory, a moral conflict, being "
        "challenged on something they believe, a public-speaking "
        "near-miss). Their voice will tighten: pitch flattens, "
        "pace constricts, dynamic range narrows. NOT trauma-bait; "
        "just enough friction that we hear the shift."
    )

    system = with_voice_rules(
        "You are leading a 60-second voice diagnostic. The user "
        "just said something. Your job is to produce ONE follow-up "
        "question that does TWO things at once:\n"
        "\n"
        "1. NATURAL BRIDGE — reference something specific the user "
        "   said. Same domain, same emotional terrain when possible. "
        "   Never feel like a non-sequitur. If they talked about "
        "   cycling, stay in the cycling universe or an obviously-"
        "   bridged adjacent universe (the body, the outdoors, "
        "   ambition, solitude). If they mentioned a person, use "
        "   that person. If they named a place, use that place.\n"
        "\n"
        f"2. ELICIT THE TARGET INTENT — your question must be a "
        f"{target_intent.upper()}-eliciting question, defined as:\n"
        f"   {intent_brief}\n"
        "\n"
        "3. CONVERSATIONAL, not interrogative. One sentence "
        "   ideally, two max. Like a thoughtful coach reflecting "
        "   back, not a survey questionnaire.\n"
        "\n"
        "EXAMPLES OF GOOD BRIDGES:\n"
        "\n"
        "  User said: \"Riding my bike is how I clear my head.\"\n"
        "  Target: STRESS\n"
        "  GOOD: \"When you're on a tough climb and your head ISN'T "
        "         clearing, what's the moment you start being hard "
        "         on yourself?\"\n"
        "  BAD:  \"Imagine someone challenges your authority in a "
        "         board room.\" (← non-sequitur; tester complained "
        "         about exactly this)\n"
        "\n"
        "  User said: \"My daughter started piano lessons last "
        "             week.\"\n"
        "  Target: CHARISMA\n"
        "  GOOD: \"What's the first moment you'll know she's "
        "         hooked on it?\"\n"
        "  BAD:  \"Tell me about a passion of yours.\" (← stock "
        "         prompt; ignores what the user gave you)\n"
        "\n"
        "FORBIDDEN:\n"
        "  - Any question that doesn't reference the user's last "
        "    turn somehow\n"
        "  - Any question that starts \"Imagine you...\" when the "
        "    user gave you real material to work with\n"
        "  - Any stock prompt from a question bank\n"
        "  - Praise inflation (\"Great answer!\", \"What a story!\")\n"
        "\n"
        "Output strict JSON with two keys:\n"
        "  question:  the one follow-up question, ≤2 sentences\n"
        "  bridge_to: a 5-12 word phrase identifying what in the "
        "             user's last turn you bridged from (debug "
        "             only; the user never sees this)\n"
    )

    history_block = _format_history_for_prompt(previous_turns)
    user_prompt = (
        f"TARGET INTENT: {target_intent}\n"
        "\n"
        f"USER'S MOST RECENT ANSWER:\n  \"{last_transcript}\"\n"
        "\n"
        f"FULL CONVERSATION SO FAR (newest last):\n{history_block}\n"
        "\n"
        "Write the ONE follow-up question now. Strict JSON."
    )

    result = chat_complete(
        spec=SPEC_CONTEXTUAL_FOLLOWUP,
        system=system,
        user=user_prompt,
        surface=_SURFACE,
        response_format_override={"type": "json_object"},
        user_id=str(guest_session_id) if guest_session_id else None,
    )
    if not result:
        return None
    parsed = result.parsed
    if not isinstance(parsed, dict):
        return None
    question = (str(parsed.get("question") or "")).strip()
    bridge_to = (str(parsed.get("bridge_to") or "")).strip()
    if not question:
        return None
    return {"question": question, "bridge_to": bridge_to}


def _format_history_for_prompt(previous_turns: list[dict]) -> str:
    """Render previous_turns as a compact history block. Caps at the
    last 3 turns to keep token cost bounded (BE rules; FE may send
    more but we trim here)."""
    if not previous_turns:
        return "  (none yet)"
    trimmed = previous_turns[-3:]
    lines: list[str] = []
    for idx, t in enumerate(trimmed, start=1):
        if not isinstance(t, dict):
            continue
        q = (t.get("question") or "").strip()
        a = (t.get("transcript") or "").strip()
        if len(q) > 200:
            q = q[:200].rstrip() + "…"
        if len(a) > 360:
            a = a[:360].rstrip() + "…"
        lines.append(f"  Turn {idx}:")
        if q:
            lines.append(f"    Will: {q}")
        if a:
            lines.append(f"    User: \"{a}\"")
    return "\n".join(lines) if lines else "  (none yet)"
