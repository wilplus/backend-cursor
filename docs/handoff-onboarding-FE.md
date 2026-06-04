# FE Handoff — Onboarding: Dad-Joke Opener → Contract Capture

**From:** Backend · **To:** Frontend · **Date:** 2026-05-29
**Source spec:** "Implement Onboarding Flow — Dad Joke Opener + Pivot to Contract Question"
**Companion:** this doc covers the **FE-facing contract**. BE implementation tasks (BE-1…BE-8) live in the source spec.

---

## 0. Status & how to use this doc

> ⚠️ **Backend status: NOT YET IMPLEMENTED.** The onboarding endpoints below do not exist in the
> backend yet (greenfield — there is currently no `sessions` table, no onboarding routes, no joke
> table). **The contracts in §3 are the agreed interface.** FE can start building **now** against the
> mock fixtures in §8. When BE ships, paths/shapes will match this doc; if anything has to change,
> it goes through the "Open decisions" in §11 first.

What's FE-owned vs BE-owned:

| Concern | Owner |
|---|---|
| Chat UI, bubbles, timings, typing indicator, placeholders, keyboard handling | **FE** |
| Joke selection + rotation, LLM calls, tone, punchline, JSON parsing/fallback, telemetry | **BE** |
| The state machine value (`onboarding_step`) | **BE writes it, FE reads `next_step`** |
| The 3-attempt contract cap | **BE enforces + flags; FE caps defensively too** (see §6) |
| Seeding/rotating the 10 jokes | **BE** — FE must render jokes dynamically, **never hardcode them** |

---

## 1. The flow in 60 seconds

```
NEW USER
  ┌─────────────────────────────────────────────────────────────┐
  │ 1. Warning bubble  →  (1.2s)  →  joke setup bubble           │  ← FE timing
  │ 2. User guesses    →  joke-reply  →  punchline + PIVOT line   │  ← BE/LLM
  │ 3. User answers    →  contract-reply  →  loops until a        │
  │    contract (situation + timeframe) is captured              │  ← BE/LLM
  │ 4. contract_set    →  fade into main session view            │  ← FE
  └─────────────────────────────────────────────────────────────┘

RETURNING USER  → skip joke entirely → "You're back…" → straight to contract loop
JUMPED-TO-SUBSTANCE → user ignores joke & states their problem → skip punchline → contract loop
STRESSED → user is panicking/anxious → drop ALL playfulness → compassionate contract gathering
```

### State machine (`onboarding_step`)

```
joke_shown ──► joke_answered ──► pivot_received ──► contract_pending ──► contract_set
                                       │                  ▲   │
   (user jumped to substance) ─────────┘                  └───┘  (loop, max 3x)
```

**FE rule:** drive the UI off the response fields `next_step`, `user_jumped_to_substance`, and
`is_contract_set`. Do **not** hardcode the enum ordering — treat `next_step` as the source of truth
for "what screen/placeholder comes next."

---

## 2. Prerequisites

- **Base URL / env:** _CONFIRM with BE_ (same API host as the rest of the app). Endpoints are under `/api/onboarding/*`.
- **Auth:** these are **public** (end-user) endpoints — **no `X-Admin-Token`** (that header is admin-only on other routes). User identity travels in the request as `user_id`.
- **Identity:**
  - FE supplies a stable **`user_id`** (string) using the app's existing user/device identity. _CONFIRM the existing source with BE._
  - **`session_id`** is **created by the backend** on the first call (§3.1) and returned to FE. FE then **echoes it back on every subsequent call**. Persist it in URL state / session storage (per FE-4) so a refresh mid-onboarding resumes the same session.
- **Returning-user detection (FE-7) is BE-side** — based on whether `user_id` has prior sessions. FE does not decide this; it reads `skip_joke` from §3.1.
- **Content-Type:** `application/json` for all POSTs.

---

## 3. API contracts (build against these)

### 3.1 — Start onboarding (creates session, returns joke OR skip)

