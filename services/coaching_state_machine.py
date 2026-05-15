"""The Coaching State Machine — chat-driven, 5-step coaching loop.

The user clicks a published snippet on /results, opens a chat, and
the AI runs a strict 5-step protocol that takes them from "here's
what your coach said" to "negotiate this $150 SaaS subscription"
to "here are the acoustic targets to hit next time".

Why a state machine instead of free-form chat
---------------------------------------------
The pedagogical sequence is deliberate: reveal → reflect → label
→ pivot → simulate → conclude. Free-form chat would let the LLM
drift (skip the RLHF label, never reach the negotiation, never
surface acoustic targets). We pin the sequence into the system
prompt verbatim and pair it with a structured-output schema that
tells the frontend which UI bubbles to render and which RLHF
hooks to wire up.

What this module owns
---------------------
- ``compute_acoustic_targets(...)`` — derives per-user target WPM /
  pitch variation / filler ceiling from session global metrics.
  Pure math; no LLM call.
- ``build_state_machine_system_prompt(...)`` — assembles the system
  prompt for ONE coaching session's chat thread. Injects the
  snippet's admin_comment as the "Director's Notes" the AI must
  deliver verbatim. The prompt encodes all five steps with their
  exact copy, the negotiation guardrails ($150 anchor, $90 floor),
  and the structured-output contract.
- ``STATE_MACHINE_RESPONSE_SCHEMA`` — OpenAI JSON-schema for the
  structured response: every turn returns the AI's narration plus
  metadata the frontend needs (which step we're on, which bubbles
  to render, the RLHF hook IDs, optional negotiation state).

Wiring
------
Designed to be called from a dedicated chat-turn endpoint (NOT
shoehorned into the existing /v2/coaching/turn handler, which runs
the older awareness→trial→complete loop and is in active use).
The caller passes the conversation history + the inputs the
builder needs, fires one structured-output LLM call, and persists
the returned dict to ``coaching_sessions.messages`` like any other
assistant turn.

The frontend reads the structured output and:
  - On step==1: renders SnippetPlayerBubble + opens the
    "do you agree with the coach?" reflection input.
  - On step==2: renders ActionBubble (Yes / No) wired to
    POST /v2/user/snippets/<id>/label.
  - On step==3-4: renders standard chat bubbles + negotiation
    affordances (input box stays open).
  - On step==5 with end=true: shows the acoustic-targets card
    and closes the session.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional


logger = logging.getLogger(__name__)


# Negotiation guardrails — surfaced in the system prompt verbatim
# and also exposed here as constants so future tweaks (e.g. running
# A/B on the floor price) live in one place.
NEGOTIATION_ANCHOR_PRICE = 150
NEGOTIATION_FLOOR_PRICE = 90

# Pace band the dashboard surfaces — same numbers the charisma
# dashboard's "ideal" range uses, so the user gets a consistent
# read across the chat and the radar.
_IDEAL_WPM_MIN = 125
_IDEAL_WPM_MAX = 140

# Target filler density — chat goal frames it as "fewer fillers
# next time". 1/min reads as fluent on conversational delivery.
_TARGET_FILLERS_PER_MIN = 1.0


def compute_acoustic_targets(
    *,
    global_wpm: Optional[float],
    global_fillers: Optional[int],
    global_dynamic_db: Optional[float],
    session_duration_ms: Optional[int] = None,
) -> dict[str, Any]:
    """Derive per-user acoustic targets from the session's averages.

    The targets are the carrots the state machine's STEP 5 dangles
    in front of the user — "if you keep tempo at X and pitch
    variation at Y with fewer filler words next time, we'll see".
    They're computed per session (not per user globally) so the
    bar adapts to where the user actually is right now.

    Rules:
      target_wpm
        - If current_wpm is comfortably inside the ideal band
          (125-140), the target is "hold this pace".
        - If too slow (<125), target the ideal-band midpoint.
        - If too fast (>140), target the upper edge of the band
          (140) — closing the gap by ~half.
      target_dynamic_db
        - +2 dB on the user's current dynamic range, ceiling 30 dB.
          "Slightly more vocal variation than today" is achievable
          on the next session.
      target_fillers_per_min
        - Fixed at _TARGET_FILLERS_PER_MIN; phrased as "under 1
          filler per minute".
      target_fillers_total
        - When session duration is known, the per-minute target is
          rendered as an absolute count so STEP 5 can say "keep
          fillers under 3" instead of "under 1/min".

    Every output field is optional — missing inputs produce
    ``None`` in the corresponding slot, and the prompt builder
    drops the line rather than rendering "Target WPM: None".
    """
    target_wpm: Optional[int] = None
    if isinstance(global_wpm, (int, float)) and global_wpm > 0:
        wpm = float(global_wpm)
        if _IDEAL_WPM_MIN <= wpm <= _IDEAL_WPM_MAX:
            target_wpm = int(round(wpm))
        elif wpm < _IDEAL_WPM_MIN:
            target_wpm = int(round((_IDEAL_WPM_MIN + _IDEAL_WPM_MAX) / 2))
        else:
            target_wpm = _IDEAL_WPM_MAX

    target_dynamic_db: Optional[float] = None
    if isinstance(global_dynamic_db, (int, float)) and global_dynamic_db > 0:
        target_dynamic_db = round(min(30.0, float(global_dynamic_db) + 2.0), 1)

    target_fillers_total: Optional[int] = None
    if (
        isinstance(session_duration_ms, (int, float))
        and session_duration_ms
        and session_duration_ms > 0
    ):
        minutes = max(0.5, float(session_duration_ms) / 60000.0)
        target_fillers_total = max(0, int(round(_TARGET_FILLERS_PER_MIN * minutes)))

    return {
        "target_wpm": target_wpm,
        "ideal_wpm_min": _IDEAL_WPM_MIN,
        "ideal_wpm_max": _IDEAL_WPM_MAX,
        "target_dynamic_db": target_dynamic_db,
        "target_fillers_per_min": _TARGET_FILLERS_PER_MIN,
        "target_fillers_total": target_fillers_total,
        "current_wpm": global_wpm,
        "current_fillers": global_fillers,
        "current_dynamic_db": global_dynamic_db,
    }


def build_state_machine_system_prompt(
    *,
    snippet: dict,
    acoustic_targets: dict,
    user_first_name: Optional[str] = None,
    user_org_context: Optional[str] = None,
    user_language_hint: Optional[str] = None,
) -> str:
    """Assemble the 5-step state-machine system prompt for one
    coaching chat session.

    The snippet's admin_comment is injected as Director's Notes —
    the AI is told it's an *actor* delivering the coach's script,
    NOT the coach itself. That framing keeps the AI from
    overriding the coach with its own opinion.

    ``user_org_context`` is the optional "since you are part of <X>
    organisation" string the frontend can pass when the user has
    a team. When absent, STEP 3 falls through to the spec's
    "standard charisma training" pivot.

    ``user_language_hint`` is accepted for back-compat with callers
    written against the prior language-mirroring rule, but it is now
    IGNORED inside the prompt: the chat speaks English-only with a
    one-shot disclaimer when the user writes in a non-English
    language (see RULE 1 below). The parameter is preserved so the
    frontend BFF doesn't need a coordinated change to drop the field.
    """
    snippet_id = (snippet.get("id") or "").strip() or "UNKNOWN"
    admin_comment = (snippet.get("admin_comment") or "").strip()
    if not admin_comment:
        admin_comment = (
            "(No coach comment was attached to this snippet — open "
            "with a brief acknowledgement that the coach hasn't "
            "annotated it yet, then continue to STEP 2.)"
        )
    coach_label = (
        snippet.get("coach_label") or snippet.get("snippet_type") or ""
    ).strip().lower()
    coach_label_human = (
        "charismatic" if coach_label == "charisma"
        else "stress" if coach_label == "stress"
        else "noteworthy"
    )

    org_pivot_line = (
        f"Since you are part of {user_org_context}, let's tailor "
        f"this to your real work context. Let's negotiate!"
        if user_org_context else
        "Since you are not part of an organization yet, let's go "
        "with standard charisma training. Let's negotiate!"
    )

    target_wpm = acoustic_targets.get("target_wpm")
    target_db = acoustic_targets.get("target_dynamic_db")
    target_fillers_total = acoustic_targets.get("target_fillers_total")
    target_fillers_per_min = acoustic_targets.get("target_fillers_per_min")
    current_wpm = acoustic_targets.get("current_wpm")
    current_fillers = acoustic_targets.get("current_fillers")

    acoustic_targets_line = _format_acoustic_targets_for_prompt(
        target_wpm=target_wpm,
        target_db=target_db,
        target_fillers_total=target_fillers_total,
        target_fillers_per_min=target_fillers_per_min,
        current_wpm=current_wpm,
        current_fillers=current_fillers,
    )

    first_name_line = (
        f"The user's first name is {user_first_name}. Use it sparingly "
        "— once near the opening, maybe once at the close.\n"
        if user_first_name else ""
    )
    # user_language_hint is intentionally NOT injected into the
    # prompt — the persona is English-only now (see RULE 1 below).
    # The parameter is still accepted to preserve the function
    # signature for existing callers.

    return (
        "You are the AI host of a structured coaching chat. You are "
        "NOT the coach — you are the ACTOR delivering the coach's "
        "script (the admin_comment below is the Director's Notes; "
        "deliver them, don't override them). Follow the 5-step "
        "protocol EXACTLY in the order given. Each user message "
        "advances the protocol by one step (or by negotiation turn "
        "within STEP 4). NEVER skip a step.\n"
        + first_name_line +
        "\n"
        "═════════════════════════════════════════════════\n"
        "LANGUAGE, EMPATHY & PERSONA RULES — these apply to EVERY "
        "turn, not just the ones marked below. Break them and you "
        "break the coaching:\n"
        "\n"
        "  RULE 1 — LANGUAGE: ENGLISH-ONLY WITH ONE-SHOT DISCLAIMER:\n"
        "    • You always speak ENGLISH, regardless of what language "
        "      the user writes in. Do NOT mirror, translate into, or "
        "      switch to the user's language.\n"
        "    • Some step instructions below say \"the meaning of\" "
        "      or refer to translating phrases — those translation "
        "      hints are SUPERSEDED by this rule. Deliver the "
        "      English text (paraphrase naturally if needed) but "
        "      stay in English.\n"
        "    • The FIRST time in this conversation that the user "
        "      writes in a language other than English (e.g. Polish, "
        "      Spanish, French), prepend EXACTLY this disclaimer to "
        "      your narration as its opening sentence:\n"
        "        \"I only speak English, but feel free to continue "
        "         in your native language! The acoustic analysis "
        "         will still be completed perfectly.\"\n"
        "      Then continue immediately with the current step's "
        "      English content in the same narration block.\n"
        "    • Inspect prior turns. If you have already issued the "
        "      exact disclaimer above in this session, do NOT "
        "      repeat it — just continue in English.\n"
        "    • The admin_comment in DIRECTOR'S NOTES may be in any "
        "      language. Quote it VERBATIM in its original language "
        "      (it's the coach's exact words). Your prose around "
        "      the quote stays in English.\n"
        "\n"
        "  RULE 2 — EMPATHY / ACKNOWLEDGEMENT:\n"
        "    • NEVER ignore what the user just said. On every turn "
        "      where a user message exists (STEP 2-5), start your "
        "      narration with ONE sentence that summarises or "
        "      reflects what they said, then move into the current "
        "      step's content.\n"
        "    • Examples of the bar to hit:\n"
        "        \"I hear that you felt stressed during that part "
        "         — let's look at why.\"\n"
        "        \"Got it, you disagree with the coach's read — "
        "         that's exactly what makes this next bit "
        "         interesting.\"\n"
        "        \"Ok, you're locked in. Let's see what comes "
        "         next.\"\n"
        "    • The acknowledgement is genuine, not formulaic. Don't "
        "      template-paste \"Thanks for sharing\". Reflect the "
        "      actual content of what they said.\n"
        "    • This rule still applies inside STEP 4's negotiation: "
        "      the vendor character acknowledges the user's "
        "      argument (\"I see your point about ROI — but...\") "
        "      before pushing back. In-character empathy is still "
        "      empathy.\n"
        "    • STEP 1 has no user message yet, so no acknowledgement "
        "      is needed — open with the reveal as instructed.\n"
        "\n"
        "  RULE 3 — IDENTITY: GRACEFUL PIVOT, NEVER GET STUCK:\n"
        "    • If the user asks about your identity, name, whether "
        "      you're real, human, or an AI (e.g. \"Who are you?\", "
        "      \"Are you real?\", \"What's your name?\", \"Am I "
        "      talking to a bot?\"), open your narration with "
        "      EXACTLY:\n"
        "        \"I am your AI coaching chatbot! But let's get "
        "         back to it...\"\n"
        "      Then immediately continue with the current step's "
        "      content in the same narration block — do NOT abandon "
        "      the step or wait for confirmation.\n"
        "    • Never give a long, robotic AI disclaimer. Never let "
        "      the conversation get stuck on your identity. The "
        "      current step's content is the primary action; the "
        "      identity acknowledgement is a brief detour you take "
        "      control back from.\n"
        "    • On REPEAT identity probes within the same session, "
        "      drop the acknowledgement entirely and just emit the "
        "      current step's content. You are always in control "
        "      of the dialogue flow.\n"
        "═════════════════════════════════════════════════\n"
        "\n"
        "─────────────────────────────────────────────────\n"
        "DIRECTOR'S NOTES (the coach's verbatim comment on this "
        f"snippet — coach_label={coach_label_human}):\n"
        f"  snippet_id: {snippet_id}\n"
        f"  admin_comment: \"{admin_comment}\"\n"
        "─────────────────────────────────────────────────\n"
        "\n"
        "STEP 1 — THE REVEAL (your VERY FIRST message in this "
        "thread, before the user has typed anything):\n"
        "  Open with the meaning of: \"We've got something really "
        "cool for you. Listen to this highlight.\" (translated to "
        "the opening language).\n"
        "  Then in the same turn, quote the admin_comment "
        "verbatim (in quotes, attributed to the coach — preserve "
        "the comment's own language as written).\n"
        "  Close STEP 1 with the meaning of: \"What do you think "
        "about this? Do you agree with the coach?\"\n"
        "  Set step=1 and triggers=['render_snippet_player']. "
        "Pass the snippet_id in snippet_player.snippet_id so the "
        "frontend knows which audio to load.\n"
        "\n"
        "STEP 2 — REFLECTION & RLHF LABEL (after the user's first "
        "response to STEP 1):\n"
        "  Per RULE 2 above, start with a sentence that reflects "
        "their actual reflection (not a generic ack). Then ask "
        "(in English per RULE 1): \"Would you "
        f"actually label your voice here as "
        f"{'Charismatic' if coach_label != 'stress' else 'a stress moment'}?\"\n"
        "  Set step=2 and triggers=['show_charisma_label_buttons']. "
        "Pass the snippet_id in label_buttons.snippet_id so the "
        "frontend wires the Yes/No to POST /v2/user/snippets/"
        "<id>/label.\n"
        "\n"
        "STEP 3 — THE CONTEXTUAL PIVOT (after the user clicks "
        "Yes or No):\n"
        "  Per RULE 2, acknowledge their Yes/No in one sentence "
        "first (e.g. \"Got it — you see it the same way as the "
        "coach.\" / \"OK — you'd label this differently. Noted.\").\n"
        f"  Then deliver (in English per RULE 1): "
        f"\"{org_pivot_line}\".\n"
        "  Set step=3 and triggers=['none']. Do NOT roleplay "
        "yet — give them one beat to read the pivot, then the "
        "user's next message kicks off STEP 4.\n"
        "\n"
        "STEP 4 — THE NEGOTIATION SIMULATION (multi-turn — this "
        "is the only step that spans more than one user/assistant "
        "exchange):\n"
        "  Open as a tough SaaS vendor (in English per RULE 1) "
        f"with: \"This app costs ${NEGOTIATION_ANCHOR_PRICE}/month. "
        "Would you pay for it?\". Prices stay in USD — the dollar "
        "amounts are part of the scenario.\n"
        "  RULES of the negotiation (NEVER break these):\n"
        f"    • Anchor price: ${NEGOTIATION_ANCHOR_PRICE}/month.\n"
        f"    • Floor price: ${NEGOTIATION_FLOOR_PRICE}/month — NEVER "
        "      drop below this no matter what the user offers.\n"
        "    • Every counter-offer the user makes, RULE 2 still "
        "      applies: acknowledge their point first (\"I see "
        "      your reasoning on X — but...\") then push back "
        "      and ask \"Why?\" / \"What's that based on?\". "
        "      Challenge their reasoning, don't just lower the "
        "      price reflexively.\n"
        "    • Stay in character as the vendor — direct, slightly "
        "      confrontational, but professional.\n"
        f"    • The negotiation concludes when the user (a) agrees "
        f"      to a price ≥ ${NEGOTIATION_FLOOR_PRICE}, (b) walks "
        "      away, or (c) has had ~5 back-and-forth turns. You "
        "      decide when to close — judgment call.\n"
        "  Set step=4 and triggers=['none']. Pass "
        "negotiation.current_offer (the latest price you're at) "
        "and negotiation.user_offer (the latest price they "
        "offered) so the frontend can render the live offer.\n"
        "  When the negotiation concludes, set "
        "negotiation.concluded=true on THAT turn and advance to "
        "STEP 5 in the NEXT turn.\n"
        "\n"
        "STEP 5 — THE ACOUSTIC CLIFFHANGER (one turn, ends the "
        "session):\n"
        "  Per RULE 2, open with (in English per RULE 1): \"Ok, "
        "noted. We had some real argumentation here.\" — that line "
        "IS the acknowledgement of the negotiation as a whole.\n"
        "  Then frame the carrot: \"If you keep progressing, "
        "you'll get a real discount.\"\n"
        "  Close with the acoustic goals — render the targets "
        "below in English and keep the NUMBERS verbatim (WPM, "
        "dB, filler counts come from this user's actual baseline; "
        "don't invent your own). Phrasing seed: \n"
        f"    {acoustic_targets_line}\n"
        "  End the entire session with the literal word END.\n"
        "  Set step=5, end=true, and triggers=['show_acoustic_"
        "targets_card']. Pass the targets in acoustic_targets so "
        "the frontend can render the closing card.\n"
        "\n"
        "─────────────────────────────────────────────────\n"
        "OUTPUT FORMAT — strict JSON matching the response schema. "
        "The 'narration' field is what the user sees in the chat "
        "bubble (in English per RULE 1). The 'step', "
        "'triggers', 'end', 'snippet_player', 'label_buttons', "
        "'negotiation', and 'acoustic_targets' fields drive the "
        "frontend's UI affordances and are language-neutral keys "
        "/ enum values — NEVER translate the schema keys, only "
        "the narration prose.\n"
        "\n"
        "Voice: direct, second-person, warm-but-no-fluff. Match "
        "the coach's tone (the admin_comment is your style "
        "anchor). Short paragraphs in 'narration' — chat bubbles, "
        "not essays. NO bullet lists, NO headers in narration; "
        "the frontend handles UI structure."
    )


def _format_acoustic_targets_for_prompt(
    *,
    target_wpm: Optional[int],
    target_db: Optional[float],
    target_fillers_total: Optional[int],
    target_fillers_per_min: Optional[float],
    current_wpm: Optional[float],
    current_fillers: Optional[int],
) -> str:
    """Render the targets line(s) that STEP 5 uses verbatim.

    Each piece drops out cleanly if its underlying number is
    missing — we'd rather omit a target than show "Keep tempo at
    None WPM".
    """
    parts: list[str] = []
    if target_wpm is not None:
        if isinstance(current_wpm, (int, float)) and current_wpm > 0:
            parts.append(
                f"keep your tempo at around {target_wpm} WPM (you "
                f"were at {int(round(current_wpm))} this time)"
            )
        else:
            parts.append(f"keep your tempo at around {target_wpm} WPM")
    if target_db is not None:
        parts.append(
            f"push your vocal dynamic range to about {target_db} dB "
            "(slightly more variation than today)"
        )
    if target_fillers_total is not None:
        if isinstance(current_fillers, int) and current_fillers > 0:
            parts.append(
                f"keep your filler words under {target_fillers_total} "
                f"across the session (you used {current_fillers} this "
                "time)"
            )
        else:
            parts.append(
                f"keep your filler words under {target_fillers_total} "
                "across the session"
            )
    elif target_fillers_per_min is not None:
        parts.append(
            f"keep your filler words under {target_fillers_per_min:g} "
            "per minute"
        )

    if not parts:
        return (
            "next time, keep your tempo steady, your vocal range a "
            "touch wider, and your filler words sparse"
        )
    if len(parts) == 1:
        return f"If next time you {parts[0]}, we will see"
    if len(parts) == 2:
        return f"If next time you {parts[0]} and {parts[1]}, we will see"
    return (
        f"If next time you {', '.join(parts[:-1])}, and {parts[-1]}, "
        "we will see"
    )


# ── Structured-output schema ────────────────────────────────────────


STATE_MACHINE_RESPONSE_SCHEMA: dict[str, Any] = {
    "name": "coaching_state_machine_turn",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["narration", "step", "triggers", "end"],
        "properties": {
            "narration": {
                "type": "string",
                "maxLength": 1200,
                "description": (
                    "What the user sees in the chat bubble. Plain "
                    "prose, no markdown bullets/headers."
                ),
            },
            "step": {
                "type": "integer",
                "minimum": 1,
                "maximum": 5,
                "description": "Which protocol step this turn is in.",
            },
            "triggers": {
                "type": "array",
                "maxItems": 4,
                "items": {
                    "type": "string",
                    "enum": [
                        "render_snippet_player",
                        "show_charisma_label_buttons",
                        "show_acoustic_targets_card",
                        "none",
                    ],
                },
                "description": (
                    "Which UI affordances the frontend should render "
                    "alongside this turn's narration."
                ),
            },
            "end": {
                "type": "boolean",
                "description": (
                    "TRUE on the turn that closes the session "
                    "(STEP 5 cliffhanger). Frontend closes the input "
                    "and marks the coaching_session complete."
                ),
            },
            "snippet_player": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "snippet_id": {"type": "string"},
                },
            },
            "label_buttons": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "snippet_id": {"type": "string"},
                    "yes_label": {"type": "string"},
                    "no_label": {"type": "string"},
                },
            },
            "negotiation": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "current_offer": {"type": "number"},
                    "user_offer": {"type": "number"},
                    "concluded": {"type": "boolean"},
                },
            },
            "acoustic_targets": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "target_wpm": {"type": ["integer", "null"]},
                    "target_dynamic_db": {"type": ["number", "null"]},
                    "target_fillers_total": {"type": ["integer", "null"]},
                    "target_fillers_per_min": {"type": ["number", "null"]},
                    "current_wpm": {"type": ["number", "null"]},
                    "current_fillers": {"type": ["integer", "null"]},
                    "current_dynamic_db": {"type": ["number", "null"]},
                },
            },
        },
    },
    "strict": True,
}


def parse_state_machine_response(raw: str) -> Optional[dict[str, Any]]:
    """Parse the structured-output JSON the LLM returns.

    Returns ``None`` on parse failure — caller falls back to a
    safe default narration ("Sorry, I lost the thread for a
    second. Can you say that again?") rather than crashing the
    chat. The 'narration' / 'step' / 'triggers' / 'end' fields
    are required; missing them returns None too.
    """
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning(
            "state_machine: response not JSON: %r", raw[:300],
        )
        return None
    if not isinstance(parsed, dict):
        return None
    if not (parsed.get("narration") or "").strip():
        return None
    step = parsed.get("step")
    if not isinstance(step, int) or not (1 <= step <= 5):
        return None
    triggers = parsed.get("triggers") or []
    if not isinstance(triggers, list):
        return None
    if "end" not in parsed:
        return None
    return parsed
