# willab — Design Decisions (Developer Reference)
**Audience:** the developer / coding agents implementing the commercial beta.
**Companion to:** `willab_user_story_beta.md` (Spec v1.1 — the source-of-truth user story). This doc is the **design-decisions consolidation** and folds in the **v1.2 deltas** (see §10). Where this doc and v1.1 differ, the v1.2 delta list is authoritative; everything else defers to the spec.
**Organization:** by component. Each section = purpose → locked decisions → states (where relevant) → code grounding → per-component deletions. Cross-cutting deletions and backend work are collected in §9 / §11.
**Two corrections folded in from review** (don't implement the older versions):
- **Status region is a linear, single-active model** — one official recording in flight at a time, `pending → delivered → back to launch`. *Not* a concurrent stack of session cards. This overrides Spec §5's concurrency DEFAULT.
- **The Lounge bot is a librarian, not a progress engine** — it retrieves and replays the coach's notes; it never computes or asserts "you're improving."

---

## 1. Foundations (type + bubble vocabulary) — *done, referenced here*
**Type roles used downstream** (actual scale lives in the Foundations work; these are the roles other components reference):
- **Display** — large hero numerals (e.g. the Readout's two hero features, 22px).
- **Heading** — section/attribution headers (e.g. "From your coach").
- **Body** — transcript, feature values, AI/coach commentary (the readable substance).
- **Meta** — labels, counters, scores, timestamps (the quiet scaffolding).

**Bubble vocabulary** — chat message "kinds" are an enumerated set. One kind is being **retired** this phase (`metrics`, see §9).

---

## 2. Intake (first-run interview — conversational, non-recording)
**Purpose:** first-run only. Capture the one-time **profile** — domain (metadata) + a specific goal in the user's own words. Conversational *framing*, structured *where it should be*. **No audio recorded.** Builds `inferred_learner_profile` / `baseline_summary`. Runs **once**; returning users skip straight to the Lounge.

**Turn structure (locked): exactly two questions, then the CTA to the Lounge.**
- **Q1 — domain: a selection, not a free chat turn.** Render the five **`DomainChips`** *inside* the chat thread as tappable options (not "type which domain interests you"). Conversational framing, structured input → you get the clean enum key, no parsing layer, one fast tap on mobile.
- **Q2 — goal: the genuinely open turn.** A single **free-text line** with a **domain-coupled placeholder** seeding it. **No goal chips** — the goal must be *in the user's own words* (it feeds the profile and gives the coach something real to read); goal chips would convert the one piece of genuine self-articulation into a second multiple-choice field.
- **Order is domain-then-goal** (not both at once) *specifically because* the goal placeholder couples to the chosen domain — the placeholder swaps to match the chip the user just tapped.

**`DomainChips` (flat chips; exactly five — bounded by Decisions 6 & 9, do not add or substitute):**
| Chip label | `domain` enum (metadata key — the contract) | Goal placeholder (free-text seed) | Vocabulary seed → `session_context.domain_vocabulary` default + Whisper prime |
|---|---|---|---|
| Public speaking | `public_speaking` | "I want to keep my nerve through the opening minute of a talk." | keynote, slide, audience, podium, Q&A, pacing |
| Sales | `sales` | "I want to sound steady when I get to pricing." | pipeline, objection, close, discovery call, pitch, quota |
| Executive presence | `executive_presence` | "I want to command the room in leadership updates." | board, stakeholder, all-hands, gravitas, brief, alignment |
| Customer service | `customer_service` | "I want to stay calm with an angry caller." | ticket, escalation, resolution, caller, SLA, de-escalate |
| Interview preparation | `interview_prep` | "I want to stop rushing my answers under pressure." | recruiter, behavioral question, STAR, panel, role, offer |

**`DomainChips` UI: flat chips, not description cards.** The recruited population (Toastmasters, sales training, MBA/exec programs, ICF coaches, interview-prep seekers) self-identifies its domain before opening the app; the five labels need no gloss. Cards would solve a comprehension problem you don't have and cost the fast single tap at the lowest-stakes moment in the flow. *Back-pocket fallback (don't build now):* if a tester ever stalls on a label, add one line of helper text under the chip row — never per-chip cards.

**Implementer notes**
- **Enum keys are the contract** — store the key, render the label, keep keys stable; the coach packet and `session_context` reference them.
- **Goal placeholder** is rotating example copy in the free-text field — it nudges articulation, it does not constrain the answer.
- **Vocabulary seed** is the editable default that lands in `session_context.domain_vocabulary` (§4) and primes Whisper; the user can edit it per recording.
- **None of this forks the flow.** Domain stays metadata (Spec §0): no branch in prompts, content, or KPI.

**Guardrails (personality must not overrun scope — this sits right next to the no-judgment spine):**
- **Bounded turns.** Exactly two questions, then the CTA. **Do not** let it become an open multi-turn steering interview — that is the charisma/stress onboarding interview you just deleted (§9). A chatty intake that drifts into "tell me more about your fears" quietly rebuilds the thing you cut.
- **No evaluation language.** It captures; it does not assess. "Got it — let's hear you," not "great choice, that's a tough skill."

**State:** `intake_in_progress` (§8) — non-recording.

---

## 3. Lounge (home hub)
**Purpose:** the always-mounted home surface. Off-task, calm, brand-toned. Everything launches from and returns to it.

**Locked decisions**
- **Always mounted.** The Lab opens as an overlay *over* the Lounge (§4); the Lounge instance and its live chat thread persist underneath and are restored on overlay close with **no remount**.
- **Open chat — text or speech**, user's choice, functionally identical, both **unmeasured**. Speech uses the **Web Speech API** (local, free); it is **not** the Whisper pipeline.
- **Mic ownership:** the Lounge speech input is **released/paused for the entire lifetime of the Lab overlay** so only the Lab's `MediaRecorder` holds `getUserMedia`; it resumes on overlay close.
- **Persistent "Start official recording" CTA** — always available, **never blocked** by an in-flight or parked session.
- **Optional warm-opener** — the repurposed former onboarding opener (light brand-tone first touch). Optional flavor only; **must never block or delay the launch CTA**; detached from the first-run path.
- **Status region pinned to the top** (§6).
- **The Lounge bot** — see §7 for its full context + the librarian guardrail.

**Persistence (BE handoff — see §11):**
- Signed-in: server-backed `lounge_messages` (survives reload + device switch).
- Unsigned: `localStorage`; **merges chronologically into the server thread on sign-up** (append, never overwrite).
- In-memory is ruled out.
- **Guardrail:** the thread feeds **only** the bot's conversational recall — never `inferred_learner_profile`, never cross-session analysis. Disclosed in first-run consent; user-deletable; never in the coach packet.

---

## 4. Lab (official recording — overlay + training zone)
**Purpose:** the high-stakes, on-task surface. The single official recording happens here. Visually and behaviorally distinct from the Lounge.

**Locked decisions**
- **Overlay, not a route.** Launched over the always-mounted Lounge; closing returns to the Lounge underneath with no remount. *(If an agent wires this as its own route, the hub model breaks — this is a STOP-and-check item.)*
- **Explicit "training zone" chrome.** Distinct from the Lounge: own header conveying official + not-yet-sent (e.g. **"Official recording · not yet sent"**), no casual Lounge affordances inside. The user always knows: in the Lab = on-task; in the Lounge = off-task.
- **Holds the mic** (`getUserMedia` → `MediaRecorder`) for its lifetime; Lounge speech input released (§3).

**Step A — `session_context` (per recording; 1 : many against the one-time profile)**
- **Topic** — *required* (feeds stickiness "topic coherence", Whisper vocabulary priming, prompt relevance, coach interpretability).
- **Audience** — optional.
- **Target length** — optional.
- **Domain vocabulary** — auto-derived from the profile domain via the **vocabulary seed in §2**; editable per recording.
- The profile **goal** shows as a read-only reminder.
- Friction target: near-zero — everything but topic is pre-filled/optional.
- **Do not** merge `session_context` into the one-time profile; **do not** cut it.

**Step B — pre-record → record → process**
- Pre-record: the prompt/task + high-stakes framing + a single large record control (distinct from the Lounge's small inline mic).
- **Min-content gate (salvaged from the removed onboarding completion gate):** reject recordings lacking speech or under the minimum duration. **Default: ≥60 s + has-speech.** Failing recordings → re-record prompt, never sent. This is a **content-validity gate only** — there is no charisma/stress contrast requirement.
- Process: progress state; **Whisper** (vocabulary-primed from `session_context`) → **ffmpeg** → **librosa** → segmentation → stickiness scoring + comment.

**Completion semantics (critical)**
- **Completion = Send to coach. The Readout is NOT the finish line.**
- **Park, don't discard, post-recording.** Diverging out of the Readout — including tapping "What do these mean?" — **parks** the session: the Lab minimizes to a **"Finish your recording → Send"** chip in the Lounge status region; the processed recording is **held and resumable**; re-entry restores the Readout at the Send step.
- **Discard rules:**
  - Mid-recording (`lab_recording`): discard-on-confirm (no artifact worth keeping).
  - Post-recording, pre-send (`lab_processing` → `readout` → `parked`): **explicit discard only**, plus the unsigned-session-end sweep.

**States introduced:** `lab_session_context`, `lab_prerecord`, `lab_recording`, `lab_processing`, **`parked`** (first-class post-recording state).

**Per-component deletions:** the onboarding **charisma/stress recording interview** and the **≥1-charisma / ≥1-stress / ≥60 s contrast completion gate** are removed; only the min-content check survives, relocated here.

---

## 5. Readout (the core payoff screen)
**Purpose:** "here's your voice as data." Neutral, factual, **non-interpretive** — it hands the verdict to the coach. This is the no-judgment promise in screen form.

**The two-stage story (frame the whole component around this)**
| Moment | Surface | Content | Tone |
|---|---|---|---|
| Right after recording | **Readout** (in the Lab overlay) | raw features + AI-stickiness + AI comment | neutral, factual |
| When analysis returns | **Insights** (in the Lounge, §6) | the **human coach's** notes + message, on the same data | personal, interpretive |

**Locked decisions**
- **Sequential reveal → summary list.** One snippet card at a time, tap-to-advance (a paced payoff, not a data dump), then a scrollable list of all cards to revisit.
- Lives inside the Lab overlay; closing **parks** (§4), it does not discard.

**Snippet card anatomy**

```
┌──────────────────────────────────────────┐
│ Snippet 2 of 5                    [▶ 0:08] │  Meta + SnippetPlayer (reused)
│ "…and that's when I realized the whole…"   │  transcript — Body
│                                            │
│   148 wpm            32% paused            │  2 HERO features — Display (22px)
│   speech rate        pause ratio           │  labels — Meta
│                                            │
│  PITCH        F0 mean 165 Hz · SD 28 Hz    │  3 grouped sections
│  PACE & PAUSE mean pause 0.4s · regular    │   label = Meta, value = Body
│  VOLUME/VOICE range 14 dB · voiced 71%     │
│   ▸ Show dynamics (F0 slope, envelope…)    │  progressive disclosure — 4 derived
│                                            │
│  ── Stickiness ──────────────────────────  │
│  "You stayed on one idea and built on it…" │  AI comment — Body (the main thing)
│  composite 0.72                            │  score — Meta, NEUTRAL (no red/green)
└──────────────────────────────────────────┘
   "Your personal baseline builds over your first
    few sessions; these are raw values."          baseline line — Meta
        ▸ What do these mean?  → opens Lounge, bot primed
   [ Send to my coach for analysis ]   persistent primary footer → send gate
```

**The locked specifics**
1. **Hero pair = speech rate + pause ratio** (Display). The two a non-expert feels immediately. **F0 mean stays in the grouped Pitch section, not a hero** — Hz is noise up top without a baseline.
2. **Grouped rest:** the other 8 features in 3 plain-language groups — **Pitch / Pace & Pauses / Volume & Voice**.
3. **"Show dynamics" expander** for the 4 abstract derived features (F0 slope, pause regularity, intensity-envelope shape, F0 mid-vs-end delta). Hierarchy is intentional: equal-for-the-classifier ≠ equal-for-a-human.
4. **Stickiness = comment-first, score-second, neutral-colored.** No good/bad, no red/green.
5. **Baseline line included** (flips Spec DEFAULT #4): *"Your personal baseline builds over your first few sessions; these are raw values."* It preempts the "is this good?" anxiety on the card.
6. **Science lives in the bot, not in tooltips.** A single **"What do these mean?"** link drops the user into the Lounge with the bot primed. **No inline per-feature explainers.** (Diverging here parks the session — §4.)
7. **Persistent send footer:** `Send to my coach for analysis`, always visible under the cards → send gate.

**Code grounding**
- **Reuse `SnippetPlayer`** for per-card playback.
- Type roles: **Display** = the 2 hero numbers; **Body** = transcript + comment + values; **Meta** = labels + score + baseline line.

**Per-component deletions:** retire the session-level **`AcousticMetricsBubble`** (wpm/pitch/flow/fillers/dynamic/energy as a chat bubble) and its **`metrics` bubble kind** — the Readout is per-snippet, richer, and a focused screen, not a chat bubble. (`SnippetPlayer` is kept.)

---

## 6. Status region + Insights view
**Purpose:** the Lounge's pinned top area — where the parked chip lives and where the coach's commentary lands.

### 6a. Status region — LINEAR single-active model
The loop is **linear: one official recording at a time.** `record → (Readout) → send → with coach → insights delivered → back to launch.` So the status region is **not** a stack of concurrent session cards. It shows, at most:

```
┌─ LOUNGE (status region pinned above chat) ─────────┐
│  [ ▶ Start official recording ]      always present │
│  ⚠ Best-man speech · recorded, not sent   Finish & send ›   (parked — if one exists)
│  🕓 Q3 update · with your coach                              (review_pending — transient)
│  ✨ Investor pitch · insights ready          Read ›          (insights_ready — transient)
│ ─────────────────────────────────────────────────── │
│  …continuous chat thread below…                      │
└──────────────────────────────────────────────────────┘
```

| State | Card (label = `session_context.topic` + state) | Action |
|---|---|---|
| `parked` | ⚠ "*[topic]* · recorded, not sent" | **Finish & send ›** → re-opens the Lab Readout (training chrome) at the Send step |
| `review_pending` | 🕓 "*[topic]* · with your coach" | none — passive, **no time estimate** |
| `insights_ready` | ✨ "*[topic]* · insights ready" (+ 💬 if a coach message exists) | **Read ›** → opens the Insights view |

**Locked behavior**
- `review_pending` and `insights_ready` are **transient states of the current session**, not items that accumulate. Once insights are **read**, the session's coach-annotated snippets **fold into the strong-sides library** (§7) and the status region returns to just the launch CTA. **Past sessions live in the library, not as a growing card stack here.**
- **`parked`** is the one state that persists across a divert, until the user sends or explicitly discards.
- **Empty state:** no cards — just the Start CTA + chat. The region is invisible until there's something to show.
- This **replaces** the earlier "read → archive list" and the ready/parked/pending/read ordering; with single-active, ordering is moot.

**Signal wiring (reuse existing infra):** the `pending → ready` flip is already wired — **`usePublishLiveSubscription`** (realtime) + **`useReviewingFetch`** (poll fallback), fired by the admin-publish event; email half = **`ResultsReadyEmail`**. **Re-point these from the retired `reviewing` phase at the status region.**

### 6b. Insights view — "commentary when it comes back"
Tapping **Read ›** **re-opens that session's Readout, now with the human layer added on the same data** (annotated Readout — confirmed reuse).

```
┌─ Insights · Investor pitch ───────── (Lounge chrome, read-only, CALM) ─┐
│  💬 From your coach                                                    │  overall coach message
│  "Strong open. Watch the drop-off when you hit numbers — let's…"        │   Heading + Body, human/warm
│ ─────────────────────────────────────────────────────────────────────│
│  Snippet 2 of 5   [▶]  "…and that's when I realized…"                   │  SAME Readout card,
│    148 wpm · 32% paused · pitch 165 Hz …                               │   raw data unchanged
│    AI stickiness: "stayed on one idea…"            (neutral, automated) │   automated layer
│    🧑 Coach: "this is your strongest 8 seconds — do more of this"        │   NEW human layer, attributed
└─────────────────────────────────────────────────────────────────────────┘
```

**Locked decisions**
- **Reuses the Readout cards** — transcript + raw features + AI-stickiness, untouched — and adds **two coach layers**: an **overall coach message** (top) and **per-snippet coach notes**. *(Both layers confirmed — per-snippet notes are the raw material for the library.)*
- **Two commentary layers, clearly attributed.** AI-stickiness comment stays **neutral/automated**; the **🧑 Coach** note is **warmer, human-attributed, visually distinct**. The user never confuses the app's read with the coach's read.
- **Read-only, Lounge chrome (calm)** — *not* the Lab's training chrome. A payoff to read, not a task to do.
- **In-app is canonical**; email is a nudge. Opening it flips the card out of `insights_ready`.
- **On read → ingest into the strong-sides library** (§7) — **tagged snippets only** (§14).
- **Overall coach message is optional — hide the "💬 From your coach" block entirely when empty.** The ≥1-tagged-note library floor (§14) already guarantees human presence in every published session; a mandated overall message would only produce filler that cheapens the warmth anchor. Per-snippet coach notes stand alone when there's no overall message.

---

## 7. Strong-sides library + Lounge bot context
**Purpose:** the user's growing, personal collection of *the coach's own notes* — and the bot's ability to hand it back on request. This is the in-scope feature; a progress engine is **not**.

**Locked decisions**
- **New persistent store (BE handoff — §11).** After each **delivered** session (on read), it ingests the **coach-annotated snippets**: snippet + raw data + the coach's note, tagged **strong / to-work-on**. It grows session over session.
- **Bot context = master science doc *+* this user's library.** The bot can retrieve and replay coach notes, surface strong/weak snippets, and offer to pull them up.
- **Librarian, not judge — hard guardrail.** The bot **retrieves and replays human-authored coach notes**. It **must not compute or assert trajectory, improvement, decline, or any cross-session synthesis.** "Are my strong moments here, in my coach's words?" = yes. "Am I improving?" = the bot does **not** answer with a computed verdict.
- **The bot's standing offer is invitational, not evaluative**, e.g.: *"Whenever you want to refresh your strong lines or work on the weaker ones, I'm here."* (register, not a mandated string)

**Why the guardrail exists (write it into the prompt + the doc):** surfacing the coach's past notes is replaying content the user already received — safe. Synthesizing "you're progressing" across sessions is the **post-PhD Learning Effectiveness System** and is explicitly out of scope this phase. The library is a **retriever of human-authored notes**, never a **judge of arc** — same no-judgment spine as the Readout, now at the bot layer. **STOP-and-check: do not let the librarian become a progress engine.**

**Existing bot guardrails still hold:** explains general science freely from the master doc; must not fabricate the user's result/score/T:C ratio; must not pre-empt the coach's read.

---

## 8. Full state model (single source of truth)
1. `welcome_consent` — first run only.
2. `intake_in_progress` — interview surface, first run only, **non-recording** (profile capture: domain + goal).
3. `lounge_idle` — home; optional warm-opener may greet.
4. `lab_session_context` — Lab overlay; per-recording context (topic required).
5. `lab_prerecord` — prompt shown, mic permission.
6. `lab_recording` — capturing audio.
7. `lab_processing` — Whisper/ffmpeg/librosa.
8. `readout` — snippets revealed; Send available.
9. **`parked`** — recorded, not sent; held + resumable; "Finish your recording" chip in Lounge.
10. `sendgate_unsigned` / `sendgate_signed`.
11. `review_pending` — with coach; passive; no time estimate.
12. `insights_ready` — email + in-app; optional coach message; **Read** opens annotated Readout.
13. `lounge_general` — open chat anytime; bot has master doc + library.

**Loop:** linear, one active recording at a time. On read, coached snippets → library, status returns to launch. `parked` persists across diverts until sent/discarded.

---

## 9. Master deletions / relocations list
**Delete**
- `AcousticMetricsBubble` component **+** the `metrics` bubble kind. *(Replaced by the per-snippet Readout cards. Keep `SnippetPlayer`.)*
- The onboarding **charisma/stress recording interview** and the **contrast completion gate** (≥1 charisma + ≥1 stress + ≥60 s). *(Salvage only the min-content check → Lab, §4.)*
- The **next-session icebreaker** AI auto-prefill + the session-2 first-question wiring (Task 10). *(BE columns may remain dormant. Concept repurposed as the coach-authored message, §6b.)*
- **`CasualVoiceConsentModal`** — premise gone: the Lounge's speech is local **Web Speech** (audio never leaves the browser), and the Lab's recording consent is covered by the first-run privacy disclosure (Spec §4.1) + the browser's own `getUserMedia` permission prompt. No separate "before audio leaves the browser" modal is needed.

**Relocate / repurpose (do NOT delete the asset)**
- Onboarding **opener** (`useOnboardingOpener`, `OpenerMicButton`, `/opener/*` BFF, `dad_jokes`): **detach from the first-run path**, re-mount as the **optional Lounge warm-opener** (§3). Must never gate the launch CTA.

**Retire (re-point, don't rip out the signals)**
- The old **`reviewing` phase**: re-point `usePublishLiveSubscription` + `useReviewingFetch` + `ResultsReadyEmail` at the **status region** (§6a).

---

## 10. Spec v1.1 → v1.2 delta (fold into the user story)
*(§-references below point to the **Spec** `willab_user_story_beta.md`, except where it says "this doc.")*
1. Spec §4.7 DEFAULT #4 + §8.4 → **baseline line included** (copy locked in this doc §5, item 5).
2. **Delete `AcousticMetricsBubble` + `metrics` bubble kind** (keep `SnippetPlayer`).
3. **Readout card anatomy** locked (this doc §5): hero pair, 3 groups, "Show dynamics" expander, comment-first neutral stickiness, "What do these mean?" → Lounge.
4. **Park-not-discard:** new first-class `parked` state; refine Spec §6.5/§6.6 (mid-recording = discard-on-confirm; post-recording pre-send = held/resumable, explicit-discard-only); "Finish your recording" chip.
5. **Lab "training zone" chrome** ("Official recording · not yet sent"; no Lounge affordances inside).
6. **Status region = linear single-active model** — overrides Spec §5 concurrency DEFAULT and §8.8; `review_pending`/`insights_ready` are transient states of the current session.
7. **Insights view = annotated Readout**, two attributed commentary layers (neutral AI + human Coach) + overall coach message.
8. **Strong-sides library** store + bot context expansion (master doc + library) + **librarian-not-judge** guardrail.
9. **Intake locked:** conversational, non-recording; chip-select domain (five `DomainChips`, enum keys) + free-text goal with domain-coupled placeholder; two-turn bounded; no goal chips; no evaluation language (this doc §2).
10. **`session_context`** as the per-recording intake (topic required), distinct from the one-time profile.
11. **Coach-authored message** surfaced in status/insights (no AI session-N+1 opener).
12. **`CasualVoiceConsentModal` deleted** — consent is covered by the first-run disclosure + the browser `getUserMedia` prompt; the Lounge's local Web Speech never leaves the browser (this doc §9).
13. **Welcome + consent (this doc §12)** — Spec §4.1 refined to one lightweight screen: recording/privacy disclosure naming **both** data paths (Lab may be sent to a coach; Lounge stored for continuity), accept-to-continue, `localStorage` `accepted` flag, shown once; **not** account creation.
14. **Send gate (this doc §13)** — Spec §4.8 refined: **park before redirect** (the parked recording is the hand-off token across OAuth); **merge-then-send** callback ordering (a: merge Lounge thread, b: send); **confirmation only on send success** (OAuth success ≠ send success); idempotent send; offline queue + retry; account-exists → log in → same merge-then-send; explicit `Back to Lounge` dismissal (no auto-teleport, no second send).
15. **Coach authoring (this doc §14)** — **direction-only** label (`threat/ambiguous/challenge`, `direction-v1`, schema-versioned + accept/override flags; migration-ready to the 28→12–16 scenario protocol); training/user **zone split** (label private, note+tag user-facing) with **no auto-derive** of the tag from the label; **new purpose-built** authoring surface (reuse components, not Tab 1); **overall message optional + hidden-when-empty**; **publish requires every snippet labeled + ≥1 tagged coach note** (human-presence floor); library ingest = **tagged-only**; segmentation **hard-capped to top-N (~10)/session**; **pseudonymized** review queue; capture a training-annotation event on publish, **no per-publish retrain**.

---

## 11. Backend handoffs (new work the original BE doesn't have)
- **`lounge_messages` store** — server-side per signed-in user; `localStorage` + merge-on-sign-up for unsigned; continuity-only, never profiled, deletable, never in coach packet.
- **Strong-sides library store** — ingests coach-annotated snippets (snippet + raw data + coach note, tagged strong / to-work-on) on each delivered session's read; read by the Lounge bot.
- **`session_context` record** — per Lab recording, 1 : many against the one-time profile; defaults inherited from profile (vocabulary from the §2 seed).
- **`profile` record** — one per user from intake: `domain` (enum) + free-text goal; produces `inferred_learner_profile` / `baseline_summary`.
- **Signal re-point** — `usePublishLiveSubscription` + `useReviewingFetch` + `ResultsReadyEmail` from the retired `reviewing` phase → the status region.
- **Coach-side authoring** — overall message + per-snippet notes per session (the admin/coach surface that produces the Insights payload — this doc §14).
- **Training-annotation / labels store** — per-snippet direction label (`direction-v1`: `threat/ambiguous/challenge`, schema-versioned, `was_pre_filled` / `was_overridden` flags) captured as an annotation event on publish; the beta's **only** classifier-training signal. **No per-publish retrain** (batched, out of scope). Migration-ready to the 28→12–16 scenario schema. Training-zone — **never** surfaces in Insights.
- **Publish gate** — Publish requires **every snippet labeled** AND **≥1 snippet with a coach note + tag** (the human-presence + library floor — a published session must carry at least one coach phrase, not just labels); overall message optional (soft warning, non-blocking).
- **Segmentation top-N cap** — the pipeline caps snippets per session to the **top-N (~10) most analyzable**, bounding coach labeling load (and therefore user insight latency) by design, not by after-the-fact alerting.
- **Pseudonymized review queue** — `review_pending` sessions listed by pseudonymous user ID; the coach sees full transcript + goal (necessarily), disclosed as *pseudonymized* in §12.
- **Send-gate callback ordering** — on the unsigned OAuth return, run **merge-then-send** in this exact order: (a) merge local Lounge thread → server (chronological append), (b) send the parked recording. Do not reorder.
- **Idempotency key on send** — server-side dedupe so a double OAuth callback or double-tap can't double-send (client guards the control + handler too).
- **Offline send-queue + retry** — if send fails / offline (either path), the recording stays `parked`, queued, auto-retried; never render "sent" until send succeeds.
- **"Confirmation only on send success" gate** — the sent-confirmation is reachable *only* on send success, never on auth success alone (OAuth success ≠ send success).

---

## 12. Welcome + consent (first-run — before Intake)
*(Flow-ordered before §2; appended here as §12 to keep §1–§11 numbering + cross-references stable.)*

**Purpose:** the very first screen, no account. Lightweight **recording/privacy consent**, **not** account creation. Shown once; then → Intake (§2).

**Locked decisions**
- **One screen, not a wizard.** Warm headline → 2–3 plain "what this does" lines → a short recording/privacy disclosure → one **Accept & continue** button → links to full Privacy / Terms.
- **Lightweight consent, not sign-up.** No email/password here — account creation is deferred to the Send gate (§13).
- **Disclosure names both data paths:** the **Lab** recording is captured and may be sent to a human coach (who reviews it under a **pseudonymous ID** — disclosed as *pseudonymized*, not anonymized, since the coach necessarily sees your recording + goal); the **Lounge** chat is stored for *your own* continuity (never used to judge you).
- **Persistence:** an `accepted` flag in `localStorage` (unsigned at this point); associates with the account on later sign-up. Shown once — returning users (flag set or account present) skip straight past it.

**Layout sketch**

```
┌─────────────────────────────────┐
│            willab                │  Heading
│  See how you actually sound,     │  Body
│  then get a real coach's read.   │
│                                  │
│  • Record a short speaking task  │  Body — what it does
│  • See the raw data of your voice│
│  • A human coach sends insights  │
│                                  │
│  We record your Lab task and may │  Meta — disclosure
│  send it to a coach. Your Lounge │
│  chats are saved just for you.   │
│                                  │
│   [ Accept & continue ]          │  primary
│   Privacy · Terms                │  Meta links
└─────────────────────────────────┘
```

**State:** `welcome_consent` (§8) — first run only. Supersedes any scattered first-run consent; `CasualVoiceConsentModal` is deleted (§9).

---

## 13. Send gate (Readout footer → coach handoff)
**Purpose:** the only sign-up gate in the whole flow. Entry = the Readout's persistent footer **`Send to my coach for analysis`** (§5). Branch on auth state. **There is no second send action** — landing on the Lounge afterward is a single dismissal tap, never a re-send.

### Path 1 — signed-in (instant)
1. Tap Send → control **disables immediately** (idempotency guard).
2. Send fires: Lab audio/transcript + features + stickiness + `profile` + this recording's `session_context`. **Never the Lounge thread** (AC-7).
3. **Success** → in-overlay confirmation: *"Your coach received your work and will analyze it. You'll get fresh insights by email — and here in your Lounge."* with a single **`Back to Lounge`** action.
4. Tap `Back to Lounge` → overlay closes → Lounge → session is `review_pending` (🕓 chip already showing).
5. **Offline / send fails:** recording stays **`parked`** + queued + auto-retry; copy *"will send when you're back online."* **Never show "sent."**

### Path 2 — unsigned (OAuth round-trip)
1. Tap Send → recording is **`parked`** (held on the Readout — this is the hand-off token across the redirect) → **redirect to the existing wired OAuth auth screen.**
2. The auth screen is **OAuth** and **already carries the "by signing up you agree to Terms + Privacy" disclosure** — no separate account-ToS surface.
3. User completes OAuth → **callback returns to the app.**
4. On callback, **in this exact order** (do not reorder):
   - **a. merge** the local Lounge thread → server (chronological append, never overwrite);
   - **b. send** the parked recording (same payload as Path 1; idempotency guard on the callback handler so a double callback can't double-send);
   - **c.** on send success → continue to step 5.
5. **Return target = back on the Readout** (where the user acted) → same confirmation as Path 1 → single **`Back to Lounge`** tap → Lounge → `review_pending`.
6. **Existing account** detected at OAuth → log in instead → run 4a–4c → step 5.

### Failure / abandon branches (both paths)
- **Bounce off the OAuth screen / abandon sign-up:** nothing is in flight during the redirect (we parked *before* redirecting), so the recording is still `parked` on the Readout with the Send button. Nothing lost.
- **Callback fires but send fails / offline at callback:** the account now exists, but the recording stays **`parked` + queued + retry**. Never render "sent" until the send actually succeeds.
- **Double callback / double-tap:** idempotency key dedupes server-side; control + handler guarded client-side. Can't double-send.

### The one trap (write it into the build)
The confirmation screen is reachable **only on send success — never on auth success alone.** OAuth succeeding does not mean the recording sent. Until send succeeds, the session is `parked`, not `review_pending`.

### States
`readout` → (`sendgate_unsigned` → OAuth → callback | `sendgate_signed`) → confirmation → `review_pending`. Any abandon/failure → `parked` (held, resumable).

### Code grounding
- Reuse the existing **OAuth auth screen** + its Terms/Privacy disclosure (no new ToS surface).
- Reuse the **`PendingSessionClaim`** post-auth handoff pattern for the merge-then-send on callback.
- `Back to Lounge` is an **explicit dismissal** (locked over auto-dismiss) so the user consciously lands on the Lounge with the `review_pending` chip visible, rather than being teleported.

---

## 14. Coach authoring (off-stage — produces the Insights payload)
*(Off-stage; the coach's **Publish** is what creates the user's `insights_ready`. Appended as §14 to keep numbering stable.)*

**Purpose:** the only human-in-the-loop surface. The coach receives the coach packet, labels each snippet for the classifier (private), authors the user-facing notes, and publishes. It is the *source* of everything §6b (Insights) and §7 (library) render.

**Scope guard:** this surface only — not A (§12) / B (§13). Reuse existing publish infra, do not rebuild it.

### Label schema — direction-only (v1), migration-ready
- **3-class direction label** per snippet: `threat | ambiguous | challenge`. This is the threat/challenge appraisal — **training zone, never user-visible** (AC-9).
- **Stored versioned, never a bare string:** `label: { schema_version: "direction-v1", value, labeled_at, labeled_by, was_pre_filled, was_overridden }`.
- **Migration boundary:** `direction-v1` is the beta schema; it must **augment, not replace,** the master-doc **28→12–16 scenario-anchored** protocol in a future commit. *(Resolves the prior OPEN flag → "direction-only for now, migration-ready.")*
- **Accept vs override is the signal:** `was_pre_filled` / `was_overridden` distinguish cheap accepts from high-value corrections — do not collapse them.

### Two zones — split-sink, never leak
| Zone | Fields | Destination |
|---|---|---|
| **Training** | direction label (+ accept/override flags) | classifier training store **only** — never the Insights view |
| **User** | coach note (free text) · strong/to-work-on tag | user (Insights) + library — never the classifier |

**Leak guard (non-negotiable):** the strong/to-work-on tag and the direction label are **independent axes**, and the tag is **never auto-derived or auto-suggested** from the label — an auto-suggest would turn the user-visible tag into a readable proxy for the private appraisal (a T:C leak). Coach guidance decorrelates **by example:** *"strong/to-work-on is celebrate-vs-improve — you can mark a **threat**-appraised moment **strong** (you handled a hard moment well) or a **challenge**-appraised one **to-work-on** (comfortable but sloppy)."*

### Cold-start vs steady-state
- **Cold start (current):** no trained classifier → **no pre-fill**; the coach labels from scratch (`was_pre_filled: false`).
- **Steady state:** classifier present → the snippet shows the mechanical verdict pre-filled; the coach **Accepts** (default) or **Overrides**. Gated on a classifier-active flag that **does not exist yet — do not invent it.** Introduce it only when the classifier lands.

### Review queue (one line / session)
- A list of `review_pending` sessions. Columns: **topic**, **pseudonymous user ID** (the coach sees full transcript + goal — necessarily; "pseudonymized," not "anonymized," §12), **sent-when**. Row → authoring view. No filters / bulk / dashboard.

### Authoring view
- **Reuses the Readout card** (one source of truth) on a **new, purpose-built surface** — *not* the old `users/[userId]` Tab 1, which carries the trinity / KPI-narrative chrome being deleted in §9. Reuse the **components** (Readout card, coaching-rationale card pattern), not the tab.
- Per snippet, two clearly demarcated zones:
  - **Training zone** (labeled "Training — not visible to user", with a divider): 3-button `threat / ambiguous / challenge` selector — pre-filled with Accept/Override **only if a classifier exists**.
  - **User zone:** coach note (optional) + strong/to-work-on toggle (optional).
- **Mandatory:** a **label** on every snippet (closed-loop training), **and at least one snippet with a coach note + tag** (the human-presence + library floor). **Selective:** note + tag on the remaining snippets.

### Publish
- **Enabled when (a) every snippet has a label, AND (b) at least one snippet carries a coach note + its strong/to-work-on tag** — the **human-presence + library floor**: a published session must contain at least one *phrase from the coach*, never just machine labels. The overall coach message stays **optional** — soft warning if empty, **never a block** (the ≥1-tagged-note floor already guarantees human presence, so a mandated overall message just yields filler).
- Fires the **existing** triggers (`usePublishLiveSubscription`, `ResultsReadyEmail`, user → `insights_ready`, library ingest) — re-pointed / built per the foundation — **plus NEW:** capture each label as a **training-annotation event**.
- **No per-publish retrain** — capture only; retraining is batched and out of scope.

### Library ingest
- On the user's **read**, only **strong/to-work-on-tagged** snippets enter the strong-sides library (the curated coaching collection). Label-only snippets are training data, **not** library — they carry no human note to replay.

### Coach-workload cap (build constraint, not a monitor)
- Segmentation **hard-caps per session to the top-N (~10) most analyzable snippets.** "Label every snippet to publish" × unbounded segmentation × **one solo coach** is the pipeline's real bottleneck — coach throughput gates *every* user's insight latency. Bound it **by design**, not by after-the-fact alerting.

**State:** drives `review_pending → insights_ready` (§8). Off-stage.
**BE handoffs added (§11):** training-annotation/labels store · publish gate (all-labeled **+ ≥1 tagged coach note**) · segmentation top-N cap · pseudonymized review queue.

---
*Locked decisions only. Open red-lines are exhausted across all surfaces — core loop + secondary, §1–§14. Anything not covered here defers to Spec v1.1 / v1.2.*
