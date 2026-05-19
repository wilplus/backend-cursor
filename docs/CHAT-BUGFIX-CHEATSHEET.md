Chat bug-fix cheat sheet

Each chat surface has exactly one prompt source. Edit that one
file, redeploy, only that surface changes. Nothing else moves.

ONBOARDING (turns 1-4, new users)
  routes/v2_routes.py:11411 — _BASELINE_TURN_OBJECTIVES
  One dict entry per turn. The whole onboarding script.
  If the bot ignores prior answers, copy Turn 2's "MUST reference
  a specific detail from the user's answer in Turn 1" clause into
  whichever turn needs it.

INTERVIEW (turn 5+, both new and returning users)
  routes/v2_routes.py:7547 — _INTERVIEW_SYSTEM_PROMPT
  Persona, tone alternation, anti-parrot, formatting, English-only,
  identity pivot.

POST-SNIPPET COACHING CHAT (the 9-step flow)
  services/coaching_state_machine.py:162 — build_state_machine_system_prompt
  One block per STEP 1-9. Edit the specific step.
  STEP 9 is the re-record ask. STEP 8 is the bridge.

AWARENESS CHAT (legacy, after clicking a snippet)
  services/skills/charisma.py:26 or services/skills/stress.py:25
  Single-message contract: <anchor> ||| <scenario> [ADVANCE].
  Don't break the [ADVANCE] token.

FAQ CHAT (/chat/query — what they ask post-signup)
  services/master_doc_rag.py
  - MASTER_DOCUMENT constant (~line 88): the verbatim facts.
    Edit when the answer copy is wrong.
  - _SYSTEM_PROMPT (~line 138): the rules.
    RULE G = upload intent, RULE I = record intent,
    RULE H = capability declines (camera/SMS/calendar).

ONE-OFF OVERRIDES (no code change)
  Force a specific question for ONE user, fires once:
    PATCH /v2/admin/users/<id>/context
    body: { "queued_override_question": "your question" }

  Make ONE user re-do the onboarding from turn 1:
    POST /v2/admin/users/<id>/reset-baseline

  Tweak ONE user's coaching tone permanently:
    Admin Tab 3 → "Custom LLM Instructions" textbox.
    Writes user_settings.custom_llm_instructions.
    Feeds the interview + coaching prompts as
    [COACHING CONTEXT] Admin Notes.

WHEN IN DOUBT
  Grep the phrase the bot said:
    grep -rn "the literal phrase" routes/ services/
  Bot is non-deterministic but prompts are literal strings —
  the phrase traces back to its source file every time.