> **PROPOSED — confirm in §11 (#1).** This consolidates BE-2 (joke) + BE-3 (write joke_id) + FE-7
> (returning-user skip) into one call so FE makes a single request on mount. Recommended over the
> bare `GET /api/onboarding/joke` from the raw spec.

```
POST /api/onboarding/start
Content-Type: application/json

{ "user_id": "<string>" }
```

**Response — new user (200):**
```json
{
  "session_id": "9f1c…uuid",
  "skip_joke": false,
  "joke_id": "3a2b…uuid",
  "setup": "What do you call a bear with no teeth?",
  "punchline": "A gummy bear.",
  "emoji": "🐻",
  "onboarding_step": "joke_shown"
}
```

**Response — returning user, skip joke (200):**
```json
{
  "session_id": "9f1c…uuid",
  "skip_joke": true,
  "opener": "You're back. What are we working on this time?",
  "onboarding_step": "contract_pending"
}
```

FE behavior:
- `skip_joke: false` → run the joke screen (§5, FE-2). You receive `punchline` up front, but **do not render it** until after the user replies (BE delivers it inside `joke-reply`). It's in the payload only so BE can keep the GET pure; treat it as opaque.
- `skip_joke: true` → render `opener` as the first assistant bubble, set placeholder to `"Tell me what's coming up…"`, go straight to the contract loop (§3.3).

---

### 3.2 — Reply to the joke

```
POST /api/onboarding/joke-reply
Content-Type: application/json

{ "session_id": "<uuid>", "user_message": "<string>" }
```

**Response (200):**
```json
{
  "assistant_message": "A gummy bear. 🐻 Okok, nevermind. Let's focus on public speaking — how can I help you?",
  "user_jumped_to_substance": false,
  "emotional_state": "neutral",
  "next_step": "pivot_received"
}
```

Field notes:
- `assistant_message` — render verbatim as one assistant bubble. It already contains punchline + pivot (or, if the user jumped to substance, an acknowledgement + one follow-up). **The pivot line inside it is canonical — see §4.**
- `user_jumped_to_substance` (bool) —
  - `false` → normal path. Set placeholder to `"Tell me what's coming up…"`. Next user message goes to §3.3.
  - `true` → user skipped the joke and stated their problem. Skip any pivot animation; the next user message still goes to §3.3 (`next_step` will be `contract_pending`).
- `emotional_state` — `"neutral" | "stressed" | "playful"`. **PROPOSED addition — confirm §11 (#3).** The raw BE-6 spec didn't return this from joke-reply, but the critical stressed case can occur on the *first* message (e.g. "I'm panicking, my dad's funeral is tomorrow" as the joke "answer"). FE needs it here to drop playful visuals immediately (§7). If `stressed`, BE also suppresses the punchline inside `assistant_message`.
- `next_step` — `"pivot_received"` normally, `"contract_pending"` if `user_jumped_to_substance`.

---

### 3.3 — Reply to the pivot (the contract loop)

```
POST /api/onboarding/contract-reply
Content-Type: application/json

{ "session_id": "<uuid>", "user_message": "<string>" }
```

**Response (200):**
```json
{
  "assistant_message": "A board pitch in two weeks — high stakes. What's the one outcome you need from that room?",
  "is_contract_set": true,
  "extracted_situation": "board pitch",
  "extracted_timeframe": "in 2 weeks",
  "emotional_state": "neutral",
  "contract_force_accepted": false,
  "next_step": "contract_set"
}
```

Field notes:
- `is_contract_set` (bool) —
  - `true` → contract captured (stored BE-side as `sessions.contract_sentence`). `assistant_message` confirms it back + asks ONE opening follow-up. Transition to `contract_set` (§5, FE-6). **Pin the contract** somewhere visible (top strip / "you're working on: X"). Build the pinned string from `extracted_situation` + `extracted_timeframe` (fall back to the user's raw message if either is null).
  - `false` → not specific enough yet. `assistant_message` sharpens **one** missing element (event *or* timeframe). Keep input focused, loop back to this endpoint with the next reply.
- `extracted_situation` / `extracted_timeframe` — strings or `null`. Use for the pinned anchor.
- `emotional_state` — `"neutral" | "stressed" | "playful"`. See §7. Once `stressed` is seen, stay in the calm visual mode for the rest of onboarding.
- `contract_force_accepted` (bool) — **PROPOSED — confirm §11 (#2).** Set `true` by BE when the 3-attempt cap was hit and it accepted whatever the user said. When `true`, treat as `contract_set` regardless of `is_contract_set`. (FE should still cap defensively — see §6.)
- `next_step` — `"contract_set"` or `"contract_pending"`.

> **Scope boundary:** Onboarding ends at `contract_set` with the opening follow-up already in
> `assistant_message`. Actually serving questions from the `charisma_inducing_questions` pool (FE-6's
> "start serving questions") is the **session-1 question-bank ticket — OUT OF SCOPE here.** Don't
> fetch a question pool in this flow.

---

### Error shape (all endpoints)

Matches the repo convention (`{"error": "..."}` + HTTP status):

```json
{ "error": "session_not_found" }
```

| Status | Meaning | FE action |
|---|---|---|
| 400 | missing `session_id` / `user_message` | fix request; shouldn't happen in normal flow |
| 404 | `session_not_found` | session expired/lost — restart onboarding from §3.1 |
| 5xx / network | server or LLM failure | show the **fallback bubble** with the canonical pivot line (§4) and let the user continue; log it |

**Important:** Even on a 200, defensively handle a missing/empty `assistant_message` by rendering the
canonical pivot line. BE's JSON parser falls back to `{}` on a bad LLM response, so BE *should* always
substitute the pivot — but FE rendering the same fallback guarantees the user never sees a blank bubble.

---

## 4. Canonical strings (exact — character for character)

These are **not** to be paraphrased or regenerated by the LLM. Verify byte-for-byte.

**Warning line** (FE renders this as the very first bubble, before the joke setup):
```
⚠️ Attention: dad joke incoming. Laugh your ass off before we talk about the serious stuff.
```

**Pivot line** (returned inside `assistant_message`; verify it appears intact):
```
Okok, nevermind. Let's focus on public speaking — how can I help you?
```
- The dash is an **em dash `—` (U+2014)**, not a hyphen. The apostrophe in `Let's` is a straight `'` (U+0027).
- The pivot line **must never contain an emoji** (the joke punchline may). If `emotional_state == "stressed"`, the ⚠️ warning bubble is suppressed entirely (§7).

> **Product-name flag (confirm §11 #4):** the source spec names the product inconsistently
> ("Willab" vs "WillpowerLab"); the assistant is "Will". FE shows a "Will is here" indicator — confirm
> the exact display name before shipping copy.

---

## 5. Screen-by-screen FE spec (timings & placeholders)

All timings below are **FE-owned** (the API doesn't enforce them).

**FE-1 — Screen/route.** New chat view at `/onboarding` (flagged). Single thread, no sidebar, no header beyond a minimal "Will is here" indicator. **Mobile-first.**

**FE-2 — Show the joke (new users):**
1. On mount → `POST /api/onboarding/start` (§3.1), store `session_id`.
2. Render the **warning line** (§4) as bubble #1.
3. After **1.2s**, render `setup` as bubble #2.
4. Show input, focused, placeholder `"Take a guess…"`.

**FE-3 — User answers the joke:**
1. `POST /api/onboarding/joke-reply`.
2. Show typing indicator (3 dots) for a **minimum 800ms** even if the response is faster.
3. Render `assistant_message`.
4. `user_jumped_to_substance == false` → placeholder → `"Tell me what's coming up…"`.
5. `user_jumped_to_substance == true` → skip ahead, next reply → contract loop.

**FE-4 — Contract loop:**
1. `POST /api/onboarding/contract-reply`.
2. `is_contract_set == true` (or `contract_force_accepted == true`) → render message, go to `contract_set`, persist + pin the contract sentence.
3. `is_contract_set == false` → render the sharpening question, keep input focused, loop.
4. **Cap at 3 iterations** — see §6.

**FE-5 — Emotional state** → see §7.

**FE-6 — Transition to first session:** once `contract_set`, fade onboarding into the main session view (or persist the same thread). Keep the **contract sentence pinned** (top of chat / "you're working on: X" strip). _(Serving the question bank = separate ticket.)_

**FE-7 — Returning users:** handled by `skip_joke: true` in §3.1 — render `opener`, go straight to the contract loop.

**FE-8 — Mobile keyboard:** input must stay visible when the keyboard opens. **Test iOS Safari specifically** (known breakage point).

---

## 6. Edge cases & required FE behavior

| Case | Who handles tone | What FE must do |
|---|---|---|
| Very long joke answer | BE/LLM (pivots regardless) | Just send it; render the returned bubble. Don't try to engage the long text. |
| User types "no" / "skip" to the joke | BE/LLM (drops joke, pivots) | Nothing special — render `assistant_message`. |
| User ignores joke, states real problem | BE (`user_jumped_to_substance: true`) | Skip pivot animation, route next reply to contract loop. |
| **Distress** ("I'm panicking…", funeral, urgency) | BE (`emotional_state: "stressed"`) | **Critical.** Drop ALL playful visuals immediately (§7). |
| User writes in Polish (UI is English) | BE/LLM (responds in same language) | Nothing — render whatever language comes back. |
| LLM returns invalid JSON | BE (falls back to canonical pivot + logs) | Also render canonical pivot if `assistant_message` is empty (§3 error note). |
| Contract never gets specific | BE caps at 3 + `contract_force_accepted` | **Defensively cap at 3 contract-reply calls** even if BE didn't flag; after the 3rd, accept whatever they said and move on. |

---

## 7. Emotional-state contract (CRITICAL)

`emotional_state ∈ { "neutral", "stressed", "playful" }` is returned by **joke-reply (proposed)** and
**contract-reply**. The LLM owns the *verbal* tone shift via its prompt; **FE owns the *visual* tone shift:**

When `emotional_state == "stressed"` (now or any earlier turn — it's sticky for the session):
- **Remove the `⚠️`** from any future bubble (and never show the warning line again).
- Slow the typing indicator to a **minimum 1500ms** (vs 800ms default).
- Suppress any playful micro-animations. Be visually calm.

This is the single most important behavior to get right (per the spec's "critical to get right" note).
If you're unsure whether a state is sticky, **treat any `stressed` as sticky for the remainder of onboarding.**

---

## 8. Mock fixtures (build now, no backend needed)

Drop these into a mock layer keyed by endpoint + scenario so you can build the full flow before BE ships.

**`POST /api/onboarding/start` — new user**
```json
{ "session_id": "mock-sess-1", "skip_joke": false, "joke_id": "mock-joke-1",
  "setup": "What do you call a bear with no teeth?", "punchline": "A gummy bear.",
  "emoji": "🐻", "onboarding_step": "joke_shown" }
```

**`POST /api/onboarding/start` — returning user**
```json
{ "session_id": "mock-sess-2", "skip_joke": true,
  "opener": "You're back. What are we working on this time?", "onboarding_step": "contract_pending" }
```

**`POST /api/onboarding/joke-reply` — cheeky/correct guess**
```json
{ "assistant_message": "Ha — you've heard it. Okok, nevermind. Let's focus on public speaking — how can I help you?",
  "user_jumped_to_substance": false, "emotional_state": "playful", "next_step": "pivot_received" }
```

**`POST /api/onboarding/joke-reply` — wrong/terse ("idk")**
```json
{ "assistant_message": "A gummy bear. 🐻 Okok, nevermind. Let's focus on public speaking — how can I help you?",
  "user_jumped_to_substance": false, "emotional_state": "neutral", "next_step": "pivot_received" }
```

**`POST /api/onboarding/joke-reply` — jumped to substance**
```json
{ "assistant_message": "Sounds like a big keynote is on your mind. When is it — and how big is the room?",
  "user_jumped_to_substance": true, "emotional_state": "neutral", "next_step": "contract_pending" }
```

**`POST /api/onboarding/joke-reply` — distress on first message**
```json
{ "assistant_message": "I hear you — that's a lot to carry. Let's take it one step at a time. What's the situation you're facing?",
  "user_jumped_to_substance": true, "emotional_state": "stressed", "next_step": "contract_pending" }
```

**`POST /api/onboarding/contract-reply` — not specific yet**
```json
{ "assistant_message": "Got it — a pitch. When is it happening?",
  "is_contract_set": false, "extracted_situation": "pitch", "extracted_timeframe": null,
  "emotional_state": "neutral", "contract_force_accepted": false, "next_step": "contract_pending" }
```

**`POST /api/onboarding/contract-reply` — contract set**
```json
{ "assistant_message": "A board pitch in two weeks — high stakes. What's the one outcome you need from that room?",
  "is_contract_set": true, "extracted_situation": "board pitch", "extracted_timeframe": "in 2 weeks",
  "emotional_state": "neutral", "contract_force_accepted": false, "next_step": "contract_set" }
```

**`POST /api/onboarding/contract-reply` — 3rd attempt, force-accepted**
```json
{ "assistant_message": "Okay — let's work with that. What matters most to you about how it goes?",
  "is_contract_set": true, "extracted_situation": null, "extracted_timeframe": null,
  "emotional_state": "neutral", "contract_force_accepted": true, "next_step": "contract_set" }
```

---

## 9. Sequence diagrams

**A. Happy path (new user)**
```
FE  ── POST /start ───────────────────────────────► BE   (creates session, picks joke)
FE  ◄─ {session_id, setup, punchline, emoji} ──────
FE  render ⚠️ warning → (1.2s) → setup bubble
FE  ── POST /joke-reply {session_id, msg} ─────────► BE → LLM (gpt-4o-mini, JSON)
FE  ◄─ {assistant_message(punchline+PIVOT), jumped:false, next:pivot_received}
FE  ── POST /contract-reply {session_id, msg} ─────► BE → LLM
FE  ◄─ {is_contract_set:false, sharpen...}         (loop, ≤3)
FE  ── POST /contract-reply {session_id, msg} ─────► BE → LLM
FE  ◄─ {is_contract_set:true, situation, timeframe, next:contract_set}
FE  pin contract → fade into session view
```

**B. Jumped to substance** — same as A but `/joke-reply` returns `jumped:true` → skip pivot, go straight to `/contract-reply`.

**C. Returning user** — `/start` returns `skip_joke:true` + `opener` → straight to `/contract-reply` loop.

**D. Stressed** — any turn returns `emotional_state:"stressed"` → FE drops ⚠️, slows typing to 1500ms, calm visuals for the rest of the flow.

---

## 10. Acceptance criteria — ownership split

| # | Criterion (from spec) | Owner | FE responsibility |
|---|---|---|---|
| 1 | New user → joke <2s → answer → punchline+pivot → contract stored | FE+BE | Mount calls `/start` fast; render within budget |
| 2 | Joke rotates; no repeat unless all 10 used | **BE** | None — render dynamically, never cache/hardcode jokes |
| 3 | Cheeky / terse / distressed tone adapts | **BE** (tone) | Visual tone shift on `stressed` (§7) |
| 4 | Skip-joke user gets substance pivot immediately | BE+FE | Honor `user_jumped_to_substance` |
| 5 | Contract in `sessions.contract_sentence` + admin panel | BE (+separate admin ticket) | Pin contract in UI |
| 6 | All turns logged in `onboarding_events` | **BE** | None |
| 7 | iPhone Safari, no keyboard issues | **FE** | FE-8 |
| 8 | Pivot line exact, character-for-character | BE+FE | Verify §4 string renders intact |

---

## 11. Open decisions — need BE + FE sign-off before lock

1. **Session creation shape.** Recommend `POST /api/onboarding/start` (returns `session_id` + joke *or* skip opener) over the raw spec's `GET /api/onboarding/joke`. Folds in BE-3 (write joke_id) and FE-7 (skip). **Decision: adopt `POST /start`?**
2. **3-attempt cap location.** Recommend BE enforces it and returns `contract_force_accepted: true` (telemetry already lives BE-side). FE keeps a defensive cap too. **Decision: BE-enforced + flag?**
3. **`emotional_state` on `joke-reply`.** Not in raw BE-6, but the distress case can land on the first message. Recommend BE returns it from `joke-reply` too (and suppresses punchline when stressed). **Decision: add it?**
4. **Display name.** "Willab" vs "WillpowerLab" — which string does FE show in the "Will is here" indicator and any copy? **Decision: confirm exact name.**
5. **`user_id` source.** What's the canonical existing identity FE passes (auth id? anonymous device id?). **Decision: confirm.**
6. **Base URL / env + feature flag** for `/onboarding`. **Decision: confirm host + flag name.**

---

## 12. Out of scope (per spec) + FE Definition of Done

**Out of scope:** session-1 question-bank UI; admin panel for contract sentence; recording capture; voice-analysis pipeline. (All separate tickets.)

**FE is done when:**
- [ ] New user sees warning → joke (within budget) → answers → punchline+pivot → contract loop → `contract_set`, contract pinned.
- [ ] Returning user skips joke (`skip_joke`) and lands in the contract loop.
- [ ] Jumped-to-substance path skips the pivot.
- [ ] `stressed` → ⚠️ removed, typing slowed to 1500ms, calm visuals (sticky).
- [ ] Pivot line renders exactly (§4), em dash intact.
- [ ] Typing indicator ≥800ms (≥1500ms stressed); joke delay 1.2s.
- [ ] Contract cap at 3 honored; graceful accept after.
- [ ] iOS Safari keyboard verified.
- [ ] Empty/`5xx`/network → canonical pivot fallback, flow continues.
- [ ] Built against §8 mocks; swapped to live API once BE confirms §11.
