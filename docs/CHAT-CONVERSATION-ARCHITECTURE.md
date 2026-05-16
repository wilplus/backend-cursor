# Chat / Conversation Architecture — single source of truth

Every conversational LLM surface in the system, what each one does, what its system prompt is, where state lives, what gets captured for learning, and what controls (admin override, baseline flag, etc.) attach to it.

This doc is meant to be the **one place** you edit when changing conversational behavior. Each section ends with the exact `file:line` and config keys to touch. As of 2026-05-15 — line numbers will drift; the function names won't.

---

## 0. Map at a glance — every conversational surface

There are **three** distinct LLM-driven chat surfaces. Plus one explicit non-LLM surface. They serve different moments in the user's journey:

| # | Surface | When it fires | LLM-driven? | System prompt source |
|---|---|---|---|---|
| 1 | **Interview / Assessment** (turns 1-N) | The main onboarding + ongoing assessment funnel. User records audio answers to bot questions. | ✅ GPT-4o-mini | `_INTERVIEW_SYSTEM_PROMPT` ([routes/v2_routes.py:7547](routes/v2_routes.py:7547)) |
| 2 | **Awareness coaching** (legacy "awareness → trial" loop) | User clicks a snippet → bot validates the user's first reply → unlocks the mic for a re-performance trial. Single LLM turn per coaching session. | ✅ GPT-4o-mini | `services/skills/charisma.py` and `stress.py` — `_AWARENESS_PROMPT` per skill |
| 3 | **5-step state-machine coaching** (Phase 17/18+) | The newer post-snippet chat: reveal → reflection/label → contextual pivot → negotiation simulation → acoustic cliffhanger. Multi-turn, JSON-schema-driven. | ✅ GPT-4o-mini | `build_state_machine_system_prompt()` ([services/coaching_state_machine.py:155](services/coaching_state_machine.py:155)) |
| 4 | Snippet card stored question | When user clicks a snippet for the first turn of a contextual chat (#2), the admin's hand-edited `follow_up_question` is served verbatim **before** any LLM call. Zero-latency, zero-cost shortcut. | ❌ Static | `charisma_snippets.follow_up_question` column |

Frontend opts into #2 or #3 by hitting different routes (`/v2/coaching/turn` vs. `/v2/coaching/state-machine/turn`). They share `coaching_sessions` for persistence so an admin transcript view replays either flow.

---

## 1. Surface 1 — Interview / Assessment (`/v2/public/interview/*`)

### 1.1 What it is
The main bot↔user assessment loop. The user gets a question, records an audio answer, the answer is uploaded and pre-processed (acoustic metrics, transcription, snippet creation), then the user requests the next question. Repeats until they stop.

### 1.2 Two endpoints

**Get next question** — `POST /v2/public/interview/next-question` ([routes/v2_routes.py:11458](routes/v2_routes.py:11458))
- **Auth**: none required (public funnel; `user_id` is optional in body for authenticated path).
- **Body**: `{ turn_number: int, user_id?: str, previous_turns?: [{question, transcript?}] }`
- **Response**: `{ question, tone: "charisma"|"stress", turn_number, source }`
- The `source` enum tells you which path produced the question — useful for debugging:
  - `admin_override` — admin pre-queued question popped (see §5.1)
  - `llm_baseline_directed` — directed-freestyle path with per-turn objective (turns 1-4 for new users)
  - `llm` — standard alternation with regular augmentations
  - `fallback` — hardcoded bank in `_INTERVIEW_QUESTIONS_FALLBACK` ([routes/v2_routes.py:7524](routes/v2_routes.py:7524)) when LLM fails

**Upload answer** — `POST /v2/public/interview/upload-answer` ([routes/v2_routes.py:11567](routes/v2_routes.py:11567))
- **Auth**: optional Bearer (guest funnel works without). Authenticated users get the `baseline_established` flag flip on turn 4.
- **Body**: multipart `audio_file` + form `guest_session_id?`, `turn_number`, `question_tone`, `duration_seconds?`
- Creates a `recordings` row on turn 1, creates a `charisma_snippet` per turn, runs acoustic metrics, kicks off transcription + coaching-outcome scoring in a background thread.
- **Side effect on turn 4 (authed users only)**: flips `user_settings.baseline_established=TRUE` and (if `BASELINE_SUMMARY_ENABLED`) computes the EBCP baseline digest for use in turn-5+ prompts. See §5.2 for the flag.

### 1.3 Question generation — `_generate_llm_question` ([routes/v2_routes.py:8008](routes/v2_routes.py:8008))

The single function that produces an interview question. Called from `next-question` and from the chat `first-question` endpoint (§2.1). Inputs:

```
turn_number, tone ("charisma"|"stress"),
previous_turns (list of {question, transcript}),
user_id (optional — gates several augmentations),
contextual_init (only used by chat first-question path),
timeout_seconds (used by paths that need a snappy fallback),
baseline_objective (the per-turn directed-freestyle objective string)
```

Returns the question text or `None` (caller falls back to the hardcoded bank).

**LLM call shape:**
- Model: `gpt-4o-mini`
- Temperature: default unset → OpenAI default ~1.0; baseline-directed path may override
- The system prompt is `_INTERVIEW_SYSTEM_PROMPT` + augmentations spliced in via `_augment_interview_prompt_with_profile()`
- User message: a render of `previous_turns` plus the current turn instruction (and `[CURRENT_TURN_OBJECTIVE]` when `baseline_objective` is set)

### 1.4 The base system prompt — `_INTERVIEW_SYSTEM_PROMPT` ([routes/v2_routes.py:7547](routes/v2_routes.py:7547))

What it currently encodes (sections you can edit):

- **Persona**: "interview coach conducting a voice charisma assessment"
- **Tone alternation rule**: charisma↔stress, must alternate
- **RULES block** — concise questions, no repetition, build on user's most recent answer, never break character
- **FORMATTING RULE** — use `|||` to separate acknowledgment from question; the frontend splits on this delimiter to render two chat bubbles
- **LANGUAGE HANDLING** — English-only with one-shot disclaimer (added Phase 18.1, commit `87abb58`). Exact disclaimer text is quoted in the prompt; LLM must inspect prior turns to avoid repeating
- **IDENTITY & PERSONA** — graceful pivot using `|||` (added Phase 18.1). Never derail; shorten on repeats

### 1.5 Augmentations spliced into the prompt

`_augment_interview_prompt_with_profile()` ([routes/v2_routes.py:8772](routes/v2_routes.py:8772)) wraps the base prompt. Reads several DB rows and appends blocks:

| Block | Source | Gate |
|---|---|---|
| `[COACHING CONTEXT]` — Learner Profile | `user_sniper_profile.coach_override_profile` ∥ `behavioral_profile` | Always when set |
| `[COACHING CONTEXT]` — Admin Notes | `user_settings.custom_llm_instructions` | Always when set |
| `[PERFORMANCE METRICS]` (Phase 17 Master Score B6) | Most recent session's `kpi_score` + acoustic aggregates via `_build_master_score_block()` | Always when the user has measurable sessions |
| `[CURRENT_TURN_OBJECTIVE]` | One of four hardcoded strings in `_BASELINE_TURN_OBJECTIVES` ([routes/v2_routes.py:11411](routes/v2_routes.py:11411)) | Only when `baseline_objective` arg is set — see §1.6 |

Phase 15 (longitudinal) and Phase 16 (baseline summary) blocks ALSO live in `_generate_llm_question` for the contextual `first-question` path. Both are flag-gated:
- `LONGITUDINAL_FIRST_QUESTION_ENABLED` — adds learner-profile + mirror + prior attempts
- `BASELINE_SUMMARY_ENABLED` — adds the EBCP digest baked at turn-4 completion

### 1.6 Directed-freestyle for turns 1-4 (new users)

The four hardcoded psychological objectives ([routes/v2_routes.py:11411](routes/v2_routes.py:11411)):

| Turn | Tone | Objective summary | Edit the full text at |
|---|---|---|---|
| 1 | charisma | Icebreaker — explain something basic to a beginner, no math, 15s natural speech | line 11412 |
| 2 | charisma | Empathy/Frustration — reference a specific detail from turn 1, simulate misunderstanding | line 11417 |
| 3 | stress | Pressure — high-pressure professional environment, aggressive authority challenge | line 11428 |
| 4 | stress | Quick Reflex — sudden arbitrary constraint (e.g. "Pitch your idea in exactly 3 sentences") | line 11433 |

Tone is hardcoded per turn in `_baseline_turn_tone()` ([routes/v2_routes.py:11447](routes/v2_routes.py:11447)) — turns 1-2 charisma, turns 3-4 stress. Turn 5+ falls back to standard alternation (odd → charisma, even → stress).

The directed path fires when:
```
1 <= turn_number <= 4 AND (no user_id OR baseline_established=False)
```
Returning authenticated users skip the objective block and get standard alternation on every turn.

### 1.7 Where state lives

- **Session row**: `v2_sessions` (guest) — created on first `upload-answer` call
- **Per-turn audio + metrics**: `charisma_snippets` — one row per turn with `transcript`, acoustic aggregates, `question_text`, `question_tone`, `turn_number`, `start_offset_ms`, `duration_ms`
- **Parent recording**: `recordings` — one row per session
- **Per-user assessment progress**: `user_settings.baseline_established` (bool) + `baseline_established_at` (timestamp)

---

## 2. Surface 2 — Awareness coaching (legacy "awareness → trial" loop)

### 2.1 What it is
The user clicks a published snippet on their results page. They get a one-question contextual chat ("what triggered that moment for you?"). They type or speak a reply. The bot validates and unlocks the mic for a re-performance trial. Single LLM turn — short, sharp, then disappears.

### 2.2 Three endpoints

**Start coaching session** — `POST /v2/coaching/start` ([routes/v2_routes.py:9111](routes/v2_routes.py:9111))
- **Auth**: Bearer required
- **Body**: `{ snippet_id: uuid }`
- Validates the snippet has an `admin_comment` (no comment ⇒ 422 SNIPPET_NOT_COACHABLE — there's nothing to coach on)
- Creates a `coaching_sessions` row, returns `coaching_id`, the admin_comment verbatim as the opening `awareness_message`, and the snippet metadata.

**First-question (contextual chat)** — `POST /v2/user/chat/first-question` ([routes/v2_routes.py:10099](routes/v2_routes.py:10099))
- **Auth**: Bearer required
- **Query**: `sourceSnippetId` (or `sourceSnippet` or `source_snippet_id` — all three accepted to survive BFF naming drift), `intent` ("charisma" or "stress")
- **Resolution order** (highest priority first):
  1. Admin queued override (§5.1) — pop-and-clear, fires once
  2. Stored `charisma_snippets.follow_up_question` — admin's pre-baked / hand-edited question, served verbatim
  3. Dynamic LLM generation via `_generate_llm_question(contextual_init=...)` — uses the skill's `awareness_system_prompt`

**Coaching turn** — `POST /v2/coaching/turn` ([routes/v2_routes.py:9225](routes/v2_routes.py:9225))
- **Auth**: Bearer required
- **Body**: `{ coaching_id: uuid, user_message: string }`
- One LLM round-trip per call. The model returns structured JSON `{validation_bubble, challenge_bubble, advance}` (schema: `services/llm_schemas.py::AWARENESS_TURN_SCHEMA`).
- When `advance=true`, the coaching session advances to `trial` stage and the frontend unlocks the mic.

### 2.3 System prompts — per-skill, in `services/skills/`

The "skill registry" decouples coaching tones from the route. Each skill is one file:

| Skill | File | Awareness prompt variable |
|---|---|---|
| charisma | [services/skills/charisma.py:26](services/skills/charisma.py:26) | `_AWARENESS_PROMPT` |
| stress   | [services/skills/stress.py:25](services/skills/stress.py:25)     | `_AWARENESS_PROMPT` |

Both prompts have the **same output contract**: a single message in this exact shape:
```
<half-sentence trigger anchor> ||| <one-sentence trigger-stripped scenario, ending with a quoted prospect line> [ADVANCE]
```

The frontend splits on `|||` into two bubbles. The `[ADVANCE]` marker is stripped server-side and flips the UI into record-only trial mode. **This contract is why the chat awareness prompts were NOT given the English-only language/identity rules in Phase 18.1** — adding a third prepended bubble would break the `[ADVANCE]` semantics.

Each skill object also carries:
- `fallback_validation_bubble` / `fallback_challenge_bubble` — surfaced when the LLM returns no parseable bubbles, keeps the UI tonally consistent on degraded responses
- `contextual_first_question` — fallback used by `/user/chat/first-question` when the LLM stalls and there's no stored `follow_up_question`

### 2.4 Augmentation for coaching turns

`_augment_coaching_system_prompt(base_prompt, user_id)` ([routes/v2_routes.py:8932](routes/v2_routes.py:8932)) wraps the awareness prompt with a `[USER LONG-TERM PROFILE]` block when available. Pulls from:
- `user_settings.custom_llm_instructions` (admin's free-text directive)
- `user_sniper_profile.coach_override_profile` ∥ `behavioral_profile` (e.g. "Stressor", "Racer", "Freezer")
- `user_settings.inferred_learner_profile` JSONB (Phase 3 — derived from prior coaching attempts) + Phase 9 admin override layered on top via `_merge_admin_override_into_profile()`

### 2.5 Where state lives

- **Coaching session**: `coaching_sessions` (id, user_id, source_snippet_id, intent, current_stage, messages JSONB)
- **Per-turn transcript**: `coaching_sessions.messages` — appended via `db.append_coaching_message(coaching_id, role, content, extra={...})`. Both user and assistant turns. `extra` carries the parsed bubbles + advance flag + raw LLM output for admin debugging
- **Stage advancement**: `coaching_sessions.current_stage` — `awareness` → `trial` → `complete`

### 2.6 Trial recording
After `advance=true`, the user records their re-performance. `POST /v2/coaching/trial-recording` ([routes/v2_routes.py:9657](routes/v2_routes.py:9657)) attaches that audio to the coaching session and triggers the coaching-outcome evaluator (§4.2).

---

## 3. Surface 3 — 5-step state-machine coaching (Phase 17/18+)

### 3.1 What it is
A richer, multi-turn coaching chat that opens with the snippet reveal and walks the user through reflection → labelling → contextual pivot → a negotiation simulation → an acoustic cliffhanger. JSON-schema-driven so the frontend can render specific UI affordances (snippet player, label buttons, live negotiation offer, acoustic targets card) per step.

Frontend chooses this flow OR the awareness flow (§2) per coaching session by hitting different endpoints. They both write to `coaching_sessions`.

### 3.2 The endpoint

**State-machine turn** — `POST /v2/coaching/state-machine/turn` ([routes/v2_routes.py:9402](routes/v2_routes.py:9402))
- **Auth**: Bearer required
- **Body**: `{ coaching_id: uuid, user_message?: str, user_language?|user_language_hint?|language?: str }`
- **Response**: structured JSON matching `STATE_MACHINE_RESPONSE_SCHEMA` — keys: `narration, step, triggers, end, snippet_player?, label_buttons?, negotiation?, acoustic_targets?`
- First call has no `user_message` — the LLM opens with STEP 1 (the reveal).
- `user_language_hint` is **accepted for back-compat but ignored** since Phase 18.1 (commit `87abb58`) — the new persona is English-only.

### 3.3 System prompt — `build_state_machine_system_prompt()` ([services/coaching_state_machine.py:155](services/coaching_state_machine.py:155))

Composed per-call from these inputs:
- `snippet` — the source snippet dict (id + admin_comment + coach_label all get baked into the DIRECTOR'S NOTES section)
- `acoustic_targets` — computed from the parent session's global aggregates via `compute_acoustic_targets()`
- `user_first_name` — looked up from `v2_student_details.name`, first token
- `user_org_context` — currently always `None` (passed as `None` from the route); when present, drives the STEP 3 "since you are part of <org>" pivot line
- `user_language_hint` — accepted, ignored (see §3.2)

The assembled prompt has these sections (read top→bottom):

| Section | Purpose | Edit location |
|---|---|---|
| Persona preamble | "You are the AI host of a structured coaching chat. You are NOT the coach — you are the ACTOR delivering the coach's script" | line 237 |
| `first_name_line` | Optional one-liner with the user's first name | line 224 |
| **RULE 1 — LANGUAGE: ENGLISH-ONLY WITH ONE-SHOT DISCLAIMER** | English-only enforcement; exact disclaimer text quoted; admin_comment exception (quote verbatim in its source language) | line 252 |
| **RULE 2 — EMPATHY / ACKNOWLEDGEMENT** | Every turn must open with a sentence reflecting what the user just said. STEP 1 exempt (no user message yet) | line 285 |
| **RULE 3 — IDENTITY: GRACEFUL PIVOT, NEVER GET STUCK** | Exact identity ack text quoted; never derail; drop ack on repeats | line 309 |
| DIRECTOR'S NOTES | `snippet_id`, `coach_label`, and the verbatim `admin_comment` quoted | line 330 |
| **STEP 1 — THE REVEAL** | Opens with a generic intro line, quotes admin_comment verbatim, closes with "What do you think? Do you agree with the coach?". Triggers `render_snippet_player` | line 337 |
| **STEP 2 — REFLECTION & RLHF LABEL** | Acknowledge user's reflection (RULE 2), ask "Would you actually label your voice here as Charismatic/a stress moment?". Triggers `show_charisma_label_buttons` so the frontend wires Yes/No to `POST /v2/user/snippets/<id>/label` | line 343 |
| **STEP 3 — THE CONTEXTUAL PIVOT** | Ack the Yes/No, deliver the org/standard pivot line. No triggers — beat for the user to read | line 355 |
| **STEP 4 — THE NEGOTIATION SIMULATION** | Multi-turn. AI plays a tough SaaS vendor at anchor price $X, floor $Y (constants in same file). Concludes when user (a) accepts ≥ floor, (b) walks, or (c) ~5 turns. Triggers carry the live offer state | line 366 |
| **STEP 5 — THE ACOUSTIC CLIFFHANGER** | Ack the negotiation, frame a discount carrot, render acoustic targets verbatim numbers (WPM, dB, fillers), close with literal `END`. Triggers `show_acoustic_targets_card`, sets `end=true` | line 398 |
| OUTPUT FORMAT block | Strict JSON, narration in English per RULE 1, schema keys are language-neutral | line 416 |
| Voice direction | "direct, second-person, warm-but-no-fluff…" | line 425 |

### 3.4 Where state lives

Same as awareness coaching (§2.5) — `coaching_sessions.messages` JSONB. The state machine doesn't have a separate state table; **the LLM infers the current step from the conversation history** that's prepended to every request. Each assistant message persists `step`, `triggers`, `end`, and any payload fields (snippet_player, label_buttons, negotiation, acoustic_targets) in the `extra` JSONB.

On `end=true` (STEP 5), `coaching_sessions.current_stage` advances to `complete`. Subsequent POSTs return `409 COACHING_COMPLETE`.

### 3.5 LLM call shape
- Model: `gpt-4o-mini`
- Temperature: 0.7
- max_tokens: 600
- `response_format`: `json_schema` with `STATE_MACHINE_RESPONSE_SCHEMA` — strict schema enforcement, the LLM cannot return malformed shape (only malformed content within the shape).

---

## 4. Cross-cutting: capture for learning (RLHF / DPO)

### 4.1 Per-attempt coaching outcomes — `follow_up_outcome` JSONB on `charisma_snippets`

When a user completes a contextual chat trial (either §2 or §3 flow), `services/coaching_outcomes.py::record_outcome()` runs an LLM evaluator (`gpt-4o-mini`) that scores the user's answer on multiple components and produces a rationale. The result is written to `charisma_snippets.follow_up_outcome` as JSONB.

Shape ([services/coaching_outcomes.py:193](services/coaching_outcomes.py:193)):
```jsonc
{
  "captured_at": "ISO8601",
  "user_id": "uuid",
  "question_text": "...",
  "user_answer": { "text", "duration_ms", "word_count" },
  "evaluator": {
    "model": "gpt-4o-mini",
    "score": 0.7123,
    "components": { "specificity": ..., "emotion": ..., ... },
    "rationale": "string",                          // AI's reasoning for the score
    "admin_corrected_rationale": "string | null",   // Phase 14.2 — admin's edited version
    "admin_reviewed_at": "ISO8601 | null"           // Phase 14.2 — presence = admin has reviewed
  },
  "score": 0.7123,                  // top-level mirror for JSONB index
  "entities": [...],                // Phase 4 — entities user mentioned
  "skill_id": "charisma|stress",
  "eligible_for_few_shot": bool,    // Phase 5 — fact-check gate
  "fact_check": { "passed", "issues", "adjusted_specificity" }
}
```

**Latest-wins semantics**: if the user records a new attempt, the entire `follow_up_outcome` JSONB is overwritten. Admin review fields (`admin_corrected_rationale`, `admin_reviewed_at`) get wiped along with the rest — by design, since a new attempt produces a new rationale that hasn't been reviewed.

### 4.2 Admin review of the AI rationale — `PATCH /v2/admin/snippets/<id>/coaching-rationale` (Phase 14.2)

Frontend's editable rationale strip. Body `{ rationale: str, edited_by_admin: bool }`. Writes:
- `evaluator.admin_corrected_rationale = rationale` (if `edited_by_admin=true`) else `null`
- `evaluator.admin_reviewed_at = NOW()`

See [routes/v2_routes.py:11968](routes/v2_routes.py:11968)-ish (Phase 14.2 commit `f82b653`) and [services/db.py::set_snippet_evaluator_rationale_review](services/db.py).

### 4.3 Publish-time annotation capture — `record_snippet_publish_annotations()` ([services/db.py:5593](services/db.py:5593))

Fires **once per session at publish time** when admin clicks "Publish" ([routes/v2_routes.py:11803](routes/v2_routes.py:11803)). For each snippet in the session, compares `(AI draft, admin final)` for three fields and emits one row per field per snippet to `admin_annotation_events`:

| `field_name` | Draft source | Final source | Gate |
|---|---|---|---|
| `admin_comment` | `charisma_snippets.ai_draft_admin_comment` | `charisma_snippets.admin_comment` | always |
| `follow_up_question` | `charisma_snippets.ai_draft_follow_up_question` | `charisma_snippets.follow_up_question` | always |
| `evaluator_rationale` | `follow_up_outcome.evaluator.rationale` | `follow_up_outcome.evaluator.admin_corrected_rationale` ∥ rationale fallback | only when `evaluator.admin_reviewed_at` is set |

**Chip logic** ([services/db.py:5733](services/db.py:5733)):
- Whitespace-collapsed case-insensitive comparison: `draft == final` → `reason_chip = "approved_as_is"`
- Otherwise: `reason_chip = NULL` (the diff IS the signal)
- Both empty: no row written

**Critical caveat**: saved but not published = not captured. If a snippet is reviewed/edited but the session never gets published, the annotation never lands in `admin_annotation_events`. The fix is operational (always publish reviewed sessions) or a backfill cron.

### 4.4 Downstream export — `scripts/export_openai_preference_jsonl.py`
Reads `admin_annotation_events` and emits OpenAI-format preference pairs for DPO/RLHF fine-tuning. Filtering by `reason_chip` is supported.

---

## 5. Cross-cutting: admin override surfaces

### 5.1 Queued override question (Phase 12 + 12.2)

Admin can pre-arm one question that will fire on the user's NEXT interaction. Pop-and-clear so it fires exactly once.

**Set/clear**: `PATCH /v2/admin/users/<id>/context` body `{ queued_override_question: "..." | null }` ([routes/v2_routes.py:776](routes/v2_routes.py:776))

**Consumed at the top of**:
- `/v2/user/chat/first-question` ([routes/v2_routes.py:10129](routes/v2_routes.py:10129)) — fires regardless of contextual init / stored follow-up
- `/v2/public/interview/next-question` ([routes/v2_routes.py:11499](routes/v2_routes.py:11499)) — fires on any turn for any user_id-bearing call (note: was turn-1-only in original design, current code allows any turn)

**Storage**: `user_settings.queued_override_question` (text column). Read+clear is non-atomic ([services/db.py:7219](services/db.py:7219)) — small race window where a concurrent admin write could be lost. Documented as acceptable for single-admin workflow.

**Source flag on response**: `source: "admin_override"` — frontend can badge the bubble if desired.

### 5.2 Baseline reset (Phase 13.1)

Admin can force a user back into the "directed-freestyle turns 1-4" regime by flipping `user_settings.baseline_established` back to FALSE.

**Reset endpoint**: `POST /v2/admin/users/<id>/reset-baseline` ([routes/v2_routes.py:881](routes/v2_routes.py:881))
- Idempotent. Returns 200 with new state.

**Flag is read by**: `/v2/public/interview/next-question` ([routes/v2_routes.py:11515](routes/v2_routes.py:11515)) — determines whether turns 1-4 use directed objectives or standard alternation.

**Flag is set by**: `/v2/public/interview/upload-answer` on turn 4 ([routes/v2_routes.py:11987](routes/v2_routes.py:11987)) — flips to TRUE the moment the user submits their answer to the last onboarding turn. Authenticated users only (guests have no row to upsert).

**Storage**: `user_settings.baseline_established` (bool) + `baseline_established_at` (timestamp; cleared on reset for audit clarity).

### 5.3 Behavioral profile override (Phase 9)

Admin's `coach_override_profile` overrides the AI's `behavioral_profile` classification (e.g. switch a user from auto-classified "Racer" to admin-set "Stressor").

**Set/clear**: same `PATCH /v2/admin/users/<id>/context` endpoint, body `{ coach_override_profile: "Stressor" | null }`
**Storage**: `user_sniper_profile.coach_override_profile` (text)
**Effect**: feeds into `[COACHING CONTEXT] Learner Profile:` block in every interview LLM call.

### 5.4 Per-user custom LLM instructions

Free-text directive the admin types ("be gentler with this user", "focus on filler words").

**Set/clear**: same `PATCH /v2/admin/users/<id>/context`, body `{ custom_llm_instructions: "..." | null }`
**Storage**: `user_settings.custom_llm_instructions`
**Effect**: feeds into `[COACHING CONTEXT] Admin Notes:` block in interview + the `[USER LONG-TERM PROFILE]` block in awareness coaching.

### 5.5 Inferred learner profile + Phase 9 admin override

The AI derives a `inferred_learner_profile` JSONB blob from past coaching attempts (specificity tendencies, score trend, etc.). Admin can override individual traits via `POST /v2/admin/users/<id>/learner-profile-override`. Override is layered field-by-field on top of inferred via `_merge_admin_override_into_profile()` ([routes/v2_routes.py:8726](routes/v2_routes.py:8726)).

---

## 6. Database tables — what lives where

| Table | Purpose | Key columns relevant to chat |
|---|---|---|
| `v2_sessions` | One row per interview session (guest or authed) | `id, user_id, results_published_at, kpi_score, global_wpm, global_fillers, global_dynamic_db, duration_ms, stickiness_top_topic, stickiness_score` |
| `recordings` | One row per parent audio recording | `id, session_v2_id, user_id, storage_path` |
| `charisma_snippets` | One row per turn / per snippet | `id, session_id, recording_id, turn_number, question_text, question_tone, transcript, admin_comment, ai_draft_admin_comment, follow_up_question, ai_draft_follow_up_question, follow_up_outcome (JSONB), snippet_type, is_skipped, start_offset_ms, duration_ms, wpm, pitch_center` |
| `stress_snippets` | Stress segments extracted from recordings | `id, recording_id, coach_label_notes, ai_draft_coach_notes, …` |
| `coaching_sessions` | One per coaching loop (awareness or state-machine) | `id, user_id, source_snippet_id, intent, current_stage, messages (JSONB)` |
| `user_settings` | Per-user admin tools + flags | `user_id, custom_llm_instructions, private_admin_notes, queued_override_question, baseline_established, baseline_established_at, inferred_learner_profile, admin_profile_override, email_pref_publish_results` |
| `user_sniper_profile` | Per-user behavioral classification | `user_id, behavioral_profile, behavioral_profile_justification, coach_override_profile, profile_override_justification` |
| `admin_annotation_events` | Capture stream for RLHF/DPO | `id, session_id, section_type, field_name, ai_original_text, coach_final_text, reason_chip, custom_reason, created_by, draft_id, created_at` |
| `v2_student_details` | Display name, etc. | `user_id, name` |

---

## 7. Decision tree — where to add new behavior

**"I want to change what the bot says during the main assessment."**
→ Edit `_INTERVIEW_SYSTEM_PROMPT` ([routes/v2_routes.py:7547](routes/v2_routes.py:7547)).

**"I want to change what the bot says during turns 1-4 specifically (new users)."**
→ Edit one of the four objectives in `_BASELINE_TURN_OBJECTIVES` ([routes/v2_routes.py:11411](routes/v2_routes.py:11411)). Don't change the prompt itself; the objectives splice in via `_generate_llm_question(baseline_objective=...)`.

**"I want to change the tone for turn N."**
→ `_baseline_turn_tone()` ([routes/v2_routes.py:11447](routes/v2_routes.py:11447)).

**"I want to change what the bot says when the user clicks a snippet to coach on it (awareness loop)."**
→ Edit the skill file: [services/skills/charisma.py:26](services/skills/charisma.py:26) or [services/skills/stress.py:25](services/skills/stress.py:25). Both have the `_AWARENESS_PROMPT` constant and the `[ADVANCE]` output contract.

**"I want to change the 5-step coaching chat."**
→ `build_state_machine_system_prompt()` ([services/coaching_state_machine.py:155](services/coaching_state_machine.py:155)). Each STEP has its own block. The schema in `STATE_MACHINE_RESPONSE_SCHEMA` defines what UI triggers / payloads are allowed per step — match the prompt and the schema.

**"I want to add a new admin-controllable behavior knob."**
→ Add a column to `user_settings`, plumb it through `db.upsert_admin_user_context_fields()`, expose it in the `PATCH /v2/admin/users/<id>/context` body shape and the GET response, then read it inside whichever LLM-call path you want it to affect.

**"I want to add a new captured signal for RLHF."**
→ Add to `_emit_publish_event_if_signal()` calls in `record_snippet_publish_annotations()` ([services/db.py:5642](services/db.py:5642)). Pick a unique `field_name`. Make sure the SELECT pulls the underlying columns.

**"I want the bot to behave differently in a non-English language."**
→ Per the Phase 18.1 spec the answer is *currently* "no — English only with one-shot disclaimer." If reversing: undo Phase 18.1 (commit `87abb58`) and probably re-introduce a Polish/multi-language variant. RULE 1 in both `_INTERVIEW_SYSTEM_PROMPT` and `build_state_machine_system_prompt()` is the surface.

**"I want to inject custom instructions for ONE user."**
→ `user_settings.custom_llm_instructions` (Admin Tab 3). Set via `PATCH /v2/admin/users/<id>/context`. Read by `_augment_interview_prompt_with_profile` and `_augment_coaching_system_prompt`.

**"I want to force a specific question on a user's next interaction."**
→ `queued_override_question` (§5.1). Set via the same PATCH endpoint. Pops on first matching call.

**"I want a user to re-do the onboarding."**
→ `POST /v2/admin/users/<id>/reset-baseline` (§5.2).

---

## 8. Common pitfalls when changing prompts

1. **The `|||` delimiter is sacred.** Frontend splits on it to render multiple bubbles. If you remove the FORMATTING RULE from a prompt, the LLM will likely emit a single bubble and the UI looks wrong. If you add more `|||` segments, the frontend must be ready to render N bubbles (it currently does — but verify).

2. **The `[ADVANCE]` token in awareness prompts (skills) is stripped server-side.** It MUST be the last token on the LLM output. Anything after it is ignored. Adding new sections after it is dead.

3. **STATE_MACHINE_RESPONSE_SCHEMA is strict.** The state-machine prompt must produce JSON matching the schema. Adding new top-level fields requires schema updates first; the LLM cannot return shape the schema doesn't allow.

4. **`baseline_established` flips at turn 4 upload, NOT turn 5 next-question.** Old code flipped lazily on turn-5 question request. Current code flips eagerly on turn-4 answer upload (commit moved it to where it semantically belongs). When testing baseline behavior, the FLIP is the moment of truth, not the next request.

5. **Skill awareness prompts didn't get the English-only + identity rules in Phase 18.1.** Their `[ADVANCE]`-terminated single-shot format conflicts. If you want consistent persona behavior across all surfaces, redesign their output contract first.

6. **`user_language_hint` is accepted but ignored** in the state-machine prompt since Phase 18.1. The frontend can keep sending it; the prompt builder silently drops it. If you re-enable language mirroring, restore the `language_hint_line` injection at [services/coaching_state_machine.py:230](services/coaching_state_machine.py:230)-ish (deleted in commit `87abb58`).

7. **Augmentation order in `_generate_llm_question`** matters — few-shot examples come first, longitudinal context second, baseline summary third, etc. If you add a new block, decide where it should sit; later blocks get more attention from the model.

8. **The contextual `first-question` resolution order**: admin override → stored `follow_up_question` → dynamic LLM. Skip a layer and you skip everything below it. The admin override winning over the stored follow-up is by design — admin's most recent action is most explicit.

9. **`coaching_state_machine.py` infers the step from conversation history**, not from a column. If you replay the messages incorrectly (e.g. dropping a turn from the prior list when calling the LLM), the model will get confused about which step to emit. Order matters; completeness matters.

10. **Annotation capture is publish-time only.** Reviewing snippets without publishing means the (AI draft, admin final) pair never lands in `admin_annotation_events`. Either ship a backfill cron or maintain operational discipline of always publishing reviewed sessions.

---

## 9. Quick-reference: every system prompt at a glance

| Prompt | File | Function/Variable | Used by |
|---|---|---|---|
| Interview base | [routes/v2_routes.py:7547](routes/v2_routes.py:7547) | `_INTERVIEW_SYSTEM_PROMPT` | All `/v2/public/interview/next-question` LLM calls and the contextual `/v2/user/chat/first-question` dynamic path |
| Interview augmentation | [routes/v2_routes.py:8772](routes/v2_routes.py:8772) | `_augment_interview_prompt_with_profile()` | Wraps the interview base with `[COACHING CONTEXT]`, `[PERFORMANCE METRICS]` |
| Baseline objectives (turns 1-4) | [routes/v2_routes.py:11411](routes/v2_routes.py:11411) | `_BASELINE_TURN_OBJECTIVES` | Spliced as `[CURRENT_TURN_OBJECTIVE]` into the interview prompt for new users |
| Charisma awareness prompt | [services/skills/charisma.py:26](services/skills/charisma.py:26) | `_AWARENESS_PROMPT` | `/v2/coaching/turn` when intent=charisma; fallback for `/v2/user/chat/first-question` |
| Stress awareness prompt | [services/skills/stress.py:25](services/skills/stress.py:25) | `_AWARENESS_PROMPT` | `/v2/coaching/turn` when intent=stress; fallback for `/v2/user/chat/first-question` |
| Coaching turn augmentation | [routes/v2_routes.py:8932](routes/v2_routes.py:8932) | `_augment_coaching_system_prompt()` | Wraps the awareness prompt with `[USER LONG-TERM PROFILE]` |
| State-machine prompt | [services/coaching_state_machine.py:155](services/coaching_state_machine.py:155) | `build_state_machine_system_prompt()` | `/v2/coaching/state-machine/turn` |
| Coaching-outcome evaluator | [services/coaching_outcomes.py:300](services/coaching_outcomes.py:300) | `_llm_score_exchange` internal | Background scoring after a coaching attempt |
| Snippet draft generator (admin-facing AI drafts) | [services/snippet_drafts.py:191](services/snippet_drafts.py:191) (charisma) / [:210](services/snippet_drafts.py:210) (stress) | `_charisma_system_prompt()` / `_stress_system_prompt()` | Generates `ai_draft_admin_comment` and `ai_draft_follow_up_question` when admin labels a snippet |
| Follow-up question generator (admin labelling) | [routes/v2_routes.py](routes/v2_routes.py) | `_generate_snippet_follow_up_question()` | When admin saves a snippet without an explicit follow-up, this generates one from the type + transcript + admin_comment |

---

## 10. Conversational LLM call summary table

| Call site | Model | Temperature | max_tokens | Schema? |
|---|---|---|---|---|
| `_generate_llm_question` (interview / chat first-question) | gpt-4o-mini | default (~1.0) | not capped here | No |
| `v2_coaching_turn` (awareness loop) | gpt-4o-mini | 0.6 | 240 | `AWARENESS_TURN_SCHEMA` |
| `v2_coaching_state_machine_turn` | gpt-4o-mini | 0.7 | 600 | `STATE_MACHINE_RESPONSE_SCHEMA` |
| `_llm_score_exchange` (outcome evaluator) | gpt-4o-mini | low (deterministic) | bounded | Structured |
| AI-draft snippet generators | gpt-4o-mini | varies | bounded | Structured |

---

## 11. Recent architectural pivots — for context when reading old code

| Phase | Commit / approximate date | What changed |
|---|---|---|
| 12 | a few weeks back | Admin user context endpoint + queued override question machinery |
| 12.2 | `920a44c` | Wired the queued override into both interview and chat (was defined but never called) |
| 13 | earlier | Smart EBCP routing — returning users (`baseline_established=TRUE`) skipped scripted turns 1-4 |
| 13.1 | `eebd7e3` | Admin endpoint to reset baseline |
| 14 | `a398ef6` | PostSessionResultsEmail render+send pipeline (Vercel render endpoint, RFC 8058 unsubscribe) |
| 14.x | inline | Email fallback when render fails (commit `c613326`) |
| 14.2 | `f82b653` | Admin editable evaluator rationale + RLHF capture for the new field |
| 16 | several commits | Baseline summary digest computed at turn-4 upload, used by turn-5+ prompts |
| 17 | several commits | Master score (B6) block in `[PERFORMANCE METRICS]` |
| 18 (reverted) | brief window | Frontend owned turns 1-4 as hardcoded strings. Then reverted: backend owns turns with directed-freestyle objectives |
| 18.1 | `87abb58` | Persona pivot: English-only with one-shot disclaimer + identity pivot rule. Replaced the upstream language-mirroring rule on the state-machine prompt |
