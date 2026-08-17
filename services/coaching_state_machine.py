"""The Coaching State Machine — chat-driven, 5-step coaching loop.

The user clicks a published snippet on /results, opens a chat, and
the AI runs a strict 5-step protocol that takes them from "here's
what your coach said" to "negotiate this $150 SaaS subscription"
to a qualitative framing for the next take.

Why a state machine instead of free-form chat
---------------------------------------------
The pedagogical sequence is deliberate: reveal → reflect → label
→ pivot → simulate → conclude. Free-form chat would let the LLM
drift (skip the RLHF label, never reach the negotiation, never
reach the re-record ask). We pin the sequence into the system
prompt verbatim and pair it with a structured-output schema that
tells the frontend which UI bubbles to render and which RLHF
hooks to wire up.

What this module owns
---------------------
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
  - On step==2: renders ActionBubble ("Yes, accurate" / "Not
    quite") wired to POST /v2/user/snippets/<id>/confidence-review
    with {"ai_correct": true|false} — the Voice Album routing beat.
    It validates the AI's pick, not the user's self-image, and is
    never a training/calibration/quorum vote. Trigger renamed to
    show_confidence_review_buttons; the old
    show_charisma_label_buttons pointed at a deleted route.
  - On step==3..7: renders standard chat bubbles for each
    Director's Script question; input box stays open.
  - On step==8: renders the qualitative next-take framing (the
    bridge — end=false, input stays open for the reaction).
    The numeric acoustic-targets card was DELETED 2026-08-06 by
    founder decision; see _NEXT_TAKE_SEED.
  - On step==9 with show_trial_recording_mic in triggers:
    swaps the text input for the mic affordance and POSTs the
    recording to /v2/coaching/trial-recording. The session is
    marked complete out-of-band when that POST arrives, NOT on
    this turn (end=false; this turn closes the input only).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional


logger = logging.getLogger(__name__)


# Legacy negotiation guardrails — kept exported for back-compat
# with any tooling that imports them, but no longer surfaced in
# the system prompt. The hardcoded SaaS-vendor roleplay was
# replaced by the admin-directed 5-question Director's Script.
NEGOTIATION_ANCHOR_PRICE = 150
NEGOTIATION_FLOOR_PRICE = 90

# Cap on how many script questions the prompt will walk through.
# Schema-side cap is also 5 (see migration). If more get passed,
# we truncate; if fewer, we walk through what we have and skip
# the missing positions.
_MAX_SCRIPT_QUESTIONS = 5

# ── STEP 2: the Voice Album routing beat (signed copy) ───────────────────
#
# STEP 2 used to ask "would you label your voice here as Charismatic?" and
# wire its Yes/No to POST /v2/user/snippets/<id>/label. That route died with
# the stress lane (2026-08-03); the button had been inert since. The founder
# signed off this replacement: the beat validates the AI's pick and routes an
# agreed moment to the Voice Album. It never feeds learning, calibration or
# quorum (POST /v2/user/snippets/<id>/confidence-review).
#
# THESE THREE STRINGS ARE SIGNED USER-FACING COPY (LIVE LOOP). Do not reword
# them, and do not let the model reword them: the question is marked VERBATIM
# in the prompt, and the two button labels are stamped onto the response
# server-side (routes/v2_routes.py) rather than trusted from the model — an
# LLM that paraphrases "Not quite" into something friendlier would be
# shipping unsigned copy to a live chat.
STEP2_QUESTION = "Did the AI pick the right moment here?"
STEP2_YES_LABEL = "Yes, accurate"
STEP2_NO_LABEL = "Not quite"

# The trigger is RENAMED, not reused: `show_charisma_label_buttons` described
# a different question against a deleted endpoint. The FE has to change
# either way (the POST target moved), and a rename makes it render nothing
# until it does — strictly better than rendering the old dead button.
CONFIDENCE_REVIEW_TRIGGER = "show_confidence_review_buttons"


def build_state_machine_system_prompt(
    *,
    snippet: dict,
    director_script_questions: Optional[list[dict]] = None,
    user_first_name: Optional[str] = None,
    user_org_context: Optional[str] = None,
    user_language_hint: Optional[str] = None,
    coaching_id: Optional[str] = None,
    admin_dont_ask_notes: Optional[str] = None,
) -> str:
    """Assemble the 9-step state-machine system prompt for one
    coaching chat session.

    The snippet's admin_comment is injected as Director's Notes —
    the AI is told it's an *actor* delivering the coach's script,
    NOT the coach itself. That framing keeps the AI from
    overriding the coach with its own opinion.

    ``director_script_questions`` is the admin-directed sequence
    of up to 5 questions the chat walks the user through after
    the RLHF label step. Shape: list of {position: 1..5, text,
    intent_tag?}. The admin's edited version (saved on Publish)
    is preferred over the AI's pre-generated draft — the route
    handler resolves which to pass in.
    When the script is empty / missing, the prompt falls through
    to a single open question and proceeds straight to the
    next-take bridge + re-record ask.

    ``coaching_id`` is echoed back to the frontend on STEP 9 via
    ``trial_recording.coaching_id`` so the recording POST knows
    which coaching session the take belongs to. Optional only so
    direct callers (tests) don't have to wire it; the live route
    always passes it.

    ``user_org_context`` is accepted for back-compat (frontend BFF
    still passes it from the previous SaaS-negotiation design) but
    is no longer used — the script REPLACES the org-context pivot.
    Passing it is harmless.

    ``user_language_hint`` is accepted for back-compat with callers
    written against the prior language-mirroring rule, but it is now
    IGNORED inside the prompt: the chat speaks English-only with a
    one-shot disclaimer when the user writes in a non-English
    language (see RULE 1 below).

    ``admin_dont_ask_notes`` is the verbatim text from
    user_settings.private_admin_notes (the "Private Admin Notes"
    Tab 3 textarea). When non-empty, an [ADMIN-PRIVATE CONTEXT]
    block is appended at the very end of the prompt instructing the
    model to navigate around the listed topics silently — never
    quote, repeat, or reference. None / empty / whitespace-only
    skips the block entirely. Route handler fetches via
    db.get_user_settings(user_id).get("private_admin_notes").
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

    # user_org_context is preserved on the signature for back-compat
    # but no longer used — the Director's Script replaces the
    # negotiation pivot.

    script_block, script_length = _format_director_script(
        director_script_questions or []
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

    coaching_id_clean = (coaching_id or "").strip() or "UNKNOWN"
    base = (
        "You are the AI host of a structured coaching chat. You are "
        "NOT the coach — you are the ACTOR delivering the coach's "
        "script (the admin_comment is the Director's Notes; the "
        "5-question script below is the Director's Script; deliver "
        "BOTH, don't override them). The protocol has up to 9 "
        "steps. Each user message advances the protocol by one "
        "step. NEVER skip a step.\n"
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
        "      where a user message exists (STEP 2 through STEP 9), "
        "      start your narration with ONE sentence that "
        "      summarises or reflects what they said, then move "
        "      into the current step's content.\n"
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
        "    • Inside the Director's Script steps (3-7), the ack "
        "      bridges from the user's last answer into the NEXT "
        "      scripted question — you don't get to invent the "
        "      next question, only the bridge phrasing.\n"
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
        "cool for you. Listen to this highlight.\" (in English per "
        "RULE 1).\n"
        "  Then in the same turn, quote the admin_comment "
        "verbatim (in quotes, attributed to the coach — preserve "
        "the comment's own language as written).\n"
        "  Close STEP 1 with the meaning of: \"What do you think "
        "about this? Do you agree with the coach?\"\n"
        "  Set step=1, current_question_position=null, and "
        "triggers=['render_snippet_player']. Pass the snippet_id "
        "in snippet_player.snippet_id so the frontend knows which "
        "audio to load.\n"
        "\n"
        # STEP 2 is the PEER-REVIEW beat (founder-signed 2026-08-04). It
        # validates the AI's pick — NOT the user's self-image — and its answer
        # lands in the peer-review corpus. The question is signed copy, hence
        # VERBATIM; the button labels are stamped server-side after this
        # returns. See the STEP2_* constants at the top of this module.
        "STEP 2 — REFLECTION & PEER-REVIEW FLAG (after the user's "
        "first response to STEP 1):\n"
        "  Per RULE 2 above, start with a sentence that reflects "
        "their actual reflection (not a generic ack). Then ask "
        "this question VERBATIM (in English per RULE 1) — it is "
        "signed copy, so do NOT reword, soften or translate it: "
        f"\"{STEP2_QUESTION}\"\n"
        "  Set step=2, current_question_position=null, and "
        f"triggers=['{CONFIDENCE_REVIEW_TRIGGER}']. Pass the "
        "snippet_id in label_buttons.snippet_id, and set "
        f"label_buttons.yes_label=\"{STEP2_YES_LABEL}\" and "
        f"label_buttons.no_label=\"{STEP2_NO_LABEL}\". The frontend "
        "wires those two buttons to POST "
        "/v2/user/snippets/<id>/confidence-review with "
        "{\"ai_correct\": true} and {\"ai_correct\": false}.\n"
        "  You are asking whether the AI picked the RIGHT MOMENT — "
        "this is not a question about whether they liked their own "
        "delivery, and 'Not quite' is a judgement on the pick, not "
        "on them. Do not editorialise either answer.\n"
        "\n"
        "─────────────────────────────────────────────────\n"
        "DIRECTOR'S SCRIPT — the admin-prepared sequence of "
        f"{script_length} question(s) you walk the user through, "
        "in order, one per turn. Steps 3 through "
        f"{2 + script_length} correspond to script positions 1 "
        f"through {script_length}.\n"
        f"{script_block}"
        "─────────────────────────────────────────────────\n"
        "\n"
        "STEPS 3..7 — THE DIRECTOR'S SCRIPT LOOP (one step per "
        "scripted question, in position order):\n"
        "  For each script position in order:\n"
        "    1. Per RULE 2, open with ONE sentence reflecting the "
        "       user's most recent message (their answer to the "
        "       previous question, or their Yes/No on STEP 2 if "
        "       this is the first script question).\n"
        "    2. Then ask the script's question for THIS position "
        "       VERBATIM. You may paraphrase only for grammar; you "
        "       do NOT rewrite the substance — that's the admin's "
        "       text. The admin's words are your script.\n"
        "    3. If the user's previous answer was extremely short "
        "       (1-3 words, \"idk\", \"yeah\") AND it's an early "
        "       script position, you may probe ONCE on this turn "
        "       before delivering the next scripted question. The "
        "       probe stays in the SAME turn as the next scripted "
        "       question — don't waste a step on a bare probe.\n"
        "  Set step = 2 + position (so script position 1 → step 3, "
        "  position 2 → step 4, ... position 5 → step 7).\n"
        "  Set current_question_position = the 1..5 position you "
        "  just delivered.\n"
        "  Set triggers=['none'].\n"
        "  If the script is empty (length 0), skip directly from "
        "  STEP 2 to STEP 8 — open STEP 8's narration with a brief "
        "  bridge acknowledging the user's reflection and proceed "
        "  to the bridge.\n"
        "\n"
        "STEP 8 — THE NEXT-TAKE BRIDGE (one turn — this is a "
        "BRIDGE, not the close; STEP 9 comes next):\n"
        "  Per RULE 2, open with (in English per RULE 1): \"Ok, "
        "noted. Good work across those reflections.\" — adapted "
        "to acknowledge what the user said in the final script "
        "answer.\n"
        "  Then frame the next take QUALITATIVELY, in English. "
        "State NO figure of any kind — no WPM, no dB, no filler "
        "count — and make no comparison to what the user did this "
        "time. Phrasing seed:\n"
        f"    {_NEXT_TAKE_SEED}\n"
        "  Close with a one-line preview that a fresh recording "
        "is coming up next (e.g. \"Now let's hear you try it — "
        "you'll record a short take in a moment.\"). Do NOT ask "
        "for the recording on this step — STEP 9 owns that.\n"
        "  Set step=8, end=false, current_question_position=null, "
        "  and triggers=['none']. Do NOT emit "
        "  show_trial_recording_mic here — that fires on STEP 9.\n"
        "\n"
        "STEP 9 — THE RE-RECORD ASK (one turn — closes the chat "
        "input and hands off to the mic):\n"
        "  Per RULE 2, open with ONE sentence reflecting the "
        "user's reaction to the framing you gave in STEP 8.\n"
        "  Then ask them to record a fresh take here in the chat. "
        "Describe the practice prompt briefly — refer back to the "
        "QUALITATIVE framing from STEP 8. State NO figure of any "
        "kind. Keep the ask to 1-2 sentences: \"Tap the mic and "
        "re-do that moment — steady tempo, a touch more range, "
        "fewer fillers.\"\n"
        "  Do NOT end with the literal word END. The session "
        "closes out-of-band when the trial recording POSTs to "
        "/v2/coaching/trial-recording.\n"
        "  Set step=9, end=false, current_question_position=null, "
        "  and triggers=['show_trial_recording_mic']. Pass the "
        f"  trial_recording object as {{ coaching_id: "
        f"\"{coaching_id_clean}\", prompt_text: <one-sentence "
        "  paraphrase of your ask> }} so the frontend wires the "
        "  mic to the right session and renders a short hint "
        "  above the recorder.\n"
        "\n"
        "─────────────────────────────────────────────────\n"
        "OUTPUT FORMAT — strict JSON matching the response schema. "
        "The 'narration' field is what the user sees in the chat "
        "bubble (in English per RULE 1). The 'step' (1..9), "
        "'current_question_position' (1..5 during script steps, "
        "null otherwise), 'triggers', 'end', 'snippet_player', "
        "'label_buttons', and "
        "'trial_recording' fields drive the frontend's UI "
        "affordances and are language-neutral keys / enum values "
        "— NEVER translate the schema keys, only the narration "
        "prose.\n"
        "\n"
        "Voice: direct, second-person, warm-but-no-fluff. Match "
        "the coach's tone (the admin_comment is your style "
        "anchor). Short paragraphs in 'narration' — chat bubbles, "
        "not essays. NO bullet lists, NO headers in narration; "
        "the frontend handles UI structure."
    )

    # Admin-private don't-ask block — appended at the very end so
    # it's the final framing the model sees before the conversation
    # history + user message. Same wording every chat surface uses.
    from services.utils import render_admin_dont_ask_block
    dont_ask_block = render_admin_dont_ask_block(admin_dont_ask_notes)
    if dont_ask_block:
        base += "\n\n" + dont_ask_block

    return base


def _format_director_script(
    questions: list[dict],
) -> tuple[str, int]:
    """Render the Director's Script block + report its length.

    Input is the ordered question list from the session row
    (admin-edited preferred over AI-pre-generated; the route
    handler picks which). Each entry should be a dict with
    {position, text, intent_tag?}. We're defensive against
    missing fields — drop empties, cap at _MAX_SCRIPT_QUESTIONS,
    and renumber so positions land 1..N in the rendered prompt
    even when the input had gaps.

    Returns ``(rendered_block, used_length)``. ``used_length`` is
    what the prompt body references when emitting "Steps 3..N+2"
    boundaries — callers MUST pass this through, never recount
    the original list.
    """
    cleaned: list[dict] = []
    for entry in questions or []:
        if not isinstance(entry, dict):
            continue
        text = (entry.get("text") or "").strip()
        if not text:
            continue
        intent = (entry.get("intent_tag") or "").strip() or None
        cleaned.append({"text": text, "intent_tag": intent})
        if len(cleaned) >= _MAX_SCRIPT_QUESTIONS:
            break

    if not cleaned:
        return (
            "  (no script — admin did not stage questions for this "
            "session. Skip from STEP 2 straight to STEP 8.)\n",
            0,
        )

    lines: list[str] = []
    for i, entry in enumerate(cleaned):
        position = i + 1
        tag_str = f" [{entry['intent_tag']}]" if entry["intent_tag"] else ""
        lines.append(
            f"  Q{position}{tag_str}: \"{entry['text']}\""
        )
    return ("\n".join(lines) + "\n", len(cleaned))


# The STEP 8 phrasing seed.
#
# THIS EXACT SENTENCE IS WHAT STEP 8 HAS EMITTED SINCE 2026-06-01. The old
# formatter built prescriptive numeric targets ("keep your tempo at around 145
# WPM (you were at 132 this time)") but its inputs have been NULL that whole
# time, so every turn fell through to this branch. Founder REJECTED the numeric
# version on 2026-08-06 -- "we don't want that, it is a wrong call" -- so the
# fall-through became the only behaviour and the arithmetic was DELETED rather
# than left gated behind a flag somebody could flip back.
#
# Qualitative direction, no figure and no shortfall comparison. Deleting the
# numbers is what keeps STEP 8 on the right side of the split-sink rule: raw
# figures are reference data, but a target is a DIRECTION, and pairing "you
# were at 132" with a goal of 145 is a verdict wearing a suggestion's clothes.
_NEXT_TAKE_SEED = (
    "next time, keep your tempo steady, your vocal range a "
    "touch wider, and your filler words sparse"
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
                "maximum": 9,
                "description": (
                    "Which protocol step this turn is in: "
                    "1=reveal, 2=rlhf_label, 3..7=script_q1..q5, "
                    "8=next_take_bridge, 9=re_record_ask."
                ),
            },
            "current_question_position": {
                "type": ["integer", "null"],
                "description": (
                    "Which Director's Script position (1..5) this "
                    "turn delivered, or null on steps 1/2/8/9. "
                    "Frontend reads this to render a '3 of 5' "
                    "progress dot."
                ),
            },
            "triggers": {
                "type": "array",
                "maxItems": 4,
                "items": {
                    "type": "string",
                    "enum": [
                        "render_snippet_player",
                        CONFIDENCE_REVIEW_TRIGGER,
                        "show_trial_recording_mic",
                        "none",
                    ],
                },
                "description": (
                    "Which UI affordances the frontend should render "
                    "alongside this turn's narration. "
                    "'show_confidence_review_buttons' fires on STEP 2 "
                    "and renders the two peer-review buttons that POST "
                    "to /v2/user/snippets/<id>/confidence-review "
                    "(replaced 'show_charisma_label_buttons', which "
                    "pointed at a deleted endpoint). "
                    "'show_trial_recording_mic' fires on STEP 9 and "
                    "unlocks the mic that POSTs to "
                    "/v2/coaching/trial-recording."
                ),
            },
            "end": {
                "type": "boolean",
                "description": (
                    "TRUE on the turn that closes the chat input "
                    "(STEP 9 re-record ask — frontend swaps the text "
                    "input for the mic affordance). The "
                    "coaching_session is marked complete out-of-band "
                    "when the trial recording POST arrives, NOT on "
                    "this turn."
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
            "trial_recording": {
                "type": "object",
                "additionalProperties": False,
                "description": (
                    "Present on STEP 9 alongside the "
                    "'show_trial_recording_mic' trigger. Frontend "
                    "uses this to POST the recording to "
                    "/v2/coaching/trial-recording and to render a "
                    "short hint above the mic. 'prompt_text' is a "
                    "one-sentence ask paraphrased from the "
                    "narration; the narration carries the full "
                    "framing."
                ),
                "properties": {
                    "coaching_id": {"type": "string"},
                    "prompt_text": {"type": "string"},
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
    if not isinstance(step, int) or not (1 <= step <= 9):
        return None
    triggers = parsed.get("triggers") or []
    if not isinstance(triggers, list):
        return None
    if "end" not in parsed:
        return None
    # current_question_position is optional but if present must
    # be either null or an integer in 1..5. The schema enforces
    # type already; double-check the range here so a downstream
    # consumer doesn't have to.
    pos = parsed.get("current_question_position")
    if pos is not None and (not isinstance(pos, int) or not (1 <= pos <= 5)):
        return None
    return parsed
